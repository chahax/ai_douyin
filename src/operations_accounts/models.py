"""Provider-neutral operation account profile models."""

from __future__ import annotations

import re
import hashlib
from dataclasses import dataclass, field
from typing import Any


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


@dataclass(slots=True)
class AccountProfile:
    """Immutable-in-practice strategy snapshot used by one analysis run.

    Authentication material deliberately does not belong to this model. Browser
    profiles remain isolated by ``account_key`` in the platform adapter layer.
    """

    account_uuid: str
    account_key: str
    domain_strategy_id: str
    strategy_version: str = "v1"
    profile_version: int = 1
    platform: str = "douyin"
    display_name: str = ""
    business_mode: str = ""
    business_goals: list[str] = field(default_factory=list)
    target_audiences: list[str] = field(default_factory=list)
    service_scope: list[str] = field(default_factory=list)
    geo_scope: list[str] = field(default_factory=list)
    seed_keywords: list[str] = field(default_factory=list)
    negative_keywords: list[str] = field(default_factory=list)
    allowed_formats: list[str] = field(default_factory=list)
    forbidden_formats: list[str] = field(default_factory=list)
    cta_policy: list[str] = field(default_factory=list)
    workflow_profile: str = ""
    publishing_windows: list[str] = field(default_factory=list)
    experiment_policy: dict[str, float] = field(
        default_factory=lambda: {"proven": 0.7, "adjacent": 0.2, "experiment": 0.1}
    )
    domain_config: dict[str, Any] = field(default_factory=dict)
    status: str = "active"

    def __post_init__(self) -> None:
        for name in ("account_uuid", "account_key", "domain_strategy_id"):
            value = str(getattr(self, name) or "").strip()
            if not _SAFE_ID.fullmatch(value):
                raise ValueError(f"invalid {name}: {value!r}")
            setattr(self, name, value)
        self.strategy_version = str(self.strategy_version or "").strip()
        if not _SAFE_ID.fullmatch(self.strategy_version):
            raise ValueError(f"invalid strategy_version: {self.strategy_version!r}")
        if self.profile_version < 1:
            raise ValueError("profile_version must be at least 1")
        if self.status not in {"active", "paused", "disabled"}:
            raise ValueError(f"invalid account profile status: {self.status}")
        self.experiment_policy = _validate_experiment_policy(self.experiment_policy)
        for name in (
            "business_goals",
            "target_audiences",
            "service_scope",
            "geo_scope",
            "seed_keywords",
            "negative_keywords",
            "allowed_formats",
            "forbidden_formats",
            "cta_policy",
            "publishing_windows",
        ):
            setattr(self, name, _unique_strings(getattr(self, name)))
        self.domain_config = dict(self.domain_config or {})

    @property
    def strategy_key(self) -> tuple[str, str]:
        return self.domain_strategy_id, self.strategy_version

    def matching_terms(self) -> list[str]:
        return _unique_strings(
            [
                *self.seed_keywords,
                *self.service_scope,
                *self.target_audiences,
                *self.business_goals,
            ]
        )


def stable_account_uuid(account_key: str) -> str:
    normalized = str(account_key or "").strip()
    if not _SAFE_ID.fullmatch(normalized):
        raise ValueError(f"invalid account_key: {normalized!r}")
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
    return f"account:{digest}"


def _unique_strings(values: list[str] | tuple[str, ...]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for raw in values or ():
        value = str(raw or "").strip()
        if value and value not in seen:
            seen.add(value)
            output.append(value)
    return output


def _validate_experiment_policy(value: dict[str, float] | None) -> dict[str, float]:
    policy = dict(value or {})
    required = {"proven", "adjacent", "experiment"}
    if set(policy) != required:
        raise ValueError(
            "experiment_policy must contain proven, adjacent, and experiment"
        )
    normalized = {key: float(policy[key]) for key in required}
    if any(item < 0 or item > 1 for item in normalized.values()):
        raise ValueError("experiment_policy values must be between 0 and 1")
    if abs(sum(normalized.values()) - 1.0) > 1e-6:
        raise ValueError("experiment_policy values must sum to 1")
    return {
        "proven": normalized["proven"],
        "adjacent": normalized["adjacent"],
        "experiment": normalized["experiment"],
    }
