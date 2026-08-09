"""
src/novel_promotion/state_machine.py — 推广任务状态机

唯一的状态转换规则来源。所有状态变更必须经由此模块校验。
"""

from dataclasses import dataclass, field
from typing import Optional

from .models import TaskStatus as TS

# Valid transitions: from_status -> set of allowed to_status values
_VALID_TRANSITIONS: dict[str, set[str]] = {
    # Selection / application
    TS.APPLYING:              {TS.UNDER_REVIEW, TS.APPLICATION_FAILED, TS.MANUAL_INTERVENTION, TS.CANCELLED},
    TS.UNDER_REVIEW:          {TS.ACTIVE, TS.REJECTED, TS.EXPIRED, TS.MANUAL_INTERVENTION, TS.CANCELLED},
    TS.ACTIVE:                {TS.SCRIPTING, TS.EXPIRED, TS.MANUAL_INTERVENTION, TS.CANCELLED},
    TS.APPLICATION_FAILED:    {TS.APPLYING, TS.MANUAL_INTERVENTION, TS.CANCELLED},
    # Scripting
    TS.SCRIPTING:             {TS.SCRIPT_REVIEW, TS.MANUAL_INTERVENTION, TS.CANCELLED},
    TS.SCRIPT_REVIEW:         {TS.SCRIPT_APPROVED, TS.SCRIPT_REJECTED, TS.REVISION_REQUIRED, TS.MANUAL_INTERVENTION, TS.CANCELLED},
    TS.SCRIPT_APPROVED:       {TS.VIDEO_QUEUED, TS.MANUAL_INTERVENTION, TS.CANCELLED},
    TS.SCRIPT_REJECTED:       {TS.SCRIPTING, TS.MANUAL_INTERVENTION, TS.CANCELLED},
    TS.REVISION_REQUIRED:     {TS.SCRIPTING, TS.MANUAL_INTERVENTION, TS.CANCELLED},
    # Video generation / QA
    TS.VIDEO_QUEUED:          {TS.GENERATING, TS.CANCELLED},
    TS.GENERATING:            {TS.QUALITY_CHECK, TS.GENERATING, TS.MANUAL_INTERVENTION, TS.CANCELLED},
    TS.QUALITY_CHECK:         {TS.REVIEW_REQUIRED, TS.QUALITY_CHECK, TS.MANUAL_INTERVENTION, TS.CANCELLED},
    # Human review
    TS.REVIEW_REQUIRED:       {TS.APPROVED, TS.REJECTED_REVIEW, TS.REVISION_REQUIRED, TS.MANUAL_INTERVENTION, TS.CANCELLED},
    TS.APPROVED:              {TS.PUBLISH_QUEUED, TS.MANUAL_INTERVENTION, TS.CANCELLED},
    TS.REJECTED_REVIEW:       {TS.VIDEO_QUEUED, TS.MANUAL_INTERVENTION, TS.CANCELLED},
    # Publishing
    TS.PUBLISH_QUEUED:        {TS.PUBLISHING, TS.CANCELLED},
    TS.PUBLISHING:            {TS.PUBLISH_PENDING_SYNC, TS.PUBLISH_FAILED, TS.MANUAL_INTERVENTION, TS.CANCELLED},
    TS.PUBLISH_PENDING_SYNC:  {TS.PUBLISHED, TS.PUBLISHED_UNBOUND, TS.MANUAL_INTERVENTION, TS.CANCELLED},
    TS.PUBLISHED:             {TS.BINDING, TS.MANUAL_INTERVENTION, TS.CANCELLED},
    TS.PUBLISH_FAILED:        {TS.PUBLISH_QUEUED, TS.MANUAL_INTERVENTION, TS.CANCELLED},
    # Binding
    TS.PUBLISHED_UNBOUND:     {TS.BINDING, TS.MANUAL_INTERVENTION, TS.CANCELLED},
    TS.BINDING:               {TS.BOUND, TS.BINDING_FAILED, TS.MANUAL_INTERVENTION, TS.CANCELLED},
    TS.BOUND:                 {TS.MONITORING, TS.MANUAL_INTERVENTION, TS.CANCELLED},
    TS.BINDING_FAILED:        {TS.BINDING, TS.PUBLISHED_UNBOUND, TS.MANUAL_INTERVENTION, TS.CANCELLED},
    # Monitoring / terminal
    TS.MONITORING:            {TS.COMPLETED, TS.STOPPED, TS.MANUAL_INTERVENTION},
    TS.COMPLETED:             set(),       # terminal
    TS.STOPPED:               set(),       # terminal
    TS.REJECTED:              set(),       # terminal
    TS.EXPIRED:               set(),       # terminal
    TS.CANCELLED:             set(),       # terminal
    # Manual intervention can move to many non-terminal states
    TS.MANUAL_INTERVENTION:   {
        TS.APPLYING, TS.UNDER_REVIEW, TS.ACTIVE, TS.SCRIPTING, TS.SCRIPT_REVIEW,
        TS.SCRIPT_APPROVED, TS.VIDEO_QUEUED, TS.GENERATING, TS.QUALITY_CHECK,
        TS.REVIEW_REQUIRED, TS.APPROVED, TS.PUBLISH_QUEUED, TS.PUBLISHING,
        TS.PUBLISH_PENDING_SYNC, TS.PUBLISHED, TS.BINDING, TS.PUBLISHED_UNBOUND,
        TS.BINDING_FAILED, TS.BOUND, TS.MONITORING,
        TS.COMPLETED, TS.CANCELLED,
    },
}


