"""Real incident/job SQLite and scheduler dispatch; no real platform windows."""
import importlib.util
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def system(tmp_path, monkeypatch):
    backend = load('auto_window_backend', 'src/scheduler/account_refresh.py')
    jobs = load('auto_window_jobs', 'src/operations_accounts/manual_window_jobs.py')
    scanner = load('auto_window_scanner', 'src/scheduler/account_manual_windows.py')
    monkeypatch.setitem(sys.modules, 'src.scheduler', SimpleNamespace(account_refresh=backend))
    monkeypatch.setitem(sys.modules, 'src.operations_accounts', SimpleNamespace(manual_window_jobs=jobs))
    db, windows = tmp_path / 'account_refresh.db', tmp_path / 'account_manual_windows.db'
    def pause():
        with backend.connect(db) as connection:
            backend._pause(connection,'A','a','challenge','human_required',time.time())
    pause()
    state, calls = SimpleNamespace(lock='', profile_status='active', fail=False), []
    runtime = SimpleNamespace(profiles=SimpleNamespace(get=lambda key:SimpleNamespace(
        account_uuid='A', account_key=key, status=state.profile_status)),
        bindings=SimpleNamespace(get_runtime_state=lambda uuid:SimpleNamespace(lock_owner=state.lock)))
    def helper(uuid, key, **kwargs):
        calls.append((uuid,key))
        kwargs['on_progress']('window_open_waiting_close')
        if state.fail:
            raise TimeoutError('local fixture')
        return SimpleNamespace(closed=True)
    monkeypatch.setitem(sys.modules, 'src.operations_accounts.manual_handling',
        SimpleNamespace(open_bound_manual_handling_window=helper))
    def scan():
        return scanner.dispatch_human_windows(path=db,jobs_path=windows,runtime=runtime)
    def settle():
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            job=jobs.get_manual_window_job('A','a',path=windows)
            if job and job['state'] in ('closed','failed','outcome_unknown'):
                return job
            time.sleep(.01)
        pytest.fail('window fixture did not finish')
    yield SimpleNamespace(backend=backend,jobs=jobs,scanner=scanner,db=db,windows=windows,
        runtime=runtime,state=state,calls=calls,scan=scan,settle=settle,pause=pause)
    with jobs._registry_lock:
        pending=list(jobs._registry.values())
    for thread in pending:
        thread.join(5)
        assert not thread.is_alive()


def test_one_auto_window_for_open_incident_survives_polling_and_reload(system):
    s=system
    first=s.scan()[0]
    assert s.settle()['state']=='closed'
    assert s.calls==[('A','a')]
    assert all(s.scan()==[] for _ in range(3))
    reloaded=load('restarted_window_jobs','src/operations_accounts/manual_window_jobs.py')
    saved=reloaded.get_incident_window_job(1,'A','a',path=s.windows)
    assert saved['job_id']==first['job_id'] and saved['state']=='closed'
    assert s.backend.snapshot(s.db)['controls'][0]['state']=='paused'
    assert s.backend.snapshot(s.db)['issues'][0]['status']=='open'
    # Once mapped, a repeat scan needs no write lock in the job database.
    with sqlite3.connect(s.windows) as db:
        db.execute('BEGIN IMMEDIATE')
        assert s.scan()==[]


def test_failed_auto_attempt_is_not_retried_but_manual_retry_is_allowed(system):
    s=system
    s.state.fail=True
    s.scan()
    assert s.settle()['state']=='failed'
    assert s.scan()==[] and len(s.calls)==1
    s.state.fail=False
    s.jobs.start_manual_window_job('A','a','admin',runtime=s.runtime,path=s.windows)
    assert s.settle()['state']=='closed' and len(s.calls)==2
    assert s.scan()==[]


def test_later_new_incident_gets_one_new_window(system):
    s=system
    first=s.scan()[0]
    s.settle()
    s.pause()
    second=s.scan()[0]
    s.settle()
    assert second['job_id']!=first['job_id'] and len(s.calls)==2
    assert s.scan()==[]


def test_human_already_opened_and_closed_current_incident_window_is_adopted(system):
    s=system
    manual=s.jobs.start_manual_window_job('A','a','admin',runtime=s.runtime,path=s.windows)
    s.settle()
    adopted=s.scan()[0]
    assert adopted['job_id']==manual['job_id'] and adopted['reused']
    assert len(s.calls)==1 and s.scan()==[]


def test_concurrent_scans_share_atomic_incident_and_job_claim(system):
    s=system
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda _:s.scan(),range(4)))
    s.settle()
    assert len(s.calls)==1
    assert len({j['job_id'] for result in results for j in result})==1


@pytest.mark.parametrize('change',['closed','recovering','backend_error','unknown_run','locked','disabled'])
def test_ineligible_or_unknown_account_never_starts_window(system,change):
    s=system
    with s.backend.connect(s.db) as db:
        if change=='closed':
            db.execute("UPDATE account_issues SET status='closed'")
        elif change=='recovering':
            db.execute("UPDATE account_controls SET state='recovery_requested'")
        elif change=='backend_error':
            db.execute("UPDATE account_controls SET error_code='scheduler_database_busy'")
        elif change=='unknown_run':
            db.execute("INSERT INTO playback_accounts(account_uuid,account_key,next_due,lease_until,run_id) VALUES('A','a',0,0,'original-unknown')")
    if change=='locked': s.state.lock='original-owner-even-if-expired'
    if change=='disabled': s.state.profile_status='disabled'
    assert s.scan()==[] and not s.calls and not s.windows.exists()


def test_worker_rechecks_incident_after_persistent_registration(system):
    s=system
    job=s.jobs.start_manual_window_job('A','a','system:human_required:1',runtime=s.runtime,path=s.windows,
        incident_id=1,incident_created_at=1,before_open=lambda:False)
    done=s.settle()
    assert done['job_id']==job['job_id'] and done['state']=='failed'
    assert done['error_code']=='incident_no_longer_actionable' and not s.calls
    assert s.scan()==[]


def test_unknown_original_window_is_retained_without_relaunch(system):
    s=system
    original=s.scan()[0]
    s.settle()
    with s.jobs._connection(s.windows,create=True) as db:
        db.execute("UPDATE manual_window_jobs SET state='outcome_unknown',phase='outcome_unknown'")
    assert s.scan()==[] and len(s.calls)==1
    retained=s.jobs.get_incident_window_job(1,'A','a',path=s.windows)
    assert retained['job_id']==original['job_id'] and retained['state']=='outcome_unknown'


def test_unconfirmed_verification_surface_opens_original_window_once(system):
    s=system
    with s.backend.connect(s.db) as db:
        db.execute("UPDATE account_controls SET error_code='verification_ui_unconfirmed'")
        db.execute("UPDATE account_issues SET error_code='verification_ui_unconfirmed'")
    job=s.scan()[0]
    assert s.settle()['job_id']==job['job_id']
    assert s.scan()==[] and len(s.calls)==1
