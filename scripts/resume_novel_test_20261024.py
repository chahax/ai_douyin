"""One authorized orphan-window disposition, identity check, and short feed run."""
from contextlib import ExitStack
from pathlib import Path
import hashlib
import json
import sqlite3
import sys
import time
import psutil

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
OUT=ROOT/'data/novel_feed_activation/recovery_test_20261024'
ACCOUNT='account:9158f1d29f70eff9819c46b4'
CID='5252d3ba90ad4c6890b4527ec96be439'


def main():
    from src.operations_accounts.browser_control import BrowserControlStore,_json
    from src.operations_accounts.publication_autonomous_reconciliation import unresolved
    from scripts.handoff_idle_browser_control import assert_profile_exited
    from src.scheduler.account_refresh import set_playback_policy,complete_account_handling
    OUT.mkdir(exist_ok=False)
    auth={'decision_source':'explicit_user_statement','user_statement':'允许处置这条旧窗口并实测',
          'command_id':CID,'account_uuid':ACCOUNT,'identity_probe_limit':1,
          'test':{'max_videos':1,'per_video_seconds':15,'total_minutes':2,'headless':True,'muted':True},
          'replay_original':False}
    (OUT/'AUTHORIZATION.json').write_text(_json(auth),encoding='utf-8')
    store=BrowserControlStore(ROOT/'data/account_browser_control.db')
    with ExitStack() as stack:
        def fence(name):
            db=sqlite3.connect((ROOT/'data'/name).as_uri()+'?mode=rw',uri=True,timeout=5)
            stack.callback(db.close);stack.enter_context(db);db.row_factory=sqlite3.Row
            db.execute('BEGIN IMMEDIATE');return db
        plans=fence('account_refresh.db')
        control=dict(plans.execute('SELECT * FROM account_controls WHERE account_uuid=?',(ACCOUNT,)).fetchone())
        assert control['state']=='paused' and control['revision']==7 and not control['recovery_token']
        for table in ('refresh_accounts','smart_accounts','playback_accounts'):
            assert not plans.execute(f'SELECT 1 FROM {table} WHERE account_uuid=? AND (run_id IS NOT NULL OR lease_until!=0)',(ACCOUNT,)).fetchone()
        policy=dict(plans.execute('SELECT * FROM playback_policies WHERE account_uuid=?',(ACCOUNT,)).fetchone())
        runtime=fence('douyin.db')
        assert not runtime.execute("SELECT 1 FROM account_runtime_state WHERE account_uuid=? AND lock_owner!=''",(ACCOUNT,)).fetchone()
        profile=Path(runtime.execute('SELECT browser_profile_dir FROM account_runtime_bindings WHERE account_uuid=?',(ACCOUNT,)).fetchone()[0]).resolve()
        assert_profile_exited(profile)
        with store._db(write=True) as db:
            pending=unresolved(store,db,ACCOUNT,('queued','running','paused','waiting_human','outcome_unknown'))
            assert len(pending)==1 and pending[0]['command_id']==CID
            original=pending[0]
            owner=dict(db.execute('SELECT * FROM browser_control_owners WHERE account_id=?',(ACCOUNT,)).fetchone())
            assert original['kind']=='manual' and original['state']=='waiting_human'
            assert original['owner_id']==owner['owner_id'] and original['generation']==owner['generation']==8
            assert owner['heartbeat']<psutil.boot_time()-5 and original['updated_at']<psutil.boot_time()-5
            facts={'boot_time':psutil.boot_time(),'profile_absent':True,'leases_empty':True,'host_cannot_survive_boot':True}
            before={'control':control,'policy':policy,'command':original,'owner':owner,'facts':facts,'at':time.time()}
            (OUT/'BEFORE.json').write_text(_json(before),encoding='utf-8')
            db.execute('CREATE TABLE IF NOT EXISTS browser_control_operator_disposals(command_id TEXT PRIMARY KEY, original_command TEXT NOT NULL, original_owner TEXT NOT NULL, authorization TEXT NOT NULL, idle_evidence TEXT NOT NULL, disposed_at REAL NOT NULL)')
            now=time.time()
            db.execute('INSERT INTO browser_control_operator_disposals VALUES(?,?,?,?,?,?)',
                       (CID,_json(original),_json(owner),_json(auth),_json(facts),now))
            result={'operator_cancelled_unknown_manual':True,'original_outcome_known':False,
                    'original_snapshot_sha256':hashlib.sha256(_json(original).encode()).hexdigest(),
                    'authorization':str(OUT/'AUTHORIZATION.json'),'task_replayed':False,'cancelled_at':now}
            db.execute("UPDATE browser_control_commands SET state='failed',error_code='operator_cancelled_unknown_manual',result=?,updated_at=? WHERE command_id=?",(_json(result),now,CID))
            db.execute("UPDATE browser_control_owners SET state='released',updated_at=? WHERE account_id=? AND owner_id=? AND generation=?",(now,ACCOUNT,owner['owner_id'],8))
            # Configure the bounded test while the scheduler control remains paused.
            options=dict(max_videos=1,per_video_seconds=15,total_minutes=2,min_relevance_score=0.0,auto_like=False,auto_comment=False)
            plans.execute('UPDATE playback_policies SET options_json=?,authorization_reference=?,revision=revision+1,updated_at=? WHERE account_uuid=?',
                (_json(options),'user:approved-one-feed-test-20261024',now,ACCOUNT))
    (OUT/'DISPOSITION.json').write_text(_json({'at':time.time(),'old_window_cancelled':True,'old_owner_released':True,'old_uncertainty_preserved':True}),encoding='utf-8')
    outcome=complete_account_handling(ACCOUNT,'novel_account_02',handled_by='user:approved-one-feed-test-20261024',plan_kinds=('playback',),expected_revision=7)
    (OUT/'RECOVERY_REQUEST.json').write_text(_json(outcome),encoding='utf-8')
    print(_json(outcome))


if __name__=='__main__':main()
