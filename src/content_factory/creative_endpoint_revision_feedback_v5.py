"""Compact source-bound endpoint diagnostics, without selecting any new plan.

Failed native service documents, receipts and budgets stay untouched. This
adapter repairs the diagnostic interface only: frozen Runtime consumes .detail,
whereas the frozen endpoint compiler exposes .diagnostic.
"""
from copy import deepcopy

from . import creative_director_endpoint_contract_v4 as endpoint
from . import creative_complete_production_pipeline_v2 as ranges
from . import creative_production_revision_loop_v3 as loop
from . import creative_video_trial_contract_v1 as source

VERSION = "creative_endpoint_revision_feedback/v5"


class EndpointFeedbackError(ValueError):
    def __init__(self, code, message, detail=None):
        super().__init__(message)
        self.code = code
        self.detail = deepcopy(detail) if detail is not None else {"code": code}


def describe_endpoint_failure(native, script, manifest):
    """Recompute exact graph options; do not recover, select or mutate cuts."""
    original = deepcopy(native)
    audit = endpoint.audit_endpoint_choices(original, script, manifest)
    graph = ranges.candidate_graph(script, manifest)
    code, message = None, None
    try:
        endpoint.compile_direction(original, script, manifest)
    except endpoint.EndpointContractError as exc:
        if exc.diagnostic != audit:
            raise EndpointFeedbackError("ENDPOINT_DIAGNOSTIC_IDENTITY_CHANGED",
                "compiler diagnostic does not match the original native/source graph") from exc
        code, message = exc.code, str(exc)
    ordered = graph["source_refs"]
    edges = {(row["start_index"], row["end_index_exclusive"]): row for row in graph["ranges"]}
    invalid = []
    for row in audit["segments"]:
        if row["endpoint_strictly_advances"] and row["range_exists_in_actual_graph"] and row["budget_available"]:
            continue
        start = row["derived_start_index"]
        edge = edges.get((start, row["end_index_exclusive"]))
        floor = row["source_numeric_lower_bound"]
        legal = deepcopy(edge["budget_options"]) if edge else []
        outgoing = [{"end_source_ref": candidate["end_source_ref"],
            "source_lower_bound_seconds": candidate["source_lower_bound_seconds"],
            "budget_options": deepcopy(candidate["budget_options"]),
            "minimum_remaining_target_seconds": candidate["minimum_remaining_target_seconds"]}
            for candidate in graph["ranges"] if candidate["start_index"] == start]
        required_minimum = round(floor["source_lower_bound_seconds"]
            + ranges.BUDGET_TIERS["minimum"]["reaction_reserve_seconds"], 6)
        invalid.append({"segment_id": row["segment_id"],
            "derived_start_source_ref": ordered[start] if 0 <= start < len(ordered) else None,
            "derived_start_index": start, "selected_end_source_ref": row["end_source_ref"],
            "end_index_exclusive": row["end_index_exclusive"], "source_refs": deepcopy(row["source_refs"]),
            "endpoint_strictly_advances": row["endpoint_strictly_advances"],
            "range_exists_in_actual_graph": row["range_exists_in_actual_graph"],
            "requested_budget_tier": row["budget_tier"], "requested_budget_available": row["budget_available"],
            "source_lower_bound_seconds": floor["source_lower_bound_seconds"],
            "normal_dialogue_seconds": floor["normal_dialogue_seconds"],
            "minimum_nonadjacent_action_seconds": floor["minimum_nonadjacent_action_seconds"],
            "required_seconds_for_requested_tier": row["minimum_required_seconds_for_requested_tier"],
            "required_seconds_for_minimum_tier": required_minimum,
            "minimum_range_exceeds_provider_limit": required_minimum > source.MAX_SEGMENT_SECONDS,
            "provider_maximum_seconds": source.MAX_SEGMENT_SECONDS,
            "legal_budget_tiers_for_selected_range": [budget["budget_tier"] for budget in legal],
            "legal_budgets_for_selected_range": legal,
            "legal_outgoing_from_derived_start": outgoing,
            "options_enumerated_only": True, "automatic_option_selected": False})
    return {"schema": VERSION + "/diagnostic",
        "status": "endpoint_numeric_contract_failed" if code else "endpoint_numeric_contract_valid",
        "code": code, "validation_error": message,
        "native_sha256": source.digest(original), "script_sha256": source.digest(script),
        "global_manifest_sha256": source.digest(manifest),
        "candidate_graph_sha256": source.digest(graph),
        "invalid_segments": invalid,
        "global_constraints": {key: deepcopy(audit[key]) for key in
            ("all_endpoints_strictly_advance", "whole_source_coverage_complete", "missing_source_refs",
             "repeated_source_refs", "segment_count_meets_numeric_minimum", "numeric_plan_bounds",
             "total_target_seconds")},
        "budget_completion_flags": [{"segment_id": row["segment_id"],
            "numeric_completion_available_after_prefix": row["whole_budget_has_numeric_completion"]}
            for row in audit["segments"]],
        "action_overlap_is_numeric_lower_bound_only": True,
        "full_native_document_duplicated": False, "native_creative_values_changed": False,
        "automatic_option_selected": False, "semantic_action_feasibility_proven": False,
        "calls_authorized": False, "media_dispatch_allowed": False}


