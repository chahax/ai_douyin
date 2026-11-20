"""Explicit endpoint stage adapter; no frozen module is replaced or patched.

The model's endpoint document remains native. Only deterministic timing and
range projections enter the older local compiler. This module has no service
client and does not grant calls or approve any media.
"""
from copy import deepcopy

from . import creative_complete_production_pipeline_v3 as local
from . import creative_director_endpoint_contract_v4 as endpoint
from . import creative_video_trial_contract_v1 as source

VERSION = "creative_complete_production_pipeline/v4"
build_initial_state = local.build_initial_state
build_director_input = endpoint.build_director_input
whole_direction_schema = endpoint.whole_direction_schema
compile_direction = endpoint.compile_direction
build_performance_input = local.build_performance_input
performance_schema = local.performance_schema
compile_performance = local.compile_performance
PerformanceWindowExceeded = local.PerformanceWindowExceeded
render_prompt = local.render_prompt
digest = source.digest


def build_request(stage, inputs, schema, model):
    if stage == "whole_direction":
        script, manifest = inputs["full_current_script"], inputs["shared_manifest"]
        if schema != endpoint.whole_direction_schema(script, manifest):
            raise ValueError("endpoint stage schema differs from its exact source")
        request = endpoint.build_director_request(inputs, script, manifest, model)
        # The pure endpoint module builds previews. An injected runtime must
        # separately authorize dispatch; this adapter itself never grants it.
        for flag in ("preview_only", "dispatched", "calls_authorized"):
            request.pop(flag, None)
        request["dispatch_authorization_from_runtime_required"] = True
        request["native_contract_version"] = endpoint.VERSION
    else:
        request = local.build_request(stage, inputs, schema, model)
    request["operator_version"] = VERSION
    return request


def compile_complete(direction, performances, script, manifest, initial):
    endpoint.verify_compiled_direction(direction, script, manifest)
    result = local.compile_complete(direction["v2_direction_projection"], performances,
        script, manifest, initial)
    result.update(schema=VERSION + "/complete", direction=deepcopy(direction),
        endpoint_native_sha256=direction["native_sha256"],
        endpoint_mapping_sha256=direction["endpoint_mapping_sha256"],
        deterministic_range_projection_sha256=direction["v2_projection_sha256"],
        model_native_endpoint_preserved=True, manual_creative_patch_applied=False,
        actual_media_quality_passed=False)
    return result


def known_failure_diagnostic(result, script):
    """Keep a failed native format intact; never convert 517 into endpoints."""
    item = {"prior_complete_native_direction": deepcopy(result["native_document"]),
        "original_result_identity": {key: deepcopy(result[key]) for key in
            ("result_id", "request_sha256", "receipt_sha256", "reported_tokens")},
        "adopted": False}
    native = result["native_document"]
    rows = native.get("segments", [])
    if rows and all("end_source_ref" in row and "budget_tier" in row for row in rows):
        item["native_contract"] = endpoint.VERSION
        try:
            item["native_endpoint_diagnostic"] = endpoint.audit_endpoint_choices(native,
                script, result["actual_input"]["shared_manifest"])
        except ValueError as exc:
            item["native_endpoint_contract_error"] = str(exc)
    else:
        item["native_contract"] = "preserved_historical_non_endpoint_document"
        item["legacy_response_not_converted"] = True
    return item
