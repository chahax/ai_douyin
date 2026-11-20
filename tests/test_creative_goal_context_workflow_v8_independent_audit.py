"""Independent actual-wire scope audit, synthetic source only and zero sends."""
from copy import deepcopy
import json
import socket

import pytest

from scripts.creative_m31_flash_role_clients_v1 import expected_wire_request
from src.content_factory import creative_goal_context_workflow_v8 as workflow
from tests.test_creative_goal_context_workflow_v7_independent_audit import causal_scenario, prior_scenario


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("workflow audit must not send to a provider")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def body(request):
    return json.loads(request["request"]["messages"][1]["content"])


def author(scenario):
    inputs, profile, goal, setup, audits, ids, native = scenario
    return workflow.prepare_script_request(inputs, profile, goal, audits, opening_setup=setup, **ids)


@pytest.mark.parametrize("location", ["none", "beat", "ending"])
def test_arbitrary_named_operational_choice_is_selected_only_by_actual_native_narrative_refs(causal_scenario, location):
    inputs, profile, goal, setup, audits, ids, native = deepcopy(causal_scenario)
    identifier = "UNRELATED_NAME_NOT_CTA_FILTER"
    goal["claims"].append({"id": identifier, "kind": "creative_choice", "text": "账号运营安排：结合证据咨询，不承诺结果。"})
    if location == "beat":
        goal["whole_plan"]["beats"][0]["claim_refs"].append(identifier)
    elif location == "ending":
        goal["whole_plan"]["ending"]["claim_refs"].append(identifier)
    setup["goal_sha256"] = workflow.digest(goal)
    views = workflow.compile_native_views(goal, setup, **ids)
    selected = {row["id"] for row in views["brief"]["facts"]}
    assert (identifier in selected) is (location != "none")
    assert views["goal"] == goal and views["brief"]["typed_claim_registry"] == goal["claims"]
    assert views["plan"]["typed_claim_registry"] == goal["claims"]
    assert views["fact_projection"]["all_claims_preserved_in_native_goal_and_registry"]
    assert views["fact_projection"]["unreferenced_claims_promoted_to_literal_obligations"] is False
    for claim in goal["claims"]:
        if claim["kind"] != "creative_choice":
            assert claim not in views["brief"]["facts"]


def test_each_actual_part_reads_complete_native_body_goal_setup_with_six_same_source_hashes(causal_scenario):
    inputs, profile, goal, setup, audits, ids, native = causal_scenario
    prepared = author(causal_scenario)
    parts = [workflow.prepare_full_review_part_request(inputs, profile, native, prepared["views"], part)
             for part in ("semantic", "physical")]
    bodies = [body(part) for part in parts]
    assert bodies[0]["same_source_sha256"] == bodies[1]["same_source_sha256"]
    assert set(bodies[0]["same_source_sha256"]) == {"script_sha256", "brief_sha256", "plan_sha256", "legal_context_sha256",
        "goal_contract_sha256", "opening_setup_sha256"}
    for request, actual in zip(parts, bodies):
        assert actual["native_goal_document"] == goal and actual["native_opening_setup_document"] == setup
        assert actual["native_script_document"] == native
        assert not any(key in actual for key in ("brief", "creative_scene_plan", "full_current_script", "source_packet", "origin_catalog"))
        assert request["wire"] == expected_wire_request(request["request"])
        assert request["request_sha256"] == workflow.digest(request["request"])
        assert request["part_context_sha256"] == workflow.digest(actual)
        schema = request["request"]["structured_schema"]["properties"]
        for key, sha in actual["same_source_sha256"].items():
            assert schema[key]["const"] == sha
        assert request["request"]["input_provenance"]["part_context_sha256"] == request["part_context_sha256"]
        assert request["request"]["input_provenance"]["native_goal_sha256"] == workflow.digest(goal)
        assert request["request"]["input_provenance"]["native_opening_setup_sha256"] == workflow.digest(setup)
        for ref, entry in actual["evidence_catalog"].items():
            path = entry["document_path"].split(".")
            original = native["beats"][int(path[2])]["steps"][int(path[4])]
            assert original["kind"] == entry["kind"] and original["speaker"] == entry["speaker"]
        assert not request["dispatch_performed"] and request["sdk_max_retries"] == 0
    assert parts[0]["part_context_sha256"] != parts[1]["part_context_sha256"]


