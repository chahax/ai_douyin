"""Performance snapshots and explainable next-cycle recommendations."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from statistics import median

from .models import (
    PerformanceResult,
    StrategyRecommendation,
    VideoMetricSnapshot,
)
from .repository import TrendRepository


class OperationsFeedbackService:
    def __init__(self, repository: TrendRepository | None = None):
        self.repository = repository or TrendRepository()

    def performance_results(self) -> list[PerformanceResult]:
        raw: list[tuple[object, list[VideoMetricSnapshot], float, float, int]] = []
        for context in self.repository.list_contexts():
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
            raw.append((context, snapshots, velocity, engagement_per_1k, views_gained))

        baseline = median([row[2] for row in raw]) if raw else 0.0
        results: list[PerformanceResult] = []
        for context, snapshots, velocity, engagement_per_1k, views_gained in raw:
            first, last = snapshots[0], snapshots[-1]
            hours = max(
                (_parse_time(last.captured_at) - _parse_time(first.captured_at)).total_seconds()
                / 3600,
                1 / 60,
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
                )
            )
        return sorted(results, key=lambda result: result.relative_performance, reverse=True)

    def recommend_next_cycle(self) -> StrategyRecommendation:
        results = self.performance_results()
        if len(results) < 3:
            return StrategyRecommendation(
                status="observing",
                sample_size=len(results),
                proven_topics=[],
                adjacent_topics=[],
                experiment_share=0.1,
                summary="有效复盘样本不足 3 条，继续采集多时点指标，不调整稳定策略。",
            )

        grouped: dict[str, list[PerformanceResult]] = defaultdict(list)
        for result in results:
            grouped[result.cluster_id or "unlinked"].append(result)
        scored = []
        for cluster_id, cluster_results in grouped.items():
            average_relative = sum(
                result.relative_performance for result in cluster_results
            ) / len(cluster_results)
            average_engagement = sum(
                result.engagement_per_1k for result in cluster_results
            ) / len(cluster_results)
            score = average_relative * 0.7 + min(2.0, average_engagement / 50) * 0.3
            scored.append((score, cluster_id, len(cluster_results)))
        scored.sort(reverse=True)
        proven = [cluster_id for _, cluster_id, count in scored if count >= 2][:3]
        if not proven and scored:
            proven = [scored[0][1]]
        adjacent = [cluster_id for _, cluster_id, _ in scored if cluster_id not in proven][:3]
        return StrategyRecommendation(
            status="ready",
            sample_size=len(results),
            proven_topics=proven,
            adjacent_topics=adjacent,
            experiment_share=0.1,
            summary=(
                "下一批建议按 70% 已验证题材、20% 相邻题材、10% 新实验分配；"
                "结论基于相对播放增速和每千次播放互动，而不是累计播放绝对值。"
            ),
        )


def _deduplicate_snapshots(
    snapshots: list[VideoMetricSnapshot],
) -> list[VideoMetricSnapshot]:
    unique: dict[str, VideoMetricSnapshot] = {}
    for snapshot in snapshots:
        unique[snapshot.captured_at] = snapshot
    return sorted(unique.values(), key=lambda value: _parse_time(value.captured_at))


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
