"""Native part requests and relevance projection, with no service calls."""
from copy import deepcopy
import json
import socket

import pytest

from scripts.creative_m31_flash_role_clients_v1 import expected_wire_request
from src.content_factory import creative_goal_context_workflow_v8 as workflow
from tests.test_creative_goal_context_workflow_v7_independent_audit import causal_scenario, prior_scenario


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("workflow v8 tests must not contact providers")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def payload(prepared):
    return json.loads(prepared["request"]["messages"][1]["content"])


def native_views(scenario):
    return workflow.compile_native_views(scenario[2], scenario[3], **scenario[5])


@pytest.mark.parametrize("part", ["semantic", "physical"])
def test_actual_part_request_preserves_complete_native_sources_and_refreshes_wire(causal_scenario, part):
    inputs, profile, goal, opening, _, _, native = causal_scenario
    views = native_views(causal_scenario)
    original = deepcopy((inputs, native, views))
    prepared = workflow.prepare_full_review_part_request(inputs, profile, native, views, part)
    actual = payload(prepared)
    assert actual["native_goal_document"] == goal
    assert actual["native_opening_setup_document"] == opening
    assert actual["native_script_document"] == native
    assert not any(key in actual for key in ("brief", "creative_scene_plan", "full_current_script", "source_packet", "origin_catalog"))
    assert (inputs, native, views) == original
    assert prepared["wire"] == expected_wire_request(prepared["request"])
    assert prepared["request_sha256"] == workflow.digest(prepared["request"])
    assert prepared["part_context_sha256"] == workflow.digest(actual)
    assert prepared["manifest"]["payload_identity"] == workflow.contexts._measure(actual)
    assert prepared["request"]["input_provenance"]["part_context_sha256"] == workflow.digest(actual)
    assert prepared["request"]["structured_schema"]["properties"]["context_sha256"]["const"] == workflow.digest(actual)
    assert not prepared["dispatch_performed"] and prepared["sdk_max_retries"] == 0
    for identifier, witness in actual["evidence_catalog"].items():
        path = witness["document_path"].split(".")
        step = actual[path[0]]["beats"][int(path[2])]["steps"][int(path[4])]
        assert step["kind"] == witness["kind"] and step["speaker"] == witness["speaker"]
        assert "quote" not in witness
    assert actual["compiled_initial_atoms"]["initial:prop:book"]["holder_character_id"] is None
    assert actual["compiled_initial_atoms"]["initial:prop:pen"]["support_entity_id"] == "book"
    assert actual["initial_evidence_catalog"]["initial:prop:pen"]["value"] == opening["props"]["pen"]
    assert goal["whole_plan"]["characters"][0]["profile"]["wardrobe"] in prepared["request"]["messages"][1]["content"]


def test_two_parts_share_exact_six_sources_but_own_disjoint_context_and_nonzero_tables(causal_scenario):
    inputs, profile, _, _, _, _, native = causal_scenario
    views = native_views(causal_scenario)
    semantic = workflow.prepare_full_review_part_request(inputs, profile, native, views, "semantic")
    physical = workflow.prepare_full_review_part_request(inputs, profile, native, views, "physical")
    sem, phy = payload(semantic), payload(physical)
    assert sem["same_source_sha256"] == phy["same_source_sha256"]
    assert semantic["review_legal_context"] == physical["review_legal_context"] == sem["verified_legal_context"]
    assert semantic["part_context_sha256"] != physical["part_context_sha256"]
    assert sem["reference_fulltext"] == inputs["reference_fulltext"]
    assert workflow.contexts._reference_occurrences(sem, inputs["reference_fulltext"]) == 1
    assert workflow.contexts._reference_occurrences(phy, inputs["reference_fulltext"]) == 0
    assert not any(key in phy for key in ("verified_legal_context", "trend_label_context", "user_goal_contract", "expression_standards"))
    assert sem["trend_label_context"]["authority"] == "metadata_only_not_law_or_story_truth"
    required = []
    for prepared in (semantic, physical):
        actual = payload(prepared)
        owned = actual["review_table_contract"]
        assert actual["part_coverage_catalog"] == owned["coverage"]
        schema_fields = prepared["request"]["structured_schema"]["properties"]
        assert all(table in schema_fields for table in owned["required_tables"])
        assert all(table not in schema_fields for table in owned["omitted_zero_tables"])
        assert all(ids for ids in owned["coverage"].values())
        required += list(owned["coverage"])
    expected = workflow.reviews.review_table_contract(
        workflow.validate_script_document(native, views, inputs["production_preferences"])["script"], views["brief"], views["plan"])
    assert set(required) == set(expected["coverage"])
    assert {"legal_claims", "review_limitations"}.issubset(sem["review_table_contract"]["required_tables"])
    assert len(required) == len(set(required))
    assert physical["manifest"]["payload_identity"]["characters"] < semantic["manifest"]["payload_identity"]["characters"]
    assert next(row for row in physical["manifest"]["field_manifest"] if row["path"] == "verified_legal_context")["disposition"] == "omitted"


