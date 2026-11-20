"""Explicit approved deployment can fence active-but-quota-exhausted scheduling."""
import hashlib
import json
import sqlite3

import pytest

from test_idle_browser_control_handoff import isolated
from test_idle_headless_handoff import family, SCRIPT, SHA


@pytest.fixture
def active(isolated,monkeypatch):
    m,service,store,command,args,root=isolated
    original,profile=family(root);service.pid=4321;original.descendants[0].parent=4321
    service.children=lambda recursive=True:original.descendants
    source=root/'worker.before.py';source.write_text('_PW_SCRIPT='+repr(SCRIPT),encoding='utf8')
    with sqlite3.connect(root/'data/douyin.db') as db:
        db.execute('ALTER TABLE account_runtime_state ADD COLUMN account_uuid TEXT')
        db.execute('ALTER TABLE account_runtime_state ADD COLUMN day_key TEXT')
        db.execute('ALTER TABLE account_runtime_state ADD COLUMN daily_runs INTEGER')
        db.execute("UPDATE account_runtime_state SET account_uuid='review:A',day_key='2026-10-19',daily_runs=25")
        db.execute('CREATE TABLE account_runtime_bindings(account_uuid TEXT,browser_profile_dir TEXT)')
        db.execute('INSERT INTO account_runtime_bindings VALUES(?,?)',('review:A',str(profile)))
    with sqlite3.connect(root/'data/account_refresh.db') as db:
        for column,kind in [('account_key','TEXT'),('revision','INTEGER'),('recovery_requested_at','REAL'),
                            ('recovery_lease_until','REAL'),('recovery_token','TEXT')]:
            db.execute(f'ALTER TABLE account_controls ADD COLUMN {column} {kind}')
        db.execute("UPDATE account_controls SET state='active',account_key='A',revision=42,recovery_lease_until=0")
    approval=dict(schema='publication_single_retry_user_authorization/20261019/v1',
        decision_source='explicit_user_statement',user_statement='可以',
        approval_question='是否允许保留原证据、人工结清未决任务并归档旧锁，再追加本视频发布1次，部署修复后继续？',
        account_uuid='review:A',account_key='A',original_command_id='original-known-unknown',
        deployment_authorized=True,operator_close_unknown_publication=True,archive_submission_lock=True,
        additional_publication_runs=1,additional_recovery_runs=0,new_media_authorized=False,
        utc_day='2026-10-19',baseline_daily_runs=25,max_daily_runs=26,active_control_revision=42,
        original_outcome_known=False,retain_original_history=True)
    path=root/'APPROVAL.json';path.write_text(json.dumps(approval,ensure_ascii=False),encoding='utf8')
    args.extend(['--idle-headless-worker','--worker-source',str(source),'--worker-script-sha256',SHA,
        '--browser-profile',str(profile),'--active-quota-idle','--approval-path',str(path),
        '--approval-sha256',hashlib.sha256(path.read_bytes()).hexdigest()])
    monkeypatch.setattr(m.psutil,'wait_procs',lambda children,timeout:(children,[]))
    monkeypatch.setattr(m,'assert_profile_exited',lambda profile:None)
    return m,service,store,command,args,root,path,approval


def assert_writer_fenced(path):
    with sqlite3.connect(path,timeout=0) as contender:
        with pytest.raises(sqlite3.OperationalError,match='locked'):
            contender.execute('BEGIN IMMEDIATE')


def test_active_approved_handoff_holds_both_writer_fences_through_parent_and_children_exit(active,monkeypatch):
    m,service,store,command,args,root,path,approval=active
    phases=[];original_stop=service.terminate
    def check(phase):
        assert_writer_fenced(root/'data/account_refresh.db')
        assert_writer_fenced(root/'data/account_browser_control.db')
        phases.append(phase)
    def stop():
        check('parent_stop');original_stop()
    def children_exit(children,timeout):
        check('children_exit');assert timeout==30
        return children,[]
    service.terminate=stop
    monkeypatch.setattr(m.psutil,'wait_procs',children_exit)
    m.main()
    assert phases==['parent_stop','children_exit'] and service.terminated==1
    with sqlite3.connect(root/'data/account_refresh.db') as db:
        assert db.execute('SELECT state,revision FROM account_controls').fetchone()==('active',42)
    with sqlite3.connect(root/'data/douyin.db') as db:
        assert db.execute('SELECT day_key,daily_runs FROM account_runtime_state').fetchone()==('2026-10-19',25)
    assert store.get(command['command_id'])==command
    assert store.snapshot('review:A')['owner']['state']=='released'
    evidence=json.loads((root/'handoff.json').read_text())
    assert evidence['active_quota_idle_snapshot']['normal_daily_limit']==20
    assert evidence['active_quota_idle_approval']['sha256']==hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize('change',['revision','daily','utc_day','other_active','runtime_lease','recovery_token',
    'business_run','business_unknown','business_lease','recovery_request','manual_unknown','approval_changed','no_headless'])
