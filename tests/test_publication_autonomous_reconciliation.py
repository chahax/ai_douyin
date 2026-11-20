"""Real control/lease SQLite; fake UI/process identities, isolated v1 fixture."""
import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from test_publication_reconciliation_control import incident,install_ui
from test_publication_bounded_retry_authorization import account_seed,ref,write
from src.operations_accounts import publication_autonomous_reconciliation as auto
from src.operations_accounts import browser_control_runtime as bridge
from src.operations_accounts import publication_two_run_authorization as quota
from src.operations_accounts.browser_control import BrowserControlActor,BrowserControlRejected,_json
from src.scheduler import account_refresh


@pytest.fixture
def authority(incident,monkeypatch):
    f=incident;old=f.auth
    prior=f.store.submit('acct:one',f.original['binding_version'],'publication_reconcile','old-one',{
        'account_uuid':'acct:one','account_key':'one','original_command_id':f.original['command_id'],'reconciliation_authorization':old})
    result={'status':'not_found','publish_evidence':{'post_verified':False},'comment':{'status':'not_submitted'}}
    out=f.root/'data/publication_reconciliations'/prior['command_id'];out.mkdir(parents=True)
    result['evidence_ref']=write(out/'evidence.json',{'schema':'publication_reconciliation_evidence/20261019/v1',
        'original_command_id':f.original['command_id'],'reconciliation_command_id':prior['command_id'],'result':dict(result)})
    with f.store._db(write=True) as db:
        db.execute("UPDATE browser_control_commands SET state='outcome_unknown',owner_id='original-owner',generation=1,result=? WHERE command_id=?",(_json(result),prior['command_id']))
    prior=f.store.get(prior['command_id']);old_auth=json.loads(Path(old['path']).read_text(encoding='utf-8'))
    with sqlite3.connect(account_refresh.DB) as db:
        db.row_factory=sqlite3.Row
        db.execute("UPDATE account_controls SET state='paused',revision=43,error_code='outcome_unknown',consecutive_failures=2 WHERE account_uuid='acct:one'")
        frozen=dict(db.execute("SELECT * FROM account_controls WHERE account_uuid='acct:one'").fetchone())
    auth={'schema':auto.SCHEMA,'decision_source':'explicit_user_statement','user_statement':'无限核查本原作品',
        **{k:old_auth[k] for k in ('account_uuid','account_key','original_command_id','original_command','prepared','original_journal','original_submission_lock')},
        'prior_reconciliation_id':prior['command_id'],'prior_reconciliation':write(f.root/'PRIOR.json',prior),
        'prior_authorization':old,'owner_snapshot':write(f.root/'OWNER.json',f.store.snapshot('acct:one')['owner']),
        'source_owner_id':'original-owner','source_generation':1,'source_backend_pid':987654321,'source_backend_create_time':1.,
        'binding_version':f.original['binding_version'],'minimum_interval_seconds':30,'baseline_daily_runs':34,'active_control_revision':43,
        'control_snapshot':write(f.root/'CONTROL.json',frozen),'allowed_reconciliation_control_state':'paused',
        'allowed_reconciliation_control_revision':43,'resume_known_scheduler_pause_after_verified_publication':True,
        'resume_control_expected_revision':43,'resume_control_target_revision':44,'resume_control_target_state':'active',
        **{k:True for k in ('read_only_reconciliation_unlimited','project_browser_process_termination_authorized','backend_restart_authorized',
        'preserve_original_unknown_snapshots','retain_submission_lock','preserve_daily_runs','ordinary_daily_limit_unchanged',
        'comment_authorization_is_original_prepared','stop_on_unknown_comment_submission')},
        'new_upload_authorized':False,'new_publish_click_authorized':False,'comment_retry_authorized':False}
    f.auth=write(f.root/'AUTONOMOUS.json',auth);monkeypatch.setattr(auto,'AUTH_SHA256',f.auth['sha256']);monkeypatch.setattr(auto,'REGISTRY',f.root/'AUTO_REGISTRY.json')
    auto.register_authorization(f.auth['path'],f.auth['sha256'])
    with f.repo.connection() as db:db.execute('UPDATE account_runtime_state SET daily_runs=34')
    import psutil
    def process(pid):
        if pid==3000:return NS(create_time=lambda:12.)
        raise psutil.NoSuchProcess(pid)
    monkeypatch.setattr(psutil,'Process',process)
    f.prior=prior
    f.kwargs.pop('expected_snapshot_sha256');f.kwargs['authorization']=f.auth
    f.kwargs['expected_snapshots_sha256']={c['command_id']:hashlib.sha256(_json(c).encode()).hexdigest() for c in (f.original,prior)}
    return f


