"""Known pre-Popen failures of an allowlisted read command; never replay work.

The historical path is a two-phase exact-CAS disposition.  Original unknown
records, logs and request evidence remain embedded and pinned, not discarded.
"""
import hashlib
import json
from pathlib import Path
import re
import time

import psutil

from .browser_control import BrowserCommandResult, BrowserControlRejected, BrowserControlStore, _json

ROOT = Path(__file__).resolve().parents[2]
READONLY_KINDS = frozenset({'fanqie_promotion_list', 'fanqie_catalog', 'fanqie_promotion_preflight','fanqie_promotion_lookup',
                          'fanqie_filled_details','fanqie_filled_details_controls'})
CODE = 'readonly_local_worker_not_started'
SAFE_CAUSES = frozenset({'FileNotFoundError', 'PermissionError'})
PENDING = ('queued', 'running', 'paused', 'waiting_human', 'outcome_unknown')


def _reject(code='readonly_startup_proof_incomplete'):
    raise BrowserControlRejected(code, '只读启动失败证据不完整或原记录已变化；未结算、未重派')


def _path(path):
    value = Path(path).resolve()
    if not value.is_relative_to(ROOT):
        _reject('evidence_outside_project')
    return value


def bind(path):
    value = _path(path)
    return {'path': str(value), 'sha256': hashlib.sha256(value.read_bytes()).hexdigest()}


def _read(reference):
    if not isinstance(reference, dict) or bind(reference['path']) != reference:
        _reject('bound_evidence_changed')
    return json.loads(_path(reference['path']).read_text(encoding='utf-8'))


def _freeze(path, value):
    path = _path(path)
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('xb') as out:
            out.write(raw)
    except FileExistsError:
        if path.read_bytes() != raw:
            _reject('recovery_artifact_already_exists')
    return bind(path)


def _no_business_artifacts(folder):
    # Initial startup cannot have observed identity, opened forms or visited the
    # list. Unknown/non-startup files make this deliberately conservative.
    allowed = {'WORKER_LAUNCH.json', 'WORKER_PROCESS.json', 'worker.log', 'DATABASE_DIAGNOSTIC.json'}
    return all(p.is_file() and (p.name in allowed or re.fullmatch(r'ADMISSION_WAIT_\d+\.json', p.name))
               for p in folder.iterdir())


def classify_startup_failure(error, session, folder):
    """Return facts only for a real typed failure before Popen returned a PID."""
    from src.platform_adapter.browser_session import BrowserWorkerStartupError
    evidence = getattr(error, 'startup_evidence', {})
    cause = error.__cause__
    if (not isinstance(error, BrowserWorkerStartupError) or type(cause).__name__ not in SAFE_CAUSES
            or not isinstance(cause, OSError) or getattr(error, 'stage', None) != 'spawning_worker'
            or not isinstance(evidence, dict) or evidence.get('stage') != 'spawning_worker'
            or evidence.get('cleanup_verified') is not True or evidence.get('ready_received') is not False
            or 'worker_pid' in evidence or evidence.get('driver_present_at_cleanup') is True
            or getattr(session, '_proc', 'missing') is not None
            or getattr(session, '_worker_stage', None) != 'spawning_worker'
            or getattr(session, '_startup_cleanup_verified', False) is not True
            or getattr(session, 'active', False) is True or not _no_business_artifacts(folder)):
        return None
    return dict(stage='spawning_worker', cleanup_verified=True, ready_received=False,
                worker_pid_observed=False, browser_worker_started=False, platform_requests_started=False,
                cause_type=type(cause).__name__, exception_type=type(error).__name__)


