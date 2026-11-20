"""Separated native planning/setup integration; offline fixtures, no paid calls."""
from copy import deepcopy
import json

from jsonschema import Draft202012Validator, ValidationError
import pytest

from scripts.creative_m31_flash_role_clients_v1 import expected_wire_request
from src.content_factory import creative_goal_context_workflow_v6 as workflow
from tests.test_creative_goal_context_workflow_v3 import scenario as prior_scenario
from tests.test_creative_goal_source_contract_v4 import native_goal
from tests.test_creative_opening_setup_contract_v1 import native_setup


def payload(prepared):
    return json.loads(prepared["request"]["messages"][1]["content"])


@pytest.fixture
def scenario(prior_scenario):
    inputs, profile, _, _, ids, native_script = prior_scenario
    goal = native_goal()
    goal["claims"][2]["origin_ids"] = [ids["source_ids"][0]]
    goal["claims"][3]["origin_ids"] = [ids["legal_ids"][0]]
    # These omissions are new synthetic fixtures, never a repair of a provider result.
    goal["claims"][4].pop("origin_ids")
    goal["claims"][5].pop("origin_ids")
    setup = native_setup(goal)
    source = workflow.prepare_goal_source_audit_request(inputs, profile, goal)
    drama = workflow.prepare_goal_drama_audit_request(inputs, profile, goal)
    judgment = {"status": "pass", "reason": "合成合同判断，不是生产质量结论", "required_revision": ""}
    source_audit = {"schema": workflow.SOURCE_AUDIT_VERSION, "goal_sha256": workflow.digest(goal),
        "audit_context_sha256": workflow.digest(payload(source)),
        "claim_checks": {row["id"]: deepcopy(judgment) for row in goal["claims"]}}
    ref = next(iter(workflow.citations.build_evidence_catalog(goal)))
    drama_audit = {"schema": workflow.DRAMA_AUDIT_VERSION, "goal_sha256": workflow.digest(goal),
        "audit_context_sha256": workflow.digest(payload(drama)),
        "goal_checks": {key: {**deepcopy(judgment), "evidence_refs": [ref]} for key in workflow.GOAL_CHECKS}}
    bundle = workflow.build_goal_audit_bundle(source_audit, drama_audit)
    return inputs, profile, goal, setup, ids, native_script, bundle, source, drama


def author(scenario, **kwargs):
    inputs, profile, goal, setup, ids, _, bundle, *_ = scenario
    return workflow.prepare_script_request(inputs, profile, goal, bundle,
        opening_setup=kwargs.get("opening_setup", setup), **ids)


def test_static_goal_schema_and_request_are_new_native_v4(scenario):
    inputs, profile, goal, *_ = scenario
    request = workflow.prepare_goal_request(inputs, profile)
    schema = request["request"]["structured_schema"]
    assert schema["properties"]["contract_version"]["const"] == workflow.goals.VERSION
    assert set(schema["properties"]["whole_plan"]["properties"]["props"]["items"]["properties"]) == {
        "id", "description", "owner_character_id"}
    Draft202012Validator(schema).validate(goal)
    assert request["request"]["stage"] == "goal_plan" and request["request"]["role"] == "writer"
    assert request["wire"] == expected_wire_request(request["request"])


def test_native_source_and_complete_drama_keep_exact_v4_identity(scenario):
    inputs, _, goal, _, _, _, bundle, source, drama = scenario
    decision = workflow.validate_goal_audit(bundle, goal, inputs=inputs)
    assert decision["accepted"] and decision["combined_decisions_only"]
    assert payload(source)["native_goal_claims"] == goal["claims"]
    assert payload(drama)["native_goal_document"] == goal
    assert payload(source)["native_goal_sha256"] == workflow.digest(goal)
    assert "opening_setup" not in payload(source) and "opening_setup" not in payload(drama)
    for prepared in (source, drama):
        assert prepared["request"]["input_provenance"]["workflow_version"] == workflow.VERSION
        assert prepared["request_sha256"] == workflow.digest(prepared["request"])


