"""Explicitly authorized idle backend exit: preflight, then evidence-backed retirement.

Never stops processes itself, never clears runtime locks or account issues.
The caller uses the original interactive Windows task between these phases.
"""
from pathlib import Path
import hashlib
import json
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT/'data/development_checkpoints/manual_open_queue_20261105'
UID = 'account:9158f1d29f70eff9819c46b4'
CID = '3cad88d74cae4fa99a71e163114b2d59'


def read(name):
    return json.loads((OUT/name).read_text(encoding='utf-8'))


def save_once(name, value):
    with (OUT/name).open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rows(name, sql, args=()):
    with sqlite3.connect((ROOT/'data'/name).as_uri()+'?mode=ro',uri=True,timeout=5) as db:
        db.row_factory=sqlite3.Row
        return [dict(row) for row in db.execute(sql,args)]


def processes():
    import psutil
    matches, unknown, backends = [], [], []
    root=str(ROOT).casefold()
    entry=str(ROOT/'scripts/run_streamlit_web.py').casefold()
    for process in psutil.process_iter(['pid','name']):
        name=(process.info['name'] or '').lower()
        if name not in {'chrome.exe','msedge.exe','node.exe','python.exe','pythonw.exe'}:
            continue
        try:
            args=process.cmdline()
            browser=name in {'chrome.exe','msedge.exe'} and any(
                arg.startswith('--user-data-dir=') and root in arg.casefold() for arg in args)
            driver=name=='node.exe' and any(root in arg.casefold() and 'playwright' in arg.casefold()
                and 'cli.js' in arg.casefold() for arg in args)
            worker=name in {'python.exe','pythonw.exe'} and any(
                '_bootstrap_started' in arg and 'browser_worker_stage' in arg for arg in args)
            item={'pid':process.pid,'name':name,'create_time':process.create_time()}
            if browser or driver or worker:
                matches.append(item)
            if name in {'python.exe','pythonw.exe'} and any(arg.casefold()==entry for arg in args[1:]):
                backends.append(item)
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
        except psutil.AccessDenied:
            unknown.append({'pid':process.pid,'name':name})
    return {'at':time.time(),'project_engines':matches,'unqueryable_targets':unknown,'canonical_backends':backends}


def validate_frozen():
    authorization=read('ACTUAL_EXIT_AUTHORIZATION.json')
    assert authorization['user_statement']=='允许受控重启并继续'
    assert authorization['decision_source']=='explicit_user_statement'
    assert authorization['owner_generation']==24 and authorization['account_uuid']==UID
    assert authorization['proposal_sha256']==sha(OUT/'ACTUAL_BACKEND_EXIT_PROPOSAL.json')
    assert authorization['candidate_sha256']==sha(OUT/'STARTUP_CANDIDATE_MANIFEST.json')
    manifest=read('STARTUP_CANDIDATE_MANIFEST.json')
    for item in manifest['files']+manifest['test_reports']+[manifest['driver_binary']]:
        assert sha(ROOT/item['file'])==item['sha256'], 'Frozen candidate changed: '+item['file']
    return authorization


