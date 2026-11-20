"""Stop only the verified idle backend; original owners/tasks are untouched."""
from contextlib import ExitStack
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'data/account_reboot_repair/20261022'
SOURCES = ('src/operations_accounts/browser_execution_journal.py',
    'src/operations_accounts/browser_control.py','src/operations_accounts/browser_boot_recovery.py',
    'src/operations_accounts/browser_control_runtime.py','src/scheduler/account_startup_recheck.py',
    'src/scheduler/account_refresh.py','src/scheduler/cron.py','src/web/account_browser_control_dashboard.py')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    import psutil
    from src.operations_accounts.browser_control import BrowserControlStore
    from src.operations_accounts.publication_autonomous_reconciliation import unresolved
    account='account:9e5f9e75192fa45becb945bc'
    command_id='6dbb0d77e18240a49b4df7d014089e89'
    receipts=[]
    for name in ('core2.xml','final1.xml','presentation.xml'):
        suite=ET.parse(OUT/name).getroot().find('testsuite')
        assert int(suite.attrib['tests'])>0
        assert all(int(suite.attrib[k])==0 for k in ('errors','failures','skipped'))
        receipts.append({'path':name,'tests':int(suite.attrib['tests'])})
    proc=psutil.Process(12416)
    assert abs(proc.create_time()-1792663760.2216053)<0.001
    assert proc.cmdline()==[str(ROOT/'.venv/Scripts/pythonw.exe'),str(ROOT/'scripts/run_streamlit_web.py')]
    assert int((ROOT/'data/logs/streamlit_web.pid').read_text())==proc.pid
    assert not proc.children(recursive=True)
    store=BrowserControlStore(ROOT/'data/account_browser_control.db')
    with ExitStack() as stack:
        def fence(name):
            db=sqlite3.connect((ROOT/'data'/name).as_uri()+'?mode=rw',uri=True,timeout=3)
            stack.callback(db.close)
            stack.enter_context(db)
            db.row_factory=sqlite3.Row;db.execute('BEGIN IMMEDIATE');return db
        plans=fence('account_refresh.db')
        controls=[dict(r) for r in plans.execute('SELECT * FROM account_controls')]
        assert all(c['state']=='paused' and not c['recovery_token'] for c in controls)
        for table in ('refresh_accounts','smart_accounts','playback_accounts'):
            assert not plans.execute(f'SELECT 1 FROM {table} WHERE run_id IS NOT NULL OR lease_until<>0').fetchone()
        runtime=fence('douyin.db')
        assert not runtime.execute("SELECT 1 FROM account_runtime_state WHERE lock_owner!=''").fetchone()
        from src.shared.config import settings
        from sqlalchemy.engine import make_url
        queue_url=make_url(settings.DATABASE_URL)
        assert queue_url.drivername=='sqlite'
        queue_path=Path(queue_url.database).resolve()
        assert queue_path==ROOT/'data/wisdom_ai.db'
        queue=fence('wisdom_ai.db')
        assert not queue.execute("SELECT 1 FROM task_executions WHERE status='running'").fetchone()
        with store._db(write=True) as db:
            pending=unresolved(store,db,account,('queued','running','paused','waiting_human','outcome_unknown'))
            assert len(pending)==1 and pending[0]['command_id']==command_id and pending[0]['state']=='running'
            owners=[dict(r) for r in db.execute('SELECT * FROM browser_control_owners')]
            assert all(o['heartbeat']<psutil.boot_time()-5 for o in owners)
            evidence={'at':time.time(),'pid':proc.pid,'created_at':proc.create_time(),'boot_time':psutil.boot_time(),
                'controls':controls,'original_commands':pending,'original_owners':owners,'tests':receipts,
                'sources':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in SOURCES}}
            if args.apply:
                target=OUT/'DEPLOY_STOP.json'
                assert not target.exists(),'Original deployment must not be repeated'
                target.write_text(json.dumps(dict(evidence,phase='stop_intent'),ensure_ascii=False,indent=2),encoding='utf-8')
                assert not proc.children(recursive=True)
                proc.terminate();proc.wait(timeout=20)
                evidence['phase']='idle_backend_stopped_original_tasks_preserved'
                target.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
            else:
                (OUT/'DEPLOY_PREVIEW.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'phase':evidence.get('phase','ready'),'pid':proc.pid,'original_task_preserved':command_id}))


if __name__=='__main__':main()