def test_opening_request_has_only_current_goal_static_actors_props_and_functional_preferences(scenario):
    inputs, profile, goal, *_ = scenario
    altered = {**deepcopy(inputs), "previous_complete_document": {"old_goal": "八份旧稿不应进入setup"},
        "revision_diagnostics": {"old_goal_failure": "旧规划诊断不进入setup"}}
    prepared = workflow.prepare_opening_setup_request(altered, profile, goal)
    body = payload(prepared)
    assert set(body) == {"native_goal_document", "native_goal_sha256", "actor_initial_states",
        "static_props", "production_preferences"}
    assert body["native_goal_document"] == goal
    assert body["actor_initial_states"] == {row["id"]: row["initial_state"] for row in goal["whole_plan"]["characters"]}
    assert body["static_props"] == goal["whole_plan"]["props"]
    assert "prior_story_scope" not in body["production_preferences"]
    assert "source_packet" not in body and "verified_legal_context" not in body and "reference_fulltext" not in body
    assert prepared["manifest"]["reference_occurrences"] == 0
    assert prepared["manifest"]["upstream_goal_semantically_validated"] is False
    assert prepared["request"]["stage"] == "goal_plan" and prepared["request"]["role"] == "writer"
    assert prepared["request"]["input_provenance"]["substage"] == "opening_setup"
    assert prepared["wire"] == expected_wire_request(prepared["request"])
    assert prepared["request"]["structured_schema"]["properties"]["characters"]["properties"]["worker"]["properties"]["location"] == {"const": "桌子左侧"}
    assert not prepared["dispatch_performed"] and prepared["sdk_max_retries"] == 0


def test_compiler_keeps_both_native_versions_and_explicit_state_without_backfill(scenario):
    _, _, goal, setup, ids, *_ = scenario
    before = deepcopy((goal, setup))
    views = workflow.compile_native_views(goal, setup, **ids)
    assert views["goal"] == goal and views["goal"]["contract_version"] == "creative_goal_source_v4"
    assert views["opening_setup"] == setup
    assert "origin_ids" not in views["goal"]["claims"][4]
    assert not views["native_values_rewritten"] and not views["unspecified_detail_filled"]
    props = {row["id"]: row for row in views["brief"]["initial_state"]["prop_states"]}
    assert props["paper"]["presence_at_start"] == "absent"
    assert props["paper"]["holder_character_id"] is props["paper"]["support"] is props["paper"]["location"] is None
    assert props["book"]["location"] == setup["props"]["book"]["location"]
    assert props["book"]["support"] == {"entity_type": "actor", "entity_id": "worker"}
    assert views["brief"]["source_identity"]["native_opening_setup_sha256"] == workflow.digest(setup)
    assert (goal, setup) == before


def test_unheld_location_and_owner_never_become_guessed_support_or_holder(scenario):
    _, _, goal, setup, ids, *_ = scenario
    goal = deepcopy(goal)
    goal["whole_plan"]["props"][0]["owner_character_id"] = "hr"
    setup = deepcopy(setup)
    setup["goal_sha256"] = workflow.digest(goal)
    setup["props"]["book"].update(holder_character_id=None, location="桌面左侧", orientation="封面朝上")
    views = workflow.compile_native_views(goal, setup, **ids)
    state = views["brief"]["initial_state"]["prop_states"][0]
    assert state["owner_character_id"] == "hr" and state["holder_character_id"] is None
    assert state["support"] is None and state["location"] == "桌面左侧" and state["orientation"] == "封面朝上"


def test_structurally_known_unlocated_present_prop_requires_complete_setup_revision(scenario):
    _, _, goal, setup, ids, *_ = scenario
    setup = deepcopy(setup)
    setup["props"]["book"].update(holder_character_id=None, location=None)
    assert workflow.setups.validate(setup, goal) == setup
    before = deepcopy(setup)
    with pytest.raises(workflow.setups.OpeningSetupContractError) as error:
        workflow.compile_native_views(goal, setup, **ids)
    assert error.value.code == "OPENING_SETUP_PRESENT_LOCATION_UNESTABLISHED"
    assert error.value.detail["content_prerequisite_failed"] is True
    assert setup == before


def test_explicit_holder_allows_unknown_location_without_filling_it(scenario):
    _, _, goal, setup, ids, *_ = scenario
    setup = deepcopy(setup)
    setup["props"]["book"]["location"] = None
    views = workflow.compile_native_views(goal, setup, **ids)
    prop = views["brief"]["initial_state"]["prop_states"][0]
    assert prop["holder_character_id"] == "worker" and prop["location"] is None
    assert prop["support"] == {"entity_type": "actor", "entity_id": "worker"}


