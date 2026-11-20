from types import SimpleNamespace as NS
import pytest

from src.operations_accounts.browser_control import BrowserControlStore, BrowserControlActor
from src.operations_accounts.browser_host_retirement import retire, retire_host, retry_allowed
from src.operations_accounts.browser_boot_recovery import read_owner


def test_queued_original_survives_retirement_and_runs_once(tmp_path):
    clock=[1000.]
    s=BrowserControlStore(tmp_path/'q.db',clock=lambda:clock[0])
    o=s.acquire_owner('a','b','backend:1:abc')
    c=s.submit('a','b','maintenance','original',{'frozen':True})
    clock[0]=1500
    assert retire(s,'a',o['owner_id'],o['generation'],evidence={'host_stopped':True,'worker_stopped':True},error_type='StartupFailure')
    assert s.get(c['command_id'])==c
    assert not retry_allowed(s,'a')
    clock[0]=1800
    assert retry_allowed(s,'a')
    calls=[]
    a=BrowserControlActor(s,'a','b','backend:2:def',{'maintenance':lambda *args:calls.append(1) or {}})
    try:
        assert a.run_next()['command_id']==c['command_id']
        assert a.run_next() is None and calls==[1]
    finally:a.stop_heartbeat()


@pytest.mark.parametrize('state',['running','paused','waiting_human','outcome_unknown'])
def test_unresolved_never_retired(tmp_path,state):
    s=BrowserControlStore(tmp_path/'q.db');o=s.acquire_owner('a','b','backend:1:abc')
    c=s.submit('a','b','manual','one',{})
    with s._db(write=True) as db:db.execute('UPDATE browser_control_commands SET state=? WHERE command_id=?',(state,c['command_id']))
    assert not retire(s,'a',o['owner_id'],o['generation'],evidence={'host_stopped':True,'worker_stopped':True})
    assert read_owner(s,'a')==o


@pytest.mark.parametrize('proof',[{}, {'host_stopped':True}, {'worker_stopped':True}])
def test_partial_proof_is_not_a_release(tmp_path,proof):
    s=BrowserControlStore(tmp_path/'q.db');o=s.acquire_owner('a','b','backend:1:abc')
    assert not retire(s,'a',o['owner_id'],o['generation'],evidence=proof)


def test_budget_persists_across_store_instances(tmp_path):
    p=tmp_path/'q.db';s=BrowserControlStore(p,clock=lambda:1000)
    for n in range(2):
        o=s.acquire_owner('a','b',f'backend:{n+1}:abc')
        assert retire(s,'a',o['owner_id'],o['generation'],evidence={'host_stopped':True,'worker_stopped':True},error_type='OSError')
    assert not retry_allowed(BrowserControlStore(p,clock=lambda:2000),'a')


def test_failed_startup_without_worker_needs_cleanup_proof(tmp_path):
    s=BrowserControlStore(tmp_path/'q.db');a=BrowserControlActor(s,'a','b','backend:1:abc',{})
    a.start()
    session=NS(_proc=None,_worker_stage='importing_playwright',_startup_cleanup_verified=False)
    r=NS(session=session,manual_tasks={},console_tasks={},shutdown=lambda:None)
    try:
        assert not retire_host(a,r)
        session._startup_cleanup_verified=True
        assert retire_host(a,r)
        assert read_owner(s,'a')['state']=='released'
    finally:a.stop_heartbeat()


def test_human_page_is_not_retired(tmp_path):
    s=BrowserControlStore(tmp_path/'q.db');a=BrowserControlActor(s,'a','b','backend:1:abc',{})
    a.start()
    try:
        assert not retire_host(a,NS(manual_tasks={'one':'tab'},console_tasks={}))
    finally:a.stop_heartbeat()


def test_actual_failed_worker_is_reaped_before_retirement(tmp_path):
    import subprocess,sys
    from src.platform_adapter.browser_session import BrowserSession
    from src.platform_adapter.models import BrowserSessionConfig
    session=BrowserSession(BrowserSessionConfig(base_url='http://127.0.0.1',home_url='http://127.0.0.1',
        user_data_dir=str(tmp_path/'profile'),storage_state_path=str(tmp_path/'state.json'),headless=True))
    proc=subprocess.Popen([sys.executable,'-S','-c','import time; time.sleep(60)'],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    session._proc=proc;session._worker_stage='importing_playwright'
    try:
        session._discard_starting_worker()
        assert proc.poll() is not None and session._startup_cleanup_verified
        s=BrowserControlStore(tmp_path/'q.db');a=BrowserControlActor(s,'a','b','backend:1:abc',{})
        a.start()
        r=NS(session=session,manual_tasks={},console_tasks={},shutdown=session.stop)
        try:assert retire_host(a,r,error_type='BrowserWorkerStartupTimeout')
        finally:a.stop_heartbeat()
    finally:
        if proc.poll() is None:proc.kill();proc.wait(timeout=5)


def test_host_idle_after_start_failure_does_not_rpc_missing_worker(tmp_path,monkeypatch):
    from src.operations_accounts import browser_control_runtime as bridge
    from src.operations_accounts import publication_autonomous_reconciliation as reconciliation
    from src.scheduler import account_refresh
    monkeypatch.setattr(account_refresh, 'DB', tmp_path/'refresh.db')
    from dataclasses import dataclass
    @dataclass
    class Context:
        account_uuid:str='a'
        account_key:str='one'
        profile:object=None
        binding:object=None
    context=Context();s=BrowserControlStore(tmp_path/'q.db')
    runtime=NS(resolve=lambda *a,**k:context,profiles=NS(get=lambda _:None),bindings=NS(get=lambda _:None))
    r=NS(context=context,account_uuid='a',account_key='one',manual_tasks={},console_tasks={},
         session=NS(_proc=None,_worker_stage='importing_playwright',_startup_cleanup_verified=True,
                    list_tabs=lambda:pytest.fail('must not RPC failed worker')))
    r.shutdown=lambda:setattr(r,'session',None)
    monkeypatch.setattr(bridge,'_runtime',lambda:runtime)
    monkeypatch.setattr(bridge,'_store',lambda:s)
    monkeypatch.setattr(bridge,'AccountBrowserResource',lambda *args:r)
    monkeypatch.setattr(bridge,'binding_version',lambda _: 'b')
    monkeypatch.setattr(bridge,'_hosts',{})
    monkeypatch.setattr(bridge,'_poll_manual_windows',lambda *args:None)
    monkeypatch.setattr(reconciliation,'queue_continuation',lambda *args:None)
    ticks=iter([0,121])
    monkeypatch.setattr(bridge.time,'monotonic',lambda:next(ticks))
    bridge._host('one')
    assert read_owner(s,'a')['state']=='released'


def test_failed_cleanup_cannot_be_retried_as_empty_resource(tmp_path):
    s=BrowserControlStore(tmp_path/'q.db');a=BrowserControlActor(s,'a','b','backend:1:abc',{})
    a.start()
    r=NS(session=NS(_proc=None,_worker_stage='not_started'),manual_tasks={},console_tasks={})
    def bad_shutdown():
        r.session=None
        raise OSError('cleanup failed after losing reference')
    r.shutdown=bad_shutdown
    try:
        with pytest.raises(OSError):retire_host(a,r)
        assert not retire_host(a,r)
        assert read_owner(s,'a')['state']=='active'
    finally:a.stop_heartbeat()
