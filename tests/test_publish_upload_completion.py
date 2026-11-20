"""Completion requires this selection, observed transport, and stable rendered proof."""
import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

import src.platform_adapter.publish_workflow as module
from src.platform_adapter.models import PublishRequest


def proof(**changes):
    value = dict(schema='upload_completion_probe/v1', truncated=False,
        transfer_bytes=False, cancel_upload=False, transferring=False, checking=False,
        failed=False, clean=False, reupload_usable=False)
    value.update(changes)
    return value


TRANSFER = proof(transfer_bytes=True, cancel_upload=True, transferring=True)
READY = proof(clean=True, reupload_usable=True)


class Surface:
    url = module.UPLOAD_URL

    def __init__(self, states):
        self.states, self.index, self.seconds = states, 0, 0
        self.probes, self.selected = [], []

    def locator(self, selector):
        value = self.states[min(self.index, len(self.states)-1)]
        return SimpleNamespace(inner_text=lambda: value.get('body', '') if isinstance(value, dict) else '',
            count=lambda: 0, first=lambda: SimpleNamespace(set_input_files=self.selected.append))

    def evaluate(self, script):
        assert 'publish-upload-completion-probe/v1' in script
        value = self.states[min(self.index, len(self.states)-1)]
        self.probes.append(value)
        if isinstance(value, Exception):
            raise value
        return value

    def wait_for_timeout(self, ms):
        self.seconds += ms/1000
        self.index += 1


def setup(tmp_path, monkeypatch, states, *, selected=True, capture_ok=True):
    page = Surface(states)
    monkeypatch.setattr(module.time, 'time', lambda: page.seconds)
    workflow = module.PublishWorkflow(SimpleNamespace())
    workflow._journal_path = tmp_path/'attempt.jsonl'
    captures = []
    workflow._capture_upload_diagnostic = lambda *_a, **kw: captures.append(kw) or capture_ok
    if selected:
        workflow._upload_video_file(page, 'fixture.mp4')
        workflow._record('file_selected')
    return workflow, page, captures


def rows(workflow):
    return [json.loads(line) for line in workflow._journal_path.read_text(encoding='utf8').splitlines()]


def test_transfer_checking_then_two_clean_observations_bind_original_selection(tmp_path, monkeypatch):
    w, p, captures = setup(tmp_path, monkeypatch,
        [TRANSFER, proof(checking=True, reupload_usable=True), READY, READY])
    assert w._wait_for_upload_complete(p, timeout=10) is True
    verified = rows(w)[-1]
    assert verified['stage'] == 'upload_completion_verified'
    assert verified['selection_journal'] == str(w._journal_path)
    assert verified['file_selection_stage'] == 'file_selected'
    assert verified['transfer']['transfer_bytes'] and verified['transfer']['cancel_upload']
    assert [v['elapsed_seconds'] for v in verified['stable_observations']] == [4, 6]
    assert captures[-1]['event'] == 'compound_success' and captures[-1]['terminal']
    assert p.selected == ['fixture.mp4']


@pytest.mark.parametrize('states', [
    [READY],  # Stale already-complete surface has no transfer from this attempt.
    [proof(transfer_bytes=True), READY],  # Bytes alone are not the specified transport witness.
    [proof(cancel_upload=True), READY],
    [TRANSFER, proof(clean=False, reupload_usable=True)],  # Hidden result / preview alone.
    [TRANSFER, proof(clean=True)],  # Missing, disabled or occluded interactive reupload.
    [TRANSFER, proof(clean=True, reupload_usable=True, checking=True)],
    [TRANSFER, proof(clean=True, reupload_usable=True, transferring=True)],
    [TRANSFER, proof(clean=True, reupload_usable=True, cancel_upload=True, transferring=True)],
    [TRANSFER, proof(clean=True, reupload_usable=True, truncated=True)],
])
def test_incomplete_unknown_or_in_progress_surface_cannot_pass(tmp_path, monkeypatch, states):
    w, p, _ = setup(tmp_path, monkeypatch, states)
    assert w._wait_for_upload_complete(p, timeout=6) is False
    assert not any(r['stage'] == 'upload_completion_verified' for r in rows(w))


@pytest.mark.parametrize('binding', ['no_selection', 'other_page', 'other_journal'])
def test_complete_transition_without_same_page_same_attempt_selection_cannot_pass(tmp_path, monkeypatch, binding):
    w, p, _ = setup(tmp_path, monkeypatch, [TRANSFER, READY], selected=binding!='no_selection')
    if binding == 'other_page':
        w._upload_selection = (object(), w._journal_path)
    if binding == 'other_journal':
        w._upload_selection = (p, tmp_path/'previous.jsonl')
    assert w._wait_for_upload_complete(p, timeout=6) is False
    assert p.probes == []


def test_lost_clean_state_resets_consecutive_count(tmp_path, monkeypatch):
    w, p, _ = setup(tmp_path, monkeypatch,
        [TRANSFER, READY, proof(checking=True), READY, READY])
    assert w._wait_for_upload_complete(p, timeout=10) is True
    assert [x['elapsed_seconds'] for x in rows(w)[-1]['stable_observations']] == [6, 8]


def test_single_ready_after_broken_stability_is_not_enough(tmp_path, monkeypatch):
    w, p, captures = setup(tmp_path, monkeypatch,
        [TRANSFER, READY, proof(checking=True), READY])
    assert w._wait_for_upload_complete(p, timeout=8) is False
    assert captures[-1]['event'] == 'timeout'


