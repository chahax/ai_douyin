"""Collection job lifecycle and checkpoint coordination."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from ..source_policy import (
    SourcePolicy,
    SourcePolicyDecision,
    SourcePolicyGate,
    SourceRequest,
)
from .checkpoint import CheckpointStore, CollectionCheckpoint
from .rate_limiter import PageBudget


class CollectionJobStatus(str, Enum):
    QUEUED = "queued"
    POLICY_CHECKED = "policy_checked"
    RUNNING = "running"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    HUMAN_REQUIRED = "human_required"
    PARSER_BROKEN = "parser_broken"
    PARTIAL = "partial"
    FAILED = "failed"


_ALLOWED_TRANSITIONS: dict[CollectionJobStatus, frozenset[CollectionJobStatus]] = {
    CollectionJobStatus.QUEUED: frozenset(
        {CollectionJobStatus.POLICY_CHECKED, CollectionJobStatus.BLOCKED}
    ),
    CollectionJobStatus.POLICY_CHECKED: frozenset(
        {CollectionJobStatus.RUNNING, CollectionJobStatus.BLOCKED}
    ),
    CollectionJobStatus.RUNNING: frozenset(
        {
            CollectionJobStatus.COMPLETED,
            CollectionJobStatus.HUMAN_REQUIRED,
            CollectionJobStatus.PARSER_BROKEN,
            CollectionJobStatus.PARTIAL,
            CollectionJobStatus.FAILED,
            CollectionJobStatus.BLOCKED,
        }
    ),
}


@dataclass(slots=True)
class CollectionJob:
    job_id: str
    request: SourceRequest
    status: CollectionJobStatus = CollectionJobStatus.QUEUED
    policy_id: str | None = None
    cursor: dict[str, Any] = field(default_factory=dict)
    pages_processed: int = 0
    items_collected: int = 0
    stop_reason: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def transition(self, target: CollectionJobStatus, reason: str | None = None) -> None:
        allowed = _ALLOWED_TRANSITIONS.get(self.status, frozenset())
        if target not in allowed:
            raise ValueError(f"invalid collection job transition: {self.status.value} -> {target.value}")
        self.status = target
        self.stop_reason = reason
        self.updated_at = datetime.now(timezone.utc)

    def record_page(self, *, cursor: dict[str, Any], item_count: int) -> None:
        if self.status != CollectionJobStatus.RUNNING:
            raise ValueError("pages can only be recorded while a job is running")
        if item_count < 0:
            raise ValueError("item_count cannot be negative")
        self.cursor = dict(cursor)
        self.pages_processed += 1
        self.items_collected += item_count
        self.updated_at = datetime.now(timezone.utc)


class CollectionJobManager:
    """Small orchestration layer shared by all future collection providers."""

    def __init__(
        self,
        *,
        gate: SourcePolicyGate | None = None,
        checkpoint_store: CheckpointStore | None = None,
    ):
        self.gate = gate or SourcePolicyGate()
        self.checkpoint_store = checkpoint_store

    def authorize(
        self,
        job: CollectionJob,
        policy: SourcePolicy,
        *,
        web_crawler_enabled: bool = False,
    ) -> SourcePolicyDecision:
        if job.status != CollectionJobStatus.QUEUED:
            raise ValueError("only queued jobs can be authorized")
        decision = self.gate.evaluate(
            policy,
            job.request,
            web_crawler_enabled=web_crawler_enabled,
        )
        job.policy_id = policy.policy_id
        if decision.allowed:
            job.transition(CollectionJobStatus.POLICY_CHECKED)
        else:
            job.transition(CollectionJobStatus.BLOCKED, f"{decision.code}: {decision.reason}")
        self._save(job)
        return decision

    def start(self, job: CollectionJob) -> None:
        job.transition(CollectionJobStatus.RUNNING)
        self._save(job)

    def record_page(
        self,
        job: CollectionJob,
        *,
        cursor: dict[str, Any],
        item_count: int,
        budget: PageBudget | None = None,
    ) -> None:
        if job.status != CollectionJobStatus.RUNNING:
            raise ValueError("pages can only be recorded while a job is running")
        if budget is not None:
            budget.reserve_page()
        job.record_page(cursor=cursor, item_count=item_count)
        self._save(job)

    def finish(
        self,
        job: CollectionJob,
        status: CollectionJobStatus = CollectionJobStatus.COMPLETED,
        *,
        reason: str | None = None,
    ) -> None:
        if status not in {
            CollectionJobStatus.COMPLETED,
            CollectionJobStatus.HUMAN_REQUIRED,
            CollectionJobStatus.PARSER_BROKEN,
            CollectionJobStatus.PARTIAL,
            CollectionJobStatus.FAILED,
            CollectionJobStatus.BLOCKED,
        }:
            raise ValueError("finish requires a terminal or stopped status")
        if status != CollectionJobStatus.COMPLETED and not reason:
            raise ValueError("non-completed jobs require a stop reason")
        job.transition(status, reason)
        self._save(job)

    def restore(self, job: CollectionJob) -> bool:
        if self.checkpoint_store is None:
            return False
        checkpoint = self.checkpoint_store.load(job.job_id)
        if checkpoint is None:
            return False
        try:
            status = CollectionJobStatus(checkpoint.status)
        except ValueError as exc:
            raise ValueError(f"unknown checkpoint status: {checkpoint.status}") from exc
        # A resumable checkpoint is operational state, not authorization.  Force
        # non-terminal work through SourcePolicyGate again in case scope expired
        # or was suspended while the worker was down.
        if status in {CollectionJobStatus.POLICY_CHECKED, CollectionJobStatus.RUNNING}:
            job.status = CollectionJobStatus.QUEUED
            job.policy_id = None
            job.stop_reason = "resume_requires_policy_recheck"
        else:
            job.status = status
            job.stop_reason = checkpoint.stop_reason
        job.cursor = dict(checkpoint.cursor)
        job.pages_processed = checkpoint.pages_processed
        job.items_collected = checkpoint.items_collected
        job.updated_at = checkpoint.updated_at
        return True

    def clear_checkpoint(self, job: CollectionJob) -> None:
        if self.checkpoint_store is not None:
            self.checkpoint_store.clear(job.job_id)

    def _save(self, job: CollectionJob) -> None:
        if self.checkpoint_store is None:
            return
        self.checkpoint_store.save(
            CollectionCheckpoint(
                job_id=job.job_id,
                status=job.status.value,
                cursor=dict(job.cursor),
                pages_processed=job.pages_processed,
                items_collected=job.items_collected,
                stop_reason=job.stop_reason,
                updated_at=job.updated_at,
            )
        )
