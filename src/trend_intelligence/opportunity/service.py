"""Application service for opportunity ranking, approval, and A/B scripts."""

from __future__ import annotations

from src.operations_accounts import AccountProfile
from src.trend_intelligence.models import ContentOpportunity, OpportunityScript
from src.trend_intelligence.repository import TrendRepository

from .scoring import ContentOpportunityScorer
from .scripts import DomainScriptStrategyRegistry, default_script_registry


class ContentOpportunityService:
    def __init__(
        self,
        repository: TrendRepository,
        *,
        scorer: ContentOpportunityScorer | None = None,
        script_registry: DomainScriptStrategyRegistry | None = None,
    ):
        self.repository = repository
        self.scorer = scorer or ContentOpportunityScorer(repository)
        self.script_registry = script_registry or default_script_registry()

    def build_opportunities(
        self, profile: AccountProfile
    ) -> list[ContentOpportunity]:
        opportunities = self.scorer.build(profile)
        for item in opportunities:
            self.repository.save_opportunity(item)
        return opportunities

    def generate_scripts(
        self,
        profile: AccountProfile,
        opportunity_id: str,
        *,
        variants: tuple[str, ...] = ("A", "B"),
    ) -> list[OpportunityScript]:
        opportunity = self.repository.get_opportunity(opportunity_id)
        if opportunity is None:
            raise KeyError(f"unknown opportunity: {opportunity_id}")
        strategy = self.script_registry.resolve(profile)
        scripts = [
            strategy.build(profile, opportunity, variant_id=variant)
            for variant in variants
        ]
        for script in scripts:
            self.repository.save_opportunity_script(script)
        return scripts

    def approve_opportunity(self, opportunity_id: str) -> bool:
        return self.repository.update_opportunity_status(opportunity_id, "approved")

    def reject_opportunity(self, opportunity_id: str) -> bool:
        return self.repository.update_opportunity_status(opportunity_id, "rejected")

    def approve_script(self, script_id: str) -> bool:
        return self.repository.update_opportunity_script_status(script_id, "approved")

    def reject_script(self, script_id: str) -> bool:
        return self.repository.update_opportunity_script_status(script_id, "rejected")
