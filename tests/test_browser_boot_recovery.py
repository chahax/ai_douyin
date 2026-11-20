import json
from types import SimpleNamespace

import pytest

from src.operations_accounts.browser_control import BrowserControlStore,_json
from src.operations_accounts import browser_boot_recovery as boot


@pytest.fixture
def incident(tmp_path,monkeypatch):
    store=BrowserControlStore(tmp_path/'control.db',clock=lambda:1000)
    store.acquire_owner('a','binding','backend:123:abc')
    with store._db(write=True)as db:db.execute('UPDATE browser_control_owners SET heartbeat=500,updated_at=500')
    command=store.submit('a','binding','maintenance','original',{'cursor':'original-value'},0)
    monkeypatch.setattr(boot,'_boot_evidence',lambda:{'boot_time':900,'backend_pid':456,'backend_create_time':950})
    return store,command


def test_previous_boot_idle_release_preserves_original_queue_and_increments_generation(incident):
    store,command=incident;old=boot.read_owner(store,'a')
    assert boot.release_previous_boot_owner(store,'a',old)
    assert store.get(command['command_id'])==command
    with store._db()as db:
        audit=db.execute('SELECT * FROM browser_control_boot_recoveries').fetchone()
        assert json.loads(audit['original_owner'])==old
    assert store.acquire_owner('a','binding','backend:456:def')['generation']==2
    assert not boot.release_previous_boot_owner(store,'a',old)


@pytest.mark.parametrize('state',['running','paused','waiting_human','outcome_unknown'])
def test_unresolved_business_never_reclaimed(incident,state):
    store,command=incident
    with store._db(write=True)as db:db.execute('UPDATE browser_control_commands SET state=?',(state,))
    old=boot.read_owner(store,'a')
    assert not boot.release_previous_boot_owner(store,'a',old)
    assert boot.read_owner(store,'a')==old


@pytest.mark.parametrize('change',['current_boot','owner_changed','foreign_owner','unavailable_boot'])
def test_missing_proof_fresh_or_changed_owner_is_preserved(incident,monkeypatch,change):
    store,_=incident;old=boot.read_owner(store,'a')
    if change=='unavailable_boot':monkeypatch.setattr(boot,'_boot_evidence',lambda:None)
    elif change=='foreign_owner':
        with store._db(write=True)as db:db.execute("UPDATE browser_control_owners SET owner_id='foreign'")
        old=boot.read_owner(store,'a')
    else:
        with store._db(write=True)as db:db.execute('UPDATE browser_control_owners SET heartbeat=?,updated_at=?',((950,950)if change=='current_boot'else(600,600)))
        if change=='current_boot':old=boot.read_owner(store,'a')
    assert not boot.release_previous_boot_owner(store,'a',old)


@pytest.mark.parametrize('changed',[False,True])
def test_settled_unknown_requires_exact_original_sidecar(incident,changed):
    store,command=incident
    with store._db(write=True)as db:db.execute("UPDATE browser_control_commands SET state='outcome_unknown'")
    original=store.get(command['command_id'])
    with store._db(write=True)as db:
        db.execute('CREATE TABLE browser_control_autonomous_reconciliation(account_id TEXT,resolution TEXT)')
        db.execute('INSERT INTO browser_control_autonomous_reconciliation VALUES(?,?)',('a',_json({'settled_readonly_snapshots':[original]})))
        if changed:db.execute("UPDATE browser_control_commands SET error_code='new-evidence'")
    before=store.get(command['command_id'])
    assert boot.release_previous_boot_owner(store,'a',boot.read_owner(store,'a'))is(not changed)
    assert store.get(command['command_id'])==before


def test_real_pump_routes_recovered_queue_to_original_account_host(incident,monkeypatch):
    from src.operations_accounts import browser_control_runtime as bridge
    store,command=incident;started=[]
    monkeypatch.setattr(bridge,'enabled',lambda:True)
    monkeypatch.setattr(bridge,'_store',lambda:store)
    monkeypatch.setattr(bridge,'_hosts',{})
    monkeypatch.setattr(bridge,'_runtime',lambda:SimpleNamespace(profiles=SimpleNamespace(list_active=lambda:[SimpleNamespace(account_uuid='a',account_key='one')])) )
    def thread(**kwargs):return SimpleNamespace(start=lambda:started.append(kwargs))
    monkeypatch.setattr(bridge.threading,'Thread',thread)
    assert bridge.pump_pending()==1
    assert started[0]['args']==('one',)
    assert store.get(command['command_id'])==command
    assert boot.read_owner(store,'a')['state']=='released'


