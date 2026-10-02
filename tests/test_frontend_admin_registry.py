import json
from pathlib import Path

from src.services.production_registry import list_projects, task_review_context
from streamlit.testing.v1 import AppTest


def write(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding='utf-8')


def test_nested_attempts_group_with_assembly_without_mtime(tmp_path):
    base = tmp_path / 'data/video_generation/campaign'
    identity = {'campaign_path': str(base / 'campaign.json'), 'campaign_series_id': 'series_004'}
    for attempt in ['S01', 'S01_retry', 'S02']:
        write(base / attempt / 'production.json', {**identity, 'shots': ['S01'], 'title': '租房', 'created_at': '2026-09-13T10:00:00+08:00'})
    write(base / 'complete/assembly.json', {'campaign_path': identity['campaign_path'], 'series_id': 'series_004', 'video': 'data/video.mp4', 'finished_at_bjt': '2026-09-13T11:00:00+08:00'})
    write(base / 'unknown/production.json', {'shots': []})
    projects = list_projects(tmp_path)
    assert len(projects) == 2
    assert len(projects[0]['attempts']) == 3
    assert len(projects[0]['assemblies']) == 1
    assert projects[1]['recorded_at'].year == 1


def test_api_success_does_not_imply_review_pass(tmp_path):
    video = tmp_path / 'data/video_generation/test/S01.mp4'
    task = {'status': 'succeeded', 'video_path': str(video)}
    assert task_review_context(task, tmp_path)['decision'] == 'pending'
    write(video.with_suffix('.quality_review.json'), {'decision': 'failed'})
    assert task_review_context(task, tmp_path)['decision'] == 'failed'
    assert task_review_context({'video_path': str(tmp_path / 'private.mp4')}, tmp_path)['decision'] == 'pending'


def test_usage_viewer_does_not_query_money(monkeypatch):
    import src.web.seedance_dashboard as dashboard
    monkeypatch.setattr(dashboard, '_cached_ark_balance', lambda scope: (_ for _ in ()).throw(AssertionError('must not query')))
    app = AppTest.from_string("from src.shared.config import settings\nsettings.SEEDANCE_PROVIDER='ark_api'\nfrom src.web.seedance_dashboard import page_seedance_usage\npage_seedance_usage()")
    app.run(timeout=30)
    assert not app.exception
    assert any(m.label == '账户可用余额' and m.value == '需管理员权限' for m in app.metric)


def test_account_page_viewer_can_read(monkeypatch):
    app = AppTest.from_string('from src.web.trend_dashboard import page_douyin_accounts\npage_douyin_accounts()')
    app.run(timeout=30)
    assert not app.exception
    assert any('账号与登录' == tab.label for tab in app.tabs)


def test_latest_production_page_renders(tmp_path, monkeypatch):
    import src.web.video_production_dashboard as dashboard
    import src.services.production_registry as registry
    from src.operations_accounts import AccountProfileRepository

    assembly = tmp_path / 'data/video_generation/sample/assembly.json'
    write(assembly, {'duration_seconds': 47.552, 'finished_at_bjt': '2026-09-13T11:00:00+08:00'})
    monkeypatch.setattr(dashboard, 'ROOT', tmp_path)
    monkeypatch.setattr(AccountProfileRepository, 'list_active', lambda self, status=None: [])
    monkeypatch.setattr(registry, 'list_projects', lambda root, account_uuid=None: [{
        'key': 'sample', 'title': '测试制作记录', 'attempts': [], 'assemblies': [assembly],
    }])
    app = AppTest.from_string('from src.web.video_production_dashboard import page_video_production\npage_video_production()')
    app.run(timeout=30)
    assert not app.exception
    assert any(m.label == '成片时长' and '47.552' in m.value for m in app.metric)


def test_balance_zero_and_refresh_failure_preserve_last_snapshot(monkeypatch):
    import src.web.seedance_dashboard as dashboard
    import src.services.volcengine_balance as service
    monkeypatch.setattr(service, 'credential_status', lambda: {'configured': True, 'sdk_installed': True})
    monkeypatch.setattr(service, 'credential_scope', lambda: 'test-account')
    calls = []

    def query():
        calls.append(1)
        if len(calls) > 1:
            raise ValueError('测试网络不可用')
        return {'available_balance': 0, 'cash_balance': 0, 'queried_at': '2026-09-14T02:54:31+00:00'}

    monkeypatch.setattr(service, 'query_account_balance', query)
    dashboard._cached_ark_balance.clear()
    app = AppTest.from_string("import streamlit as st\nst.session_state['user_role']='admin'\nfrom src.shared.config import settings\nsettings.SEEDANCE_PROVIDER='ark_api'\nfrom src.web.seedance_dashboard import page_seedance_usage\npage_seedance_usage()")
    app.run(timeout=30)
    assert not app.exception
    assert next(m for m in app.metric if m.label == '账户可用余额').value == '0'
    app.button(key='ark_balance_refresh').click().run(timeout=30)
    assert not app.exception
    assert next(m for m in app.metric if m.label == '账户可用余额').value == '0'
    assert any('上次成功快照' in w.value for w in app.warning)
    dashboard._cached_ark_balance.clear()
