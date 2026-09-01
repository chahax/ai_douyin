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
from .providers.base import TrendCollectionRequest, TrendCollectionResult, TrendProvider
from .repository import TrendRepository
from .source_policy import SourcePolicy


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
    ):
        observations = self.repository.list_observations(limit=limit)
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
