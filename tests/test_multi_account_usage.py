import json
from datetime import datetime, timezone

import pytest
from src.services.seedance_usage_service import summarize_seedance_usage
from src.services.artifact_account import artifact_account
from src.services import database
from src.services.video_service import save_video, get_videos, count_videos
from src.platform_adapter.models import VideoItem, VideoStatus


def report(path, owner, task, seconds=5):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'schema': 'seedance_generation_report/v1', 'provider': 'ark_api',
        'account_uuid': owner, 'account_key': owner, 'request': {},
        'final': {'id': task, 'status': 'succeeded', 'duration': seconds,
                  'updated_at': datetime.now(timezone.utc).timestamp(), 'usage': {'completion_tokens': 100}}}), encoding='utf-8')


def test_single_account_and_all_totals_reconcile(tmp_path):
    folder = tmp_path / 'data/reports'
    report(folder/'a.seedance.json', 'A', 'task-a')
    report(folder/'a-copy.seedance.json', 'A', 'task-a')
    report(folder/'b.seedance.json', 'B', 'task-b', 7)
    report(folder/'unknown.seedance.json', '', 'task-unknown', 3)
    all_usage = summarize_seedance_usage(folder, provider='ark_api', project_root=tmp_path)
    a = summarize_seedance_usage(folder, provider='ark_api', project_root=tmp_path, account_uuid='A')
    unknown = summarize_seedance_usage(folder, provider='ark_api', project_root=tmp_path, account_uuid='')
    assert all_usage['summary']['report_count'] == 3
    assert all_usage['summary']['generated_seconds'] == 15
    assert a['summary']['generated_seconds'] == 5
    assert unknown['summary']['generated_seconds'] == 3
    assert sum(r['generated_seconds'] for r in all_usage['account_totals']) == 15
    assert all(r['estimated_cost_usd'] is None for r in all_usage['account_totals'])


def test_provenance_conflict_and_missing_never_adopt_current_account(tmp_path):
    source = tmp_path/'data/script.json'
    source.parent.mkdir()
    source.write_text(json.dumps({'account_uuid': 'B'}))
    assert artifact_account({'account_uuid': 'A', 'source_script': str(source)}, tmp_path)['account_conflict']
    assert artifact_account({}, tmp_path)['account_uuid'] == ''


def test_duplicate_task_with_conflicting_owners_is_unassigned(tmp_path):
    folder = tmp_path/'data/reports'
    report(folder/'a.seedance.json', 'A', 'same-task')
    report(folder/'b.seedance.json', 'B', 'same-task')
    usage = summarize_seedance_usage(folder, provider='ark_api', project_root=tmp_path)
    assert usage['summary']['report_count'] == 1
    assert usage['tasks'][0]['account_uuid'] == ''
    assert usage['tasks'][0]['account_conflict']


