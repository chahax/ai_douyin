"""Application service for native trend collection and analysis."""

from __future__ import annotations

from src.operations_accounts import AccountProfile

from .analysis import TrendAnalyzer
from .collection import (
    AccountCollectionPlan,
    CollectionWave,
    PlannedCollectionBatch,
    TrendCollectionPlanner,
)
from .models import PublishedContentContext, VideoMetricSnapshot
from .models import ContentEvidence
from .content_analysis.classification import score_account_relevance
from .tag_graph import (
    build_keyword_tag_relations,
    build_tag_cooccurrence_relations,
    build_tag_traffic_snapshots,
)
from .providers.base import TrendCollectionRequest, TrendCollectionResult, TrendProvider
from .repository import TrendRepository
from .source_policy import SourcePolicy
from .sample_gate import batch_observations, require_sample


class TrendOperationsService:
    def __init__(
        self,
        repository: TrendRepository | None = None,
        analyzer: TrendAnalyzer | None = None,
        collection_planner: TrendCollectionPlanner | None = None,
    ):
        self.repository = repository or TrendRepository()
        self.analyzer = analyzer or TrendAnalyzer()
        self.collection_planner = collection_planner or TrendCollectionPlanner()

    def collect(
        self,
        provider: TrendProvider,
        request: TrendCollectionRequest,
        *,
        policy: SourcePolicy,
        account_profile: AccountProfile | None = None,
        plan: AccountCollectionPlan | None = None,
        batch: PlannedCollectionBatch | None = None,
    ) -> tuple[str | None, TrendCollectionResult]:
        result = provider.collect(request, policy=policy)
        if account_profile is not None and result.observations:
            original_count = len(result.observations)
            relevant = []
            for item in result.observations:
                relevance = score_account_relevance(
                    account_profile,
                    title=item.title,
                    hashtags=item.hashtags,
                    content_text=item.raw_text or item.title,
                    evidence=[
                        ContentEvidence(
                            channel="visible_metadata",
                            text=" ".join(
                                part
                                for part in (item.title, item.raw_text)
                                if part
                            )[:1500],
                            confidence=0.8,
                        )
                    ],
                )
                item.relevance_score = relevance.score
                item.relevance_terms = list(
                    dict.fromkeys(
                        relevance.matched_seed_keywords
                        + relevance.matched_profile_terms
                        + relevance.matched_topic_terms
                    )
                )
                if relevance.score >= 30 and not relevance.excluded_terms:
                    relevant.append(item)
            result.observations = relevant
            filtered_count = original_count - len(relevant)
            result.warnings.append(
                f"账号相关度预检：保留 {len(relevant)} 条，跳过 {filtered_count} 条不相关内容。"
            )
            self._rebuild_filtered_tag_graph(result, request)
        if not result.observations:
            return None, result
        run_id = self.repository.save_collection(
            result.observations,
            provider=provider.provider_id,
            keywords=request.keywords,
            warnings=result.warnings,
            tag_relations=result.tag_relations,
            tag_traffic_snapshots=result.tag_traffic_snapshots,
            account_uuid=(account_profile.account_uuid if account_profile else ""),
            profile_version=(account_profile.profile_version if account_profile else 0),
            domain_strategy_id=(
                account_profile.domain_strategy_id if account_profile else ""
            ),
            strategy_version=(
                account_profile.strategy_version if account_profile else ""
            ),
            plan_id=(plan.plan_id if plan else ""),
            batch_id=(batch.batch_id if batch else ""),
            wave_kind=(batch.wave_kind if batch else ""),
        )
        return run_id, result

    @staticmethod
    def _rebuild_filtered_tag_graph(
        result: TrendCollectionResult,
        request: TrendCollectionRequest,
    ) -> None:
        relations, roots_by_tag = build_keyword_tag_relations(
            result.observations,
            max_tags_per_keyword=request.max_related_tags_per_keyword,
            max_total_tags=request.max_total_related_tags,
        )
        observations_by_tag: dict[str, list] = {}
        for item in result.observations:
            if item.query_kind == "tag" and item.query_value:
                observations_by_tag.setdefault(item.query_value, []).append(item)
        result.tag_relations = relations + build_tag_cooccurrence_relations(
            observations_by_tag,
            roots_by_tag,
        )
        result.tag_traffic_snapshots = build_tag_traffic_snapshots(
            observations_by_tag,
            roots_by_tag,
            limit_per_sort=request.limit_per_sort,
        )

    def create_collection_plan(
        self,
        account_profile: AccountProfile,
        *,
        wave_kind: CollectionWave = "baseline",
        hot_keywords: list[str] | None = None,
    ) -> AccountCollectionPlan:
        plan = self.collection_planner.build(
            account_profile,
            wave_kind=wave_kind,
            hot_keywords=hot_keywords,
        )
        self.repository.save_collection_plan(plan)
        return plan

    def collect_plan_batch(
        self,
        provider: TrendProvider,
        plan: AccountCollectionPlan,
        batch_id: str,
        *,
        account_profile: AccountProfile,
        policy: SourcePolicy,
        headless: bool = False,
    ) -> tuple[str | None, TrendCollectionResult]:
        if plan.account_uuid != account_profile.account_uuid:
            raise ValueError("collection plan does not belong to account profile")
        if plan.profile_version != account_profile.profile_version:
            raise ValueError("collection plan profile version is stale")
        batch = next(
            (item for item in plan.batches if item.batch_id == batch_id), None
        )
        if batch is None:
            raise KeyError(f"unknown collection batch: {batch_id}")
        self.repository.save_collection_plan(plan)
        self.repository.update_collection_plan_status(plan.plan_id, "running")
        run_id, result = self.collect(
            provider,
            batch.to_request(headless=headless),
            policy=policy,
            account_profile=account_profile,
            plan=plan,
            batch=batch,
        )
        completed_batches = {
            str(item.get("batch_id") or "")
            for item in self.repository.list_collection_runs(plan_id=plan.plan_id)
        }
        if run_id:
            completed_batches.add(batch.batch_id)
        status = (
            "completed"
            if {item.batch_id for item in plan.batches}.issubset(completed_batches)
            else "partial"
        )
        self.repository.update_collection_plan_status(plan.plan_id, status)
        return run_id, result

    def pending_plan_batches(
        self, plan: AccountCollectionPlan
    ) -> list[PlannedCollectionBatch]:
        completed = {
            str(item.get("batch_id") or "")
            for item in self.repository.list_collection_runs(plan_id=plan.plan_id)
            if item.get("status") == "completed"
        }
        return [item for item in plan.batches if item.batch_id not in completed]

    def collection_plan_progress(
        self, plan: AccountCollectionPlan
    ) -> dict[str, int | str]:
        pending = self.pending_plan_batches(plan)
        total = len(plan.batches)
        completed = total - len(pending)
        return {
            "plan_id": plan.plan_id,
            "total_batches": total,
            "completed_batches": completed,
            "pending_batches": len(pending),
            "completion_percent": round(completed / max(1, total) * 100),
        }

    def analyze(
        self,
        *,
        preferred_topics: list[str] | None = None,
        account_profile: AccountProfile | None = None,
        limit: int = 2000,
        collection_run_id: str = "",
    ):
        observations = batch_observations(self.repository,
            limit=limit,
            run_id=collection_run_id,
            account_uuid=(account_profile.account_uuid if account_profile else ""),
        )
        require_sample(observations)
        clusters, briefs = self.analyzer.analyze(
            observations,
            preferred_topics=preferred_topics or [],
            account_profile=account_profile,
        )
        self.repository.save_analysis(clusters, briefs)
        return clusters, briefs

    def approve_brief(self, brief_id: str) -> bool:
        return self.repository.update_brief_status(brief_id, "approved")

    def reject_brief(self, brief_id: str) -> bool:
        return self.repository.update_brief_status(brief_id, "rejected")

    def link_published_content(self, context: PublishedContentContext) -> None:
        self.repository.link_published_content(context)

    def record_snapshot(self, snapshot: VideoMetricSnapshot) -> None:
        self.repository.record_video_snapshot(snapshot)
