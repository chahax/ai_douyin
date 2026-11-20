"""One exact, authorized deployment cancellation before smart browser dispatch."""
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from .browser_control import BrowserControlRejected, _json
from .pre_dispatch_playback_cancel import _open_database, _write_new
from .publication_unknown_closure import _json_ref, file_reference

ROOT = Path(__file__).resolve().parents[2]
AUTHORIZATION_SHA256 = '1abadd49594b71ecaba4c9a22c6023864fdcc7c7b71aad2311dec8830bff691a'
SNAPSHOT_SHA256 = '7481e111adbbde4ac53623cb21fc37f6026559d94ab8f9ebbe7135ca07d91fc3'
COMMAND_ID = '8262f00c438a4d9ca01c0f0c683dcf59'
RUN_ID = 'c8518c2467134991b465604dde956829'
OWNER_ID = 'backend:22452:06d85d2fa0cc47758f6937f29cb5cbc2'
GENERATION = 8


class PreDispatchSmartCancelPartial(RuntimeError):
    code = 'pre_dispatch_smart_cancellation_partial'


def _reject():
    raise BrowserControlRejected('pre_dispatch_smart_mismatch', '原智能维护未派发证据、授权、owner或完整快照已变化，未取消。')


def operator_cancel_pre_dispatch_smart(store, *, owner_id, generation, authorization,
        snapshot, audit_dir, now=None):
    """Three write fences; core commit then scheduler commit, not crash-atomic.

    Any partial completion requires stopping deployment and inspecting INTENT/STOP.
    This does not resume control, alter quota, or cancel a dispatched browser task.
    """
    if (authorization.get('sha256') != AUTHORIZATION_SHA256
            or snapshot.get('sha256') != SNAPSHOT_SHA256
            or owner_id != OWNER_ID or generation != GENERATION):
        _reject()
    approval, before = _json_ref(authorization), _json_ref(snapshot)
    audit_dir = Path(audit_dir).resolve()
    if (set(before) != {'command', 'run', 'account', 'policy', 'control', 'runtime'}
            or store.path != (ROOT / 'data/account_browser_control.db').resolve()
            or not audit_dir.is_relative_to((ROOT / 'data').resolve())
            or approval.get('schema') != 'publication_fast_upload_retry_user_authorization/20261019/v1'
            or approval.get('decision_source') != 'explicit_user_statement'
            or approval.get('user_statement') != '允许' or not approval.get('approval_question')
            or approval.get('deployment_authorized') is not True
            or approval.get('baseline_daily_runs') != 26 or approval.get('max_daily_runs') != 27
            or approval.get('active_control_revision') != 42 or approval.get('additional_recovery_runs') != 0):
        _reject()
    account_id, account_key = approval['account_uuid'], approval['account_key']
    command, run, account, policy, control, usage = (before[name]
        for name in ('command', 'run', 'account', 'policy', 'control', 'runtime'))
    now = time.time() if now is None else now
    scheduler = _open_database(ROOT / 'data/account_refresh.db')
    runtime = None
    intent = None
    core_committed = scheduler_committed = False
    try:
        runtime = _open_database(ROOT / 'data/douyin.db')
        with store._db(write=True) as db:
            scheduler.execute('BEGIN IMMEDIATE')
            runtime.execute('BEGIN IMMEDIATE')
            current_command = store._command(db.execute('SELECT * FROM browser_control_commands WHERE command_id=?', (COMMAND_ID,)).fetchone())
            current = {'command': current_command}
            for name, query, args in (
                    ('run', 'SELECT * FROM smart_runs WHERE run_id=?', (RUN_ID,)),
                    ('account', 'SELECT * FROM smart_accounts WHERE account_uuid=?', (account_id,)),
                    ('policy', 'SELECT * FROM smart_policy WHERE id=1', ()),
                    ('control', 'SELECT * FROM account_controls WHERE account_uuid=?', (account_id,))):
                current[name] = dict(scheduler.execute(query, args).fetchone() or {})
            current['runtime'] = dict(runtime.execute('SELECT * FROM account_runtime_state WHERE account_uuid=?', (account_id,)).fetchone() or {})
            if current != before:
                _reject()
            store._owner(db, account_id, owner_id, generation, command['binding_version'])
            if (command.get('command_id') != COMMAND_ID or command.get('account_id') != account_id
                    or command.get('kind') != 'maintenance' or command.get('state') != 'queued'
                    or any(command.get(k) is not None for k in ('owner_id', 'generation', 'cursor', 'result', 'error_code'))
                    or command['payload'].get('account_uuid') != account_id or command['payload'].get('account_key') != account_key
                    or command['payload'].get('mode') != 'smart-operations'
                    or command['payload'].get('options') != {
                        'authorization_reference': 'user-authorized-smart-operations-2026-09-21',
                        'headless': True, 'playback_options': None, 'research_keywords': ['装修合同', '租房押金']}
                    or run.get('run_id') != RUN_ID or run.get('status') != 'running' or run.get('finished_at') is not None
                    or json.loads(run['detail']) != {} or account.get('run_id') != RUN_ID
                    or any(v.get('account_uuid') != account_id or v.get('account_key') != account_key for v in (run, account, control))
                    or not run['started_at'] <= command['created_at'] <= run['started_at'] + 60
                    or account['lease_until'] <= run['started_at'] or command['updated_at'] != command['created_at']
                    or now < command['created_at'] or policy != {'id': 1, 'enabled': 1, 'interval_seconds': 86400}
                    or control.get('state') != 'active' or control.get('revision') != 42 or control.get('consecutive_failures') != 2
                    or control.get('error_code') or control.get('recovery_token') or control.get('recovery_lease_until')
                    or usage.get('account_uuid') != account_id or usage.get('daily_runs') != 26
                    or usage.get('day_key') != approval.get('utc_day')
                    or usage.get('day_key') != datetime.fromtimestamp(now, timezone.utc).date().isoformat()
                    or usage.get('lock_owner') or usage.get('lock_expires_at')):
                _reject()
            active = db.execute("SELECT * FROM browser_control_commands WHERE account_id=? AND state NOT IN ('failed','succeeded')", (account_id,)).fetchall()
            if ([r['command_id'] for r in active if r['kind'] != 'manual'] != [COMMAND_ID]
                    or any(r['command_id'] != COMMAND_ID and (r['kind'] != 'manual' or r['state'] != 'queued') for r in active)):
                _reject()
            for kind in ('refresh', 'smart', 'playback'):
                pending = scheduler.execute(f"SELECT run_id FROM {kind}_runs WHERE account_uuid=? AND (status IN ('running','outcome_unknown') OR finished_at IS NULL)", (account_id,)).fetchall()
                if (kind != 'smart' and pending) or (kind == 'smart' and [r['run_id'] for r in pending] != [RUN_ID]):
                    _reject()
                if kind != 'smart' and scheduler.execute(f'SELECT 1 FROM {kind}_accounts WHERE account_uuid=? AND (run_id IS NOT NULL OR coalesce(lease_until,0)<>0)', (account_id,)).fetchone():
                    _reject()
            audit_dir.mkdir(parents=True, exist_ok=False)
            intent = {'schema': 'pre_dispatch_smart_cancel/20261019/v1', 'phase': 'intent',
                'authorization': authorization, 'source_snapshot': snapshot, 'before': before,
                'owner_id': owner_id, 'generation': generation, 'cancelled_at': now,
                'cross_database_crash_atomic': False}
            _write_new(audit_dir / 'INTENT.json', intent)
            intent_ref = file_reference(audit_dir / 'INTENT.json')
            detail = {'operator_cancelled_before_dispatch': True, 'external_browser_dispatched': False,
                'message': '按明确部署批准取消仍排队的智能维护；未运行浏览器或新增消费。',
                'command_id': COMMAND_ID, 'intent': intent_ref}
            scheduler.execute("UPDATE smart_runs SET status='cancelled_before_browser_dispatch',finished_at=?,detail=? WHERE run_id=? AND status='running'",
                (now, _json(detail), RUN_ID))
            scheduler.execute('UPDATE smart_accounts SET next_due=?,run_id=NULL,lease_until=0 WHERE account_uuid=? AND run_id=?',
                (now + policy['interval_seconds'], account_id, RUN_ID))
            result = {'cancelled_before_dispatch': True, 'operator_deployment_cancellation': True,
                'authorization': authorization, 'intent': intent_ref, 'before_snapshot': command,
                'before': before, 'external_browser_dispatched': False}
            db.execute("UPDATE browser_control_commands SET state='failed',error_code='operator_cancelled_before_dispatch',result=?,updated_at=? WHERE command_id=? AND state='queued'",
                (_json(result), now, COMMAND_ID))
            db.commit()
            core_committed = True
            scheduler.commit()
            scheduler_committed = True
            if (dict(scheduler.execute('SELECT * FROM account_controls WHERE account_uuid=?', (account_id,)).fetchone()) != control
                    or dict(runtime.execute('SELECT * FROM account_runtime_state WHERE account_uuid=?', (account_id,)).fetchone()) != usage):
                raise PreDispatchSmartCancelPartial('Control/runtime changed; stop deployment and inspect intent')
            receipt = dict(intent, phase='completed', core_committed=True, scheduler_committed=True,
                intent=intent_ref, after_command=store._command(db.execute('SELECT * FROM browser_control_commands WHERE command_id=?', (COMMAND_ID,)).fetchone()),
                after_run=dict(scheduler.execute('SELECT * FROM smart_runs WHERE run_id=?', (RUN_ID,)).fetchone()),
                after_account=dict(scheduler.execute('SELECT * FROM smart_accounts WHERE account_uuid=?', (account_id,)).fetchone()))
            _write_new(audit_dir / 'RECEIPT.json', receipt)
            return file_reference(audit_dir / 'RECEIPT.json')
    except BaseException as exc:
        scheduler.rollback()
        if intent is not None:
            _write_new(audit_dir / 'STOP.json', {'phase': 'partial' if core_committed else 'not_committed',
                'core_committed': core_committed, 'scheduler_committed': scheduler_committed, 'error_type': type(exc).__name__})
        if core_committed:
            raise PreDispatchSmartCancelPartial('Partial cancellation or incomplete receipt; stop deployment and inspect intent') from exc
        raise
    finally:
        if runtime is not None:
            runtime.rollback()
            runtime.close()
        scheduler.close()
