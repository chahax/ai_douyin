import json
import pytest

from test_account_handling_continuation import backend, seed_run, pause, complete
from src.operations_accounts.browser_control import BrowserControlStore
from src.scheduler import browser_task_tracking as tracking
from src.web.account_exception_notice import _handling_state


@pytest.fixture
def waiting(backend,tmp_path):
    ar=backend; path=tmp_path/'account_refresh.db'
    run=seed_run(ar,path,status='waiting_original',finished_at=None)
    with ar.connect(path)as db:
        db.execute("UPDATE refresh_runs SET detail=? WHERE run_id=?",(json.dumps({'error_code':'queue_wait_timeout'}),run))
        db.execute("UPDATE refresh_accounts SET run_id=?,lease_until=500 WHERE account_uuid='A'",(run,))
    store=BrowserControlStore(tmp_path/'browser.db',clock=lambda:1000)
    command=store.submit('A','binding','maintenance','original',{'mode':'post-publish','account_key':'a','account_uuid':'A','options':{}},0)
    tracking.attach(command,store.path,run_id=run,path=path)
    pause(ar,path)
    return ar,path,store,command,run


def test_completion_verifies_identity_then_releases_only_original_queued_refresh(waiting):
    ar,path,store,command,run=waiting
    before=ar.snapshot(path)
    assert _handling_state(before,'A','a')[2]
    assert complete(ar,path)['accepted']
    requested=ar.snapshot(path)
    target=json.loads(requested['handling_requests'][0]['targets_json'])[0]
    assert target['status']=='waiting_original' and target['queued_wait']['command_id']==command['command_id']
    token=ar._claim_recovery('A','a',path=path)
    assert token and ar._finish_recovery('A','a',token,healthy=True,status='active',path=path)
    after=ar.snapshot(path)
    assert after['controls'][0]['state']=='active'
    assert after['accounts']==before['accounts'] and after['runs']==before['runs']
    assert store.get(command['command_id'])==command


@pytest.mark.parametrize('change',['running','unknown','entered','replaced','disabled'])
def test_queue_exception_never_covers_started_changed_or_disabled_work(waiting,change):
    ar,path,store,command,run=waiting
    if change in {'running','unknown','replaced'}:
        with store._db(write=True)as db:
            if change=='replaced':db.execute("UPDATE browser_control_commands SET request_sha='changed'")
            else:db.execute('UPDATE browser_control_commands SET state=?',('running'if change=='running'else'outcome_unknown',))
    elif change=='entered':
        from src.operations_accounts.browser_execution_journal import record
        with store._db(write=True)as db:record(db,dict(command,owner_id='original',generation=1),'handler_entered',1000,entered=True)
    else:
        with ar.connect(path)as db:db.execute('UPDATE refresh_policy SET enabled=0')
    assert not complete(ar,path)['accepted']
    assert not ar.snapshot(path)['queued_refresh_waits']


def test_original_queue_changing_during_probe_invalidates_completion(waiting):
    ar,path,store,command,run=waiting
    assert complete(ar,path)['accepted']
    token=ar._claim_recovery('A','a',path=path)
    with store._db(write=True)as db:db.execute("UPDATE browser_control_commands SET request_sha='changed'")
    assert not ar._finish_recovery('A','a',token,healthy=True,status='active',path=path)
    assert ar.snapshot(path)['controls'][0]['state']=='paused'


def test_original_maintenance_receipt_advances_original_plan_once_after_identity_recovery(waiting):
    from src.operations_accounts.browser_control import BrowserControlActor
    ar,path,store,command,run=waiting
    assert complete(ar,path)['accepted']
    token=ar._claim_recovery('A','a',path=path)
    assert ar._finish_recovery('A','a',token,healthy=True,status='active',path=path)
    value={'status':'completed','message':'原同步成功','run_id':'maintenance:original',
        'synced_videos':1,'synced_comments':0,'comment_sync_failures':0,'login_healthy':True,'error_code':''}
    actor=BrowserControlActor(store,'A','binding','backend:123:abc',
        {'maintenance':lambda ctx,payload:{'maintenance_result':value}}).start()
    try:
        assert actor.run_next()['command_id']==command['command_id']
        tracking.reconcile(path)
        after=ar.snapshot(path)
        assert after['runs'][0]['run_id']==run and after['runs'][0]['status']=='completed'
        assert after['accounts'][0]['run_id'] is None
        tracking.reconcile(path)
        assert ar.snapshot(path)['accounts']==after['accounts']
        assert len(store.snapshot('A')['commands'])==1
    finally:
        actor.close()
