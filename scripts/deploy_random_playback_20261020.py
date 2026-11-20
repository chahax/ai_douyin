"""One supervised, fenced upgrade after the two known terminal playback attempts."""
import hashlib
import json
from pathlib import Path
import sys
import time

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.handoff_idle_browser_control import idle_headless_worker_children, assert_profile_exited
from src.operations_accounts.browser_control import BrowserControlStore
from src.operations_accounts.publication_autonomous_reconciliation import unresolved
from src.scheduler import account_refresh as refresh
from src.platform_adapter.browser_session import _PW_SCRIPT


def main():
    account = 'account:9e5f9e75192fa45becb945bc'
    profile = ROOT / 'data/douyin_warmup/accounts/account01/profile'
    evidence = ROOT / 'data/playback_random_schedule/20261020/DEPLOYMENT_STOP.json'
    if evidence.exists():
        raise RuntimeError('Original deployment already recorded; do not repeat retirement')
    proc = psutil.Process(5632)
    assert proc.create_time() == 1792461513.9718273
    assert Path(proc.cwd()).resolve() == ROOT
    assert [str(Path(x).resolve()) for x in proc.cmdline()] == [
        str((ROOT / '.venv/Scripts/pythonw.exe').resolve()),
        str((ROOT / 'scripts/run_streamlit_web.py').resolve())]
    assert int((ROOT / 'data/logs/streamlit_web.pid').read_text()) == proc.pid
    store = BrowserControlStore(ROOT / 'data/account_browser_control.db')
    with refresh.connect() as plans:
        plans.execute('BEGIN IMMEDIATE')
        for table in ('refresh_accounts', 'smart_accounts', 'playback_accounts'):
            assert not plans.execute(f'SELECT 1 FROM {table} WHERE run_id IS NOT NULL').fetchone()
        control = dict(plans.execute('SELECT * FROM account_controls WHERE account_uuid=?', (account,)).fetchone())
        assert control['state'] == 'paused' and control['revision'] == 48 and not control['recovery_token']
        assert not plans.execute("SELECT 1 FROM account_handling_requests WHERE status IN ('requested','probing')").fetchone()
        with store._db(write=True) as db:
            assert not unresolved(store, db, account, ('queued', 'running', 'paused', 'waiting_human', 'outcome_unknown'))
            owner = dict(db.execute('SELECT * FROM browser_control_owners WHERE account_id=?', (account,)).fetchone())
            assert owner['owner_id'].startswith('backend:5632:') and owner['generation'] == 33
            children, child_evidence = idle_headless_worker_children(proc, profile, hashlib.sha256(_PW_SCRIPT.encode()).hexdigest())
            record = {'at': time.time(), 'pid': proc.pid, 'create_time': proc.create_time(),
                      'owner': owner, 'control': control, 'children': child_evidence,
                      'reason': 'Deploy tested daily random schedule; preserve current timeout pause and terminal attempts'}
            evidence.with_name('DEPLOYMENT_STOP_INTENT.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
            proc.terminate()
            proc.wait(15)
    _, alive = psutil.wait_procs(children, timeout=30)
    assert not alive, 'Original worker children remain; do not release owner or start replacement'
    assert_profile_exited(profile)
    store.release_owner(account, owner['owner_id'], owner['generation'])
    record['finished_at'] = time.time()
    record['owner_released'] = True
    record['pause_preserved'] = True
    evidence.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'stopped_pid': proc.pid, 'owner_released': True, 'pause_preserved': True}))


if __name__ == '__main__':
    main()
