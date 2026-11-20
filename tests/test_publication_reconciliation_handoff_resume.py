"""No real PID access: explicit resume of a frozen, stopped handoff only."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

import psutil
import pytest

from test_publication_reconciliation_handoff import setup, unchanged, module, _json

NATIVE_PREFLIGHT=module.preflight_chrome_readability


@pytest.fixture
def resumed(setup,monkeypatch):
    root,store,original,queued,service,calls,faults,evidence=setup
    args=sys.argv;authref={'path':args[args.index('--authorization-path')+1],
                         'sha256':args[args.index('--authorization-sha256')+1]}
    children,observed=module.browser_proof.idle_headless_worker_children(service,args[args.index('--browser-profile')+1],
        args[args.index('--worker-script-sha256')+1])
    with sqlite3.connect(store.path) as db:
        db.row_factory=sqlite3.Row
        original_owner=dict(db.execute('SELECT * FROM browser_control_owners').fetchone())
    failed={'schema':'publication_reconciliation_handoff_run/20261019/v1','phase':'stopped_without_handoff',
        'error_type':'AccessDenied','authorization':authref,'parent_exited':True,'termination_requested':True,
        'handoff_committed':False,'alive_child_ids':[],'gone_child_ids':sorted(c.pid for c in children),
        'original_owner':original_owner,'original_command_id':original['command_id'],
        'original_unknown_preserved':True,'submission_lock_preserved':True,
        'browser_writer_fenced':True,'scheduler_writer_fenced':True,'observed_children':observed,
        'expected_snapshot_sha256':hashlib.sha256(_json(original).encode()).hexdigest(),
        'worker_source':module.browser_proof.worker_source_evidence(args[args.index('--worker-source')+1],args[args.index('--worker-script-sha256')+1])}
    path=root/'FAILED.json';path.write_text(_json(failed),encoding='utf8');before=path.read_bytes()
    sha=hashlib.sha256(before).hexdigest();monkeypatch.setattr(module,'RESUME_FAILURE_SHA256',sha)
    args.extend(['--resume-failure-evidence',str(path),'--resume-failure-sha256',sha])
    def absent(pid):raise psutil.NoSuchProcess(pid)
    def no_wait(*a,**kw):raise AssertionError('Resume must never wait on or signal a process')
    monkeypatch.setattr(module.psutil,'Process',absent)
    monkeypatch.setattr(module.psutil,'wait_procs',no_wait)
    return setup,path,before


def test_exact_stopped_evidence_resumes_under_dual_fences_without_any_process_action(resumed):
    setup,path,before=resumed
    root,store,original,queued,service,calls,_,evidence=setup
    module.main();unchanged(setup)
    assert path.read_bytes()==before and service.terminated==0 and len(calls)==1
    assert store.snapshot('review:A')['owner']['state']=='released'
    result=json.loads(evidence.read_text())
    assert result['handoff_committed'] and result['resumed_previous_exit']
    assert result['termination_requested'] is False


@pytest.mark.parametrize('failure',['pid_present','api_rollback'])
def test_resume_pid_presence_or_transaction_failure_preserves_old_unknown_owner_and_failed_evidence(resumed,monkeypatch,failure):
    setup,path,before=resumed
    root,store,original,queued,service,calls,faults,_=setup
    if failure=='pid_present':
        child=service.descendants[-1]
        def current(pid):
            if pid!=child.pid:raise psutil.NoSuchProcess(pid)
            return child
        monkeypatch.setattr(module.psutil,'Process',current)
    else:faults['api']=True
    with pytest.raises(RuntimeError):module.main()
    unchanged(setup)
    assert path.read_bytes()==before and service.terminated==0
    assert store.snapshot('review:A')['owner']['state']=='active'
    with sqlite3.connect(store.path) as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='adapter_handoff'").fetchone()
    assert len(calls)==int(failure=='api_rollback')


def test_preflight_unreadable_unrelated_chrome_prevents_termination(setup,monkeypatch):
    root,store,original,queued,service,calls,_,evidence=setup
    class Chrome:
        info={'name':'chrome.exe'}
        def cmdline(self):raise psutil.AccessDenied(pid=22256)
    monkeypatch.setattr(module.psutil,'process_iter',lambda attrs:[Chrome()])
    monkeypatch.setattr(module,'preflight_chrome_readability',NATIVE_PREFLIGHT)
    with pytest.raises(psutil.AccessDenied):module.main()
    unchanged(setup)
    assert service.terminated==0 and calls==[]
    assert store.snapshot('review:A')['owner']['state']=='active'
    assert json.loads(evidence.read_text())['phase']=='rejected_before_stop'


def test_reused_child_pid_is_read_only_and_recorded_with_distinct_creation_time(resumed,monkeypatch):
    setup,path,before=resumed
    root,store,original,queued,service,calls,_,evidence=setup
    child=service.descendants[-1]
    class Reused:
        def create_time(self):return child.started+100
        def terminate(self):raise AssertionError('Never signal a reused process')
    def current(pid):
        if pid!=child.pid:raise psutil.NoSuchProcess(pid)
        return Reused()
    monkeypatch.setattr(module.psutil,'Process',current)
    module.main();unchanged(setup)
    assert path.read_bytes()==before and service.terminated==0
    result=json.loads(evidence.read_text())
    checks=result['pid_identity_checks']
    assert [c for c in checks if c['status']=='pid_reused']==[{'pid':child.pid,
        'expected_create_time':child.started,'current_create_time':child.started+100,'status':'pid_reused'}]
    retirement=json.loads((root/'handoff.RETIREMENT.json').read_text())
    assert retirement['pid_identity_checks']==checks


def test_unreadable_original_identity_stops_without_signal_or_owner_release(resumed,monkeypatch):
    setup,path,before=resumed
    root,store,original,queued,service,calls,_,evidence=setup
    def denied(pid):raise psutil.AccessDenied(pid)
    monkeypatch.setattr(module.psutil,'Process',denied)
    with pytest.raises(psutil.AccessDenied):module.main()
    unchanged(setup)
    assert path.read_bytes()==before and service.terminated==0 and calls==[]
    assert store.snapshot('review:A')['owner']['state']=='active'
