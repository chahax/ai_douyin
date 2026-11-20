"""Independent offline audit: exact native setup and deterministic source views."""
from copy import deepcopy
import json

import pytest

from scripts.creative_m31_flash_role_clients_v1 import expected_wire_request
from src.content_factory import creative_goal_context_workflow_v6 as workflow
from src.content_factory import creative_goal_source_contract_v4 as goals
from src.content_factory import creative_opening_setup_contract_v1 as setups
from tests.test_creative_goal_context_workflow_v3 import scenario as prior_scenario


def payload(prepared):
    return json.loads(prepared["request"]["messages"][1]["content"])


@pytest.fixture
def audit_scenario(prior_scenario):
    inputs, profile, goal, _, ids, native_script = prior_scenario
    # Independent synthetic native fixture, never a production migration.
    goal = deepcopy(goal)
    goal["contract_version"] = goals.VERSION
    goal["whole_plan"]["props"] = [{key: prop[key] for key in ("id", "description", "owner_character_id")}
                                    for prop in goal["whole_plan"]["props"]]
    opening = {"schema": setups.VERSION, "goal_sha256": setups.digest(goal),
        "characters": {actor["id"]: deepcopy(actor["initial_state"])
                       for actor in goal["whole_plan"]["characters"]},
        "props": {"book": {"presence": "present", "holder_character_id": "worker",
                           "location": "员工手中", "orientation": None},
                  "paper": {"presence": "absent", "holder_character_id": None,
                            "location": None, "orientation": None}}}
    source, drama = workflow.prepare_goal_source_audit_request(inputs, profile, goal), workflow.prepare_goal_drama_audit_request(inputs, profile, goal)
    judgment = {"status": "pass", "reason": "合成来源判定，仅接线验证", "required_revision": ""}
    native_source = {"schema": workflow.SOURCE_AUDIT_VERSION, "goal_sha256": workflow.digest(goal),
        "audit_context_sha256": workflow.digest(payload(source)),
        "claim_checks": {claim["id"]: deepcopy(judgment) for claim in goal["claims"]}}
    ref = next(iter(workflow.citations.build_evidence_catalog(goal)))
    native_drama = {"schema": workflow.DRAMA_AUDIT_VERSION, "goal_sha256": workflow.digest(goal),
        "audit_context_sha256": workflow.digest(payload(drama)),
        "goal_checks": {key: {**deepcopy(judgment), "evidence_refs": [ref]} for key in workflow.GOAL_CHECKS}}
    bundle = workflow.build_goal_audit_bundle(native_source, native_drama)
    return inputs, profile, goal, opening, bundle, ids, native_script


def author(audit_scenario):
    inputs, profile, goal, opening, bundle, ids, _ = audit_scenario
    return workflow.prepare_script_request(inputs, profile, goal, bundle, opening_setup=opening, **ids)


def test_actual_setup_request_contains_only_same_goal_physical_authority(audit_scenario):
    inputs, profile, goal, opening, bundle, ids, _ = audit_scenario
    prepared = workflow.prepare_opening_setup_request(inputs, profile, goal)
    body = payload(prepared)
    assert body["native_goal_document"] == goal
    assert body["actor_initial_states"] == opening["characters"]
    assert body["static_props"] == goal["whole_plan"]["props"]
    assert "reference_fulltext" not in body and "verified_legal_context" not in body
    assert "previous_complete_document" not in body
    assert prepared["request"]["role"] == "writer"
    assert prepared["request"]["input_provenance"]["substage"] == "opening_setup"
    assert prepared["wire"] == expected_wire_request(prepared["request"])
    assert prepared["request"]["structured_schema"] == setups.build_schema(goal)
    assert prepared["dispatch_performed"] is False and prepared["sdk_max_retries"] == 0


def test_compiler_maps_only_declared_presence_holder_and_static_owner(audit_scenario):
    _, _, goal, opening, _, ids, _ = audit_scenario
    before = deepcopy((goal, opening))
    views = workflow.compile_native_views(goal, opening, **ids)
    props = {row["id"]: row for row in views["brief"]["initial_state"]["prop_states"]}
    assert props["book"]["support"] == {"entity_type": "actor", "entity_id": "worker"}
    assert props["paper"]["support"] is None and props["paper"]["location"] is None
    assert props["paper"]["presence_at_start"] == "absent"
    assert props["book"]["owner_character_id"] == goal["whole_plan"]["props"][0]["owner_character_id"]
    assert (goal, opening) == before and not views["native_values_rewritten"]
    assert views["brief"]["source_identity"]["native_goal_sha256"] == workflow.digest(goal)
    assert views["brief"]["source_identity"]["native_opening_setup_sha256"] == workflow.digest(opening)