def test_save_rejects_cross_account_ownership(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DB_PATH', tmp_path/'video.db')
    save_video(VideoItem(video_id='same-id', title='A', account_uuid='A'))
    with pytest.raises(ValueError, match='归属冲突'):
        save_video(VideoItem(video_id='same-id', title='B', account_uuid='B'))
    assert get_videos(account_uuid='A')[0]['title'] == 'A'
    assert get_videos(account_uuid='B') == []
    assert count_videos(account_uuid='') == 0
    assert count_videos() == 1


def test_same_title_does_not_claim_multiple_drafts(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DB_PATH', tmp_path/'video.db')
    for local in ('draft-1', 'draft-2'):
        save_video(VideoItem(local_id=local, title='相同标题', status=VideoStatus.PENDING, account_uuid='A'))
    save_video(VideoItem(video_id='published', title='相同标题', status=VideoStatus.PUBLISHED, account_uuid='A'))
    assert count_videos(status='pending_review', account_uuid='A') == 2
    assert count_videos(status='published', account_uuid='A') == 1


def test_frozen_job_rejects_changed_binding(monkeypatch):
    from types import SimpleNamespace
    import src.operations_accounts.task_scope as scope
    profile = SimpleNamespace(account_uuid='A', status='active', profile_version=1)
    binding = SimpleNamespace(platform_identity_key='douyin:original')
    monkeypatch.setattr(scope, 'AccountProfileRepository', lambda: SimpleNamespace(db_path='unused', get=lambda key: profile))
    monkeypatch.setattr(scope, 'AccountBindingRepository', lambda path: SimpleNamespace(get_optional=lambda key: binding))
    frozen = scope.freeze_task_scope({'account_key': 'a', 'title': '内容'})
    assert scope.validate_task_scope(frozen) == {'account_key': 'a', 'title': '内容'}
    binding.platform_identity_key = 'douyin:other'
    with pytest.raises(ValueError, match='变化'):
        scope.validate_task_scope(frozen)
    with pytest.raises(ValueError, match='快照'):
        scope.validate_task_scope({'account_key': 'a'})


def test_usage_page_switches_single_and_all(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from streamlit.testing.v1 import AppTest
    from src.shared.config import settings
    import src.operations_accounts as accounts
    folder = tmp_path/'data/reports'
    report(folder/'a.seedance.json', 'A', 'a', 5)
    report(folder/'b.seedance.json', 'B', 'b', 7)
    monkeypatch.setattr(settings, 'SEEDANCE_USAGE_REPORT_DIR', str(folder))
    monkeypatch.setattr(accounts, 'AccountProfileRepository', lambda: SimpleNamespace(list_active=lambda **kwargs:
        [SimpleNamespace(account_uuid=k, account_key=k, display_name=k) for k in ('A','B')]))
    app = AppTest.from_string("from src.shared.config import settings\nsettings.SEEDANCE_PROVIDER='ark_api'\nfrom src.web.seedance_dashboard import page_seedance_usage\npage_seedance_usage()").run(timeout=30)
    assert not app.exception
    assert next(m for m in app.metric if m.label == '本月接口生成成功').value == '2'

    app.selectbox(key='usage_account_scope').set_value('A').run()
    assert not app.exception
    assert next(m for m in app.metric if m.label == '本月接口生成成功').value == '1'
    app.selectbox(key='usage_account_scope').set_value('*').run()
    assert next(m for m in app.metric if m.label == '本月接口生成成功').value == '2'


def test_publish_rejects_mismatched_artifact_even_if_request_matches(monkeypatch):
    from types import SimpleNamespace
    from src.platform_adapter.douyin_adapter import DouyinAdapter
    from src.platform_adapter.models import PublishRequest
    import src.services.artifact_account as ownership
    monkeypatch.setattr(ownership, 'artifact_account', lambda *args: {'account_uuid': 'A'})
    adapter = object.__new__(DouyinAdapter)
    adapter.runtime_context = SimpleNamespace(account_uuid='B')
    result = adapter.publish_video(PublishRequest(video_path='data/test.mp4', title='test', extra_metadata={'account_uuid': 'B'}))
    assert not result.success
    assert result.status == 'account_mismatch'


def test_publish_dedup_follows_platform_identity(tmp_path, monkeypatch):
    import src.platform_adapter.publish_workflow as workflow
    from src.platform_adapter.models import PublishRequest
    monkeypatch.setattr(workflow, '__file__', str(tmp_path/'src/platform_adapter/publish_workflow.py'))
    video = tmp_path/'test.mp4'
    video.write_bytes(b'test-video')
    def request(key, identity):
        return PublishRequest(video_path=str(video), title='test', extra_metadata={
            'account_key': key, 'account_uuid': key, 'platform_identity_key': identity})
    first = workflow.PublishWorkflow(None)
    first._start_journal(request('A', 'douyin-a'))
    first._reserve_submission()
    with pytest.raises(ValueError, match='已有提交记录'):
        workflow.PublishWorkflow(None)._start_journal(request('renamed-A', 'douyin-a'))
    workflow.PublishWorkflow(None)._start_journal(request('B', 'douyin-b'))
