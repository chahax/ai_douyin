"""Pure orchestration policy for whole-director revision and native reuse.

No function dispatches a provider request, repairs creative values, approves a
video, or changes a historical receipt. A runner must persist returned states
before dispatch. Counts belong to the inherited source scope, not a directory.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
import re

from .creative_video_trial_contract_v1 import digest
from . import creative_complete_production_pipeline_v1 as local_contract

VERSION = "creative_production_revision_loop/v3"
WINDOW_FAILURE = "LOCAL_PERFORMANCE_WINDOW_EXCEEDED"
REVIEW_FAILURE = "FULL_PRODUCTION_REVIEW_FAILED"
DIRECTOR_FAILURE = "WHOLE_DIRECTION_CONTRACT_INVALID"
_SHA = re.compile(r"^[0-9a-f]{64}$")


def _strict_json(text):
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    return json.loads(text, object_pairs_hook=pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def normalize_receipt(receipt, expected_request=None):
    """Extract original tool output only; ordinary prose is never converted.

    This checks the available receipt's internal bindings. Persistence/frozen
    file authenticity remains the runner's responsibility. Rejected contracts
    can be complete known results; a successful HTTP code alone cannot be one.
    """
    row = deepcopy(receipt)
    request = row.get("request")
    metadata = row.get("response_metadata", {})
    errors = []
    if not isinstance(request, dict) or row.get("request_sha256") != digest(request):
        errors.append("REQUEST_IDENTITY_INVALID")
    if expected_request is not None and request != expected_request:
        errors.append("REQUEST_CHANGED")
    source_sha = row.get("source_binding_sha256")
    if not isinstance(source_sha, str) or not _SHA.fullmatch(source_sha):
        errors.append("SOURCE_IDENTITY_INVALID")
    status_code = metadata.get("http_status_code")
    if type(status_code) is not int or not 200 <= status_code < 300:
        errors.append("HTTP_RESULT_UNKNOWN_OR_REJECTED")
    if metadata.get("response_body_complete") is not True:
        errors.append("RESPONSE_INCOMPLETE")
    if metadata.get("finish_reason") not in ("tool_calls", "stop"):
        errors.append("RESPONSE_NOT_FINISHED")
    if not isinstance(metadata.get("raw_body_sha256"), str) or not _SHA.fullmatch(metadata["raw_body_sha256"]):
        errors.append("ORIGINAL_RESPONSE_EVIDENCE_MISSING")
    payload = row.get("response_payload", {})
    usage = payload.get("usage", {}) if isinstance(payload, dict) else {}
    total = metadata.get("total_tokens")
    usage_known = type(total) is int and total >= 0 and usage.get("total_tokens") == total
    for field in ("prompt_tokens", "completion_tokens"):
        if field in metadata and (type(metadata[field]) is not int or metadata[field] < 0):
            usage_known = False
        if field in usage and (type(usage[field]) is not int or usage[field] < 0):
            usage_known = False
        if field in usage and field in metadata and usage[field] != metadata[field]:
            usage_known = False
    if not usage_known:
        errors.append("USAGE_UNKNOWN")
    native = None
    try:
        choices = payload["choices"]
        if len(choices) != 1 or choices[0].get("finish_reason") != metadata.get("finish_reason"):
            raise ValueError("one finished response required")
        calls = choices[0]["message"].get("tool_calls", [])
        expected_tool = (request or {}).get("structured_schema", {}).get("title") or "submit_creative_json"
        if len(calls) != 1 or calls[0].get("type") != "function" or calls[0]["function"].get("name") != expected_tool:
            errors.append("REQUIRED_TOOL_MISSING")
        else:
            outer = _strict_json(calls[0]["function"]["arguments"])
            if not isinstance(outer, dict) or outer != row.get("output"):
                raise ValueError("wire output does not equal stored original output")
            if (request or {}).get("output_transport") == "creative_json_document_transport/v1":
                if set(outer) != {"payload_json"} or not isinstance(outer["payload_json"], str):
                    raise ValueError("complete native JSON-string document required")
                native = _strict_json(outer["payload_json"])
                if row.get("document_output") is not None and native != row["document_output"]:
                    raise ValueError("stored document differs from original payload")
            else:
                native = deepcopy(outer)
            if not isinstance(native, dict):
                raise ValueError("native document must be a JSON object")
            if native.get("availability") == "unknown":
                errors.append("NATIVE_AVAILABILITY_UNKNOWN")
    except (KeyError, TypeError, ValueError, AttributeError):
        errors.append("NATIVE_DOCUMENT_INCOMPLETE_OR_CHANGED")
        native = None
    actual_input = None
    try:
        users = [message for message in request["messages"] if message["role"] == "user"]
        actual_input = _strict_json(users[0]["content"])
        if not isinstance(actual_input, dict):
            raise ValueError("stage input must be an object")
    except (KeyError, IndexError, TypeError, ValueError):
        errors.append("ACTUAL_INPUT_EVIDENCE_MISSING")
    return {"schema": VERSION + "/result_evidence", "result_id": str(row.get("ordinal", metadata.get("response_id", ""))),
        "stage": row.get("label"), "status": row.get("status"),
        "known_complete": not errors, "usage_known": usage_known,
        "reported_tokens": total if usage_known else None,
        "source_binding_sha256": source_sha, "request_sha256": row.get("request_sha256"),
        "actual_input": actual_input, "actual_input_sha256": digest(actual_input) if actual_input is not None else None,
        "request": request, "native_document": native,
        "native_sha256": digest(native) if native is not None else None,
        "receipt_sha256": digest(row), "errors": list(dict.fromkeys(errors)),
        "original_output_preserved": True, "ordinary_body_adopted": False,
        "automatic_transport_retry": False}


def initial_loop_state(inherited_director_attempts, source_binding_sha256=None, default_limit=3, stable_scope_material=None):
    """Carry all original attempts, including unresolved/unknown dispatched ones."""
    if type(default_limit) is not int or default_limit < 0:
        raise ValueError("nonnegative original candidate cap required")
    evidence = [normalize_receipt(row) if row.get("schema") != VERSION + "/result_evidence" else deepcopy(row)
        for row in inherited_director_attempts]
    ids = [row["result_id"] for row in evidence]
    if any(not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError("original dispatched candidate identities must be unique")
    bindings = {row["source_binding_sha256"] for row in evidence}
    if source_binding_sha256 is None and len(bindings) == 1:
        source_binding_sha256 = next(iter(bindings))
    if not isinstance(source_binding_sha256, str) or not _SHA.fullmatch(source_binding_sha256):
        raise ValueError("inherited immutable source binding required")
    if bindings and bindings != {source_binding_sha256}:
        raise ValueError("inherited candidate scope differs")
    scope_keys = ("full_current_script", "shared_manifest", "planned_initial_state")
    derived = [{key: deepcopy(row["actual_input"][key]) for key in scope_keys} for row in evidence
        if isinstance(row.get("actual_input"), dict) and all(key in row["actual_input"] for key in scope_keys)]
    if stable_scope_material is None and derived:
        stable_scope_material = derived[0]
    if derived and any(row != stable_scope_material for row in derived):
        raise ValueError("inherited complete creative source scope changed")
    if stable_scope_material is not None and set(stable_scope_material) != set(scope_keys):
        raise ValueError("stable scope must bind full source, shared manifest and original planned initial state")
    return {"schema": VERSION + "/state", "source_binding_sha256": source_binding_sha256,
        "stable_scope_material": deepcopy(stable_scope_material),
        "stable_scope_sha256": digest(stable_scope_material) if stable_scope_material is not None else None,
        "successor_source_bindings": [],
        "original_candidate_limit": default_limit, "additional_candidate_grants": [],
        "director_events": [{"event": "inherited_result", "result": row} for row in evidence],
        "budget_reset": False, "history_preserved": True, "automatic_transport_retry": False}


def register_successor_binding(state, new_source_binding_sha256, stable_scope_material, parent_state_sha256):
    """Record a new code freeze inheriting the exact original creative scope.

    This is not an authorization or counter reset. The runner must independently
    verify both frozen files and persist this successor proof before dispatch.
    """
    if (not isinstance(new_source_binding_sha256, str) or not _SHA.fullmatch(new_source_binding_sha256)
        or state["stable_scope_material"] is None or stable_scope_material != state["stable_scope_material"]):
        raise ValueError("successor code freeze must preserve complete stable creative scope")
    result = deepcopy(state)
    existing = [row for row in state["successor_source_bindings"] if row["source_binding_sha256"] == new_source_binding_sha256]
    if existing:
        if existing[0]["stable_scope_sha256"] != digest(stable_scope_material):
            raise ValueError("successor binding changed its original scope")
        return result
    if parent_state_sha256 != digest(state):
        raise ValueError("successor must bind the complete current inherited history")
    if new_source_binding_sha256 == state["source_binding_sha256"]:
        raise ValueError("successor binding must identify a new code freeze")
    result["successor_source_bindings"].append({"source_binding_sha256": new_source_binding_sha256,
        "stable_scope_sha256": state["stable_scope_sha256"], "parent_state_sha256": parent_state_sha256,
        "authorization_added": False, "budget_reset": False})
    return result


def _compatible_evidence(state, evidence):
    allowed = {state["source_binding_sha256"], *[row["source_binding_sha256"] for row in state["successor_source_bindings"]]}
    if evidence["source_binding_sha256"] not in allowed:
        return False
    scope = state["stable_scope_material"]
    inp = evidence.get("actual_input")
    # A current local state differs from the frozen film initial state by design.
    # Native recompile verifies that state prefix. Fixed source/manifest must
    # still match, including for an explicitly recorded successor code freeze.
    if scope is not None and isinstance(inp, dict):
        if "shared_manifest" not in inp or inp["shared_manifest"] != scope["shared_manifest"]:
            return False
        if "full_current_script" in inp and inp["full_current_script"] != scope["full_current_script"]:
            return False
        if (evidence.get("stage") or "").startswith("whole_direction"):
            if any(inp.get(key) != value for key, value in scope.items()):
                return False
    elif evidence["source_binding_sha256"] != state["source_binding_sha256"]:
        return False
    return True


def _attempts(state):
    identities = set()
    unresolved = set()
    for event in state["director_events"]:
        if event["event"] == "claim":
            identities.add(event["request_identity"])
            unresolved.add(event["request_identity"])
        else:
            key = event.get("request_identity") or "original:" + event["result"]["result_id"]
            identities.add(key)
            unresolved.discard(key)
    return identities, unresolved


def candidate_capacity(state):
    identities, unresolved = _attempts(state)
    limit = state["original_candidate_limit"] + sum(row["additional_candidates"] for row in state["additional_candidate_grants"])
    return {"attempts_including_claims": len(identities), "candidate_limit": limit,
        "remaining": max(0, limit - len(identities)), "unresolved_claims": sorted(unresolved),
        "unresolved_result_ids": [event["result"]["result_id"] for event in state["director_events"]
            if event["event"] != "claim" and not event["result"]["known_complete"]],
        "historical_attempts_exceed_limit": len(identities) > limit, "budget_reset": False}


def authorize_extra_candidate(state, explicit_user_grant):
    """Apply explicit external human evidence, never infer it from 'continue'."""
    grant = deepcopy(explicit_user_grant)
    if (grant.get("authority") != "explicit_user" or not grant.get("grant_id") or not grant.get("user_quote")
        or type(grant.get("additional_candidates")) is not int or grant["additional_candidates"] < 1
        or grant.get("source_binding_sha256") != state["source_binding_sha256"]):
        raise ValueError("explicit scope-bound additional-candidate authorization required")
    result = deepcopy(state)
    matching = [row for row in result["additional_candidate_grants"] if row["grant_id"] == grant["grant_id"]]
    if matching:
        if matching != [grant]:
            raise ValueError("same grant identity changed; allowance cannot be renewed")
        return result
    result["additional_candidate_grants"].append(grant)
    return result


def claim_director_request(state, request_identity):
    """Persist this claim before invoking a service; restart cannot redispatch."""
    if not isinstance(request_identity, str) or not request_identity:
        raise ValueError("new immutable request identity required")
    capacity = candidate_capacity(state)
    identities, _ = _attempts(state)
    if request_identity in identities:
        raise ValueError("director request already claimed; query original identity only")
    if capacity["unresolved_claims"]:
        raise ValueError("original director result unresolved; no new dispatch")
    if capacity["unresolved_result_ids"]:
        raise ValueError("original director result or usage unknown; no new dispatch")
    if not capacity["remaining"]:
        raise ValueError("inherited director candidate allowance exhausted")
    result = deepcopy(state)
    result["director_events"].append({"event": "claim", "request_identity": request_identity})
    return result


def register_director_result(state, result_evidence, request_identity=None):
    """Append even unknown/rejected spent attempts; never give their slot back."""
    evidence = (normalize_receipt(result_evidence) if result_evidence.get("schema") != VERSION + "/result_evidence"
        else deepcopy(result_evidence))
    if not _compatible_evidence(state, evidence) or not evidence["result_id"]:
        raise ValueError("director result source or original identity changed")
    result = deepcopy(state)
    prior = [event for event in result["director_events"] if event["event"] != "claim"
        and event["result"]["result_id"] == evidence["result_id"]]
    event = {"event": "result", "request_identity": request_identity, "result": evidence}
    if prior:
        if prior[0]["result"] != evidence or prior[0].get("request_identity") != request_identity:
            raise ValueError("original result changed; preserve immutable evidence")
        return result
    if request_identity is not None:
        _, pending = _attempts(state)
        if request_identity not in pending:
            raise ValueError("result must resolve its already persisted request claim")
    result["director_events"].append(event)
    return result


def route_failure(state, failure_code, result_evidence, prior_native_direction,
                  failed_native_performance=None, diagnostic=None):
    """Return a full director revision input or a stop; never select new cuts."""
    evidence = (normalize_receipt(result_evidence) if result_evidence.get("schema") != VERSION + "/result_evidence"
        else deepcopy(result_evidence))
    base = {"schema": VERSION + "/failure_route", "failure_code": failure_code,
        "action": "stop", "dispatch_allowed": False, "source_binding_sha256": state["source_binding_sha256"],
        "capacity": candidate_capacity(state), "original_result_id": evidence["result_id"],
        "complete_original_evidence_preserved": True, "manual_cut_or_duration_patch_allowed": False,
        "local_acceleration_revision_allowed": False, "automatic_transport_retry": False,
        "full_production_review_invalidated": True}
    if not _compatible_evidence(state, evidence):
        return {**base, "reason": "SOURCE_IDENTITY_CHANGED"}
    if not evidence["known_complete"]:
        return {**base, "reason": "RESULT_OR_USAGE_NOT_COMPLETE", "evidence_errors": evidence["errors"]}
    if failure_code not in (WINDOW_FAILURE, REVIEW_FAILURE, DIRECTOR_FAILURE):
        return {**base, "reason": "FAILURE_NOT_ELIGIBLE_FOR_WHOLE_DIRECTION_REVISION"}
    native = evidence["native_document"]
    if failure_code == WINDOW_FAILURE and native != failed_native_performance:
        return {**base, "reason": "FAILED_LOCAL_NATIVE_CHANGED"}
    if failure_code == WINDOW_FAILURE:
        try:
            if (diagnostic["code"] != WINDOW_FAILURE or diagnostic["complete_native_performance"] != native
                or diagnostic["native_sha256"] != digest(native) or not diagnostic["normal_schedule"]):
                raise ValueError("typed native window evidence missing")
            for key in ("target_seconds", "required_seconds", "provider_maximum_seconds", "excess_seconds"):
                if type(diagnostic[key]) not in (int, float) or not math.isfinite(diagnostic[key]):
                    raise ValueError("finite window numbers required")
            limit = min(diagnostic["target_seconds"], diagnostic["provider_maximum_seconds"])
            if (diagnostic["provider_maximum_seconds"] != 15 or diagnostic["required_seconds"] <= limit + 1e-6
                or diagnostic["excess_seconds"] <= 0
                or abs(diagnostic["excess_seconds"] - (diagnostic["required_seconds"] - limit)) > 1e-6):
                raise ValueError("actual normal schedule must exceed unchanged window")
            current = evidence["actual_input"].get("current_sources")
            if current is None:
                script = evidence["actual_input"]["full_current_script"]
                bank = local_contract.source.catalog(script)
                current = {ref: bank[ref] for ref in diagnostic["source_refs"]}
            schedule, elapsed, total = local_contract._compile_schedule(native, current)
            if (schedule != diagnostic["normal_schedule"] or abs(total - diagnostic["required_seconds"]) > 1e-6
                or abs(elapsed - diagnostic["source_seconds"]) > 1e-6
                or list(current) != diagnostic["source_refs"]):
                raise ValueError("window diagnostic differs from original native normal schedule")
        except (KeyError, TypeError, ValueError, AttributeError):
            return {**base, "reason": "LOCAL_WINDOW_DIAGNOSTIC_NOT_VERIFIED"}
    if failure_code == DIRECTOR_FAILURE and native != prior_native_direction:
        return {**base, "reason": "FAILED_DIRECTOR_NATIVE_CHANGED"}
    if failure_code == REVIEW_FAILURE:
        checks = native.get("checks", [])
        if (not checks or any(row.get("status") not in ("pass", "fail") for row in checks)
            or not any(row.get("status") == "fail" for row in checks) or not native.get("revision_requirements")):
            return {**base, "reason": "FULL_REVIEW_NOT_KNOWN_EXPLICIT_FAILURE"}
    if base["capacity"]["unresolved_claims"]:
        return {**base, "reason": "ORIGINAL_DIRECTOR_RESULT_UNRESOLVED"}
    if base["capacity"]["unresolved_result_ids"]:
        return {**base, "reason": "ORIGINAL_DIRECTOR_RESULT_OR_USAGE_UNKNOWN"}
    if not base["capacity"]["remaining"]:
        return {**base, "reason": "INHERITED_DIRECTOR_ALLOWANCE_EXHAUSTED"}
    if not isinstance(prior_native_direction, dict):
        return {**base, "reason": "COMPLETE_PRIOR_DIRECTOR_REQUIRED"}
    if failure_code in (WINDOW_FAILURE, REVIEW_FAILURE):
        results = [event["result"] for event in state["director_events"] if event["event"] != "claim"]
        if (not results or results[-1]["status"] != "contract_valid" or not results[-1]["known_complete"]
            or results[-1]["native_document"] != prior_native_direction):
            return {**base, "reason": "PRIOR_DIRECTOR_NOT_CURRENT_VALID_NATIVE"}
    feedback = {"revision_kind": "complete_native_whole_direction",
        "failure_code": failure_code, "prior_complete_native_direction": deepcopy(prior_native_direction),
        "failed_complete_native_result": deepcopy(native), "diagnostic": deepcopy(diagnostic),
        "original_result_identity": {key: deepcopy(evidence[key]) for key in (
            "result_id", "request_sha256", "native_sha256", "receipt_sha256", "reported_tokens")},
        "instruction": "提交完整新的原生整片导演计划；保留全文与共用初态，不拼接旧计划、不由程序修改切点，不压缩原对白或提速。重新安排范围及预算，并给出全片叙事理由。"}
    return {**base, "action": "whole_direction_revision", "dispatch_allowed": True,
        "reason": "KNOWN_COMPLETE_FAILURE_WITH_REMAINING_CANDIDATE_ALLOWANCE",
        "revision_input": feedback, "must_claim_new_request_before_dispatch": True}


def reuse_native_performance(records, expected_input, compile_native, expected_request=None):
    """Reuse a unique original local result only after exact-input recompile.

    Call sequentially with the current completed source prefix and predecessor
    ending state. A changed predecessor invalidates subsequent original inputs.
    Matching segment IDs or source ranges alone never authorizes reuse.
    """
    if isinstance(expected_input, dict) and "messages" in expected_input:
        if expected_request is not None and expected_request != expected_input:
            raise ValueError("two expected native requests disagree")
        expected_request = deepcopy(expected_input)
        users = [message for message in expected_request["messages"] if message["role"] == "user"]
        expected_input = _strict_json(users[0]["content"])
    rejected = []
    matches = []
    for original in records:
        record_receipt = original.get("receipt", original)
        evidence = normalize_receipt(record_receipt, expected_request)
        if "receipt" in original and original.get("request") != evidence["request"]:
            rejected.append({"result_id": evidence["result_id"], "reason": "RECORD_REQUEST_CHANGED"})
            continue
        if not evidence["known_complete"] or evidence["status"] != "contract_valid":
            rejected.append({"result_id": evidence["result_id"], "reason": "ORIGINAL_RESULT_NOT_VALID_COMPLETE"})
            continue
        if evidence["actual_input"] != expected_input:
            rejected.append({"result_id": evidence["result_id"], "reason": "ACTUAL_INPUT_SOURCE_OR_STATE_PREFIX_CHANGED"})
            continue
        try:
            compiled = compile_native(deepcopy(evidence["native_document"]))
        except ValueError as error:
            rejected.append({"result_id": evidence["result_id"], "reason": "NATIVE_RECOMPILE_FAILED", "detail": str(error)})
            continue
        if "receipt" in original and original.get("compiled") != compiled:
            rejected.append({"result_id": evidence["result_id"], "reason": "STORED_COMPILED_PERFORMANCE_CHANGED"})
            continue
        matches.append((evidence, compiled))
    if len(matches) > 1:
        return {"status": "blocked", "reason": "MULTIPLE_VALID_NATIVE_RESULTS", "invalidated": rejected,
            "native_reused": False, "full_production_review_invalidated": True}
    if not matches:
        return {"status": "rebuild_required", "reason": "NO_EXACT_VALID_NATIVE_INPUT", "invalidated": rejected,
            "native_reused": False, "full_production_review_invalidated": True}
    evidence, compiled = matches[0]
    return {"status": "reused_original_native", "native_reused": True,
        "result_id": evidence["result_id"], "receipt_sha256": evidence["receipt_sha256"],
        "native_document": deepcopy(evidence["native_document"]), "compiled": compiled,
        "exact_actual_input_sha256": evidence["actual_input_sha256"], "invalidated": rejected,
        "full_production_review_invalidated": True, "creative_values_repaired": False}


def full_review_invalidation(old_native_direction, new_native_direction):
    """A new director result always requires full same-source production review."""
    return {"schema": VERSION + "/review_invalidation", "full_production_review_invalidated": True,
        "old_direction_sha256": digest(old_native_direction), "new_direction_sha256": digest(new_native_direction),
        "required_action": "compile_all_current_native_performances_then_review_complete_production_again",
        "old_full_review_reusable": False, "machine_text_handoff_ready": False,
        "human_visual_approval": False, "media_dispatch_allowed": False}
