"""Isolated v2 handoff adapters; the native authorization is tested by core."""
import hashlib,json,sqlite3,sys
import psutil

import pytest

from scripts import handoff_autonomous_reconciliation as module
from src.operations_accounts.browser_control import BrowserControlStore,_json
from src.operations_accounts import publication_autonomous_reconciliation as authority
from test_publication_reconciliation_handoff import setup


@pytest.fixture
def autonomous(setup,monkeypatch):
    root,store,original,oldmanual,service,calls,faults,evidence=setup
    monkeypatch.setattr(module,'ROOT',root)
    monkeypatch.setattr(module,'datetime',module.v1.datetime)
    prior=store.submit('review:A','binding-v1','publication_reconcile','old-reconciliation',{},400)
    maintenance=store.submit('review:A','binding-v1','maintenance','original-maintenance',{'mode':'post-publish','options':{}},0)
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE browser_control_commands SET state='outcome_unknown',owner_id=?,generation=15 WHERE command_id=?",
            ('backend:43940:original-nonce',prior['command_id']))
    prior=store.get(prior['command_id'])
    with sqlite3.connect(root/'data/douyin.db') as db:db.execute('UPDATE account_runtime_state SET daily_runs=34')
    with sqlite3.connect(root/'data/account_refresh.db') as db:
        db.row_factory=sqlite3.Row
        db.execute('ALTER TABLE account_controls ADD COLUMN error_code TEXT')
        db.execute("UPDATE account_controls SET state='paused',revision=43,error_code='outcome_unknown'")
        control=dict(db.execute('SELECT * FROM account_controls').fetchone())
        db.execute('DROP TABLE refresh_accounts');db.execute('DROP TABLE refresh_runs')
        db.execute('CREATE TABLE refresh_accounts(account_uuid TEXT,account_key TEXT,next_due REAL,lease_until REAL,run_id TEXT)')
        db.execute("INSERT INTO refresh_accounts VALUES('review:A','account01',50,100,'original-refresh')")
        db.execute('CREATE TABLE refresh_runs(run_id TEXT,account_uuid TEXT,account_key TEXT,status TEXT,finished_at REAL)')
        db.execute("INSERT INTO refresh_runs VALUES('original-refresh','review:A','account01','outcome_unknown',NULL)")
        frozen_run=dict(db.execute('SELECT * FROM refresh_runs').fetchone())
        frozen_cursor=dict(db.execute('SELECT * FROM refresh_accounts').fetchone())
    def ref(name,value):
        path=root/name;path.write_text(_json(value),encoding='utf8')
        return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    refs={'maintenance_command':ref('MAINTENANCE.json',maintenance),'refresh_run':ref('RUN.json',frozen_run),
          'refresh_account':ref('CURSOR.json',frozen_cursor)}
    refs_ref=ref('REFS.json',refs)
    oldargs=list(sys.argv);profile=oldargs[oldargs.index('--browser-profile')+1]
    auth={'schema':'publication_autonomous_reconciliation_authorization/v2','project_browser_process_termination_authorized':True,
        'backend_restart_authorized':True,'baseline_daily_runs':34,'active_control_revision':43,
        'allowed_reconciliation_control_state':'paused','allowed_reconciliation_control_revision':43,
        'original_command':ref('PUBLISH.json',original),'prior_reconciliation':ref('PRIOR.json',prior),
        'control_snapshot':ref('CONTROL.json',control),'original_command_id':original['command_id'],'prior_reconciliation_id':prior['command_id'],
        'account_uuid':'review:A','account_key':'account01','source_owner_id':'backend:43940:original-nonce',
        'source_generation':15,'binding_version':'binding-v1','browser_profile':profile,
        'source_backend_pid':service.pid,'source_backend_create_time':service.started}
    authref=ref('AUTH_V2.json',auth)
    monkeypatch.setattr(module,'AUTH_SHA',authref['sha256'])
    monkeypatch.setattr(module,'MAINTENANCE_ID',maintenance['command_id']);monkeypatch.setattr(module,'REFRESH_ID','original-refresh')
    monkeypatch.setattr(authority,'validate_authorization',lambda reference: {'fixture_native_authorization_adapter':True})
    sys.argv[:]=['handoff-v2','--authorization-path',authref['path'],'--authorization-sha256',authref['sha256'],
        '--maintenance-refs',refs_ref['path'],'--maintenance-refs-sha256',refs_ref['sha256'],
        '--worker-source',oldargs[oldargs.index('--worker-source')+1],
        '--worker-script-sha256',oldargs[oldargs.index('--worker-script-sha256')+1],'--evidence',str(evidence)]
    # Explicit authority allows the same exact project tree with a visible window.
    service.descendants[4].command.remove('--headless')
    apicalls=[]
    class Adapter(BrowserControlStore):
        def handoff_publication_reconciliation_v2(self,**kwargs):
            apicalls.append(kwargs)
            for path in (self.path,root/'data/account_refresh.db'):
                with sqlite3.connect(path,timeout=0) as db:
                    with pytest.raises(sqlite3.OperationalError,match='locked'):db.execute('BEGIN IMMEDIATE')
            current=[BrowserControlStore._command(row) for row in kwargs['connection'].execute("SELECT * FROM browser_control_commands WHERE state='outcome_unknown'")]
            assert kwargs['expected_snapshots_sha256']=={c['command_id']:hashlib.sha256(_json(c).encode()).hexdigest() for c in current}
            kwargs['connection'].execute("UPDATE browser_control_owners SET state='released'")
            if faults.get('v2_api'):raise RuntimeError('v2 injected transaction fault')
            return {'fixture_transaction_adapter':True}
    monkeypatch.setattr(module,'BrowserControlStore',Adapter)
    return setup,prior,maintenance,frozen_run,frozen_cursor,apicalls