def test_runtime_read_paths_never_select_retirement_audit(incident):
    import sqlite3
    from src.operations_accounts import publication_autonomous_reconciliation as auto
    store,_=incident
    with store._db(write=True)as db:
        db.execute('''CREATE TABLE browser_control_autonomous_reconciliation(
            account_id TEXT PRIMARY KEY,authorization TEXT,original_owner_id TEXT,original_generation INTEGER,
            binding_version TEXT,retirement_evidence TEXT,released_at REAL,new_owner_id TEXT,new_generation INTEGER,
            resolution TEXT,new_owner_create_time REAL)''')
        db.execute('INSERT INTO browser_control_autonomous_reconciliation VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            ('a','{}','old',1,'binding','historical audit retained',600,'new',2,_json({'settled_readonly_snapshots':[]}),900))
        def authorize(action,table,column,*other):
            return sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_READ and table==auto.TABLE and column=='retirement_evidence' else sqlite3.SQLITE_OK
        db.set_authorizer(authorize)
        assert auto.row(db,'a',include_retirement=False)['new_generation']==2
        assert auto.unresolved(store,db,'a',('outcome_unknown',))==[]
        with pytest.raises(sqlite3.DatabaseError):auto.row(db,'a')
        db.set_authorizer(None)
        assert auto.row(db,'a')['retirement_evidence']=='historical audit retained'
    assert store.pending_reconciliation_authorization('a')is None
    assert auto.queue_continuation(store,'a')is None


@pytest.mark.parametrize('change',[None,'native_incomplete','request_changed'])
def test_completed_command_fast_path_requires_immutable_request_and_same_native_proof(incident,tmp_path,monkeypatch,change):
    import hashlib
    from src.operations_accounts import publication_autonomous_reconciliation as auto
    from src.operations_accounts import publication_two_run_authorization as quota
    store,_=incident
    monkeypatch.setattr(quota,'ROOT',tmp_path)
    monkeypatch.setattr(auto,'REGISTRY',tmp_path/'registry.json')
    def freeze(name,value):
        path=tmp_path/name;path.write_text(_json(value),encoding='utf-8')
        return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    command=store.submit('a','binding','publish','original-publish',{'frozen':'request'},100)
    with store._db(write=True)as db:db.execute("UPDATE browser_control_commands SET state='outcome_unknown' WHERE command_id=?",(command['command_id'],))
    before=store.get(command['command_id']);frozen=freeze('original.json',before)
    proof={k:True for k in('post_verified','ai_declaration_verified','fiction_declaration_verified','hashtags_verified','player_verified','ai_active_source_verified')}
    proof.update(post_id='123',publish_url='https://www.douyin.com/video/123',review_status='clear')
    native_proof=dict(proof)
    if change=='native_incomplete':native_proof.pop('player_verified')
    native=freeze('native.json',{'schema':'publication_reconciliation_evidence/20261019/v1','account_uuid':'a',
        'original_command_id':command['command_id'],'reconciliation_command_id':'reconciliation',
        'result':{'status':'verified_published','publish_evidence':native_proof,'comment':{'exact':'comment'}}})
    resolved=dict(proof,status='published',success=True,original_unknown_snapshot=before,reconciliation_evidence=native,
        reconciliation_command_id='reconciliation',comment={'exact':'comment'},settled_readonly_snapshots=[])
    auth=freeze('authority.json',{'schema':auto.SCHEMA,'account_uuid':'a','original_command_id':command['command_id'],'original_command':frozen})
    auto.REGISTRY.write_text(_json(auth),encoding='utf-8')
    with store._db(write=True)as db:
        db.execute("UPDATE browser_control_commands SET state='succeeded',result=? WHERE command_id=?",(_json(resolved),command['command_id']))
        if change=='request_changed':db.execute("UPDATE browser_control_commands SET request_sha='changed' WHERE command_id=?",(command['command_id'],))
    with store._db()as db:
        value=auto._completed_resolution(db,'a')
        assert (value==resolved)if change is None else(value is None)
