"""Strictly read-only deployment barrier; never repairs production records."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'data/development_checkpoints/management_ui_audit_20261104'


def read(name, sql, args=()):
    with closing(sqlite3.connect((ROOT/'data'/name).as_uri()+'?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute(sql, args)]


def main():
    import psutil
    from src.shared.config import settings
    from src.operations_accounts import browser_control_runtime as bridge
    from src.operations_accounts.publication_autonomous_reconciliation import unresolved
    blockers = []
    pid = int((ROOT/'data/logs/streamlit_web.pid').read_text().strip())
    backend = psutil.Process(pid)
    if not any(Path(arg).resolve() == ROOT/'scripts/run_streamlit_web.py' for arg in backend.cmdline()[1:]):
        raise RuntimeError('Canonical backend mismatch')
    children = [{'pid': p.pid, 'name': p.name()} for p in backend.children(recursive=True)]
    if children:
        blockers.append('backend_has_children')
    controls = read('account_refresh.db', 'SELECT account_uuid,account_key,state,revision FROM account_controls')
    if not controls or any(row['state'] != 'paused' for row in controls):
        blockers.append('account_not_paused')
    runs = {}
    for kind in ('refresh', 'smart', 'playback'):
        runs[kind] = read('account_refresh.db', f"SELECT run_id,account_uuid,status FROM {kind}_runs WHERE status IN ('running','outcome_unknown')")
        if runs[kind]:
            blockers.append(kind+'_inflight_or_unknown')
    locks = read('douyin.db', 'SELECT account_uuid,lock_owner,lock_expires_at FROM account_runtime_state WHERE lock_owner IS NOT NULL AND lock_owner != ?', ('',))
    if locks:
        blockers.append('runtime_lock_present')
    store = bridge._store()
    pending = []
    with store._db() as db:
        for row in controls:
            for command in unresolved(store, db, row['account_uuid'], ('running','paused','waiting_human','outcome_unknown')):
                pending.append({key: command[key] for key in ('command_id','kind','state','owner_id','generation')})
    old_manual = '10b2bcfbba84499b93ad1a9891ec0226'
    if any(row['command_id'] != old_manual or row['kind'] != 'manual' or row['state'] != 'waiting_human' for row in pending):
        blockers.append('unresolved_business_or_new_manual')
    proof = json.loads((OUT/'PREBOOT_PLAN_READONLY_FINAL.json').read_text(encoding='utf-8'))
    if pending and (not proof['eligible'] or proof['boot_evidence']['backend_pid'] != pid
                    or proof['boot_evidence']['backend_create_time'] != backend.create_time()):
        blockers.append('old_manual_exit_proof_missing')
    # Only the known local scheduler store is supported by this deployment tool.
    if settings.DATABASE_URL != 'sqlite:///./data/wisdom_ai.db':
        blockers.append('custom_scheduler_database_requires_review')
        executions = []
    else:
        executions = read('wisdom_ai.db', "SELECT execution_uuid,status FROM task_executions WHERE status IN ('running','pending')")
        if executions:
            blockers.append('task_queue_not_idle')
    result = dict(captured_at=time.time(), backend_pid=pid, backend_create_time=backend.create_time(),
                  children=children, controls=controls, runs=runs, runtime_locks=locks,
                  unresolved=pending, task_executions=executions, blockers=blockers,
                  ready=not blockers, production_mutation=False)
    (OUT/'DEPLOY_PREFLIGHT.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'ready': not blockers, 'blockers': blockers, 'backend_pid': pid}))
    return 0 if not blockers else 2


if __name__ == '__main__':
    raise SystemExit(main())
