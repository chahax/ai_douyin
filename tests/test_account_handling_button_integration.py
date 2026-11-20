"""Real UI -> persistent async job -> original helper -> Event-controlled browser."""
from contextlib import contextmanager
from types import SimpleNamespace
import threading
import time
import sqlite3

import pytest
from streamlit.testing.v1 import AppTest


@pytest.mark.parametrize('failure', [None, 'launch', 'timeout'])
def test_async_button_returns_before_close_and_polls_real_worker(tmp_path, monkeypatch, failure):
    # This fixture exercises the preserved legacy async worker, not managed-owner admission.
    monkeypatch.setenv('AI_DOUYIN_BROWSER_CONTROL', '0')
    from src.web import account_exception_notice as notice
    from src.web.components import auth
    from src.operations_accounts import manual_handling, manual_window_jobs as jobs, runtime
    from src.scheduler import account_refresh
    from src.platform_adapter.models import BrowserSessionConfig

    monkeypatch.chdir(tmp_path)
    events, starts = [], []
    opened, release = threading.Event(), threading.Event()
    relative_profile = 'data/douyin_warmup/accounts/a/profile'
    relative_state = 'data/douyin_warmup/accounts/a/storage_state.json'
    profile_dir, storage = str(tmp_path / relative_profile), str(tmp_path / relative_state)
    profile = SimpleNamespace(account_uuid='A', account_key='a', display_name='账号a')
    binding = SimpleNamespace(account_uuid='A', account_key='a', browser_environment_key='original-env',
                              browser_profile_dir=profile_dir, storage_state_path=storage)
    context = runtime.AccountRuntimeContext(profile, binding, 'original-env', profile_dir, storage)

    class Session:
        config = BrowserSessionConfig(base_url='https://www.douyin.com', home_url='https://www.douyin.com',
            user_data_dir=relative_profile, storage_state_path=relative_state, headless=False)
        def open_for_manual_login_until_closed(self, url, timeout_seconds, *, on_opened=None):
            events.append(('open', url, threading.current_thread().name))
            if failure == 'timeout':
                raise TimeoutError('private startup diagnostics')
            if failure:
                raise RuntimeError('private launch diagnostics')
            assert callable(on_opened)
            on_opened()
            opened.set()
            assert release.wait(15), 'test must release the fake user window'
        def stop(self):
            events.append(('stop',))

    prepared = SimpleNamespace(profile=profile, browser_environment_key='original-env',
        browser_profile_dir=profile_dir, storage_state_path=storage,
        create_browser_session=lambda **kwargs: Session())
    class Runtime:
        def resolve(self, key, *, require_healthy):
            events.append(('resolve', key, require_healthy))
            return context
        @contextmanager
        def manual_browser_environment(self, key):
            events.append(('lease-enter', key))
            try:
                yield prepared
            finally:
                events.append(('lease-exit', key))

    view = {'issues': [{'id': 1, 'account_uuid': 'A', 'account_key': 'a', 'status': 'open',
            'created_at': 100, 'error_code': 'human_required', 'message': '原记录需要安全验证'}],
            'controls': [{'account_uuid': 'A', 'account_key': 'a', 'state': 'paused'}]}
    path = tmp_path / 'windows.db'
    real_start, real_get = jobs.start_manual_window_job, jobs.get_manual_window_job
    def start(uuid, key, requested_by, **kwargs):
        starts.append((uuid, key, requested_by))
        return real_start(uuid, key, requested_by, path=path, **kwargs)
    monkeypatch.setattr(jobs, 'start_manual_window_job', start)
    monkeypatch.setattr(jobs, 'get_manual_window_job', lambda uuid, key: real_get(uuid, key, path=path))
    monkeypatch.setattr(auth, 'get_current_user', lambda: 'operator')
    monkeypatch.setattr(auth, 'get_current_role', lambda: 'admin')
    monkeypatch.setattr(account_refresh, 'snapshot', lambda: view)
    monkeypatch.setattr(runtime, 'AccountRuntimeService', Runtime)
    monkeypatch.setattr(manual_handling, '_handling_snapshot', lambda: view)
    monkeypatch.setattr(manual_handling, '_pause_for_handling', lambda uuid, key: events.append(('pause', uuid, key)))
    monkeypatch.setattr(manual_handling, 'resolve_manual_handling_target', lambda *args, **kwargs:
        manual_handling.ManualHandlingTarget('https://www.douyin.com/search/test', '原记录搜索页', 'recorded_research_keyword'))
    monkeypatch.setattr(manual_handling, '_manual_window_event', lambda *args, **kwargs: None)
    def forbidden(*args, **kwargs):
        raise AssertionError('window jobs must not navigate, recover or close the issue')
    monkeypatch.setattr(notice.st, 'switch_page', forbidden)
    monkeypatch.setattr(account_refresh, 'complete_account_handling', forbidden)
    monkeypatch.setattr(account_refresh, 'close_account_issue', forbidden)
    monkeypatch.setattr(notice, '_selector_profiles', [profile, SimpleNamespace(account_uuid='B', account_key='b', display_name='账号b')], raising=False)
    app = AppTest.from_string(
        "import streamlit as st\nst.session_state.setdefault('active_account_uuid', 'B')\n"
        "from src.web import account_exception_notice as notice\n"
        "notice.render_account_exception_notice()\n"
        "from src.web.components.account_scope import select_account_scope\n"
        "select_account_scope(notice._selector_profiles, key='accounts_selected_scope', allow_all=False)\n",
        default_timeout=20).run()
    assert not app.exception and not starts and not events
    assert app.selectbox(key='accounts_selected_scope').value == 'B'
    try:
        app.button(key='global_account_issue_open_1').click().run()
        assert not app.exception
        assert app.selectbox(key='accounts_selected_scope').value == 'A'
        assert starts == [('A', 'a', 'operator')]
        assert all(row[2].startswith('ManualWindow-') for row in events if row[0] == 'open')
        if not failure:
            assert opened.wait(3)
            app.run()
            assert app.button(key='global_account_issue_open_1').disabled
            assert app.button(key='global_account_handling_complete_1').disabled
            assert any('窗口已打开' in item.value for item in app.info)
            assert real_get('A', 'a', path=path)['state'] == 'running'
            assert not release.is_set()
            # A later user selection survives timed/ordinary read-only polling.
            app.selectbox(key='accounts_selected_scope').set_value('B').run()
            assert app.session_state['active_account_uuid'] == 'B'
        release.set()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                job = real_get('A', 'a', path=path)
            except sqlite3.OperationalError as exc:
                if 'locked' not in str(exc).lower() and 'busy' not in str(exc).lower():
                    raise
                # Read only the original job; local DB contention never starts
                # another window or substitutes a terminal receipt.
                time.sleep(0.01)
                continue
            if job and job['state'] in ('closed', 'failed'):
                break
            time.sleep(0.01)
        else:
            pytest.fail('worker did not save its terminal receipt')
        app.run()
        assert not app.exception
        assert len(starts) == 1
        assert view['controls'][0]['state'] == 'paused' and view['issues'][0]['status'] == 'open'
        if failure:
            assert any('打开人工处理窗口失败' in item.value for item in app.error)
            assert not any('private' in item.value for item in app.error)
        else:
            assert job['state'] == 'closed'
            assert events[-2:] == [('stop',), ('lease-exit', 'a')]
            assert any('人工窗口已关闭' in item.value for item in app.info)
            assert not any('窗口已打开' in item.value for item in app.info)
            assert not app.button(key='global_account_handling_complete_1').disabled
            assert app.selectbox(key='accounts_selected_scope').value == 'B'
    finally:
        release.set()
        with jobs._registry_lock:
            workers = list(jobs._registry.values())
        for worker in workers:
            worker.join(timeout=5)