def transfer(f):
    with f.store._db(write=True) as db:return f.store.handoff_publication_reconciliation_v2(**f.kwargs,connection=db)


def actor(f):
    return BrowserControlActor(f.store,'acct:one',f.original['binding_version'],'backend:3000:test',
        {'publication_reconcile':bridge._publication_reconcile},admission=bridge._admission,context=f.resource,
        owner_acquirer=lambda a,b,o:f.store.acquire_reconciliation_owner(a,b,o,f.auth))


def ui(f,monkeypatch,status):
    window=install_ui(f,monkeypatch,status,expected_count=None,comment_status='not_submitted' if status!='verified_published' else None)
    base=bridge.BorrowedSession
    base.stop=lambda self:setattr(window,'own_tab_closed',True)
    return window


def test_infinite_scope_counts_actual_runs_and_pending_retries_still_block_ordinary(authority,monkeypatch):
    f=authority;transfer(f);window=ui(f,monkeypatch,'verification_pending');a=actor(f)
    first=bridge.queue_publication_reconciliation(f.auth)
    assert bridge.queue_publication_reconciliation(f.auth)['command_id']==first['command_id']
    try:
        assert a.run_next()['state']=='outcome_unknown'
        assert f.repo.get_runtime_state('acct:one').daily_runs==35 and window.own_tab_closed and not f.resource.console_tasks
        assert auto.queue_continuation(f.store,'acct:one') is None
        f.store.clock=lambda:__import__('time').time()+31
        second=auto.queue_continuation(f.store,'acct:one')
        assert second['payload']['reconciliation_attempt']==2
        assert a.run_next()['state']=='outcome_unknown' and f.repo.get_runtime_state('acct:one').daily_runs==36
        ordinary=f.store.submit('acct:one',f.original['binding_version'],'read','ordinary',{},1000)
        assert a.run_next() is None and f.store.get(ordinary['command_id'])['state']=='queued'
        assert f.store.get(f.original['command_id'])==f.original and f.store.get(f.prior['command_id'])==f.prior
        assert bridge.operation_daily_limit('publish',20,'acct:one')==20
        a.stop_heartbeat()
        dead=json.loads(Path(f.kwargs['retirement_evidence']['path']).read_text(encoding='utf-8'))
        dead.update(owner_id=a.owner_id,generation=a.generation,original_backend_pid=3000,original_backend_create_time=12.,finished_at=f.store.clock(),
            pid_identity_checks=[{'pid':3000,'expected_create_time':12.,'status':'not_present'}])
        later=dict(f.kwargs,owner_id=a.owner_id,generation=a.generation,retirement_evidence=write(f.root/'NEXT_RETIREMENT.json',dead))
        later['expected_snapshots_sha256']={c['command_id']:hashlib.sha256(_json(c).encode()).hexdigest() for c in f.store.snapshot('acct:one')['commands'] if c['state']=='outcome_unknown'}
        import psutil
        def gone(pid):raise psutil.NoSuchProcess(pid)
        monkeypatch.setattr(psutil,'Process',gone)
        with f.store._db(write=True) as db:f.store.handoff_publication_reconciliation_v2(**later,connection=db)
        assert f.store.pending_reconciliation_authorization('acct:one')==f.auth
        with f.store._db() as db:assert db.execute(f'SELECT count(*) FROM {auto.AUDIT_TABLE}').fetchone()[0]==2
    finally:a.stop_heartbeat()