def readonly_startup_handler(handler, *, accounts, sessions):
    """Fail known pre-browser reads normally; all other exceptions stay unknown."""
    def wrapped(ctx, payload):
        count = len(sessions)
        try:
            return handler(ctx, payload)
        except Exception as error:
            if ctx.command['kind'] not in READONLY_KINDS or len(sessions) != count + 1:
                raise
            facts = classify_startup_failure(error, sessions[-1], accounts.folder(ctx.task_id))
            if facts is None:
                raise
            evidence = _freeze(accounts.folder(ctx.task_id) / 'READONLY_STARTUP_FAILURE.json', dict(
                schema='fanqie_readonly_startup_failure/v1', command_id=ctx.task_id,
                kind=ctx.command['kind'], resource_id=ctx.command['account_id'],
                binding_version=ctx.binding_version, owner_id=ctx.actor.owner_id,
                generation=ctx.actor.generation, **facts))
            return BrowserCommandResult('failed', dict(reason=CODE, known_local_failure=True,
                startup_evidence=evidence, original_request_replayed=False, **facts))
    return wrapped


def _snapshot(db, command_id):
    command = BrowserControlStore._command(db.execute(
        'SELECT * FROM browser_control_commands WHERE command_id=?', (command_id,)).fetchone())
    if not command:
        _reject('original_command_missing')
    row = db.execute('SELECT * FROM browser_control_owners WHERE account_id=?', (command['account_id'],)).fetchone()
    return command, dict(row) if row else None


def _check_subject(accounts, command, owner):
    if (command['kind'] not in READONLY_KINDS or command['state'] != 'outcome_unknown'
            or not command['account_id'].startswith('fanqie:') or not owner
            or any(owner[key] != command[key] for key in ('account_id', 'binding_version', 'owner_id', 'generation'))
            or owner['state'] == 'released'):
        _reject('original_readonly_unknown_required')
    env = accounts.get(command['account_id'])
    accounts.check_association(env)
    if env['binding_version'] != command['binding_version']:
        _reject('original_binding_changed')
    result = command.get('result') or {}
    causes = result.get('exception_causes') or []
    if (result.get('error_type') != 'BrowserWorkerStartupError'
            or len(causes) != 1 or causes[0].get('error_type') not in SAFE_CAUSES):
        _reject()


def _startup_log(accounts, command):
    folder = accounts.folder(command['command_id'])
    if not _no_business_artifacts(folder):
        _reject('business_or_unrecognised_evidence_present')
    text = (folder / 'worker.log').read_text(encoding='utf-8')
    events = [line for line in text.splitlines() if 'browser_worker_start ' in line]
    stages = [line for line in events if 'failure_evidence=' not in line]
    if (len(stages) != 2 or not re.search(r' stage=spawning_worker timeout_seconds=', stages[0])
            or not re.search(r' stage=spawning_worker outcome=failed error_type=(FileNotFoundError|PermissionError) elapsed_ms=\d+', stages[1])):
        _reject()
    facts = [json.loads(line.split('failure_evidence=', 1)[1]) for line in events if 'failure_evidence=' in line]
    if (len(facts) != 1 or facts[0].get('stage') != 'spawning_worker'
            or facts[0].get('cleanup_verified') is not True or facts[0].get('ready_received') is not False
            or 'worker_pid' in facts[0] or facts[0].get('driver_present_at_cleanup') is True):
        _reject()
    launch = json.loads((folder / 'WORKER_LAUNCH.json').read_text(encoding='utf-8'))
    process = json.loads((folder / 'WORKER_PROCESS.json').read_text(encoding='utf-8'))
    if (launch.get('command_id') != command['command_id'] or process.get('command_id') != command['command_id']
            or type(process.get('pid')) is not int or process['pid'] <= 0):
        _reject()
    return [bind(folder / name) for name in ('worker.log', 'WORKER_LAUNCH.json', 'WORKER_PROCESS.json')], process


def _check_process_proof(reference, command, owner, process):
    proof = _read(reference)
    if (proof.get('schema') != 'fanqie_readonly_owner_exit/v1' or proof.get('owner_exited') is not True
            or any(proof.get(key) != command[key] for key in ('command_id', 'owner_id', 'generation'))
            or proof.get('worker_process') != bind(process['path'])):
        _reject('owner_exit_proof_mismatch')
    checks = proof.get('processes')
    if (not isinstance(checks, list) or not checks or len({c.get('pid') for c in checks}) != len(checks)
            or process['pid'] not in {c.get('pid') for c in checks}):
        _reject('original_owner_process_not_checked')
    for check in checks:
        if (type(check.get('pid')) is not int or check['pid'] <= 0 or check.get('exists') is not False
                or not isinstance(check.get('observed_at_epoch'), (int, float))
                or check['observed_at_epoch'] < max(command['updated_at'], owner['updated_at'])
                or check['observed_at_epoch'] > time.time() + 5):
            _reject('owner_exit_proof_mismatch')
        # A reused live PID is a refusal, never a reason to kill another process.
        if psutil.pid_exists(check['pid']):
            _reject('original_owner_process_present')
    return proof


