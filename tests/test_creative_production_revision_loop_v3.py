"""Known result routing, inherited caps and original-input cache invalidation."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from src.content_factory import creative_production_revision_loop_v3 as loop
from src.content_factory import creative_complete_production_pipeline_v1 as contract
from src.content_factory import creative_complete_production_pipeline_v3 as current_contract
from tests.test_creative_complete_production_pipeline_v2 import v2_fixture

ACTUAL = Path(__file__).resolve().parents[1] / "data/production_revisions/shared_full_production_20261012/run_01"
SOURCE_SHA = "a" * 64


def receipt(native, stage_input=None, ordinal=1, status="contract_valid"):
    stage_input = stage_input or {"source": "complete frozen source", "state_prefix": [], "initial": "original"}
    request = {"role": "writer", "model": "MiniMax-M3", "operator_version": "offline_fixture/v3",
        "parameters": {"temperature": .4, "thinking": "disabled", "max_completion_tokens": 10000},
        "messages": [{"role": "system", "content": "current phase only"},
            {"role": "user", "content": json.dumps(stage_input, ensure_ascii=False)}],
        "structured_schema": {"title": "submit_creative_json", "type": "object"},
        "output_transport": "creative_json_document_transport/v1"}
    outer = {"payload_json": json.dumps(native, ensure_ascii=False)}
    return {"ordinal": ordinal, "label": "whole_direction", "status": status,
        "request": request, "request_sha256": loop.digest(request), "source_binding_sha256": SOURCE_SHA,
        "output": outer, "document_output": deepcopy(native),
        "response_metadata": {"http_status_code": 200, "response_body_complete": True,
            "finish_reason": "tool_calls", "raw_body_sha256": "b" * 64,
            "total_tokens": 25, "prompt_tokens": 20, "completion_tokens": 5},
        "response_payload": {"choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": [
            {"type": "function", "function": {"name": "submit_creative_json", "arguments": json.dumps(outer, ensure_ascii=False)}}]}}],
            "usage": {"total_tokens": 25, "prompt_tokens": 20, "completion_tokens": 5}},
        "automatic_retry": False}


def empty_state():
    return loop.initial_loop_state([], SOURCE_SHA)


def actual_receipts():
    paths = [next(ACTUAL.glob(f"call_{n}_*.json")) for n in (514, 515, 516)]
    return paths, [json.loads(path.read_text(encoding="utf8")) for path in paths]


def test_actual_three_known_failures_exhaust_director_candidates_without_reset_or_mutation():
    paths, rows = actual_receipts()
    before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    state = loop.initial_loop_state(rows)
    capacity = loop.candidate_capacity(state)
    assert capacity["attempts_including_claims"] == capacity["candidate_limit"] == 3
    assert capacity["remaining"] == 0 and not capacity["budget_reset"]
    evidence = loop.normalize_receipt(rows[-1])
    assert evidence["known_complete"] and evidence["reported_tokens"] == 15036
    native = evidence["native_document"]
    directive = loop.route_failure(state, loop.DIRECTOR_FAILURE, evidence, native)
    assert directive["reason"] == "INHERITED_DIRECTOR_ALLOWANCE_EXHAUSTED"
    assert not directive["dispatch_allowed"]
    with pytest.raises(ValueError, match="allowance exhausted"):
        loop.claim_director_request(state, "new-directory-does-not-reset-history")
    assert before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def test_complete_local_window_failure_returns_entire_native_director_for_new_request():
    script, manifest, initial, direction, performances = v2_fixture()
    failed = deepcopy(performances[0]["native"])
    failed["action_timings"][0]["duration_seconds"] = 15
    original = deepcopy(direction["native"])
    stage_input = current_contract.build_performance_input(script, manifest, direction["segments"][0], initial, [], "reference", {})
    evidence = loop.normalize_receipt(receipt(failed, stage_input, status="contract_rejected"))
    with pytest.raises(current_contract.PerformanceWindowExceeded) as error:
        current_contract.compile_performance(failed, script, manifest, direction["segments"][0], initial, [])
    diagnostic = error.value.diagnostic
    state = loop.register_director_result(empty_state(), receipt(original, ordinal=0))
    route = loop.route_failure(state, loop.WINDOW_FAILURE, evidence, original, failed, diagnostic)
    assert route["action"] == "whole_direction_revision" and route["dispatch_allowed"]
    assert route["revision_input"]["prior_complete_native_direction"] == original
    assert route["revision_input"]["failed_complete_native_result"] == failed
    assert route["revision_input"]["diagnostic"] == diagnostic
    assert route["must_claim_new_request_before_dispatch"]
    assert not route["manual_cut_or_duration_patch_allowed"]
    assert not route["local_acceleration_revision_allowed"]
    assert "new_segments" not in route
    assert direction["native"] == original
    changed = deepcopy(diagnostic); changed["required_seconds"] = 1
    assert loop.route_failure(state, loop.WINDOW_FAILURE, evidence, original, failed, changed)["reason"] == "LOCAL_WINDOW_DIAGNOSTIC_NOT_VERIFIED"
    assert loop.route_failure(state, loop.WINDOW_FAILURE, evidence, original, failed)["reason"] == "LOCAL_WINDOW_DIAGNOSTIC_NOT_VERIFIED"
    patched = deepcopy(original); patched["whole_observation"] = "手工回填的新观察"
    assert loop.route_failure(state, loop.WINDOW_FAILURE, evidence, patched, failed, diagnostic)["reason"] == "PRIOR_DIRECTOR_NOT_CURRENT_VALID_NATIVE"


@pytest.mark.parametrize("defect", ["truncated", "unknown_usage", "negative_usage", "bool_usage", "missing_tool",
    "unknown_native", "changed_native", "changed_request", "incomplete_response", "duplicate_json", "http_unknown"])
def test_unknown_truncated_missing_tool_and_changed_evidence_stop_without_new_dispatch(defect):
    native = {"availability": "known", "complete": "original document"}
    row = receipt(native, status="contract_rejected")
    if defect == "truncated": row["response_metadata"]["finish_reason"] = "length"
    elif defect == "unknown_usage": row["response_metadata"]["total_tokens"] = None
    elif defect == "negative_usage": row["response_metadata"]["total_tokens"] = -1
    elif defect == "bool_usage": row["response_metadata"]["total_tokens"] = True
    elif defect == "missing_tool":
        row["response_payload"]["choices"][0]["message"] = {"content": json.dumps(native)}
    elif defect == "unknown_native":
        native = {"availability": "unknown"}
        row = receipt(native, status="contract_rejected")
    elif defect == "changed_native": row["document_output"]["complete"] = "manually patched"
    elif defect == "changed_request": row["request"]["model"] = "different-model"
    elif defect == "incomplete_response": row["response_metadata"]["response_body_complete"] = False
    elif defect == "duplicate_json":
        outer = {"payload_json": '{"availability":"known","availability":"unknown"}'}
        row["output"] = outer
        row["response_payload"]["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = json.dumps(outer)
    else: row["response_metadata"]["http_status_code"] = None
    evidence = loop.normalize_receipt(row)
    assert not evidence["known_complete"]
    route = loop.route_failure(empty_state(), loop.DIRECTOR_FAILURE, evidence, native)
    assert route["action"] == "stop" and not route["dispatch_allowed"]
    assert route["reason"] == "RESULT_OR_USAGE_NOT_COMPLETE"
    assert not evidence["ordinary_body_adopted"]
    assert not route["automatic_transport_retry"]


def test_claim_is_persistent_and_unknown_result_consumes_attempt_without_redispatch():
    state = loop.claim_director_request(empty_state(), "request-sha-001")
    with pytest.raises(ValueError, match="already claimed"):
        loop.claim_director_request(state, "request-sha-001")
    with pytest.raises(ValueError, match="unresolved"):
        loop.claim_director_request(state, "request-sha-002")
    row = receipt({"availability": "known"}, status="response_unknown")
    row["response_metadata"]["response_body_complete"] = False
    state = loop.register_director_result(state, row, "request-sha-001")
    assert loop.candidate_capacity(state)["attempts_including_claims"] == 1
    assert loop.candidate_capacity(state)["remaining"] == 2
    assert loop.candidate_capacity(state)["unresolved_result_ids"] == ["1"]
    with pytest.raises(ValueError, match="result or usage unknown"):
        loop.claim_director_request(state, "request-sha-002")
    assert loop.register_director_result(state, row, "request-sha-001") == state
    changed = deepcopy(row); changed["status"] = "contract_valid"
    with pytest.raises(ValueError, match="result changed"):
        loop.register_director_result(state, changed, "request-sha-001")
    route = loop.route_failure(state, loop.DIRECTOR_FAILURE, row, {"availability": "known"})
    assert not route["dispatch_allowed"]


def test_explicit_scope_bound_extra_grant_is_single_idempotent_and_preserves_three_failures():
    _, rows = actual_receipts()
    state = loop.initial_loop_state(rows)
    grant = {"authority": "explicit_user", "grant_id": "offline-simulation-only",
        "user_quote": "仅模拟明确额外一份授权，不代表当前用户已授权生产",
        "additional_candidates": 1, "source_binding_sha256": state["source_binding_sha256"]}
    updated = loop.authorize_extra_candidate(state, grant)
    assert loop.authorize_extra_candidate(updated, grant) == updated
    capacity = loop.candidate_capacity(updated)
    assert capacity["candidate_limit"] == 4 and capacity["attempts_including_claims"] == 3
    assert len(state["additional_candidate_grants"]) == 0
    changed = deepcopy(grant); changed["additional_candidates"] = 2
    with pytest.raises(ValueError, match="grant identity changed"):
        loop.authorize_extra_candidate(updated, changed)
    with pytest.raises(ValueError, match="scope-bound"):
        loop.authorize_extra_candidate(state, {**grant, "authority": "inferred_continue"})
    claimed = loop.claim_director_request(updated, "new-unique-request")
    assert loop.candidate_capacity(claimed)["remaining"] == 0
    assert claimed["director_events"][:3] == state["director_events"]


def test_successor_code_freeze_preserves_creative_scope_history_and_exhausted_allowance():
    _, rows = actual_receipts()
    state = loop.initial_loop_state(rows)
    new_binding = "c" * 64
    updated = loop.register_successor_binding(state, new_binding, state["stable_scope_material"], loop.digest(state))
    assert loop.candidate_capacity(updated) == loop.candidate_capacity(state)
    assert updated["director_events"] == state["director_events"]
    assert updated["source_binding_sha256"] == state["source_binding_sha256"]
    assert loop.register_successor_binding(updated, new_binding, state["stable_scope_material"], loop.digest(state)) == updated
    changed = deepcopy(state["stable_scope_material"])
    changed["full_current_script"]["title"] = "source replacement"
    with pytest.raises(ValueError, match="stable creative scope"):
        loop.register_successor_binding(state, "d" * 64, changed, loop.digest(state))
    with pytest.raises(ValueError, match="inherited history"):
        loop.register_successor_binding(state, "d" * 64, state["stable_scope_material"], "e" * 64)
    row = deepcopy(rows[-1]); row["ordinal"] = 600; row["source_binding_sha256"] = new_binding
    evidence = loop.normalize_receipt(row)
    route = loop.route_failure(updated, loop.DIRECTOR_FAILURE, evidence, evidence["native_document"])
    assert route["reason"] == "INHERITED_DIRECTOR_ALLOWANCE_EXHAUSTED"
    assert not route["dispatch_allowed"]
    wrong = deepcopy(row)
    inp = json.loads(wrong["request"]["messages"][1]["content"])
    inp["shared_manifest"]["script_sha256"] = "f" * 64
    wrong["request"]["messages"][1]["content"] = json.dumps(inp, ensure_ascii=False)
    wrong["request_sha256"] = loop.digest(wrong["request"])
    with pytest.raises(ValueError, match="source or original identity changed"):
        loop.register_director_result(updated, wrong)
    evidence = loop.normalize_receipt(wrong)
    assert loop.route_failure(updated, loop.DIRECTOR_FAILURE, evidence, evidence["native_document"])["reason"] == "SOURCE_IDENTITY_CHANGED"


def test_full_review_failure_returns_director_and_unknown_review_stops():
    _, _, _, direction, _ = v2_fixture()
    state = loop.register_director_result(empty_state(), receipt(direction["native"], ordinal=0))
    native = {"checks": [{"id": "cause", "status": "fail", "evidence": "current source failure"}],
        "revision_requirements": [{"problem": "late actor reaction"}]}
    route = loop.route_failure(state, loop.REVIEW_FAILURE, receipt(native), direction["native"])
    assert route["action"] == "whole_direction_revision"
    assert route["revision_input"]["failed_complete_native_result"] == native
    native["checks"].append({"id": "unknown", "status": "unknown"})
    route = loop.route_failure(state, loop.REVIEW_FAILURE, receipt(native), direction["native"])
    assert route["reason"] == "FULL_REVIEW_NOT_KNOWN_EXPLICIT_FAILURE"
    assert not route["dispatch_allowed"]


def performance_record(i=0):
    script, manifest, initial, direction, performances = v2_fixture()
    performance = performances[i]
    inp = {"full_current_script": script, "shared_manifest": manifest,
        "compiled_segment": direction["segments"][i], "planned_initial_state": performance["planned_initial_state"],
        "completed_source_refs": performance["completed_refs"]}
    row = receipt(performance["native"], inp, ordinal=10 + i)
    compiler = lambda native: contract.compile_performance(native, script, manifest, direction["segments"][i],
        performance["planned_initial_state"], performance["completed_refs"])
    return {"request": row["request"], "receipt": row, "compiled": performance}, compiler


def test_reuse_recompiles_unique_native_exact_actual_request_and_preserves_creative_values():
    record, compiler = performance_record()
    original = deepcopy(record)
    result = loop.reuse_native_performance([record], record["request"], compiler)
    assert result["status"] == "reused_original_native"
    assert result["compiled"] == record["compiled"]
    assert result["native_document"] == record["receipt"]["document_output"]
    assert not result["creative_values_repaired"]
    assert result["full_production_review_invalidated"]
    assert record == original


@pytest.mark.parametrize("change", ["source", "prefix", "previous_state", "budget", "model", "rule", "schema", "patched_compiled"])
def test_reuse_is_invalidated_by_source_state_prefix_direction_or_actual_request_change(change):
    record, compiler = performance_record(1)
    expected = deepcopy(record["request"])
    inp = json.loads(expected["messages"][1]["content"])
    if change == "source": inp["full_current_script"]["title"] += " altered"
    elif change == "prefix": inp["completed_source_refs"] = []
    elif change == "previous_state": inp["planned_initial_state"]["actors"][0]["posture"] = "站起"
    elif change == "budget": inp["compiled_segment"]["target_seconds"] += 1
    elif change == "model": expected["model"] = "changed-model"
    elif change == "rule": expected["messages"][0]["content"] += " changed phase"
    elif change == "schema": expected["structured_schema"]["type"] = "array"
    else: record["compiled"]["schedule"][0]["original_text"] = "manual shorter line"
    expected["messages"][1]["content"] = json.dumps(inp, ensure_ascii=False)
    result = loop.reuse_native_performance([record], expected, compiler)
    assert result["status"] == "rebuild_required" and not result["native_reused"]
    assert result["full_production_review_invalidated"]


def test_duplicate_valid_results_and_unchanged_new_plan_never_reuse_old_full_review():
    record, compiler = performance_record()
    other = deepcopy(record); other["receipt"]["ordinal"] += 1
    result = loop.reuse_native_performance([record, other], record["request"], compiler)
    assert result["status"] == "blocked" and result["reason"] == "MULTIPLE_VALID_NATIVE_RESULTS"
    direction = {"native": "same complete values"}
    result = loop.full_review_invalidation(direction, deepcopy(direction))
    assert result["full_production_review_invalidated"] and not result["old_full_review_reusable"]
    assert not result["machine_text_handoff_ready"]
    assert not result["human_visual_approval"] and not result["media_dispatch_allowed"]
