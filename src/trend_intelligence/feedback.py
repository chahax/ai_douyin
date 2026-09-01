"""Multi-window performance attribution and next-cycle learning."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean, median

from .models import (
    DimensionPerformance,
    FeedbackLearningReport,
    PerformanceResult,
    SnapshotWindowDue,
    StrategyRecommendation,
    VideoMetricSnapshot,
)
from .repository import TrendRepository


SNAPSHOT_WINDOWS = {
    "1h": 1,
    "6h": 6,
    "24h": 24,
    "72h": 72,
    "7d": 168,
}


class OperationsFeedbackService:
    def __init__(self, repository: TrendRepository | None = None):
        self.repository = repository or TrendRepository()

    def performance_results(
        self, *, account_uuid: str = ""
    ) -> list[PerformanceResult]:
        raw: list[tuple[object, list[VideoMetricSnapshot], float, float, int, str]] = []
        for context in self.repository.list_contexts():
            if account_uuid and context.account_uuid != account_uuid:
                continue
            snapshots = self.repository.list_video_snapshots(
                video_id=context.video_id,
                local_id=context.local_id,
            )
            snapshots = _deduplicate_snapshots(snapshots)
            if len(snapshots) < 2:
                continue
            first, last = snapshots[0], snapshots[-1]
            hours = max(
                (_parse_time(last.captured_at) - _parse_time(first.captured_at)).total_seconds()
                / 3600,
                1 / 60,
            )
            views_gained = max(0, last.views - first.views)
            velocity = views_gained / hours
            engagement = (
                last.likes + 2 * last.comments + 3 * last.shares + 2 * last.collects
            )
            engagement_per_1k = engagement / max(1, last.views) * 1000
            raw.append(
                (
                    context,
                    snapshots,
                    velocity,
                    engagement_per_1k,
                    views_gained,
                    _latest_window(context.published_at, last.captured_at, hours),
                )
            )

        baselines: dict[tuple[str, str, str], float] = {}
        grouped_velocities: dict[tuple[str, str, str], list[float]] = defaultdict(list)
        for context, _, velocity, _, _, latest_window in raw:
            grouped_velocities[
                (
                    context.account_uuid or "legacy",
                    _duration_bucket(context.duration_seconds),
                    latest_window,
                )
            ].append(velocity)
        for key, values in grouped_velocities.items():
            baselines[key] = median(values)

        results: list[PerformanceResult] = []
        for context, snapshots, velocity, engagement_per_1k, views_gained, latest_window in raw:
            first, last = snapshots[0], snapshots[-1]
            hours = max(
                (_parse_time(last.captured_at) - _parse_time(first.captured_at)).total_seconds()
                / 3600,
                1 / 60,
            )
            baseline = baselines.get(
                (
                    context.account_uuid or "legacy",
                    _duration_bucket(context.duration_seconds),
                    latest_window,
                ),
                0.0,
            )
            relative = velocity / baseline if baseline > 0 else 1.0
            results.append(
                PerformanceResult(
                    identity=context.local_id or context.video_id,
                    video_id=context.video_id,
                    cluster_id=context.cluster_id,
                    brief_id=context.brief_id,
                    view_velocity=round(velocity, 3),
                    engagement_per_1k=round(engagement_per_1k, 3),
                    relative_performance=round(relative, 3),
                    observation_hours=round(hours, 3),
                    views_gained=views_gained,
                    account_uuid=context.account_uuid,
                    opportunity_id=context.opportunity_id,
                    script_id=context.script_id,
                    script_variant=context.script_variant,
                    hook_type=context.hook_type,
                    presentation_type=(
                        context.presentation_type or context.content_format
                    ),
                    workflow_profile=context.workflow_profile,
                    publish_window=context.publish_window,
                    latest_window=latest_window,
                )
            )
        return sorted(
            results, key=lambda result: result.relative_performance, reverse=True
        )

    def dimension_performance(
        self, *, account_uuid: str = ""
    ) -> list[DimensionPerformance]:
        results = self.performance_results(account_uuid=account_uuid)
        grouped: dict[tuple[str, str], list[PerformanceResult]] = defaultdict(list)
        dimensions = {
            "topic": lambda item: item.cluster_id,
            "opportunity": lambda item: item.opportunity_id,
            "script_variant": lambda item: item.script_variant,
            "hook": lambda item: item.hook_type,
            "presentation": lambda item: item.presentation_type,
            "workflow": lambda item: item.workflow_profile,
            "publish_window": lambda item: item.publish_window,
            "metric_window": lambda item: item.latest_window,
        }
        for result in results:
            for dimension, getter in dimensions.items():
                value = str(getter(result) or "").strip()
                if value:
                    grouped[(dimension, value)].append(result)
        output: list[DimensionPerformance] = []
        for (dimension, value), rows in grouped.items():
            sample_size = len(rows)
            output.append(
                DimensionPerformance(
                    dimension=dimension,
                    value=value,
                    sample_size=sample_size,
                    average_relative_performance=round(
                        mean(item.relative_performance for item in rows), 3
                    ),
                    average_view_velocity=round(
                        mean(item.view_velocity for item in rows), 3
                    ),
                    average_engagement_per_1k=round(
                        mean(item.engagement_per_1k for item in rows), 3
                    ),
                    win_rate=round(
                        sum(item.relative_performance >= 1.0 for item in rows)
                        / sample_size,
                        3,
                    ),
                    confidence=round(min(1.0, sample_size / 5), 3),
                )
            )
        return sorted(
            output,
            key=lambda item: (
                item.average_relative_performance * item.confidence,
                item.sample_size,
            ),
            reverse=True,
        )

    def recommend_next_cycle(
        self, *, account_uuid: str = ""
    ) -> StrategyRecommendation:
        results = self.performance_results(account_uuid=account_uuid)
        if len(results) < 3:
            return StrategyRecommendation(
                status="observing",
                sample_size=len(results),
                proven_topics=[],
                adjacent_topics=[],
                experiment_share=0.1,
                summary="有效复盘样本不足 3 条，继续采集多时点指标，不调整稳定策略。",
                allocation={"proven": 0.7, "adjacent": 0.2, "experiment": 0.1},
            )

        dimensions = self.dimension_performance(account_uuid=account_uuid)
        topics = [item for item in dimensions if item.dimension == "topic"]
        proven = [
            item.value
            for item in topics
            if item.sample_size >= 2 and item.average_relative_performance >= 0.7
        ][:3]
        if not proven and topics:
            proven = [topics[0].value]
        adjacent = [item.value for item in topics if item.value not in proven][:3]
        winners = [
            f"{item.dimension}:{item.value}"
            for item in dimensions
            if item.sample_size >= 2 and item.average_relative_performance >= 1.1
        ][:8]
        losers = [
            f"{item.dimension}:{item.value}"
            for item in reversed(dimensions)
            if item.sample_size >= 2 and item.average_relative_performance < 0.8
        ][:8]
        return StrategyRecommendation(
            status="ready",
            sample_size=len(results),
            proven_topics=proven,
            adjacent_topics=adjacent,
            experiment_share=0.1,
            summary=(
                "下一批按 70% 已验证题材、20% 相邻题材、10% 新实验分配；"
                "同时参考钩子、展示方式、工作流和发布时间窗的同账号相对表现。"
            ),
            winning_dimensions=winners,
            losing_dimensions=losers,
            allocation={"proven": 0.7, "adjacent": 0.2, "experiment": 0.1},
        )

    def build_learning_report(
        self,
        *,
        account_uuid: str,
        profile_version: int,
    ) -> FeedbackLearningReport:
        if not account_uuid:
            raise ValueError("account_uuid is required for a learning report")
        dimensions = self.dimension_performance(account_uuid=account_uuid)
        recommendation = self.recommend_next_cycle(account_uuid=account_uuid)
        adjustments = {
            f"{item.dimension}:{item.value}": _dimension_score(item)
            for item in dimensions
            if item.dimension != "metric_window"
        }
        identity = "|".join(
            (
                account_uuid,
                str(profile_version),
                str(recommendation.sample_size),
                "|".join(f"{key}={value:.2f}" for key, value in adjustments.items()),
            )
        )
        report = FeedbackLearningReport(
            report_id="feedback:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24],
            account_uuid=account_uuid,
            profile_version=profile_version,
            sample_size=recommendation.sample_size,
            status=recommendation.status,
            dimensions=dimensions,
            score_adjustments=adjustments,
            proven_topics=recommendation.proven_topics,
            next_cycle_allocation=dict(recommendation.allocation),
            summary=recommendation.summary,
        )
        self.repository.save_feedback_learning_report(report)
        return report

    def due_snapshot_windows(
        self,
        *,
        account_uuid: str = "",
        now: datetime | None = None,
    ) -> list[SnapshotWindowDue]:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        due: list[SnapshotWindowDue] = []
        for context in self.repository.list_contexts():
            if account_uuid and context.account_uuid != account_uuid:
                continue
            published = _parse_optional_time(context.published_at)
            if published is None:
                continue
            snapshots = self.repository.list_video_snapshots(
                video_id=context.video_id, local_id=context.local_id
            )
            elapsed = sorted(
                max(
                    0.0,
                    (_parse_time(item.captured_at) - published).total_seconds() / 3600,
                )
                for item in snapshots
            )
            for window, hours in SNAPSHOT_WINDOWS.items():
                target = published + timedelta(hours=hours)
                if current < target:
                    continue
                if any(value >= hours * 0.8 for value in elapsed):
                    continue
                due.append(
                    SnapshotWindowDue(
                        local_id=context.local_id,
                        video_id=context.video_id,
                        account_uuid=context.account_uuid,
                        window=window,
                        target_at=target.isoformat(),
                        overdue_hours=round(
                            (current - target).total_seconds() / 3600, 3
                        ),
                    )
                )
        return sorted(due, key=lambda item: item.overdue_hours, reverse=True)


def _dimension_score(item: DimensionPerformance) -> float:
    raw = max(
        0.0,
        min(100.0, 50 + (item.average_relative_performance - 1.0) * 50),
    )
    return round(50 + (raw - 50) * item.confidence, 2)


def _latest_window(published_at: str, captured_at: str, fallback_hours: float) -> str:
    published = _parse_optional_time(published_at)
    if published is None:
        elapsed = fallback_hours
    else:
        elapsed = max(
            0.0,
            (_parse_time(captured_at) - published).total_seconds() / 3600,
        )
    available = [
        (label, hours) for label, hours in SNAPSHOT_WINDOWS.items() if elapsed >= hours * 0.8
    ]
    return available[-1][0] if available else "early"


def _duration_bucket(value: float | None) -> str:
    duration = float(value or 0.0)
    if duration <= 0:
        return "unknown"
    if duration <= 20:
        return "short"
    if duration <= 60:
        return "medium"
    return "long"


def _deduplicate_snapshots(
    snapshots: list[VideoMetricSnapshot],
) -> list[VideoMetricSnapshot]:
    unique: dict[str, VideoMetricSnapshot] = {}
    for snapshot in snapshots:
        unique[snapshot.captured_at] = snapshot
    return sorted(unique.values(), key=lambda value: _parse_time(value.captured_at))


def _parse_optional_time(value: str) -> datetime | None:
    return _parse_time(value) if value else None


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
