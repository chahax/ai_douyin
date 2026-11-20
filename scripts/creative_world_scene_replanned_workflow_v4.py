"""Focused enactment and explicit native full-review v7 over frozen WF3."""
from scripts import creative_world_scene_replanned_workflow_v3 as prior
from scripts import creative_enacted_causality_audit_v1 as enacted
from src.content_factory import creative_full_review_protocol_v7 as full

VERSION = "creative_world_scene_replanned_workflow/v4"
REVIEW_BRIDGE_VERSION = VERSION + "/canonical_review_bridge"


class CanonicalReviewBridge(prior.CanonicalReviewBridge):
    VERSION = REVIEW_BRIDGE_VERSION
    BUNDLE_VERSION = full.BUNDLE_VERSION

    def prepare_full_review_part_request(self, inputs, profile, native, views, part):
        result = super().prepare_full_review_part_request(inputs, profile, native, views, part)
        return full.upgrade_prepared(result, inputs, views, part)

    def validate_part(self, document, part, script, brief, plan, legal_context, **options):
        try: compiled = prior.contract.recover_compiled(script, options["goal_contract"], brief)
        except (ValueError, KeyError, TypeError) as exc: return self._invalid(exc)
        result = full.validate_part(document, part, script, brief, plan, legal_context,
            checking_adapter=self.delegate, **options)
        decorated = self._decorate(result, compiled)
        decorated["canonical_review_bridge_version"] = REVIEW_BRIDGE_VERSION
        return decorated

    def build_review_bundle(self, native_semantic_review, native_physical_review):
        return full.build_review_bundle(native_semantic_review, native_physical_review)

    def validate_bundle(self, bundle, script, brief, plan, legal_context, **options):
        try: compiled = prior.contract.recover_compiled(script, options["goal_contract"], brief)
        except (ValueError, KeyError, TypeError) as exc: return self._invalid(exc)
        result = full.validate_bundle(bundle, script, brief, plan, legal_context,
            checking_adapter=self.delegate, **options)
        decorated = self._decorate(result, compiled)
        decorated["canonical_review_bridge_version"] = REVIEW_BRIDGE_VERSION
        return decorated


class ReviewWorkflow(prior.ReviewWorkflow):
    def full_reviews(self): return CanonicalReviewBridge(self.adapter)

    @staticmethod
    def prepare_enacted_causality_request(inputs, profile, native, views):
        return enacted.prepare(inputs, profile, native, views)

    @staticmethod
    def validate_enacted_causality(native, prepared):
        return enacted.validate(native, prepared)
