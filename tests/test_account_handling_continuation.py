"""Human completion records intent; only an unchanged original-identity probe releases it."""
import importlib.util
import json
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def backend(monkeypatch):
    ar = load('isolated_handling_continuation', 'src/scheduler/account_refresh.py')
    ap = load('isolated_handling_playback', 'src/scheduler/account_playback.py')
    monkeypatch.setitem(sys.modules, 'src.scheduler.account_playback', ap)
    monkeypatch.setattr(ar, 'time', SimpleNamespace(time=lambda: 1000.0))
    return ar


def configure_playback(ar, db, uuid='A', key='a', enabled=True, **kwargs):
    ar.set_playback_policy(uuid, key, enabled, authorization_reference='user-20261018', path=db, **kwargs)


def seed_run(ar, db, kind='refresh', status='blocked', *, account_uuid='A', account_key='a', suffix='', finished_at=900):
    run_id = kind + suffix
    with ar.connect(db) as connection:
        connection.execute(f'INSERT OR REPLACE INTO {kind}_accounts(account_uuid,account_key,next_due) VALUES(?,?,?)',
                           (account_uuid, account_key, 9999))
        fields = 'run_id,account_uuid,account_key,reason,started_at,finished_at,status,detail'
        values = [run_id, account_uuid, account_key, 'periodic', 100 if not suffix else 200, finished_at,
                  status, json.dumps({'error_code': 'human_required'})]
        if kind == 'playback':
            fields += ',policy_snapshot'
            values.append('{}')
        connection.execute(f'INSERT INTO {kind}_runs({fields}) VALUES({",".join("?" for _ in values)})', values)
    return run_id


def pause(ar, db):
    with ar.connect(db) as connection:
        ar._pause(connection, 'A', 'a', '需要人工完成安全验证', 'human_required', 950)


def complete(ar, db):
    return ar.complete_account_handling('A', 'a', handled_by='admin', path=db)


def test_completion_only_registers_and_verified_identity_releases_latest_failed_plans(backend, tmp_path, monkeypatch):
    ar = backend
    db = tmp_path / 'handling.db'
    configure_playback(ar, db)
    for kind in ('refresh', 'smart', 'playback'):
        seed_run(ar, db, kind)
    pause(ar, db)
    original = ar.snapshot(db)
    response = complete(ar, db)
    assert response['accepted'] and response['state'] == 'recovery_requested'
    pending = ar.snapshot(db)
    assert pending['accounts'] == original['accounts']
    assert pending['runs'] == original['runs']
    request = pending['handling_requests'][0]
    assert request['handled_by'] == 'admin' and request['status'] == 'requested'
    assert {target['run_id'] for target in json.loads(request['targets_json'])} == {'refresh', 'smart', 'playback'}
    assert 'probe_token' not in request
    calls = []
    def probe(key, *, headless):
        calls.append(key)
        assert ar.snapshot(db)['handling_requests'][0]['status'] == 'probing'
        return SimpleNamespace(healthy=True, status='active', expected=SimpleNamespace(account_uuid='A', account_key='a'))
    monkeypatch.setitem(sys.modules, 'src.operations_accounts.runtime', SimpleNamespace(
        AccountRuntimeService=lambda: SimpleNamespace(probe_recovery=probe)))
    ar.recover_requested_accounts(path=db)
    current = ar.snapshot(db)
    assert calls == ['a'] and current['controls'][0]['state'] == 'active'
    assert current['handling_requests'][0]['status'] == 'completed'
    for key in ('accounts', 'smart_accounts', 'playback_accounts'):
        assert current[key][0]['next_due'] == 1000
    for key in ('runs', 'smart_runs', 'playback_runs'):
        assert current[key] == original[key]


def test_latest_completed_and_future_normal_cycles_are_not_replayed(backend, tmp_path):
    ar = backend
    db = tmp_path / 'handling.db'
    seed_run(ar, db, status='failed')
    seed_run(ar, db, status='completed', suffix='newer')
    pause(ar, db)
    assert complete(ar, db)['accepted']
    assert json.loads(ar.snapshot(db)['handling_requests'][0]['targets_json']) == []
    token = ar._claim_recovery('A', 'a', path=db)
    assert ar._finish_recovery('A', 'a', token, healthy=True, status='active', path=db)
    assert ar.snapshot(db)['accounts'][0]['next_due'] == 9999