def idle_state():
    from src.operations_accounts.browser_control import BrowserControlStore
    from src.operations_accounts.publication_autonomous_reconciliation import unresolved
    controls=rows('account_refresh.db','SELECT account_key,state,revision FROM account_controls')
    assert sorted((c['account_key'],c['state'],c['revision']) for c in controls)==[
        ('account01','paused',73),('novel_account_02','paused',41)]
    for kind in ('refresh','smart','playback'):
        assert not rows('account_refresh.db',f"SELECT run_id FROM {kind}_runs WHERE status IN ('running','outcome_unknown')")
    assert not rows('douyin.db',"SELECT account_uuid FROM account_runtime_state WHERE lock_owner IS NOT NULL AND lock_owner!=''")
    assert not rows('wisdom_ai.db',"SELECT execution_uuid FROM task_executions WHERE status IN ('pending','running')")
    store=BrowserControlStore(ROOT/'data/account_browser_control.db')
    original=store.get(CID)
    assert original['state']=='failed' and original['error_code']=='operator_cancelled_unknown_manual'
    assert original['result']['original_outcome_known'] is False
    assert original['result']['before_snapshot_sha256']==read('CONTINUATION_PLAN.json')['expected_original_snapshot_sha256']
    with store._db() as db:
        assert not unresolved(store,db,UID,('queued','running','paused','waiting_human','outcome_unknown'))
        owner=dict(db.execute('SELECT * FROM browser_control_owners WHERE account_id=?',(UID,)).fetchone())
    expected=read('CONTINUATION_PLAN.json')['original_manual']
    for key in ('owner_id','generation','binding_version'):
        assert owner[key]==expected[key]
    assert owner['state']=='active'
    protected=rows('account_browser_control.db',
        'SELECT command_id,state,owner_id,generation,request_sha,updated_at FROM browser_control_commands WHERE command_id=?',
        ('10b2bcfbba84499b93ad1a9891ec0226',))
    return store,owner,controls,protected


def main(phase):
    import psutil
    validate_frozen()
    store,owner,controls,protected=idle_state()
    scan=processes()
    assert not scan['project_engines'] and not scan['unqueryable_targets'], 'Browser process absence not proven'
    if phase=='before':
        backend=psutil.Process(5236)
        assert backend.create_time()==1793839149.175543 and not backend.children(recursive=True)
        assert str(ROOT/'scripts/run_streamlit_web.py') in backend.cmdline()
        allowed={backend.pid}
        parent=backend.parent()
        if parent and str(ROOT/'scripts/run_streamlit_web.py') in parent.cmdline():
            allowed.add(parent.pid)
        assert scan['canonical_backends'] and {p['pid'] for p in scan['canonical_backends']}<=allowed
        save_once('ACTUAL_EXIT_BEFORE_RUN.json',{'at':time.time(),'backend_pid':5236,
            'backend_create_time':backend.create_time(),'scan':scan,'owner':owner,'controls':controls,
            'protected_account01_manual':protected,'candidate_sha256':sha(OUT/'STARTUP_CANDIDATE_MANIFEST.json')})
        print(json.dumps({'ready_to_stop_original_idle_task':True,'backend_pid':5236}))
    elif phase=='after':
        before=read('ACTUAL_EXIT_BEFORE_RUN.json')
        assert time.time()-before['at']<=180, 'Exit observation window expired'
        assert not psutil.pid_exists(5236) and not scan['canonical_backends'], 'Original backend exit not proven'
        assert owner==before['owner'] and controls==before['controls'] and protected==before['protected_account01_manual']
        evidence={'source':'explicit_user_authorized_actual_idle_backend_exit','host_stopped':True,
            'worker_stopped':True,'original_backend_pid':5236,'original_backend_create_time':before['backend_create_time'],
            'before_evidence_sha256':sha(OUT/'ACTUAL_EXIT_BEFORE_RUN.json'),'after_process_scan':scan,
            'authorization_sha256':sha(OUT/'ACTUAL_EXIT_AUTHORIZATION.json'),
            'original_unknown_result_reclassified':False}
        from src.operations_accounts.browser_host_retirement import retire
        assert retire(store,UID,owner['owner_id'],owner['generation'],evidence=evidence), 'Idle retirement guard rejected'
        saved=rows('account_browser_control.db','SELECT owner_id,generation,state FROM browser_control_owners WHERE account_id=?',(UID,))
        assert saved[0]['state']=='released'
        save_once('ACTUAL_EXIT_RETIREMENT_RECEIPT.json',{'at':time.time(),'evidence':evidence,'owner':saved,
            'controls':controls,'protected_account01_manual':protected,'new_manual_queued':False})
        print(json.dumps({'retirement_recorded':True,'owner_generation':24,'account_resume':False}))
    else:
        raise ValueError('Unknown phase')


if __name__=='__main__':
    main(sys.argv[1])
