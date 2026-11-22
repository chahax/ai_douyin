import sqlite3
import sys
from types import SimpleNamespace as NS
from unittest.mock import Mock
import pytest
from src.operations_accounts.retained_feed_session import minimize,take_tab,enabled
from src.operations_accounts.clear_feed_resume import reserve


def test_explicit_authorization_does_not_reset_or_reuse_automatic_history(tmp_path):
    path=tmp_path/'state.db'
    assert reserve('a','old',4,{},path,100000)
    assert reserve('b','old-b',4,{},path,100000)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE clear_feed_user_authorizations(command_id TEXT PRIMARY KEY,account_uuid TEXT,revision INTEGER,authorization_reference TEXT,consumed_at REAL)')
        db.execute("INSERT INTO clear_feed_user_authorizations VALUES('new','a',6,'user accepted original minimized session',NULL)")
    assert not reserve('a','new',7,{},path,100010)
    assert not reserve('b','new',6,{},path,100010)
    assert reserve('a','new',6,{},path,100012)
    assert not reserve('a','new',6,{},path,100013)
    assert not reserve('a','another',6,{},path,100014)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT consumed_at FROM clear_feed_user_authorizations").fetchone()[0]==100012
        assert db.execute("SELECT COUNT(*) FROM clear_feed_resumes WHERE command_id='old'").fetchone()[0]==1


@pytest.mark.parametrize('kind,mode,expected',[('recovery',None,False),('maintenance','post-publish',False),('maintenance','playback',True)])
def test_retained_tab_is_exclusively_handed_to_playback_once(kind,mode,expected):
    resource=NS(retained_feed_tab='original')
    context=NS(command={'kind':kind,'payload':{'mode':mode}})
    assert bool(take_tab(resource,context)) is expected
    assert resource.retained_feed_tab== (None if expected else 'original')
    if expected:assert take_tab(resource,context) is None


def test_minimize_failure_is_not_success():
    page=Mock();cdp=page.context.new_cdp_session.return_value
    cdp.send.side_effect=[{'windowId':4},{},{'bounds':{'windowState':'normal'}}]
    with pytest.raises(RuntimeError):minimize(page)
    cdp.detach.assert_called_once()


def test_missing_preference_does_not_change_other_accounts(tmp_path):
    path=tmp_path/'state.db';sqlite3.connect(path).close()
    assert not enabled('a',path)


@pytest.mark.parametrize('cleaned', [False, True])
def test_identity_probe_records_only_confirmed_pre_ready_failure(cleaned):
    from src.operations_accounts import browser_control_runtime as bridge
    from src.operations_accounts.runtime import AccountRuntimeError
    from src.platform_adapter.browser_session import BrowserWorkerStartupError

    startup = BrowserWorkerStartupError('launching_browser')
    startup.startup_evidence = dict(stage='launching_browser', ready_received=False, cleanup_verified=cleaned)

    def probe(*args, **kwargs):
        raise AccountRuntimeError('recovery_probe_failed', 'test') from startup

    session = NS(_proc=None, _startup_cleanup_verified=cleaned)
    ctx = NS(resource=NS(runtime=NS(probe_recovery=probe), account_key='test', headless=True, session=session))
    if cleaned:
        outcome = bridge._recovery(ctx, {})
        assert outcome.state == 'failed' and outcome.result['error_code'] == 'browser_start_failed'
        assert outcome.result['identity_verified'] is False
    else:
        with pytest.raises(AccountRuntimeError):
            bridge._recovery(ctx, {})


def test_real_chrome_minimizes_original_window_and_keeps_tab():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=False,args=['--mute-audio'])
        try:
            page=browser.new_page();page.set_content('<div>Local window handoff test</div>')
            assert minimize(page)=={'minimized':True}
            assert not page.is_closed() and page.locator('div').inner_text()=='Local window handoff test'
        finally:browser.close()


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows taskbar')
@pytest.mark.parametrize('chromium_sandbox', [False, True])
def test_real_chrome_managed_window_stays_in_taskbar_during_navigation(tmp_path, chromium_sandbox):
    import ctypes
    import threading
    import psutil
    from ctypes import wintypes
    from src.operations_accounts.interactive_desktop import current_desktop_name
    from src.platform_adapter.browser_session import BrowserSession
    from src.platform_adapter.models import BrowserSessionConfig

    if current_desktop_name() != 'Default':
        pytest.skip('Focus sampling requires the interactive Windows desktop')
    user32 = ctypes.WinDLL('user32')
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    observed = {}
    stage = 'startup'
    done = threading.Event()

    def sample_foreground():
        while not done.is_set():
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(pid))
            observed.setdefault(pid.value, set()).add(stage)
            done.wait(0.01)

    session = BrowserSession(BrowserSessionConfig(base_url='about:blank', home_url='about:blank', user_data_dir=str(tmp_path/'chrome'),
        storage_state_path=str(tmp_path/'state.json'), headless=False, browser_channel='chrome',
        chromium_sandbox=chromium_sandbox, mute_audio=True, start_minimized=True, background_account_label='Taskbar QA'))
    observer = threading.Thread(target=sample_foreground)
    observer.start()
    try:
        session.start()
        assert session.get_page()._cmd('supervision_window_state')['window_state'] == 'minimized', 'startup'
        assert session.get_page().evaluate('document.title') == 'Taskbar QA · 抖音业务窗口'
        stage = 'new tab'
        page = session.new_tab('maintenance')
        assert page._cmd('supervision_window_state')['window_state'] == 'minimized', 'new tab'
        stage = 'navigation'
        page.goto('about:blank')
        assert page._cmd('supervision_window_state')['window_state'] == 'minimized'
        owned = {p.pid: p.name() for p in psutil.Process(session._proc.pid).children(recursive=True)}
        assert owned
    finally:
        done.set()
        observer.join()
        session.stop()
    assert not [(owned[pid], stages) for pid, stages in observed.items() if pid in owned]


