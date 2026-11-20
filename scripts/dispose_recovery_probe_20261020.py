"""One explicit operator disposition; never infer approval or retry the old probe."""
import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'data/browser_navigation_repair/20261020/production_smoke'
CID = '66847ff658b54c939c816e258c0df99d'
ACCOUNT = 'account:9e5f9e75192fa45becb945bc'
OWNER = 'backend:21472:0e8b7aa5ee0d4e53889dd95ef421dcde'


def dispose(db, store, original, approval, facts):
    from src.operations_accounts.browser_control import _json
    from src.operations_accounts.publication_autonomous_reconciliation import unresolved
    if not db.in_transaction:
        raise RuntimeError('Writer fence required')
    if (approval.get('command_id') != CID or approval.get('cancel_unknown_probe') is not True
            or not approval.get('user_statement')):
        raise RuntimeError('Explicit authorization for this unknown probe required')
    current = dict(db.execute('SELECT * FROM browser_control_commands WHERE command_id=?', (CID,)).fetchone())
    if current != original:
        raise RuntimeError('Original probe changed')
    pending = unresolved(store, db, ACCOUNT, ('queued','running','paused','waiting_human','outcome_unknown'))
    if [r['command_id'] for r in pending] != [CID]:
        raise RuntimeError('Other unresolved work remains')
    if (current['kind'] != 'recovery' or current['state'] != 'outcome_unknown'
            or current['account_id'] != ACCOUNT or current['owner_id'] != OWNER
            or current['generation'] != 35
            or current['error_code'] != 'handler_exception:AccountRuntimeError'):
        raise RuntimeError('Not the reviewed recovery failure')
    owner = dict(db.execute('SELECT * FROM browser_control_owners WHERE account_id=?', (ACCOUNT,)).fetchone())
    if owner['owner_id'] != OWNER or owner['generation'] != 35 or owner['state'] != 'active':
        raise RuntimeError('Owner changed')
    if not all(facts.get(k) is True for k in ('process_exited', 'profile_exited',
            'leases_empty', 'manual_windows_closed', 'pause_preserved', 'only_original_unresolved')):
        raise RuntimeError('Incomplete quiescence evidence')
    now = time.time()
    db.execute('''CREATE TABLE IF NOT EXISTS browser_control_operator_disposals(
        command_id TEXT PRIMARY KEY, original_command TEXT NOT NULL, original_owner TEXT NOT NULL,
        authorization TEXT NOT NULL, idle_evidence TEXT NOT NULL, disposed_at REAL NOT NULL)''')
    db.execute('INSERT INTO browser_control_operator_disposals VALUES(?,?,?,?,?,?)',
        (CID, _json(original), _json(owner), _json(approval), _json(facts), now))
    result = {'operator_cancelled_unknown_probe': True, 'original_outcome_known': False,
        'task_replayed': False, 'original_command_sha256': hashlib.sha256(_json(original).encode()).hexdigest()}
    db.execute("UPDATE browser_control_commands SET state='failed', error_code='operator_cancelled_unknown_probe', result=?, updated_at=? WHERE command_id=?",
        (_json(result), now, CID))
    db.execute("UPDATE browser_control_owners SET state='released',updated_at=? WHERE account_id=?",
        (now, ACCOUNT))
    return result


