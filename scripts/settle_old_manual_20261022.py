"""Exact user-authorized disposal; never retries the original window task."""
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
OUT=ROOT/'data/account_reboot_repair/20261022'
ACCOUNT='account:9e5f9e75192fa45becb945bc'
CID='6dbb0d77e18240a49b4df7d014089e89'


def main():
    import psutil
    from scripts.handoff_idle_browser_control import assert_profile_exited
    from src.operations_accounts.browser_control import BrowserControlStore,_json
    from src.operations_accounts.publication_autonomous_reconciliation import unresolved
    authorization=json.loads((OUT/'CANCEL_AND_PROBE_AUTHORIZATION.json').read_text(encoding='utf-8'))
    assert authorization['user_statement']=='允许取消这条旧开窗任务并核验'
    assert authorization['command_id']==CID and authorization['account_uuid']==ACCOUNT
    assert authorization['identity_probe_limit']==1 and authorization['replay_original'] is False
    receipt=OUT/'MANUAL_DISPOSITION.json'
    assert not receipt.exists(),'Existing disposition intent must be inspected, not retried'
    before=json.loads((OUT/'DEPLOY_STOP.json').read_text(encoding='utf-8'))
    store=BrowserControlStore(ROOT/'data/account_browser_control.db')
    with ExitStack() as stack:
        def fence(name):
            db=sqlite3.connect((ROOT/'data'/name).as_uri()+'?mode=rw',uri=True,timeout=3)
            stack.callback(db.close);stack.enter_context(db)
            db.row_factory=sqlite3.Row;db.execute('BEGIN IMMEDIATE');return db
        plans=fence('account_refresh.db')
        control=dict(plans.execute('SELECT * FROM account_controls WHERE account_uuid=?',(ACCOUNT,)).fetchone())
        assert control['state']=='paused' and control['revision']==63 and not control['recovery_token']
        for table in ('refresh_accounts','smart_accounts','playback_accounts'):
            assert not plans.execute(f'SELECT 1 FROM {table} WHERE run_id IS NOT NULL').fetchone()
        manual=fence('account_manual_windows.db')
        assert not manual.execute("SELECT 1 FROM manual_window_jobs WHERE state NOT IN ('closed','failed')").fetchone()
        runtime=fence('douyin.db')
        assert not runtime.execute("SELECT 1 FROM account_runtime_state WHERE lock_owner!=''").fetchone()
        profile=Path(runtime.execute('SELECT browser_profile_dir FROM account_runtime_bindings WHERE account_uuid=?',(ACCOUNT,)).fetchone()[0]).resolve()
        assert_profile_exited(profile)
        with store._db(write=True) as db:
            pending=unresolved(store,db,ACCOUNT,('queued','running','paused','waiting_human','outcome_unknown'))
            assert pending==before['original_commands'] and len(pending)==1 and pending[0]['command_id']==CID
            original=pending[0]
            owner=dict(db.execute('SELECT * FROM browser_control_owners WHERE account_id=?',(ACCOUNT,)).fetchone())
            assert owner==before['original_owners'][0]
            assert original['kind']=='manual' and original['owner_id']==owner['owner_id']
            assert owner['heartbeat']<psutil.boot_time()-5 and original['updated_at']<psutil.boot_time()-5
            facts={'boot_time':psutil.boot_time(),'original_process_cannot_survive_host_boot':True,
                   'profile_absent':True,'leases_empty':True,'pause_preserved':True}
            record={'authorization':authorization,'original_command':original,'original_owner':owner,'facts':facts,
                    'phase':'intent','at':time.time()}
            receipt.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
            db.execute('''CREATE TABLE IF NOT EXISTS browser_control_operator_disposals(
                command_id TEXT PRIMARY KEY, original_command TEXT NOT NULL, original_owner TEXT NOT NULL,
                authorization TEXT NOT NULL, idle_evidence TEXT NOT NULL, disposed_at REAL NOT NULL)''')
            now=time.time()
            db.execute('INSERT INTO browser_control_operator_disposals VALUES(?,?,?,?,?,?)',
                       (CID,_json(original),_json(owner),_json(authorization),_json(facts),now))
            result={'operator_cancelled_unknown_manual':True,'original_outcome_known':False,
                    'original_snapshot_sha256':hashlib.sha256(_json(original).encode()).hexdigest(),
                    'task_replayed':False,'cancelled_at':now}
            db.execute("UPDATE browser_control_commands SET state='failed',error_code='operator_cancelled_unknown_manual',result=?,updated_at=? WHERE command_id=?",
                       (_json(result),now,CID))
            db.execute("UPDATE browser_control_owners SET state='released',updated_at=? WHERE account_id=? AND owner_id=? AND generation=?",
                       (now,ACCOUNT,owner['owner_id'],owner['generation']))
    record['phase']='cancelled_original_unknown_preserved'
    receipt.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    # The normal startup scan may already have recorded the single request.
    # This entrypoint is idempotent and never queues a second pending probe.
    from src.scheduler.account_refresh import complete_account_handling
    outcome=complete_account_handling(ACCOUNT,'account01',handled_by='explicit_user_reboot_repair_20261022')
    (OUT/'IDENTITY_PROBE_REQUEST.json').write_text(json.dumps(outcome,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'disposition':record['phase'],'recovery':outcome},ensure_ascii=False))


if __name__=='__main__':main()