def test_author_binds_exact_native_audits_setup_goal_and_actual_wire(scenario):
    _, _, goal, setup, _, _, bundle, *_ = scenario
    prepared = author(scenario)
    body, provenance = payload(prepared), prepared["request"]["input_provenance"]
    assert body["native_goal_document"] == goal and body["native_opening_setup_document"] == setup
    assert provenance["native_opening_setup_sha256"] == workflow.digest(setup)
    assert provenance["native_goal_sha256"] == workflow.digest(goal)
    assert provenance["native_source_audit_sha256"] == workflow.digest(bundle["native_source_audit"])
    assert provenance["native_drama_audit_sha256"] == workflow.digest(bundle["native_drama_audit"])
    assert provenance["context_manifest_sha256"] == workflow.digest(prepared["manifest"])
    assert prepared["manifest"]["payload_identity"]["semantic_sha256"] == workflow.digest(body)
    assert prepared["wire"] == expected_wire_request(prepared["request"])


@pytest.mark.parametrize("mutation", [
    lambda setup: setup.update(goal_sha256="f" * 64),
    lambda setup: setup["characters"]["worker"].update(location="另一个工位"),
    lambda setup: setup["props"]["paper"].update(holder_character_id="hr"),
    lambda setup: setup["props"]["book"].pop("location"),
])
def test_wrong_missing_or_conflicting_native_setup_blocks_author_without_hand_repair(scenario, mutation):
    setup = deepcopy(scenario[3])
    mutation(setup)
    before = deepcopy(setup)
    with pytest.raises(workflow.setups.OpeningSetupContractError):
        author(scenario, opening_setup=setup)
    assert setup == before


@pytest.mark.parametrize("kind,status", [(kind, status) for kind in ("source", "drama") for status in ("fail", "unknown")])
def test_each_native_semantic_failure_or_unknown_still_blocks_author(scenario, kind, status):
    altered = list(deepcopy(scenario))
    table = "claim_checks" if kind == "source" else "goal_checks"
    row = next(iter(altered[6]["native_" + kind + "_audit"][table].values()))
    row.update(status=status, required_revision="完整新规划修改来源或因果缺口" if status == "fail" else "")
    with pytest.raises(ValueError, match="both native"):
        author(altered)


def test_missing_setup_cannot_fall_back_to_old_static_plan_state(scenario):
    inputs, profile, goal, _, ids, _, bundle, *_ = scenario
    with pytest.raises(TypeError, match="opening_setup"):
        workflow.prepare_script_request(inputs, profile, goal, bundle, **ids)


def test_setup_revision_uses_only_paired_same_goal_native_document_and_diagnostics(scenario):
    inputs, profile, goal, setup, *_ = scenario
    revised = {**deepcopy(inputs), "previous_opening_setup": deepcopy(setup),
        "opening_setup_diagnostics": {"findings": [{"path": "/props/paper/location", "message": "本地合成合同诊断"}]}}
    prepared = workflow.prepare_opening_setup_request(revised, profile, goal)
    assert payload(prepared)["previous_opening_setup"] == setup
    assert payload(prepared)["opening_setup_diagnostics"] == revised["opening_setup_diagnostics"]
    assert prepared["manifest"]["generation_mode"] == "bounded_content_revision"
    assert workflow.validate_goal_audit(scenario[6], goal, inputs=revised)["accepted"]


@pytest.mark.parametrize("alter", ["missing_previous", "missing_diagnostics", "changed_goal", "empty_diagnostics"])
def test_setup_repair_cannot_reuse_goal_diagnostics_or_change_source(scenario, alter):
    inputs, profile, goal, setup, *_ = scenario
    revised = {**deepcopy(inputs), "previous_opening_setup": deepcopy(setup), "opening_setup_diagnostics": {"issue": "synthetic"}}
    if alter == "missing_previous": revised.pop("previous_opening_setup")
    elif alter == "missing_diagnostics": revised.pop("opening_setup_diagnostics")
    elif alter == "changed_goal": revised["previous_opening_setup"]["goal_sha256"] = "f" * 64
    else: revised["opening_setup_diagnostics"] = {}
    with pytest.raises(ValueError):
        workflow.prepare_opening_setup_request(revised, profile, goal)


