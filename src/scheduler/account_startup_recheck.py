"""One bounded original-session recheck for a pause inherited from host boot."""
import json
import uuid

from . import account_refresh as refresh


RECHECKABLE = frozenset({'human_required', 'verification_ui_unconfirmed',
    'recovery_probe_failed', 'login_unhealthy', 'navigation_timeout'})


def browser_idle(store, account_uuid):
    from src.operations_accounts.publication_autonomous_reconciliation import unresolved
    with store._db() as db:
        owner = db.execute('SELECT state FROM browser_control_owners WHERE account_id=?', (account_uuid,)).fetchone()
        if owner and owner['state'] != 'released':
            return False
        return not unresolved(store, db, account_uuid, ('queued','running','paused','waiting_human','outcome_unknown'))


def request_rechecks(*, path=refresh.DB, store=None, boot_time=None, now=None):
    if boot_time is None:
        from src.operations_accounts.browser_boot_recovery import _boot_evidence
        evidence = _boot_evidence()
        if evidence is None:
            return []
        boot_time = evidence['boot_time']
    now = refresh.time.time() if now is None else now
    if not 0 < boot_time <= now - 300:
        return []
    candidates = [c for c in refresh.snapshot(path)['controls'] if c['state'] == 'paused'
                  and c['error_code'] in RECHECKABLE and c['updated_at'] < boot_time]
    if not candidates:
        return []
    if store is None:
        from src.operations_accounts import browser_control_runtime as bridge
        if not bridge.enabled():
            return []
        store = bridge._store()
    accepted = []
    for candidate in candidates:
        account = candidate['account_uuid']
        if not browser_idle(store, account):
            continue
        with refresh.connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM account_controls WHERE account_uuid=?', (account,)).fetchone()
            if (not row or row['account_key'] != candidate['account_key'] or row['state'] != 'paused'
                    or row['error_code'] not in RECHECKABLE or row['updated_at'] != candidate['updated_at']
                    or row['updated_at'] >= boot_time or row['recovery_token']
                    or refresh._handling_unresolved(db, account, now)):
                continue
            if db.execute("SELECT 1 FROM account_handling_requests WHERE account_uuid=? AND status IN ('requested','probing')", (account,)).fetchone():
                continue
            policies = refresh._handling_policies(db, account, row['account_key'])
            if not any(p and p['enabled'] for p in policies.values()):
                continue
            db.execute('''CREATE TABLE IF NOT EXISTS account_startup_rechecks(
                account_uuid TEXT NOT NULL,boot_time REAL NOT NULL,requested_at REAL NOT NULL,
                request_id TEXT NOT NULL,original_control TEXT NOT NULL,
                PRIMARY KEY(account_uuid,boot_time))''')
            if db.execute('SELECT 1 FROM account_startup_rechecks WHERE account_uuid=? AND (boot_time=? OR requested_at>?)',
                          (account, boot_time, now - 86400)).fetchone():
                continue
            targets = []
            for kind in refresh._PLAN_KINDS:
                latest = refresh._latest_plan_run(db, kind, account, row['account_key'])
                if (policies[kind] and policies[kind]['enabled'] and latest and latest['finished_at'] is not None
                        and latest['status'] in {'failed','blocked'}):
                    targets.append(dict(kind=kind, run_id=latest['run_id'], status=latest['status'], finished_at=latest['finished_at']))
            request_id = uuid.uuid4().hex
            revision = row['revision'] + 1
            db.execute('INSERT INTO account_startup_rechecks VALUES(?,?,?,?,?)',
                       (account, boot_time, now, request_id, json.dumps(dict(row), ensure_ascii=False)))
            db.execute("""UPDATE account_controls SET state='recovery_requested',recovery_requested_at=?,
                updated_at=?,revision=? WHERE account_uuid=?""", (now, now, revision, account))
            db.execute('''INSERT INTO account_handling_requests(request_id,account_uuid,account_key,handled_by,
                requested_at,control_revision,status,targets_json,policies_json,message) VALUES(?,?,?,?,?,?,?,?,?,?)''',
                (request_id, account, row['account_key'], 'automatic_startup_recheck', now, revision, 'requested',
                 json.dumps(targets), json.dumps(policies, sort_keys=True),
                 '重启后自动复核历史暂停；尚未证明验证已解除，原身份核验通过后才恢复。'))
            accepted.append(request_id)
    return accepted
