"""Fresh synthetic world additions; no original report is converted to pass."""
from copy import deepcopy
import json
from pathlib import Path
import socket

import pytest
from jsonschema import Draft202012Validator, ValidationError

from src.content_factory import creative_goal_context_workflow_v28 as w
from scripts import creative_world_scene_text_driver_v1 as driver
from scripts.creative_m31_flash_role_clients_v1 import expected_wire_request
from tests.test_creative_world_scene_context_v1 import case as world_case, profile
from tests.test_creative_legal_speech_scope_v2 import synthetic_scope, add_ambiguity
from tests.test_creative_scoped_source_review_v2 import synthetic_review

ROOT = Path(__file__).resolve().parents[1] / "data/production_trials/legal_scoped_text_session_20261015/round_01"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs): raise AssertionError("world workflow is pure/offline only")
    monkeypatch.setattr(socket.socket, "connect", deny); monkeypatch.setattr(socket, "create_connection", deny)


def payload(prepared): return json.loads(prepared["request"]["messages"][1]["content"])


@pytest.fixture
def case():
    goal, native = world_case.__wrapped__()
    inputs = json.loads((ROOT / "INPUTS.json").read_text("utf-8-sig"))
    setup = json.loads((ROOT / "call_633_opening_setup_02.json").read_text("utf-8-sig"))["output"]
    setup.update(schema=w.OPENING_SETUP_VERSION, goal_sha256=w.digest(goal))
    return inputs, goal, setup, native


def audits(inputs, goal):
    """Brand-new synthetic reviewer objects, not old631/635 projections."""
    scoped = synthetic_scope(goal)
    for ref in w.metadata_reference_catalog(goal): scoped["records_by_ref"][ref] = {"act": "N"}
    source_request = w.prepare_goal_scoped_source_request(inputs, profile(), goal, scoped)
    source = synthetic_review(goal, scoped, source_request["scoped_source_context"])
    drama_request = w.prepare_goal_drama_audit_request(inputs, profile(), goal)
    first = next(ref for ref in w.legacy.drama_contract.build_evidence_catalog(goal) if ref.startswith("G"))
    row = {"status": "pass", "reason": "OFFLINE synthetic control, not semantic gold", "required_revision": "",
        "evidence_refs": [first], "counterexample_analysis": "OFFLINE current source fields only", "counterevidence_refs": []}
    drama = {"schema": w.legacy.DRAMA_AUDIT_VERSION, "goal_sha256": w.digest(goal),
        "audit_context_sha256": drama_request["audit_context_sha256"], "goal_checks": {key: deepcopy(row) for key in w.legacy.GOAL_CHECKS},
        "scope_observations": {ref: {"audible_speakers": [], "operated_props": []}
            for ref in w.legacy.drama_contract.build_scope_source_catalog(goal)}, "closed_scope_findings": []}
    focused_request = w.prepare_goal_commitment_audit_request(inputs, profile(), goal)
    checks = {}
    all_g = [ref for ref in w.legacy.commitment_audit.build_evidence_catalog(goal) if ref.startswith("G")]
    for claim_id, item in w.legacy.commitment_audit.build_commitment_usage_catalog(goal).items():
        checks[claim_id] = {"claim_ref": item["claim_ref"], "literal_requirement": "OFFLINE synthetic requirement",
            "actual_usages": {key: {"evidence_refs": [use["evidence_refs"][0]], "comparison_refs": [all_g[0]],
                "requirement_scope": "background_consistency", "actual_interpretation": "OFFLINE new synthetic usage",
                "relationship": "compatible"} for key, use in item["usages"].items()},
            "status": "pass", "reason": "OFFLINE new object, not old approval", "required_revision": "", "counterevidence_refs": []}
    focused = {"schema": w.legacy.commitment_audit.VERSION, "goal_sha256": w.digest(goal),
        "audit_context_sha256": focused_request["audit_context_sha256"], "commitment_checks": checks}
    return w.build_goal_audit_bundle(scoped, source, focused, drama)