def test_failure_takes_priority_over_clean_and_success_marker(tmp_path, monkeypatch):
    w, p, captures = setup(tmp_path, monkeypatch, [TRANSFER,
        proof(clean=True, reupload_usable=True, failed=True, body='上传失败 上传完成')])
    assert w._wait_for_upload_complete(p, timeout=8) is False
    assert captures[-1]['event'] == 'failure_marker'
    assert not any(r['stage'] == 'upload_completion_verified' for r in rows(w))


@pytest.mark.parametrize('bad', [{}, proof(clean=1), RuntimeError('private transport error')])
def test_probe_unknown_or_failure_never_passes_and_does_not_log_sensitive_error(tmp_path, monkeypatch, bad):
    w, p, _ = setup(tmp_path, monkeypatch, [TRANSFER, bad])
    assert w._wait_for_upload_complete(p, timeout=8) is False
    assert rows(w)[-1]['stage'] == 'upload_completion_probe_failed'
    assert 'private transport' not in w._journal_path.read_text(encoding='utf8')


def test_terminal_diagnostic_failure_blocks_compound_success(tmp_path, monkeypatch):
    w, p, captures = setup(tmp_path, monkeypatch, [TRANSFER, READY, READY])
    w._capture_upload_diagnostic = lambda *_a, **kw: captures.append(kw) or kw['event']!='compound_success'
    assert w._wait_for_upload_complete(p, timeout=8) is False
    assert captures[-1]['event'] == 'compound_success'
    assert not any(r['stage'] == 'upload_completion_verified' for r in rows(w))


def test_real_do_publish_selects_before_wait_and_never_advances_on_unconfirmed_upload(tmp_path, monkeypatch):
    w, p, _ = setup(tmp_path, monkeypatch, [READY], selected=False)
    w._open_upload_page = lambda: p
    observed = []
    def wait(page, **_):
        assert w._upload_selection == (page, w._journal_path)
        assert rows(w)[-2]['stage'] == 'file_selected'
        observed.append('wait')
        return False
    w._wait_for_upload_complete = wait
    for name in ('_fill_title', '_fill_description', '_require_ai_declaration', '_reserve_submission', '_click_publish'):
        setattr(w, name, lambda *_a, **_kw: pytest.fail('must stop before form or submission'))
    result = w._do_publish(PublishRequest('fixture.mp4', 'fixture'))
    assert result.status == 'upload_failed' and not result.success
    assert '未确认' in result.message and '网络' not in result.message
    assert observed == ['wait'] and p.selected == ['fixture.mp4']


def test_failed_file_selection_cannot_reuse_previous_attempt_binding(tmp_path, monkeypatch):
    w, p, _ = setup(tmp_path, monkeypatch, [READY])
    w._open_upload_page = lambda: p
    def fail(*_):
        raise OSError('selection failed')
    w._upload_video_file = fail
    with pytest.raises(OSError):
        w._do_publish(PublishRequest('fixture.mp4', 'fixture'))
    assert w._upload_selection is None


@pytest.mark.parametrize('status,expected_transferring', [
    ('', False),
    ('正在上传', True),
    ('上传中64%', True),
    ('上传处理中...', True),
])
def test_actual_probe_js_distinguishes_fixed_footer_from_independent_live_status(status, expected_transferring):
    """Execute the production read-only JS against a small rendered-DOM fixture."""
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is required for the offline DOM probe fixture')
    footer = '点击发布后，如作品还在上传中，请勿关闭页面，等待上传发布完成。'
    class NodeSurface:
        def evaluate(self, script):
            texts = ['作品未见异常', '重新上传', footer] + ([status] if status else [])
            fixture = r'''
const texts=TEXTS;
global.innerWidth=1200;global.innerHeight=800;global.NodeFilter={SHOW_TEXT:4};
const body={parentElement:null,hidden:false,disabled:false,getAttribute:()=>null,hasAttribute:()=>false};
const els=texts.map((text,i)=>({tagName:'DIV',parentElement:body,hidden:false,disabled:false,
  innerText:text,tabIndex:-1,closest:()=>null,getClientRects:()=>[{}],
  getAttribute:n=>n==='role'&&text==='重新上传'?'button':null,hasAttribute:()=>false,
  getBoundingClientRect:()=>({left:0,top:i*40,right:200,bottom:i*40+20}),
  contains(other){return other===this;}}));
global.getComputedStyle=el=>({display:'block',visibility:'visible',opacity:'1',pointerEvents:'auto',cursor:'auto'});
global.document={body,elementFromPoint:(x,y)=>els[Math.floor(y/40)],
  createTreeWalker:()=>{let i=0;return {nextNode:()=>i<els.length?{parentElement:els[i],textContent:texts[i++]}:null};}};
console.log(JSON.stringify((PROBE)()));
'''.replace('TEXTS', json.dumps(texts, ensure_ascii=False)).replace('PROBE', script)
            completed = subprocess.run([node, '-e', fixture], capture_output=True, text=True,
                encoding='utf8', timeout=5, check=True)
            return json.loads(completed.stdout)
    observed = module.PublishWorkflow._probe_upload_completion(NodeSurface())
    assert observed['clean'] and observed['reupload_usable']
    assert observed['transferring'] is expected_transferring