def test_full_native_script_revision_keeps_goal_audits_and_setup_intact(scenario):
    inputs, profile, goal, setup, ids, native, bundle, *_ = scenario
    revised = {**deepcopy(inputs), "previous_complete_document": deepcopy(native),
        "revision_diagnostics": {"full_review": "完整新稿修复合成问题"}}
    prepared = workflow.prepare_script_request(revised, profile, goal, bundle, opening_setup=setup, **ids)
    assert payload(prepared)["previous_complete_document"] == native
    assert payload(prepared)["native_opening_setup_document"] == setup
    assert prepared["manifest"]["generation_mode"] == "bounded_content_revision"


def test_full_review_keeps_native_v4_setup_and_binds_actual_projected_law(scenario):
    inputs, profile, goal, setup, _, native, *_ = scenario
    views = author(scenario)["views"]
    reviewed = workflow.prepare_full_review_request(inputs, profile, native, views)
    body = payload(reviewed)
    assert body["native_goal_document"] == goal
    assert body["native_opening_setup_document"] == setup
    assert reviewed["review_legal_context"] == body["verified_legal_context"]
    assert reviewed["request"]["structured_schema"]["properties"]["goal_contract_sha256"]["const"] == workflow.digest(goal)
    assert reviewed["request"]["structured_schema"]["properties"]["legal_context_sha256"]["const"] == workflow.digest(body["verified_legal_context"])
    assert reviewed["request"]["input_provenance"]["native_opening_setup_sha256"] == workflow.digest(setup)
    assert reviewed["manifest"]["payload_identity"]["semantic_sha256"] == workflow.digest(body)
    assert reviewed["wire"] == expected_wire_request(reviewed["request"])


@pytest.mark.parametrize("view", ["brief", "plan"])
def test_full_review_rejects_hand_changed_compiled_views(scenario, view):
    inputs, profile, _, _, _, native, *_ = scenario
    views = author(scenario)["views"]
    if view == "brief": views[view]["initial_state"]["prop_states"][0]["holder_character_id"] = "hr"
    else: views[view]["ending"]["visible_consequence"] += " hand patch"
    with pytest.raises(ValueError, match="exact native"):
        workflow.prepare_full_review_request(inputs, profile, native, views)


def test_changed_authority_invalidates_audits_before_setup_is_used(scenario):
    altered = list(deepcopy(scenario))
    altered[0]["verified_legal_context"]["facts"][0]["paraphrase"] += " changed authority"
    with pytest.raises(ValidationError):
        author(altered)


def test_setup_is_not_human_quality_or_spatial_approval(scenario):
    inputs, profile, goal, *_ = scenario
    prepared = workflow.prepare_opening_setup_request(inputs, profile, goal)
    assert prepared["production_dispatch_eligible"] is False
    assert prepared["request"]["input_provenance"]["human_approval"] is None
    assert "same_goal_audit_admission" in prepared["request"]["input_provenance"]
    assert "Natural-language location/orientation" in author(scenario)["views"]["unresolved_obligations"]


def test_old_native_goal_version_and_current_prop_state_are_never_silently_migrated(scenario):
    inputs, profile, goal, *_ = scenario
    bad = deepcopy(goal)
    bad["contract_version"] = "creative_goal_source_v3"
    bad["whole_plan"]["props"][0]["presence_at_start"] = "present"
    before = deepcopy(bad)
    with pytest.raises(workflow.goals.GoalContractError):
        workflow.prepare_opening_setup_request(inputs, profile, bad)
    with pytest.raises(workflow.goals.GoalContractError):
        workflow.prepare_goal_drama_audit_request(inputs, profile, bad)
    assert bad == before


def test_opening_context_overflow_stops_without_truncating_native_plan(scenario):
    inputs, profile, goal, *_ = scenario
    goal = deepcopy(goal)
    goal["whole_plan"]["premise"] += "大" * 120000
    before = deepcopy(goal)
    with pytest.raises(ValueError, match="context budget"):
        workflow.prepare_opening_setup_request(inputs, profile, goal)
    assert goal == before


def test_new_setup_repair_keys_do_not_change_exact_source_id_catalog(scenario):
    inputs, _, goal, setup, ids, *_ = scenario
    repaired = {**deepcopy(inputs), "previous_opening_setup": setup, "opening_setup_diagnostics": {"issue": "synthetic"}}
    assert workflow.origin_ids(repaired) == ids