def wire_check(prepared):
    assert prepared["wire"] == expected_wire_request(prepared["request"])
    assert prepared["request_sha256"] == w.digest(prepared["request"])
    assert prepared["manifest"]["structured_schema_sha256"] == w.digest(prepared["request"]["structured_schema"])
    assert prepared["request"]["input_provenance"]["context_manifest_sha256"] == w.digest(prepared["manifest"])
    assert prepared["manifest"]["payload_identity"] == w.contexts._measure(payload(prepared))
    assert not prepared["production_dispatch_eligible"] and prepared["provider_calls"] == 0


def test_actual_four_audits_writer_compile_render_and_whole_feedback(case):
    inputs, goal, setup, native = case; before = deepcopy(case)
    bundle = audits(inputs, goal)
    decision = w.validate_goal_audit(bundle, goal, inputs=inputs)
    assert decision["valid"] and decision["accepted"] and not decision["paired_snapshot_approval_required"]
    prepared = [w.prepare_goal_request(inputs, profile()), w.prepare_goal_scope_request(inputs, profile(), goal),
        w.prepare_goal_scoped_source_request(inputs, profile(), goal, bundle["native_scope_audit"]),
        w.prepare_goal_commitment_audit_request(inputs, profile(), goal), w.prepare_goal_drama_audit_request(inputs, profile(), goal),
        w.prepare_opening_setup_request(inputs, profile(), goal)]
    for item in prepared: wire_check(item)
    for item in prepared[1:5]:
        frame = payload(item)["native_goal_evidence_view"]
        assert w.legacy.evidence_view.reconstruct_goal(frame) == goal
    authored = w.prepare_script_request(inputs, profile(), goal, bundle, opening_setup=setup, **w.origin_ids(inputs))
    wire_check(authored)
    assert payload(authored)["native_goal_document"] == goal
    assert "full_prior_script" not in payload(authored)["production_preferences"].get("prior_story_scope", {})
    assert "full_prior_script" in inputs["production_preferences"]["prior_story_scope"]
    assert authored["manifest"]["reference_occurrences"] == 1
    Draft202012Validator(authored["request"]["structured_schema"]).validate(native)
    result = w.validate_script_document(native, authored["views"], inputs["production_preferences"])
    compiled = result["script"]
    assert {k: v for k, v in compiled.items() if k != "selected_candidate_id"} == native
    assert result["compiler_manifest"]["native_script_sha256"] == w.digest(native)
    assert "世界框架" in w.render_script(native, goal) and native["scene_contexts"][0]["story_time"]["label"] in w.render_script(native, goal)
    diagnostics = {"complete_same_source_part_review": {"OFFLINE": "functional gap, no rewritten sentence"}}
    revised = w.prepare_script_request({**inputs, "previous_complete_document": native, "revision_diagnostics": diagnostics},
        profile(), goal, bundle, opening_setup=setup, **w.origin_ids(inputs))
    assert payload(revised)["previous_complete_document"] == native and payload(revised)["revision_diagnostics"] == diagnostics
    assert "full_prior_script" not in payload(revised)["production_preferences"].get("prior_story_scope", {})
    assert case == before


def test_metadata_only_exact_foreign_paths_not_natural_language_and_source_challenge(case):
    inputs, goal, _, _ = case
    catalog = w.metadata_reference_catalog(goal); assert catalog
    goal["whole_plan"]["world_frame"]["social_context"] = goal["whole_plan"]["characters"][0]["id"]
    natural_ref = next(ref for ref, row in w.prior.scope_audit.evidence.build_evidence_catalog(goal).items()
        if row["document_path"] == "whole_plan.world_frame.social_context")
    assert natural_ref not in w.metadata_reference_catalog(goal)
    scoped = synthetic_scope(goal)
    for ref in w.metadata_reference_catalog(goal): scoped["records_by_ref"][ref] = {"act": "N"}
    request = w.prepare_goal_scope_request(inputs, profile(), goal)
    assert request["wire"]["tools"][0]["function"]["parameters"] == request["request"]["structured_schema"]
    assert w.validate_goal_scope(scoped, goal, context_sha256=request["scope_context_sha256"], inputs=inputs)["valid"]
    bad = deepcopy(scoped); bad["records_by_ref"][next(iter(catalog))] = {"act": "F"}
    with pytest.raises(ValidationError): w.validate_goal_scope(bad, goal, context_sha256=request["scope_context_sha256"], inputs=inputs)
    source = w.prepare_goal_scoped_source_request(inputs, profile(), goal, scoped)
    refs = source["request"]["structured_schema"]["properties"]["scope_challenges"]["items"]["properties"]["source_ref"]["enum"]
    assert natural_ref in refs and not (set(refs) & set(w.metadata_reference_catalog(goal)))


