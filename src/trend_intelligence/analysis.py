"""Deterministic, explainable trend clustering and brief generation."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

from src.operations_accounts import AccountProfile

from .domain import (
    DomainStrategy,
    DomainStrategyRegistry,
    DomainTopicContext,
    get_default_domain_registry,
)
from .models import TrendBrief, TrendCluster, TrendObservation, utc_now_iso


GENERIC_HASHTAGS = {
    "抖音",
    "热门",
    "热点",
    "上热门",
    "法律",
    "普法",
    "知识",
    "推荐",
}
RISK_WORDS = {
    "必胜",
    "保证胜诉",
    "百分百",
    "内幕",
    "实锤",
    "曝光",
    "死亡",
    "自杀",
    "抓捕",
}
STOP_CHARS = set("的了是在和与及或就都也很把被让给有无这那你我他她它们一个怎么什么为什么")


def metric_to_number(value: str) -> int | None:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(万|亿)?\s*", value or "")
    if match is None:
        return None
    number = float(match.group(1))
    multiplier = {None: 1, "万": 10_000, "亿": 100_000_000}[match.group(2)]
    return round(number * multiplier)


def stable_item_id(*, video_id: str = "", url: str = "", title: str = "", author: str = "") -> str:
    if video_id and video_id.isdigit():
        return f"douyin:{video_id}"
    identity = "|".join((url.strip(), title.strip(), author.strip()))
    return "douyin:sha256:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


@dataclass(slots=True)
class _AggregatedItem:
    item_id: str
    title: str
    author: str
    observations: list[TrendObservation] = field(default_factory=list)
    keywords: set[str] = field(default_factory=set)
    sorts: set[str] = field(default_factory=set)
    best_rank: int = 20
    max_metric: int = 0
    sample_score: float = 0.0
    trend_score: float | None = None
    tokens: set[str] = field(default_factory=set)
    hashtags: set[str] = field(default_factory=set)


class TrendAnalyzer:
    def __init__(
        self,
        *,
        cluster_threshold: float = 0.2,
        domain_registry: DomainStrategyRegistry | None = None,
    ):
        if not 0 <= cluster_threshold <= 1:
            raise ValueError("cluster_threshold must be between 0 and 1")
        self.cluster_threshold = cluster_threshold
        self.domain_registry = domain_registry or get_default_domain_registry()

    def analyze(
        self,
        observations: Iterable[TrendObservation],
        *,
        preferred_topics: Iterable[str] = (),
        account_profile: AccountProfile | None = None,
    ) -> tuple[list[TrendCluster], list[TrendBrief]]:
        items = self._aggregate(list(observations))
        grouped = self._cluster(items)
        preferred = {value.strip().lower() for value in preferred_topics if value.strip()}
        strategy: DomainStrategy | None = None
        if account_profile is not None:
            strategy = self.domain_registry.resolve(account_profile)
            preferred.update(
                value.strip().lower()
                for value in account_profile.matching_terms()
                if value.strip()
            )
        clusters = [
            self._score_cluster(
                group,
                preferred,
                account_profile=account_profile,
                strategy=strategy,
            )
            for group in grouped
        ]
        clusters.sort(key=lambda cluster: cluster.selection_score, reverse=True)
        briefs = [
            self._build_brief(
                cluster,
                account_profile=account_profile,
                strategy=strategy,
            )
            for cluster in clusters
        ]
        return clusters, briefs

    def _aggregate(self, observations: list[TrendObservation]) -> list[_AggregatedItem]:
        grouped: dict[str, list[TrendObservation]] = defaultdict(list)
        for observation in observations:
            if observation.title.strip():
                grouped[observation.item_id].append(observation)

        items: list[_AggregatedItem] = []
        for item_id, rows in grouped.items():
            newest = max(rows, key=lambda row: row.collected_at)
            item = _AggregatedItem(
                item_id=item_id,
                title=newest.title.strip(),
                author=newest.author.strip(),
                observations=rows,
                keywords={
                    keyword.strip()
                    for row in rows
                    for keyword in (row.root_keywords or [row.keyword])
                    if keyword.strip()
                },
                sorts={row.sort_key for row in rows if row.sort_key},
                best_rank=min(max(1, row.rank) for row in rows),
                max_metric=max((row.metric_value or 0 for row in rows), default=0),
            )
            item.tokens = _title_tokens(item.title)
            item.hashtags = {
                tag
                for row in rows
                for tag in row.hashtags
                if tag
            } or _hashtags(item.title)
            item.sample_score = self._sample_score(item)
            item.trend_score = self._trend_score(rows)
            items.append(item)
        return sorted(items, key=lambda item: item.sample_score, reverse=True)

    @staticmethod
    def _sample_score(item: _AggregatedItem) -> float:
        rank_score = max(0.0, 1.0 - (item.best_rank - 1) / 20)
        metric_score = min(1.0, math.log10(item.max_metric + 1) / 6)
        sort_score = min(1.0, len(item.sorts) / 3)
        keyword_score = min(1.0, len(item.keywords) / 3)
        quality_score = sum(
            (
                0.35 if item.title else 0,
                0.25 if item.author else 0,
                0.4 if item.max_metric > 0 else 0,
            )
        )
        return round(
            100
            * (
                0.35 * rank_score
                + 0.25 * metric_score
                + 0.2 * sort_score
                + 0.1 * keyword_score
                + 0.1 * quality_score
            ),
            2,
        )

    @staticmethod
    def _trend_score(rows: list[TrendObservation]) -> float | None:
        by_run: dict[str, list[TrendObservation]] = defaultdict(list)
        for row in rows:
            run_key = row.run_id.strip()
            if run_key:
                by_run[run_key].append(row)
        if len(by_run) < 2:
            return None

        run_points: list[tuple[datetime, int, int]] = []
        for run_rows in by_run.values():
            captured = min(_parse_time(row.collected_at) for row in run_rows)
            metric = max((row.metric_value or 0 for row in run_rows), default=0)
            rank = min(max(1, row.rank) for row in run_rows)
            run_points.append((captured, metric, rank))
        run_points.sort(key=lambda value: value[0])
        first, last = run_points[0], run_points[-1]
        hours = max((last[0] - first[0]).total_seconds() / 3600, 1 / 60)
        metric_velocity = max(0.0, last[1] - first[1]) / hours
        metric_score = min(1.0, math.log10(metric_velocity + 1) / 5)
        rank_score = min(1.0, max(0, first[2] - last[2]) / 20)
        return round(100 * (0.6 * metric_score + 0.4 * rank_score), 2)

    def _cluster(self, items: list[_AggregatedItem]) -> list[list[_AggregatedItem]]:
        clusters: list[list[_AggregatedItem]] = []
        for item in items:
            best_index: int | None = None
            best_similarity = 0.0
            for index, cluster in enumerate(clusters):
                similarity = max(self._similarity(item, member) for member in cluster)
                if similarity > best_similarity:
                    best_index = index
                    best_similarity = similarity
            if best_index is not None and best_similarity >= self.cluster_threshold:
                clusters[best_index].append(item)
            else:
                clusters.append([item])
        return clusters

    @staticmethod
    def _similarity(left: _AggregatedItem, right: _AggregatedItem) -> float:
        shared_hashtags = (left.hashtags & right.hashtags) - GENERIC_HASHTAGS
        if shared_hashtags:
            return 1.0
        union = left.tokens | right.tokens
        token_similarity = len(left.tokens & right.tokens) / len(union) if union else 0.0
        keyword_bonus = 0.1 if left.keywords & right.keywords else 0.0
        return min(1.0, token_similarity + keyword_bonus)

    def _score_cluster(
        self,
        items: list[_AggregatedItem],
        preferred_topics: set[str],
        *,
        account_profile: AccountProfile | None,
        strategy: DomainStrategy | None,
    ) -> TrendCluster:
        item_ids = sorted(item.item_id for item in items)
        keywords = sorted({keyword for item in items for keyword in item.keywords})
        title = _cluster_title(items, keywords)
        identity_parts = list(item_ids)
        if account_profile is not None:
            identity_parts.extend(
                [
                    account_profile.account_uuid,
                    account_profile.domain_strategy_id,
                    account_profile.strategy_version,
                    str(account_profile.profile_version),
                ]
            )
        cluster_id = "cluster:" + hashlib.sha256(
            "|".join(identity_parts).encode("utf-8")
        ).hexdigest()[:20]
        top_sample_scores = sorted((item.sample_score for item in items), reverse=True)[:5]
        sample_score = sum(top_sample_scores) / max(1, len(top_sample_scores))
        trend_values = [item.trend_score for item in items if item.trend_score is not None]
        trend_score = sum(trend_values) / len(trend_values) if trend_values else None
        base_score = trend_score if trend_score is not None else sample_score
        topic_context = _domain_topic_context(title, keywords, items)
        strategy_evidence: dict[str, object] = {}
        if strategy is not None and account_profile is not None:
            fit_evidence = strategy.score_account_fit(account_profile, topic_context)
            account_fit = max(0.0, min(100.0, float(fit_evidence.score)))
            strategy_evidence = {"account_fit": fit_evidence.to_dict()}
        else:
            normalized_title = title.lower()
            account_fit = 100.0 if not preferred_topics or any(
                topic in normalized_title
                or any(topic in keyword.lower() for keyword in keywords)
                for topic in preferred_topics
            ) else 55.0
        demand = min(100.0, 35 + 15 * sum(len(item.sorts) for item in items) / len(items))
        unique_authors = len({item.author for item in items if item.author})
        originality = min(100.0, 55 + 10 * unique_authors)
        feasibility = 90.0 if all(len(item.title) <= 300 for item in items) else 70.0
        risk_count = sum(
            1 for risk in RISK_WORDS if any(risk in item.title for item in items)
        )
        risk_penalty = min(35.0, risk_count * 10.0)
        selection_score = (
            0.4 * base_score
            + 0.25 * account_fit
            + 0.15 * demand
            + 0.1 * originality
            + 0.1 * feasibility
            - risk_penalty
        )
        return TrendCluster(
            cluster_id=cluster_id,
            title=title,
            item_ids=item_ids,
            keywords=keywords,
            sample_count=len(items),
            sample_score=round(sample_score, 2),
            trend_score=round(trend_score, 2) if trend_score is not None else None,
            selection_score=round(max(0.0, min(100.0, selection_score)), 2),
            score_kind="trend" if trend_score is not None else "sample",
            score_breakdown={
                "base": round(base_score, 2),
                "account_fit": round(account_fit, 2),
                "demand": round(demand, 2),
                "originality": round(originality, 2),
                "feasibility": round(feasibility, 2),
                "risk_penalty": round(risk_penalty, 2),
            },
            representative_titles=[item.title for item in items[:5]],
            account_uuid=(account_profile.account_uuid if account_profile else ""),
            domain_strategy_id=(
                account_profile.domain_strategy_id if account_profile else ""
            ),
            strategy_version=(
                account_profile.strategy_version if account_profile else ""
            ),
            strategy_evidence=strategy_evidence,
        )

    @staticmethod
    def _build_brief(
        cluster: TrendCluster,
        *,
        account_profile: AccountProfile | None,
        strategy: DomainStrategy | None,
    ) -> TrendBrief:
        brief_identity = [cluster.cluster_id]
        if account_profile is not None:
            brief_identity.extend(
                [
                    account_profile.account_uuid,
                    account_profile.domain_strategy_id,
                    account_profile.strategy_version,
                    str(account_profile.profile_version),
                ]
            )
        brief_id = "brief:" + hashlib.sha256(
            "|".join(brief_identity).encode("utf-8")
        ).hexdigest()[:20]
        evidence = [
            f"样本量 {cluster.sample_count}，查询词：{', '.join(cluster.keywords) or '未标注'}",
            f"选题分 {cluster.selection_score:.1f}，依据类型：{cluster.score_kind}",
        ]
        evidence.extend(cluster.representative_titles[:3])
        source_scope = {
            "coverage": "authorized_visible_samples",
            "score_kind": cluster.score_kind,
            "sample_count": cluster.sample_count,
            "generated_at": utc_now_iso(),
        }
        if strategy is not None and account_profile is not None:
            topic_context = DomainTopicContext(
                title=cluster.title,
                keywords=list(cluster.keywords),
                representative_titles=list(cluster.representative_titles),
                sample_count=cluster.sample_count,
            )
            blueprint = strategy.build_brief_blueprint(
                account_profile,
                topic_context,
            )
            audience_questions = blueprint.audience_questions
            angles = blueprint.angles
            recommended_hook = blueprint.recommended_hook
            script_structure = blueprint.script_structure
            risks = list(blueprint.risks)
            source_scope.update(blueprint.source_scope)
            source_scope.update(
                {
                    "account_uuid": account_profile.account_uuid,
                    "account_key": account_profile.account_key,
                    "account_profile_version": account_profile.profile_version,
                    "domain_strategy_id": account_profile.domain_strategy_id,
                    "strategy_version": account_profile.strategy_version,
                    "strategy_evidence": cluster.strategy_evidence,
                }
            )
        else:
            audience_questions = [
                f"普通人在遇到“{cluster.title}”时最容易误解什么？",
                "需要提前保留哪些证据或完成哪些行动？",
                "哪些常见说法需要补充适用条件？",
            ]
            angles = [
                "普法解释：说明规则、例外和适用条件",
                "生活场景：用重新创作的日常冲突呈现问题",
                "行动清单：给出证据、沟通和求助步骤",
            ]
            recommended_hook = f"遇到{cluster.title}，很多人第一步就做错了。"
            script_structure = [
                "3秒问题或反常识开头",
                "生活场景与核心冲突",
                "规则、例外和事实核验提示",
                "三步行动清单",
                "非承诺式互动收尾",
            ]
            risks = [
                "热门样本只用于发现关注点，不作为法律事实或个案事实依据",
                "发布前需要核验法规时效、主体身份和关键事实",
                "避免复制代表样本文案、镜头或独特表达",
            ]
        if cluster.score_breakdown.get("risk_penalty", 0) > 0:
            risks.insert(0, "样本含高风险或确定性表达，需要人工复核")
        return TrendBrief(
            brief_id=brief_id,
            cluster_id=cluster.cluster_id,
            title=cluster.title,
            status="draft",
            score=cluster.selection_score,
            score_kind=cluster.score_kind,
            keywords=cluster.keywords,
            evidence=evidence,
            audience_questions=audience_questions,
            angles=angles,
            recommended_hook=recommended_hook,
            script_structure=script_structure,
            risks=risks,
            source_scope=source_scope,
            account_uuid=(account_profile.account_uuid if account_profile else ""),
            domain_strategy_id=(
                account_profile.domain_strategy_id if account_profile else ""
            ),
            strategy_version=(
                account_profile.strategy_version if account_profile else ""
            ),
        )


def _hashtags(title: str) -> set[str]:
    return {
        match.strip().lower()
        for match in re.findall(r"#([\w\u4e00-\u9fff]{2,24})", title or "")
        if match.strip()
    }


def _title_tokens(title: str) -> set[str]:
    normalized = re.sub(r"#[\w\u4e00-\u9fff]+", " ", (title or "").lower())
    english = set(re.findall(r"[a-z0-9]{2,}", normalized))
    chinese_chunks = re.findall(r"[\u4e00-\u9fff]{2,}", normalized)
    bigrams: set[str] = set()
    for chunk in chinese_chunks:
        for index in range(len(chunk) - 1):
            token = chunk[index : index + 2]
            if not all(char in STOP_CHARS for char in token):
                bigrams.add(token)
    return english | bigrams | _hashtags(title)


def _cluster_title(items: list[_AggregatedItem], keywords: list[str]) -> str:
    hashtag_counts = Counter(
        hashtag
        for item in items
        for hashtag in item.hashtags
        if hashtag not in GENERIC_HASHTAGS
    )
    if hashtag_counts:
        return hashtag_counts.most_common(1)[0][0]
    if keywords:
        return f"{keywords[0]}相关讨论"
    shortest = min((item.title for item in items), key=len, default="待命名话题")
    return shortest[:24]


def _domain_topic_context(
    title: str,
    keywords: list[str],
    items: list[_AggregatedItem],
) -> DomainTopicContext:
    return DomainTopicContext(
        title=title,
        keywords=list(keywords),
        representative_titles=[item.title for item in items[:5]],
        hashtags=sorted({tag for item in items for tag in item.hashtags}),
        sample_count=len(items),
    )


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
