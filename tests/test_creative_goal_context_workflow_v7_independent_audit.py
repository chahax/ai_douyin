"""Independent native-position and counterexample request audit, offline only."""
from copy import deepcopy
import json
import socket

from jsonschema import ValidationError
import pytest

from scripts.creative_m31_flash_role_clients_v1 import expected_wire_request
from src.content_factory import creative_goal_context_workflow_v7 as workflow
from src.content_factory import creative_goal_source_contract_v4 as goals
from src.content_factory import creative_opening_setup_contract_v2 as setups
from tests.test_creative_goal_context_workflow_v3 import scenario as prior_scenario


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("independent workflow audit may not contact a provider")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def payload(prepared):
    return json.loads(prepared["request"]["messages"][1]["content"])


@pytest.fixture
def causal_scenario(prior_scenario):
    inputs, profile, goal, _, _, native = deepcopy(prior_scenario)
    goal["contract_version"] = goals.VERSION
    goal["whole_plan"]["props"] = [{key: prop[key] for key in ("id", "description", "owner_character_id")}
                                    for prop in goal["whole_plan"]["props"]]
    goal["whole_plan"]["props"].append({"id": "pen", "description": "合成夹具中的员工笔",
                                        "owner_character_id": "worker"})
    opening = {"schema": setups.VERSION, "goal_sha256": setups.digest(goal),
        "characters": {actor["id"]: deepcopy(actor["initial_state"])
                       for actor in goal["whole_plan"]["characters"]},
        "props": {"book": {"kind": "scene", "scene_id": "room", "location": "柜内搁板上", "orientation": None},
                  "paper": {"kind": "absent", "orientation": None},
                  "pen": {"kind": "prop", "container_prop_id": "book", "location": "封面内侧夹着", "orientation": None}}}
    native["beats"][1]["steps"][1]["text"] = "员工保持坐姿，记录本留在柜内搁板上，笔仍夹在封面内侧。"
    judgment = {"status": "pass", "reason": "合成仅测试来源与请求绑定，不是内容或质量金标", "required_revision": ""}
    source_req = workflow.prepare_goal_source_audit_request(inputs, profile, goal)
    drama_req = workflow.prepare_goal_drama_audit_request(inputs, profile, goal)
    reference = next(iter(workflow.citations.build_evidence_catalog(goal)))
    source = {"schema": workflow.SOURCE_AUDIT_VERSION, "goal_sha256": workflow.digest(goal),
        "audit_context_sha256": workflow.digest(payload(source_req)),
        "claim_checks": {claim["id"]: deepcopy(judgment) for claim in goal["claims"]}}
    drama = {"schema": workflow.DRAMA_AUDIT_VERSION, "goal_sha256": workflow.digest(goal),
        "audit_context_sha256": workflow.digest(payload(drama_req)),
        "goal_checks": {key: {**deepcopy(judgment), "evidence_refs": [reference],
            "counterexample_analysis": "合成对照仅测试反证字段，不宣称语义已证明", "counterevidence_refs": []}
            for key in workflow.GOAL_CHECKS}}
    return inputs, profile, goal, opening, workflow.build_goal_audit_bundle(source, drama), workflow.origin_ids(inputs), native


def author(scenario):
    inputs, profile, goal, opening, bundle, ids, _ = scenario
    return workflow.prepare_script_request(inputs, profile, goal, bundle, opening_setup=opening, **ids)


def test_setup_request_and_wire_use_exact_v2_schema_without_old_repair_or_pass_authority(causal_scenario):
    inputs, profile, goal, opening, *_ = causal_scenario
    prepared = workflow.prepare_opening_setup_request({**inputs,
        "previous_complete_document": {"old_goal": "not setup authority"},
        "revision_diagnostics": {"old_pass": "not setup authority"}}, profile, goal)
    actual = payload(prepared)
    assert actual["native_goal_document"] == goal
    assert actual["actor_initial_states"] == opening["characters"]
    assert actual["static_props"] == goal["whole_plan"]["props"]
    assert "previous_complete_document" not in actual and "revision_diagnostics" not in actual
    assert prepared["request"]["structured_schema"] == setups.build_schema(goal)
    assert prepared["wire"] == expected_wire_request(prepared["request"])
    assert prepared["request_sha256"] == workflow.digest(prepared["request"])
    assert prepared["request"]["input_provenance"]["native_goal_sha256"] == workflow.digest(goal)
    assert not prepared["dispatch_performed"] and prepared["sdk_max_retries"] == 0