@pytest.mark.parametrize('path,expected_goto',[('/',False),('/jingxuan',True)])
def test_borrower_preserves_only_current_homepage_and_rejects_owner_actions(path,expected_goto):
    from src.operations_accounts import browser_control_runtime as bridge
    from src.operations_accounts.browser_control import BrowserControlRejected
    owner=Mock();owner.new_tab.return_value=NS(tab_id='identity')
    owner.cmd.return_value={'value':{'host':'www.douyin.com','path':path}}
    resource=NS(retained_feed_tab='original',ensure_session=lambda:owner)
    ctx=NS(command={'kind':'maintenance','payload':{'mode':'playback'}},check_dispatch=Mock())
    token=bridge._active.set(ctx)
    try:
        session=bridge.BorrowedSession(resource,'maintenance')
        assert resource.retained_feed_tab=='original' and session.tab_id=='identity'
        session.open_page('https://www.douyin.com/user/self?from_tab_name=main')
        assert resource.retained_feed_tab=='original'
        owner.cmd.reset_mock()
        session.open_page('https://www.douyin.com/?recommend=1')
        assert any(c.args[0]=='goto' for c in owner.cmd.call_args_list) is expected_goto
        owner.new_tab.assert_called_once()
        with pytest.raises(BrowserControlRejected):session.cmd('minimize_window')
        session.stop();assert [c.args[0] for c in owner.close_tab.call_args_list]==['identity','original']
    finally:bridge._active.reset(token)


@pytest.mark.parametrize('opted_in',[True,False])
@pytest.mark.parametrize('headless', [True, False])
def test_future_background_session_honors_saved_minimized_preference(monkeypatch,opted_in,headless):
    from src.operations_accounts import browser_control_runtime as bridge
    from src.operations_accounts import retained_feed_session as retained
    from src.platform_adapter.douyin_warmup import DouyinWarmupService
    owner=Mock();owner.get_page.return_value._cmd.return_value={'minimized':True}
    build=Mock(return_value=owner)
    monkeypatch.setattr(DouyinWarmupService,'build_browser_session',build)
    monkeypatch.setattr(retained,'enabled',lambda *args:opted_in)
    ctx=NS(account_key='a',account_uuid='account:a')
    runtime=Mock();runtime.bindings.get_runtime_state.return_value=NS(lock_owner='')
    resource=bridge.AccountBrowserResource(ctx,runtime,headless=headless)
    assert resource.ensure_session() is owner
    build.assert_called_once_with('a',headless=headless and not opted_in)
    if opted_in:
        assert owner.config.start_minimized is True and owner.config.mute_audio is True
        assert not resource.headless
    assert owner.start.call_count == int(headless and opted_in)


@pytest.mark.parametrize('started_minimized', [False, True])
def test_borrowed_navigation_respects_window_opened_from_taskbar(monkeypatch, started_minimized):
    from src.operations_accounts import browser_control_runtime as bridge
    from src.operations_accounts import retained_feed_session as retained
    monkeypatch.setattr(retained,'enabled',lambda *args:True)
    owner=Mock();owner.new_tab.return_value=NS(tab_id='identity')
    owner.config.mute_audio=True
    owner.config.start_minimized=started_minimized
    owner.get_page.return_value._cmd.return_value={'window_state':'normal'} if started_minimized else {'minimized':True}
    resource=NS(retained_feed_tab=None,headless=False,account_uuid='account:a',ensure_session=lambda:owner)
    ctx=NS(command={'kind':'maintenance','payload':{'mode':'playback'}},check_dispatch=Mock())
    token=bridge._active.set(ctx)
    try:
        session=bridge.BorrowedSession(resource,'maintenance')
        session.open_page('https://www.douyin.com/user/self')
        owner.get_page.return_value._cmd.assert_called_once_with('supervision_window_state' if started_minimized else 'minimize_window')
        assert session.keep_background()=={'minimized':not started_minimized,'muted':True}
    finally:bridge._active.reset(token)
