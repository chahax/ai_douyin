import importlib.util
import sqlite3
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace as NS

import pytest


@pytest.fixture
def prepared(tmp_path,monkeypatch):
    from src.operations_accounts import runtime
    spec=importlib.util.spec_from_file_location('latency_backend',Path(__file__).parents[1]/'src/scheduler/account_refresh.py')
    ar=importlib.util.module_from_spec(spec);ar.__package__='src.scheduler';spec.loader.exec_module(ar)
    path=tmp_path/'feedback.db'
    ar.pause_account('A','alpha','QA original pause',path=path)
    calls=[]
    def probe(key,**kwargs):
        calls.append(key)
        return NS(healthy=True,status='active',expected=NS(account_uuid='A',account_key='alpha'))
    monkeypatch.setattr(runtime,'AccountRuntimeService',lambda:NS(probe_recovery=probe))
    return ar,path,calls


def test_fast_lane_needs_explicit_persisted_request_and_returns_exact_receipt(prepared):
    ar,path,calls=prepared
    ar.request_account_recovery('A','alpha',path=path)
    ar.recover_requested_accounts(path=path,requested_only=True)
    assert calls==[]  # Generic/startup requests remain on the normal scan.
    ar.pause_account('A','alpha','new user pause',path=path)
    accepted=ar.complete_account_handling('A','alpha',handled_by='QA user',path=path)
    assert accepted['request_id']==ar.snapshot(path)['handling_requests'][0]['request_id']
    assert accepted['requested_at']>0
    assert ar.handling_poll_seconds(path=path)==2
    ar.recover_requested_accounts(path=path,requested_only=True)
    ar.recover_requested_accounts(path=path,requested_only=True)
    assert calls==['alpha']
    current=ar.snapshot(path)
    assert current['controls'][0]['state']=='active' and current['handling_requests'][0]['status']=='completed'
    assert not current['runs'] and not current['playback_runs'] and not current['smart_runs']
    assert ar.handling_poll_seconds(path=path)==15


def test_busy_normal_scan_and_fast_lane_cannot_duplicate_original_probe(prepared,monkeypatch):
    from src.operations_accounts import runtime
    ar,path,calls=prepared
    accepted=ar.complete_account_handling('A','alpha',handled_by='QA user',path=path)
    started=threading.Event();release=threading.Event()
    def probe(key,**kwargs):
        calls.append(key);started.set()
        assert release.wait(5)
        return NS(healthy=True,status='active',expected=NS(account_uuid='A',account_key='alpha'))
    monkeypatch.setattr(runtime,'AccountRuntimeService',lambda:NS(probe_recovery=probe))
    worker=threading.Thread(target=lambda:ar.recover_requested_accounts(path=path,requested_only=True))
    worker.start()
    try:
        assert started.wait(4)
        ar.recover_requested_accounts(path=path)
        ar.recover_requested_accounts(path=path,requested_only=True)
        assert calls==['alpha']
        assert ar.snapshot(path)['handling_requests'][0]['request_id']==accepted['request_id']
    finally:release.set();worker.join(5)
    assert not worker.is_alive()


def test_actual_two_second_scheduler_consumes_one_existing_request(prepared):
    from apscheduler.schedulers.background import BackgroundScheduler
    ar,path,calls=prepared
    scheduler=BackgroundScheduler()
    scheduler.add_job(lambda:ar.recover_requested_accounts(path=path,requested_only=True),'interval',seconds=2,max_instances=1,coalesce=True)
    scheduler.start()
    try:
        began=time.monotonic()
        accepted=ar.complete_account_handling('A','alpha',handled_by='QA user',path=path)
        deadline=began+5
        while time.monotonic()<deadline:
            if ar.snapshot(path)['handling_requests'][0]['status']=='completed':break
            time.sleep(.05)
        elapsed=time.monotonic()-began
        assert ar.snapshot(path)['handling_requests'][0]['status']=='completed'
        assert elapsed<4.5 and calls==['alpha']
        assert len(ar.snapshot(path)['handling_requests'])==1
    finally:scheduler.shutdown(wait=True)


@pytest.mark.parametrize('status,phrase', [('requested','已受理'),('probing','正在核验'),('completed','已通过'),('failed','未放行'),('invalidated','未放行')])
def test_elapsed_feedback_distinguishes_acceptance_from_identity_success(status,phrase):
    from src.web.account_handling_feedback import feedback
    row=dict(request_id='original',account_uuid='A',account_key='alpha',status=status,requested_at=100,finished_at=142 if status in ('completed','failed','invalidated') else None)
    current=feedback({'handling_requests':[row]},'A','alpha',now=165)
    assert phrase in current['message']
    assert current['elapsed_seconds']==(42 if row['finished_at'] else 65)
    if status!='completed':assert '已通过' not in current['message']
    assert feedback({'handling_requests':[row]},'B','beta',now=165) is None


def test_reading_poll_cadence_does_not_create_database(prepared,tmp_path):
    ar,_,_=prepared;missing=tmp_path/'absent.db'
    assert ar.handling_poll_seconds(path=missing)==15 and not missing.exists()


@pytest.mark.parametrize('legacy_receipt',[False,True])
def test_real_button_immediately_records_receipt_and_disables_repeat(prepared,monkeypatch,legacy_receipt):
    from streamlit.testing.v1 import AppTest
    from src.web import account_exception_notice as notice
    from src.web.components import auth
    from src.scheduler import account_refresh as actual
    ar,path,calls=prepared
    monkeypatch.setattr(auth,'get_current_user',lambda:'QA user')
    monkeypatch.setattr(auth,'get_current_role',lambda:'admin')
    monkeypatch.setattr(auth,'has_permission',lambda *args:True)
    monkeypatch.setattr(actual,'snapshot',lambda:ar.snapshot(path))
    monkeypatch.setattr(actual,'DB',path)
    def complete(*args,**kwargs):
        result=ar.complete_account_handling(*args,**kwargs,path=path)
        if legacy_receipt:
            result.pop('request_id',None);result.pop('requested_at',None)
        return result
    monkeypatch.setattr(actual,'complete_account_handling',complete)
    monkeypatch.setattr(notice,'_read_manual_window_job',lambda *args:(None,True))
    app=AppTest.from_string("from src.web.account_exception_notice import render_account_handling_completion\nfrom src.scheduler.account_refresh import snapshot\nrender_account_handling_completion('A','alpha',key='finish',data=snapshot())").run(timeout=30)
    app.button(key='finish').click().run()
    assert not app.exception and app.button(key='finish').disabled
    request=ar.snapshot(path)['handling_requests'][0]
    assert app.session_state['handling_receipt:A']==request['request_id']
    assert app.session_state['handling_fast_poll'] is True
    assert any('完成请求已受理' in item.value for item in app.caption)
    assert calls==[]
    app.run();assert len(ar.snapshot(path)['handling_requests'])==1
    ar.recover_requested_accounts(path=path,requested_only=True)
    app.run();assert any('本次原身份核验已通过' in item.value for item in app.caption)
