from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.agent.registry import _fanqie_batch_run
from src.platform_adapter import fanqie_batch
from src.scheduler.models import (
    FanqieBatchBook,
    FanqieBatchStatus,
    ScheduledTask,
    TaskExecution,
)
from src.shared.database import Base


def _sessions(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'queue.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(fanqie_batch, "SessionLocal", sessions)
    return sessions


def test_enqueue_keeps_book_task_execution_one_to_one(tmp_path, monkeypatch):
    sessions = _sessions(tmp_path, monkeypatch)
    with sessions() as session:
        session.add_all([
            FanqieBatchBook(book_name="甲书", chapters=3, interval_s=7),
            FanqieBatchBook(book_name="乙书", chapters=5, interval_s=9),
        ])
        session.commit()

    result = fanqie_batch.batch_enqueue_pending()

    assert result["total"] == 2
    assert result["queued"] == 2
    assert result["skipped"] == 0
    assert len(result["mappings"]) == 2
    with sessions() as session:
        tasks = session.query(ScheduledTask).all()
        executions = session.query(TaskExecution).all()
        assert len(tasks) == 2
        assert len(executions) == 2
        assert {row.task_id for row in executions} == set(result["task_ids"])
        for mapping in result["mappings"]:
            task = session.query(ScheduledTask).filter_by(id=mapping["task_id"]).one()
            execution = session.query(TaskExecution).filter_by(
                execution_uuid=mapping["execution_uuid"]
            ).one()
            assert task.max_retries == 2
            assert task.skill_params["row_id"] == mapping["row_id"]
            assert execution.task_id == task.id
            assert execution.skill_params_snapshot["row_id"] == mapping["row_id"]

    repeated = fanqie_batch.batch_enqueue_pending()
    assert repeated["total"] == 2
    assert repeated["queued"] == 0
    assert repeated["skipped"] == 2
    with sessions() as session:
        assert session.query(ScheduledTask).count() == 2
        assert session.query(TaskExecution).count() == 2


def test_exact_queue_task_runs_only_its_bound_row(monkeypatch):
    calls = []

    def fake_fetch(row_id, headless=True):
        calls.append((row_id, headless))
        return fanqie_batch.BookFetchResult(
            book_name="精确目标",
            success=True,
            chapters_fetched=3,
            duration_ms=25,
        )

    monkeypatch.setattr(fanqie_batch, "_fetch_one", fake_fetch)
    result = _fanqie_batch_run(row_id=17, interval_s=8)

    assert result["success"] is True
    assert result["data"]["total"] == 1
    assert result["data"]["succeeded"] == 1
    assert calls == [(17, True)]


def test_exact_queue_failure_is_visible_to_scheduler_retry(monkeypatch):
    monkeypatch.setattr(
        fanqie_batch,
        "_fetch_one",
        lambda row_id, headless=True: fanqie_batch.BookFetchResult(
            book_name="失败目标",
            success=False,
            error_code="skill_error",
            error_message="temporary browser failure",
            duration_ms=10,
        ),
    )

    result = _fanqie_batch_run(row_id=23)

    assert result["success"] is False
    assert result["error"]["retryable"] is True
    assert result["error"]["details"]["failed"] == 1


def test_failed_fetch_counts_one_attempt_and_done_row_is_idempotent(tmp_path, monkeypatch):
    sessions = _sessions(tmp_path, monkeypatch)
    with sessions() as session:
        failed = FanqieBatchBook(book_name="只计一次", chapters=2)
        done = FanqieBatchBook(
            book_name="已经完成",
            status=FanqieBatchStatus.DONE.value,
            chapters_fetched=2,
        )
        session.add_all([failed, done])
        session.commit()
        failed_id, done_id = failed.id, done.id

    class FailingService:
        def fetch_book(self, **kwargs):
            raise RuntimeError("boom")

    first = fanqie_batch._fetch_one(failed_id, service=FailingService())
    second = fanqie_batch._fetch_one(done_id, service=FailingService())

    assert first.success is False
    assert second.success is True
    assert second.error_code == "skipped"
    with sessions() as session:
        row = session.query(FanqieBatchBook).filter_by(id=failed_id).one()
        assert row.status == FanqieBatchStatus.FAILED.value
        assert row.attempt_count == 1
