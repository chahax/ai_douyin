"""Built-in and pluggable domain strategies."""

from __future__ import annotations

from functools import lru_cache

from .base import (
    AccountFitEvidence,
    DomainBriefBlueprint,
    DomainQueryPlan,
    DomainStrategy,
    DomainStrategyConfigError,
    DomainTopicContext,
    PydanticDomainStrategy,
)
from .legal import LegalServicesStrategy
from .novel import NovelPromotionStrategy
from .registry import (
    DomainStrategyRegistry,
    DomainStrategySpec,
    register_many,
)


@lru_cache(maxsize=1)
def get_default_domain_registry() -> DomainStrategyRegistry:
    return register_many(
        DomainStrategyRegistry(),
        [LegalServicesStrategy(), NovelPromotionStrategy()],
    )


__all__ = [
    "AccountFitEvidence",
    "DomainBriefBlueprint",
    "DomainQueryPlan",
    "DomainStrategy",
    "DomainStrategyConfigError",
    "DomainStrategyRegistry",
    "DomainStrategySpec",
    "DomainTopicContext",
    "LegalServicesStrategy",
    "NovelPromotionStrategy",
    "PydanticDomainStrategy",
    "get_default_domain_registry",
    "register_many",
]
