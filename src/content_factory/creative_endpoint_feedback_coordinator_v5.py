"""New subclass repairing only whole-direction endpoint diagnostic handoff.

Frozen v4 production code is inherited byte-for-byte. This subclass does not
change candidate claims, transport recovery, local acting or full review routes.
"""
from copy import deepcopy
import json

from .creative_complete_production_coordinator_v4 import (
    CompleteProductionCoordinator, DispatchGateError,
)
from . import creative_endpoint_revision_feedback_v5 as feedback_adapter
from . import creative_production_revision_loop_v3 as loop
from . import creative_video_trial_contract_v1 as source

VERSION = "creative_endpoint_feedback_coordinator/v5"


class EndpointFeedbackCoordinator(CompleteProductionCoordinator):
    def _terminal_prompt_context(self, terminal, state):
        summary, feedback = super()._terminal_prompt_context(terminal, state)
        if not isinstance(feedback, dict) or feedback.get("failure_code") != loop.DIRECTOR_FAILURE:
            return summary, feedback
        result_id = feedback.get("original_result_identity", {}).get("result_id")
        candidates = [event["result"] for event in state.get("director_events", [])
            if isinstance(event.get("result"), dict) and event["result"].get("result_id") == result_id]
        if not candidates or any(row != candidates[0] for row in candidates[1:]):
            raise DispatchGateError("ENDPOINT_ORIGINAL_RESULT_IDENTITY_REQUIRED")
        evidence = candidates[0]
        actual = evidence.get("actual_input")
        if not isinstance(actual, dict) or "full_current_script" not in actual or "shared_manifest" not in actual:
            raise DispatchGateError("ENDPOINT_SOURCE_CONTEXT_REQUIRED")
        try:
            enriched = feedback_adapter.enrich_director_revision_input(feedback,
                actual["full_current_script"], actual["shared_manifest"], result_evidence=evidence)
        except feedback_adapter.EndpointFeedbackError as exc:
            raise DispatchGateError(exc.code, exc.detail) from exc
        return summary, enriched

    def _call(self, label, request, validate, state, preflight=None):
        whole = request.get("stage") == "whole_direction"
        if whole:
            try:
                original_input = json.loads(request["messages"][1]["content"])
                script = deepcopy(original_input["full_current_script"])
                manifest = deepcopy(original_input["shared_manifest"])
            except (KeyError, TypeError, ValueError, IndexError) as exc:
                raise DispatchGateError("ENDPOINT_SOURCE_CONTEXT_REQUIRED") from exc
            actual_validate = feedback_adapter.wrap_endpoint_validator(validate, script, manifest)
        else:
            actual_validate = validate
        receipt, evidence = super()._call(label, request, actual_validate, state, preflight)
        if whole:
            self._endpoint_feedback_context = {
                "script": script, "manifest": manifest, "actual_input_sha256": source.digest(original_input),
                "request_sha256": source.digest(request), "evidence": deepcopy(evidence)}
        return receipt, evidence

    def _latest_revision_diagnostics(self, diagnostics, feedback):
        if isinstance(feedback, dict) and feedback.get("failure_code") == loop.DIRECTOR_FAILURE:
            context = getattr(self, "_endpoint_feedback_context", None)
            if context is None:
                raise DispatchGateError("ENDPOINT_SOURCE_CONTEXT_REQUIRED")
            evidence = context["evidence"]
            if (evidence.get("request_sha256") != context["request_sha256"]
                or evidence.get("actual_input_sha256") != context["actual_input_sha256"]):
                raise DispatchGateError("ENDPOINT_RESULT_SOURCE_CONTEXT_CHANGED")
            try:
                feedback = feedback_adapter.enrich_director_revision_input(feedback,
                    context["script"], context["manifest"], result_evidence=evidence)
            except feedback_adapter.EndpointFeedbackError as exc:
                raise DispatchGateError(exc.code, exc.detail) from exc
        return super()._latest_revision_diagnostics(diagnostics, feedback)
