"""Explicit, audited closure of a manual window proven older than host boot.

This never handles unknown business outcomes, runtime locks, account controls,
browser launch, identity verification or dispatch. Preview is strictly RO.
"""
import hashlib
import json
import math
import re

from .browser_control import BrowserControlRejected, _json
from .browser_boot_recovery import _boot_evidence

TABLE = 'manual_previous_boot_closures'


def _reject():
    raise BrowserControlRejected('manual_boot_closure_unproven',
        '原窗口的系统重启证据、绑定或未决任务不匹配，未结清旧记录。')


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


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
            or command['binding_version'] != owner['binding_version'] or binding != owner['binding_version']
            or any(not _number(v) or v >= boot - 5 for v in
                   (owner['heartbeat'], owner['updated_at'], command['created_at'], command['updated_at']))):
        _reject()
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
                    or not _number(journal['updated_at']) or journal['updated_at'] >= boot - 5):
        _reject()
    proof = dict(schema='manual_previous_boot_closure/v1', account_id=account_id, account_key=account_key,
        command_id=command_id, binding_version=binding, owner=owner, request_sha=command['request_sha'],
        command_updated_at=command['updated_at'], result_sha=hashlib.sha256(_json(command.get('result')).encode()).hexdigest(),
        boot_evidence=evidence, original_execution=dict(journal) if journal else None)
    return proof, command


def preview(store, account_id, account_key, command_id, binding):
    evidence = _boot_evidence()
    with store._db() as db:
        db.execute('BEGIN')
        proof, _ = _plan(store, db, account_id, account_key, command_id, binding, evidence)
    return {'available': True, 'proof_sha': hashlib.sha256(_json(proof).encode()).hexdigest()}


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
                  'close_reason': 'proven_previous_host_boot', 'original_result_sha': proof['result_sha']}
        db.execute("UPDATE browser_control_commands SET state='succeeded',result=?,error_code='',updated_at=? WHERE command_id=?",
                   (_json(result), now, command_id))
        from .browser_execution_journal import finish
        finish(db, original, 'succeeded', '', now)
        db.execute("UPDATE browser_control_owners SET state='released',updated_at=? WHERE account_id=?", (now, account_id))
    return {'status': 'settled', 'identity_verified': False, 'account_resumed': False}
