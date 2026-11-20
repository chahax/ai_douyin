"""Upload diagnostics are bounded evidence and never a completion substitute."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.platform_adapter.publish_workflow as module
from src.platform_adapter.browser_session import Page as RemotePage
from src.platform_adapter.models import PublishRequest


class Clock:
    def __init__(self):
        self.seconds = 0.0

    def time(self):
        return self.seconds


class UploadPage:
    url = 'https://creator.douyin.com/creator-micro/content/upload'

    def __init__(self, clock, states, *, fail=None):
        self.clock, self.states, self.fail = clock, states, fail
        self.index, self.wait_count = 0, 0
        self.evaluations, self.screenshots = [], []

    @property
    def state(self):
        return self.states[min(self.index, len(self.states)-1)]

    def wait_for_timeout(self, ms):
        self.clock.seconds += ms/1000
        if self.wait_count:
            self.index += 1
        self.wait_count += 1

    def locator(self, selector):
        return SimpleNamespace(inner_text=lambda: self.state['body'],
            count=lambda: self.state.get('progress', 0) if "progress" in selector else self.state.get('loading', 0))

    def evaluate(self, script):
        self.evaluations.append(script)
        if self.fail == 'evaluate':
            raise RuntimeError('secret exception message must not be journaled')
        return {'visible_text': self.state['body'],
            'buttons': [{'text': '重新上传', 'disabled': False, 'aria_disabled': 'false'}],
            'progress': [{'text': '42%', 'aria_label': '上传进度', 'aria_valuenow': '42',
                'aria_valuemin': '0', 'aria_valuemax': '100', 'aria_valuetext': '42%', 'aria_busy': 'true'}]}

    def _cmd(self, action, **kwargs):
        assert action == 'screenshot'
        assert kwargs['full_page'] is False
        self.screenshots.append(kwargs['path'])
        if self.fail == 'screenshot':
            raise OSError('another secret exception message')
        Path(kwargs['path']).write_bytes(b'fixture-native-screenshot-bytes')
        return {'path': kwargs['path']}


def setup(tmp_path, monkeypatch, states, *, fail=None):
    clock = Clock()
    monkeypatch.setattr(module.time, 'time', clock.time)
    workflow = module.PublishWorkflow(SimpleNamespace())
    workflow._journal_path = tmp_path / 'original-publish.jsonl'
    return workflow, UploadPage(clock, states, fail=fail)


def events(workflow):
    return [json.loads(row) for row in workflow._journal_path.read_text(encoding='utf-8').splitlines()]


def test_changed_upload_state_and_timeout_save_ui_aria_screenshots_alongside_original_journal(tmp_path, monkeypatch):
    workflow, page = setup(tmp_path, monkeypatch, [
        {'body': '正在上传 42%', 'progress': 9, 'loading': 1},
        {'body': '视频预览已出现', 'progress': 1, 'loading': 0}])
    assert workflow._wait_for_upload_complete(page, timeout=6) is False
    recorded = events(workflow)
    assert [row['event'] for row in recorded] == ['state_changed', 'state_changed', 'timeout']
    assert len(page.screenshots) == 3
    for row in recorded:
        evidence_path = Path(row['evidence_path'])
        assert evidence_path.parent == workflow._journal_path.parent
        assert hashlib.sha256(evidence_path.read_bytes()).hexdigest() == row['evidence_sha256']
        value = json.loads(evidence_path.read_text(encoding='utf-8'))
        assert value['ui']['progress'][0]['aria_valuenow'] == '42'
        assert value['ui']['buttons'][0]['text'] == '重新上传'
        assert value['upload_completion_assessed_by_diagnostic'] is False
        assert hashlib.sha256(Path(value['screenshot']['path']).read_bytes()).hexdigest() == row['screenshot_sha256']
    assert recorded[-1]['stage'] == 'upload_ui_diagnostic'


def test_only_original_completion_marker_succeeds_even_if_preview_and_progress_look_complete(tmp_path, monkeypatch):
    workflow, page = setup(tmp_path, monkeypatch, [
        {'body': '视频预览已出现，填写作品描述', 'progress': 0, 'loading': 0},
        {'body': '上传完成', 'progress': 0, 'loading': 0}])
    assert workflow._wait_for_upload_complete(page, timeout=6) is True
    assert events(workflow)[-1]['event'] == 'success_marker'


def test_explicit_failure_marker_is_false_and_gets_terminal_evidence(tmp_path, monkeypatch):
    workflow, page = setup(tmp_path, monkeypatch, [{'body': '上传失败，请重试'}])
    assert workflow._wait_for_upload_complete(page, timeout=6) is False
    assert events(workflow)[-1]['event'] == 'failure_marker'
    assert len(page.screenshots) == 1


def test_diagnostics_have_five_change_budget_and_one_reserved_timeout_slot(tmp_path, monkeypatch):
    workflow, page = setup(tmp_path, monkeypatch,
        [{'body': f'正在上传 {i}%', 'progress': i+1, 'loading': i%2} for i in range(20)])
    assert workflow._wait_for_upload_complete(page, timeout=30) is False
    recorded = events(workflow)
    assert len(recorded) == len(page.evaluations) == len(page.screenshots) == 6
    assert [row['event'] for row in recorded].count('state_changed') == 5
    assert recorded[-1]['event'] == 'timeout'


@pytest.mark.parametrize('failure', ['evaluate', 'screenshot'])
def test_diagnostic_failure_never_allows_publication_or_leaks_exception_body(tmp_path, monkeypatch, failure):
    workflow, page = setup(tmp_path, monkeypatch, [{'body': '上传完成'}], fail=failure)
    assert workflow._wait_for_upload_complete(page, timeout=6) is False
    recorded = events(workflow)
    assert recorded[-1]['stage'] == 'upload_ui_diagnostic_failed'
    assert 'secret' not in workflow._journal_path.read_text(encoding='utf-8')
    assert 'submission_started' not in [row['stage'] for row in recorded]


def test_upload_failure_still_stops_before_form_declarations_or_submission_lock(tmp_path, monkeypatch):
    workflow, page = setup(tmp_path, monkeypatch, [{'body': '视频预览已出现', 'progress': 0}], fail='screenshot')
    workflow._open_upload_page = lambda: page
    workflow._upload_video_file = lambda *_: None
    forbidden = []
    for method in ('_fill_title', '_fill_description', '_require_ai_declaration', '_reserve_submission', '_click_publish'):
        setattr(workflow, method, lambda *_a, **_k: forbidden.append('unexpected publication step'))
    result = workflow._do_publish(PublishRequest('original.mp4', 'original'))
    assert result.status == 'upload_failed' and result.success is False
    assert forbidden == []
    assert workflow._submission_started is False


def test_remote_page_keeps_evaluate_and_screenshot_on_original_upload_tab(tmp_path):
    calls = []
    def command(action, **kwargs):
        calls.append((action, kwargs))
        if action == 'evaluate':
            return {'value': {'visible_text': '正在上传', 'buttons': [], 'progress': []}}
        assert action == 'screenshot'
        Path(kwargs['path']).write_bytes(b'native-screenshot-fixture')
        return {'path': kwargs['path']}
    session = SimpleNamespace(cmd=command)
    page = RemotePage(session, tab_id='original-upload-tab')
    workflow = module.PublishWorkflow(session)
    workflow._journal_path = tmp_path / 'original.jsonl'
    assert workflow._capture_upload_diagnostic(page, event='state_changed', status='progress:1')
    assert [action for action, _ in calls] == ['evaluate', 'screenshot']
    assert all(kwargs['tab_id'] == 'original-upload-tab' for _, kwargs in calls)
    script = calls[0][1]['js']
    assert all(forbidden not in script for forbidden in ('localStorage', 'sessionStorage', 'document.cookie', 'fetch(', 'XMLHttpRequest', '.value', 'videoWidth', 'currentTime'))
    assert 'NodeFilter.SHOW_TEXT' in script and 'getComputedStyle' in script
    assert "getAttribute('aria-valuenow')" in script


def test_ui_evidence_serialization_is_bounded_even_for_oversized_transport_result(tmp_path, monkeypatch):
    workflow, page = setup(tmp_path, monkeypatch, [{'body': '正在上传'}])
    page.evaluate = lambda _: {'visible_text': 'x'*20000,
        'buttons': [{'text': 'b'*500, 'unexpected': 'not persisted'} for _ in range(100)],
        'progress': [{'aria_valuenow': '1'*500} for _ in range(100)],
        'unexpected': 'not persisted'}
    assert workflow._capture_upload_diagnostic(page, event='state_changed', status='progress:1')
    value = json.loads(Path(events(workflow)[0]['evidence_path']).read_text(encoding='utf-8'))
    assert len(value['ui']['visible_text']) == 12000
    assert len(value['ui']['buttons']) == 40
    assert len(value['ui']['progress']) == 24
    assert 'unexpected' not in json.dumps(value)


def test_existing_diagnostic_files_are_not_overwritten(tmp_path, monkeypatch):
    workflow, page = setup(tmp_path, monkeypatch, [{'body': '上传完成'}])
    target = tmp_path / 'original-publish.upload-01-state_changed.png'
    target.write_bytes(b'original')
    assert workflow._wait_for_upload_complete(page, timeout=6) is False
    assert target.read_bytes() == b'original'
    assert page.evaluations == [] and page.screenshots == []
    assert events(workflow)[-1]['error_type'] == 'FileExistsError'


def test_public_readonly_surface_capture_needs_no_publish_journal_or_upload(tmp_path):
    from src.platform_adapter.upload_surface_diagnostic import capture_upload_surface
    page = UploadPage(Clock(), [{'body': '上传视频 选择文件', 'progress': 0}])
    result = capture_upload_surface(page, tmp_path / 'inspection')
    assert result['ui']['visible_text'] == '上传视频 选择文件'
    assert result['upload_completion_assessed_by_diagnostic'] is False
    assert sorted(path.name for path in (tmp_path / 'inspection').iterdir()) == ['surface.json', 'surface.png']
    assert page.wait_count == 0
    assert len(page.evaluations) == len(page.screenshots) == 1
    assert hashlib.sha256(Path(result['evidence']['path']).read_bytes()).hexdigest() == result['evidence']['sha256']


def test_public_surface_capture_rejects_outside_project_before_any_browser_command(tmp_path, monkeypatch):
    from src.platform_adapter import upload_surface_diagnostic as helper
    monkeypatch.setattr(helper, 'WORKSPACE_ROOT', tmp_path / 'project')
    page = UploadPage(Clock(), [{'body': '选择文件'}])
    with pytest.raises(ValueError, match='inside the project'):
        helper.capture_upload_surface(page, tmp_path / 'outside')
    assert page.evaluations == [] and page.screenshots == []
    assert not (tmp_path / 'outside').exists()


@pytest.mark.parametrize('name', ['../surface', 'a/b', 'x'*181])
def test_public_surface_capture_requires_local_bounded_artifact_name(tmp_path, name):
    from src.platform_adapter.upload_surface_diagnostic import capture_upload_surface
    page = UploadPage(Clock(), [{'body': '选择文件'}])
    with pytest.raises(ValueError, match='basename'):
        capture_upload_surface(page, tmp_path / 'inspection', artifact_name=name)
    assert page.evaluations == [] and page.screenshots == []