def test_author_and_full_review_actual_wire_receive_identical_native_setup(audit_scenario):
    inputs, profile, goal, opening, _, _, native = audit_scenario
    prepared = author(audit_scenario)
    review = workflow.prepare_full_review_request(inputs, profile, native, prepared["views"])
    for request in (prepared, review):
        assert payload(request)["native_opening_setup_document"] == opening
        assert payload(request)["native_goal_document"] == goal
        assert request["request"]["input_provenance"]["native_opening_setup_sha256"] == workflow.digest(opening)
        assert request["request"]["input_provenance"]["native_goal_sha256"] == workflow.digest(goal)
        assert request["request_sha256"] == workflow.digest(request["request"])
        assert request["wire"] == expected_wire_request(request["request"])


@pytest.mark.parametrize("target", ["prop_holder", "prop_location", "actor_location", "plan_ending", "brief_goal_identity"])
def test_full_review_rejects_mutated_compiled_views_even_with_native_identity_retained(audit_scenario, target):
    inputs, profile, goal, opening, _, _, native = audit_scenario
    views = deepcopy(author(audit_scenario)["views"])
    if target == "prop_holder":
        views["brief"]["initial_state"]["prop_states"][0]["holder_character_id"] = "hr"
    elif target == "prop_location":
        views["brief"]["initial_state"]["prop_states"][0]["location"] = "未经原生setup定义的位置"
    elif target == "actor_location":
        views["brief"]["initial_state"]["character_states"][0]["location"] = "未经规划允许的座位"
    elif target == "plan_ending":
        views["plan"]["ending"]["visible_consequence"] = "不是原生规划结尾"
    else:
        views["brief"]["source_identity"]["native_goal_sha256"] = "0" * 64
    before = deepcopy(views)
    with pytest.raises(ValueError):
        workflow.prepare_full_review_request(inputs, profile, native, views)
    assert views == before


def test_opening_setup_revision_must_bind_same_goal_and_pair_full_native_diagnostics(audit_scenario):
    inputs, profile, goal, opening, *_ = audit_scenario
    with pytest.raises(ValueError, match="together"):
        workflow.prepare_opening_setup_request({**inputs, "previous_opening_setup": opening}, profile, goal)
    bad = deepcopy(opening)
    bad["goal_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="unchanged native goal"):
        workflow.prepare_opening_setup_request({**inputs, "previous_opening_setup": bad,
            "opening_setup_diagnostics": {"code": "known content failure"}}, profile, goal)


def test_absent_state_and_actor_mismatch_fail_before_author_request(audit_scenario):
    for target in ("absent", "actor"):
        altered = list(deepcopy(audit_scenario))
        if target == "absent":
            altered[3]["props"]["paper"]["holder_character_id"] = "hr"
        else:
            altered[3]["characters"]["worker"]["location"] = "桌子右侧"
        with pytest.raises(setups.OpeningSetupContractError):
            author(altered)


def test_structural_null_is_preserved_but_unplaced_present_prop_blocks_author(audit_scenario):
    _, _, goal, opening, _, ids, _ = audit_scenario
    opening["props"]["book"].update(holder_character_id=None, location=None)
    original = deepcopy(opening)
    assert setups.validate(opening, goal) == original
    with pytest.raises(setups.OpeningSetupContractError) as error:
        workflow.compile_native_views(goal, opening, **ids)
    assert error.value.code == "OPENING_SETUP_PRESENT_LOCATION_UNESTABLISHED"
    assert opening == original
    with pytest.raises(setups.OpeningSetupContractError):
        author(audit_scenario)


def test_held_prop_null_location_is_not_guessed_or_backfilled(audit_scenario):
    _, _, goal, opening, _, ids, _ = audit_scenario
    opening["props"]["book"]["location"] = None
    views = workflow.compile_native_views(goal, opening, **ids)
    prop = views["brief"]["initial_state"]["prop_states"][0]
    assert prop["presence_at_start"] == "present" and prop["support"] == {"entity_type": "actor", "entity_id": "worker"}
    assert prop["holder_character_id"] == "worker" and prop["location"] is None
    assert prop["owner_character_id"] == "worker"
    assert views["opening_setup"]["props"]["book"]["location"] is None
    assert author(audit_scenario)["views"]["opening_setup"]["props"]["book"]["location"] is None
