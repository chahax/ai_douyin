"""Application service for native trend collection and analysis."""

from __future__ import annotations

from src.operations_accounts import AccountProfile

from .analysis import TrendAnalyzer
from .models import PublishedContentContext, VideoMetricSnapshot
from .providers.base import TrendCollectionRequest, TrendCollectionResult, TrendProvider
from .repository import TrendRepository
from .source_policy import SourcePolicy


class TrendOperationsService:
    def __init__(
        self,
        repository: TrendRepository | None = None,
        analyzer: TrendAnalyzer | None = None,
    ):
        self.repository = repository or TrendRepository()
        self.analyzer = analyzer or TrendAnalyzer()

    def collect(
        self,
        provider: TrendProvider,
        request: TrendCollectionRequest,
        *,
        policy: SourcePolicy,
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
        )
        return run_id, result

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
