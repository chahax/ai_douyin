"""Account-specific opportunity ranking and domain script generation."""

from .scoring import ContentOpportunityScorer
from .scripts import (
    DomainScriptStrategy,
    DomainScriptStrategyRegistry,
    LegalOpportunityScriptStrategy,
    NovelOpportunityScriptStrategy,
    default_script_registry,
)
from .service import ContentOpportunityService

__all__ = [
    "ContentOpportunityScorer",
    "ContentOpportunityService",
    "DomainScriptStrategy",
    "DomainScriptStrategyRegistry",
    "LegalOpportunityScriptStrategy",
    "NovelOpportunityScriptStrategy",
    "default_script_registry",
]
