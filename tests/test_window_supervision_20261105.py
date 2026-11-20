import sqlite3
import time
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from src.operations_accounts import window_supervision as windows
from src.operations_accounts import browser_control_runtime as bridge


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv('AI_DOUYIN_WINDOW_SUPERVISION','1')
    prefs = tmp_path/'windows.db'
    controls = tmp_path/'controls.db'
    owner = tmp_path/'owners.db'
    runtime = tmp_path/'runtime.db'
    with sqlite3.connect(controls) as db:
        db.execute('CREATE TABLE account_controls(account_uuid TEXT PRIMARY KEY,account_key TEXT,state TEXT)')
        db.executemany('INSERT INTO account_controls VALUES(?,?,?)', [('a','alpha','active'),('b','beta','active')])
    with sqlite3.connect(owner) as db:
        db.execute('CREATE TABLE browser_control_owners(account_id TEXT,owner_id TEXT,generation INTEGER,binding_version TEXT,state TEXT,heartbeat REAL)')
        db.execute('INSERT INTO browser_control_owners VALUES(?,?,?,?,?,?)', ('a','original',4,'binding','active',time.time()))
        db.execute('CREATE TABLE browser_control_commands(command_id TEXT,account_id TEXT,state TEXT)')
    with sqlite3.connect(runtime) as db:
        db.execute('CREATE TABLE account_runtime_state(account_uuid TEXT,lock_owner TEXT)')
    monkeypatch.setattr(windows,'DB',prefs)
    monkeypatch.setattr(bridge,'DB',owner)
    monkeypatch.setattr('src.scheduler.account_refresh.DB',controls)
    return NS(prefs=prefs,controls=controls,owner=owner,runtime=runtime)


def save(state, *, account='a', key='alpha', enabled=True, mode='background', revision=0, target=None):
    return windows.save(account,key,enabled,mode,actor='local-admin',expected_revision=revision,
                        path=state.prefs,control_path=state.controls,target=target)


def resource():
    page = NS(tab_id='original-tab',_cmd=Mock(return_value={'window_state':'minimized'}))
    session = NS(_proc=object(),_supervision_protocol=1,config=NS(headless=False,mute_audio=True),
        window_status=lambda: {'open':True,'tabs':[{'tab_id':'original-tab','closed':False}]},
        get_page=lambda tab:page)
    actor = NS(owner_id='original',generation=4,binding_version='binding',_check_owner=Mock())
    return NS(account_uuid='a',account_key='alpha',session=session),actor,page


def test_read_only_views_do_not_create_database(state):
    assert windows.preference('a')['enabled'] is False
    assert windows.runtime_snapshot('a') is None
    assert not state.prefs.exists()


def test_deployment_gate_preserves_current_runtime_without_any_browser_io(state,monkeypatch):
    save(state);res,actor,page=resource()
    monkeypatch.delenv('AI_DOUYIN_WINDOW_SUPERVISION',raising=False)
    assert not windows.enabled(res) and not windows.keep_idle_window(res)
    windows.synchronize(res,actor)
    page._cmd.assert_not_called();actor._check_owner.assert_not_called()


def test_settings_isolation_cas_duplicate_and_no_business_side_effects(state):
    original=state.controls.read_bytes()
    assert save(state)==1
    assert save(state,revision=1)==1
    with pytest.raises(ValueError): save(state,revision=0)
    with pytest.raises(ValueError): save(state,account='b',key='alpha')
    assert windows.preference('b')['enabled'] is False
    assert state.controls.read_bytes()==original
    with sqlite3.connect(state.prefs) as db:
        assert db.execute('SELECT COUNT(*) FROM window_preference_audit').fetchone()[0]==1


@pytest.mark.parametrize('mode', ['watch','wrong',None])
def test_unbound_or_invalid_display_is_rejected(state,mode):
    with pytest.raises(ValueError): save(state,mode=mode)
    assert windows.preference('a')['enabled'] is False


@pytest.mark.parametrize('signed_in,role',[(False,'admin'),(True,'viewer'),(True,'editor')])
def test_server_refuses_non_admin_settings_display_and_pause(state,monkeypatch,signed_in,role):
    from src.web.components import auth
    monkeypatch.setattr(auth,'get_current_user',lambda:'viewer' if signed_in else None)
    monkeypatch.setattr(auth,'get_current_role',lambda:role)
    monkeypatch.setattr(auth,'has_permission',lambda role,permission:role=='admin')
    with pytest.raises(PermissionError): windows.save_from_web('a','alpha',True,'background',expected_revision=0)
    with pytest.raises(PermissionError): windows.pause_from_web('a','alpha')
    assert not state.prefs.exists()


def test_display_only_once_and_navigation_does_not_minimize_again(state):
    save(state)
    res,actor,page=resource()
    windows.synchronize(res,actor)
    assert page._cmd.call_count==1
    res._supervision_next=0
    windows.synchronize(res,actor)
    assert page._cmd.call_count==1
    snap=windows.live_runtime('a')
    assert snap['applied_revision']==1 and snap['headed'] and snap['muted']
    assert save(state,mode='watch',revision=1,target=snap)==2
    res._supervision_next=0
    windows.synchronize(res,actor)
    page._cmd.assert_called_with('supervision_window',mode='watch')
    res._supervision_next=0
    windows.synchronize(res,actor)
    assert page._cmd.call_count==2


def test_old_display_request_cannot_restore_new_owner_window(state):
    save(state)
    res,actor,page=resource();windows.synchronize(res,actor)
    snap=windows.runtime_snapshot('a')
    save(state,mode='watch',revision=1,target=snap)
    new,actor2,page2=resource();actor2.generation=5;actor2.owner_id='replacement'
    windows.synchronize(new,actor2)
    page2._cmd.assert_not_called()
    assert windows.runtime_snapshot('a')['applied_revision']==0


