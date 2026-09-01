"""Multi-run momentum signals for videos and tag families."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from .models import (
    TagFamilyTrendSignal,
    TrendObservation,
    TrendTagTrafficSnapshot,
    VideoTrendSignal,
)
from .repository import TrendRepository


class TemporalTrendService:
    def __init__(self, repository: TrendRepository):
        self.repository = repository

    def video_signals(
        self, *, window_days: int = 14, limit: int = 100_000
    ) -> list[VideoTrendSignal]:
        return build_video_trend_signals(
            self.repository.list_observations(limit=limit), window_days=window_days
        )

    def tag_family_signals(
        self, *, window_days: int = 14, limit: int = 100_000
    ) -> list[TagFamilyTrendSignal]:
        return build_tag_family_trend_signals(
            self.repository.list_tag_traffic_snapshots(limit=limit),
            window_days=window_days,
        )


def build_video_trend_signals(
    observations: list[TrendObservation], *, window_days: int = 14
) -> list[VideoTrendSignal]:
    if window_days < 1:
        raise ValueError("window_days must be positive")
    if not observations:
        return []
    latest_time = max(_parse_time(item.collected_at) for item in observations)
    cutoff = latest_time - timedelta(days=window_days)
    window = [item for item in observations if _parse_time(item.collected_at) >= cutoff]
    run_ids = {item.run_id for item in window if item.run_id}
    grouped: dict[str, list[TrendObservation]] = defaultdict(list)
    for item in window:
        grouped[item.item_id].append(item)
    signals = [
        _video_signal(rows, total_runs=max(1, len(run_ids)))
        for rows in grouped.values()
    ]
    return sorted(
        signals,
        key=lambda item: (item.momentum_score, item.confidence),
        reverse=True,
    )


def build_tag_family_trend_signals(
    snapshots: list[TrendTagTrafficSnapshot], *, window_days: int = 14
) -> list[TagFamilyTrendSignal]:
    if window_days < 1:
        raise ValueError("window_days must be positive")
    if not snapshots:
        return []
    latest_time = max(_parse_time(item.collected_at) for item in snapshots)
    cutoff = latest_time - timedelta(days=window_days)
    grouped: dict[tuple[str, str, str], list[TrendTagTrafficSnapshot]] = defaultdict(list)
    for item in snapshots:
        if _parse_time(item.collected_at) >= cutoff:
            grouped[(item.root_keyword, item.tag, item.sort_key)].append(item)
    signals = [_tag_signal(rows) for rows in grouped.values()]
    return sorted(
        signals,
        key=lambda item: (item.momentum_score, item.confidence),
        reverse=True,
    )


def _video_signal(
    rows: list[TrendObservation], *, total_runs: int
) -> VideoTrendSignal:
    points = _collapse_video_points(rows)
    first_time, first_metric, first_rank = points[0]
    last_time, last_metric, last_rank = points[-1]
    hours = max((last_time - first_time).total_seconds() / 3600, 1 / 60)
    metric_velocity = None
    if first_metric is not None and last_metric is not None:
        metric_velocity = (last_metric - first_metric) / hours
    rank_velocity = (first_rank - last_rank) / hours
    metric_component = 0.0
    if metric_velocity is not None:
        metric_component = math.copysign(
            min(1.0, math.log10(abs(metric_velocity) + 1) / 4), metric_velocity
        )
    rank_component = max(-1.0, min(1.0, rank_velocity / 5))
    run_coverage = min(1.0, len(points) / max(1, total_runs))
    published = [_parse_optional_time(item.published_at) for item in rows]
    valid_published = [item for item in published if item is not None]
    age_hours = None
    freshness = 0.5
    if valid_published:
        age_hours = max(
            0.0, (last_time - max(valid_published)).total_seconds() / 3600
        )
        freshness = max(0.0, 1.0 - age_hours / (24 * 30))
    signed_momentum = 0.6 * metric_component + 0.25 * rank_component + 0.15 * (
        freshness * 2 - 1
    )
    momentum_score = max(0.0, min(100.0, 50 + 50 * signed_momentum))
    has_known_metric = all(
        (item.metric_kind or "displayed_unknown") != "displayed_unknown"
        for item in rows
    )
    confidence = min(1.0, len(points) / 4) * min(1.0, hours / 24)
    if not has_known_metric:
        confidence *= 0.75
    if len(points) < 2:
        direction = "insufficient"
        confidence = 0.0
    elif momentum_score >= 60:
        direction = "rising"
    elif momentum_score <= 40:
        direction = "falling"
    else:
        direction = "stable"
    newest = max(rows, key=lambda item: _parse_time(item.collected_at))
    return VideoTrendSignal(
        item_id=newest.item_id,
        video_id=newest.video_id,
        title=newest.title,
        author=newest.author,
        point_count=len(points),
        observation_hours=round(hours if len(points) >= 2 else 0.0, 3),
        metric_kind=_dominant_metric_kind(rows),
        metric_start=first_metric,
        metric_end=last_metric,
        metric_velocity_per_hour=(
            round(metric_velocity, 3) if metric_velocity is not None else None
        ),
        rank_start=first_rank,
        rank_end=last_rank,
        rank_improvement_per_hour=round(rank_velocity, 3),
        run_coverage=round(run_coverage, 3),
        age_hours=round(age_hours, 3) if age_hours is not None else None,
        momentum_score=round(momentum_score, 2),
        confidence=round(confidence, 3),
        direction=direction,
        latest_collected_at=newest.collected_at,
    )


def _tag_signal(rows: list[TrendTagTrafficSnapshot]) -> TagFamilyTrendSignal:
    ordered = sorted(rows, key=lambda item: _parse_time(item.collected_at))
    first, last = ordered[0], ordered[-1]
    hours = max(
        (_parse_time(last.collected_at) - _parse_time(first.collected_at)).total_seconds()
        / 3600,
        1 / 60,
    )
    sample_velocity = (last.sample_score - first.sample_score) / hours
    rank_velocity = (first.best_rank - last.best_rank) / hours
    metric_velocity = 0.0
    if first.visible_metric_max is not None and last.visible_metric_max is not None:
        metric_velocity = (last.visible_metric_max - first.visible_metric_max) / hours
    sample_component = max(-1.0, min(1.0, sample_velocity / 5))
    rank_component = max(-1.0, min(1.0, rank_velocity / 5))
    metric_component = math.copysign(
        min(1.0, math.log10(abs(metric_velocity) + 1) / 4), metric_velocity
    )
    momentum = max(
        0.0,
        min(
            100.0,
            50
            + 50
            * (
                0.5 * sample_component
                + 0.3 * rank_component
                + 0.2 * metric_component
            ),
        ),
    )
    confidence = min(1.0, len(ordered) / 4) * min(1.0, hours / 24)
    if len(ordered) < 2:
        direction = "insufficient"
        confidence = 0.0
    elif momentum >= 60:
        direction = "rising"
    elif momentum <= 40:
        direction = "falling"
    else:
        direction = "stable"
    return TagFamilyTrendSignal(
        root_keyword=last.root_keyword,
        tag=last.tag,
        sort_key=last.sort_key,
        point_count=len(ordered),
        observation_hours=round(hours if len(ordered) >= 2 else 0.0, 3),
        sample_score_start=first.sample_score,
        sample_score_end=last.sample_score,
        sample_score_velocity_per_hour=round(sample_velocity, 3),
        best_rank_start=first.best_rank,
        best_rank_end=last.best_rank,
        visible_metric_start=first.visible_metric_max,
        visible_metric_end=last.visible_metric_max,
        momentum_score=round(momentum, 2),
        confidence=round(confidence, 3),
        direction=direction,
        latest_collected_at=last.collected_at,
    )


def _collapse_video_points(
    rows: list[TrendObservation],
) -> list[tuple[datetime, int | None, int]]:
    by_run: dict[str, list[TrendObservation]] = defaultdict(list)
    for index, row in enumerate(rows):
        key = row.run_id or f"untracked:{row.collected_at}:{index}"
        by_run[key].append(row)
    points: list[tuple[datetime, int | None, int]] = []
    for run_rows in by_run.values():
        captured = max(_parse_time(item.collected_at) for item in run_rows)
        metrics = [item.metric_value for item in run_rows if item.metric_value is not None]
        points.append(
            (
                captured,
                max(metrics) if metrics else None,
                min(max(1, item.rank) for item in run_rows),
            )
        )
    return sorted(points, key=lambda item: item[0])


def _dominant_metric_kind(rows: list[TrendObservation]) -> str:
    values = [item.metric_kind for item in rows if item.metric_kind]
    return max(set(values), key=values.count) if values else "displayed_unknown"


def _parse_optional_time(value: str) -> datetime | None:
    return _parse_time(value) if value else None


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat((value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