def test_clear_feed_completion_only_targets_playback_and_fences_changed_pause(backend, tmp_path):
    ar=backend;db=tmp_path/'scoped.db'
    configure_playback(ar,db)
    for kind in ('refresh','smart','playback'):
        seed_run(ar,db,kind)
    pause(ar,db)
    with ar.connect(db) as connection:
        revision=connection.execute('SELECT revision FROM account_controls WHERE account_uuid=?',('A',)).fetchone()[0]
    assert not ar.complete_account_handling('A','a',handled_by='system:clear-feed',path=db,
        plan_kinds=('playback',),expected_revision=revision+1)['accepted']
    assert ar.complete_account_handling('A','a',handled_by='system:clear-feed',path=db,
        plan_kinds=('playback',),expected_revision=revision)['accepted']
    targets=json.loads(ar.snapshot(db)['handling_requests'][0]['targets_json'])
    assert [target['kind'] for target in targets]==['playback']


@pytest.mark.parametrize('status', ['cancelled', 'skipped', 'completed'])
def test_non_failure_terminal_statuses_never_become_continuation_targets(backend, tmp_path, status):
    ar = backend
    db = tmp_path / 'handling.db'
    seed_run(ar, db, status=status)
    pause(ar, db)
    assert complete(ar, db)['accepted']
    assert json.loads(ar.snapshot(db)['handling_requests'][0]['targets_json']) == []


@pytest.mark.parametrize('kind', ['refresh', 'smart', 'playback'])
def test_unknown_or_unfinished_original_run_blocks_completion_without_new_identity(backend, tmp_path, kind):
    ar = backend
    db = tmp_path / 'handling.db'
    seed_run(ar, db, kind, status='outcome_unknown', finished_at=None)
    with ar.connect(db) as connection:
        connection.execute(f'UPDATE {kind}_accounts SET run_id=?,lease_until=50', (kind,))
    pause(ar, db)
    original = ar.snapshot(db)
    response = complete(ar, db)
    assert not response['accepted'] and response['state'] == 'outcome_unknown'
    assert ar.snapshot(db) == original
    assert not ar.snapshot(db)['handling_requests']


def test_busy_token_active_account_wrong_scope_and_actor_are_rejected(backend, tmp_path):
    ar = backend
    db = tmp_path / 'handling.db'
    assert not complete(ar, db)['accepted']
    pause(ar, db)
    assert ar.complete_account_handling('A', 'b', handled_by='admin', path=db)['state'] == 'binding_mismatch'
    assert ar.complete_account_handling('A', 'a', handled_by=' ', path=db)['state'] == 'invalid_actor'
    with ar.connect(db) as connection:
        connection.execute("UPDATE account_controls SET recovery_token='original',recovery_lease_until=2000")
    assert complete(ar, db)['state'] == 'busy'
    with ar.connect(db) as connection:
        connection.execute("UPDATE account_controls SET state='active',recovery_token=NULL")
    assert complete(ar, db)['state'] == 'active'
    assert not ar.snapshot(db)['handling_requests']


def test_concurrent_duplicate_completion_creates_one_persistent_request(backend, tmp_path):
    ar = backend
    db = tmp_path / 'handling.db'
    seed_run(ar, db)
    pause(ar, db)
    barrier = Barrier(2)
    def register():
        barrier.wait()
        return complete(ar, db)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(register) for _ in range(2)]
        assert sorted(future.result()['accepted'] for future in futures) == [False, True]
    token = ar._claim_recovery('A', 'a', path=db)
    assert token
    assert not complete(ar, db)['accepted']
    assert len(ar.snapshot(db)['handling_requests']) == 1
    assert ar._claim_recovery('A', 'a', path=db) is None


def test_failed_identity_probe_preserves_pause_and_due_then_requires_new_human_completion(backend, tmp_path):
    ar = backend
    db = tmp_path / 'handling.db'
    seed_run(ar, db)
    pause(ar, db)
    complete(ar, db)
    token = ar._claim_recovery('A', 'a', path=db)
    assert not ar._finish_recovery('A', 'a', token, healthy=False, status='identity_mismatch', path=db)
    state = ar.snapshot(db)
    assert state['controls'][0]['state'] == 'paused'
    assert state['accounts'][0]['next_due'] == 9999
    assert state['handling_requests'][0]['status'] == 'failed'
    assert ar._claim_recovery('A', 'a', path=db) is None
    assert complete(ar, db)['accepted']
    assert len(ar.snapshot(db)['handling_requests']) == 2


