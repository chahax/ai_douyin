"""Provider contracts for trend collection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from src.trend_intelligence.models import (
    TrendObservation,
    TrendTagRelation,
    TrendTagTrafficSnapshot,
)
from src.trend_intelligence.source_policy import SourcePolicy


@dataclass(slots=True)
class TrendCollectionRequest:
    keywords: list[str]
    limit_per_sort: int = 20
    sorts: tuple[str, ...] = ("comprehensive", "most_liked", "latest")
    headless: bool = False
    web_crawler_enabled: bool = False
    expand_related_tags: bool = False
    max_related_tags_per_keyword: int = 2
    max_total_related_tags: int = 6


@dataclass(slots=True)
class TrendCollectionResult:
    observations: list[TrendObservation]
    warnings: list[str] = field(default_factory=list)
    policy_code: str = "allowed"
    stopped_reason: str = ""
    tag_relations: list[TrendTagRelation] = field(default_factory=list)
    tag_traffic_snapshots: list[TrendTagTrafficSnapshot] = field(
        default_factory=list
    )


class TrendProvider(Protocol):
    provider_id: str

    def collect(
        self,
        request: TrendCollectionRequest,
        *,
        policy: SourcePolicy,
    ) -> TrendCollectionResult: ...
