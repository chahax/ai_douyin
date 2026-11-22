"""Audited handback after a host reboot or a proven backend and browser exit.

This never handles unknown business outcomes, runtime locks, account controls,
browser launch, identity verification or dispatch. Preview is strictly RO.
"""
import hashlib
import json
import math
import re
from pathlib import Path

from .browser_control import BrowserControlRejected, _json
from .browser_boot_recovery import _boot_evidence

TABLE = 'manual_previous_boot_closures'


def _reject():
    raise BrowserControlRejected('manual_boot_closure_unproven',
        '原窗口的退出证据、账号绑定或未决任务不匹配，未结清旧记录。')


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _previous_backend_gone(owner_pid, profile_dir, opened_at):
    """An orphan browser may outlive its backend. Missing evidence blocks closure."""
    import psutil
    if not psutil.WINDOWS or not profile_dir or not Path(profile_dir).is_absolute() or psutil.pid_exists(owner_pid):
        return False
    profile = Path(profile_dir).resolve()
    cache = Path(__file__).resolve().parents[2] / 'data/browser_worker_cache'
    for process in psutil.process_iter():
        try:
            name = process.name().lower()
            if name in {'chrome.exe','msedge.exe','chromium.exe','chrome-headless-shell.exe'}:
                args = process.cmdline()
                if not args:
                    return False
                for idx, arg in enumerate(args):
                    if arg.lower() == '--user-data-dir':
                        if idx + 1 >= len(args):
                            return False
                        directory = args[idx + 1]
                    elif arg.lower().startswith('--user-data-dir='):
                        directory = arg.split('=', 1)[1]
                    else:
                        continue
                    if Path(directory.strip('"')).resolve() == profile:
                        return False
            elif name in {'python.exe','pythonw.exe'} and process.create_time() <= opened_at:
                args = process.cmdline()
                if not args or any(Path(arg).parent == cache for arg in args[1:]):
                    return False
        except psutil.NoSuchProcess:
            continue
        except (psutil.Error, OSError, ValueError):
            return False
    return True


def _bound_profile(account_id, account_key, binding):
    from .browser_control_runtime import _manual_closure_binding
    version, directory = _manual_closure_binding(account_id, account_key)
    if version != binding:
        _reject()
    return directory


def _plan(store, db, account_id, account_key, command_id, binding, evidence):
    now = store.clock()
    if not isinstance(evidence, dict):
        _reject()
    boot, created = evidence.get('boot_time'), evidence.get('backend_create_time')
    if (not all(_number(v) for v in (boot, created, now)) or not boot <= created <= now
            or type(evidence.get('backend_pid')) is not int or evidence['backend_pid'] <= 0):
        _reject()
    raw = db.execute('SELECT * FROM browser_control_commands WHERE command_id=?', (command_id,)).fetchone()
    owner_row = db.execute('SELECT * FROM browser_control_owners WHERE account_id=?', (account_id,)).fetchone()
    command, owner = store._command(raw), dict(owner_row) if owner_row else None
    if (not command or not owner or command['account_id'] != account_id or command['kind'] != 'manual'
            or command['state'] != 'waiting_human' or owner['state'] not in {'active', 'outcome_unknown'}
            or command['payload'].get('account_uuid') != account_id
            or command['payload'].get('account_key') != account_key
            or not re.fullmatch(r'backend:[1-9][0-9]*:[a-f0-9]+', owner['owner_id'])
            or command['owner_id'] != owner['owner_id'] or command['generation'] != owner['generation']
            or command['binding_version'] != owner['binding_version'] or binding != owner['binding_version']):
        _reject()
    times = (owner['heartbeat'], owner['updated_at'], command['created_at'], command['updated_at'])
    if not all(_number(v) for v in times):
        _reject()
    cutoff = boot - 5
    reason = 'proven_previous_host_boot'
    if max(times) >= cutoff:
        if min(times) < boot or max(times) >= created or now - owner['heartbeat'] <= store.owner_ttl:
            _reject()
        profile_dir = _bound_profile(account_id, account_key, binding)
        if not _previous_backend_gone(int(owner['owner_id'].split(':')[1]), profile_dir, command['updated_at']):
            _reject()
        cutoff = created
        reason = 'proven_previous_backend_exit'
    request = [account_id, binding, command['kind'], command['payload'], command['priority']]
    if hashlib.sha256(_json(request).encode()).hexdigest() != command['request_sha']:
        _reject()
    from .publication_autonomous_reconciliation import unresolved
    pending = unresolved(store, db, account_id, ('running', 'paused', 'waiting_human', 'outcome_unknown'))
    if len(pending) != 1 or pending[0] != command:
        _reject()
    from .browser_execution_journal import exists
    journal = db.execute('SELECT * FROM browser_control_execution WHERE command_id=?',
                         (command_id,)).fetchone() if exists(db) else None
    if journal and (any(journal[k] != command[k] for k in ('request_sha', 'owner_id', 'generation'))
                    or not _number(journal['updated_at']) or journal['updated_at'] >= cutoff):
        _reject()
    proof = dict(schema='manual_previous_boot_closure/v1', account_id=account_id, account_key=account_key,
        command_id=command_id, binding_version=binding, owner=owner, request_sha=command['request_sha'],
        command_updated_at=command['updated_at'], result_sha=hashlib.sha256(_json(command.get('result')).encode()).hexdigest(),
        boot_evidence=evidence, original_execution=dict(journal) if journal else None)
    if reason == 'proven_previous_backend_exit':
        proof.update(close_reason=reason, profile_dir=str(profile_dir), schema='manual_previous_backend_closure/v1')
    return proof, command


