"""Render and click the preserved metrics/official-console controls, no platform."""
from types import SimpleNamespace as NS

from streamlit.testing.v1 import AppTest


def test_managed_metrics_button_uses_backend_read_without_foreground_lease(monkeypatch):
    from src import operations_accounts
    from src.operations_accounts import browser_control_runtime as bridge
    from src.platform_adapter.models import SyncResult
    from src.web import content_performance_dashboard as page
    from src.web import production_learning_dashboard
    from src.web.components import auth, account_scope
    monkeypatch.setenv('AI_DOUYIN_BROWSER_CONTROL', '1')
    profile = NS(account_uuid='acct:test', account_key='test')
    monkeypatch.setattr(operations_accounts, 'AccountProfileRepository', lambda: NS(db_path='unused', list_active=lambda: [profile]))
    monkeypatch.setattr(operations_accounts, 'AccountBindingRepository', lambda *_: NS(list_all=lambda: [NS(account_key='test', status='active')]))
    monkeypatch.setattr(operations_accounts, 'AccountRuntimeService', lambda: (_ for _ in ()).throw(AssertionError('foreground runtime forbidden')))
    monkeypatch.setattr(account_scope, 'select_account_scope', lambda *_a, **_k: profile.account_uuid)
    monkeypatch.setattr(auth, 'get_current_role', lambda: 'admin')
    monkeypatch.setattr(page, 'latest_snapshots', lambda *_: [])
    monkeypatch.setattr(page, 'snapshot_history', lambda *_: [])
    monkeypatch.setattr(production_learning_dashboard, 'render_learning', lambda *_a, **_k: None)
    requests = []
    def controlled(account_key, method, params, **options):
        requests.append((account_key, method, params, options))
        return SyncResult(True, 'success', videos=[])
    monkeypatch.setattr(bridge, 'managed_adapter_call', controlled)
    app = AppTest.from_string('from src.web.content_performance_dashboard import render_content_performance\nrender_content_performance()', default_timeout=60).run()
    assert not app.exception
    next(button for button in app.button if button.label == '采集视频后台数据').click()
    app.run()
    assert not app.exception
    assert requests == [('test', 'sync_videos', {'page_limit': 5}, {'operation_profile': 'creator_metrics_ui'})]
    assert any('已采集' in message.value for message in app.success)


def test_official_console_button_only_queues_and_shows_existing_waiting_job(monkeypatch):
    from src.operations_accounts import browser_control_runtime as bridge
    from src.web import trend_dashboard as page, account_exception_notice
    monkeypatch.setenv('AI_DOUYIN_BROWSER_CONTROL', '1')
    binding = NS(avatar_url='', nickname='测试账号', public_uid='123', sec_uid='',
        verification_source='page_verified', status='active', browser_environment_key='env:test',
        verified_at='', last_health_at='')
    runtime = NS(bindings=NS(get_optional=lambda *_: binding))
    monkeypatch.setattr(page, 'AccountRuntimeService', lambda **_: runtime)
    monkeypatch.setattr(page, 'DouyinOAuthClient', lambda: NS(configured=False))
    monkeypatch.setattr(page, 'get_current_role', lambda: 'admin')
    monkeypatch.setattr(page, 'get_current_user', lambda: 'actual-admin')
    monkeypatch.setattr(account_exception_notice, 'render_account_manual_window_controls', lambda *_a, **_k: None)
    monkeypatch.setattr(account_exception_notice, 'render_account_handling_completion', lambda *_a, **_k: None)
    jobs, calls = [], []
    monkeypatch.setattr(bridge, 'official_console_snapshot', lambda _: jobs[-1] if jobs else None)
    def queued(account_uuid, account_key, user):
        calls.append((account_uuid, account_key, user))
        job = {'command_id': 'original-console', 'state': 'queued'}
        jobs.append(job)
        return job
    monkeypatch.setattr(bridge, 'queue_official_console', queued)
    app = AppTest.from_string('''
from types import SimpleNamespace as NS
from src.web.trend_dashboard import _render_account_binding
_render_account_binding(NS(account_uuid='acct:test', account_key='test'), NS())
''', default_timeout=60).run()
    assert not app.exception
    button = next(button for button in app.button if button.label == '在此账号专属环境打开官方管理页')
    assert not button.disabled
    button.click()
    app.run()
    assert not app.exception
    assert calls == [('acct:test', 'test', 'actual-admin')]
    assert any('尚未确认打开' in message.value for message in app.info)
    jobs[-1]['state'] = 'waiting_human'
    app.run()
    assert not app.exception
    assert next(button for button in app.button if button.label == '在此账号专属环境打开官方管理页').disabled
    assert any('管理页已打开' in text.value for text in app.caption)
    assert calls == [('acct:test', 'test', 'actual-admin')]
