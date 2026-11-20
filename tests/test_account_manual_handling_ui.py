"""The login page saves manual work, then requests backend identity verification."""
from contextlib import contextmanager
from dataclasses import asdict
from types import SimpleNamespace
import sys

from streamlit.testing.v1 import AppTest


def _app(monkeypatch, *, bound=True, role='admin'):
    from src.web import trend_dashboard as page
    from src.web.components import auth
    from src.scheduler import account_refresh
    from src.operations_accounts import DouyinIdentity
    from src.operations_accounts import manual_handling

    events = []
    state = {'controls': [{'account_uuid': 'A', 'account_key': 'a', 'state': 'paused', 'error_code': 'human_required'}],
             'accounts': [], 'smart_accounts': [], 'playback_accounts': [], 'runs': [], 'smart_runs': [], 'playback_runs': []}
    identity = DouyinIdentity(nickname='账号a', public_uid='123', sec_uid='sec-a')
    binding = SimpleNamespace(avatar_url='', nickname='账号a', public_uid='123', sec_uid='',
                              verification_source='browser', status='blocked', browser_environment_key='own-a',
                              verified_at='', last_health_at='', platform_identity_key=identity.platform_identity_key) if bound else None
    class Session:
        def open_for_manual_login_until_closed(self, url, **kwargs):
            events.append(('open', url))
        def stop(self):
            events.append(('stop',))
    class Runtime:
        bindings = SimpleNamespace(get_optional=lambda key: binding)
        @contextmanager
        def manual_browser_environment(self, key):
            events.append(('lease-enter', key))
            try:
                yield SimpleNamespace(create_browser_session=lambda **kwargs: Session())
            finally:
                events.append(('lease-exit', key))
        def probe_unbound_identity(self, key, **kwargs):
            assert not bound, 'existing binding must be verified only by backend'
            events.append(('probe-unbound', key))
            return identity
    jobs = {}
    def open_bound(uuid, key, requested_by, **kwargs):
        events.append(('open-bound', (uuid, key), {'requested_by': requested_by, **kwargs}))
        jobs[uuid] = {'job_id': 'job-A', 'account_uuid': uuid, 'account_key': key, 'state': 'closed', 'phase': 'closed'}
        return dict(jobs[uuid])
    def pause(*args, **kwargs):
        events.append(('pause', args, kwargs))
    def complete(uuid, key, **kwargs):
        events.append(('complete', (uuid, key), kwargs))
        state['controls'][0]['state'] = 'recovery_requested'
        return {'accepted': True, 'state': 'recovery_requested', 'message': '等待核验'}
    monkeypatch.setattr(page, 'AccountRuntimeService', lambda **kwargs: Runtime())
    monkeypatch.setattr(page, 'DouyinOAuthClient', lambda: SimpleNamespace(configured=False))
    for module in (page, auth):
        monkeypatch.setattr(module, 'get_current_user', lambda: 'operator-test')
        monkeypatch.setattr(module, 'get_current_role', lambda: role)
    monkeypatch.setattr(account_refresh, 'snapshot', lambda: state)
    monkeypatch.setattr(account_refresh, 'pause_account', pause)
    monkeypatch.setattr(account_refresh, 'complete_account_handling', complete, raising=False)
    monkeypatch.setitem(sys.modules, 'src.operations_accounts.manual_window_jobs',
                        SimpleNamespace(start_manual_window_job=open_bound,
                                        get_manual_window_job=lambda uuid, key: jobs.get(uuid)))
    # Only the time-label adapter is needed here; avoid pandas/Arrow cold imports.
    monkeypatch.setitem(sys.modules, 'src.web.production_insights', SimpleNamespace(display_time=lambda value: '未记录'))
    profile = SimpleNamespace(account_uuid='A', account_key='a')
    repository = SimpleNamespace(db_path='unused-test-db')
    monkeypatch.setattr(page, '_manual_ui_context', (profile, repository), raising=False)
    app = AppTest.from_string(
        "from src.web import trend_dashboard as page\n"
        "page._render_account_binding(*page._manual_ui_context)\n", default_timeout=20).run()
    assert not app.exception
    return app, events, state, identity


