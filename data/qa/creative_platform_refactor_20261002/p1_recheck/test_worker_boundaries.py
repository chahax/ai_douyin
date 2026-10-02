from pathlib import Path
import time
from datetime import datetime,timedelta
from copy import deepcopy
from src.scheduler import queue as queue_module
from src.scheduler.queue import TaskQueue
from src.scheduler.models import TaskExecution
from src.agent import registry as registry_module
from test_task_queue_claim import _sessions


def test_recovered_execution_discards_late_worker_result(tmp_path,monkeypatch):
    factory=_sessions(tmp_path)
    owner_session,other_session=factory(),factory()
    owner=TaskQueue(owner_session,owner_id='owner',lease_seconds=60)
    other=TaskQueue(other_session,owner_id='recovery',lease_seconds=60)
    execution=owner.claim_next()
    initial_result=deepcopy(execution.result)
    class FakeRegistry:
        def call(self,*args,**kwargs):
            other_session.query(TaskExecution).filter_by(id=execution.id).update({TaskExecution.lease_expires_at:datetime.utcnow()-timedelta(seconds=1)})
            other_session.commit()
            assert other.recover_expired_leases()==1
            other_session.expire_all()
            assert other_session.get(TaskExecution,execution.id).status=='outcome_unknown'
            return {'success':True,'data':'late-fixture-result'}
    monkeypatch.setattr(registry_module,'SkillRegistry',FakeRegistry)
    monkeypatch.setattr(queue_module,'SessionLocal',factory)
    try:
        owner._execute_sync(execution,owner_session)
        other_session.expire_all()
        saved=other_session.get(TaskExecution,execution.id)
        assert saved.status=='outcome_unknown'
        assert saved.result==initial_result
        assert saved.claim_owner is None
    finally:
        owner_session.close();other_session.close();factory.kw['bind'].dispose()


def test_running_skill_renews_lease_past_initial_expiry(tmp_path,monkeypatch):
    factory=_sessions(tmp_path)
    owner_session,observer=factory(),factory()
    owner=TaskQueue(owner_session,owner_id='owner',lease_seconds=2)
    execution=owner.claim_next()
    initial_expiry=execution.lease_expires_at
    class FakeRegistry:
        def call(self,*args,**kwargs):
            deadline=time.monotonic()+5
            while datetime.utcnow()<=initial_expiry+timedelta(seconds=0.25):
                assert time.monotonic()<deadline
                time.sleep(0.04)
            observer.expire_all()
            saved=observer.get(TaskExecution,execution.id)
            assert saved.status=='running'
            assert saved.claim_owner=='owner'
            assert saved.lease_expires_at>initial_expiry
            assert saved.lease_expires_at>datetime.utcnow()
            return {'success':True,'data':'renewed-fixture-result'}
    monkeypatch.setattr(registry_module,'SkillRegistry',FakeRegistry)
    monkeypatch.setattr(queue_module,'SessionLocal',factory)
    try:
        owner._execute_sync(execution,owner_session)
        observer.expire_all()
        saved=observer.get(TaskExecution,execution.id)
        assert saved.status=='completed'
        assert saved.result.get('data')=='renewed-fixture-result'
    finally:
        owner_session.close();observer.close();factory.kw['bind'].dispose()
