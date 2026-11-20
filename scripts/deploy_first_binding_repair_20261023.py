"""Deploy first-binding fix only while both accounts and backend are idle."""
from contextlib import ExitStack
import argparse,hashlib,json,sqlite3,sys,time
from pathlib import Path
import xml.etree.ElementTree as ET
import psutil

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
OUT=ROOT/'data/first_binding_repair/20261023'


def main():
    from src.operations_accounts.browser_control import BrowserControlStore
    from src.operations_accounts.publication_autonomous_reconciliation import unresolved
    p=argparse.ArgumentParser();p.add_argument('--apply',action='store_true');args=p.parse_args()
    for name in ('tests.xml','final.xml'):
        suite=ET.parse(OUT/name).getroot().find('testsuite')
        assert int(suite.attrib['tests'])>0 and all(int(suite.attrib[k])==0 for k in ('errors','failures','skipped'))
    proc=psutil.Process(21204)
    assert abs(proc.create_time()-1792753406.4510572)<.001
    assert proc.cmdline()==[str(ROOT/'.venv/Scripts/pythonw.exe'),str(ROOT/'scripts/run_streamlit_web.py')]
    assert int((ROOT/'data/logs/streamlit_web.pid').read_text())==proc.pid
    assert not proc.children(recursive=True)
    store=BrowserControlStore(ROOT/'data/account_browser_control.db')
    with ExitStack() as stack:
        def fence(name):
            db=sqlite3.connect((ROOT/'data'/name).as_uri()+'?mode=rw',uri=True,timeout=3)
            stack.callback(db.close);stack.enter_context(db);db.row_factory=sqlite3.Row;db.execute('BEGIN IMMEDIATE');return db
        plans=fence('account_refresh.db')
        for table in ('refresh_accounts','smart_accounts','playback_accounts'):
            assert not plans.execute(f'SELECT 1 FROM {table} WHERE run_id IS NOT NULL OR lease_until!=0').fetchone()
        assert not plans.execute("SELECT 1 FROM account_controls WHERE state IN ('recovering','recovery_requested')").fetchone()
        accounts=fence('douyin.db')
        assert not accounts.execute("SELECT 1 FROM account_runtime_state WHERE lock_owner!=''").fetchone()
        assert not accounts.execute("SELECT 1 FROM account_runtime_bindings WHERE account_key='novel_account_02'").fetchone()
        identity_rows=[dict(r) for r in accounts.execute('SELECT account_uuid,account_key,platform_identity_key,browser_environment_key FROM account_runtime_bindings')]
        queue=fence('wisdom_ai.db')
        assert not queue.execute("SELECT 1 FROM task_executions WHERE status='running'").fetchone()
        with store._db(write=True) as db:
            assert not db.execute("SELECT 1 FROM browser_control_owners WHERE state!='released'").fetchone()
            for key in ('account:9e5f9e75192fa45becb945bc','account:9158f1d29f70eff9819c46b4'):
                assert not unresolved(store,db,key,('queued','running','paused','waiting_human','outcome_unknown'))
            paths=['src/operations_accounts/runtime.py','src/web/trend_dashboard.py']
            proof={'at':time.time(),'pid':proc.pid,'created_at':proc.create_time(),'bindings_before':identity_rows,
                   'sources':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in paths},
                   'new_account_bound':False,'phase':'preview'}
            if args.apply:
                target=OUT/'DEPLOYMENT.json';assert not target.exists()
                proof['phase']='stop_intent';target.write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
                assert not proc.children(recursive=True)
                proc.terminate();proc.wait(timeout=20)
                proof['phase']='idle_backend_stopped'
                target.write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'phase':proof['phase'],'account':'novel_account_02','binding_unchanged':True}))


if __name__=='__main__':main()