def test_existing_account_calls_shared_window_service_and_does_not_rebind(monkeypatch):
    app, events, _, identity = _app(monkeypatch)
    app.session_state['pending_douyin_identity_a'] = asdict(identity)
    app.button(key='bind_douyin_a').click().run()
    assert not app.exception
    assert len(events) == 1 and events[0][:2] == ('open-bound', ('A', 'a'))
    assert events[0][2]['runtime'] is not None
    assert not any(item[0] in ('probe-unbound', 'complete') for item in events)
    assert 'pending_douyin_identity_a' not in app.session_state
    assert any('人工窗口已关闭' in item.value for item in app.info)
    assert not any(item.label == '确认身份并保存唯一绑定' for item in app.button)


def test_login_completion_only_registers_backend_request_and_disables_repeat(monkeypatch):
    app, events, _, _ = _app(monkeypatch)
    app.button(key='verify_douyin_a').click().run()
    assert not app.exception
    assert events == [('complete', ('A', 'a'), {'handled_by': 'operator-test'})]
    assert app.button(key='verify_douyin_a').disabled
    assert any('等待后台核验' in item.value for item in app.caption)
    assert not app.success


def test_unbound_account_keeps_original_identity_confirmation_flow(monkeypatch):
    app, events, _, _ = _app(monkeypatch, bound=False)
    app.button(key='bind_douyin_a').click().run()
    assert not app.exception
    assert ('probe-unbound', 'a') in events
    assert not any(item[0] in ('open-bound', 'pause', 'complete') for item in events)
    assert any(item.label == '确认身份并保存唯一绑定' for item in app.button)


def test_viewer_cannot_open_manual_window_or_complete(monkeypatch):
    app, events, _, _ = _app(monkeypatch, role='viewer')
    assert app.button(key='bind_douyin_a').disabled
    assert app.button(key='verify_douyin_a').disabled
    assert events == []


def test_binding_metrics_include_paused_account_even_when_binding_is_normal():
    from src.web.trend_dashboard import _account_binding_metrics
    profiles = [SimpleNamespace(account_uuid='A', account_key='a')]
    assert _account_binding_metrics(profiles, {'a': SimpleNamespace(status='active')},
                                    [{'account_uuid': 'A', 'account_key': 'a', 'state': 'paused'}]) == (1, 1)


def test_binding_metrics_cannot_claim_zero_pending_when_snapshot_unavailable():
    from src.web.trend_dashboard import _account_binding_metrics
    assert _account_binding_metrics([SimpleNamespace(account_uuid='A', account_key='a')],
                                    {'a': SimpleNamespace(status='active')}, None) == (1, '未知')


def test_binding_metrics_invalid_or_unregistered_controls_are_unknown():
    from src.web.trend_dashboard import _account_binding_metrics
    profiles = [SimpleNamespace(account_uuid='A', account_key='a')]
    bindings = {'a': SimpleNamespace(status='active')}
    for controls in ([], [None], [{'account_uuid': 'A'}],
                     [{'account_uuid': 'A', 'account_key': 'wrong', 'state': 'active'}],
                     [{'account_uuid': 'A', 'account_key': 'a', 'state': 'unrecognized'}]):
        assert _account_binding_metrics(profiles, bindings, controls) == (1, '未知')


def test_single_account_first_render_selects_only_available_account():
    from src.web.trend_dashboard import _initialize_single_account_scope
    state = {'active_account_uuid': '*'}
    _initialize_single_account_scope([SimpleNamespace(account_uuid='A')], state)
    assert state == {'active_account_uuid': 'A'}


def test_initial_account_default_does_not_take_over_existing_or_multiaccount_choice():
    from src.web.trend_dashboard import _initialize_single_account_scope
    one = [SimpleNamespace(account_uuid='A')]
    cases = [(one, {'accounts_selected_scope': '?', 'active_account_uuid': '?'}),
             (one, {'accounts_selected_scope': 'A', 'active_account_uuid': 'A'}),
             (one, {'active_account_uuid': 'A'}),
             ([*one, SimpleNamespace(account_uuid='B')], {'active_account_uuid': '*'})]
    for profiles, state in cases:
        expected = dict(state)
        _initialize_single_account_scope(profiles, state)
        assert state == expected
