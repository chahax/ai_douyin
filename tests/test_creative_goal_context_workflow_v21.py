"""Small offline integration scope for native setup4 and unchanged source4."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

from jsonschema import ValidationError
import pytest

from scripts.creative_m31_flash_role_clients_v1 import expected_wire_request, M31FlashRoleClients
from src.content_factory import creative_goal_context_workflow_v20 as frozen
from src.content_factory import creative_goal_context_workflow_v21 as workflow
from src.content_factory import creative_opening_setup_contract_v3 as old_setups
from src.content_factory import creative_opening_setup_contract_v4 as setups
from tests.test_creative_opening_setup_contract_v4 import synthetic_v4
from tests.test_creative_goal_context_workflow_v7_independent_audit import causal_scenario, prior_scenario
from tests import test_creative_goal_context_workflow_v20 as helpers
from tests.test_creative_split_full_review_contract_v4 import synthetic_consistency
from tests import test_goal_context_text_production_v4 as review_helpers

PROJECT = Path(__file__).resolve().parents[1]
ACTUAL = PROJECT / "data/production_trials/goal_context_text_production_20261013/round_23"


def read(path): return json.loads(path.read_text(encoding="utf-8-sig"))
def profile(): return read(PROJECT / "config/creative_goal_context_model_profile_v6.json")
def payload(prepared): return json.loads(prepared["request"]["messages"][1]["content"])


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **kw): raise AssertionError("workflow21 tests must never dispatch")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(M31FlashRoleClients, "__init__", deny)


def new_case(causal_scenario):
    inputs, goal, fixture, ids, native = helpers.new_case(causal_scenario)
    return inputs, goal, synthetic_v4(fixture), ids, native


def fresh_bundle(inputs, goal):
    synthetic = helpers.fresh_bundle(inputs, goal)
    return workflow.build_goal_audit_bundle(synthetic["native_source_audit"], synthetic["native_drama_audit"],
                                          synthetic["native_commitment_audit"])


def final_wire(prepared):
    actual = payload(prepared)
    assert prepared["wire"] == expected_wire_request(prepared["request"])
    assert prepared["request_sha256"] == workflow.digest(prepared["request"])
    assert prepared["manifest"]["payload_identity"] == workflow.contexts._measure(actual)
    assert prepared["request"]["input_provenance"]["context_manifest_sha256"] == workflow.digest(prepared["manifest"])
    assert prepared["manifest"]["workflow_version"] == workflow.VERSION
    assert prepared["sdk_max_retries"] == 0 and not prepared["dispatch_performed"]
    return actual


def test_setup_request_exposes_v4_type_in_actual_schema_messages_and_provenance(causal_scenario):
    inputs, goal, opening, _, _ = new_case(causal_scenario)
    prepared = workflow.prepare_opening_setup_request(inputs, profile(), goal)
    actual = final_wire(prepared)
    assert actual["native_goal_document"] == goal
    assert prepared["request"]["structured_schema"] == setups.build_schema(goal)
    assert setups.OPENING_SETUP_RULE in prepared["wire"]["messages"][0]["content"]
    assert "status只选specified或unspecified" in prepared["wire"]["messages"][0]["content"]
    assert prepared["manifest"]["opening_setup_contract_version"] == setups.VERSION
    assert prepared["request"]["input_provenance"]["opening_setup_contract_version"] == setups.VERSION
    assert workflow.validate_opening_setup_document(opening, goal) == opening
    assert workflow.contexts._reference_occurrences(actual, inputs["reference_fulltext"]) == 0


def test_compiler_author_and_same_source_both_review_paths_preserve_native_orientation(causal_scenario, monkeypatch):
    inputs, goal, opening, ids, native = new_case(causal_scenario)
    before = deepcopy((inputs, goal, opening, native))
    def forbid(*a, **kw): raise AssertionError("new chain cannot normalize with frozen setup3")
    for name in ("validate", "build_schema", "project_legacy_prop_states"):
        monkeypatch.setattr(old_setups, name, forbid)
    views = workflow.compile_native_views(goal, opening, **ids)
    props = {row["id"]: row for row in views["brief"]["initial_state"]["prop_states"]}
    for identifier, state in opening["props"].items():
        assert json.loads(props[identifier]["expected_state"]) == state
        expected = state["orientation"]["text"] if state["kind"] != "absent" and state["orientation"]["status"] == "specified" else None
        assert props[identifier]["orientation"] == expected
    audits = fresh_bundle(inputs, goal)
    assert audits["native_source_audit"]["schema"] == workflow.source_audit.VERSION
    authored = workflow.prepare_script_request(inputs, profile(), goal, audits, opening_setup=opening, **ids)
    assert final_wire(authored)["native_opening_setup_document"] == opening
    assert authored["views"] == views
    compiled = workflow.validate_script_document(native, views, inputs["production_preferences"])["script"]
    requests = {part: workflow.prepare_full_review_part_request(inputs, profile(), native, views, part)
                for part in ("semantic", "physical")}
    full = review_helpers.full_review({"full_current_script": compiled, "brief": views["brief"],
        "creative_scene_plan": views["plan"], "native_goal_document": goal,
        "verified_legal_context": requests["semantic"]["review_legal_context"]})
    full.update(schema=workflow.reviews.VERSION, opening_setup_sha256=workflow.digest(opening))
    for part, prepared in requests.items():
        actual = final_wire(prepared)
        assert actual["native_opening_setup_document"] == opening
        assert actual["native_script_document"] == native and actual["native_goal_document"] == goal
        assert actual["same_source_sha256"]["opening_setup_sha256"] == workflow.digest(opening)
        assert prepared["request"]["structured_schema"]["properties"]["opening_setup_sha256"] == {"const": workflow.digest(opening)}
        for identifier, state in opening["props"].items():
            assert actual["initial_evidence_catalog"]["initial:prop:" + identifier]["value"] == state
            assert "orientation" not in actual["compiled_initial_atoms"]["initial:prop:" + identifier]
        report = {key: deepcopy(full[key]) for key in prepared["request"]["structured_schema"]["properties"] if key in full}
        report.update(schema=workflow.split_reviews.VERSION, part=part, context_sha256=prepared["context_sha256"], revision_target="none")
        if part == "semantic": report.update(synthetic_consistency(compiled, views["brief"], views["plan"], goal_contract=goal))
        result = workflow.split_reviews.validate_part(report, part, compiled, views["brief"], views["plan"],
            prepared["review_legal_context"], context_sha256=prepared["context_sha256"], goal_contract=goal, opening_setup=opening)
        assert result["valid"] and result["accepted"], result
        if part == "physical":
            # A reviewer cannot replace an unspecified/null direction with its guess.
            guessed = deepcopy(report)
            identifier = next(iter(guessed["observed_prop_initial"]))
            guessed["observed_prop_initial"][identifier]["orientation"] = "伪猜朝上"
            rejected = workflow.split_reviews.validate_part(guessed, part, compiled, views["brief"], views["plan"],
                prepared["review_legal_context"], context_sha256=prepared["context_sha256"], goal_contract=goal, opening_setup=opening)
            assert not rejected["valid"] and not rejected["accepted"], rejected
    assert (inputs, goal, opening, native) == before


@pytest.mark.parametrize("fault", ["missing_source", "missing_drama", "missing_commitment", "different_goal", "old_bundle"])
def test_all_three_same_goal_audits_remain_required(causal_scenario, fault):
    inputs, goal, opening, ids, _ = new_case(causal_scenario)
    bundle = fresh_bundle(inputs, goal)
    if fault.startswith("missing_"): bundle.pop("native_" + fault[8:] + "_audit")
    elif fault == "different_goal": bundle["native_source_audit"]["goal_sha256"] = "0" * 64
    else: bundle["schema"] = frozen.BUNDLE_VERSION
    with pytest.raises((ValueError, ValidationError)): workflow.prepare_script_request(inputs, profile(), goal, bundle, opening_setup=opening, **ids)


@pytest.mark.parametrize("target", ["compiled_orientation", "native_orientation"])
def test_orientation_tamper_blocks_same_source_full_review(causal_scenario, target):
    inputs, goal, opening, ids, native = new_case(causal_scenario)
    views = workflow.compile_native_views(goal, opening, **ids)
    if target == "compiled_orientation": views["brief"]["initial_state"]["prop_states"][0]["orientation"] = "擅改朝上"
    else:
        identifier = next(key for key, state in views["opening_setup"]["props"].items() if state["kind"] != "absent")
        views["opening_setup"]["props"][identifier]["orientation"] = {"status": "specified", "text": "擅改朝上"}
    with pytest.raises(ValueError): workflow.prepare_full_review_part_request(inputs, profile(), native, views, "physical")


def test_actual609_setup_preview_and_author_preserve_original_goal_and_three_current_reports():
    inputs, goal = read(ACTUAL / "INPUTS.json"), read(ACTUAL / "INHERITED_NATIVE_GOAL.json")
    prepared = workflow.prepare_opening_setup_request(inputs, profile(), goal)
    actual = final_wire(prepared)
    assert actual["native_goal_document"] == goal and actual["actor_initial_states"] == {
        row["id"]: row["initial_state"] for row in goal["whole_plan"]["characters"]}
    assert prepared["request"]["structured_schema"] == setups.build_schema(goal)
    assert prepared["manifest"]["reference_occurrences"] == 0
    # A new shape-only fixture; neither614 nor615 is used as setup input.
    opening = {"schema": setups.VERSION, "goal_sha256": workflow.digest(goal), "characters": deepcopy(actual["actor_initial_states"]),
        "props": {row["id"]: {"kind": "scene", "scene_id": goal["whole_plan"]["scenes"][0]["id"],
            "location": "Synthetic shape-only initial position", "orientation": {"status": "unspecified", "text": ""}}
            for row in goal["whole_plan"]["props"]}}
    bundle = workflow.build_goal_audit_bundle(read(ACTUAL / "call_611_goal_source_audit_00.json")["output"],
        read(ACTUAL / "call_613_goal_drama_audit_00.json")["output"], read(ACTUAL / "call_612_goal_commitment_audit_00.json")["output"])
    decision = workflow.validate_goal_audit(bundle, goal, inputs=inputs)
    assert decision["accepted"] and not decision["semantic_truth_deterministically_proven"]
    authored = workflow.prepare_script_request(inputs, profile(), goal, bundle, opening_setup=opening, **workflow.origin_ids(inputs))
    body = final_wire(authored)
    assert body["native_goal_document"] == goal and body["native_opening_setup_document"] == opening
    original = workflow.audit_contexts._base_context(inputs, goal)["payload"]
    assert body["verified_legal_context"] == original["verified_legal_context"]
    assert body["user_goal_contract"] == original["user_goal_contract"]
    assert workflow.contexts._reference_occurrences(body, inputs["reference_fulltext"]) == 1
    for kind in ("source", "drama", "commitment"):
        assert authored["request"]["input_provenance"]["native_" + kind + "_audit_sha256"] == workflow.digest(bundle["native_" + kind + "_audit"])


def test_actual611_complete_report_and_decision_project_losslessly_into_new_whole_plan(tmp_path):
    inputs, goal = read(ACTUAL / "INPUTS.json"), read(ACTUAL / "INHERITED_NATIVE_GOAL.json")
    bundle = workflow.build_goal_audit_bundle(read(ACTUAL / "call_611_goal_source_audit_00.json")["output"],
        read(ACTUAL / "call_613_goal_drama_audit_00.json")["output"], read(ACTUAL / "call_612_goal_commitment_audit_00.json")["output"])
    source_request = workflow.prepare_goal_source_audit_request(inputs, profile(), goal)
    frozen_request = frozen.prepare_goal_source_audit_request(inputs, profile(), goal)
    assert payload(source_request) == payload(frozen_request)
    assert source_request["request"]["structured_schema"] == frozen_request["request"]["structured_schema"]
    decision = workflow.validate_goal_audit(bundle, goal, inputs=inputs)
    source_report = {"source": deepcopy(bundle["native_source_audit"])}
    diagnostics = {"complete_native_same_source_goal_audit_reports": source_report,
        "complete_same_source_goal_audits": [deepcopy(decision["source_decision"])],
        "reviewer_notes": {"status": "pending_model_verification", "semantic_quality_approved": False}}
    artifact = tmp_path / "original_complete611_diagnostics.json"
    artifact.write_text(json.dumps(diagnostics, ensure_ascii=False), encoding="utf-8")
    revision = {**inputs, "previous_complete_document": deepcopy(goal), "revision_diagnostics": diagnostics,
                "goal_revision_feedback_evidence_path": str(artifact)}
    before = deepcopy(revision)
    prepared = workflow.prepare_goal_request(revision, profile())
    actual = final_wire(prepared)
    assert actual["previous_complete_document"] == goal
    assert actual["revision_diagnostics"]["complete_native_same_source_goal_audit_reports"] == source_report
    source = actual["revision_diagnostics"]["complete_same_source_goal_audits"][0]
    for key in ("findings", "uncertainties"):
        assert source[key] == decision["source_decision"][key]
    for key in workflow.SOURCE4_COMPILED_FEEDBACK_TABLES:
        reference = source[key]
        assert workflow.feedback._resolve_pointer(diagnostics, reference["original_json_pointer"]) == decision["source_decision"][key]
        assert reference["original_value_sha256"] == workflow.digest(decision["source_decision"][key])
    assert actual["revision_diagnostics"]["reviewer_notes"] == diagnostics["reviewer_notes"]
    assert workflow.contexts._reference_occurrences(actual, inputs["reference_fulltext"]) == 1
    assert prepared["manifest"]["payload_identity"]["characters"] <= 100000
    assert revision == before
    # Extra full audits exceed this original budget; never erase native reports to fit.
    oversized = deepcopy(revision)
    oversized.pop("goal_revision_feedback_evidence_path")
    oversized["revision_diagnostics"]["complete_native_same_source_goal_audit_reports"] = deepcopy(bundle)
    oversized["revision_diagnostics"]["complete_same_source_goal_audits"] = [decision[key]
        for key in ("source_decision", "drama_decision", "commitment_decision")]
    with pytest.raises(workflow.contexts.ContextError): workflow.prepare_goal_request(oversized, profile())


def test_new_setup_compile_cannot_accept_or_rewrite_old614615():
    inputs, goal = read(ACTUAL / "INPUTS.json"), read(ACTUAL / "INHERITED_NATIVE_GOAL.json")
    for ordinal in (614, 615):
        path = next(ACTUAL.glob(f"call_{ordinal}_*.json"))
        original = path.read_bytes()
        native = json.loads(original)["output"]
        with pytest.raises(setups.OpeningSetupContractError): workflow.compile_native_views(goal, native, **workflow.origin_ids(inputs))
        assert path.read_bytes() == original
