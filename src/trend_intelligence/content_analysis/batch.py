"""Cached batch orchestration for content-analysis implementations."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

from src.trend_intelligence.models import (
    ContentAnalysisBatchResult,
    VideoContentAnalysis,
)
from src.trend_intelligence.repository import TrendRepository

from .base import ContentAnalysisRequest, stable_analysis_id
from .local import LocalQwenParaformerProvider
from .metadata import MetadataContentAnalysisProvider
from .registry import ContentAnalysisProviderRegistry
from .toolchain import LocalContentToolchain


class ContentAnalysisBatchService:
    def __init__(
        self,
        repository: TrendRepository,
        *,
        registry: ContentAnalysisProviderRegistry | None = None,
        toolchain: LocalContentToolchain | None = None,
        max_concurrency: int = 4,
    ):
        self.repository = repository
        self.registry = registry or _default_registry()
        self.toolchain = toolchain or LocalContentToolchain()
        self.max_concurrency = max(1, min(4, int(max_concurrency)))

    def analyze(
        self,
        requests: list[ContentAnalysisRequest],
        *,
        implementation_id: str = "metadata_heuristic",
        allow_metadata_fallback: bool = True,
        run_local_toolchain: bool = False,
    ) -> ContentAnalysisBatchResult:
        if not requests:
            raise ValueError("content analysis batch cannot be empty")
        accounts = {item.account_profile.account_uuid for item in requests}
        if len(accounts) != 1:
            raise ValueError("one content analysis batch must belong to one account")
        provider = self.registry.get(implementation_id)
        workers = min(
            self.max_concurrency,
            max(1, int(provider.max_parallelism)),
            len(requests),
        )

        def work(request: ContentAnalysisRequest):
            return self._analyze_one(
                request,
                implementation_id=implementation_id,
                allow_metadata_fallback=allow_metadata_fallback,
                run_local_toolchain=run_local_toolchain,
            )

        if workers == 1:
            outcomes = [work(request) for request in requests]
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                outcomes = list(executor.map(work, requests))
        analyses = [item[0] for item in outcomes if item[0] is not None]
        errors = [item[2] for item in outcomes if item[2]]
        result = ContentAnalysisBatchResult(
            batch_id=f"content-batch:{uuid.uuid4().hex}",
            implementation_id=implementation_id,
            account_uuid=next(iter(accounts)),
            requested_count=len(requests),
            completed_count=sum(item.status == "completed" for item in analyses),
            degraded_count=sum(item.status == "degraded" for item in analyses),
            failed_count=sum(item[0] is None for item in outcomes),
            cached_count=sum(item[1] for item in outcomes),
            analyses=analyses,
            errors=errors,
        )
        self.repository.save_content_analysis_batch(result)
        return result

    def _analyze_one(
        self,
        request: ContentAnalysisRequest,
        *,
        implementation_id: str,
        allow_metadata_fallback: bool,
        run_local_toolchain: bool,
    ) -> tuple[VideoContentAnalysis | None, bool, str]:
        provider = self.registry.get(implementation_id)
        active_request = request
        try:
            if (
                implementation_id == "local_qwen_paraformer"
                and run_local_toolchain
                and request.local_video_path
                and not request.qwen_analysis_path
                and not request.transcript_path
            ):
                active_request = self.toolchain.prepare_request(request)
            analysis_id = stable_analysis_id(
                active_request,
                provider_id=provider.provider_id,
                provider_version=provider.provider_version,
            )
            cached = self.repository.get_content_analysis(analysis_id)
            if cached is not None:
                return cached, True, ""
            analysis = provider.analyze(active_request)
            self.repository.save_content_analysis(analysis)
            return analysis, False, ""
        except Exception as exc:
            message = f"{request.item_id}: {type(exc).__name__}: {exc}"
            if not allow_metadata_fallback or implementation_id == "metadata_heuristic":
                return None, False, message
            fallback_request = replace(
                request,
                media_access_mode="metadata_only",
                local_video_path="",
                qwen_analysis_path="",
                transcript_path="",
                scene_alignment_path="",
            )
            fallback = self.registry.get("metadata_heuristic")
            analysis_id = stable_analysis_id(
                fallback_request,
                provider_id=fallback.provider_id,
                provider_version=fallback.provider_version,
            )
            cached = self.repository.get_content_analysis(analysis_id)
            if cached is not None:
                return cached, True, message
            analysis = fallback.analyze(fallback_request)
            self.repository.save_content_analysis(analysis)
            return analysis, False, message


def _default_registry() -> ContentAnalysisProviderRegistry:
    registry = ContentAnalysisProviderRegistry()
    registry.register(MetadataContentAnalysisProvider())
    registry.register(LocalQwenParaformerProvider())
    return registry