def test_active_mode_refuses_any_unfrozen_or_nonidle_state_before_stop(active,change):
    m,service,store,command,args,root,path,approval=active
    if change in ('revision','other_active','recovery_token','business_run','business_unknown','business_lease','recovery_request'):
        with sqlite3.connect(root/'data/account_refresh.db') as db:
            if change=='revision':db.execute('UPDATE account_controls SET revision=43')
            elif change=='other_active':db.execute("INSERT INTO account_controls(account_uuid,account_key,state,revision) VALUES('other','B','active',42)")
            elif change=='recovery_token':db.execute("UPDATE account_controls SET recovery_token='original-unresolved'")
            elif change=='business_run':db.execute("UPDATE smart_accounts SET run_id='original',lease_until=1000")
            elif change=='business_unknown':db.execute("UPDATE smart_runs SET status='outcome_unknown'")
            elif change=='business_lease':db.execute('UPDATE smart_accounts SET lease_until=1000')
            else:db.execute("INSERT INTO account_handling_requests VALUES('probing')")
    elif change in ('daily','utc_day','runtime_lease'):
        with sqlite3.connect(root/'data/douyin.db') as db:
            if change=='daily':db.execute('UPDATE account_runtime_state SET daily_runs=24')
            elif change=='utc_day':db.execute("UPDATE account_runtime_state SET day_key='2026-10-20'")
            else:db.execute("UPDATE account_runtime_state SET lock_owner='original'")
    elif change=='manual_unknown':
        with sqlite3.connect(root/'data/account_manual_windows.db') as db:
            db.execute('CREATE TABLE manual_window_jobs(state TEXT)')
            db.execute("INSERT INTO manual_window_jobs VALUES('outcome_unknown')")
    elif change=='approval_changed':path.write_text('{}',encoding='utf8')
    else:args.remove('--idle-headless-worker')
    with pytest.raises(RuntimeError):m.main()
    assert service.terminated==0 and store.snapshot('review:A')['owner']['state']=='active'
    assert store.get(command['command_id'])==command


@pytest.mark.parametrize('field,value',[('deployment_authorized',False),('additional_recovery_runs',1),
    ('additional_publication_runs',2),('active_control_revision',43),('baseline_daily_runs',24),
    ('max_daily_runs',27),('account_uuid','other'),('utc_day','2026-10-20'),
    ('decision_source','model_decision'),('retain_original_history',False),('original_outcome_known',True)])
def test_approval_sha_cannot_turn_a_different_authorization_into_active_handoff(active,field,value):
    m,service,store,command,args,root,path,approval=active
    approval[field]=value;path.write_text(json.dumps(approval),encoding='utf8')
    args[args.index('--approval-sha256')+1]=hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(RuntimeError):m.main()
    assert service.terminated==0


def test_existing_scheduler_writer_is_not_ignored_or_cleared(active):
    m,service,store,command,args,root,path,approval=active
    with sqlite3.connect(root/'data/account_refresh.db') as scheduler:
        scheduler.execute('BEGIN IMMEDIATE')
        with pytest.raises(sqlite3.OperationalError,match='locked'):m.main()
        assert scheduler.in_transaction
    assert service.terminated==0
    assert store.snapshot('review:A')['owner']['state']=='active'


def test_late_approval_change_is_rechecked_under_writer_fences_before_stop(active,monkeypatch):
    m,service,store,command,args,root,path,approval=active
    original=m.idle_headless_worker_children;calls=[]
    def changed(*a):
        result=original(*a);calls.append(True)
        if len(calls)==2:path.write_text('{}',encoding='utf8')
        return result
    monkeypatch.setattr(m,'idle_headless_worker_children',changed)
    with pytest.raises(RuntimeError,match='SHA256 changed'):m.main()
    assert service.terminated==0 and not(root/'handoff.json').exists()
