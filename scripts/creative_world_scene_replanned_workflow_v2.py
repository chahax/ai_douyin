"""Thin v4 source-state adapter over the frozen complete-replan workflow.

The continuation coordinator owns its original finite scope. No claim, provider
or output normalization is implemented here.
"""
from copy import deepcopy

from scripts import creative_world_scene_replanned_workflow_v1 as prior
from scripts import creative_world_scene_source_state_audit_v4 as state_audit

VERSION = "creative_world_scene_replanned_workflow/v2"


class ReviewWorkflow(prior.ReviewWorkflow):
    @staticmethod
    def prepare_source_state_audit_request(inputs, profile, goal, setup):
        dedicated = deepcopy(profile)
        dedicated.setdefault("stage_parameters", {}).setdefault("goal_audit", {})["max_completion_tokens"] = 32000
        result = state_audit.prepare(inputs, dedicated, goal, setup)
        result["coordinator_profile_projection"] = {"schema": VERSION + "/source_state_profile_projection",
            "caller_profile": deepcopy(profile), "caller_profile_sha256": prior.base.digest(profile),
            "effective_profile_sha256": prior.base.digest(dedicated), "source_state_only_output_cap_override": 32000,
            "other_stage_profile_modified": False}
        return result

    @staticmethod
    def validate_source_state_audit(native, prepared):
        views = prepared["views"]
        original = prepared["coordinator_profile_projection"]["caller_profile"]
        expected = ReviewWorkflow.prepare_source_state_audit_request(views["inputs"], original, views["goal"], views["setup"])
        if prepared != expected: raise ValueError("source-state v4 substage or complete request binding changed")
        pure = {key: value for key, value in prepared.items() if key != "coordinator_profile_projection"}
        return state_audit.validate(native, pure)

    def prepare_script_request(self, inputs, profile, goal, audit, **kwargs):
        # Parent dispatches self.validate_source_state_audit and therefore runs
        # the real v4 source gate. Only its explicit ancestry version label is
        # replaced here; neither native nor computed decision is rewritten.
        result = super().prepare_script_request(inputs, profile, goal, audit, **kwargs)
        result["manifest"]["replanned_workflow_version"] = VERSION
        result["manifest"]["source_state_admission_binding"]["source_state_audit_version"] = state_audit.VERSION
        result["request"]["input_provenance"]["source_state_audit_version"] = state_audit.VERSION
        return self.base._mark(result, inputs)