@pytest.mark.parametrize('change', ['pause', 'playback_disable', 'playback_options', 'refresh_policy', 'smart_policy'])
def test_new_pause_or_actual_related_policy_change_invalidates_inflight_completion(backend, tmp_path, change):
    ar = backend
    db = tmp_path / 'handling.db'
    configure_playback(ar, db)
    seed_run(ar, db, 'playback')
    pause(ar, db)
    complete(ar, db)
    token = ar._claim_recovery('A', 'a', path=db)
    if change == 'pause':
        ar.pause_account('A', 'a', 'new pause', path=db)
    elif change == 'playback_disable':
        configure_playback(ar, db, enabled=False)
    elif change == 'playback_options':
        configure_playback(ar, db, options={'max_videos': 10})
    elif change == 'refresh_policy':
        ar.set_policy(False, 14400, db)
    else:
        ar.set_smart_policy(False, 86400, db)
    due_after_setting = ar.snapshot(db)['playback_accounts'][0]['next_due']
    assert not ar._finish_recovery('A', 'a', token, healthy=True, status='active', path=db)
    state = ar.snapshot(db)
    assert state['controls'][0]['state'] == 'paused'
    assert state['playback_accounts'][0]['next_due'] == due_after_setting
    assert state['handling_requests'][0]['status'] == 'invalidated'
    with ar.connect(db) as connection:
        assert connection.execute('SELECT recovery_token FROM account_controls WHERE account_uuid="A"').fetchone()[0] is None


def test_other_account_playback_change_and_identical_policy_save_do_not_invalidate(backend, tmp_path):
    ar = backend
    db = tmp_path / 'handling.db'
    configure_playback(ar, db)
    seed_run(ar, db, 'playback')
    pause(ar, db)
    complete(ar, db)
    configure_playback(ar, db, 'B', 'b', options={'max_videos': 8})
    configure_playback(ar, db)  # Same effective setting is not a new policy version.
    ar.set_policy(True, 14400, db)
    ar.set_smart_policy(True, 86400, db)
    token = ar._claim_recovery('A', 'a', path=db)
    assert token and ar._finish_recovery('A', 'a', token, healthy=True, status='active', path=db)
    assert ar.snapshot(db)['playback_accounts'][0]['next_due'] == 1000


def test_legacy_recovery_keeps_existing_future_due_semantics(backend, tmp_path):
    ar = backend
    db = tmp_path / 'handling.db'
    seed_run(ar, db)
    pause(ar, db)
    assert ar.request_account_recovery('A', 'a', path=db)
    token = ar._claim_recovery('A', 'a', path=db)
    assert ar._finish_recovery('A', 'a', token, healthy=True, status='active', path=db)
    assert ar.snapshot(db)['accounts'][0]['next_due'] == 9999
    assert not ar.snapshot(db)['handling_requests']


@pytest.mark.parametrize('phase', ['before_claim', 'after_claim'])
def test_latest_target_change_or_missing_terminal_evidence_is_rejected_at_probe(backend, tmp_path, phase):
    ar = backend
    db = tmp_path / 'handling.db'
    seed_run(ar, db)
    pause(ar, db)
    complete(ar, db)
    token = ar._claim_recovery('A', 'a', path=db) if phase == 'after_claim' else None
    seed_run(ar, db, status='completed', suffix='newer')
    if phase == 'before_claim':
        assert ar._claim_recovery('A', 'a', path=db) is None
    else:
        assert not ar._finish_recovery('A', 'a', token, healthy=True, status='active', path=db)
    state = ar.snapshot(db)
    assert state['controls'][0]['state'] == 'paused'
    assert state['handling_requests'][0]['status'] == 'invalidated'
    assert state['accounts'][0]['next_due'] == 9999


def test_close_prompt_is_independent_and_opening_existing_handling_preserves_real_pause(backend, tmp_path):
    ar = backend
    db = tmp_path / 'handling.db'
    seed_run(ar, db)
    pause(ar, db)
    original = ar.snapshot(db)
    ar.pause_account('A', 'a', 'open manual window', preserve_existing_pause=True, path=db)
    assert ar.snapshot(db) == original
    issue_id = original['issues'][0]['id']
    assert ar.close_account_issue(issue_id, 'A', 'a', closed_by='admin', path=db)
    assert complete(ar, db)['accepted']
    assert ar.snapshot(db)['issues'][0]['status'] == 'closed'
    assert ar.snapshot(db)['controls'][0]['error_code'] == 'human_required'