def test_old_goal_setup_and_reports_cannot_adopt_new_fields(case):
    inputs, goal, setup, native = case
    old_goal = w.world.legacy_goal_checking_projection(goal)
    assert not w.diagnose_goal_document(old_goal, inputs=inputs)["valid"]
    old_setup = w.legacy_opening_setup_checking_projection(setup, goal)
    with pytest.raises(ValidationError): w.validate_opening_setup_document(old_setup, goal)
    bundle = audits(inputs, goal); bundle["native_drama_audit"]["goal_sha256"] = w.digest(old_goal)
    with pytest.raises((ValueError, ValidationError)): w.prepare_script_request(inputs, profile(), goal, bundle,
        opening_setup=setup, **w.origin_ids(inputs))


def test_driver_unknown_and_preparation_fault_stop_without_retry_or_credentials(case):
    inputs, _, _, _ = case
    scenario = {"schema": driver.SCENARIO_VERSION, "synthetic": True, "inputs": inputs, "profile": profile(),
        "documents": {"whole_plan_01": {"kind": "transport_unknown", "output": None}}}
    result = driver.run_mock(scenario)
    assert result["status"] == "halt_unknown_or_protocol" and len(result["calls"]) == 1 and result["provider_calls"] == 0
    scenario["profile"] = {}
    result = driver.run_mock(scenario)
    assert result["status"] == "halt_offline_preparation_contract" and result["calls"] == []


def mock_scenario(case, *, first_semantic="pass"):
    """Static new reviewer documents, explicitly not semantic gold or SDK proof."""
    from tests.test_creative_full_review_protocol_v6 import synthetic_full_reports
    inputs, goal, setup, native = deepcopy(case)
    bundle = audits(inputs, goal)
    documents = {"whole_plan_01": {"kind": "known_complete", "output": goal},
        "opening_setup_01": {"kind": "known_complete", "output": setup}}
    for kind in w.AUDITS:
        documents[kind + "_audit_01"] = {"kind": "known_complete", "output": bundle["native_" + kind + "_audit"]}
    authored = w.prepare_script_request(inputs, profile(), goal, bundle, opening_setup=setup, **w.origin_ids(inputs))
    versions = [native]
    if first_semantic == "fail":
        new_native = deepcopy(native); new_native["title"] = "OFFLINE完整第2稿，非内容质量结论"
        for beat in new_native["beats"]:
            for rows in beat["ensemble"].values():
                for row in rows: row["expression"] = "OFFLINE第2稿完整原生表演设定，保持聆听。"
        versions.append(new_native)
    for version, script in enumerate(versions, 1):
        views = deepcopy(authored["views"])
        views["compiled_script"] = w.validate_script_document(script, views, inputs["production_preferences"])["script"]
        prepared = {part: w.prepare_full_review_part_request(inputs, profile(), script, views, part)
            for part in ("semantic", "physical")}
        contexts = {part: value["part_context_sha256"] for part, value in prepared.items()}
        reports = synthetic_full_reports(views, prepared["semantic"]["review_legal_context"], contexts,
            prior_story_scope=inputs["production_preferences"].get("prior_story_scope"))
        if version == 1 and first_semantic != "pass":
            row = next(iter(reports["semantic"]["world_scene_checks"].values()))
            row.update(status=first_semantic, reason="OFFLINE current full-text functional control", required_revision=(
                "Submit a complete new native script with readable context" if first_semantic == "fail" else ""))
            reports["semantic"]["revision_target"] = "script" if first_semantic == "fail" else "none"
        documents[f"complete_script_{version:02}"] = {"kind": "known_complete", "output": script}
        for part in reports: documents[f"full_review_{part}_{version:02}"] = {"kind": "known_complete", "output": reports[part]}
    return {"schema": driver.SCENARIO_VERSION, "synthetic": True, "inputs": inputs, "profile": profile(), "documents": documents}


