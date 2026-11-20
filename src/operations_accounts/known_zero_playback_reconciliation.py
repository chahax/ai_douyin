"""Explicit settlement of a fully ended, zero-playback checkpoint failure.

This is not resume, retry or general paused recovery. Native/legacy receipts,
quotas and account controls stay untouched. Only the exact paused control row
can become failed, through its original transition API and snapshot CAS.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3

from .browser_control import BrowserControlRejected, BrowserControlStore

ROOT = Path(__file__).resolve().parents[2]


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def snapshot_sha256(value):
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


def _require(condition, message):
    if not condition:
        raise BrowserControlRejected('reconciliation_evidence_invalid', message)


def _zero(value):
    return type(value) in (int, float) and math.isfinite(value) and value == 0


@contextmanager
def _ro(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
    db.row_factory = sqlite3.Row
    try:
        yield db
    finally:
        db.close()


def _save_new(path, value):
    with Path(path).open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())


def reconcile_known_zero_playback(store: BrowserControlStore, command_id: str, *,
        account_id: str, account_key: str, owner_id: str, generation: int,
        receipt_path: str | Path, receipt_sha256: str, legacy_run_id: str,
        scheduler_db: str | Path, runtime_db: str | Path, audit_dir: str | Path,
        apply: bool = False, workspace_root: str | Path = ROOT):
    """Preview by default; apply settles exactly one proven known failure.

    The caller supplies original identities and receipt SHA explicitly. An
    immutable before audit precedes CAS; failure after that keeps the audit and
    never dispatches, retries, unpauses or releases a browser owner.
    """
    root = Path(workspace_root).resolve()
    receipt_path, audit_dir = Path(receipt_path).resolve(), Path(audit_dir).resolve()
    for path in (receipt_path, audit_dir, Path(store.path).resolve(),
                 Path(scheduler_db).resolve(), Path(runtime_db).resolve()):
        _require(path != root and path.is_relative_to(root), 'Reconciliation files must remain in the project')
    body = receipt_path.read_bytes()
    _require(hashlib.sha256(body).hexdigest() == receipt_sha256, 'Native receipt bytes differ from the observed SHA')
    try:
        native = json.loads(body.decode('utf-8'))
    except (ValueError, UnicodeError) as exc:
        raise BrowserControlRejected('reconciliation_evidence_invalid', 'Native receipt is truncated or unreadable') from exc
    _require(isinstance(native, dict), 'Native receipt is not a complete object')
    command = store.get(command_id)
    _require(command is not None, 'Original command is missing')
    _require(command['state'] == 'paused' and command['kind'] == 'maintenance'
        and command['error_code'] == 'resume_gate_rejected', 'Only the final known checkpoint suspension can be settled')
    _require(command['account_id'] == account_id and command['owner_id'] == owner_id
        and command['generation'] == generation, 'Original account/owner/generation differs')
    data = store.snapshot(account_id)
    owner = data['owner']
    _require(owner and owner['state'] == 'active' and owner['owner_id'] == owner_id
        and owner['generation'] == generation and owner['binding_version'] == command['binding_version'],
        'Original browser owner is unknown, changed or expired')
    _require(not any(row['command_id'] != command_id and row['state'] not in {'queued', 'succeeded', 'failed'}
        for row in data['commands']), 'Another command is active or unresolved')
    payload = command['payload']
    _require(payload.get('mode') == 'playback' and payload.get('account_key') == account_key
        and payload.get('account_uuid') == account_id, 'Command is not the original playback account')
    options = payload.get('options', {})
    playback = options.get('playback_options', {})
    _require(playback.get('auto_like') is False and playback.get('auto_comment') is False
        and _zero(playback.get('max_likes')) and _zero(playback.get('max_comments')),
        'Only playback with external interactions disabled is eligible')
    cursor = command.get('cursor') or {}
    completed = cursor.get('completed') or {}
    _require(cursor.get('stage') == 'playback_before_candidate' and _zero(cursor.get('next_candidate_index'))
        and _zero(cursor.get('likes_remaining')) and _zero(cursor.get('comments_remaining')),
        'Checkpoint is not the untouched first playback candidate')
    _require(completed.get('status') == 'completed' and completed.get('items') == []
        and not completed.get('error_code') and all(_zero(completed.get(key))
        for key in ('verified_videos', 'actual_watch_seconds', 'likes_performed', 'comments_sent')),
        'Checkpoint contains incomplete, unknown or nonzero playback')
    result = command.get('result')
    _require(isinstance(result, dict) and set(result) == {'maintenance_result'}
        and result.get('maintenance_result') == native,
        'Native full result and original control result are not identical')
    _require(native.get('mode') == 'playback' and native.get('status') == 'failed'
        and native.get('error_code') == command['error_code'] and native.get('failure_stage') == 'playback'
        and native.get('account_uuid') == account_id and native.get('account_key') == account_key
        and native.get('runtime_lease_acquired') is True and native.get('playback_items') == [],
        'Native result is not a complete known playback failure')
    _require(all(_zero(native.get(key)) for key in ('interaction_actions', 'playback_verified_videos',
        'actual_watch_seconds', 'likes_performed', 'comments_sent')), 'Native receipt has nonzero or missing playback results')
    policy = native.get('interaction_policy') or {}
    _require(policy.get('requested_auto_like') is False and policy.get('requested_auto_comment') is False
        and _zero(policy.get('effective_like_budget')) and _zero(policy.get('effective_comment_budget')),
        'Native interaction policy does not prove the zero-action scope')
    _require(isinstance(native.get('run_id'), str) and native['run_id'].startswith('maintenance:'), 'Native run identity is missing')
    expected_path = root / 'data/account_maintenance' / account_key / (native['run_id'].replace(':', '_') + '.json')
    _require(expected_path.resolve() == receipt_path, 'Native receipt is outside its original account/run location')
    native_log = Path(native.get('log_path', ''))
    _require((native_log if native_log.is_absolute() else root / native_log).resolve() == receipt_path,
        'Native self-reported receipt location differs')
    try:
        started = datetime.fromisoformat(native['started_at'])
        finished = datetime.fromisoformat(native['finished_at'])
        _require(started.tzinfo is not None and finished.tzinfo is not None
            and finished >= started and command['updated_at'] >= finished.timestamp(),
            'Native result is not fully ended before the current control snapshot')
    except (KeyError, TypeError, ValueError) as exc:
        raise BrowserControlRejected('reconciliation_evidence_invalid', 'Native completion timestamps are incomplete') from exc
    with _ro(runtime_db) as db:
        row = db.execute('SELECT * FROM account_runtime_state WHERE account_uuid=?', (account_id,)).fetchone()
        _require(row is not None and not row['lock_owner'] and not row['lock_expires_at'], 'Original business lease is still held or unknown')
    with _ro(scheduler_db) as db:
        control = db.execute('SELECT * FROM account_controls WHERE account_uuid=?', (account_id,)).fetchone()
        _require(control is not None and control['account_key'] == account_key
            and control['state'] == 'paused' and not control['recovery_token'], 'Account control or recovery state changed')
        for kind in ('refresh', 'smart', 'playback'):
            pending = db.execute(f'SELECT 1 FROM {kind}_accounts WHERE account_uuid=? AND (run_id IS NOT NULL OR coalesce(lease_until,0)<>0)', (account_id,)).fetchone()
            unknown = db.execute(f"SELECT 1 FROM {kind}_runs WHERE account_uuid=? AND (status IN ('running','starting','claimed','outcome_unknown') OR finished_at IS NULL)", (account_id,)).fetchone()
            _require(not pending and not unknown, 'Original scheduler owner/run is active or unresolved')
        legacy = db.execute('SELECT * FROM playback_runs WHERE run_id=? AND account_uuid=? AND account_key=?', (legacy_run_id, account_id, account_key)).fetchone()
        latest = db.execute('SELECT run_id FROM playback_runs WHERE account_uuid=? ORDER BY started_at DESC,rowid DESC LIMIT 1', (account_id,)).fetchone()
        _require(legacy is not None and latest and latest['run_id'] == legacy_run_id
            and legacy['status'] == 'failed' and legacy['finished_at'] is not None
            and legacy['started_at'] <= command['created_at'] <= legacy['finished_at']
            and command['updated_at'] >= legacy['finished_at'], 'Original latest legacy playback failure is not settled or bound in time')
        legacy = dict(legacy)
        detail, legacy_policy = json.loads(legacy['detail']), json.loads(legacy['policy_snapshot'])
        _require(detail.get('error_code') in {'paused', 'resume_gate_rejected'}
            and legacy_policy.get('account_uuid') == account_id and legacy_policy.get('account_key') == account_key
            and legacy_policy.get('authorization_reference') == options.get('authorization_reference')
            and bool(options.get('authorization_reference')), 'Legacy failure or authorization identity differs')
        _require(all(legacy_policy.get('options', {}).get(key) == playback.get(key) for key in (
            'max_videos', 'per_video_seconds', 'total_minutes', 'min_relevance_score', 'auto_like', 'auto_comment')),
            'Legacy playback policy differs from the original command')
    before_sha = snapshot_sha256(command)
    report = {'schema': 'known_zero_playback_reconciliation/v1', 'status': 'eligible',
        'command_id': command_id, 'account_id': account_id, 'account_key': account_key,
        'owner_id': owner_id, 'generation': generation, 'before_snapshot_sha256': before_sha,
        'before_result_sha256': snapshot_sha256(result), 'before_cursor_sha256': snapshot_sha256(cursor),
        'native_receipt': {'path': str(receipt_path), 'sha256': receipt_sha256, 'run_id': native['run_id']},
        'legacy_run_id': legacy_run_id, 'legacy_row_sha256': snapshot_sha256(legacy),
        'playback_resumed': False, 'account_unpaused': False, 'platform_task_dispatched': False}
    if not apply:
        return report
    # Preserve the entire old row, not merely the new conclusion. New audit
    # files are never overwritten; a failed CAS keeps the prepared evidence.
    audit_dir.mkdir(parents=True, exist_ok=False)
    _save_new(audit_dir / 'before.json', dict(report, command_before=command,
        prepared_at=datetime.now(timezone.utc).isoformat()))
    try:
        _require(hashlib.sha256(receipt_path.read_bytes()).hexdigest() == receipt_sha256, 'Native receipt changed before settlement')
        settled = store.transition(command_id, owner_id, generation, 'failed', cursor=cursor,
            result=result, error_code=command['error_code'], expected_snapshot_sha256=before_sha)
    except BaseException as exc:
        _save_new(audit_dir / 'outcome.json', dict(report, status='settlement_not_confirmed',
            error_type=type(exc).__name__, error_code=getattr(exc, 'code', ''),
            finished_at=datetime.now(timezone.utc).isoformat()))
        raise
    _require(settled['state'] == 'failed' and settled['result'] == result
        and settled['cursor'] == cursor and settled['error_code'] == command['error_code'],
        'Settlement did not retain the original failure evidence')
    report.update(status='settled_failed', after_snapshot_sha256=snapshot_sha256(settled),
        audit_dir=str(audit_dir), finished_at=datetime.now(timezone.utc).isoformat())
    _save_new(audit_dir / 'outcome.json', report)
    return report