@pytest.mark.parametrize('api_fail',[False,True])
def test_visible_project_eof_handoff_or_rollback_preserves_two_unknowns_and_durable_original_wait(autonomous,api_fail):
    setup,prior,maintenance,run,cursor,apicalls=autonomous
    root,store,original,manual,service,_,faults,evidence=setup
    faults['v2_api']=api_fail
    if api_fail:
        with pytest.raises(RuntimeError,match='v2 injected'):module.main()
    else:module.main()
    assert service.terminated==1 and len(apicalls)==1
    for command in (original,prior,maintenance,manual):assert store.get(command['command_id'])==command
    assert store.snapshot('review:A')['owner']['persisted_state']==('active' if api_fail else 'released')
    with sqlite3.connect(root/'data/account_refresh.db') as db:
        db.row_factory=sqlite3.Row
        assert dict(db.execute('SELECT * FROM refresh_runs').fetchone())==run
        assert dict(db.execute('SELECT * FROM refresh_accounts').fetchone())==cursor
        assert db.execute('SELECT state FROM deployment_maintenance_holds').fetchone()[0]=='awaiting_original'
    assert (root/'lock.json').read_bytes()==b'original lock'


def test_foreign_browser_profile_rejects_before_stop_and_before_creating_hold(autonomous):
    setup,*_=autonomous
    root,store,original,manual,service,_,_,evidence=setup
    service.descendants[4].command[-1]='--user-data-dir='+str(root/'unrelated-profile')
    with pytest.raises(RuntimeError,match='original account profile'):module.main()
    assert service.terminated==0
    with sqlite3.connect(root/'data/account_refresh.db') as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='deployment_maintenance_holds'").fetchone()


def test_same_authority_redeployment_uses_audited_successor_all_native_unknowns_and_same_hold(autonomous,monkeypatch):
    setup,prior,maintenance,run,cursor,apicalls=autonomous
    root,store,original,manual,service,_,faults,evidence=setup
    module.main()
    with sqlite3.connect(root/'data/account_refresh.db') as db:
        before_hold=db.execute('SELECT * FROM deployment_maintenance_holds').fetchone()
    reference={'path':sys.argv[sys.argv.index('--authorization-path')+1],'sha256':sys.argv[sys.argv.index('--authorization-sha256')+1]}
    successor='backend:43940:successor-nonce';service.started+=50;service.exited=False
    for child in service.descendants:child.started+=50
    def current(pid):
        if service.exited:raise psutil.NoSuchProcess(pid)
        return service
    monkeypatch.setattr(module.psutil,'Process',current)
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE browser_control_owners SET owner_id=?,generation=16,state='active'",(successor,))
        db.execute(f'CREATE TABLE {authority.TABLE}(account_id TEXT,authorization TEXT,new_owner_id TEXT,new_generation INTEGER,new_owner_create_time REAL)')
        db.execute(f'INSERT INTO {authority.TABLE} VALUES(?,?,?,?,?)',('review:A',_json(reference),successor,16,service.started))
    attempt=store.submit('review:A','binding-v1','publication_reconcile','new-native-attempt',{'reconciliation_authorization':reference},400)
    result={'status':'not_found','publish_evidence':{},'comment':{'status':'not_submitted'}}
    proof=root/'native-attempt.json';proof.write_text(_json({'reconciliation_command_id':attempt['command_id'],'result':result}),encoding='utf8')
    result['evidence_ref']={'path':str(proof),'sha256':hashlib.sha256(proof.read_bytes()).hexdigest()}
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE browser_control_commands SET state='outcome_unknown',result=?,owner_id=?,generation=16 WHERE command_id=?",(_json(result),successor,attempt['command_id']))
    with sqlite3.connect(root/'data/douyin.db') as db:db.execute('UPDATE account_runtime_state SET daily_runs=35')
    sys.argv[sys.argv.index('--evidence')+1]=str(root/'HANDOFF_SECOND.json')
    module.main()
    assert service.terminated==2 and len(apicalls)==2
    assert apicalls[-1]['owner_id']==successor and apicalls[-1]['generation']==16
    assert set(apicalls[-1]['expected_snapshots_sha256'])=={original['command_id'],prior['command_id'],attempt['command_id']}
    with sqlite3.connect(root/'data/account_refresh.db') as db:
        assert db.execute('SELECT * FROM deployment_maintenance_holds').fetchone()==before_hold
    record=json.loads((root/'HANDOFF_SECOND.json').read_text())
    assert record['maintenance_hold']['reused_existing'] is True
    assert record['original_runtime_counter']['daily_runs']==35
