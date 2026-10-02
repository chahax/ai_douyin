from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.scheduler.models import ScheduledTask, TaskExecution, TaskStatus, TaskType
from src.scheduler.queue import TaskQueue
from src.shared.database import Base


def _sessions(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'queue.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    seed = factory()
    task = ScheduledTask(
        task_uuid="task-1",
        name="fixture",
        skill_name="fixture",
        task_type=TaskType.QUEUE.value,
        status=TaskStatus.PENDING.value,
        enabled=True,
    )
    seed.add(task)
    seed.commit()
    execution = TaskExecution(
        execution_uuid="execution-1",
        task_id=task.id,
        status=TaskStatus.PENDING.value,
        skill_params_snapshot={},
    )
    seed.add(execution)
    seed.commit()
    seed.close()
    return factory


def test_sqlite_conditional_claim_has_exactly_one_winner(tmp_path):
    factory = _sessions(tmp_path)
    first_session, second_session = factory(), factory()
    first = TaskQueue(first_session, owner_id="worker-a", lease_seconds=60)
    second = TaskQueue(second_session, owner_id="worker-b", lease_seconds=60)

    claimed_by_first = first.claim_next()
    claimed_by_second = second.claim_next()

    assert claimed_by_first is not None
    assert claimed_by_first.status == TaskStatus.RUNNING.value
    assert claimed_by_first.claim_owner == "worker-a"
    assert claimed_by_first.lease_expires_at is not None
    assert claimed_by_second is None
    second_session.expire_all()
    saved = second_session.query(TaskExecution).one()
    assert saved.claim_owner == "worker-a"


def test_heartbeat_requires_owner_and_expired_lease_becomes_unknown(tmp_path):
    factory = _sessions(tmp_path)
    owner_session, other_session = factory(), factory()
    owner = TaskQueue(owner_session, owner_id="worker-a", lease_seconds=60)
    other = TaskQueue(other_session, owner_id="worker-b", lease_seconds=60)
    execution = owner.claim_next()

    previous_expiry = execution.lease_expires_at
    owner.heartbeat(execution)
    assert execution.lease_expires_at >= previous_expiry

    owner_session.query(TaskExecution).filter_by(id=execution.id).update({
        TaskExecution.lease_expires_at: datetime.utcnow() - timedelta(seconds=1),
    })
    owner_session.commit()
    assert other.recover_expired_leases() == 1
    other_session.expire_all()
    recovered = other_session.query(TaskExecution).one()
    assert recovered.status == TaskStatus.OUTCOME_UNKNOWN.value
    assert recovered.next_retry_at is None
    assert "核对" in recovered.error_message