def test_actual_author_review_catalog_preserves_native_scene_and_container_atoms(causal_scenario):
    inputs, profile, goal, opening, *_rest, native = causal_scenario
    prepared = author(causal_scenario)
    review = workflow.prepare_full_review_request(inputs, profile, native, prepared["views"])
    actual = payload(review)
    for request in (prepared, review):
        assert payload(request)["native_opening_setup_document"] == opening
        assert payload(request)["native_goal_document"] == goal
        assert request["request"]["input_provenance"]["native_opening_setup_sha256"] == workflow.digest(opening)
        assert request["wire"] == expected_wire_request(request["request"])
        assert request["request_sha256"] == workflow.digest(request["request"])
        assert request["manifest"]["reference_proof"]["payload_occurrences"] == 1
        assert not any(key in payload(request) for key in ("native_source_audit", "native_drama_audit", "native_full_review"))
    for identifier in ("book", "pen", "paper"):
        witness = actual["initial_evidence_catalog"]["initial:prop:" + identifier]
        assert witness["value"] == opening["props"][identifier]
        assert witness["origin"] == "native_opening_setup_document"
    props = {row["id"]: row for row in prepared["views"]["brief"]["initial_state"]["prop_states"]}
    assert props["book"]["support"] == {"entity_type": "scene", "entity_id": "room"}
    assert props["pen"]["support"] == {"entity_type": "prop", "entity_id": "book"}
    assert props["book"]["holder_character_id"] is None and props["pen"]["holder_character_id"] is None
    assert props["book"]["owner_character_id"] == props["pen"]["owner_character_id"] == "worker"
    assert props["paper"]["presence_at_start"] == "absent" and props["paper"]["support"] is None
    assert review["request"]["structured_schema"]["properties"]["opening_setup_sha256"]["const"] == workflow.digest(opening)
    assert review["request"]["structured_schema"]["properties"]["legal_context_sha256"]["const"] == workflow.digest(actual["verified_legal_context"])


def test_unresolved_counterevidence_cannot_coexist_with_pass_or_reach_author(causal_scenario):
    altered = list(deepcopy(causal_scenario))
    drama = altered[4]["native_drama_audit"]
    first = drama["goal_checks"]["closed_production_scope"]
    first["counterevidence_refs"] = first["evidence_refs"]
    before = deepcopy(drama)
    with pytest.raises(ValidationError):
        workflow.validate_goal_drama_audit(drama, altered[2], context_sha256=drama["audit_context_sha256"])
    with pytest.raises(ValidationError):
        author(altered)
    assert drama == before


@pytest.mark.parametrize("status", ["fail", "unknown"])
def test_explicit_counterexample_failure_or_uncertainty_blocks_author(causal_scenario, status):
    altered = list(deepcopy(causal_scenario))
    drama = altered[4]["native_drama_audit"]
    first = drama["goal_checks"]["closed_production_scope"]
    first.update(status=status, counterevidence_refs=first["evidence_refs"],
                 required_revision="完整新规划修正容器与副本因果" if status == "fail" else "")
    result = workflow.validate_goal_drama_audit(drama, altered[2], context_sha256=drama["audit_context_sha256"])
    assert result["valid"] and not result["accepted"]
    assert bool(result["uncertainties"]) == (status == "unknown")
    with pytest.raises(ValueError, match="must pass"):
        author(altered)


def test_whitespace_counterexample_analysis_is_not_substantive(causal_scenario):
    drama = deepcopy(causal_scenario[4]["native_drama_audit"])
    drama["goal_checks"]["closed_production_scope"]["counterexample_analysis"] = " \n\t"
    with pytest.raises(ValueError, match="substantive"):
        workflow.validate_goal_drama_audit(drama, causal_scenario[2], context_sha256=drama["audit_context_sha256"])


@pytest.mark.parametrize("target", ["holder", "support", "native_setup", "ending"])
def test_compiler_or_native_source_tamper_blocks_full_review_before_request(causal_scenario, target):
    inputs, profile, goal, opening, bundle, ids, native = causal_scenario
    views = deepcopy(author(causal_scenario)["views"])
    if target == "holder":
        views["brief"]["initial_state"]["prop_states"][0]["holder_character_id"] = "worker"
    elif target == "support":
        views["brief"]["initial_state"]["prop_states"][0]["support"] = {"entity_type": "actor", "entity_id": "worker"}
    elif target == "native_setup":
        views["opening_setup"]["props"]["book"]["location"] = "错误位置"
    else:
        views["plan"]["ending"]["visible_consequence"] = "没有原生来源的结果"
    before = deepcopy(views)
    with pytest.raises(ValueError):
        workflow.prepare_full_review_request(inputs, profile, native, views)
    assert views == before


def test_undeclared_container_open_atom_cannot_be_established_by_its_location_quote(causal_scenario):
    from tests import test_goal_context_text_production_v4 as old_helpers
    inputs, profile, goal, opening, bundle, ids, native = causal_scenario
    prepared = author(causal_scenario)
    full_request = workflow.prepare_full_review_request(inputs, profile, native, prepared["views"])
    body = payload(full_request)
    review = old_helpers.full_review(body)
    review.update(schema=workflow.reviews.VERSION, opening_setup_sha256=workflow.digest(opening))
    review["action_checks"]["E0003"]["preconditions"] = [{
        "entity_id": "book", "state_key": "open", "expected_value": True, "actual_value": True,
        "established_by": "initial:prop:book", "quote": "柜内搁板上"}]
    result = workflow.reviews.validate_full_review(review, body["full_current_script"],
        prepared["views"]["brief"], prepared["views"]["plan"], full_request["review_legal_context"],
        goal_contract=goal, opening_setup=opening)
    assert not result["valid"] and not result["accepted"], result
