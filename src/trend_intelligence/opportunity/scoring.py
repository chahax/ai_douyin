"""Explainable, account-scoped content-opportunity ranking."""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import datetime, timedelta, timezone
from statistics import mean

from src.operations_accounts import AccountProfile
from src.trend_intelligence.models import (
    ContentOpportunity,
    TrendBrief,
    TrendCluster,
    VideoContentAnalysis,
    VideoTrendSignal,
)
from src.trend_intelligence.repository import TrendRepository
from src.trend_intelligence.temporal import TemporalTrendService


class ContentOpportunityScorer:
    def __init__(self, repository: TrendRepository):
        self.repository = repository

    def build(
        self,
        profile: AccountProfile,
        *,
        now: datetime | None = None,
    ) -> list[ContentOpportunity]:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        clusters = [
            item
            for item in self.repository.list_clusters(limit=500)
            if item.account_uuid == profile.account_uuid
            and item.domain_strategy_id == profile.domain_strategy_id
            and item.strategy_version == profile.strategy_version
        ]
        briefs = {
            item.cluster_id: item
            for item in self.repository.list_briefs(limit=500)
            if item.account_uuid == profile.account_uuid
        }
        analyses = self.repository.list_content_analyses(
            account_uuid=profile.account_uuid, limit=100_000
        )
        latest_analysis: dict[str, VideoContentAnalysis] = {}
        for item in analyses:
            if item.profile_version == profile.profile_version:
                latest_analysis.setdefault(item.item_id, item)
        signals = {
            item.item_id: item
            for item in TemporalTrendService(self.repository).video_signals(
                window_days=14, limit=100_000
            )
        }
        opportunities = [
            self._score_one(
                cluster,
                briefs.get(cluster.cluster_id),
                profile,
                latest_analysis,
                signals,
                current,
            )
            for cluster in clusters
        ]
        return sorted(
            opportunities,
            key=lambda item: item.opportunity_score,
            reverse=True,
        )

    @staticmethod
    def _score_one(
        cluster: TrendCluster,
        brief: TrendBrief | None,
        profile: AccountProfile,
        analyses: dict[str, VideoContentAnalysis],
        signals: dict[str, VideoTrendSignal],
        now: datetime,
    ) -> ContentOpportunity:
        item_analyses = [
            analyses[item_id] for item_id in cluster.item_ids if item_id in analyses
        ]
        item_signals = [
            signals[item_id]
            for item_id in cluster.item_ids
            if item_id in signals and signals[item_id].direction != "insufficient"
        ]
        traffic = cluster.trend_score or cluster.sample_score
        if item_signals:
            temporal = _weighted_mean(
                [item.momentum_score for item in item_signals],
                [max(0.05, item.confidence) for item in item_signals],
            )
            temporal_confidence = mean(item.confidence for item in item_signals)
        else:
            temporal, temporal_confidence = 50.0, 0.0
        relevance_values = [
            item.relevance.score
            for item in item_analyses
            if item.relevance is not None
        ]
        relevance_weights = [
            max(0.05, item.relevance.confidence)
            for item in item_analyses
            if item.relevance is not None
        ]
        strategy_fit = (
            cluster.strategy_evidence.get("account_fit", {}).get("score", 50.0)
            if isinstance(cluster.strategy_evidence, dict)
            else 50.0
        )
        relevance = (
            _weighted_mean(relevance_values, relevance_weights)
            if relevance_values
            else float(strategy_fit)
        )
        content_confidence = (
            mean(
                (
                    0.9 if item.status == "completed" else 0.45
                )
                * (item.relevance.confidence if item.relevance else 0.5)
                for item in item_analyses
            )
            if item_analyses
            else 0.15
        )
        ages = [item.age_hours for item in item_signals if item.age_hours is not None]
        freshness = (
            mean(max(0.0, 100.0 - age / 72 * 100) for age in ages)
            if ages
            else 40.0
        )
        presentation = _mode(
            [item.presentation_type for item in item_analyses], "unknown"
        )
        hook = _mode([item.hook_type for item in item_analyses], "question")
        pacing = _mode([item.pacing for item in item_analyses], "balanced")
        saturation_penalty = min(25.0, max(0.0, (cluster.sample_count - 10) * 1.25))
        feasibility = 85.0
        if presentation in profile.forbidden_formats:
            feasibility = 20.0
        elif profile.allowed_formats and presentation not in profile.allowed_formats:
            feasibility = 65.0
        risk_penalty = float(cluster.score_breakdown.get("risk_penalty", 0.0))
        feedback_prior = 50.0
        score = (
            0.24 * traffic
            + 0.22 * temporal
            + 0.22 * relevance
            + 0.12 * content_confidence * 100
            + 0.1 * freshness
            + 0.1 * feasibility
            - 0.5 * saturation_penalty
            - risk_penalty
        )
        opportunity_id = "opportunity:" + hashlib.sha256(
            "|".join(
                (
                    profile.account_uuid,
                    str(profile.profile_version),
                    profile.domain_strategy_id,
                    profile.strategy_version,
                    cluster.cluster_id,
                )
            ).encode("utf-8")
        ).hexdigest()[:24]
        valid_hours = 48 if temporal_confidence >= 0.25 else 24 * 7
        topic_labels = _unique(
            [label for item in item_analyses for label in item.topic_labels]
            or cluster.keywords
        )
        user_intents = _unique(
            [intent for item in item_analyses for intent in item.user_intents]
        )
        selected = sorted(
            cluster.item_ids,
            key=lambda item_id: (
                signals[item_id].momentum_score if item_id in signals else 0.0,
                analyses[item_id].relevance.score
                if item_id in analyses and analyses[item_id].relevance
                else 0.0,
            ),
            reverse=True,
        )[:10]
        evidence = [
            f"流量基础分 {traffic:.1f}；视频动量 {temporal:.1f}（置信度 {temporal_confidence:.2f}）",
            f"账号内容相关度 {relevance:.1f}；内容证据完整度 {content_confidence:.2f}",
            f"建议展示方式 {presentation}，钩子 {hook}，节奏 {pacing}",
        ]
        if brief is not None:
            evidence.extend(brief.evidence[:3])
        evidence.extend(
            item.content_summary[:200]
            for item in item_analyses[:3]
            if item.content_summary
        )
        return ContentOpportunity(
            opportunity_id=opportunity_id,
            account_uuid=profile.account_uuid,
            account_key=profile.account_key,
            profile_version=profile.profile_version,
            domain_strategy_id=profile.domain_strategy_id,
            strategy_version=profile.strategy_version,
            cluster_id=cluster.cluster_id,
            brief_id=brief.brief_id if brief else "",
            title=cluster.title,
            status="candidate",
            opportunity_score=round(max(0.0, min(100.0, score)), 2),
            score_breakdown={
                "traffic": round(traffic, 2),
                "temporal_momentum": round(temporal, 2),
                "temporal_confidence": round(temporal_confidence, 3),
                "account_relevance": round(relevance, 2),
                "content_confidence": round(content_confidence * 100, 2),
                "freshness": round(freshness, 2),
                "feasibility": round(feasibility, 2),
                "feedback_prior": feedback_prior,
                "saturation_penalty": round(saturation_penalty, 2),
                "risk_penalty": round(risk_penalty, 2),
            },
            selected_item_ids=selected,
            recommended_presentation=presentation,
            recommended_hook_type=hook,
            recommended_pacing=pacing,
            recommended_duration_seconds=15.0,
            recommended_publish_window=(
                profile.publishing_windows[0] if profile.publishing_windows else "待测试"
            ),
            recommended_workflow_profile=profile.workflow_profile or "current_default",
            topic_labels=topic_labels,
            user_intents=user_intents,
            evidence=evidence,
            risks=list(brief.risks if brief else []),
            valid_from=now.isoformat(),
            valid_until=(now + timedelta(hours=valid_hours)).isoformat(),
            created_at=now.isoformat(),
        )


def _weighted_mean(values: list[float], weights: list[float]) -> float:
    total = sum(weights)
    return sum(value * weight for value, weight in zip(values, weights)) / max(
        total, 1e-9
    )


def _mode(values: list[str], default: str) -> str:
    normalized = [value for value in values if value and value != "unknown"]
    return Counter(normalized).most_common(1)[0][0] if normalized else default


def _unique(values: list[str]) -> list[str]:
    output: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized not in output:
            output.append(normalized)
    return output[:30]