def preview(store, account_id, account_key, command_id, binding):
    evidence = _boot_evidence()
    with store._db() as db:
        db.execute('BEGIN')
        proof, _ = _plan(store, db, account_id, account_key, command_id, binding, evidence)
    return {'available': True, 'proof_sha': hashlib.sha256(_json(proof).encode()).hexdigest(),
            'reason': proof.get('close_reason', 'proven_previous_host_boot')}


def settle(store, account_id, account_key, command_id, binding, proof_sha, requested_by):
    if (not isinstance(requested_by, str) or not requested_by.strip() or len(requested_by) > 200
            or re.search(r'(?i)(https?://|cookie\s*[:=]|password\s*[:=]|bearer\s)', requested_by)):
        _reject()
    evidence = _boot_evidence()
    with store._db(write=True) as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)).fetchone():
            previous = db.execute(f'SELECT account_id,proof_sha,proof FROM {TABLE} WHERE command_id=?', (command_id,)).fetchone()
            if previous:
                prior_proof = json.loads(previous['proof'])
                if (previous['account_id'] == account_id and previous['proof_sha'] == proof_sha
                        and prior_proof['account_key'] == account_key and prior_proof['binding_version'] == binding):
                    return {'status': 'already_settled'}
                _reject()
        proof, original = _plan(store, db, account_id, account_key, command_id, binding, evidence)
        if hashlib.sha256(_json(proof).encode()).hexdigest() != proof_sha:
            _reject()
        db.execute(f'''CREATE TABLE IF NOT EXISTS {TABLE}(
            command_id TEXT PRIMARY KEY, account_id TEXT NOT NULL, proof_sha TEXT NOT NULL,
            proof TEXT NOT NULL, original_command TEXT NOT NULL, requested_by TEXT NOT NULL,
            settled_at REAL NOT NULL)''')
        now = store.clock()
        db.execute(f'INSERT INTO {TABLE} VALUES(?,?,?,?,?,?,?)',
            (command_id, account_id, proof_sha, _json(proof), _json(original), requested_by.strip(), now))
        result = {'window_closed': True, 'identity_verified': False, 'session_saved': False,
                  'close_reason': proof.get('close_reason', 'proven_previous_host_boot'), 'original_result_sha': proof['result_sha']}
        db.execute("UPDATE browser_control_commands SET state='succeeded',result=?,error_code='',updated_at=? WHERE command_id=?",
                   (_json(result), now, command_id))
        from .browser_execution_journal import finish
        finish(db, original, 'succeeded', '', now)
        db.execute("UPDATE browser_control_owners SET state='released',updated_at=? WHERE account_id=?", (now, account_id))
    return {'status': 'settled', 'identity_verified': False, 'account_resumed': False}
