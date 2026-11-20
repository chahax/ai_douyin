"""Focused offline role separation, not gold judgments for an old script."""
from copy import deepcopy

import pytest

from src.content_factory import creative_physical_anchor_contract_v1 as contract


def fixture():
    brief = {"selected_candidate_id": "physical_role_fixture",
        "characters": [{"id": "person", "name": "甲", "role": "在桌边"}],
        "scenes": [{"id": "room", "description": "同一房间，桌面"}],
        "facts": [{"id": "F1", "text": "纸与笔均不在容器内，纸无遮挡。"}],
        "initial_state": {"scene_id": "room", "character_states": [], "prop_states": [
            {"id": "paper", "expected_state": "纸面朝上在甲面前的桌面，无遮挡。", "holder_character_id": None},
            {"id": "pen", "expected_state": "笔在纸旁的桌面，无人持笔。", "holder_character_id": None}]}}
    script = contract.base.compile_script({"title": "物理测试", "premise": "仅供离线契约验证。", "beats": [
        {"id": "B1", "event": "初态", "trigger": "桌面", "steps": [
            {"kind": "action", "speaker": "", "text": "房间里，纸面朝上放在甲面前的桌面上，无遮挡；笔在纸旁，均无人持拿，也不在容器内。"},
            {"kind": "action", "speaker": "", "text": "甲看了一眼纸。"}]}]}, brief)
    source = {"brief_sha256": contract._digest(brief), "source_catalog_sha256": contract._digest(contract.source_catalog(brief)), "states": []}
    actual = {"brief_sha256": contract._digest(brief), "script_sha256": contract._digest(script), "states": []}
    for entity in ("paper", "pen"):
        source_dimensions, actual_dimensions = {}, {}
        for dimension in contract.DIMENSIONS:
            src = dict(knowledge="unconstrained", value="unspecified", reference_type="unspecified", reference_id="",
                       explanation="离线夹具明确未约束此维度。", source_refs=[])
            obs = dict(knowledge="unknown", value="unspecified", reference_type="unspecified", reference_id="",
                       explanation="未作任何生产判断。", evidence_refs=[], temporal_basis="unknown")
            if dimension == "support":
                src["surface_kind"] = obs["surface_kind"] = "unspecified"
            source_dimensions[dimension], actual_dimensions[dimension] = src, obs
        source["states"].append(dict(entity_type="prop", entity_id=entity, dimensions=source_dimensions))
        actual["states"].append(dict(entity_type="prop", entity_id=entity, dimensions=actual_dimensions))

    def known(entity, dimension, value, reference_type="none", reference_id="", **extras):
        src = next(row for row in source["states"] if row["entity_id"] == entity)["dimensions"][dimension]
        obs = next(row for row in actual["states"] if row["entity_id"] == entity)["dimensions"][dimension]
        values = dict(knowledge="known", value=value, reference_type=reference_type, reference_id=reference_id, **extras)
        source_id = "initial:prop:" + entity
        src.update(**values, source_refs=[{"source_id": source_id, "quote": contract.source_catalog(brief)[source_id]}])
        obs.update(**values, evidence_refs=["E0001"], temporal_basis="earliest")

    for entity in ("paper", "pen"):
        known(entity, "scene", "located_in", "scene", "room")
        known(entity, "support", "on_surface", "scene_surface", "room", surface_kind="table")
        known(entity, "holder", "no_holder")
        known(entity, "container", "outside")
    known("paper", "spatial_reference", "in_front_of", "character", "person")
    known("pen", "spatial_reference", "beside", "prop", "paper")
    known("paper", "orientation", "face_up")
    known("paper", "visibility", "visible")
    return brief, script, source, actual


def test_scene_support_holder_and_spatial_reference_can_all_be_correct_without_same_anchor():
    brief, script, source, actual = fixture()
    before = deepcopy((script, source, actual))
    result = contract.decide(source, actual, script, brief)
    assert result["status"] == "source_constrained_physics_ready"
    assert result["legacy_initial_state_approved"] is False
    assert result["unconstrained_dimensions_not_certified"]
    assert (script, source, actual) == before


@pytest.mark.parametrize("dimension,updates", [
    ("orientation", {"value": "face_down"}),
    ("visibility", {"value": "occluded"}),
    ("holder", {"value": "held_by", "reference_type": "character", "reference_id": "person"}),
    ("support", {"surface_kind": "floor"}),
    ("container", {"value": "inside", "reference_type": "prop", "reference_id": "pen"}),
])
def test_known_conflict_in_same_dimension_still_requires_whole_new_script(dimension, updates):
    brief, script, source, actual = fixture()
    actual["states"][0]["dimensions"][dimension].update(updates)
    result = contract.decide(source, actual, script, brief)
    assert result["status"] == "needs_whole_revision"
    assert result["revision_requirements"][0]["dimension"] == dimension


def test_necessary_unknown_does_not_inherit_scene_or_later_position_as_satisfaction():
    brief, script, source, actual = fixture()
    actual["states"][1]["dimensions"]["spatial_reference"]["knowledge"] = "unknown"
    assert contract.decide(source, actual, script, brief)["status"] == "halt_physical_uncertain"


def test_late_known_value_is_not_known_earliest_state():
    brief, script, source, actual = fixture()
    actual["states"][1]["dimensions"]["spatial_reference"].update(evidence_refs=["E0002"], temporal_basis="later_only")
    assert contract.decide(source, actual, script, brief)["status"] == "halt_physical_uncertain"


def test_claimed_earliest_observation_requires_first_step_evidence_in_public_schema():
    brief, script, _, actual = fixture()
    actual["states"][1]["dimensions"]["spatial_reference"]["evidence_refs"] = ["E0002"]
    with pytest.raises(ValueError):
        contract.validate_actual(actual, script, brief)


def test_space_reference_cannot_be_encoded_as_holding_or_surface_owner():
    brief, script, _, actual = fixture()
    actual["states"][0]["dimensions"]["holder"].update(value="held_by", reference_type="scene", reference_id="room")
    with pytest.raises(ValueError):
        contract.validate_actual(actual, script, brief)


@pytest.mark.parametrize("change", ["wrong_script", "wrong_brief", "fake_quote", "duplicate_entity"])
def test_all_physical_sources_and_observations_remain_sha_and_reference_bound(change):
    brief, script, source, actual = fixture()
    if change == "wrong_script":
        actual["script_sha256"] = "0" * 64
    elif change == "wrong_brief":
        source["brief_sha256"] = "0" * 64
    elif change == "fake_quote":
        source["states"][0]["dimensions"]["scene"]["source_refs"][0]["quote"] = "来源没有的字"
    else:
        source["states"][1] = deepcopy(source["states"][0])
    with pytest.raises(ValueError):
        contract.decide(source, actual, script, brief)


def test_known_conflict_and_other_unknown_preserve_both_findings():
    brief, script, source, actual = fixture()
    actual["states"][0]["dimensions"]["visibility"]["value"] = "occluded"
    actual["states"][1]["dimensions"]["spatial_reference"]["knowledge"] = "unknown"
    result = contract.decide(source, actual, script, brief)
    assert result["status"] == "needs_whole_revision"
    assert result["revision_requirements"] and result["uncertainties"]
