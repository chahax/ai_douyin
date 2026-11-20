"""Handoff adapter decisions; native v8 chain semantics are reviewed separately."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3

import pytest

from src.operations_accounts import publication_two_run_authorization as quota
from src.operations_accounts.browser_control import BrowserControlRejected


@pytest.fixture(scope='module')
def seed(tmp_path_factory):
    project=Path(__file__).parents[1]
    raw=(project/'data/video_generation/h3_dense_office_full_20261018/publication/resume_native_scroll_publish_20261019/USER_AUTHORIZATION.json').read_bytes()
    root=tmp_path_factory.mktemp('native-scroll-handoff-seed');(root/'data').mkdir()
    spec=importlib.util.spec_from_file_location('native_scroll_handoff_isolated',project/'scripts/handoff_idle_browser_control.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.ROOT=root
    path=root/'APPROVAL.json';path.write_bytes(raw);approval=json.loads(raw)
    reference={'path':str(path),'sha256':hashlib.sha256(raw).hexdigest()}
    parent=dict(schema='publication_native_scroll_retry/20261019/v8',scope='publish_only',
        baseline_daily_runs=32,max_daily_runs=33,active_control_revision=42,user_authorization=reference,
        idempotency_keys={'publish':'user-native-scroll-publication-retry-20261019:approved-h3-publication'},
        **{k:approval[k] for k in ('account_uuid','account_key','utc_day','prepared','video')})
    parent_reference={'path':str(root/'PARENT.json'),'sha256':'a'*64}
    registry=root/'REGISTRY_V8.json';registry.write_text(json.dumps(parent_reference),encoding='utf8')
    with sqlite3.connect(root/'data/account_refresh.db') as db:
        db.execute('CREATE TABLE account_controls(account_uuid TEXT,account_key TEXT,state TEXT,revision INTEGER,recovery_requested_at REAL,recovery_lease_until REAL,recovery_token TEXT)')
        db.execute('INSERT INTO account_controls VALUES(?,?,?,42,NULL,0,NULL)',(approval['account_uuid'],approval['account_key'],'active'))
    with sqlite3.connect(root/'data/douyin.db') as db:
        db.execute('CREATE TABLE account_runtime_state(account_uuid TEXT,day_key TEXT,daily_runs INTEGER,lock_owner TEXT)')
        db.execute('INSERT INTO account_runtime_state VALUES(?,?,32,?)',(approval['account_uuid'],approval['utc_day'],''))
    with sqlite3.connect(root/'data/account_browser_control.db') as db:db.execute('CREATE TABLE seed_marker(value TEXT)')
    return m,root,path,raw,approval,reference,parent,parent_reference,registry


def call(seed):
    m,_,path,_,approval,reference,*_=seed
    return m.active_quota_approval(path,reference['sha256'],approval['account_uuid'])


def test_exact_registered_native_v8_call_rechecked_inside_both_fences_at32_and_rejects_index2(seed,monkeypatch):
    m,root,path,raw,approval,reference,parent,parent_reference,registry=seed
    monkeypatch.setattr(quota,'REGISTRY_V8',registry,raising=False);observed=[]
    def validate(value):
        assert value==parent_reference
        for dbpath in (root/'data/account_refresh.db',root/'data/account_browser_control.db'):
            with sqlite3.connect(dbpath,timeout=0) as contender:
                with pytest.raises(sqlite3.OperationalError,match='locked'):contender.execute('BEGIN IMMEDIATE')
        observed.append(value)
        return parent
    monkeypatch.setattr(quota,'validate_authorization',validate)
    with sqlite3.connect(root/'data/account_refresh.db') as scheduler,sqlite3.connect(root/'data/account_browser_control.db') as browser:
        scheduler.execute('BEGIN IMMEDIATE');browser.execute('BEGIN IMMEDIATE')
        checked,ref=call(seed)
        assert checked==approval and ref==reference
        assert m.check_active_quota_idle(scheduler,checked)['daily_runs']==32
        with pytest.raises(RuntimeError):m.check_active_quota_idle(scheduler,checked,attempt_index=2,
            approval_reference=ref,browser_fence=browser)
    assert len(observed)==1 and path.read_bytes()==raw


def test_changed_user_approval_cannot_be_rehashed_to_authorize_another_request(seed,monkeypatch):
    m,root,_,_,approval,*_=seed
    altered=copy.deepcopy(approval);altered['additional_publication_runs']=2
    path=root/'ALTERED.json';path.write_text(json.dumps(altered),encoding='utf8')
    monkeypatch.setattr(quota,'validate_authorization',lambda *_:pytest.fail('Changed approval must fail before native validator'))
    with pytest.raises(RuntimeError,match='exact original user approval'):
        m.active_quota_approval(path,hashlib.sha256(path.read_bytes()).hexdigest(),approval['account_uuid'])


def test_registered_parent_must_bind_exact_original_approval_reference(seed,monkeypatch):
    *_,parent,parent_reference,registry=seed
    changed=copy.deepcopy(parent);changed['user_authorization']['sha256']='b'*64
    monkeypatch.setattr(quota,'REGISTRY_V8',registry,raising=False)
    monkeypatch.setattr(quota,'validate_authorization',lambda *_:changed)
    with pytest.raises(RuntimeError,match='exact approval'):call(seed)


@pytest.mark.parametrize('native_reason',['unknown','human_required'])
def test_native_full_chain_rejection_is_propagated_and_never_replaced_by_cap_fields(seed,monkeypatch,native_reason):
    registry=seed[-1];monkeypatch.setattr(quota,'REGISTRY_V8',registry,raising=False)
    def reject(*_):raise BrowserControlRejected('quota_authorization_invalid',native_reason)
    monkeypatch.setattr(quota,'validate_authorization',reject)
    with pytest.raises(BrowserControlRejected,match=native_reason):call(seed)