@pytest.mark.parametrize("target", ["compiled_holder", "compiled_ending", "facts", "fact_projection"])
def test_compiler_or_fact_manifest_tamper_prevents_part_preparation(causal_scenario, target):
    inputs, profile, _, _, _, _, native = causal_scenario
    views = native_views(causal_scenario)
    if target == "compiled_holder":
        views["brief"]["initial_state"]["prop_states"][0]["holder_character_id"] = "worker"
    elif target == "compiled_ending":
        views["plan"]["ending"]["attempt_result"] = "无原生来源的结果"
    elif target == "facts":
        views["brief"]["facts"] = []
    else:
        views["fact_projection"]["policy"] = "manual_patch"
    with pytest.raises(ValueError, match="compiled views"):
        workflow.prepare_full_review_part_request(inputs, profile, native, views, "semantic")


@pytest.mark.parametrize("identifier", ["OPERATING_STRATEGY_1", "UNRELATED_NAME", "CC_CTA"])
@pytest.mark.parametrize("referenced", [False, True])
def test_fact_projection_is_driven_by_native_references_not_claim_names(causal_scenario, identifier, referenced):
    inputs, profile, goal, opening, _, ids, native = deepcopy(causal_scenario)
    choice = {"id": identifier, "kind": "creative_choice", "text": "合成运营或设计选择；本测试不判断正文质量。", "origin_ids": []}
    goal["claims"].append(choice)
    if referenced:
        goal["whole_plan"]["beats"][0]["claim_refs"].append(identifier)
    opening["goal_sha256"] = workflow.digest(goal)
    before = deepcopy((goal, opening))
    views = workflow.compile_native_views(goal, opening, **ids)
    fact_ids = {row["id"] for row in views["brief"]["facts"]}
    assert (identifier in fact_ids) is referenced
    assert choice in views["goal"]["claims"] and choice in views["brief"]["typed_claim_registry"]
    projection = views["fact_projection"]
    assert projection["policy"] == workflow.FACT_PROJECTION_POLICY
    assert (identifier in projection["omitted_unreferenced_claim_ids"]) is (not referenced)
    assert projection["limitation"] == workflow.FACT_PROJECTION_LIMITATION
    assert (goal, opening) == before


def test_ending_reference_alone_can_create_a_narrative_requirement(causal_scenario):
    goal, opening, ids = deepcopy(causal_scenario[2]), deepcopy(causal_scenario[3]), causal_scenario[5]
    goal["claims"].append({"id": "END_REQUIREMENT", "kind": "creative_choice", "text": "合成结尾选择", "origin_ids": []})
    goal["whole_plan"]["ending"]["claim_refs"].append("END_REQUIREMENT")
    opening["goal_sha256"] = workflow.digest(goal)
    assert "END_REQUIREMENT" in {row["id"] for row in workflow.compile_native_views(goal, opening, **ids)["brief"]["facts"]}


def test_new_author_request_uses_v8_exact_relevance_views_and_native_setup(causal_scenario):
    inputs, profile, goal, opening, bundle, ids, _ = causal_scenario
    prepared = workflow.prepare_script_request(inputs, profile, goal, bundle, opening_setup=opening, **ids)
    actual = payload(prepared)
    assert actual["brief"] == native_views(causal_scenario)["brief"]
    assert actual["native_goal_document"] == goal and actual["native_opening_setup_document"] == opening
    assert prepared["manifest"]["fact_projection"] == prepared["views"]["fact_projection"]
    assert prepared["request"]["input_provenance"]["workflow_version"] == workflow.VERSION
    assert prepared["wire"] == expected_wire_request(prepared["request"])


def test_old_single_review_entry_and_unknown_part_are_rejected(causal_scenario):
    inputs, profile, _, _, _, _, native = causal_scenario
    views = native_views(causal_scenario)
    with pytest.raises(ValueError, match="two provider-native"):
        workflow.prepare_full_review_request(inputs, profile, native, views)
    with pytest.raises(ValueError, match="semantic or physical"):
        workflow.prepare_full_review_part_request(inputs, profile, native, views, "combined")
