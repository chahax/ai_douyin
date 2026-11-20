"""No platform or production store: narrow known-failure settlement guards."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace as NS

import pytest

from src.operations_accounts.browser_control import BrowserControlStore, BrowserControlRejected
from src.operations_accounts.known_zero_playback_reconciliation import reconcile_known_zero_playback, snapshot_sha256


@pytest.fixture
def f(tmp_path):
    now = [1800000000.]
    store = BrowserControlStore(tmp_path / 'control.sqlite', clock=lambda: now[0])
    native_path = tmp_path / 'data/account_maintenance/review' / ('maintenance_' + 'a'*32 + '.json')
    native_path.parent.mkdir(parents=True)
    options = {'max_videos': 20, 'per_video_seconds': 90, 'total_minutes': 20,
        'min_relevance_score': 60., 'auto_like': False, 'auto_comment': False,
        'max_likes': 0, 'max_comments': 0}
    native = {'run_id': 'maintenance:' + 'a'*32, 'account_key': 'review', 'account_uuid': 'review:A',
        'mode': 'playback', 'status': 'failed', 'error_code': 'resume_gate_rejected',
        'failure_stage': 'playback', 'runtime_lease_acquired': True, 'playback_items': [],
        'interaction_actions': 0, 'playback_verified_videos': 0, 'actual_watch_seconds': 0.,
        'likes_performed': 0, 'comments_sent': 0, 'interaction_policy': {
            'requested_auto_like': False, 'requested_auto_comment': False,
            'effective_like_budget': 0, 'effective_comment_budget': 0},
        'started_at': datetime.fromtimestamp(now[0]+1, timezone.utc).isoformat(),
        'finished_at': datetime.fromtimestamp(now[0]+5, timezone.utc).isoformat(),
        'log_path': str(native_path.relative_to(tmp_path))}
    native_path.write_text(json.dumps(native), encoding='utf-8')
    command = store.submit('review:A', 'binding', 'maintenance', 'original', {
        'account_uuid': 'review:A', 'account_key': 'review', 'mode': 'playback',
        'options': {'authorization_reference': 'original-authorized-playback', 'playback_options': options}})
    owner = store.acquire_owner('review:A', 'binding', 'backend:123:original')
    store.claim_next('review:A', 'binding', owner['owner_id'], owner['generation'])
    cursor = {'stage': 'playback_before_candidate', 'next_candidate_index': 0,
        'likes_remaining': 0, 'comments_remaining': 0, 'completed': {'status': 'completed',
            'items': [], 'error_code': '', 'verified_videos': 0, 'actual_watch_seconds': 0.,
            'likes_performed': 0, 'comments_sent': 0}}
    now[0] += 6
    store.transition(command['command_id'], owner['owner_id'], owner['generation'], 'paused',
        cursor=cursor, result={'maintenance_result': native}, error_code='resume_gate_rejected')
    runtime = tmp_path / 'runtime.sqlite'
    with sqlite3.connect(runtime) as db:
        db.execute('CREATE TABLE account_runtime_state(account_uuid TEXT,lock_owner TEXT,lock_expires_at TEXT,daily_runs INTEGER)')
        db.execute("INSERT INTO account_runtime_state VALUES('review:A','','',2)")
    scheduler = tmp_path / 'scheduler.sqlite'
    with sqlite3.connect(scheduler) as db:
        db.execute('CREATE TABLE account_controls(account_uuid TEXT,account_key TEXT,state TEXT,recovery_token TEXT)')
        db.execute("INSERT INTO account_controls VALUES('review:A','review','paused',NULL)")
        for kind in ('refresh', 'smart', 'playback'):
            db.execute(f'CREATE TABLE {kind}_accounts(account_uuid TEXT,run_id TEXT,lease_until REAL)')
            db.execute(f"INSERT INTO {kind}_accounts VALUES('review:A',NULL,0)")
            if kind != 'playback':
                db.execute(f'CREATE TABLE {kind}_runs(account_uuid TEXT,status TEXT,finished_at REAL)')
        db.execute('CREATE TABLE playback_runs(run_id TEXT,account_uuid TEXT,account_key TEXT,status TEXT,started_at REAL,finished_at REAL,detail TEXT,policy_snapshot TEXT)')
        policy = {'account_uuid': 'review:A', 'account_key': 'review',
            'authorization_reference': 'original-authorized-playback', 'options': options}
        db.execute('INSERT INTO playback_runs VALUES(?,?,?,?,?,?,?,?)', ('legacy-original', 'review:A',
            'review', 'failed', now[0]-7, now[0]-2, json.dumps({'error_code': 'paused'}), json.dumps(policy)))
    kwargs = {'account_id': 'review:A', 'account_key': 'review', 'owner_id': owner['owner_id'],
        'generation': owner['generation'], 'receipt_path': native_path,
        'receipt_sha256': hashlib.sha256(native_path.read_bytes()).hexdigest(), 'legacy_run_id': 'legacy-original',
        'scheduler_db': scheduler, 'runtime_db': runtime, 'audit_dir': tmp_path / 'audit', 'workspace_root': tmp_path}
    return NS(store=store, command=command, owner=owner, native=native, native_path=native_path,
        scheduler=scheduler, runtime=runtime, cursor=cursor, kwargs=kwargs, root=tmp_path)


def settle(f, **extra):
    return reconcile_known_zero_playback(f.store, f.command['command_id'], **dict(f.kwargs, **extra))


def test_preview_is_readonly_and_apply_only_settles_failed_preserving_all_original_evidence(f):
    before = f.store.get(f.command['command_id'])
    file_bytes = {p: p.read_bytes() for p in (f.native_path, f.scheduler, f.runtime)}
    assert settle(f)['status'] == 'eligible'
    assert not (f.root / 'audit').exists()
    assert f.store.get(f.command['command_id']) == before
    result = settle(f, apply=True)
    after = f.store.get(f.command['command_id'])
    assert result['status'] == 'settled_failed'
    assert after == dict(before, state='failed')  # fake clock unchanged
    assert all(p.read_bytes() == body for p, body in file_bytes.items())
    audit = json.loads((f.root/'audit/before.json').read_text(encoding='utf-8'))
    assert audit['command_before'] == before
    assert audit['before_result_sha256'] == snapshot_sha256(before['result'])
    assert not result['account_unpaused'] and not result['playback_resumed']


@pytest.mark.parametrize('change', ['unknown', 'incomplete', 'receipt-sha', 'nonzero', 'later-candidate', 'owner', 'legacy', 'runtime-lock'])
def test_unknown_incomplete_nonzero_or_mismatched_evidence_cannot_settle(f, change):
    if change == 'unknown':
        f.store.transition(f.command['command_id'], f.owner['owner_id'], f.owner['generation'],
            'outcome_unknown', result={'original': 'unknown'})
    elif change == 'incomplete':
        f.store.transition(f.command['command_id'], f.owner['owner_id'], f.owner['generation'],
            'paused', cursor=f.cursor, result=None, error_code='resume_gate_rejected')
    elif change == 'receipt-sha':
        f.native_path.write_text(f.native_path.read_text()+'\n')
    elif change in {'nonzero', 'later-candidate'}:
        cursor = dict(f.cursor)
        if change == 'nonzero':
            cursor['completed'] = dict(cursor['completed'], actual_watch_seconds=1.)
        else:
            cursor['next_candidate_index'] = 1
        f.store.transition(f.command['command_id'], f.owner['owner_id'], f.owner['generation'],
            'paused', cursor=cursor, result={'maintenance_result': f.native}, error_code='resume_gate_rejected')
    elif change == 'owner':
        f.kwargs['owner_id'] = 'backend:123:other'
    elif change == 'legacy':
        f.kwargs['legacy_run_id'] = 'other-legacy'
    else:
        with sqlite3.connect(f.runtime) as db:
            db.execute("UPDATE account_runtime_state SET lock_owner='old-unknown'")
    before = f.store.get(f.command['command_id'])
    with pytest.raises(BrowserControlRejected):
        settle(f, apply=True)
    assert f.store.get(f.command['command_id']) == before
    assert not (f.root / 'audit').exists()


def test_truncated_native_receipt_is_not_treated_as_complete_even_with_matching_new_sha(f):
    f.native_path.write_bytes(b'{"run_id":')
    f.kwargs['receipt_sha256'] = hashlib.sha256(f.native_path.read_bytes()).hexdigest()
    with pytest.raises(BrowserControlRejected, match='truncated'):
        settle(f, apply=True)
    assert f.store.get(f.command['command_id'])['state'] == 'paused'


def test_atomic_original_transition_cas_rejects_changed_checkpoint_after_validation(f, monkeypatch):
    original_transition = f.store.transition
    def raced(*args, **kwargs):
        original_transition(f.command['command_id'], f.owner['owner_id'], f.owner['generation'],
            'paused', cursor=dict(f.cursor, next_candidate_index=1),
            result={'maintenance_result': f.native}, error_code='resume_gate_rejected')
        return original_transition(*args, **kwargs)
    monkeypatch.setattr(f.store, 'transition', raced)
    with pytest.raises(BrowserControlRejected) as error:
        settle(f, apply=True)
    assert error.value.code == 'command_changed'
    assert f.store.get(f.command['command_id'])['state'] == 'paused'
    assert json.loads((f.root/'audit/outcome.json').read_text())['status'] == 'settlement_not_confirmed'
