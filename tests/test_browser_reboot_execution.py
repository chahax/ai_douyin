"""Failure boundaries use disposable SQLite and actual abrupt worker exit."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from src.operations_accounts.browser_control import BrowserControlStore, BrowserControlActor, BrowserControlDeferred
from src.operations_accounts import browser_boot_recovery as boot
from src.operations_accounts import browser_execution_journal as journal


@pytest.mark.parametrize('phase', ['before_handler', 'after_entry', 'legacy'])
def test_actual_worker_exit_recovers_only_proven_unexecuted_original_id(tmp_path, monkeypatch, phase):
    path = tmp_path / 'control.db'
    store = BrowserControlStore(path, clock=lambda:500)
    command = store.submit('a','binding','maintenance','one',{'value':'immutable'})
    script = '''
import os, sys
from src.operations_accounts.browser_control import BrowserControlStore
from src.operations_accounts.browser_execution_journal import before_handler
s=BrowserControlStore(sys.argv[1],clock=lambda:500)
o=s.acquire_owner('a','binding','backend:123:abc')
c=s.claim_next('a','binding',o['owner_id'],o['generation'])
if sys.argv[2]=='after_entry':before_handler(s,c['command_id'],o['owner_id'],o['generation'])
if sys.argv[2]=='legacy':
    with s._db(write=True) as db:db.execute('DELETE FROM browser_control_execution')
os._exit(77)
'''
    result = subprocess.run([sys.executable,'-c',script,str(path),phase], cwd=Path(__file__).parents[1],
                            env=dict(os.environ, PYDANTIC_DISABLE_PLUGINS='__all__'), timeout=30, capture_output=True)
    assert result.returncode == 77, result.stderr.decode(errors='replace')
    store.clock = lambda:1000
    monkeypatch.setattr(boot,'_boot_evidence',lambda:dict(boot_time=900,backend_pid=456,backend_create_time=950))
    original = store.get(command['command_id'])
    old_owner = boot.read_owner(store,'a')
    assert store.list_pending_accounts() == ['a']  # No queued task remains.
    assert boot.release_previous_boot_owner(store,'a',old_owner) is (phase == 'before_handler')
    if phase != 'before_handler':
        assert store.get(command['command_id']) == original
        assert boot.read_owner(store,'a') == old_owner
        return
    calls=[]
    actor=BrowserControlActor(store,'a','binding','backend:456:def',{'maintenance':lambda *args:calls.append(1) or {'done':True}})
    try:
        outcome=actor.run_next()
        assert outcome['command_id']==command['command_id'] and outcome['state']=='succeeded'
        assert outcome['payload']==command['payload'] and calls==[1]
        assert actor.run_next() is None
        with store._db() as db:
            audit=json.loads(db.execute('SELECT boot_evidence FROM browser_control_boot_recoveries').fetchone()[0])
            assert audit['unexecuted_commands']==[original]
    finally:
        actor.stop_heartbeat()


def test_quota_wait_has_backoff_and_does_not_repeat_claims(tmp_path):
    clock=[1000.0];calls=[]
    store=BrowserControlStore(tmp_path/'queue.db',clock=lambda:clock[0],owner_ttl=1000)
    def admission(*args):
        calls.append('admission')
        if len(calls)==1:raise BrowserControlDeferred('daily_quota_exceeded','wait')
    actor=BrowserControlActor(store,'a','b','backend:123:abc',{'manual':lambda *args:{'done':True}},admission=admission)
    original=store.submit('a','b','manual','one',{})
    try:
        assert actor.run_next()['state']=='queued'
        before=store.get(original['command_id'])
        clock[0]=1299
        assert actor.run_next() is None
        assert store.get(original['command_id'])==before and calls==['admission']
        clock[0]=1300
        assert actor.run_next()['state']=='succeeded'
        assert calls==['admission','admission']
    finally:actor.stop_heartbeat()


@pytest.mark.parametrize('change', ['request','owner','generation','time','binding'])
def test_changed_or_fresh_evidence_never_replays(tmp_path,monkeypatch,change):
    store=BrowserControlStore(tmp_path/'q.db',clock=lambda:500)
    owner=store.acquire_owner('a','b','backend:123:abc')
    original=store.submit('a','b','manual','one',{})
    store.claim_next('a','b',owner['owner_id'],owner['generation'])
    with store._db(write=True) as db:
        sql={'request':"UPDATE browser_control_execution SET request_sha='changed'",
             'owner':"UPDATE browser_control_execution SET owner_id='changed'",
             'generation':"UPDATE browser_control_execution SET generation=2",
             'time':"UPDATE browser_control_execution SET updated_at=901",
             'binding':"UPDATE browser_control_commands SET binding_version='changed'"}[change]
        db.execute(sql)
    before=store.get(original['command_id'])
    store.clock=lambda:1000
    monkeypatch.setattr(boot,'_boot_evidence',lambda:dict(boot_time=900,backend_pid=456,backend_create_time=950))
    assert not boot.release_previous_boot_owner(store,'a',boot.read_owner(store,'a'))
    assert store.get(original['command_id'])==before


def test_handler_does_not_run_when_durable_entry_commit_fails(tmp_path,monkeypatch):
    store=BrowserControlStore(tmp_path/'q.db')
    store.submit('a','b','manual','one',{})
    def fail(*args):raise OSError('storage unavailable')
    monkeypatch.setattr(journal,'before_handler',fail)
    actor=BrowserControlActor(store,'a','b','backend:123:abc',{'manual':lambda *args:pytest.fail('must persist first')})
    try:
        assert actor.run_next()['state']=='outcome_unknown'
        assert actor.run_next() is None
    finally:actor.stop_heartbeat()


def test_real_pump_reports_old_inflight_without_starting_duplicate_host(tmp_path,monkeypatch):
    from src.operations_accounts import browser_control_runtime as bridge
    store=BrowserControlStore(tmp_path/'q.db',clock=lambda:500)
    owner=store.acquire_owner('a','b','backend:123:abc')
    store.submit('a','b','manual','one',{})
    command=store.claim_next('a','b',owner['owner_id'],owner['generation'])
    journal.before_handler(store,command['command_id'],owner['owner_id'],owner['generation'])
    store.clock=lambda:1000
    monkeypatch.setattr(boot,'_boot_evidence',lambda:dict(boot_time=900,backend_pid=456,backend_create_time=950))
    monkeypatch.setattr(bridge,'enabled',lambda:True)
    monkeypatch.setattr(bridge,'_store',lambda:store)
    monkeypatch.setattr(bridge,'_hosts',{})
    monkeypatch.setattr(bridge,'_runtime',lambda:pytest.fail('blocked account must not start'))
    assert bridge.pump_pending()==0
    assert bridge.pump_status()=={'started':0,'blocked_accounts':['a']}


def test_status_view_never_reads_historical_payload_or_receipt(tmp_path,monkeypatch):
    from contextlib import contextmanager
    import sqlite3
    store=BrowserControlStore(tmp_path/'q.db')
    command=store.submit('a','b','manual','one',{'private':'must not read'})
    original=store._db
    @contextmanager
    def protected(**kwargs):
        assert not kwargs.get('write')
        with original(**kwargs) as db:
            db.set_authorizer(lambda action,table,column,*rest: sqlite3.SQLITE_DENY
                if action==sqlite3.SQLITE_READ and table=='browser_control_commands' and column in {'payload','result'}
                else sqlite3.SQLITE_OK)
            yield db
    monkeypatch.setattr(store,'_db',protected)
    view=store.operational_snapshot('a')
    assert view['commands'][0]['command_id']==command['command_id']
    assert view['commands'][0]['phase']=='legacy_unrecorded'


def test_ui_distinguishes_stale_owner_and_paused_account_from_active_execution(monkeypatch):
    from contextlib import nullcontext
    import streamlit as st
    from src.web import account_browser_control_dashboard as page
    from src.web.components import auth
    from src.operations_accounts import browser_control_runtime as bridge
    labels=[];tables=[]
    monkeypatch.setattr(auth,'get_current_user',lambda:'admin')
    monkeypatch.setattr(bridge,'enabled',lambda:True)
    monkeypatch.setattr(bridge,'operational_snapshot',lambda _:dict(owner={'state':'active','heartbeat':1},
        commands=[dict(command_id='old',kind='manual',state='running',phase='legacy_unrecorded',error_code='old')]))
    monkeypatch.setattr(st,'expander',lambda *args,**kwargs:nullcontext())
    monkeypatch.setattr(st,'caption',labels.append)
    monkeypatch.setattr(st,'dataframe',lambda rows,**kwargs:tables.extend(rows))
    monkeypatch.setattr(st,'warning',lambda message:pytest.fail(message))
    page.render_browser_control({'controls':[dict(account_uuid='a',account_key='one',state='paused')]},'*')
    assert any('账号业务：未恢复' in label and '心跳过期' in label for label in labels)
    assert tables[0]['状态']=='原任务待核对，无法确认仍在执行'
    assert tables[0]['执行阶段']=='旧任务无阶段证据'