def test_full_mock_world_double_review_compile_render_and_segment(case):
    scenario = mock_scenario(case); result = driver.run_mock(scenario)
    assert result["status"] == "offline_mock_contract_closure", result.get("stop_details")
    assert len(result["calls"]) == 9
    assert result["native_script"] == scenario["documents"]["complete_script_01"]["output"]
    assert result["native_script_sha256"] != result["compiled_script_sha256"]
    assert "世界框架" in result["rendered_script"] and "参与人物" in result["rendered_script"]
    for call in result["calls"]:
        wire_check(call["prepared"])
        if call["label"].startswith("full_review_"):
            actual = payload(call["prepared"])
            assert actual["native_goal_document"] == result["native_goal"]
            assert actual["native_script_document"] == result["native_script"]
            assert actual["native_opening_setup_document"] == result["native_opening_setup"]
            assert "temporal_relation_catalog" in actual
            assert "full_prior_script" not in actual["production_preferences"].get("prior_story_scope", {})
            if call["label"] == "full_review_semantic_01":
                assert actual["prior_story_scope"] == scenario["inputs"]["production_preferences"]["prior_story_scope"]
            else:
                assert "prior_story_scope" not in actual
    semantic = next(row for row in result["calls"] if row["label"] == "full_review_semantic_01")["prepared"]
    assert semantic["manifest"]["reference_occurrences"] == 1
    assert result["decision"]["complete_same_source_full_review"] and result["decision"]["accepted"]
    segment = result["first_segment_context"]
    assert segment["world_frame"] == result["native_goal"]["whole_plan"]["world_frame"]
    assert segment["current_beat"] == result["native_script"]["beats"][0]
    assert not segment["actual_media_request_connected"] and not segment["upcoming_event_is_already_executed"]
    assert not segment["previous_script_event_is_verified_executed"]
    assert result["provider_calls"] == result["production_claims"] == 0
    assert not result["creative_quality_passed"] and not result["text_ready_for_director"]


def test_known_full_review_failure_rewrites_complete_native_and_rebuilds_both_reviews(case):
    scenario = mock_scenario(case, first_semantic="fail"); result = driver.run_mock(scenario)
    assert result["status"] == "offline_mock_contract_closure", result.get("stop_details")
    labels = [row["label"] for row in result["calls"]]
    assert "full_review_physical_01" not in labels
    assert labels[-3:] == ["complete_script_02", "full_review_semantic_02", "full_review_physical_02"]
    writer2 = next(row for row in result["calls"] if row["label"] == "complete_script_02")["prepared"]
    actual = payload(writer2)
    assert actual["previous_complete_document"] == scenario["documents"]["complete_script_01"]["output"]
    assert actual["revision_diagnostics"]["native_part_reviews"]["semantic"] == scenario["documents"]["full_review_semantic_01"]["output"]
    assert result["native_script"] == scenario["documents"]["complete_script_02"]["output"]
    assert result["native_script"] != actual["previous_complete_document"]
    assert not result["production_dispatch_eligible"] and result["provider_calls"] == 0


def test_actual_native_review_unknown_stops_before_physical_or_new_body(case):
    scenario = mock_scenario(case, first_semantic="unknown"); result = driver.run_mock(scenario)
    assert result["status"] == "halt_review_unknown", result.get("stop_details")
    assert result["calls"][-1]["label"] == "full_review_semantic_01"
    assert all(row["label"] not in ("full_review_physical_01", "complete_script_02") for row in result["calls"])
    assert result["provider_calls"] == 0 and not result["creative_quality_passed"]
