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


@dataclass(slots=True)
class DouyinIdentity:
    """Verified public identity; never contains a password or access token."""

    nickname: str
    avatar_url: str = ""
    public_uid: str = ""
    open_id: str = ""
    union_id: str = ""
    sec_uid: str = ""
    verification_source: str = "page_verified"
    verified_at: str = ""
    auth_expires_at: str = ""

    @property
    def platform_identity_key(self) -> str:
        if self.open_id:
            return f"open_id:{self.open_id}"
        if self.sec_uid:
            return f"sec_uid:{self.sec_uid}"
        if self.public_uid:
            return f"public_uid:{self.public_uid}"
        return ""

    def validate(self) -> None:
        if not self.nickname.strip():
            raise ValueError("抖音身份缺少昵称，不能确认绑定。")
        if not self.platform_identity_key:
            raise ValueError("抖音身份缺少 open_id、公开 UID 或 sec_uid，不能确认绑定。")
        if self.verification_source not in {"official_oauth", "page_verified"}:
            raise ValueError("不支持的抖音身份验证来源。")


@dataclass(slots=True)
class AccountBinding:
    """One-to-one account, browser environment and Douyin identity binding."""

    account_uuid: str
    account_key: str
    browser_environment_key: str
    browser_profile_dir: str
    storage_state_path: str
    platform_identity_key: str
    nickname: str
    avatar_url: str = ""
    public_uid: str = ""
    open_id: str = ""
    union_id: str = ""
    sec_uid: str = ""
    verification_source: str = "page_verified"
    status: str = "active"
    verified_at: str = ""
    last_health_at: str = ""
    auth_expires_at: str = ""
    last_error: str = ""
    confirmed_by: str = ""
    created_at: str = ""
    updated_at: str = ""

    @property
    def display_identity(self) -> str:
        uid = self.public_uid or self.open_id or self.sec_uid
        return f"{self.nickname}（{uid}）" if uid else self.nickname


@dataclass(slots=True)
class AccountRuntimeState:
    account_uuid: str
    day_key: str = ""
    daily_runs: int = 0
    last_run_at: str = ""
    lock_owner: str = ""
    lock_expires_at: str = ""
    consecutive_failures: int = 0
    circuit_open_until: str = ""
    updated_at: str = ""


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
