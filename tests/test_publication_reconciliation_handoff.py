"""Offline process-adapter faults with real isolated dual SQLite fences.

The public reconciliation API is an explicit transaction adapter here; its
native authorization/CAS behavior is covered by the core module's own tests.
No real process, browser, production database or original receipt is changed.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

import psutil
import pytest

from scripts import handoff_publication_reconciliation as module
from src.operations_accounts.browser_control import BrowserControlStore, _json
from test_idle_headless_handoff import family, SCRIPT, SHA


@pytest.fixture
def setup(tmp_path, monkeypatch):
    root=tmp_path; (root/'data/logs').mkdir(parents=True)
    monkeypatch.setattr(module,'ROOT',root)
    monkeypatch.setattr(module.browser_proof,'ROOT',root)
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return datetime(2026,10,19,10,0,tzinfo=timezone.utc)
    monkeypatch.setattr(module,'datetime',Clock)
    store=BrowserControlStore(root/'data/account_browser_control.db')
    account='review:A'; owner='backend:43940:original-nonce'
    store.acquire_owner(account,'binding-v1',owner)
    original=store.submit(account,'binding-v1','publish','original',{'frozen':True},250)
    queued=store.submit(account,'binding-v1','manual','original-manual',{},200)
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE browser_control_owners SET generation=15")
        db.execute("UPDATE browser_control_commands SET state='outcome_unknown',owner_id=?,generation=15,result=? WHERE command_id=?",
                   (owner,_json({'status':'submission_unknown'}),original['command_id']))
    original=store.get(original['command_id'])
    service,profile=family(root);service.pid=43940;service.started=2000.5
    service.descendants[0].parent=service.pid
    for i,child in enumerate(service.descendants):child.started=2001+i
    service.terminated=0;service.wait_error=None
    service.is_running=lambda:True
    service.cwd=lambda:str(root)
    service.cmdline=lambda:['python.exe',str(root/'scripts/run_streamlit_web.py')]
    def assert_fenced():
        for path in (store.path,root/'data/account_refresh.db'):
            with sqlite3.connect(path,timeout=0) as db:
                with pytest.raises(sqlite3.OperationalError,match='locked'):db.execute('BEGIN IMMEDIATE')
    def terminate():
        assert_fenced();service.terminated+=1
    def wait(timeout):
        assert timeout==5
        if service.wait_error:raise service.wait_error
        service.exited=True
    service.terminate=terminate;service.wait=wait
    def process(pid):
        if getattr(service,'exited',False):raise psutil.NoSuchProcess(pid)
        return service
    monkeypatch.setattr(module.psutil,'Process',process)
    monkeypatch.setattr(module.psutil,'wait_procs',lambda children,timeout:(children,[]))
    monkeypatch.setattr(module.browser_proof,'assert_profile_exited',lambda profile:None)
    monkeypatch.setattr(module,'preflight_chrome_readability',lambda:None)
    (root/'data/logs/streamlit_web.pid').write_text(str(service.pid))
    source=root/'worker.before.py';source.write_text('_PW_SCRIPT='+repr(SCRIPT),encoding='utf8')
    with sqlite3.connect(root/'data/account_refresh.db') as db:
        db.execute('CREATE TABLE account_controls(account_uuid TEXT,account_key TEXT,state TEXT,revision INTEGER,recovery_requested_at REAL,recovery_lease_until REAL,recovery_token TEXT)')
        db.execute('INSERT INTO account_controls VALUES(?,?,?,?,NULL,0,NULL)',(account,'account01','active',42))
        db.execute('CREATE TABLE account_handling_requests(status TEXT)')
        for kind in ('refresh','smart','playback'):
            db.execute(f'CREATE TABLE {kind}_accounts(run_id TEXT,lease_until REAL)')
            db.execute(f'INSERT INTO {kind}_accounts VALUES(NULL,0)')
            db.execute(f'CREATE TABLE {kind}_runs(status TEXT,finished_at REAL)')
            db.execute(f"INSERT INTO {kind}_runs VALUES('failed',1)")
    with sqlite3.connect(root/'data/douyin.db') as db:
        db.execute('CREATE TABLE account_runtime_state(account_uuid TEXT,day_key TEXT,daily_runs INTEGER,lock_owner TEXT,lock_expires_at TEXT)')
        db.execute('INSERT INTO account_runtime_state VALUES(?,?,33,NULL,NULL)',(account,'2026-10-19'))
        db.execute('CREATE TABLE account_runtime_bindings(account_uuid TEXT,browser_profile_dir TEXT)')
        db.execute('INSERT INTO account_runtime_bindings VALUES(?,?)',(account,str(profile)))
    def ref(name,data):
        path=root/name;path.write_bytes(data)
        return {'path':str(path),'sha256':hashlib.sha256(data).hexdigest()}
    auth={'schema':'publication_reconciliation_repair_authorization/20261019/v1','decision_source':'explicit_user_statement',
        'deployment_authorized':True,'utc_day':'2026-10-19','baseline_daily_runs':33,'max_daily_runs':34,
        'additional_reconciliation_runs':1,'active_control_revision':42,'new_upload_authorized':False,
        'new_publish_click_authorized':False,'preserve_original_unknown_snapshot':True,'retain_submission_lock':True,
        'visible_managed_window_authorized':True,'verify_exact_work_before_comment':True,
        'comment_authorization_is_original_prepared':True,'comment_retry_authorized':False,
        'stop_on_human_required_or_unknown':True,'account_uuid':account,'account_key':'account01',
        'original_command_id':original['command_id'],'original_owner_id':owner,'user_statement':'fixture approval',
        'preceding_user_confirmation':'fixture published','original_generation':15,'original_backend_pid':service.pid,
        'original_backend_create_time':service.started,'original_command':ref('original.json',_json(original).encode()),
        'original_journal':ref('journal.jsonl',b'original journal\n'),'original_submission_lock':ref('lock.json',b'original lock'),
        'prepared':ref('prepared.json',b'original prepared')}
    authref=ref('authorization.json',_json(auth).encode())
    monkeypatch.setattr(module,'AUTHORIZATION_SHA256',authref['sha256'])
    evidence=root/'handoff.json'
    monkeypatch.setattr(sys,'argv',['handoff','--authorization-path',authref['path'],'--authorization-sha256',authref['sha256'],
        '--worker-source',str(source),'--worker-script-sha256',SHA,'--browser-profile',str(profile),'--evidence',str(evidence)])
    calls=[];faults={}
    class TransactionAdapter(BrowserControlStore):
        def handoff_publication_reconciliation(self,**kwargs):
            calls.append(kwargs);assert_fenced()
            db=kwargs['connection'];assert db.in_transaction
            assert kwargs['expected_snapshot_sha256']==hashlib.sha256(_json(original).encode()).hexdigest()
            assert kwargs['authorization']==authref
            retirement=json.loads(Path(kwargs['retirement_evidence']['path']).read_text())
            assert retirement['parent_exited'] and retirement['descendants_exited']
            assert type(retirement['finished_at']) is float
            assert retirement['gone_child_ids']==sorted(p.pid for p in service.descendants)
            assert retirement['alive_child_ids']==[]
            db.execute("UPDATE browser_control_owners SET state='released'")
            db.execute('CREATE TABLE adapter_handoff(authorization TEXT)')
            db.execute('INSERT INTO adapter_handoff VALUES(?)',(_json(authref),))
            if faults.get('api'):raise RuntimeError('injected transaction fault')
            return {'restricted':True,'fixture_transaction_adapter':True}
    monkeypatch.setattr(module,'BrowserControlStore',TransactionAdapter)
    return root,store,original,queued,service,calls,faults,evidence


def unchanged(setup):
    root,store,original,queued,*_=setup
    assert store.get(original['command_id'])==original
    assert store.get(queued['command_id'])==queued
    assert (root/'lock.json').read_bytes()==b'original lock'
    assert (root/'journal.jsonl').read_bytes()==b'original journal\n'


def test_success_holds_both_fences_and_preserves_unknown_lock_and_queued_manual(setup):
    root,store,original,queued,service,calls,faults,evidence=setup
    module.main();unchanged(setup)
    assert service.terminated==1 and len(calls)==1
    assert store.snapshot('review:A')['owner']['state']=='released'
    assert json.loads(evidence.read_text())['handoff_committed']
    with pytest.raises(FileExistsError):module.exclusive_json(root/'handoff.RETIREMENT.json',{})


@pytest.mark.parametrize('gate',['snapshot','running','scheduler','runtime','manual'])
def test_unresolved_work_or_changed_snapshot_prevents_any_stop(setup,gate):
    root,store,original,queued,service,calls,_,evidence=setup
    if gate in ('snapshot','running'):
        with sqlite3.connect(store.path) as db:
            db.execute('UPDATE browser_control_commands SET state=? WHERE command_id=?',
                ('failed' if gate=='snapshot' else 'running',original['command_id'] if gate=='snapshot' else queued['command_id']))
    elif gate=='scheduler':
        with sqlite3.connect(root/'data/account_refresh.db') as db:db.execute("UPDATE refresh_accounts SET run_id='inflight'")
    elif gate=='runtime':
        with sqlite3.connect(root/'data/douyin.db') as db:db.execute("UPDATE account_runtime_state SET lock_owner='held'")
    else:
        with sqlite3.connect(root/'data/account_manual_windows.db') as db:
            db.execute('CREATE TABLE manual_window_jobs(state TEXT)');db.execute("INSERT INTO manual_window_jobs VALUES('outcome_unknown')")
    with pytest.raises(RuntimeError):module.main()
    assert service.terminated==0 and calls==[]
    assert store.snapshot('review:A')['owner']['state']=='active'
    assert json.loads(evidence.read_text())['phase']=='rejected_before_stop'


@pytest.mark.parametrize('fault',['parent_timeout','child_alive','late_profile','api_rollback'])
def test_unconfirmed_exit_or_atomic_api_failure_never_releases_or_changes_original(setup,monkeypatch,fault):
    root,store,original,queued,service,calls,faults,evidence=setup
    if fault=='parent_timeout':service.wait_error=psutil.TimeoutExpired(5,pid=service.pid)
    elif fault=='child_alive':monkeypatch.setattr(module.psutil,'wait_procs',lambda children,timeout:(children[:-1],children[-1:]))
    elif fault=='late_profile':
        def late(_):raise RuntimeError('late profile descendant')
        monkeypatch.setattr(module.browser_proof,'assert_profile_exited',late)
    else:faults['api']=True
    with pytest.raises((RuntimeError,psutil.TimeoutExpired)):module.main()
    unchanged(setup)
    assert service.terminated==1
    assert store.snapshot('review:A')['owner']['state']=='active'
    with sqlite3.connect(store.path) as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='adapter_handoff'").fetchone()
    result=json.loads(evidence.read_text());assert not result['handoff_committed']
    assert result['phase']==('stop_unconfirmed' if fault=='parent_timeout' else 'stopped_without_handoff')
    assert len(calls)==int(fault=='api_rollback')


def test_last_process_family_change_is_rejected_before_request_record(setup,monkeypatch):
    root,store,original,queued,service,calls,_,evidence=setup
    native=module.browser_proof.idle_headless_worker_children;count=[]
    def changed(*args):
        children,observed=native(*args);count.append(True)
        if len(count)==2:observed[0]['create_time']+=1
        return children,observed
    monkeypatch.setattr(module.browser_proof,'idle_headless_worker_children',changed)
    with pytest.raises(RuntimeError,match='family changed'):module.main()
    unchanged(setup)
    assert service.terminated==0 and calls==[]
    assert not json.loads(evidence.read_text())['termination_requested']