def test_semantic_retains_actual_reference_law_usergoal_and_labels_physical_omits_them(causal_scenario):
    inputs, profile, goal, setup, audits, ids, native = causal_scenario
    views = author(causal_scenario)["views"]
    semantic = workflow.prepare_full_review_part_request(inputs, profile, native, views, "semantic")
    physical = workflow.prepare_full_review_part_request(inputs, profile, native, views, "physical")
    a, b = body(semantic), body(physical)
    for key in ("reference_fulltext", "verified_legal_context", "user_goal_contract", "expression_standards", "trend_label_context"):
        assert key in a and key not in b
    assert a["reference_fulltext"] == inputs["reference_fulltext"]
    assert a["trend_label_context"]["authority"] == "metadata_only_not_law_or_story_truth"
    assert a["verified_legal_context"] == semantic["review_legal_context"] == physical["review_legal_context"]
    assert semantic["manifest"]["reference_proof"]["payload_occurrences"] == 1
    assert physical["manifest"]["reference_proof"]["payload_occurrences"] == 0
    assert a["native_goal_document"]["whole_plan"]["characters"] == b["native_goal_document"]["whole_plan"]["characters"]


@pytest.mark.parametrize("field", ["brief", "plan", "fact_projection"])
def test_compiler_identity_cannot_be_used_to_smuggle_modified_scope_into_part_request(causal_scenario, field):
    inputs, profile, goal, setup, audits, ids, native = causal_scenario
    views = deepcopy(author(causal_scenario)["views"])
    views[field]["injected"] = "tamper with same original hashes"
    with pytest.raises(ValueError, match="compiled views differ"):
        workflow.prepare_full_review_part_request(inputs, profile, native, views, "semantic")


def test_old_single_full_review_entry_cannot_silently_create_a_counterfeit_native_response():
    with pytest.raises(ValueError, match="two provider-native"):
        workflow.prepare_full_review_request()


def test_fresh_conception_actual_wire_keeps_exact_counterexamples_reference_and_authority(causal_scenario):
    inputs, profile, *_ = causal_scenario
    context = {"source_receipt_sha256": "d" * 64, "verified_failure_quotes": ["只写日期名字不等于写明通知事项"],
        "prior_creative_choices_are_replaceable": True}
    prepared = workflow.prepare_goal_request({**inputs, "fresh_reconception_context": context}, profile)
    actual = body(prepared)
    assert actual["fresh_reconception_context"] == context
    assert "previous_complete_document" not in actual and "revision_diagnostics" not in actual
    assert actual["reference_fulltext"] == inputs["reference_fulltext"]
    assert prepared["manifest"]["planning_mode"] == "fresh_complete_conception"
    assert prepared["manifest"]["previous_complete_document_sent"] is False
    assert prepared["manifest"]["payload_identity"] == workflow.contexts._measure(actual)
    assert prepared["manifest"]["input_identity"] == workflow.contexts._measure({**inputs, "fresh_reconception_context": context})
    assert prepared["manifest"]["reference_proof"]["payload_occurrences"] == 1
    fields = [row for row in prepared["manifest"]["field_manifest"] if row["path"] == "fresh_reconception_context"]
    assert len(fields) == 1 and fields[0]["disposition"] == "included"
    assert prepared["wire"] == expected_wire_request(prepared["request"])
    assert prepared["request_sha256"] == workflow.digest(prepared["request"])
    assert not prepared["dispatch_performed"] and prepared["sdk_max_retries"] == 0


@pytest.mark.parametrize("field", ["previous_complete_document", "revision_diagnostics"])
def test_fresh_and_native_revision_modes_are_mutually_exclusive(causal_scenario, field):
    inputs, profile, goal, *_ = causal_scenario
    with pytest.raises(ValueError, match="mutually exclusive"):
        workflow.prepare_goal_request({**inputs, "fresh_reconception_context": {"failure": "witnessed"}, field: goal}, profile)


@pytest.mark.parametrize("context", [{}, [], None])
def test_fresh_conception_cannot_silently_send_an_empty_untyped_context(causal_scenario, context):
    inputs, profile, *_ = causal_scenario
    with pytest.raises(ValueError, match="nonempty witnessed"):
        workflow.prepare_goal_request({**inputs, "fresh_reconception_context": context}, profile)


def test_same_run_native_revision_keeps_entire_prior_document_and_original_contract(causal_scenario):
    inputs, profile, goal, *_ = causal_scenario
    diagnostic = {"exact_error": "完整旧规划已有明确内容错误，需要完整原生新版本"}
    prepared = workflow.prepare_goal_request({**inputs, "previous_complete_document": goal, "revision_diagnostics": diagnostic}, profile)
    actual = body(prepared)
    assert actual["previous_complete_document"] == goal and actual["revision_diagnostics"] == diagnostic
    assert "fresh_reconception_context" not in actual
    assert prepared["wire"] == expected_wire_request(prepared["request"])
    with pytest.raises(ValueError, match="require the complete native previous version"):
        workflow.prepare_goal_request({**inputs, "revision_diagnostics": diagnostic}, profile)