@pytest.mark.parametrize('change',['headless','unmuted','closed'])
def test_unknown_or_unready_window_never_claimed_viewable(state,change):
    save(state);res,actor,page=resource()
    if change=='headless':res.session.config.headless=True
    if change=='unmuted':res.session.config.mute_audio=False
    if change=='closed':res.session.window_status=lambda:{'open':False,'context_closed':True}
    windows.synchronize(res,actor)
    page._cmd.assert_not_called()
    assert windows.live_runtime('a') is None


def test_stale_or_replaced_owner_is_not_online(state):
    save(state);res,actor,page=resource();windows.synchronize(res,actor)
    assert windows.live_runtime('a')
    with sqlite3.connect(state.owner) as db:db.execute("UPDATE browser_control_owners SET generation=5")
    assert windows.live_runtime('a') is None


@pytest.mark.parametrize('paused,running,unknown,locked,expected',[
    (False,False,False,False,False),(True,False,False,False,True),
    (True,True,False,False,False),(True,False,True,False,False),(True,False,False,True,False)])
def test_manual_handover_requires_pause_and_actual_release(state,paused,running,unknown,locked,expected):
    with sqlite3.connect(state.controls) as db:db.execute('UPDATE account_controls SET state=? WHERE account_uuid=?',('paused' if paused else 'active','a'))
    with sqlite3.connect(state.owner) as db:
        if running or unknown:db.execute('INSERT INTO browser_control_commands VALUES(?,?,?)',('original','a','running' if running else 'outcome_unknown'))
    with sqlite3.connect(state.runtime) as db:
        if locked:db.execute('INSERT INTO account_runtime_state VALUES(?,?)',('a','original-lock'))
    assert windows.takeover_ready('a',control_path=state.controls,owner_path=state.owner,runtime_path=state.runtime) is expected


def test_window_display_never_focuses_or_navigates_and_checks_receipt(monkeypatch):
    import sys
    monkeypatch.setattr(sys,'platform','linux')
    page=Mock();cdp=page.context.new_cdp_session.return_value
    cdp.send.side_effect=[{'windowId':7},{},{'bounds':{'windowState':'normal'}}]
    assert windows.set_window(page,'watch')=={'window_state':'normal'}
    page.bring_to_front.assert_not_called();page.goto.assert_not_called();cdp.detach.assert_called_once()
    cdp.send.side_effect=[{'windowId':7},{},{'bounds':{'windowState':'normal'}}]
    with pytest.raises(RuntimeError):windows.set_window(page,'background')


@pytest.mark.parametrize('mode,flag,iconic',[('watch',4,False),('background',7,True)])
def test_windows_product_helper_uses_noactivate_and_verifies_native_state(mode,flag,iconic):
    from src.operations_accounts.window_noactivate import apply_native
    user32=Mock();user32.IsIconic.return_value=iconic
    assert apply_native(user32,123,mode)['window_state']==('minimized' if iconic else 'normal')
    user32.ShowWindow.assert_called_once_with(123,flag)
    user32.SetForegroundWindow.assert_not_called()
    user32.SetFocus.assert_not_called()
    user32.IsIconic.return_value=not iconic
    with pytest.raises(RuntimeError):apply_native(user32,123,mode)


def test_idle_keepalive_requires_opt_in_and_started_visible_window(state):
    res,actor,page=resource()
    assert not windows.keep_idle_window(res)
    save(state)
    assert windows.keep_idle_window(res)
    res.session._proc=None
    assert not windows.keep_idle_window(res)


def test_borrowers_reuse_one_automation_tab_but_never_borrow_manual(state):
    save(state)
    owner=Mock();owner.config.headless=False
    owner._supervision_protocol=1
    owner.new_tab.return_value=NS(tab_id='automation')
    owner.get_page.return_value=NS(tab_id='automation')
    owner.list_tabs.return_value=[{'tab_id':'automation','closed':False},{'tab_id':'manual','closed':False}]
    res=NS(account_uuid='a',account_key='alpha',ensure_session=lambda:owner)
    ctx=NS(actor=Mock(),command={'kind':'maintenance','payload':{}},check_dispatch=Mock())
    token=bridge._active.set(ctx)
    try:
        first=bridge.BorrowedSession(res,'maintenance');first.stop()
        second=bridge.BorrowedSession(res,'maintenance');second.stop()
        assert first.tab_id==second.tab_id=='automation'
        owner.new_tab.assert_called_once();owner.close_tab.assert_not_called()
        with pytest.raises(bridge.BrowserControlRejected):second.cmd('supervision_window')
        manual=bridge.BorrowedSession(res,'manual');manual.stop()
        assert owner.new_tab.call_count==2
    finally:bridge._active.reset(token)


def test_pause_gate_fires_before_any_browser_io(state):
    from src.operations_accounts.browser_control import BrowserControlDeferred
    save(state)
    owner=Mock();owner.config.headless=False;owner.new_tab.return_value=NS(tab_id='automation')
    owner._supervision_protocol=1
    res=NS(account_uuid='a',account_key='alpha',ensure_session=lambda:owner)
    ctx=NS(actor=Mock(),command={'kind':'maintenance','payload':{}},check_dispatch=Mock())
    token=bridge._active.set(ctx)
    try:
        borrowed=bridge.BorrowedSession(res,'maintenance')
        ctx.check_dispatch.side_effect=BrowserControlDeferred('human_required','paused')
        with pytest.raises(BrowserControlDeferred):borrowed.cmd('goto',url='about:blank')
        owner.cmd.assert_not_called()
    finally:bridge._active.reset(token)
