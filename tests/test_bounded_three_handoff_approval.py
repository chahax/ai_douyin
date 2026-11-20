"""Six focused decisions; one closed SQLite seed, no browser/main repetition."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3

import pytest


def ref(root,name,value):
    path=root/name;path.write_text(json.dumps(value),encoding='utf8')
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


@pytest.fixture(scope='module')
def seed(tmp_path_factory):
    root=tmp_path_factory.mktemp('bounded-handoff-seed')
    source=Path(__file__).parents[1]/'scripts/handoff_idle_browser_control.py'
    spec=importlib.util.spec_from_file_location('bounded_handoff_seed',source)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.ROOT=root
    (root/'data').mkdir()
    with sqlite3.connect(root/'data/account_refresh.db') as db:
        db.execute('CREATE TABLE account_controls(account_uuid TEXT,account_key TEXT,state TEXT,revision INTEGER,recovery_requested_at REAL,recovery_lease_until REAL,recovery_token TEXT)')
        db.execute("INSERT INTO account_controls VALUES('A','account01','active',42,NULL,0,NULL)")
    with sqlite3.connect(root/'data/douyin.db') as db:
        db.execute('CREATE TABLE account_runtime_state(account_uuid TEXT,day_key TEXT,daily_runs INTEGER,lock_owner TEXT)')
        db.execute("INSERT INTO account_runtime_state VALUES('A','2026-10-19',27,'')")
    film={'prepared':{'path':str(root/'prepared.json'),'sha256':'1'*64},
          'video':{'path':str(root/'film.mp4'),'sha256':'2'*64}}
    grant=dict(schema='publication_fast_upload_retry/20261019/v4',scope='publish_only',
        account_uuid='A',account_key='account01',utc_day='2026-10-19',baseline_daily_runs=26,
        max_daily_runs=27,active_control_revision=42,**film)
    bounded=dict(schema='publication_bounded_retry_user_authorization/20261019/v1',
        decision_source='explicit_user_statement',user_statement='可以',approval_question='最多3次，仅提交前失败修复续行，未知或人工停',
        account_uuid='A',account_key='account01',deployment_authorized=True,additional_publication_runs=3,
        additional_recovery_runs=0,new_media_authorized=False,utc_day='2026-10-19',baseline_daily_runs=27,
        max_daily_runs=30,active_control_revision=42,only_known_pre_submission_failures=True,
        stop_on_unknown=True,stop_on_human_required=True,retain_original_history=True,
        previous_authorization=ref(root,'V4.json',grant),previous_command_id='known-failed',
        previous_command=ref(root,'command.json',{'command_id':'known-failed','account_id':'A',
            'kind':'publish','state':'failed','result':{'status':'upload_failed'}}),
        previous_journal=ref(root,'journal.json',{'stage':'upload_failed'}),
        previous_final_state=ref(root,'final.json',{'status':'failed'}),**film)
    return m,root,bounded,grant


def validate(seed,value,name):
    m,root,*_=seed;reference=ref(root,name,value)
    return m.active_quota_approval(reference['path'],reference['sha256'],'A')[0]


def test_exact_27_30_three_scope_and_existing_active_quota_gate_keep_state_unchanged(seed):
    m,root,bounded,_=seed;value=validate(seed,bounded,'approved.json')
    with sqlite3.connect(root/'data/account_refresh.db') as control:
        control.execute('BEGIN IMMEDIATE')
        snapshot=m.check_active_quota_idle(control,value)
        with sqlite3.connect(root/'data/account_refresh.db',timeout=0) as contender:
            with pytest.raises(sqlite3.OperationalError,match='locked'):contender.execute('BEGIN IMMEDIATE')
        assert control.execute('SELECT state,revision FROM account_controls').fetchone()==('active',42)
    assert snapshot['daily_runs']==27 and snapshot['normal_daily_limit']==20


def test_exact_three_scope_never_accepts_more_quota_recovery_or_missing_stop_conditions(seed):
    for index,(field,value) in enumerate([('max_daily_runs',31),('additional_publication_runs',4),
            ('additional_recovery_runs',1),('only_known_pre_submission_failures',False),
            ('stop_on_unknown',False),('stop_on_human_required',False)]):
        variant=copy.deepcopy(seed[2]);variant[field]=value
        with pytest.raises(RuntimeError):validate(seed,variant,f'scope-{index}.json')


def test_unknown_previous_or_another_film_cannot_continue_known_failure_chain(seed):
    _,root,bounded,_=seed
    for index,kind in enumerate(('unknown','other_film')):
        variant=copy.deepcopy(bounded)
        if kind=='unknown':
            variant['previous_command']=ref(root,'unknown.json',{'command_id':'known-failed','account_id':'A',
                'kind':'publish','state':'outcome_unknown','result':{'status':'upload_failed'}})
        else:variant['video']['sha256']='3'*64
        with pytest.raises(RuntimeError):validate(seed,variant,f'chain-{index}.json')


def test_previous_v3_and_v4_approval_modes_remain_exact(seed):
    _,root,bounded,grant=seed
    v4=copy.deepcopy(bounded)
    for key in ('only_known_pre_submission_failures','stop_on_unknown','stop_on_human_required'):v4.pop(key)
    old_grant=copy.deepcopy(grant);old_grant.update(schema='publication_single_retry/20261019/v3',baseline_daily_runs=25,max_daily_runs=26)
    v4.update(schema='publication_fast_upload_retry_user_authorization/20261019/v1',user_statement='允许',
        baseline_daily_runs=26,max_daily_runs=27,additional_publication_runs=1,
        previous_authorization=ref(root,'V3.json',old_grant))
    assert validate(seed,v4,'old-v4.json')['baseline_daily_runs']==26
    v3=copy.deepcopy(v4)
    v3.update(schema='publication_single_retry_user_authorization/20261019/v1',user_statement='可以',
        baseline_daily_runs=25,max_daily_runs=26,operator_close_unknown_publication=True,
        archive_submission_lock=True,original_outcome_known=False,original_command_id='old-unknown')
    assert validate(seed,v3,'old-v3.json')['baseline_daily_runs']==25


def test_27_approval_does_not_accept_other_runtime_baseline(seed):
    m,root,bounded,_=seed;value=validate(seed,bounded,'daily-approval.json')
    try:
        with sqlite3.connect(root/'data/douyin.db') as runtime:runtime.execute('UPDATE account_runtime_state SET daily_runs=26')
        with sqlite3.connect(root/'data/account_refresh.db') as control:
            control.execute('BEGIN IMMEDIATE')
            with pytest.raises(RuntimeError,match='baseline changed'):m.check_active_quota_idle(control,value)
    finally:
        with sqlite3.connect(root/'data/douyin.db') as runtime:runtime.execute('UPDATE account_runtime_state SET daily_runs=27')


def test_existing_writer_fence_requirement_is_not_bypassed_by_three_approval(seed):
    m,root,bounded,_=seed;value=validate(seed,bounded,'fence-approval.json')
    with sqlite3.connect(root/'data/account_refresh.db') as control:
        with pytest.raises(RuntimeError,match='writer fence'):m.check_active_quota_idle(control,value)
