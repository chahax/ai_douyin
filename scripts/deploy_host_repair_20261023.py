"""Apply the approved repair to the exact idle backend and original queued task."""
import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
OUT=ROOT/'data/account_host_repair/20261023'
ACCOUNT='account:9e5f9e75192fa45becb945bc'
COMMAND='d8b6ffd9d8d5465db32e3b89da48f7ee'
RUN='6425a407962544248d1213efce857dca'


def main():
    import psutil
    from src.operations_accounts.browser_control import BrowserControlStore
    from src.operations_accounts.publication_autonomous_reconciliation import unresolved
    from src.operations_accounts.browser_host_retirement import retire
    from src.scheduler.browser_task_tracking import attach
    from src.scheduler.account_refresh import complete_account_handling
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    target=OUT/'DEPLOYMENT.json'
    if args.apply:assert not target.exists(),'Deployment already attempted; inspect receipt instead of retrying'
    suites=[]
    for name in ('test2.xml','regression.xml','final_tracking.xml'):
        suite=ET.parse(OUT/name).getroot().find('testsuite')
        assert int(suite.attrib['tests'])>0 and all(int(suite.attrib[k])==0 for k in ('errors','failures','skipped'))
        suites.append(dict(file=name,tests=int(suite.attrib['tests'])))
    proc=psutil.Process(7248)
    assert abs(proc.create_time()-1792728927.9687111)<.001
    assert proc.cmdline()==[str(ROOT/'.venv/Scripts/pythonw.exe'),str(ROOT/'scripts/run_streamlit_web.py')]
    assert int((ROOT/'data/logs/streamlit_web.pid').read_text())==proc.pid
    assert not proc.children(recursive=True)
    def no_profile_browser():
        for p in psutil.process_iter(['name','cmdline']):
            if p.info['name'].lower() not in ('chrome.exe','msedge.exe'):continue
            cmd=' '.join(p.info['cmdline'] or []).replace('\\','/').lower()
            assert not ('ai_douyin' in cmd and 'account01' in cmd),'Original profile browser still exists'
    no_profile_browser()
    store=BrowserControlStore(ROOT/'data/account_browser_control.db')
    with ExitStack() as stack:
        def fence(name):
            db=sqlite3.connect((ROOT/'data'/name).as_uri()+'?mode=rw',uri=True,timeout=3)
            stack.callback(db.close);stack.enter_context(db);db.row_factory=sqlite3.Row
            db.execute('BEGIN IMMEDIATE');return db
        plans=fence('account_refresh.db')
        control=dict(plans.execute('SELECT * FROM account_controls WHERE account_uuid=?',(ACCOUNT,)).fetchone())
        assert control['revision']==70 and control['state']=='paused' and not control['recovery_token']
        for table in ('refresh_accounts','smart_accounts','playback_accounts'):
            assert not plans.execute(f'SELECT 1 FROM {table} WHERE run_id IS NOT NULL OR lease_until!=0').fetchone()
        original_run=dict(plans.execute('SELECT * FROM refresh_runs WHERE run_id=?',(RUN,)).fetchone())
        assert original_run['status']=='failed' and json.loads(original_run['detail'])['error_code']=='command_wait_timeout'
        runtime=fence('douyin.db')
        assert not runtime.execute("SELECT 1 FROM account_runtime_state WHERE lock_owner!=''").fetchone()
        queue=fence('wisdom_ai.db')
        assert not queue.execute("SELECT 1 FROM task_executions WHERE status='running'").fetchone()
        with store._db(write=True) as db:
            pending=unresolved(store,db,ACCOUNT,('queued','running','paused','waiting_human','outcome_unknown'))
            assert len(pending)==1
            command=pending[0]
            assert command['command_id']==COMMAND and command['state']=='queued'
            assert command['owner_id'] is None and command['generation'] is None and command['result'] is None
            assert not db.execute('SELECT 1 FROM browser_control_execution WHERE command_id=?',(COMMAND,)).fetchone()
            owner=dict(db.execute('SELECT * FROM browser_control_owners WHERE account_id=?',(ACCOUNT,)).fetchone())
            assert owner['generation']==46 and owner['owner_id']=='backend:7248:f7ab0243a7ee404d98e676da0713e813'
            evidence={'at':time.time(),'authorization':'开发测试然后应用到这次吧','pid':proc.pid,'created_at':proc.create_time(),
                      'owner':owner,'command':command,'run':original_run,'control':control,'tests':suites,
                      'sources':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [
                          ROOT/'src/operations_accounts/browser_host_retirement.py',ROOT/'src/operations_accounts/browser_control_runtime.py',
                          ROOT/'src/scheduler/browser_task_tracking.py',ROOT/'src/scheduler/account_refresh.py',ROOT/'src/platform_adapter/browser_session.py']}}
            if args.apply:
                target.write_text(json.dumps(dict(evidence,phase='stop_intent'),ensure_ascii=False,indent=2),encoding='utf-8')
                no_profile_browser();assert not proc.children(recursive=True)
                proc.terminate();proc.wait(timeout=20)
                evidence['phase']='backend_stopped'
                target.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    if not args.apply:
        print(json.dumps({'phase':'ready','pid':proc.pid,'original_command':COMMAND}));return
    assert not psutil.pid_exists(proc.pid)
    no_profile_browser()
    assert retire(store,ACCOUNT,owner['owner_id'],owner['generation'],
        evidence={'host_stopped':True,'worker_stopped':True,'source':'approved_deployment',
                  'receipt':str(target),'pid':proc.pid,'created_at':evidence['created_at']},error_type='HistoricalStartupFailure')
    assert store.get(COMMAND)==command
    attach(command,store.path,run_id=RUN,path=ROOT/'data/account_refresh.db')
    result=complete_account_handling(ACCOUNT,'account01',handled_by='approved_host_repair_20261023')
    evidence.update(phase='deployed_recovery_requested',recovery=result)
    target.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    assert result['accepted'],result
    print(json.dumps({'phase':evidence['phase'],'original_command':COMMAND,'recovery':result},ensure_ascii=False))


if __name__=='__main__':main()
