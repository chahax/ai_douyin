"""Account-scoped, bounded collection planning."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Literal

from src.operations_accounts import AccountProfile
from src.trend_intelligence.domain import (
    DomainStrategyRegistry,
    get_default_domain_registry,
)
from src.trend_intelligence.providers.base import TrendCollectionRequest


CollectionWave = Literal["baseline", "discovery", "momentum"]
_WAVE_INTERVAL_HOURS = {"baseline": 24, "discovery": 24, "momentum": 6}


@dataclass(frozen=True, slots=True)
class PlannedCollectionBatch:
    batch_id: str
    sequence: int
    wave_kind: CollectionWave
    keywords: list[str]
    sorts: tuple[str, ...]
    limit_per_sort: int
    expand_related_tags: bool
    max_related_tags_per_keyword: int
    max_total_related_tags: int
    estimated_pages: int

    def to_request(
        self,
        *,
        headless: bool = False,
        web_crawler_enabled: bool = True,
    ) -> TrendCollectionRequest:
        return TrendCollectionRequest(
            keywords=list(self.keywords),
            limit_per_sort=self.limit_per_sort,
            sorts=self.sorts,
            headless=headless,
            web_crawler_enabled=web_crawler_enabled,
            expand_related_tags=self.expand_related_tags,
            max_related_tags_per_keyword=self.max_related_tags_per_keyword,
            max_total_related_tags=self.max_total_related_tags,
        )


@dataclass(frozen=True, slots=True)
class AccountCollectionPlan:
    plan_id: str
    account_uuid: str
    account_key: str
    profile_version: int
    domain_strategy_id: str
    strategy_version: str
    wave_kind: CollectionWave
    repeat_interval_hours: int
    negative_keywords: list[str]
    intent_labels: list[str]
    batches: list[PlannedCollectionBatch] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def estimated_pages(self) -> int:
        return sum(batch.estimated_pages for batch in self.batches)

    @property
    def keywords(self) -> list[str]:
        return _unique(
            keyword for batch in self.batches for keyword in batch.keywords
        )

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["estimated_pages"] = self.estimated_pages
        payload["keywords"] = self.keywords
        return payload


class TrendCollectionPlanner:
    """Convert a domain query plan into auditable browser-sized batches."""

    def __init__(
        self,
        registry: DomainStrategyRegistry | None = None,
        *,
        max_pages_per_batch: int = 30,
        max_keywords_per_batch: int = 2,
    ):
        if max_pages_per_batch < 1:
            raise ValueError("max_pages_per_batch must be positive")
        if max_keywords_per_batch < 1:
            raise ValueError("max_keywords_per_batch must be positive")
        self.registry = registry or get_default_domain_registry()
        self.max_pages_per_batch = max_pages_per_batch
        self.max_keywords_per_batch = max_keywords_per_batch

    def build(
        self,
        profile: AccountProfile,
        *,
        wave_kind: CollectionWave = "baseline",
        hot_keywords: list[str] | None = None,
        created_at: str | None = None,
    ) -> AccountCollectionPlan:
        if wave_kind not in _WAVE_INTERVAL_HOURS:
            raise ValueError(f"unsupported collection wave: {wave_kind}")
        strategy = self.registry.resolve(profile)
        query_plan = strategy.build_query_plan(profile)
        negative = _unique(query_plan.negative_keywords)
        if wave_kind == "baseline":
            keywords = query_plan.root_keywords
            sorts = ("comprehensive", "most_liked", "latest")
            expand, related_per_keyword, total_related = True, 2, 6
        elif wave_kind == "discovery":
            keywords = [*query_plan.root_keywords, *query_plan.related_keywords]
            sorts = ("comprehensive", "latest")
            expand, related_per_keyword, total_related = False, 0, 0
        else:
            keywords = hot_keywords or query_plan.root_keywords
            sorts = ("most_liked", "latest")
            expand, related_per_keyword, total_related = False, 0, 0

        filtered = [
            value
            for value in _unique(keywords)
            if not any(term.lower() in value.lower() for term in negative)
        ]
        if not filtered:
            raise ValueError("domain query plan produced no usable keywords")
        timestamp = created_at or datetime.now(timezone.utc).isoformat()
        identity = "|".join(
            (
                profile.account_uuid,
                str(profile.profile_version),
                profile.domain_strategy_id,
                profile.strategy_version,
                wave_kind,
                timestamp,
            )
        )
        plan_id = "plan:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        batches: list[PlannedCollectionBatch] = []
        for sequence, chunk in enumerate(
            _chunks(filtered, self.max_keywords_per_batch), start=1
        ):
            estimated_pages = _estimate_pages(
                keyword_count=len(chunk),
                sort_count=len(sorts),
                expand_related_tags=expand,
                related_per_keyword=related_per_keyword,
                total_related=total_related,
            )
            if estimated_pages > self.max_pages_per_batch:
                raise ValueError(
                    f"planned batch requires {estimated_pages} pages, exceeding "
                    f"the {self.max_pages_per_batch}-page cap"
                )
            batches.append(
                PlannedCollectionBatch(
                    batch_id=f"{plan_id}:b{sequence:03d}",
                    sequence=sequence,
                    wave_kind=wave_kind,
                    keywords=chunk,
                    sorts=sorts,
                    limit_per_sort=20,
                    expand_related_tags=expand,
                    max_related_tags_per_keyword=related_per_keyword,
                    max_total_related_tags=total_related,
                    estimated_pages=estimated_pages,
                )
            )
        return AccountCollectionPlan(
            plan_id=plan_id,
            account_uuid=profile.account_uuid,
            account_key=profile.account_key,
            profile_version=profile.profile_version,
            domain_strategy_id=profile.domain_strategy_id,
            strategy_version=profile.strategy_version,
            wave_kind=wave_kind,
            repeat_interval_hours=_WAVE_INTERVAL_HOURS[wave_kind],
            negative_keywords=negative,
            intent_labels=list(query_plan.intent_labels),
            batches=batches,
            created_at=timestamp,
        )


def _estimate_pages(
    *,
    keyword_count: int,
    sort_count: int,
    expand_related_tags: bool,
    related_per_keyword: int,
    total_related: int,
) -> int:
    base = keyword_count * sort_count
    if not expand_related_tags:
        return base
    related = min(total_related, keyword_count * related_per_keyword)
    return base + related * sort_count


def _chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _unique(values) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw or "").strip()
        if value and value not in seen:
            seen.add(value)
            output.append(value)
    return output
