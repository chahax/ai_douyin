"""Actual native audit scope and author admission; no provider or media calls."""
from copy import deepcopy
import json
from pathlib import Path
import socket

from jsonschema import ValidationError
import pytest

from scripts.creative_m31_flash_role_clients_v1 import expected_wire_request
from src.content_factory import creative_goal_context_workflow_v9 as workflow
from tests.test_creative_goal_context_workflow_v7_independent_audit import causal_scenario, prior_scenario


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("workflow v9 tests cannot contact a provider")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def payload(prepared):
    return json.loads(prepared["request"]["messages"][1]["content"])


def synthetic_bundle(inputs, profile, goal):
    source_request = workflow.prepare_goal_source_audit_request(inputs, profile, goal)
    drama_request = workflow.prepare_goal_drama_audit_request(inputs, profile, goal)
    judgment = {"status": "pass", "reason": "合成仅测试接线，不证明语义真值或审美", "required_revision": ""}
    source = {"schema": workflow.SOURCE_AUDIT_VERSION, "goal_sha256": workflow.digest(goal),
        "audit_context_sha256": workflow.digest(payload(source_request)),
        "claim_checks": {row["id"]: deepcopy(judgment) for row in goal["claims"]}}
    ref = next(iter(workflow.citations.build_evidence_catalog(goal)))
    drama = {"schema": workflow.DRAMA_AUDIT_VERSION, "goal_sha256": workflow.digest(goal),
        "audit_context_sha256": workflow.digest(payload(drama_request)),
        "goal_checks": {key: {**deepcopy(judgment), "evidence_refs": [ref],
            "counterexample_analysis": "合成空观察仅验证控制，不证明已抽取所有实际声音与物件", "counterevidence_refs": []}
            for key in workflow.GOAL_CHECKS},
        "scope_observations": {beat["id"]: {"audible_speakers": [], "operated_props": []}
            for beat in goal["whole_plan"]["beats"]}}
    return workflow.build_goal_audit_bundle(source, drama)


def test_actual_drama_request_has_new_native_scope_schema_and_refreshed_wire(causal_scenario):
    inputs, profile, goal, *_ = causal_scenario
    before = deepcopy((inputs, goal))
    prepared = workflow.prepare_goal_drama_audit_request(inputs, profile, goal)
    actual = payload(prepared)
    assert (inputs, goal) == before and actual["native_goal_document"] == goal
    scope = workflow.drama_contract.build_production_scope_catalog(goal)
    assert actual["production_scope_catalog"] == scope
    schema = prepared["request"]["structured_schema"]
    assert schema["properties"]["schema"]["const"] == workflow.DRAMA_AUDIT_VERSION
    assert set(schema["properties"]["scope_observations"]["required"]) == set(scope["beat_scopes"])
    assert schema["$defs"]["evidence_refs"]["maxItems"] == len(workflow.citations.build_evidence_catalog(goal)) > 8
    assert prepared["manifest"]["payload_identity"] == workflow.contexts._measure(actual)
    assert schema["properties"]["audit_context_sha256"]["const"] == workflow.digest(actual)
    assert prepared["wire"] == expected_wire_request(prepared["request"])
    assert prepared["request_sha256"] == workflow.digest(prepared["request"])
    assert prepared["request"]["input_provenance"]["workflow_version"] == workflow.VERSION
    system = prepared["request"]["messages"][0]["content"]
    assert "不超过8" not in system and "scope_observations" in system and "null" in system
    assert workflow.contexts._reference_occurrences(actual, inputs["reference_fulltext"]) == 1
    assert prepared["sdk_max_retries"] == 0 and not prepared["dispatch_performed"]


def test_current_bundle_admits_author_without_old_contract_fallback(causal_scenario):
    inputs, profile, goal, opening, old_bundle, ids, _ = causal_scenario
    bundle = synthetic_bundle(inputs, profile, goal)
    validated = workflow.validate_goal_audit(bundle, goal, inputs=inputs)
    assert validated["accepted"] and not validated["semantic_truth_deterministically_proven"]
    request = workflow.prepare_script_request(inputs, profile, goal, bundle, opening_setup=opening, **ids)
    assert payload(request)["native_goal_document"] == goal
    assert payload(request)["native_opening_setup_document"] == opening
    assert request["manifest"]["native_goal_audit_bundle_version"] == workflow.BUNDLE_VERSION
    assert request["request"]["input_provenance"]["native_drama_audit_sha256"] == workflow.digest(bundle["native_drama_audit"])
    assert request["wire"] == expected_wire_request(request["request"])
    with pytest.raises(ValueError, match="new bundle"):
        workflow.prepare_script_request(inputs, profile, goal, old_bundle, opening_setup=opening, **ids)


