"""Manual-switchable content-analysis implementation registry."""

from __future__ import annotations

from .base import ContentAnalysisProvider


class ContentAnalysisProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, ContentAnalysisProvider] = {}

    def register(
        self, provider: ContentAnalysisProvider, *, replace: bool = False
    ) -> None:
        provider_id = str(provider.provider_id or "").strip()
        if not provider_id:
            raise ValueError("content analysis provider_id is required")
        if provider_id in self._providers and not replace:
            raise ValueError(f"duplicate content analysis provider: {provider_id}")
        if int(provider.max_parallelism) < 1:
            raise ValueError("provider max_parallelism must be positive")
        self._providers[provider_id] = provider

    def get(self, provider_id: str) -> ContentAnalysisProvider:
        try:
            return self._providers[provider_id]
        except KeyError as exc:
            raise KeyError(f"unknown content analysis provider: {provider_id}") from exc

    def list_available(self) -> list[ContentAnalysisProvider]:
        return [self._providers[key] for key in sorted(self._providers)]
