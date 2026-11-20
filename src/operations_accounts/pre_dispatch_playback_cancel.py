"""Exact deployment cancellation of a queued browser command, not playback success."""
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import time

from .browser_control import BrowserControlRejected, _json
from .publication_unknown_closure import file_reference, _json_ref

ROOT = Path(__file__).resolve().parents[2]
AUTHORIZATION_SHA256 = '40bf002fd5999874b94cee9c4b19a443ed0bcf19c1a0d041690af1aff81d45d3'
COMMAND_ID = '4763e8ac2e3d44e5a743b660777ec66c'
RUN_ID = '83c172ab9cf74c33bf9c87c01153e167'


class PreDispatchPlaybackCancelPartial(RuntimeError):
    code = 'pre_dispatch_cancellation_partial'


def _reject():
    raise BrowserControlRejected('pre_dispatch_playback_mismatch', '原播放尚未进入浏览器的证据、授权或快照不匹配，未取消。')


def _open_database(path):
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=rw', uri=True, timeout=2)
    db.row_factory = sqlite3.Row
    return db


def _write_new(path, value):
    with path.open('x', encoding='utf-8') as handle:
        handle.write(_json(value))
        handle.flush()
        os.fsync(handle.fileno())


def operator_cancel_pre_dispatch_playback(store, *, owner_id, generation, authorization,
        command_snapshot, run_snapshot, account_snapshot, policy_snapshot, audit_dir, now=None):
    """Three write fences; core commits before scheduler so no cancelled run can dispatch.

    The scheduler may use WAL: this is deliberately NOT a crash-atomic multi-DB
    claim. A partial core commit is retained and requires operator reconciliation.
    """
    if authorization.get('sha256') != AUTHORIZATION_SHA256:
        _reject()
    approval = _json_ref(authorization)
    command = _json_ref(command_snapshot)
    run = _json_ref(run_snapshot)
    account = _json_ref(account_snapshot)
    policy = _json_ref(policy_snapshot)
    audit_dir = Path(audit_dir).resolve()
    if (not audit_dir.is_relative_to((ROOT / 'data').resolve())
            or store.path != (ROOT / 'data/account_browser_control.db').resolve()
            or command.get('command_id') != COMMAND_ID or run.get('run_id') != RUN_ID
            or approval.get('schema') != 'publication_single_retry_user_authorization/20261019/v1'
            or approval.get('decision_source') != 'explicit_user_statement'
            or not approval.get('user_statement') or not approval.get('approval_question')
            or approval.get('deployment_authorized') is not True
            or approval.get('baseline_daily_runs') != 25 or approval.get('max_daily_runs') != 26
            or approval.get('active_control_revision') != 42
            or approval.get('additional_recovery_runs') != 0):
        _reject()
    now = time.time() if now is None else now
    account_id, account_key = approval['account_uuid'], approval['account_key']
    scheduler = _open_database(ROOT / 'data/account_refresh.db')
    runtime = None
    intent = None
    core_committed = scheduler_committed = False
    try:
        runtime = _open_database(ROOT / 'data/douyin.db')
        with store._db(write=True) as db:
            scheduler.execute('BEGIN IMMEDIATE')
            runtime.execute('BEGIN IMMEDIATE')
            current = store._command(db.execute('SELECT * FROM browser_control_commands WHERE command_id=?', (COMMAND_ID,)).fetchone())
            current_run = scheduler.execute('SELECT * FROM playback_runs WHERE run_id=?', (RUN_ID,)).fetchone()
            current_account = scheduler.execute('SELECT * FROM playback_accounts WHERE account_uuid=?', (account_id,)).fetchone()
            current_policy = scheduler.execute('SELECT * FROM playback_policies WHERE account_uuid=?', (account_id,)).fetchone()
            if (current != command or not current_run or dict(current_run) != run
                    or not current_account or dict(current_account) != account
                    or not current_policy or dict(current_policy) != policy):
                _reject()
            store._owner(db, account_id, owner_id, generation, command['binding_version'])
            if (command['account_id'] != account_id or command['kind'] != 'maintenance'
                    or command['state'] != 'queued' or command['owner_id'] is not None or command['generation'] is not None
                    or command['cursor'] is not None or command['result'] is not None
                    or command['payload'].get('account_uuid') != account_id or command['payload'].get('account_key') != account_key
                    or command['payload'].get('mode') != 'playback'
                    or any(value.get('account_uuid') != account_id or value.get('account_key') != account_key
                        for value in (run, account, policy))
                    or run['status'] != 'running' or run['finished_at'] is not None or json.loads(run['detail']) != {}
                    or account['run_id'] != RUN_ID or account['lease_until'] <= run['started_at']
                    or run['dispatched_at'] is None
                    or not run['started_at'] <= run['dispatched_at'] <= command['created_at'] <= run['started_at'] + 60
                    or command['updated_at'] < command['created_at'] or now < command['created_at']):
                _reject()
            active = db.execute("SELECT * FROM browser_control_commands WHERE account_id=? AND state NOT IN ('failed','succeeded')", (account_id,)).fetchall()
            if (sum(row['kind'] == 'maintenance' and json.loads(row['payload']).get('mode') == 'playback' for row in active) != 1
                    or any(row['command_id'] != COMMAND_ID and (row['state'] != 'queued' or row['kind'] != 'manual') for row in active)):
                _reject()
            for kind in ('refresh', 'smart', 'playback'):
                pending = scheduler.execute(f"SELECT * FROM {kind}_runs WHERE account_uuid=? AND (status IN ('running','outcome_unknown') OR finished_at IS NULL)", (account_id,)).fetchall()
                if (kind != 'playback' and pending) or (kind == 'playback' and [row['run_id'] for row in pending] != [RUN_ID]):
                    _reject()
                if kind != 'playback' and scheduler.execute(f'SELECT 1 FROM {kind}_accounts WHERE account_uuid=? AND (run_id IS NOT NULL OR coalesce(lease_until,0)<>0)', (account_id,)).fetchone():
                    _reject()
            control = dict(scheduler.execute('SELECT * FROM account_controls WHERE account_uuid=?', (account_id,)).fetchone() or {})
            usage = dict(runtime.execute('SELECT * FROM account_runtime_state WHERE account_uuid=?', (account_id,)).fetchone() or {})
            if (control.get('account_key') != account_key or control.get('state') != 'active' or control.get('revision') != 42
                    or control.get('consecutive_failures') != 1 or control.get('recovery_token')
                    or control.get('recovery_lease_until') or control.get('error_code')
                    or usage.get('daily_runs') != 25 or usage.get('day_key') != approval.get('utc_day')
                    or usage.get('day_key') != datetime.fromtimestamp(now, timezone.utc).date().isoformat()
                    or usage.get('lock_owner') or usage.get('lock_expires_at')):
                _reject()
            from src.scheduler.account_refresh import _playback_policy_dict
            from src.scheduler.account_playback import normalize_options
            from src.platform_adapter.douyin_playback import PlaybackOptions
            frozen = json.loads(run['policy_snapshot'])
            expected_policy = _playback_policy_dict(policy)
            expected_policy['options'] = normalize_options(expected_policy['options'])
            options = command['payload']['options']
            if (frozen != expected_policy or policy['enabled'] != 1
                    or not 8 * 3600 <= policy['interval_seconds'] <= 7 * 86400
                    or set(options) != {'authorization_reference', 'headless', 'playback_options', 'research_keywords'}
                    or options['authorization_reference'] != frozen['authorization_reference'] or not frozen['authorization_reference']
                    or options['headless'] is not True or options['research_keywords'] is not None
                    or options['playback_options'] != asdict(PlaybackOptions(**normalize_options(frozen['options'])))):
                _reject()
            audit_dir.mkdir(parents=True, exist_ok=False)
            intent = {'schema': 'pre_dispatch_playback_cancel/20261019/v1', 'phase': 'intent',
                'authorization': authorization, 'sources': {'command': command_snapshot, 'run': run_snapshot,
                    'account': account_snapshot, 'policy': policy_snapshot},
                'before_command': command, 'before_run': run, 'before_account': account, 'before_policy': policy,
                'before_control': control, 'before_runtime': usage, 'owner_id': owner_id, 'generation': generation,
                'cancelled_at': now, 'cross_database_crash_atomic': False}
            _write_new(audit_dir / 'INTENT.json', intent)
            intent_ref = file_reference(audit_dir / 'INTENT.json')
            detail = {'operator_cancelled_before_dispatch': True, 'external_browser_dispatched': False,
                'message': '明确批准部署：原浏览器命令仍在排队，取消本次计划，未观看或新增消费。',
                'command_id': COMMAND_ID, 'preserved_worker_dispatched_at': run['dispatched_at'], 'intent': intent_ref}
            scheduler.execute("UPDATE playback_runs SET status='cancelled_before_browser_dispatch',finished_at=?,detail=? WHERE run_id=? AND status='running'",
                (now, _json(detail), RUN_ID))
            scheduler.execute('UPDATE playback_accounts SET next_due=?,run_id=NULL,lease_until=0 WHERE account_uuid=? AND run_id=?',
                (now + policy['interval_seconds'], account_id, RUN_ID))
            result = {'cancelled_before_dispatch': True, 'operator_deployment_cancellation': True,
                'authorization': authorization, 'intent': intent_ref, 'before_snapshot': command,
                'before_scheduler_run': run, 'external_browser_dispatched': False}
            db.execute("UPDATE browser_control_commands SET state='failed',error_code='operator_cancelled_before_dispatch',result=?,updated_at=? WHERE command_id=? AND state='queued'",
                (_json(result), now, COMMAND_ID))
            db.commit()  # Client may wake, but its late finish is still behind the scheduler writer fence.
            core_committed = True
            scheduler.commit()
            scheduler_committed = True
            after_control = dict(scheduler.execute('SELECT * FROM account_controls WHERE account_uuid=?', (account_id,)).fetchone())
            after_usage = dict(runtime.execute('SELECT * FROM account_runtime_state WHERE account_uuid=?', (account_id,)).fetchone())
            if after_control != control or after_usage != usage:
                raise PreDispatchPlaybackCancelPartial('Control/runtime changed; inspect saved intent before deploying')
            receipt = dict(intent, phase='completed', core_committed=True, scheduler_committed=True,
                intent=intent_ref, after_command=store._command(db.execute('SELECT * FROM browser_control_commands WHERE command_id=?', (COMMAND_ID,)).fetchone()),
                after_run=dict(scheduler.execute('SELECT * FROM playback_runs WHERE run_id=?', (RUN_ID,)).fetchone()),
                after_account=dict(scheduler.execute('SELECT * FROM playback_accounts WHERE account_uuid=?', (account_id,)).fetchone()))
            _write_new(audit_dir / 'RECEIPT.json', receipt)
            return file_reference(audit_dir / 'RECEIPT.json')
    except BaseException as exc:
        scheduler.rollback()
        if intent is not None:
            _write_new(audit_dir / 'STOP.json', {'phase': 'partial' if core_committed else 'not_committed',
                'core_committed': core_committed, 'scheduler_committed': scheduler_committed, 'error_type': type(exc).__name__})
        if core_committed:
            raise PreDispatchPlaybackCancelPartial('Cancellation partially committed or receipt incomplete; stop deployment and inspect intent') from exc
        raise
    finally:
        if runtime is not None:
            runtime.rollback()
            runtime.close()
        scheduler.close()