@pytest.mark.parametrize("status", ["fail", "unknown"])
def test_scope_failure_or_unknown_blocks_author(causal_scenario, status):
    inputs, profile, goal, opening, _, ids, _ = causal_scenario
    bundle = synthetic_bundle(inputs, profile, goal)
    bundle["native_drama_audit"]["goal_checks"]["closed_production_scope"].update(
        status=status, required_revision="完整新规划修复范围" if status == "fail" else "")
    with pytest.raises(ValueError, match="must pass"):
        workflow.prepare_script_request(inputs, profile, goal, bundle, opening_setup=opening, **ids)


def test_observed_undeclared_object_cannot_keep_closed_scope_pass(causal_scenario):
    inputs, profile, goal, opening, _, ids, _ = causal_scenario
    bundle = synthetic_bundle(inputs, profile, goal)
    scope = workflow.drama_contract.build_production_scope_catalog(goal)
    beat_id = next(iter(scope["beat_scopes"]))
    ref = scope["beat_scopes"][beat_id]["evidence_refs"][0]
    quote = workflow.citations.build_evidence_catalog(goal)[ref]["quote"]
    bundle["native_drama_audit"]["scope_observations"][beat_id]["operated_props"].append(
        {"source_ref": ref, "quote": quote, "declared_prop_id": None})
    with pytest.raises(ValueError, match="undeclared"):
        workflow.prepare_script_request(inputs, profile, goal, bundle, opening_setup=opening, **ids)


@pytest.mark.parametrize("field", ["verified_legal_context", "user_goal_contract", "reference_fulltext"])
def test_author_recomputes_actual_source_and_drama_contexts(causal_scenario, field):
    inputs, profile, goal, opening, _, ids, _ = deepcopy(causal_scenario)
    bundle = synthetic_bundle(inputs, profile, goal)
    if field == "verified_legal_context":
        inputs[field]["scope"] += "合成上下文变更"
    elif field == "user_goal_contract":
        inputs[field]["audience_goals"][0]["text"] += "合成上下文变更"
    else:
        inputs[field] += "\n合成参考变更"
    with pytest.raises(ValidationError):
        workflow.prepare_script_request(inputs, profile, goal, bundle, opening_setup=opening, **ids)


def test_many_unique_current_refs_are_finite_without_arbitrary_eight_cap(causal_scenario):
    inputs, profile, goal, *_ = causal_scenario
    bundle = synthetic_bundle(inputs, profile, goal)
    refs = list(workflow.citations.build_evidence_catalog(goal))
    bundle["native_drama_audit"]["goal_checks"]["concrete_conflict"]["evidence_refs"] = refs
    assert len(refs) > 8
    result = workflow.validate_goal_audit(bundle, goal, inputs=inputs)
    assert result["accepted"] and not result["semantic_truth_deterministically_proven"]
    assert not result["drama_decision"]["scope_observations_complete_extraction_proven"]


@pytest.mark.parametrize("part", ["semantic", "physical"])
def test_v8_complete_split_payload_and_fact_projection_are_inherited(causal_scenario, part):
    inputs, profile, goal, opening, _, ids, native = causal_scenario
    views = workflow.compile_native_views(goal, opening, **ids)
    request = workflow.prepare_full_review_part_request(inputs, profile, native, views, part)
    old_request = workflow.prior.prepare_full_review_part_request(inputs, profile, native, views, part)
    assert payload(request) == payload(old_request)
    assert request["same_source_sha256"] == old_request["same_source_sha256"]
    assert request["part_context_sha256"] == workflow.digest(payload(request))
    assert request["request"]["input_provenance"]["workflow_version"] == workflow.VERSION
    assert request["wire"] == expected_wire_request(request["request"])


def test_fresh_conception_remains_explicit_and_without_old_full_text(causal_scenario):
    inputs, profile, *_ = deepcopy(causal_scenario)
    for key in ("previous_complete_document", "revision_diagnostics"):
        inputs.pop(key, None)
    inputs["fresh_reconception_context"] = {"verified_defect": "合成声音范围反例，仅测新构想接线"}
    request = workflow.prepare_goal_request(inputs, profile)
    actual = payload(request)
    assert actual["fresh_reconception_context"] == inputs["fresh_reconception_context"]
    assert "previous_complete_document" not in actual and "revision_diagnostics" not in actual
    assert request["manifest"]["planning_mode"] == "fresh_complete_conception"
    assert workflow.CAST_SCOPE_RULE in request["request"]["messages"][0]["content"]
    assert request["wire"] == expected_wire_request(request["request"])


