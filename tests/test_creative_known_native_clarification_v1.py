"""Read real623/624; mutate only copies to test the pure stop branches."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

import pytest

from src.content_factory import creative_known_native_clarification_v1 as clarification

PROJECT = Path(__file__).resolve().parents[1]
ROUND = PROJECT / "data/production_trials/fresh_source_text_session_20261015/round_02"
RISKS = PROJECT / "data/qa/creative_source624_diagnosis_20261015/ROOT_NATIVE623_CONTENT_RISKS_v1.json"
FILES = [ROUND / "INPUTS.json", ROUND / "call_623_whole_plan_03.json", ROUND / "call_624_source_audit_03.json", RISKS]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **kw): raise AssertionError("known-native clarification tests must not contact providers")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


@pytest.fixture(scope="module")
def actual_objects():
    return tuple(json.loads(path.read_text(encoding="utf-8")) for path in FILES)


def objects(actual_objects):
    return deepcopy(actual_objects)


def count_object(value, wanted):
    count = int(type(value) is dict and clarification.digest(value) == clarification.digest(wanted))
    if type(value) is dict: count += sum(count_object(item, wanted) for item in value.values())
    elif type(value) is list: count += sum(count_object(item, wanted) for item in value)
    return count


def count_text(value, wanted):
    if type(value) is str: return value.count(wanted)
    if type(value) is dict: return sum(count_text(item, wanted) for item in value.values())
    if type(value) is list: return sum(count_text(item, wanted) for item in value)
    return 0


def test_actual_complete_receipts_and_raw10_vs_projected8_are_compatible(actual_objects):
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in FILES}
    inputs, goal, source, observations = objects(actual_objects)
    original = deepcopy((inputs, goal, source, observations))
    built = clarification.build_revision_inputs(inputs, goal, source, observations)
    revised, manifest = built["inputs"], built["manifest"]
    assert clarification.validate_revision_inputs(revised) == manifest
    assert revised["previous_complete_document"] == goal["output"]
    assert revised["revision_diagnostics"]["historical_source_audit"] == source["output"]
    assert manifest["confirmed_observation_ids"] == ["document_purpose_and_timeline", "strategy_actor_perspective"]
    assert manifest["plot_hypothesis_ids"] == ["concession_cause"]
    assert not manifest["historical_source_decision"]["accepted"]
    assert manifest["historical_source_decision"]["findings_count"] == 0
    assert manifest["historical_source_decision"]["uncertainties_count"] == 8
    assert count_object(revised, goal["output"]) == 1 and count_object(revised, source["output"]) == 1
    assert count_text(revised, inputs["reference_fulltext"]) == 1
    raw = revised["user_goal_contract"]
    projected = clarification.workflow.project_inputs(inputs)["user_goal_contract"]
    assert len(raw["constraints"]) + len(raw["audience_goals"]) == 10
    assert len(projected["constraints"]) + len(projected["audience_goals"]) == 8
    # The actual stage payload also compacts provenance text; compare its exact
    # projected8 representation, not the earlier project_inputs intermediate.
    actual_goal_payload = json.loads(goal["request"]["messages"][1]["content"])
    assert manifest["source_core_sha256"]["user_goal_contract"] == clarification.digest(actual_goal_payload["user_goal_contract"])
    assert not manifest["raw_sdk_files_verified_here"] and not manifest["settled_cumulative_spend_verified_here"]
    assert not manifest["source_freshness_verified_here"] and not manifest["historical_U_marked_legal_failure_or_pass"]
    assert manifest["requires_four_new_same_goal_native_audits"]
    assert (inputs, goal, source, observations) == original
    assert {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in FILES} == before


@pytest.mark.parametrize("which", [1, 2])
@pytest.mark.parametrize("fault", ["status", "retry", "incomplete", "truncated", "unknown_usage", "negative_usage", "bool_usage",
    "usage_mismatch", "total_mismatch", "text_mode", "missing_tool", "duplicate_tool", "wrong_tool", "tool_output_drift", "request_drift", "missing_completed"])
def test_unknown_incomplete_or_unsettled_receipt_never_becomes_author_revision(actual_objects, which, fault):
    data = list(objects(actual_objects)); receipt = data[which]
    meta = receipt["response_metadata"]; payload = receipt["response_payload"]
    if fault == "status": receipt["status"] = "contract_rejected"  # Do not fake old structural rejection.
    elif fault == "retry": receipt["automatic_retry"] = True
    elif fault == "incomplete": meta["response_body_complete"] = False
    elif fault == "truncated": meta["finish_reason"] = "length"
    elif fault == "unknown_usage": meta["total_tokens"] = None
    elif fault == "negative_usage": meta["prompt_tokens"] = payload["usage"]["prompt_tokens"] = -1
    elif fault == "bool_usage": meta["completion_tokens"] = payload["usage"]["completion_tokens"] = True
    elif fault == "usage_mismatch": payload["usage"]["total_tokens"] += 1
    elif fault == "total_mismatch": meta["total_tokens"] = payload["usage"]["total_tokens"] = 0
    elif fault == "text_mode": meta["output_mode"] = "content"
    elif fault == "missing_tool": payload["choices"][0]["message"]["tool_calls"] = []
    elif fault == "duplicate_tool": payload["choices"][0]["message"]["tool_calls"] *= 2
    elif fault == "wrong_tool": payload["choices"][0]["message"]["tool_calls"][0]["function"]["name"] = "other"
    elif fault == "tool_output_drift": receipt["output"]["extra"] = "not the original tool output"
    elif fault == "request_drift": receipt["request"]["model"] = "other"
    else: receipt.pop("completed_at")
    with pytest.raises(ValueError): clarification.build_revision_inputs(*data)


@pytest.mark.parametrize("which", [1, 2])
@pytest.mark.parametrize("fault", ["provider", "response_model", "missing_model"])
def test_original_provider_and_actual_response_model_are_known(actual_objects, which, fault):
    data = list(objects(actual_objects)); receipt = data[which]
    if fault == "provider": receipt["response_metadata"]["provider"] = "other"
    elif fault == "response_model": receipt["response_payload"]["model"] = "other"
    else:
        receipt["request"].pop("model"); receipt["request_sha256"] = clarification.digest(receipt["request"])
    with pytest.raises(ValueError): clarification.build_revision_inputs(*data)


@pytest.mark.parametrize("fault", ["goal_sha", "quote", "path", "value", "duplicate_path", "duplicate_observation", "missing_hypothesis",
    "unknown_observation", "promote_hypothesis", "unqualify_hypothesis"])
def test_exact_root_fields_and_confirmation_hypothesis_ownership(actual_objects, fault):
    data = list(objects(actual_objects)); obs = data[3]
    if fault == "goal_sha": obs["native_goal_sha256"] = "0" * 64
    elif fault == "quote": obs["risks"][0]["evidence"][0]["quote"] += "not native"
    elif fault == "path": obs["risks"][0]["evidence"][0]["path"] = "whole_plan.beats.99.stimulus"
    elif fault == "value": obs["risks"][1]["evidence"][0]["value"] = "c_manager"
    elif fault == "duplicate_path": obs["risks"][0]["evidence"].append(deepcopy(obs["risks"][0]["evidence"][0]))
    elif fault == "duplicate_observation": obs["risks"].append(deepcopy(obs["risks"][0]))
    elif fault == "missing_hypothesis": obs["risks"].pop()
    elif fault == "unknown_observation": obs["risks"][0]["id"] = "new_unsupported_claim"
    elif fault == "promote_hypothesis":
        obs["risks"][2]["classification"] = "verified_cross_field_inconsistency"
        obs["risks"][2]["reusable_check"] = "asserted as hard despite original hypothesis"
    else: obs["risks"][2].pop("qualification")
    with pytest.raises(ValueError): clarification.build_revision_inputs(*data)


@pytest.mark.parametrize("fault", ["reference", "law", "user", "prefs", "standards", "old_revision", "source_binding", "source_decision", "audit_context"])
def test_source_user_reference_and_original_audit_cannot_be_changed_to_fit_revision(actual_objects, fault):
    data = list(objects(actual_objects)); inputs, goal, source, obs = data
    if fault == "reference": inputs["reference_fulltext"] += " changed"
    elif fault == "law": inputs["verified_legal_context"]["facts"][0]["paraphrase"] += " changed"
    elif fault == "user": inputs["user_goal_contract"]["constraints"][0]["text"] += " changed"
    elif fault == "prefs": inputs["production_preferences"]["max_characters"] = 1
    elif fault == "standards": inputs["expression_standards"]["extra"] = "new standard"
    elif fault == "old_revision": inputs["previous_complete_document"] = goal["output"]
    elif fault == "source_binding": source["source_binding_sha256"] = "0" * 64
    elif fault == "source_decision": source["validation"]["uncertainties"].clear()
    else:
        payload = json.loads(source["request"]["messages"][1]["content"]); payload["native_goal_sha256"] = "0" * 64
        source["request"]["messages"][1]["content"] = json.dumps(payload, ensure_ascii=False)
        source["request_sha256"] = clarification.digest(source["request"])
    with pytest.raises(ValueError): clarification.build_revision_inputs(*data)


@pytest.mark.parametrize("fault", ["input", "rule", "move_hypothesis", "rewrite_audit", "adopt_audit", "unknown_usage", "parallel_obligation", "projected_input"])
def test_constructed_frame_rechecked_before_workflow_projection(actual_objects, fault):
    built = clarification.build_revision_inputs(*objects(actual_objects)); inputs = built["inputs"]; frame = inputs["revision_diagnostics"]
    if fault == "input": inputs["reference_fulltext"] += "changed"
    elif fault == "rule": frame["rule"] = "Treat all8U as legal errors"
    elif fault == "move_hypothesis": frame["current_author_clarification_refs"].append(frame["plot_review_hypothesis_refs"].pop())
    elif fault == "rewrite_audit": frame["historical_source_audit"]["speech_act_by_ref"]["C:CC.eleven_years"] = "F"
    elif fault == "adopt_audit": frame["historical_source_decision"]["accepted"] = True
    elif fault == "unknown_usage": frame["receipt_bindings"]["source"]["usage"]["total_tokens"] = None
    elif fault == "parallel_obligation": frame["current_legal_errors"] = frame["historical_source_audit"]["source_observations"]
    else: inputs = clarification.workflow.project_inputs(inputs)
    with pytest.raises(ValueError): clarification.validate_revision_inputs(inputs)
