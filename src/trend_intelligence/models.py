"""Domain models for trend discovery and operation feedback."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class TrendObservation:
    item_id: str
    video_id: str
    url: str
    title: str
    author: str
    keyword: str
    sort_key: str
    sort_label: str
    rank: int
    run_id: str = ""
    metric_text: str = ""
    metric_value: int | None = None
    metric_kind: str = "displayed_unknown"
    collected_at: str = field(default_factory=utc_now_iso)
    published_at: str = ""
    published_at_text: str = ""
    raw_text: str = ""
    query_kind: str = "keyword"
    query_value: str = ""
    query_depth: int = 0
    root_keywords: list[str] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TrendTagRelation:
    root_keyword: str
    source_kind: str
    source_value: str
    target_tag: str
    relation_kind: str
    support_video_count: int
    source_video_count: int
    unique_authors: int
    sort_coverage: int
    weight: float
    relationship_score: float
    visible_metric_max: int | None = None
    expanded: bool = False
    supporting_item_ids: list[str] = field(default_factory=list)
    run_id: str = ""
    collected_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class TrendTagTrafficSnapshot:
    root_keyword: str
    tag: str
    sort_key: str
    sort_label: str
    unique_video_count: int
    best_rank: int
    reciprocal_rank_score: float
    sample_score: float
    visible_metric_max: int | None = None
    visible_metric_median: float | None = None
    top_item_ids: list[str] = field(default_factory=list)
    metric_kind: str = "displayed_unknown"
    score_kind: str = "sample_traffic_proxy"
    run_id: str = ""
    collected_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class TrendCluster:
    cluster_id: str
    title: str
    item_ids: list[str]
    keywords: list[str]
    sample_count: int
    sample_score: float
    trend_score: float | None
    selection_score: float
    score_kind: str
    score_breakdown: dict[str, float] = field(default_factory=dict)
    representative_titles: list[str] = field(default_factory=list)
    account_uuid: str = ""
    domain_strategy_id: str = ""
    strategy_version: str = ""
    strategy_evidence: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class TrendBrief:
    brief_id: str
    cluster_id: str
    title: str
    status: str
    score: float
    score_kind: str
    keywords: list[str]
    evidence: list[str]
    audience_questions: list[str]
    angles: list[str]
    recommended_hook: str
    script_structure: list[str]
    risks: list[str]
    source_scope: dict[str, Any]
    account_uuid: str = ""
    domain_strategy_id: str = ""
    strategy_version: str = ""
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class VideoMetricSnapshot:
    video_id: str
    local_id: str = ""
    captured_at: str = field(default_factory=utc_now_iso)
    publish_time: str = ""
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    collects: int = 0


@dataclass(slots=True)
class PublishedContentContext:
    local_id: str
    video_id: str = ""
    brief_id: str = ""
    cluster_id: str = ""
    script_version: str = "v1"
    workflow_profile: str = ""
    hook_type: str = ""
    content_format: str = ""
    duration_seconds: float | None = None
    published_at: str = ""


@dataclass(slots=True)
class PerformanceResult:
    identity: str
    video_id: str
    cluster_id: str
    brief_id: str
    view_velocity: float
    engagement_per_1k: float
    relative_performance: float
    observation_hours: float
    views_gained: int


@dataclass(slots=True)
class StrategyRecommendation:
    status: str
    sample_size: int
    proven_topics: list[str]
    adjacent_topics: list[str]
    experiment_share: float
    summary: str


@dataclass(slots=True)
class VideoTrendSignal:
    item_id: str
    video_id: str
    title: str
    author: str
    point_count: int
    observation_hours: float
    metric_kind: str
    metric_start: int | None
    metric_end: int | None
    metric_velocity_per_hour: float | None
    rank_start: int
    rank_end: int
    rank_improvement_per_hour: float
    run_coverage: float
    age_hours: float | None
    momentum_score: float
    confidence: float
    direction: str
    latest_collected_at: str


@dataclass(slots=True)
class TagFamilyTrendSignal:
    root_keyword: str
    tag: str
    sort_key: str
    point_count: int
    observation_hours: float
    sample_score_start: float
    sample_score_end: float
    sample_score_velocity_per_hour: float
    best_rank_start: int
    best_rank_end: int
    visible_metric_start: int | None
    visible_metric_end: int | None
    momentum_score: float
    confidence: float
    direction: str
    latest_collected_at: str
