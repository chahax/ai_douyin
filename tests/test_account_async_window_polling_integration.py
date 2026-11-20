"""Actual widgets, async SQLite job and shared helper across open/close rerenders."""
from contextlib import contextmanager
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace

from streamlit.testing.v1 import AppTest


def test_closed_background_window_updates_ui_and_preserves_later_account_selection(tmp_path, monkeypatch):
    monkeypatch.setenv('AI_DOUYIN_BROWSER_CONTROL', '0')
    from src.operations_accounts import manual_handling, manual_window_jobs as jobs, runtime
    from src.scheduler import account_refresh
    from src.web import account_exception_notice as notice
    from src.web.components import auth
    from src.platform_adapter.models import BrowserSessionConfig

    opened, close = Event(), Event()
    calls = []
    path = tmp_path / 'account_manual_windows.db'
    original_start, original_get = jobs.start_manual_window_job, jobs.get_manual_window_job
    monkeypatch.setattr(jobs, 'start_manual_window_job',
        lambda uuid, key, actor, **kwargs: original_start(uuid, key, actor, path=path, **kwargs))
    monkeypatch.setattr(jobs, 'get_manual_window_job',
        lambda uuid, key, **kwargs: original_get(uuid, key, path=path))
    profile = SimpleNamespace(account_uuid='A', account_key='a', display_name='Account A')
    profile_dir, storage = str(tmp_path / 'original_profile'), str(tmp_path / 'original_state.json')
    binding = SimpleNamespace(account_uuid='A', account_key='a', browser_environment_key='original',
                              browser_profile_dir=profile_dir, storage_state_path=storage)
    context = runtime.AccountRuntimeContext(profile, binding, 'original', profile_dir, storage)

    class Session:
        config = BrowserSessionConfig(base_url='https://www.douyin.com', home_url='https://www.douyin.com',
            user_data_dir=profile_dir, storage_state_path=storage, headless=False)
        def open_for_manual_login_until_closed(self, url, *, timeout_seconds, on_opened):
            calls.append('open')
            on_opened()
            opened.set()
            assert close.wait(60), 'Test must release the controlled window.'
        def stop(self):
            calls.append('stop')

    prepared = SimpleNamespace(profile=profile, browser_environment_key='original',
        browser_profile_dir=profile_dir, storage_state_path=storage,
        create_browser_session=lambda **kwargs: Session())
    class Runtime:
        def resolve(self, key, *, require_healthy):
            assert key == 'a' and require_healthy is False
            return context
        @contextmanager
        def manual_browser_environment(self, key):
            assert key == 'a'
            calls.append('lease-enter')
            try:
                yield prepared
            finally:
                calls.append('lease-exit')

    data = {'issues': [{'id': 3, 'account_uuid': 'A', 'account_key': 'a', 'status': 'open',
                       'created_at': 100, 'error_code': 'human_required', 'message': 'original historical event'}],
            'controls': [{'account_uuid': 'A', 'account_key': 'a', 'state': 'paused'}]}
    monkeypatch.setattr(auth, 'get_current_user', lambda: 'operator-test')
    monkeypatch.setattr(auth, 'get_current_role', lambda: 'admin')
    monkeypatch.setattr(account_refresh, 'snapshot', lambda: data)
    monkeypatch.setattr(runtime, 'AccountRuntimeService', Runtime)
    monkeypatch.setattr(manual_handling, '_handling_snapshot', lambda: data)
    monkeypatch.setattr(manual_handling, '_pause_for_handling', lambda *args: None)
    monkeypatch.setattr(manual_handling, 'resolve_manual_handling_target',
        lambda *a, **k: manual_handling.ManualHandlingTarget('https://www.douyin.com/user/self', 'original page'))
    monkeypatch.setattr(manual_handling, '_manual_window_event', lambda *args, **kwargs: None)
    def forbidden(*args, **kwargs):
        raise AssertionError('Window polling must not complete handling or close the historical incident.')
    monkeypatch.setattr(account_refresh, 'complete_account_handling', forbidden)
    monkeypatch.setattr(account_refresh, 'close_account_issue', forbidden)
    monkeypatch.setattr(notice, '_test_scope_profiles', [profile,
        SimpleNamespace(account_uuid='B', account_key='b', display_name='Account B')], raising=False)
    app = AppTest.from_string(
        "import streamlit as st\nst.session_state.setdefault('active_account_uuid','B')\n"
        "from src.web import account_exception_notice as notice\n"
        "notice.render_account_exception_notice()\n"
        "from src.web.components.account_scope import select_account_scope\n"
        "select_account_scope(notice._test_scope_profiles,key='accounts_selected_scope',allow_all=False)\n",
        default_timeout=20).run()
    try:
        assert not app.exception and app.selectbox(key='accounts_selected_scope').value == 'B'
        app.button(key='global_account_issue_open_3').click().run()
        assert not app.exception
        assert opened.wait(5)
        # The widget call returned while the controlled browser is still open.
        assert not close.is_set() and app.selectbox(key='accounts_selected_scope').value == 'A'
        active = original_get('A', 'a', path=path)
        assert active['state'] in ('starting', 'running')
        app.run()
        assert app.button(key='global_account_issue_open_3').disabled
        assert app.button(key='global_account_handling_complete_3').disabled
        app.selectbox(key='accounts_selected_scope').select('B').run()
        assert app.session_state['active_account_uuid'] == 'B'
        close.set()
        deadline = monotonic() + 5
        while monotonic() < deadline:
            terminal = original_get('A', 'a', path=path)
            if terminal['state'] == 'closed':
                break
            sleep(.02)
        assert terminal['state'] == 'closed' and terminal['job_id'] == active['job_id']
        app.run()
        assert not app.exception
        assert app.selectbox(key='accounts_selected_scope').value == 'B'
        assert not app.button(key='global_account_handling_complete_3').disabled
        visible = ' '.join(item.value for kind in (app.info, app.caption, app.success) for item in kind)
        assert '已关闭' in visible and '窗口已打开，请在' not in visible
        assert calls == ['lease-enter', 'open', 'stop', 'lease-exit']
        assert data['controls'][0]['state'] == 'paused' and data['issues'][0]['status'] == 'open'
    finally:
        close.set()
