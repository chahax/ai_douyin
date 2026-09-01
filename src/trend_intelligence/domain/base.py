"""Contracts shared by pluggable content-operation domain strategies."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, ValidationError

from src.operations_accounts import AccountProfile


class DomainStrategyConfigError(ValueError):
    """Raised when an account's domain configuration is invalid."""


class EmptyDomainConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True, slots=True)
class DomainQueryPlan:
    root_keywords: list[str]
    related_keywords: list[str] = field(default_factory=list)
    negative_keywords: list[str] = field(default_factory=list)
    intent_labels: list[str] = field(default_factory=list)
    max_query_depth: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DomainTopicContext:
    title: str
    keywords: list[str]
    representative_titles: list[str]
    hashtags: list[str] = field(default_factory=list)
    sample_count: int = 0

    @property
    def searchable_text(self) -> str:
        return " ".join(
            [self.title, *self.keywords, *self.hashtags, *self.representative_titles]
        ).lower()


@dataclass(frozen=True, slots=True)
class AccountFitEvidence:
    score: float
    matched_terms: list[str] = field(default_factory=list)
    excluded_terms: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": round(float(self.score), 2),
            "matched_terms": list(self.matched_terms),
            "excluded_terms": list(self.excluded_terms),
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class DomainBriefBlueprint:
    audience_questions: list[str]
    angles: list[str]
    recommended_hook: str
    script_structure: list[str]
    risks: list[str]
    source_scope: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class DomainStrategy(Protocol):
    strategy_id: str
    version: str
    label: str

    def config_schema(self) -> dict[str, Any]: ...
    def validate_profile(self, profile: AccountProfile) -> dict[str, Any]: ...
    def build_query_plan(self, profile: AccountProfile) -> DomainQueryPlan: ...
    def score_account_fit(
        self,
        profile: AccountProfile,
        topic: DomainTopicContext,
    ) -> AccountFitEvidence: ...
    def build_brief_blueprint(
        self,
        profile: AccountProfile,
        topic: DomainTopicContext,
    ) -> DomainBriefBlueprint: ...


class PydanticDomainStrategy:
    """Base implementation for versioned, schema-driven domain config."""

    strategy_id: ClassVar[str]
    version: ClassVar[str] = "v1"
    label: ClassVar[str]
    config_model: ClassVar[type[BaseModel]] = EmptyDomainConfig

    def config_schema(self) -> dict[str, Any]:
        return self.config_model.model_json_schema()

    def validate_profile(self, profile: AccountProfile) -> dict[str, Any]:
        if profile.domain_strategy_id != self.strategy_id:
            raise DomainStrategyConfigError(
                f"profile strategy {profile.domain_strategy_id!r} does not match "
                f"{self.strategy_id!r}"
            )
        if profile.strategy_version != self.version:
            raise DomainStrategyConfigError(
                f"profile strategy version {profile.strategy_version!r} does not match "
                f"{self.version!r}"
            )
        try:
            config = self.config_model.model_validate(profile.domain_config)
        except ValidationError as exc:
            raise DomainStrategyConfigError(
                f"invalid {self.strategy_id}/{self.version} domain config: {exc}"
            ) from exc
        return config.model_dump(mode="json")


def unique_terms(*groups: list[str] | tuple[str, ...]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for raw in group or ():
            value = str(raw or "").strip()
            if value and value not in seen:
                seen.add(value)
                output.append(value)
    return output


def text_matches(text: str, terms: list[str]) -> list[str]:
    normalized = (text or "").lower()
    return [term for term in unique_terms(terms) if term.lower() in normalized]