def prepare_recovery(accounts, command_id, process_proof_binding, output_directory):
    """Read original state, pin evidence, and prepare an explicit disposition."""
    with accounts.connection() as db:
        command, owner = _snapshot(db, command_id)
    _check_subject(accounts, command, owner)
    artifacts, process = _startup_log(accounts, command)
    process['path'] = artifacts[2]['path']
    _check_process_proof(process_proof_binding, command, owner, process)
    folder = _path(output_directory)
    if folder == accounts.folder(command_id) or folder.is_relative_to(accounts.folder(command_id)):
        _reject('recovery_evidence_must_be_separate')
    plan = dict(schema='fanqie_readonly_startup_recovery/v1', command_id=command_id,
        database=str(accounts.db.resolve()), command_snapshot=command, owner_snapshot=owner,
        command_snapshot_sha256=hashlib.sha256(_json(command).encode()).hexdigest(),
        source_artifacts=artifacts, process_proof=process_proof_binding,
        code=bind(__file__), disposition='failed_local_startup_only', request_replay_allowed=False)
    return _freeze(folder / 'RECOVERY_PLAN.json', plan)


def settle_recovery(accounts, plan_binding):
    """Resolve only the exact proven read failure; no queue, launch or retry."""
    plan = _read(plan_binding)
    if (plan.get('schema') != 'fanqie_readonly_startup_recovery/v1'
            or plan.get('database') != str(accounts.db.resolve()) or plan.get('code') != bind(__file__)
            or plan.get('request_replay_allowed') is not False
            or plan.get('command_snapshot_sha256') != hashlib.sha256(_json(plan.get('command_snapshot')).encode()).hexdigest()):
        _reject('recovery_plan_mismatch')
    _read(plan['process_proof'])  # Cached disposition must still pin every original proof.
    for artifact in plan['source_artifacts']:
        if bind(artifact['path']) != artifact:
            _reject('original_evidence_changed')
    with accounts.connection(True) as db:
        command, owner = _snapshot(db, plan['command_id'])
        if command['state'] == 'failed' and (command.get('result') or {}).get('recovery_plan') == plan_binding:
            return command  # Never release a later owner on cached reentry.
        if command != plan['command_snapshot'] or owner != plan['owner_snapshot']:
            _reject('original_snapshot_changed')
        _check_subject(accounts, command, owner)
        artifacts, process = _startup_log(accounts, command)
        if artifacts != plan['source_artifacts']:
            _reject('original_evidence_changed')
        process['path'] = artifacts[2]['path']
        _check_process_proof(plan['process_proof'], command, owner, process)
        pending = db.execute("SELECT 1 FROM browser_control_commands WHERE account_id=? AND command_id!=? AND state IN ('queued','running','paused','waiting_human','outcome_unknown') LIMIT 1",
                             (command['account_id'], command['command_id'])).fetchone()
        if pending:
            _reject('other_pending_command')
        now = time.time()
        result = dict(reason=CODE, known_local_failure=True, browser_worker_started=False,
            platform_requests_started=False, original_unknown_record_retained=True,
            before_snapshot=command, before_snapshot_sha256=plan['command_snapshot_sha256'],
            recovery_plan=plan_binding, settled_at=now, original_request_replayed=False)
        db.execute("UPDATE browser_control_commands SET state='failed',error_code=?,result=?,updated_at=? WHERE command_id=?",
                   (CODE, _json(result), now, command['command_id']))
        db.execute("UPDATE browser_control_owners SET state='released',updated_at=? WHERE account_id=? AND owner_id=? AND generation=?",
                   (now, command['account_id'], owner['owner_id'], owner['generation']))
        return _snapshot(db, command['command_id'])[0]