def test_preserving_existing_pause_cannot_change_scope_token_revision_or_issues(backend, tmp_path):
    ar = backend
    db = tmp_path / 'handling.db'
    pause(ar, db)
    with ar.connect(db) as connection:
        connection.execute("UPDATE account_controls SET recovery_token='original-probe',recovery_lease_until=2000")
    original = ar.snapshot(db)
    ar.pause_account('A', 'a', 'open handling', preserve_existing_pause=True, path=db)
    assert ar.snapshot(db) == original
    with pytest.raises(ValueError, match='不一致'):
        ar.pause_account('A', 'b', 'wrong scope', preserve_existing_pause=True, path=db)
    assert ar.snapshot(db) == original
    with ar.connect(db) as connection:
        assert connection.execute('SELECT recovery_token FROM account_controls').fetchone()[0] == 'original-probe'


def test_legacy_schema_adds_handling_audit_and_fast_snapshot_stays_read_only(backend, tmp_path, monkeypatch):
    ar = backend
    db = tmp_path / 'handling.db'
    pause(ar, db)
    original = ar.snapshot(db)
    with sqlite3.connect(db) as connection:
        connection.execute('DROP TABLE account_handling_requests')
    assert ar.snapshot(db) == original
    statements = []
    original_connect = sqlite3.connect
    def traced_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection
    monkeypatch.setattr(ar.sqlite3, 'connect', traced_connect)
    with original_connect(db) as writer:
        writer.execute('BEGIN IMMEDIATE')
        ar.snapshot(db)
    assert not any(sql.lstrip().upper().startswith(('BEGIN', 'CREATE', 'INSERT', 'UPDATE')) for sql in statements)


@pytest.mark.parametrize('code', ['outcome_unknown', 'recovery_outcome_unknown'])
def test_explicit_unknown_control_code_rejects_completion_even_without_original_pointer(backend, tmp_path, code):
    ar = backend
    db = tmp_path / 'handling.db'
    seed_run(ar, db, status='failed')
    pause(ar, db)
    with ar.connect(db) as connection:
        connection.execute('UPDATE account_controls SET error_code=?', (code,))
    before = ar.snapshot(db)
    assert complete(ar, db)['state'] == 'outcome_unknown'
    assert ar.snapshot(db) == before


@pytest.mark.parametrize('status', ['failed', 'blocked', 'completed'])
def test_terminal_label_never_overrides_explicit_unknown_receipt_code(backend, tmp_path, status):
    ar = backend
    db = tmp_path / 'handling.db'
    original_id = seed_run(ar, db, status=status)
    pause(ar, db)
    with ar.connect(db) as connection:
        connection.execute('UPDATE refresh_runs SET detail=? WHERE run_id=?',
                           (json.dumps({'error_code': 'outcome_unknown', 'message': 'original receipt'}), original_id))
    before = ar.snapshot(db)
    assert complete(ar, db)['state'] == 'outcome_unknown'
    assert ar.snapshot(db) == before


def test_late_unknown_receipt_code_invalidates_probe_and_generic_unknown_word_is_not_a_code(backend, tmp_path):
    ar = backend
    db = tmp_path / 'handling.db'
    original_id = seed_run(ar, db, status='failed')
    pause(ar, db)
    with ar.connect(db) as connection:
        connection.execute('UPDATE refresh_runs SET detail=? WHERE run_id=?',
                           (json.dumps({'error_code': 'unknown_page_layout', 'message': 'unknown text is not an outcome code'}), original_id))
    assert complete(ar, db)['accepted']
    token = ar._claim_recovery('A', 'a', path=db)
    assert token
    with ar.connect(db) as connection:
        connection.execute('UPDATE refresh_runs SET detail=? WHERE run_id=?',
                           (json.dumps({'error_code': 'outcome_unknown'}), original_id))
    assert not ar._finish_recovery('A', 'a', token, healthy=True, status='active', path=db)
    state = ar.snapshot(db)
    assert state['controls'][0]['state'] == 'paused'
    assert state['accounts'][0]['next_due'] == 9999
    assert state['handling_requests'][0]['status'] == 'invalidated'