@dataclass
class TransitionCheck:
    allowed: bool
    from_status: str
    to_status: str
    reason: str = ""


def can_transition(from_status: str, to_status: str) -> TransitionCheck:
    """Check if a status transition is valid."""
    if from_status == to_status:
        return TransitionCheck(True, from_status, to_status, "no-op: same status")

    allowed = _VALID_TRANSITIONS.get(from_status, set())
    if to_status in allowed:
        return TransitionCheck(True, from_status, to_status, "")

    return TransitionCheck(
        False, from_status, to_status,
        f"Invalid transition: '{from_status}' -> '{to_status}'",
    )


def must_transition(from_status: str, to_status: str) -> None:
    """Raise ValueError if the transition is not valid."""
    check = can_transition(from_status, to_status)
    if not check.allowed:
        raise ValueError(check.reason)


def is_terminal(status: str) -> bool:
    """Check if a status is terminal (no outgoing transitions)."""
    targets = _VALID_TRANSITIONS.get(status, set())
    return len(targets) == 0


def is_non_terminal_for_alias(status: str) -> bool:
    """Check if a status should prevent alias reuse (SQLite partial unique index)."""
    return not is_terminal(status)


# Old status → new status mapping
OLD_STATUS_MAP: dict[str, str] = {
    "started":            TS.APPLYING,
    "submitted":          TS.UNDER_REVIEW,
    "pending_review":     TS.UNDER_REVIEW,
    "under_review":       TS.UNDER_REVIEW,
    "active":             TS.ACTIVE,
    "rejected":           TS.REJECTED,
    "expired":            TS.EXPIRED,
    "alias_taken":        TS.APPLYING,  # keep applying, add alias conflict event
    "failed":             TS.APPLICATION_FAILED,
    "needs_manual_check": TS.MANUAL_INTERVENTION,
    "manual_or_skipped":  TS.MANUAL_INTERVENTION,
}
"""Map old task.json apply_status values to the new state machine."""


def map_old_status(old_status: str) -> str:
    """Map an old apply_status string to the new TaskStatus enum value.

    Unknown values default to MANUAL_INTERVENTION.
    """
    if not old_status:
        return TS.MANUAL_INTERVENTION
    return OLD_STATUS_MAP.get(old_status, TS.MANUAL_INTERVENTION)