def test_verified_result_settles_only_exact_readonly_snapshots_and_keeps_lock(authority,monkeypatch):
    # This case explicitly exercises the opt-in legacy cap; the product default
    # now treats daily run counts as audit statistics.
    monkeypatch.setenv('AI_DOUYIN_ENFORCE_DAILY_RUN_LIMIT','1')
    f=authority;transfer(f);window=ui(f,monkeypatch,'verified_published');a=actor(f)
    command=bridge.queue_publication_reconciliation(f.auth)
    try:
        assert a.run_next()['state']=='succeeded' and window.own_tab_closed
        assert quota.control_snapshot('acct:one')['revision']==44
        with sqlite3.connect(account_refresh.DB) as db:assert db.execute("SELECT consecutive_failures FROM account_controls WHERE account_uuid='acct:one'").fetchone()[0]==2
        assert f.store.get(f.prior['command_id'])==f.prior and f.lock.exists()
        from src.scheduler import deployment_maintenance
        maintenance=f.store.submit('acct:one',f.original['binding_version'],'maintenance','held',{'mode':'post-publish','options':{}},0)
        monkeypatch.setattr(deployment_maintenance,'held_command',lambda command:{'authorization':f.auth} if command['command_id']==maintenance['command_id'] else None)
        held=a.run_next()
        assert held['state']=='queued' and held['error_code']=='daily_quota_exceeded' and f.repo.get_runtime_state('acct:one').daily_runs==35
        a.close()
        owner=f.store.acquire_owner('acct:one',f.original['binding_version'],'ordinary-owner')
        f.store.release_owner('acct:one','ordinary-owner',owner['generation'])
        extra=f.store.submit('acct:one',f.original['binding_version'],'publish','unrelated',{})
        with f.store._db(write=True) as db:db.execute("UPDATE browser_control_commands SET state='outcome_unknown' WHERE command_id=?",(extra['command_id'],))
        with pytest.raises(BrowserControlRejected):f.store.acquire_owner('acct:one',f.original['binding_version'],'blocked')
    finally:a.stop_heartbeat()


def test_handoff_rollback_other_unknown_and_changed_cas_are_rejected(authority):
    f=authority
    with pytest.raises(RuntimeError):
        with f.store._db(write=True) as db:
            f.store.handoff_publication_reconciliation_v2(**f.kwargs,connection=db)
            raise RuntimeError('rollback')
    assert f.store.pending_reconciliation_authorization('acct:one') is None
    bad=dict(f.kwargs);bad['expected_snapshots_sha256']={}
    with pytest.raises(BrowserControlRejected):
        with f.store._db(write=True) as db:f.store.handoff_publication_reconciliation_v2(**bad,connection=db)
    extra=f.store.submit('acct:one',f.original['binding_version'],'read','unknown',{})
    with f.store._db(write=True) as db:db.execute("UPDATE browser_control_commands SET state='outcome_unknown' WHERE command_id=?",(extra['command_id'],))
    with pytest.raises(BrowserControlRejected):transfer(f)
    with sqlite3.connect(account_refresh.DB) as db:db.execute("UPDATE account_controls SET reason='new pause' WHERE account_uuid='acct:one'")
    assert not auto.control_allowed(auto.validate_authorization(f.auth)['authorization'])


def test_human_required_retains_own_page_and_stops_autonomous_retries(authority,monkeypatch):
    f=authority;transfer(f);window=ui(f,monkeypatch,'human_required');a=actor(f)
    command=bridge.queue_publication_reconciliation(f.auth)
    try:
        assert a.run_next()['state']=='outcome_unknown'
        assert not getattr(window,'own_tab_closed',False) and f.resource.console_tasks=={command['command_id']:'reconciliation-tab'}
        f.store.clock=lambda:__import__('time').time()+31
        assert auto.queue_continuation(f.store,'acct:one') is None
        assert f.repo.get_runtime_state('acct:one').daily_runs==35 and f.store.get(f.original['command_id'])==f.original
    finally:a.stop_heartbeat()
