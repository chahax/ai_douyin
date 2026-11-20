"""A restart waits the same unexecuted command and uses the original finisher."""
import json
import sqlite3

import pytest

from src.operations_accounts.browser_control import BrowserControlStore,_json
from src.scheduler import account_refresh as refresh
from src.scheduler import deployment_maintenance as module


@pytest.fixture
def held(tmp_path):
    path=tmp_path/'refresh.db';browser_path=tmp_path/'browser.db'
    store=BrowserControlStore(browser_path);store.acquire_owner('review:A','binding','test-owner')
    command=store.submit('review:A','binding','maintenance','original-only',{'mode':'post-publish','options':{}},0)
    with refresh.connect(path) as control,sqlite3.connect(browser_path) as browser:
        control.execute('BEGIN IMMEDIATE');browser.execute('BEGIN IMMEDIATE');browser.row_factory=sqlite3.Row
        control.execute("INSERT INTO account_controls(account_uuid,account_key,state,reason,error_code,revision,updated_at) VALUES('review:A','account01','paused','Original wait expired','outcome_unknown',43,1)")
        control.execute("INSERT INTO refresh_accounts VALUES('review:A','account01',50,100,'original-refresh')")
        control.execute("INSERT INTO refresh_runs(run_id,account_uuid,account_key,reason,started_at,status) VALUES('original-refresh','review:A','account01','periodic',1,'outcome_unknown')")
        original=dict(control.execute('SELECT * FROM refresh_runs').fetchone())
        module.hold_queued(control,browser,authorization={'fixture':True},command_id=command['command_id'],run_id='original-refresh',
            account_uuid='review:A',account_key='account01',browser_path=browser_path)
    return path,store,command,original


def test_restart_waits_original_then_crash_after_real_finish_is_idempotently_settled(held,monkeypatch):
    path,store,command,original=held
    with refresh.connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        assert refresh._gate(db,'review:A','account01',10000) is False
        assert dict(db.execute('SELECT * FROM refresh_runs').fetchone())==original
        assert db.execute('SELECT revision FROM account_controls').fetchone()[0]==43
        # Simulate the separate verified-publication control transition: the
        # hold must still prevent an expired original wait becoming new unknown.
        db.execute("UPDATE account_controls SET state='active',revision=44")
        assert refresh._gate(db,'review:A','account01',10000) is False
        assert tuple(db.execute('SELECT state,revision FROM account_controls').fetchone())==('active',44)
        db.execute("UPDATE account_controls SET state='paused',revision=43")
    assert module.resume_pending(path=path)[0]['state']=='waiting_original'
    assert module.resume_pending(path=path)[0]['command_id']==command['command_id']
    assert store.get(command['command_id'])==command
    assert module.held_command(command,path=path)['run_id']=='original-refresh'
    assert module.held_command(dict(command,payload={'mode':'wrong'}),path=path) is None
    claim=store.claim_next('review:A','binding','test-owner',1)
    assert module.held_command(claim,path=path)['command_snapshot']==command
    native={'status':'completed','message':'Original actual result','run_id':'native-maintenance-result',
        'synced_videos':3,'synced_comments':2,'comment_sync_failures':0,'login_healthy':True,'error_code':''}
    store.transition(claim['command_id'],'test-owner',1,'succeeded',result={'maintenance_result':native})
    finish=refresh.finish;calls=[]
    def crash_after_finish(*args,**kwargs):
        calls.append(args[0]);finish(*args,**kwargs);raise RuntimeError('after durable original finish')
    monkeypatch.setattr(refresh,'finish',crash_after_finish)
    with pytest.raises(RuntimeError,match='durable original finish'):module.resume_pending(path=path)
    assert calls==['original-refresh']
    assert module.resume_pending(path=path)==[{'command_id':command['command_id'],'run_id':'original-refresh','state':'settled'}]
    assert calls==['original-refresh'] and module.resume_pending(path=path)==[]
    with refresh.connect(path) as db:
        run=dict(db.execute('SELECT * FROM refresh_runs').fetchone())
        assert run['status']=='completed' and json.loads(run['detail'])['maintenance_run_id']=='native-maintenance-result'
        assert db.execute('SELECT run_id FROM refresh_accounts').fetchone()[0] is None
        assert tuple(db.execute('SELECT state,revision FROM account_controls').fetchone())==('paused',43)
        assert db.execute('SELECT COUNT(*) FROM refresh_runs').fetchone()[0]==1
    assert len(store.snapshot('review:A')['commands'])==1


def test_changed_task_identity_never_finishes_or_replaces_original_unknown_refresh(held):
    path,store,command,original=held
    with sqlite3.connect(store.path) as db:
        db.execute('UPDATE browser_control_commands SET payload=? WHERE command_id=?',(_json({'mode':'different-task'}),command['command_id']))
    with pytest.raises(RuntimeError,match='identity changed'):module.resume_pending(path=path)
    with refresh.connect(path) as db:
        assert dict(db.execute('SELECT * FROM refresh_runs').fetchone())==original
        assert db.execute('SELECT state FROM deployment_maintenance_holds').fetchone()[0]=='awaiting_original'
