"""Six isolated decisions using the existing native v5 SQLite/module seed."""
import copy
import importlib.util
from pathlib import Path
import sqlite3

import pytest

from test_publication_bounded_retry_authorization import ready, account_seed, queue, continuation
from src.operations_accounts import publication_bounded_retry_authorization as bounded
from src.operations_accounts import publication_two_run_authorization as quota


@pytest.fixture
def handoff(ready):
    f=ready
    source=Path(__file__).parents[1]/'scripts/handoff_idle_browser_control.py'
    spec=importlib.util.spec_from_file_location('continuation_handoff_isolated',source)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.ROOT=f.root
    approval,_=quota._load_reference(f.value['user_authorization'])
    return f,m,approval


def sync_runtime(f):
    with sqlite3.connect(f.root/'account.db') as source, sqlite3.connect(f.root/'data/douyin.db') as target:
        source.backup(target)


def check(h,index,*,approval=None):
    f,m,original=h
    sync_runtime(f)
    with sqlite3.connect(f.root/'scheduler.db') as scheduler, sqlite3.connect(f.root/'data/account_browser_control.db') as browser:
        scheduler.execute('BEGIN IMMEDIATE');browser.execute('BEGIN IMMEDIATE')
        return m.check_active_quota_idle(scheduler,approval or original,attempt_index=index,
            approval_reference=f.value['user_authorization'],browser_fence=browser)


def test_registered_slot2_and_slot3_proofs_validate_under_both_fences_at_exact_baselines(handoff,monkeypatch):
    f,m,approval=handoff;before=f.parent_path.read_bytes()
    original=bounded.validate_attempt;observed=[]
    def fenced_validate(reference,index):
        for path in (f.root/'scheduler.db',f.root/'data/account_browser_control.db'):
            with sqlite3.connect(path,timeout=0) as contender:
                with pytest.raises(sqlite3.OperationalError,match='locked'):contender.execute('BEGIN IMMEDIATE')
        observed.append(index)
        return original(reference,index)
    queue(f,1);assert f.actor.run_next()['state']=='failed';continuation(f,2)
    monkeypatch.setattr(bounded,'validate_attempt',fenced_validate)
    second=check(handoff,2)
    assert second['daily_runs']==28 and second['quota_attempt_index']==2 and second['registered_parent']==f.parent
    # A valid proof never permits a different current counter.
    sync_runtime(f)
    with sqlite3.connect(f.root/'data/douyin.db') as runtime:runtime.execute('UPDATE account_runtime_state SET daily_runs=29')
    with sqlite3.connect(f.root/'scheduler.db') as scheduler, sqlite3.connect(f.root/'data/account_browser_control.db') as browser:
        scheduler.execute('BEGIN IMMEDIATE');browser.execute('BEGIN IMMEDIATE')
        with pytest.raises(RuntimeError,match='baseline changed'):
            m.check_active_quota_idle(scheduler,approval,attempt_index=2,
                approval_reference=f.value['user_authorization'],browser_fence=browser)
    # Remove the wrapper before ordinary queue admission (only handoff has both fences).
    monkeypatch.setattr(bounded,'validate_attempt',original)
    queue(f,2);assert f.actor.run_next()['state']=='failed';continuation(f,3)
    monkeypatch.setattr(bounded,'validate_attempt',fenced_validate)
    third=check(handoff,3)
    assert third['daily_runs']==29 and third['quota_attempt_index']==3
    assert observed==[2,2,3] and f.parent_path.read_bytes()==before
    assert approval['baseline_daily_runs']==27 and approval['max_daily_runs']==30


def test_missing_continuation_or_skipped_slot_cannot_deploy_from_remaining_quota(handoff):
    f,_,_=handoff;queue(f,1);f.actor.run_next()
    with pytest.raises(RuntimeError):check(handoff,2)
    continuation(f,2)
    with pytest.raises(RuntimeError):check(handoff,3)


@pytest.mark.parametrize('change',['unknown','human','submission_lock'])
def test_native_predecessor_uncertainty_or_lock_invalidates_existing_proof(handoff,change):
    f,_,_=handoff;command=queue(f,1);f.actor.run_next();continuation(f,2)
    if change=='submission_lock':(f.root/'data/publish_runs'/f'{f.key}.submitted.json').write_text('{}')
    else:
        from src.operations_accounts.browser_control import _json
        with f.store._db(write=True) as db:
            if change=='unknown':db.execute("UPDATE browser_control_commands SET state='outcome_unknown' WHERE command_id=?",(command['command_id'],))
            else:db.execute('UPDATE browser_control_commands SET result=? WHERE command_id=?',
                (_json({'status':'human_required','human_required':True,'success':False}),command['command_id']))
    with pytest.raises(RuntimeError):check(handoff,2)


def test_default_first_attempt_and_legacy_schema_only_one_are_preserved(handoff):
    f,m,approval=handoff
    snapshot=check(handoff,1)
    assert snapshot['daily_runs']==27 and 'quota_attempt_index' not in snapshot
    older=copy.deepcopy(approval);older['schema']='publication_single_retry_user_authorization/20261019/v1'
    with pytest.raises(RuntimeError):check(handoff,2,approval=older)
    sync_runtime(f)
    with sqlite3.connect(f.root/'scheduler.db') as scheduler:
        scheduler.execute('BEGIN IMMEDIATE')
        with pytest.raises(RuntimeError,match='writer fences'):
            m.check_active_quota_idle(scheduler,approval,attempt_index=2,
                approval_reference=f.value['user_authorization'])