@pytest.fixture
def actual_round08():
    root = Path(__file__).resolve().parents[1]
    source = root / "data/production_trials/goal_context_text_production_20261013/round_08"
    read = lambda name: json.loads((source / name).read_text(encoding="utf-8"))
    profile = json.loads((root / "config/creative_goal_context_model_profile_v2.json").read_text(encoding="utf-8"))
    return read("INPUTS.json"), profile, read("call_554_goal_plan_12.json"), read("call_556_goal_drama_audit_02.json")


def test_actual554_every_beat_scope_and_real_radio_evidence_are_visible(actual_round08):
    inputs, profile, receipt, old_review = actual_round08
    goal = receipt["output"]
    request = workflow.prepare_goal_drama_audit_request(inputs, profile, goal)
    actual, schema = payload(request), request["request"]["structured_schema"]
    scope = actual["production_scope_catalog"]
    assert scope["declared_actor_ids"] == ["linxiao", "macheng"]
    assert set(scope["beat_scopes"]) == {row["id"] for row in goal["whole_plan"]["beats"]}
    assert "G023" in scope["beat_scopes"]["b3"]["evidence_refs"]
    assert not any("radio" in prop for prop in scope["declared_prop_ids"])
    assert actual["native_goal_document"]["whole_plan"]["beats"][2]["stimulus"] == "桌上的对讲机响了两声，主管在那边只问了一句：明天这个人上不上班，你一句话回我。"
    assert schema["$defs"]["evidence_refs"]["maxItems"] == len(workflow.citations.build_evidence_catalog(goal))
    with pytest.raises(ValidationError):
        workflow.validate_goal_drama_audit(old_review["output"], goal, context_sha256=workflow.digest(actual))
    assert old_review["status"] == "contract_rejected"  # Never convert the old native output.


def test_actual_known554_revision_preserves_complete_native_prior_and_diagnostics(actual_round08):
    inputs, profile, receipt, _ = actual_round08
    repaired_inputs = deepcopy(inputs)
    repaired_inputs.pop("fresh_reconception_context", None)
    goal = receipt["output"]
    repaired_inputs["previous_complete_document"] = deepcopy(goal)
    diagnostics = {"receipt_ordinal": 556, "verified_defect": "b3实际可辨主管声音及操作设备未声明，提交完整新规划"}
    repaired_inputs["revision_diagnostics"] = diagnostics
    before = deepcopy(repaired_inputs)
    request = workflow.prepare_goal_request(repaired_inputs, profile)
    actual = payload(request)
    assert repaired_inputs == before
    assert actual["previous_complete_document"] == goal and actual["revision_diagnostics"] == diagnostics
    assert "fresh_reconception_context" not in actual
    assert request["manifest"]["generation_mode"] == "bounded_content_revision"
    assert request["wire"] == expected_wire_request(request["request"])
    assert request["manifest"]["payload_identity"] == workflow.contexts._measure(actual)


@pytest.mark.parametrize("stage", ["goal", "source", "drama", "setup", "script", "semantic", "physical"])
def test_each_actual_request_binds_the_final_manifest_after_workflow_metadata(causal_scenario, stage):
    inputs, profile, goal, opening, _, ids, native = causal_scenario
    if stage == "goal":
        request = workflow.prepare_goal_request(inputs, profile)
    elif stage == "source":
        request = workflow.prepare_goal_source_audit_request(inputs, profile, goal)
    elif stage == "drama":
        request = workflow.prepare_goal_drama_audit_request(inputs, profile, goal)
    elif stage == "setup":
        request = workflow.prepare_opening_setup_request(inputs, profile, goal)
    elif stage == "script":
        bundle = synthetic_bundle(inputs, profile, goal)
        request = workflow.prepare_script_request(inputs, profile, goal, bundle, opening_setup=opening, **ids)
        assert "fact_projection" in request["manifest"]
        assert request["manifest"]["native_goal_audit_bundle_version"] == workflow.BUNDLE_VERSION
    else:
        views = workflow.compile_native_views(goal, opening, **ids)
        request = workflow.prepare_full_review_part_request(inputs, profile, native, views, stage)
    assert request["manifest"]["workflow_version"] == workflow.VERSION
    assert request["request"]["input_provenance"]["context_manifest_sha256"] == workflow.digest(request["manifest"])
    assert request["request_sha256"] == workflow.digest(request["request"])
    assert request["wire"] == expected_wire_request(request["request"])