def wrap_endpoint_validator(validator, script, manifest):
    """Expose .detail for Runtime, only for the original endpoint error type."""
    frozen_script, frozen_manifest = deepcopy(script), deepcopy(manifest)
    def validate(native):
        original = deepcopy(native)
        try:
            return validator(deepcopy(original))
        except endpoint.EndpointContractError as exc:
            exact = endpoint.audit_endpoint_choices(original, frozen_script, frozen_manifest)
            if exc.diagnostic != exact:
                raise EndpointFeedbackError("ENDPOINT_DIAGNOSTIC_IDENTITY_CHANGED",
                    "endpoint error refers to a different native document/source input") from exc
            detail = describe_endpoint_failure(original, frozen_script, frozen_manifest)
            if detail["code"] != exc.code:
                raise EndpointFeedbackError("ENDPOINT_DIAGNOSTIC_CODE_CHANGED",
                    "endpoint failure code differs from exact source recomputation") from exc
            raise EndpointFeedbackError(exc.code, str(exc), detail) from exc
    return validate


def enrich_director_revision_input(feedback, script, manifest, *, result_evidence=None):
    """Add exact diagnostics to a known complete director-content correction.

    Caller supplies the original normalized evidence. This function cannot grant
    another candidate, convert prose to a native tool response, or infer source
    input from a failed plan. Local/window and full-review feedback are unchanged.
    """
    result = deepcopy(feedback)
    if type(result) is not dict or result.get("failure_code") != loop.DIRECTOR_FAILURE:
        return result
    evidence = deepcopy(result_evidence)
    if not isinstance(evidence, dict) or evidence.get("schema") != loop.VERSION + "/result_evidence":
        raise EndpointFeedbackError("ENDPOINT_KNOWN_RESULT_EVIDENCE_REQUIRED", "original normalized director result required")
    if (evidence.get("known_complete") is not True or evidence.get("usage_known") is not True
        or evidence.get("status") != "contract_rejected" or evidence.get("errors") != []
        or type(evidence.get("reported_tokens")) is not int or evidence["reported_tokens"] < 0):
        raise EndpointFeedbackError("ENDPOINT_RESULT_NOT_COMPLETE", "unknown or incomplete result is not eligible for content feedback")
    actual = evidence.get("actual_input")
    request = evidence.get("request")
    try:
        request_input = loop._strict_json(next(message["content"] for message in request["messages"]
            if message["role"] == "user"))
    except (KeyError, TypeError, ValueError, StopIteration):
        request_input = None
    if (not isinstance(actual, dict) or actual.get("full_current_script") != script
        or actual.get("shared_manifest") != manifest
        or source.digest(actual.get("full_current_script")) != source.digest(script)
        or source.digest(actual.get("shared_manifest")) != source.digest(manifest)
        or evidence.get("actual_input_sha256") != source.digest(actual)
        or request_input != actual or not isinstance(request, dict)
        or request.get("stage") != "whole_direction" or request.get("role") != "writer"):
        raise EndpointFeedbackError("ENDPOINT_SOURCE_INPUT_CHANGED", "director feedback differs from original actual source input")
    native = evidence.get("native_document")
    identity = result.get("original_result_identity")
    expected_identity = {key: deepcopy(evidence.get(key)) for key in
        ("result_id", "request_sha256", "native_sha256", "receipt_sha256", "reported_tokens")}
    if (not isinstance(native, dict) or evidence.get("native_sha256") != source.digest(native)
        or result.get("failed_complete_native_result") != native or identity != expected_identity
        or source.digest(result.get("failed_complete_native_result")) != source.digest(native)
        or source.digest(identity) != source.digest(expected_identity)
        or evidence.get("request_sha256") != source.digest(evidence.get("request"))):
        raise EndpointFeedbackError("ENDPOINT_NATIVE_RESULT_IDENTITY_CHANGED", "feedback does not match original complete native result identity")
    # DIRECTOR_FAILURE also includes ordinary schema/content errors. Preserve
    # their existing complete-draft route; only the actual endpoint exception
    # subtype qualifies for this interface adapter.
    try:
        endpoint.compile_direction(native, script, manifest)
    except endpoint.EndpointContractError:
        pass
    except (ValueError, KeyError, TypeError):
        return result
    else:
        return result
    detail = describe_endpoint_failure(native, script, manifest)
    previous = result.get("diagnostic")
    result["diagnostic"] = {"validation_error": detail["validation_error"],
        "endpoint_contract_diagnostic": detail,
        "previous_diagnostic_sha256": source.digest(previous),
        "original_result_identity": deepcopy(expected_identity),
        "source_input_sha256": evidence["actual_input_sha256"]}
    if (result.get("prior_complete_native_direction") == native
        and source.digest(result.get("prior_complete_native_direction")) == source.digest(native)):
        result.pop("prior_complete_native_direction")
        result["prior_complete_native_direction_sha256"] = source.digest(native)
        result["prior_direction_and_failed_result_are_same_native_identity"] = True
    result["endpoint_feedback_adapter"] = {
        "schema": VERSION, "known_complete_result_verified": True,
        "native_document_sha256": source.digest(native),
        "source_input_sha256": evidence["actual_input_sha256"],
        "full_native_result_kept_in_failed_field": True, "native_values_modified": False,
        "automatic_endpoint_or_budget_choice": False, "calls_authorized": False}
    return result
