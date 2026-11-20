"""One user-authorized disposition of the exact novel console and queued research."""
import hashlib
import json
import sqlite3
import time
from pathlib import Path

import psutil

from src.operations_accounts.browser_control import BrowserControlStore, _json

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT = 'account:9158f1d29f70eff9819c46b4'
CONSOLE = 'ca34df02c62048798c664a43b6d87037'
RESEARCH = 'e372aaf1eb214d9ead7a23f060294baa'
RUN = 'dae915a48c6c47e9b95b9089ffa88447'


def main():
    directory = ROOT / 'data/novel_feed_activation/recovery_20261023'
    directory.mkdir(exist_ok=False)
    authorization = {
        'decision_source': 'explicit_user_statement',
        'user_statement': '可以直接关闭重启吧',
        'previous_statement': '这个不对这个小说可以后续再说直接可以刷首页的视频吗',
        'account_uuid': ACCOUNT, 'command_id': CONSOLE,
        'scope': 'Dispose exact unknown console; cancel undispatched research; resume existing feed policy',
    }
    (directory / 'AUTHORIZATION.json').write_text(_json(authorization), encoding='utf-8')
    # No kill by executable name. The novel profile is already closed.
    profile = str(ROOT / 'data/douyin_warmup/accounts/novel_account_02/profile').lower()
    for process in psutil.process_iter(['pid', 'name', 'cmdline']):
        if process.info['name'].lower() in {'chrome.exe', 'msedge.exe'}:
            assert not any(a.lower() == '--user-data-dir=' + profile for a in process.info['cmdline'] or []), 'Novel browser still open'
    store = BrowserControlStore(ROOT / 'data/account_browser_control.db')
    before = store.get(CONSOLE)
    queued = store.get(RESEARCH)
    assert before['account_id'] == ACCOUNT and before['kind'] == 'official_console' and before['state'] == 'outcome_unknown'
    assert queued['account_id'] == ACCOUNT and queued['state'] == 'queued'
    assert queued['owner_id'] is None and queued['generation'] is None
    assert queued['payload']['mode'] == 'smart-operations'
    db = sqlite3.connect(ROOT / 'data/account_refresh.db', timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('BEGIN IMMEDIATE')
    run = dict(db.execute('SELECT * FROM smart_runs WHERE run_id=?', (RUN,)).fetchone())
    schedule = dict(db.execute('SELECT * FROM smart_accounts WHERE account_uuid=?', (ACCOUNT,)).fetchone())
    assert run['status'] == 'running' and schedule['run_id'] == RUN
    snapshot = {'console': before, 'research': queued, 'smart_run': run, 'smart_schedule': schedule}
    (directory / 'BEFORE.json').write_text(_json(snapshot), encoding='utf-8')
    try:
        cancelled = store.cancel_queued(RESEARCH, hashlib.sha256(_json(queued).encode()).hexdigest(),
            'User deferred novel research and requested home feed viewing', 'user-authorized-codex')
        now = time.time()
        detail = {'operator_cancelled_before_dispatch': True, 'external_browser_dispatched': False,
                  'command_id': RESEARCH, 'evidence': str(directory),
                  'message': '用户要求暂缓小说调研，先浏览首页；保留原记录，取消尚未派发任务。'}
        db.execute('UPDATE smart_runs SET status=?,finished_at=?,detail=? WHERE run_id=?',
                   ('cancelled_before_browser_dispatch', now, _json(detail), RUN))
        db.execute('UPDATE smart_accounts SET run_id=NULL,lease_until=0,next_due=? WHERE account_uuid=? AND run_id=?',
                   (now + 86400, ACCOUNT, RUN))
        db.commit()
    finally:
        db.close()
    # Exact compare-and-set; unknown history remains embedded, never a success.
    with store._db(write=True) as core:
        current = store._command(core.execute('SELECT * FROM browser_control_commands WHERE command_id=?', (CONSOLE,)).fetchone())
        assert current == before, 'Console changed; preserve remaining gate'
        result = {'operator_cancelled_unknown_console': True, 'original_outcome_known': False,
                  'authorization': authorization, 'before_snapshot': before,
                  'evidence_directory': str(directory), 'cancelled_at': time.time()}
        core.execute("UPDATE browser_control_commands SET state='failed',error_code='operator_cancelled_unknown_console',result=?,updated_at=? WHERE command_id=?",
                     (_json(result), time.time(), CONSOLE))
    receipt = {'at': time.time(), 'console': store.get(CONSOLE), 'research': cancelled,
               'browser_processes_killed': [], 'other_account_modified': False,
               'next_research_deferred_seconds': 86400, 'feed_policy_preserved': True}
    (directory / 'RECEIPT.json').write_text(_json(receipt), encoding='utf-8')
    print(json.dumps({'status': 'disposed_exact_tasks', 'receipt': str(directory / 'RECEIPT.json')}))


if __name__ == '__main__':
    main()
