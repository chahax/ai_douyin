import sqlite3
from types import SimpleNamespace as NS

import pytest


@pytest.fixture
def activation(tmp_path,monkeypatch):
    from apscheduler.schedulers.background import BackgroundScheduler
    from src.scheduler import account_refresh,handling_fast_lane,runner
    from src.web.components import auth
    path=tmp_path/'controls.db'
    account_refresh.pause_account('A','alpha','QA pause',path=path)
    monkeypatch.setattr(account_refresh,'DB',path)
    monkeypatch.setattr(handling_fast_lane,'ACTIVATION_PATH',tmp_path/'ACTIVATION.json')
    monkeypatch.setattr(auth,'get_current_user',lambda:'QA admin')
    monkeypatch.setattr(auth,'get_current_role',lambda:'admin')
    monkeypatch.setattr(auth,'has_permission',lambda *args:True)
    scheduler=BackgroundScheduler();scheduler.start()
    monkeypatch.setattr(runner,'scheduler_instance',NS(_scheduler=scheduler))
    try:yield account_refresh,handling_fast_lane,scheduler
    finally:scheduler.shutdown(wait=True)


def test_actual_existing_scheduler_accepts_one_job_without_restart_or_business(activation):
    ar,lane,scheduler=activation
    before=ar.snapshot(ar.DB)
    first=lane.install_from_web();second=lane.install_from_web()
    assert first['reused'] is False and second['reused'] is True
    assert len(scheduler.get_jobs())==1
    job=scheduler.get_job(lane.JOB_ID)
    assert job.trigger.interval.total_seconds()==2 and job.max_instances==1
    assert ar.snapshot(ar.DB)==before
    assert lane.ACTIVATION_PATH.exists() and first['backend_restarted'] is False


def test_unknown_existing_job_is_preserved_and_not_replaced(activation):
    _,lane,scheduler=activation
    original=scheduler.add_job(lambda:None,'interval',hours=1,id=lane.JOB_ID)
    with pytest.raises(RuntimeError,match='different'):lane.install_from_web()
    assert scheduler.get_job(lane.JOB_ID).func is original.func
    assert not lane.ACTIVATION_PATH.exists()


def test_legacy_processor_uses_same_claims_and_never_normal_business_scan(activation,monkeypatch):
    from src.operations_accounts import runtime
    ar,lane,_=activation;calls=[]
    ar.complete_account_handling('A','alpha',handled_by='QA user',path=ar.DB)
    def normal(*,path):raise AssertionError('must not run the general scan')
    monkeypatch.setattr(ar,'recover_requested_accounts',normal)
    monkeypatch.setattr(runtime,'AccountRuntimeService',lambda:NS(probe_recovery=lambda *args,**kwargs:
        calls.append('original-identity') or NS(healthy=True,status='active',expected=NS(account_uuid='A',account_key='alpha'))))
    lane.verify_original_claims(ar)
    lane.run_registered_requests();lane.run_registered_requests()
    assert calls==['original-identity']
    assert ar.snapshot(ar.DB)['handling_requests'][0]['status']=='completed'
    assert not ar.snapshot(ar.DB)['runs'] and not ar.snapshot(ar.DB)['playback_runs']


def test_editor_cannot_register_job_or_write_activation(activation,monkeypatch):
    from src.web.components import auth
    _,lane,scheduler=activation
    monkeypatch.setattr(auth,'has_permission',lambda *args:False)
    with pytest.raises(PermissionError):lane.install_from_web()
    assert not scheduler.get_jobs() and not lane.ACTIVATION_PATH.exists()


def test_changed_loaded_claim_is_rejected_before_job_registration(activation,monkeypatch):
    ar,lane,scheduler=activation
    monkeypatch.setattr(ar,'_claim_recovery',lambda *args,**kwargs:None)
    with pytest.raises(RuntimeError,match='differs'):lane.install_from_web()
    assert not scheduler.get_jobs() and not lane.ACTIVATION_PATH.exists()


def test_real_activation_button_registers_once_and_read_only_refresh_does_not_write(activation):
    from streamlit.testing.v1 import AppTest
    ar,lane,scheduler=activation
    before=ar.snapshot(ar.DB)
    app=AppTest.from_string('from src.web.handling_feedback_upgrade import render_feedback_upgrade\nrender_feedback_upgrade()').run(timeout=30)
    assert not app.exception and not scheduler.get_jobs() and not lane.ACTIVATION_PATH.exists()
    app.button(key='activate_handling_feedback').click().run()
    assert not app.exception and len(scheduler.get_jobs())==1
    modified=lane.ACTIVATION_PATH.stat().st_mtime_ns
    app.run()
    assert lane.ACTIVATION_PATH.stat().st_mtime_ns==modified
    assert ar.snapshot(ar.DB)==before
