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
    manual_verification_timeout_seconds: int = 0
    related_tag_domain: str = ""
    related_tag_filter_terms: tuple[str, ...] = ()
    related_tag_excluded_terms: tuple[str, ...] = ()
    min_related_tag_support_videos: int = 1
    min_related_tag_unique_authors: int = 0


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
    blocked_search: dict = field(default_factory=dict)
    challenge_evidence: dict = field(default_factory=dict)
    navigation_evidence: dict = field(default_factory=dict)


class TrendProvider(Protocol):
    provider_id: str

    def collect(
        self,
        request: TrendCollectionRequest,
        *,
        policy: SourcePolicy,
    ) -> TrendCollectionResult: ...


def related_tag_selection_options(request: TrendCollectionRequest) -> dict:
    """Shared before-search and after-filter selection rules; legacy defaults retained."""
    def allowed(tag):
        text = tag.casefold()
        if request.related_tag_domain == "legal_services":
            from src.trend_intelligence.collection.legal_core import legal_topic_tag_exclusion
            if legal_topic_tag_exclusion(tag): return False
        return ((not request.related_tag_filter_terms or
                 any(term.casefold() in text for term in request.related_tag_filter_terms))
                and not any(term.casefold() in text for term in request.related_tag_excluded_terms))
    return {"candidate_filter": allowed if (request.related_tag_domain or request.related_tag_filter_terms or request.related_tag_excluded_terms) else None,
            "min_support_videos": max(1, request.min_related_tag_support_videos),
            "min_unique_authors": max(0, request.min_related_tag_unique_authors)}