def main(approval_path):
    import psutil
    from scripts.handoff_idle_browser_control import idle_headless_worker_children, assert_profile_exited
    from src.operations_accounts.browser_control import BrowserControlStore
    from src.operations_accounts.publication_autonomous_reconciliation import unresolved
    proposal = json.loads((OUT/'RECOVERY_DISPOSAL_PROPOSAL.json').read_bytes())
    raw = (OUT/'RECOVERY_FAILURE_ORIGINAL.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != proposal['original_command_sha256']:
        raise RuntimeError('Original evidence changed')
    approval = json.loads(Path(approval_path).read_bytes())
    if (approval.get('command_id') != CID or approval.get('cancel_unknown_probe') is not True
            or approval.get('deploy_and_smoke') is not True or not approval.get('user_statement')):
        raise RuntimeError('Explicit reviewed disposition and deployment approval required')
    original = json.loads(raw)
    store = BrowserControlStore(ROOT/'data/account_browser_control.db')
    receipt = OUT/'RECOVERY_DISPOSAL_EXECUTION.json'
    if receipt.exists():
        raise RuntimeError('Previous execution exists; inspect instead of retrying')
    with ExitStack() as stack:
        def fence(name):
            db = stack.enter_context(sqlite3.connect((ROOT/'data'/name).as_uri()+'?mode=rw',uri=True,timeout=3))
            db.row_factory = sqlite3.Row
            db.execute('BEGIN IMMEDIATE')
            return db
        plans = fence('account_refresh.db')
        control = plans.execute('SELECT * FROM account_controls WHERE account_uuid=?',(ACCOUNT,)).fetchone()
        if control['state'] != 'paused' or control['revision'] != 50 or control['recovery_token']:
            raise RuntimeError('Pause changed')
        for table in ('refresh_accounts','smart_accounts','playback_accounts'):
            if plans.execute(f'SELECT 1 FROM {table} WHERE run_id IS NOT NULL OR coalesce(lease_until,0)<>0').fetchone():
                raise RuntimeError('Business work remains')
        if plans.execute("SELECT 1 FROM account_handling_requests WHERE status IN ('requested','probing')").fetchone():
            raise RuntimeError('Handling work remains')
        manual = fence('account_manual_windows.db')
        if manual.execute("SELECT 1 FROM manual_window_jobs WHERE state NOT IN ('closed','failed')").fetchone():
            raise RuntimeError('Manual window remains')
        runtime = fence('douyin.db')
        if runtime.execute("SELECT 1 FROM account_runtime_state WHERE lock_owner!=''").fetchone():
            raise RuntimeError('Runtime lease remains')
        profile = runtime.execute('SELECT browser_profile_dir FROM account_runtime_bindings WHERE account_uuid=?',(ACCOUNT,)).fetchone()[0]
        if Path(profile).resolve() != Path(proposal['profile']).resolve():
            raise RuntimeError('Profile changed')
        with store._db(write=True) as db:
            pending = unresolved(store,db,ACCOUNT,('queued','running','paused','waiting_human','outcome_unknown'))
            if [r['command_id'] for r in pending] != [CID]:
                raise RuntimeError('Other unresolved work remains')
            current = dict(db.execute('SELECT * FROM browser_control_commands WHERE command_id=?',(CID,)).fetchone())
            owner = dict(db.execute('SELECT * FROM browser_control_owners WHERE account_id=?',(ACCOUNT,)).fetchone())
            if current != original or owner['owner_id'] != OWNER or owner['generation'] != 35 or owner['state'] != 'active':
                raise RuntimeError('Command or owner changed')
            proc = psutil.Process(proposal['service_pid'])
            if (proc.create_time() != proposal['process_create_time']
                    or Path(proc.cwd()).resolve() != ROOT
                    or str(ROOT/'scripts/run_streamlit_web.py').lower() not in [s.lower() for s in proc.cmdline()]
                    or int((ROOT/'data/logs/streamlit_web.pid').read_text()) != proc.pid):
                raise RuntimeError('Service identity changed')
            children, evidence = idle_headless_worker_children(proc, profile, proposal['worker_script_sha256'])
            record = dict(command_id=CID, phase='stop_requested', original_outcome_known=False,
                process_pid=proc.pid, process_create_time=proc.create_time(), children=evidence)
            receipt.write_text(json.dumps(record,indent=2),encoding='utf8')
            proc.terminate()
            proc.wait(timeout=5)
            _, alive = psutil.wait_procs(children,timeout=10)
            if alive:
                raise RuntimeError('Original worker family has not exited; no disposition committed')
            assert_profile_exited(profile)
            facts = dict(process_exited=True,profile_exited=True,leases_empty=True,
                manual_windows_closed=True,pause_preserved=True,only_original_unresolved=True)
            result = dispose(db,store,original,approval,facts)
        record.update(phase='disposed_owner_released',result=result,completed_at=time.time())
        receipt.write_text(json.dumps(record,indent=2),encoding='utf8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--approval', required=True)
    main(parser.parse_args().approval)
