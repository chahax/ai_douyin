"""Guarded, explicitly authorized diagnostics reload and one manual request.
No process stop/start inside Python; original Windows task is controlled by caller.
"""
from pathlib import Path
import hashlib
import json
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/development_checkpoints/browser_history_compare_20261105'
sys.path.insert(0,str(ROOT))
from execute_idle_browser_exit_20261105 import rows, processes


def load(name):return json.loads((OUT/name).read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(name,obj):
    with (OUT/name).open('x',encoding='utf-8') as f:json.dump(obj,f,ensure_ascii=False,indent=2)


def frozen():
    auth=load('OBSERVATION_AUTHORIZATION.json')
    assert auth['user_statement']=='允许加载诊断并开窗一次'
    assert auth['plan_sha256']==sha(OUT/'NEXT_DRIVER_OBSERVATION_PLAN.json')
    plan=load('NEXT_DRIVER_OBSERVATION_PLAN.json')
    assert plan['candidate_manifest_sha256']==sha(OUT/'DRIVER_DIAGNOSTICS_CANDIDATE.json')
    diag=load('DRIVER_DIAGNOSTICS_CANDIDATE.json')
    replacement={x['file']:x for x in diag['files']}
    baseline=json.loads((ROOT/'data/development_checkpoints/manual_open_queue_20261105/STARTUP_CANDIDATE_MANIFEST.json').read_text(encoding='utf-8'))
    for item in baseline['files']+baseline['test_reports']+[baseline['driver_binary']]:
        actual=replacement.get(item['file'],item)
        assert sha(ROOT/actual['file'])==actual['sha256'],'Reviewed source changed: '+actual['file']
    for item in diag['files']+[diag['regression'],diag['real_api_results']]:
        assert sha(ROOT/item['file'])==item['sha256'],'Diagnostic candidate changed'


def idle():
    from src.operations_accounts.browser_control_runtime import _store
    from src.operations_accounts.publication_autonomous_reconciliation import unresolved
    controls=rows('account_refresh.db','SELECT account_key,state,revision FROM account_controls')
    assert sorted((c['account_key'],c['state'],c['revision']) for c in controls)==[
        ('account01','paused',73),('novel_account_02','paused',41)]
    for kind in ('refresh','smart','playback'):
        assert not rows('account_refresh.db',f"SELECT run_id FROM {kind}_runs WHERE status IN ('running','outcome_unknown')")
    assert not rows('douyin.db',"SELECT account_uuid FROM account_runtime_state WHERE lock_owner IS NOT NULL AND lock_owner!=''")
    assert not rows('wisdom_ai.db',"SELECT execution_uuid FROM task_executions WHERE status IN ('running','pending')")
    store=_store();uid='account:9158f1d29f70eff9819c46b4'
    with store._db() as db:
        assert not unresolved(store,db,uid,('queued','running','paused','waiting_human','outcome_unknown'))
        owner=dict(db.execute('SELECT * FROM browser_control_owners WHERE account_id=?',(uid,)).fetchone())
    assert owner['state']=='released' and owner['generation']==25
    protected=rows('account_browser_control.db','SELECT command_id,state,owner_id,generation,request_sha,updated_at FROM browser_control_commands WHERE command_id=?',('10b2bcfbba84499b93ad1a9891ec0226',))
    return controls,owner,protected


def main(phase):
    import psutil
    frozen()
    controls,owner,protected=idle()
    scan=processes()
    assert not scan['project_engines'] and not scan['unqueryable_targets'],'Browser family state unknown'
    if phase=='before':
        pid=int((ROOT/'data/logs/streamlit_web.pid').read_text())
        assert pid==17852
        p=psutil.Process(pid)
        assert p.create_time()==1793851756.3479247 and not p.children(recursive=True)
        assert str(ROOT/'scripts/run_streamlit_web.py') in p.cmdline()
        family={pid}
        parent=p.parent()
        if parent and str(ROOT/'scripts/run_streamlit_web.py') in parent.cmdline():family.add(parent.pid)
        assert {x['pid'] for x in scan['canonical_backends']}<=family
        save('OBSERVATION_BEFORE_RELOAD.json',{'at':time.time(),'backend_pid':pid,'backend_create_time':p.create_time(),
            'controls':controls,'owner':owner,'protected':protected,'process_scan':scan})
        print(json.dumps({'ready':True,'backend_pid':pid}))
    elif phase=='after_exit':
        before=load('OBSERVATION_BEFORE_RELOAD.json')
        assert time.time()-before['at']<=180
        assert not psutil.pid_exists(before['backend_pid']) and not scan['canonical_backends']
        assert controls==before['controls'] and owner==before['owner'] and protected==before['protected']
        save('OBSERVATION_ACTUAL_EXIT.json',{'at':time.time(),'old_backend_exited':True,
            'process_scan':scan,'controls':controls,'owner':owner,'owner_mutated':False,'protected':protected})
        print(json.dumps({'exit_proven':True,'owner_unchanged':True}))
    elif phase=='queue_once':
        import urllib.request
        pid=int((ROOT/'data/logs/streamlit_web.pid').read_text());p=psutil.Process(pid)
        assert pid!=17852 and p.create_time()>load('OBSERVATION_ACTUAL_EXIT.json')['at']
        assert str(ROOT/'scripts/run_streamlit_web.py') in p.cmdline()
        assert urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health',timeout=4).status==200
        before=load('OBSERVATION_BEFORE_RELOAD.json')
        assert controls==before['controls'] and protected==before['protected']
        authsha=sha(OUT/'OBSERVATION_AUTHORIZATION.json')
        marker='user-confirmed:driver-observation:'+authsha[:16]
        save('OBSERVATION_ONCE_INTENT.json',{'at':time.time(),'backend_pid':pid,'backend_create_time':p.create_time(),
            'requested_by':marker,'allow_automatic_resume':False,'authorization_sha256':authsha,'budget':1})
        from src.operations_accounts.browser_control_runtime import queue_manual_window,_store
        job=queue_manual_window('account:9158f1d29f70eff9819c46b4','novel_account_02',marker,allow_automatic_resume=False)
        assert not job.get('reused')
        command=_store().get(job['job_id'])
        assert command['payload']['allow_automatic_resume'] is False and command['payload']['requested_by']==marker
        receipt={'at':time.time(),'command_id':job['job_id'],'request_sha':command['request_sha'],
            'binding_version':command['binding_version'],'backend_pid':pid,'state':command['state'],
            'allow_automatic_resume':False,'reused':False,'account_resume_requested':False}
        save('OBSERVATION_QUEUE_RECEIPT.json',receipt)
        print(json.dumps(receipt))
    else:raise ValueError('Unknown phase')


if __name__=='__main__':main(sys.argv[1])
