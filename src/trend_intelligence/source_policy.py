"""Fail-closed source authorization for trend collection.

This module contains no browser or HTTP code.  Every provider, including future
authorized web providers, must obtain an allowed decision before doing I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable
from urllib.parse import urlparse


class SourceProvider(str, Enum):
    MANUAL_IMPORT = "manual_import"
    OWNED_ACCOUNT_EXPORT = "owned_account_export"
    LICENSED_FEED = "licensed_feed"
    AUTHORIZED_WEB = "authorized_web"


class PolicyStatus(str, Enum):
    UNVERIFIED = "unverified"
    APPROVED = "approved"
    SUSPENDED = "suspended"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class SourcePolicy:
    policy_id: str
    provider: SourceProvider
    status: PolicyStatus = PolicyStatus.UNVERIFIED
    allowed_hosts: tuple[str, ...] = ()
    allowed_path_prefixes: tuple[str, ...] = ()
    allowed_fields: frozenset[str] = field(default_factory=frozenset)
    allowed_purposes: frozenset[str] = field(default_factory=frozenset)
    min_interval_seconds: float = 0.0
    max_pages_per_run: int = 1
    daily_page_cap: int = 1
    raw_retention_days: int = 0
    starts_at: datetime | None = None
    expires_at: datetime | None = None
    authorization_reference_hash: str | None = None

    def __post_init__(self) -> None:
        if not self.policy_id.strip():
            raise ValueError("policy_id cannot be empty")
        if self.min_interval_seconds < 0:
            raise ValueError("min_interval_seconds cannot be negative")
        if self.max_pages_per_run < 0 or self.daily_page_cap < 0:
            raise ValueError("page limits cannot be negative")
        if self.raw_retention_days < 0:
            raise ValueError("raw_retention_days cannot be negative")
        _require_aware(self.starts_at, "starts_at")
        _require_aware(self.expires_at, "expires_at")
        if self.starts_at and self.expires_at and self.starts_at >= self.expires_at:
            raise ValueError("starts_at must be earlier than expires_at")


@dataclass(frozen=True, slots=True)
class SourceRequest:
    provider: SourceProvider
    purposes: frozenset[str]
    requested_fields: frozenset[str] = field(default_factory=frozenset)
    target_url: str | None = None
    planned_pages: int = 1
    pages_used_today: int = 0
    requested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.purposes:
            raise ValueError("at least one purpose is required")
        if self.planned_pages < 1:
            raise ValueError("planned_pages must be at least 1")
        if self.pages_used_today < 0:
            raise ValueError("pages_used_today cannot be negative")
        _require_aware(self.requested_at, "requested_at")


@dataclass(frozen=True, slots=True)
class SourcePolicyDecision:
    allowed: bool
    code: str
    reason: str
    policy_id: str
    min_interval_seconds: float = 0.0
    max_pages_per_run: int = 0
    daily_page_cap: int = 0


class SourcePolicyGate:
    """Evaluate a request without side effects and deny on missing information."""

    def evaluate(
        self,
        policy: SourcePolicy,
        request: SourceRequest,
        *,
        web_crawler_enabled: bool = False,
    ) -> SourcePolicyDecision:
        def deny(code: str, reason: str) -> SourcePolicyDecision:
            return SourcePolicyDecision(False, code, reason, policy.policy_id)

        if request.provider != policy.provider:
            return deny("provider_mismatch", "request provider does not match policy")
        if policy.status != PolicyStatus.APPROVED:
            return deny("policy_not_approved", f"policy status is {policy.status.value}")

        now = request.requested_at.astimezone(timezone.utc)
        if policy.starts_at and now < policy.starts_at.astimezone(timezone.utc):
            return deny("policy_not_started", "authorization is not active yet")
        if policy.expires_at and now >= policy.expires_at.astimezone(timezone.utc):
            return deny("policy_expired", "authorization has expired")

        disallowed_purposes = request.purposes - policy.allowed_purposes
        if disallowed_purposes:
            return deny(
                "purpose_not_allowed",
                f"purposes are not authorized: {_stable_list(disallowed_purposes)}",
            )

        disallowed_fields = request.requested_fields - policy.allowed_fields
        if disallowed_fields:
            return deny(
                "fields_not_allowed",
                f"fields are not authorized: {_stable_list(disallowed_fields)}",
            )

        if request.planned_pages > policy.max_pages_per_run:
            return deny("run_page_cap_exceeded", "planned pages exceed per-run policy cap")
        if request.pages_used_today + request.planned_pages > policy.daily_page_cap:
            return deny("daily_page_cap_exceeded", "planned pages exceed daily policy cap")

        if policy.provider == SourceProvider.AUTHORIZED_WEB:
            web_denial = self._evaluate_web_scope(policy, request, web_crawler_enabled)
            if web_denial is not None:
                return deny(*web_denial)

        return SourcePolicyDecision(
            True,
            "allowed",
            "request is within the approved source policy",
            policy.policy_id,
            min_interval_seconds=policy.min_interval_seconds,
            max_pages_per_run=policy.max_pages_per_run,
            daily_page_cap=policy.daily_page_cap,
        )

    @staticmethod
    def _evaluate_web_scope(
        policy: SourcePolicy,
        request: SourceRequest,
        web_crawler_enabled: bool,
    ) -> tuple[str, str] | None:
        if not web_crawler_enabled:
            return "web_crawler_disabled", "automatic web collection is disabled"
        if not policy.authorization_reference_hash:
            return "authorization_evidence_missing", "written authorization evidence is missing"
        if not request.target_url:
            return "target_url_missing", "authorized web collection requires a target URL"

        parsed = urlparse(request.target_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return "invalid_target_url", "target URL must be an absolute HTTP(S) URL"
        host = parsed.hostname.lower().rstrip(".")
        if not any(_host_matches(host, pattern) for pattern in policy.allowed_hosts):
            return "host_not_allowed", "target host is outside the authorized scope"
        if not any(_path_matches(parsed.path or "/", prefix) for prefix in policy.allowed_path_prefixes):
            return "path_not_allowed", "target path is outside the authorized scope"
        return None


def approved_manual_import_policy(
    *,
    policy_id: str = "manual-import-default",
    allowed_fields: Iterable[str] = (),
    allowed_purposes: Iterable[str] = ("trend_analysis",),
) -> SourcePolicy:
    """Build the explicit local-import policy used by the offline MVP."""

    return SourcePolicy(
        policy_id=policy_id,
        provider=SourceProvider.MANUAL_IMPORT,
        status=PolicyStatus.APPROVED,
        allowed_fields=frozenset(allowed_fields),
        allowed_purposes=frozenset(allowed_purposes),
        max_pages_per_run=1,
        daily_page_cap=1,
    )


def _host_matches(host: str, pattern: str) -> bool:
    normalized = pattern.lower().rstrip(".")
    if normalized.startswith("*."):
        suffix = normalized[2:]
        return bool(suffix) and host.endswith(f".{suffix}")
    return host == normalized


def _path_matches(path: str, prefix: str) -> bool:
    normalized = "/" + prefix.lstrip("/")
    if normalized == "/":
        return True
    normalized = normalized.rstrip("/")
    return path == normalized or path.startswith(f"{normalized}/")


def _require_aware(value: datetime | None, name: str) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError(f"{name} must be timezone-aware")


def _stable_list(values: Iterable[str]) -> str:
    return ", ".join(sorted(values))
