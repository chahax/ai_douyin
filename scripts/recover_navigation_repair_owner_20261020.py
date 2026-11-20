"""Supervised one-time retirement of the confirmed exited, idle backend 6572."""
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
from src.operations_accounts.browser_control import BrowserControlStore
from src.operations_accounts.publication_autonomous_reconciliation import unresolved

ACCOUNT = 'account:9e5f9e75192fa45becb945bc'
OWNER = 'backend:6572:fa2fc8d9aa264b1eb14b16e1321a9ab1'
OUT = ROOT / 'data/browser_navigation_repair/20261020'


def assert_backend_exited():
    if psutil.pid_exists(6572):
        raise RuntimeError('Original PID exists or was reused; retain owner')
    if (ROOT / 'data/logs/streamlit_web.pid').read_text().strip() != '6572':
        raise RuntimeError('Backend identity changed; retain owner')
    entry = ROOT / 'scripts/run_streamlit_web.py'
    for process in psutil.process_iter(['name']):
        if (process.info.get('name') or '').lower() not in {'python.exe', 'pythonw.exe'}:
            continue
        try:
            command = process.cmdline()
        except psutil.NoSuchProcess:
            continue
        if any(str(Path(v)).casefold() == str(entry).casefold() for v in command[1:]):
            raise RuntimeError('Another project backend exists; retain owner')
    assert_profile_exited(ROOT / 'data/douyin_warmup/accounts/account01/profile')


def main(execute=False):
    if (OUT / 'EXITED_OWNER_RELEASED.json').exists():
        raise RuntimeError('Recovery already recorded; do not repeat')
    assert_backend_exited()
    store = BrowserControlStore(ROOT / 'data/account_browser_control.db')
    with ExitStack() as stack:
        plans = stack.enter_context(sqlite3.connect(
            (ROOT / 'data/account_refresh.db').as_uri() + '?mode=rw', uri=True, timeout=3))
        plans.row_factory = sqlite3.Row
        plans.execute('BEGIN IMMEDIATE')
        for table in ('refresh_accounts', 'smart_accounts', 'playback_accounts'):
            if plans.execute(f'SELECT 1 FROM {table} WHERE run_id IS NOT NULL').fetchone():
                raise RuntimeError('Business lease remains; retain owner')
        control = dict(plans.execute('SELECT * FROM account_controls WHERE account_uuid=?', (ACCOUNT,)).fetchone())
        if control['state'] != 'paused' or control['revision'] != 48 or control['recovery_token']:
            raise RuntimeError('Original pause changed; retain owner')
        if plans.execute("SELECT 1 FROM account_handling_requests WHERE status IN ('requested','probing')").fetchone():
            raise RuntimeError('Handling request remains; retain owner')
        manual = stack.enter_context(sqlite3.connect(
            (ROOT / 'data/account_manual_windows.db').as_uri() + '?mode=rw', uri=True, timeout=3))
        manual.execute('BEGIN IMMEDIATE')
        if manual.execute("SELECT 1 FROM manual_window_jobs WHERE state NOT IN ('closed','failed')").fetchone():
            raise RuntimeError('Manual window unresolved; retain owner')
        with store._db(write=True) as db:
            if unresolved(store, db, ACCOUNT, ('queued','running','paused','waiting_human','outcome_unknown')):
                raise RuntimeError('Original command unresolved; retain owner')
            owner = dict(db.execute('SELECT * FROM browser_control_owners WHERE account_id=?', (ACCOUNT,)).fetchone())
            if owner['owner_id'] != OWNER or owner['generation'] != 34 or owner['state'] != 'active':
                raise RuntimeError('Owner changed; retain owner')
        assert_backend_exited()
        record = dict(at=time.time(), original_owner=owner, backend_pid_absent=True,
            original_profile_absent=True, business_leases_empty=True, unresolved_commands_empty=True,
            manual_windows_closed=True, account_state='paused', account_revision=48,
            evidence='TEST_QUEUE_CANCELLED.json',
            reason='User requested continued repair; original backend exited, no task replay or account resume')
        record['source_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        (OUT / 'EXITED_OWNER_PREFLIGHT.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
        if execute:
            store.release_owner(ACCOUNT, OWNER, 34)
            record['released_at'] = time.time()
            (OUT / 'EXITED_OWNER_RELEASED.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps({'preflight_passed':True,'owner_released':execute,'pause_preserved':True}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true')
    main(parser.parse_args().execute)
