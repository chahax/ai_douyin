from datetime import datetime, timezone

import pytest

from src.trend_intelligence.collection import (
    CollectionCheckpoint,
    CollectionJob,
    CollectionJobManager,
    CollectionJobStatus,
    CollectionRateLimiter,
    FileCheckpointStore,
    PageBudget,
    PageBudgetExceeded,
)
from src.trend_intelligence.source_policy import (
    SourceProvider,
    SourceRequest,
    approved_manual_import_policy,
)


def _manual_request() -> SourceRequest:
    return SourceRequest(
        provider=SourceProvider.MANUAL_IMPORT,
        purposes=frozenset({"trend_analysis"}),
        requested_fields=frozenset({"title"}),
        requested_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
    )


def test_file_checkpoint_roundtrip_and_clear(tmp_path) -> None:
    store = FileCheckpointStore(tmp_path)
    checkpoint = CollectionCheckpoint(
        job_id="legal-import-001",
        status="running",
        cursor={"row": 12},
        pages_processed=1,
        items_collected=12,
    )
    target = store.save(checkpoint)
    assert target.exists()
    assert store.load(checkpoint.job_id) == checkpoint
    store.clear(checkpoint.job_id)
    assert store.load(checkpoint.job_id) is None


def test_checkpoint_rejects_path_traversal(tmp_path) -> None:
    store = FileCheckpointStore(tmp_path)
    with pytest.raises(ValueError, match="safe filename"):
        store.load("../outside")


def test_checkpoint_rejects_sensitive_session_data() -> None:
    with pytest.raises(ValueError, match="sensitive data"):
        CollectionCheckpoint(
            job_id="unsafe-checkpoint",
            status="running",
            cursor={"page": 1, "access_token": "must-not-be-written"},
        )


def test_collection_job_lifecycle_is_checkpointed(tmp_path) -> None:
    store = FileCheckpointStore(tmp_path)
    manager = CollectionJobManager(checkpoint_store=store)
    policy = approved_manual_import_policy(allowed_fields={"title"})
    job = CollectionJob(job_id="legal-import-002", request=_manual_request())

    decision = manager.authorize(job, policy)
    assert decision.allowed is True
    assert job.status == CollectionJobStatus.POLICY_CHECKED

    manager.start(job)
    budget = PageBudget(max_pages_per_run=1, daily_page_cap=1)
    manager.record_page(job, cursor={"row": 20}, item_count=20, budget=budget)
    manager.finish(job)

    restored = CollectionJob(job_id=job.job_id, request=_manual_request())
    assert manager.restore(restored) is True
    assert restored.status == CollectionJobStatus.COMPLETED
    assert restored.cursor == {"row": 20}
    assert restored.items_collected == 20


def test_denied_job_is_blocked_before_running(tmp_path) -> None:
    store = FileCheckpointStore(tmp_path)
    manager = CollectionJobManager(checkpoint_store=store)
    policy = approved_manual_import_policy(allowed_fields=set())
    job = CollectionJob(job_id="legal-import-003", request=_manual_request())

    decision = manager.authorize(job, policy)
    assert decision.allowed is False
    assert decision.code == "fields_not_allowed"
    assert job.status == CollectionJobStatus.BLOCKED
    with pytest.raises(ValueError, match="invalid collection job transition"):
        manager.start(job)


def test_running_checkpoint_requires_policy_recheck_on_resume(tmp_path) -> None:
    store = FileCheckpointStore(tmp_path)
    manager = CollectionJobManager(checkpoint_store=store)
    policy = approved_manual_import_policy(allowed_fields={"title"})
    job = CollectionJob(job_id="legal-import-resume", request=_manual_request())
    manager.authorize(job, policy)
    manager.start(job)
    manager.record_page(job, cursor={"row": 5}, item_count=5)

    restored = CollectionJob(job_id=job.job_id, request=_manual_request())
    assert manager.restore(restored) is True
    assert restored.status == CollectionJobStatus.QUEUED
    assert restored.stop_reason == "resume_requires_policy_recheck"
    assert restored.cursor == {"row": 5}

    assert manager.authorize(restored, policy).allowed is True
    manager.start(restored)
    assert restored.status == CollectionJobStatus.RUNNING


def test_page_budget_is_a_hard_cap() -> None:
    budget = PageBudget(max_pages_per_run=2, daily_page_cap=10, pages_used_today=8)
    budget.reserve_page()
    budget.reserve_page()
    assert budget.remaining_this_run == 0
    assert budget.remaining_today == 0
    with pytest.raises(PageBudgetExceeded, match="per-run"):
        budget.reserve_page()


def test_collection_rate_limiter_reserves_per_source_slots() -> None:
    now = [100.0]
    sleeps: list[float] = []

    def clock() -> float:
        return now[0]

    def sleeper(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    limiter = CollectionRateLimiter(3, clock=clock, sleeper=sleeper)
    assert limiter.acquire("douyin:www.douyin.com") == 0
    assert limiter.seconds_until_ready("douyin:www.douyin.com") == 3
    assert limiter.acquire("douyin:www.douyin.com") == 3
    assert limiter.acquire("licensed:feed-a") == 0
    assert sleeps == [3]
