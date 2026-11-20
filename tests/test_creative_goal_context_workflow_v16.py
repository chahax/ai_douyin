"""Entire native-v3 setup path and three current audit gates, offline only."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

from jsonschema import Draft202012Validator, ValidationError
import pytest

from scripts.creative_m31_flash_role_clients_v1 import M31FlashRoleClients, expected_wire_request
from src.content_factory import creative_goal_context_workflow_v16 as workflow
from src.content_factory import creative_opening_setup_contract_v2 as old_setups
from src.content_factory import creative_opening_setup_contract_v3 as setups
from src.content_factory import creative_goal_drama_audit_contract_v10 as old_drama
from tests.test_creative_goal_context_workflow_v7_independent_audit import causal_scenario, prior_scenario
from tests.test_creative_goal_context_workflow_v15 import synthetic_focused
from tests.test_creative_split_full_review_contract_v2 import synthetic_consistency
from tests import test_goal_context_text_production_v4 as review_helpers

PROJECT = Path(__file__).resolve().parents[1]
ACTUAL = PROJECT / "data/production_trials/goal_context_text_production_20261013/round_15"


def read(p): return json.loads(p.read_text(encoding="utf-8-sig"))
def payload(p): return json.loads(p["request"]["messages"][1]["content"])
def profile(): return read(PROJECT / "config/creative_goal_context_model_profile_v3.json")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **kw): raise AssertionError("workflow16 tests may not create clients or contact providers")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(M31FlashRoleClients, "__init__", deny)


def new_case(causal_scenario):
    inputs, _, goal, old_shape, _, ids, native = deepcopy(causal_scenario)
    # Fresh synthetic v3 document; no original589/590 response is rewritten.
    opening = {"schema": setups.VERSION, "goal_sha256": workflow.digest(goal),
        "characters": deepcopy(old_shape["characters"]),
        "props": {key: {"kind": "absent"} if row["kind"] == "absent" else deepcopy(row)
                  for key, row in old_shape["props"].items()}}
    return inputs, goal, opening, ids, native


def fresh_bundle(inputs, goal):
    judgement = {"status": "pass", "reason": "Synthetic shape-only judgment, not semantic gold", "required_revision": ""}
    source_request = workflow.prepare_goal_source_audit_request(inputs, profile(), goal)
    drama_request = workflow.prepare_goal_drama_audit_request(inputs, profile(), goal)
    first = next(ref for ref in workflow.drama_contract.build_evidence_catalog(goal) if ref.startswith("G"))
    row = {**judgement, "evidence_refs": [first], "counterexample_analysis": "Synthetic full comparison field",
           "counterevidence_refs": []}
    source = {"schema": workflow.SOURCE_AUDIT_VERSION, "goal_sha256": workflow.digest(goal),
        "audit_context_sha256": workflow.digest(payload(source_request)),
        "claim_checks": {claim["id"]: deepcopy(judgement) for claim in goal["claims"]}}
    drama = {"schema": workflow.DRAMA_AUDIT_VERSION, "goal_sha256": workflow.digest(goal),
        "audit_context_sha256": workflow.digest(payload(drama_request)),
        "goal_checks": {key: deepcopy(row) for key in workflow.GOAL_CHECKS},
        "scope_observations": {ref: {"audible_speakers": [], "operated_props": []}
            for ref in workflow.drama_contract.build_scope_source_catalog(goal)}, "closed_scope_findings": []}
    focused = synthetic_focused(inputs, goal)
    focused["audit_context_sha256"] = workflow.digest(payload(workflow.prepare_goal_commitment_audit_request(inputs, profile(), goal)))
    return workflow.build_goal_audit_bundle(source, drama, focused)


def final_wire(prepared):
    actual = payload(prepared)
    assert prepared["wire"] == expected_wire_request(prepared["request"])
    assert prepared["request_sha256"] == workflow.digest(prepared["request"])
    assert prepared["manifest"]["payload_identity"] == workflow.contexts._measure(actual)
    assert prepared["request"]["input_provenance"]["context_manifest_sha256"] == workflow.digest(prepared["manifest"])
    assert prepared["manifest"]["workflow_version"] == workflow.VERSION
    assert prepared["sdk_max_retries"] == 0 and not prepared["dispatch_performed"]
    return actual


def test_setup_wire_consumes_exact_new_native_rule_and_absent_kind_only(causal_scenario):
    inputs, goal, opening, _, _ = new_case(causal_scenario)
    prepared = workflow.prepare_opening_setup_request(inputs, profile(), goal)
    actual = final_wire(prepared)
    assert actual["native_goal_document"] == goal
    assert prepared["request"]["structured_schema"] == setups.build_schema(goal)
    assert setups.OPENING_SETUP_RULE in prepared["wire"]["messages"][0]["content"]
    assert "absent只填kind，不填写orientation" in prepared["wire"]["messages"][0]["content"]
    assert workflow.validate_opening_setup_document(opening, goal) == opening
    assert workflow.contexts._reference_occurrences(actual, inputs["reference_fulltext"]) == 0


def test_new_v3_full_compile_author_body_and_both_review_paths_never_call_v2(causal_scenario, monkeypatch):
    inputs, goal, opening, ids, native = new_case(causal_scenario)
    before = deepcopy((inputs, goal, opening, native))
    def forbid(*a, **kw): raise AssertionError("hidden opening_v2 call is forbidden in the v16 chain")
    for name in ("validate", "build_schema", "project_legacy_prop_states"):
        monkeypatch.setattr(old_setups, name, forbid)
    workflow.prepare_opening_setup_request(inputs, profile(), goal)
    views = workflow.compile_native_views(goal, opening, **ids)
    props = {row["id"]: row for row in views["brief"]["initial_state"]["prop_states"]}
    assert json.loads(props["paper"]["expected_state"]) == {"kind": "absent"}
    assert all(props["paper"][key] is None for key in ("orientation", "location", "support", "holder_character_id"))
    bundle = fresh_bundle(inputs, goal)
    assert workflow.validate_goal_audit(bundle, goal, inputs=inputs)["accepted"]
    authored = workflow.prepare_script_request(inputs, profile(), goal, bundle, opening_setup=opening, **ids)
    assert authored["views"] == views
    assert final_wire(authored)["native_opening_setup_document"] == opening
    compiled = workflow.validate_script_document(native, views, inputs["production_preferences"])["script"]
    prepared = {part: workflow.prepare_full_review_part_request(inputs, profile(), native, views, part)
                for part in ("semantic", "physical")}
    reports = {}
    full = review_helpers.full_review({"full_current_script": compiled, "brief": views["brief"],
        "creative_scene_plan": views["plan"], "native_goal_document": goal,
        "verified_legal_context": prepared["semantic"]["review_legal_context"]})
    full.update(schema=workflow.reviews.VERSION, opening_setup_sha256=workflow.digest(opening))
    for part, request in prepared.items():
        actual = final_wire(request)
        assert actual["native_opening_setup_document"] == opening
        assert actual["initial_evidence_catalog"]["initial:prop:paper"]["value"] == {"kind": "absent"}
        assert actual["compiled_initial_atoms"]["initial:prop:paper"]["presence"] == "absent"
        assert actual["same_source_sha256"]["opening_setup_sha256"] == workflow.digest(opening)
        assert request["request"]["structured_schema"]["properties"]["opening_setup_sha256"]["const"] == workflow.digest(opening)
        assert request["request"]["input_provenance"]["native_opening_setup_sha256"] == workflow.digest(opening)
        report = {key: deepcopy(full[key]) for key in request["request"]["structured_schema"]["properties"] if key in full}
        report.update(schema=workflow.split_reviews.VERSION, part=part, context_sha256=request["context_sha256"], revision_target="none")
        if part == "semantic": report.update(synthetic_consistency(compiled, views["brief"], views["plan"], goal_contract=goal))
        reports[part] = report
        result = workflow.split_reviews.validate_part(report, part, compiled, views["brief"], views["plan"],
            request["review_legal_context"], context_sha256=request["context_sha256"], goal_contract=goal, opening_setup=opening)
        assert result["valid"] and result["accepted"], result
        assert workflow.contexts._reference_occurrences(actual, inputs["reference_fulltext"]) == (1 if part == "semantic" else 0)
    result = workflow.split_reviews.validate_bundle(workflow.split_reviews.build_review_bundle(reports["semantic"], reports["physical"]),
        compiled, views["brief"], views["plan"], prepared["semantic"]["review_legal_context"],
        semantic_context_sha256=prepared["semantic"]["context_sha256"], physical_context_sha256=prepared["physical"]["context_sha256"],
        goal_contract=goal, opening_setup=opening)
    assert result["valid"] and result["accepted"] and not result["creative_quality_passed"], result
    assert (inputs, goal, opening, native) == before


@pytest.mark.parametrize("fault", ["missing_source", "missing_drama", "missing_commitment", "old_drama", "old_bundle",
    "cross_drama_context", "cross_drama_goal", "missing_scope_G", "focus_fail", "focus_unknown"])
def test_three_native_current_audits_remain_required_and_do_not_use_v10_bundle(causal_scenario, fault):
    inputs, goal, opening, ids, _ = new_case(causal_scenario)
    bundle = fresh_bundle(inputs, goal)
    if fault.startswith("missing_") and fault != "missing_scope_G": bundle.pop("native_" + fault[8:] + "_audit")
    elif fault == "old_drama": bundle["native_drama_audit"]["schema"] = old_drama.VERSION
    elif fault == "old_bundle": bundle["schema"] = old_drama.BUNDLE_VERSION
    elif fault == "cross_drama_context": bundle["native_drama_audit"]["audit_context_sha256"] = "0" * 64
    elif fault == "cross_drama_goal": bundle["native_drama_audit"]["goal_sha256"] = "0" * 64
    elif fault == "missing_scope_G": bundle["native_drama_audit"]["scope_observations"].pop(next(iter(bundle["native_drama_audit"]["scope_observations"])))
    else:
        row = next(iter(bundle["native_commitment_audit"]["commitment_checks"].values()))
        usage = next(iter(row["actual_usages"].values()))
        status = fault[6:]
        row.update(status=status, required_revision="Complete new native plan" if status == "fail" else "")
        usage["relationship"] = "contradicts" if status == "fail" else "unknown"
    with pytest.raises((ValueError, ValidationError)):
        workflow.prepare_script_request(inputs, profile(), goal, bundle, opening_setup=opening, **ids)


def test_actual585_scope_all_beat_and_ending_G_and_commitments_only_in_focused_packet():
    if not ACTUAL.exists(): pytest.skip("read-only actual585 fixture absent")
    inputs, goal = read(ACTUAL / "INPUTS.json"), read(ACTUAL / "call_585_goal_plan_22.json")["output"]
    drama_request = workflow.prepare_goal_drama_audit_request(inputs, profile(), goal)
    actual = final_wire(drama_request)
    schema = drama_request["request"]["structured_schema"]
    scopes = workflow.drama_contract.build_scope_source_catalog(goal)
    assert set(schema["properties"]["scope_observations"]["properties"]) == set(scopes)
    assert "G083" in scopes and "G107" in scopes and any(row["source_scope"] == "ending" for row in scopes.values())
    assert "commitment_checks" not in schema["properties"] and "commitment_checks" not in schema["required"]
    assert "creative_commitment_usage_catalog" not in actual
    assert "commitment_checks" not in drama_request["wire"]["messages"][0]["content"]
    shared = schema["$defs"]["scope_source_observations"]["properties"]
    for table in ("audible_speakers", "operated_props"):
        definition = workflow.STAGE_RESPONSIBILITY_CONTRACT["scope_observation_definitions"][table]
        assert shared[table]["description"] == definition["include"] + "；不包括" + definition["exclude"]
    assert workflow.contexts._reference_occurrences(actual, inputs["reference_fulltext"]) == 1
    focus = workflow.prepare_goal_commitment_audit_request(inputs, profile(), goal)
    assert "commitment_checks" in focus["request"]["structured_schema"]["required"]
    assert payload(focus)["creative_commitment_usage_catalog"] == workflow.commitment_audit.build_commitment_usage_catalog(goal)


@pytest.mark.parametrize("target", ["native_version", "native_sha", "compiled_holder", "compiled_expected_state", "fact_projection"])
def test_opening_or_compiler_tamper_blocks_current_request_before_dispatch(causal_scenario, target):
    inputs, goal, opening, ids, native = new_case(causal_scenario)
    views = workflow.compile_native_views(goal, opening, **ids)
    if target == "native_version": views["opening_setup"]["schema"] = old_setups.VERSION
    elif target == "native_sha": views["opening_setup"]["goal_sha256"] = "0" * 64
    elif target == "compiled_holder": views["brief"]["initial_state"]["prop_states"][0]["holder_character_id"] = "worker"
    elif target == "compiled_expected_state": views["brief"]["initial_state"]["prop_states"][1]["expected_state"] = '{"kind":"absent","orientation":null}'
    else: views["fact_projection"]["policy"] = "manual_patch"
    with pytest.raises(ValueError): workflow.prepare_full_review_part_request(inputs, profile(), native, views, "semantic")


def test_actual_setup_request_has_new_absent_branch_and_rule_without_old_receipt_conversion():
    if not ACTUAL.exists(): pytest.skip("read-only actual585 fixture absent")
    paths = [ACTUAL / name for name in ("call_585_goal_plan_22.json", "call_589_opening_setup_01.json",
        "call_590_opening_setup_02.json", "STATE.json", "CALL_LEDGER.json", "PRODUCTION_FREEZE.json")]
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    inputs, goal = read(ACTUAL / "INPUTS.json"), read(paths[0])["output"]
    prepared = workflow.prepare_opening_setup_request(inputs, profile(), goal)
    final_wire(prepared)
    assert prepared["request"]["structured_schema"]["properties"]["schema"]["const"] == setups.VERSION
    assert setups.OPENING_SETUP_RULE in prepared["request"]["messages"][0]["content"]
    branches = prepared["request"]["structured_schema"]["properties"]["props"]["properties"]["pr_water"]["oneOf"]
    absent = next(row for row in branches if row["properties"]["kind"]["const"] == "absent")
    assert set(absent["properties"]) == {"kind"}
    for p in paths[1:3]:
        with pytest.raises(setups.OpeningSetupContractError): workflow.validate_opening_setup_document(read(p)["output"], goal)
    assert before == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
