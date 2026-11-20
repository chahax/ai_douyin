"""Explicit user cancellation of one accidental test, with original uncertainty retained."""
import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.handoff_idle_browser_control import assert_profile_exited
from src.operations_accounts.browser_control import BrowserControlStore, _json
from src.operations_accounts.publication_autonomous_reconciliation import unresolved

CID = '46186a716576430a98f2147d90ffda2f'
ACCOUNT = 'account:9e5f9e75192fa45becb945bc'
OWNER = 'backend:6572:fa2fc8d9aa264b1eb14b16e1321a9ab1'
OUT = ROOT / 'data/browser_navigation_repair/20261020'


def dispose(db, store, original, authorization, facts):
    if not db.in_transaction:
        raise RuntimeError('A writer fence is required')
    if authorization.get('user_response') != '取消' or authorization.get('command_id') != CID:
        raise RuntimeError('Exact operator authorization is required')
    current = dict(db.execute('SELECT * FROM browser_control_commands WHERE command_id=?', (CID,)).fetchone())
    if current != original or current['state'] != 'outcome_unknown' or current['kind'] != 'maintenance':
        raise RuntimeError('Original unknown request changed')
    if (current['account_id'] != ACCOUNT or current['owner_id'] != OWNER or current['generation'] != 34
            or json.loads(current['payload'])['options']['authorization_reference'] != 'local test, no network'):
        raise RuntimeError('Not the authorized accidental test')
    pending = unresolved(store, db, ACCOUNT, ('queued','running','paused','waiting_human','outcome_unknown'))
    if [r['command_id'] for r in pending] != [CID]:
        raise RuntimeError('Other unresolved work remains')
    owner = dict(db.execute('SELECT * FROM browser_control_owners WHERE account_id=?', (ACCOUNT,)).fetchone())
    if owner['owner_id'] != OWNER or owner['generation'] != 34 or owner['state'] != 'active':
        raise RuntimeError('Original owner changed')
    if not all(facts.get(k) is True for k in
               ('old_process_absent','profile_absent','leases_empty','manual_windows_closed','pause_preserved')):
        raise RuntimeError('Incomplete idle evidence')
    now = time.time()
    result = dict(operator_cancelled_unknown_test=True, original_outcome_known=False,
        original_snapshot_sha256=hashlib.sha256(_json(original).encode()).hexdigest(),
        user_response='取消', cancelled_at=now, task_replayed=False)
    db.execute('''CREATE TABLE IF NOT EXISTS browser_control_operator_disposals(
        command_id TEXT PRIMARY KEY, original_command TEXT NOT NULL, original_owner TEXT NOT NULL,
        authorization TEXT NOT NULL, idle_evidence TEXT NOT NULL, disposed_at REAL NOT NULL)''')
    db.execute('INSERT INTO browser_control_operator_disposals VALUES(?,?,?,?,?,?)',
        (CID,_json(original),_json(owner),_json(authorization),_json(facts),now))
    db.execute("""UPDATE browser_control_commands SET state='failed',
        error_code='operator_cancelled_unknown_test',result=?,updated_at=? WHERE command_id=?""",
        (_json(result),now,CID))
    db.execute("UPDATE browser_control_owners SET state='released',updated_at=? WHERE account_id=?",
        (now,ACCOUNT))
    return result


def main(execute=False):
    proposal = json.loads((OUT/'OPERATOR_DISPOSAL_PROPOSAL.json').read_text(encoding='utf8'))
    raw = (OUT/'TEST_UNKNOWN_ORIGINAL.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != proposal['original_snapshot_sha256']:
        raise RuntimeError('Frozen original evidence changed')
    original = json.loads(raw)
    authorization = dict(user_response='取消', command_id=CID, at=time.time(),
        approval_question='保留完整原始证据，人工取消这条测试任务并解除它的队列占用；不重跑该任务。',
        proposal_sha256=hashlib.sha256((OUT/'OPERATOR_DISPOSAL_PROPOSAL.json').read_bytes()).hexdigest())
    store = BrowserControlStore(ROOT/'data/account_browser_control.db')
    with ExitStack() as stack:
        def fence(name):
            db = stack.enter_context(sqlite3.connect((ROOT/'data'/name).as_uri()+'?mode=rw',uri=True,timeout=3))
            db.row_factory=sqlite3.Row
            db.execute('BEGIN IMMEDIATE')
            return db
        plans=fence('account_refresh.db')
        for table in ('refresh_accounts','smart_accounts','playback_accounts'):
            if plans.execute(f'SELECT 1 FROM {table} WHERE run_id IS NOT NULL').fetchone():
                raise RuntimeError('Business task remains')
        control=plans.execute('SELECT * FROM account_controls WHERE account_uuid=?',(ACCOUNT,)).fetchone()
        if control['state']!='paused' or control['revision']!=48 or control['recovery_token']:
            raise RuntimeError('Original pause changed')
        if plans.execute("SELECT 1 FROM account_handling_requests WHERE status IN ('requested','probing')").fetchone():
            raise RuntimeError('Handling request remains')
        manual=fence('account_manual_windows.db')
        if manual.execute("SELECT 1 FROM manual_window_jobs WHERE state NOT IN ('closed','failed')").fetchone():
            raise RuntimeError('Manual window unresolved')
        runtime=fence('douyin.db')
        if runtime.execute("SELECT 1 FROM account_runtime_state WHERE account_uuid=? AND lock_owner!=''",(ACCOUNT,)).fetchone():
            raise RuntimeError('Original runtime lease remains')
        if psutil.pid_exists(6572):
            raise RuntimeError('Old PID exists or reused; no disposition')
        assert_profile_exited(ROOT/'data/douyin_warmup/accounts/account01/profile')
        facts=dict(old_process_absent=True,profile_absent=True,leases_empty=True,
            manual_windows_closed=True,pause_preserved=True,checked_at=time.time())
        with store._db(write=True) as db:
            # The exact cancellation and owner retirement commit atomically.
            result=dispose(db,store,original,authorization,facts)
            if not execute:
                db.rollback()
            else:
                (OUT/'OPERATOR_CANCELLATION_INTENT.json').write_text(
                    json.dumps(dict(authorization=authorization,facts=facts),ensure_ascii=False,indent=2),encoding='utf8')
    if execute:
        (OUT/'OPERATOR_CANCELLATION_RESULT.json').write_text(
            json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(executed=execute,command_id=CID,owner_released=execute,
        account_pause_preserved=True,original_outcome_known=False)))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--execute',action='store_true')
    main(parser.parse_args().execute)
