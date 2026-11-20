"""One explicit 998cc disposition and deployment; never rerun."""
import sys,json,time,sqlite3,hashlib
from pathlib import Path
import xml.etree.ElementTree as ET
import psutil
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
OUT=ROOT/'data/novel_feed_activation/timeout_recovery_20261024'
A='account:9158f1d29f70eff9819c46b4'
CID='998cc4ec5d424db9bbddf993ee4ce4cb'

def main():
    from src.operations_accounts.browser_control import BrowserControlStore,_json
    from scripts.handoff_idle_browser_control import assert_profile_exited
    for filename,n in [('retained_feed_tests.xml',57),('retained_feed_final.xml',9),('feed_navigation_probe_final.xml',13)]:
        s=ET.parse(ROOT/'data/novel_feed_activation'/filename).getroot().find('testsuite')
        assert int(s.attrib['tests'])==n and all(int(s.attrib[k])==0 for k in ('errors','failures','skipped'))
    p=psutil.Process(37540);assert abs(p.create_time()-1792818857.0187273)<.001
    assert p.cmdline()==[str(ROOT/'.venv/Scripts/pythonw.exe'),str(ROOT/'scripts/run_streamlit_web.py')]
    assert_profile_exited(ROOT/'data/douyin_warmup/accounts/novel_account_02/profile')
    children=p.children(recursive=True)
    for c in children:
        args=c.cmdline()
        assert (c.name()=='pythonw.exe' and any('browser_worker_stage' in a for a in args)) or (c.name()=='node.exe' and 'playwright' in args[0]) or c.name()=='conhost.exe'
    store=BrowserControlStore(ROOT/'data/account_browser_control.db')
    original=store.get(CID)
    assert original['state']=='outcome_unknown' and original['kind']=='manual' and original['error_code']=='handler_exception:BrowserNavigationTimeout'
    with sqlite3.connect(ROOT/'data/account_refresh.db') as db:
        assert db.execute('SELECT state,revision FROM account_controls WHERE account_uuid=?',(A,)).fetchone()==('paused',13)
        for table in ('refresh_accounts','smart_accounts','playback_accounts'):
            assert not db.execute(f'SELECT 1 FROM {table} WHERE run_id IS NOT NULL OR lease_until!=0').fetchone()
    with store._db() as db:
        assert not db.execute("SELECT 1 FROM browser_control_commands WHERE state IN ('queued','running','paused')").fetchone()
        owner=dict(db.execute('SELECT * FROM browser_control_owners WHERE account_id=?',(A,)).fetchone())
        assert owner['owner_id']=='backend:37540:48a9984a4e044565aaafd8104f71f817' and owner['generation']==12
    OUT.mkdir(exist_ok=False)
    auth={'user_statement':'允许处置998cc并继续部署实测','command_id':CID,'account_uuid':A,'reopen_limit':1,'identity_probe_limit':1,'playback':'existing minimized muted daily policy','replay_original':False}
    (OUT/'AUTHORIZATION.json').write_text(_json(auth),encoding='utf-8')
    files=['src/operations_accounts/browser_control_runtime.py','src/operations_accounts/retained_feed_session.py','src/operations_accounts/clear_feed_resume.py','src/platform_adapter/browser_session.py','src/platform_adapter/recommendation_entry.py']
    before={'at':time.time(),'original_command':original,'original_owner':owner,'browser_exited':True,'process':{'pid':p.pid,'created_at':p.create_time()},'children':[{'pid':c.pid,'created_at':c.create_time(),'name':c.name()} for c in children],'sources':{f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in files}}
    (OUT/'BEFORE.json').write_text(_json(before),encoding='utf-8')
    p.terminate()
    try:p.wait(timeout=10)
    except psutil.TimeoutExpired:assert not psutil.pid_exists(p.pid)
    for c in children:
        if c.is_running():c.terminate()
    psutil.wait_procs(children,timeout=10)
    assert not psutil.pid_exists(p.pid) and not any(c.is_running() for c in children)
    assert_profile_exited(ROOT/'data/douyin_warmup/accounts/novel_account_02/profile')
    with store._db(write=True) as db:
        row=db.execute('SELECT state FROM browser_control_commands WHERE command_id=?',(CID,)).fetchone()
        assert row['state']=='outcome_unknown'
        db.execute('CREATE TABLE IF NOT EXISTS browser_control_operator_disposals(command_id TEXT PRIMARY KEY, original_command TEXT NOT NULL, original_owner TEXT NOT NULL, authorization TEXT NOT NULL, idle_evidence TEXT NOT NULL, disposed_at REAL NOT NULL)')
        now=time.time();facts={'original_browser_closed':True,'old_host_and_workers_exited':True,'business_leases_empty':True}
        db.execute('INSERT INTO browser_control_operator_disposals VALUES(?,?,?,?,?,?)',(CID,_json(original),_json(owner),_json(auth),_json(facts),now))
        result={'operator_cancelled_unknown_manual':True,'original_outcome_known':False,'original_snapshot_sha256':hashlib.sha256(_json(original).encode()).hexdigest(),'authorization':str(OUT/'AUTHORIZATION.json'),'task_replayed':False}
        db.execute("UPDATE browser_control_commands SET state='failed',error_code='operator_cancelled_unknown_manual',result=?,updated_at=? WHERE command_id=?",(_json(result),now,CID))
        db.execute("UPDATE browser_control_owners SET state='released',updated_at=? WHERE account_id=? AND owner_id=? AND generation=12",(now,A,owner['owner_id']))
    (OUT/'DISPOSITION.json').write_text(_json(result),encoding='utf-8')
    from src.operations_accounts.browser_control_runtime import queue_manual_window
    window=queue_manual_window(A,'novel_account_02','user:approved-998cc-disposition-and-minimized-resume')
    with sqlite3.connect(ROOT/'data/account_refresh.db') as db:
        assert db.execute('SELECT state,revision FROM account_controls WHERE account_uuid=?',(A,)).fetchone()==('paused',13)
        db.execute('INSERT INTO clear_feed_user_authorizations VALUES(?,?,?,?,NULL)',(window['job_id'],A,13,'User explicitly approved 998cc disposition, one reopened window and minimized original-session playback'))
    (OUT/'DEPLOYMENT.json').write_text(_json(window),encoding='utf-8');print(_json(window))

if __name__=='__main__':main()
