"""Offline surface transition tests; source fidelity remains separately pending."""
from copy import deepcopy
import json
import pytest
from jsonschema import Draft202012Validator

from scripts import creative_component_registry_v1 as registry
from scripts import creative_surface_state_v1 as surface
from src.content_factory.creative_workflow_contract import CreativeContractError
from tests.test_creative_state_plan_v2 import sample as old_sample


def sample():
    plan, script, original = old_sample()
    original["props"].append({"id": "P03", "name": "善后便利贴三张",
        "appearance": "正方形小纸片，分别为浅黄、浅粉、浅蓝底，深灰手写短词（对账/改明细/收尾）",
        "owner_id": "C01"})
    bundle = registry.build_p03_registry(original)
    manifest = bundle["effective_manifest"]
    plan["schema"] = surface.VERSION
    for prop in ("P03_Y", "P03_P", "P03_B"):
        plan["initial_state"][prop] = {"holder": "none", "location": "surface:E01:桌角"}
    plan["beats"][0]["events"][0]["operations"] = [
        {"kind": "slide", "actor": "C02", "target": "P03_Y", "value": "surface:E01:方澄手边"}]
    plan["beats"][1]["events"][0]["operations"] = [
        {"kind": "slide", "actor": "C02", "target": "P03_Y", "value": "surface:E01:林屿面前"}]
    return plan, script, manifest


def apply(operation, state, manifest):
    return surface._apply_operation(operation, state,
        {c["id"] for c in manifest["characters"]},
        {p["id"] for p in manifest["props"]},
        {e["id"] for e in manifest["scene"]["elements"]}, "test",
        surface_ids=surface.support_surface_ids(manifest))


def test_slide_is_typed_and_changes_only_selected_member_location():
    p, s, m = sample()
    raw = deepcopy(p)
    operation = p["beats"][0]["events"][0]["operations"][0]
    state = deepcopy(p["initial_state"])
    changes, reads, description = apply(operation, state, m)
    assert changes == [{"entity": "P03_Y", "field": "location",
        "from": "surface:E01:桌角", "to": "surface:E01:方澄手边"}]
    assert reads == {("P03_Y", "holder"), ("P03_Y", "location")}
    assert state["P03_Y"]["holder"] == "none"
    assert state["P03_P"] == p["initial_state"]["P03_P"]
    assert state["P03_B"] == p["initial_state"]["P03_B"]
    assert "slide" in description
    assert p == raw


def test_projection_and_cross_shot_compile_preserve_member_state_and_original_slide():
    p, s, m = sample()
    raw = deepcopy((p, s, m))
    Draft202012Validator(surface.build_state_plan_schema({"script": s, "static_visual_manifest": m})).validate(p)
    result = surface.compile_state_plan(p, s, m)
    assert (p, s, m) == raw
    assert "slide" in result["shots"][0]["visible_performance"]
    first = json.loads(result["shots"][0]["end_state"])
    second = json.loads(result["shots"][1]["start_state"])
    assert first == second
    assert any(k.startswith("P03_Y") and v["location"] == "surface:E01:方澄手边" for k, v in first.items())
    assert all(v["location"] == "surface:E01:桌角" for k, v in first.items()
        if k.startswith("P03_P") or k.startswith("P03_B"))
    assert p["beats"][0]["events"][0]["operations"][0]["kind"] == "slide"


def test_partial_independent_holder_does_not_take_the_collection_or_other_members():
    p, s, m = sample()
    state = deepcopy(p["initial_state"])
    apply({"kind": "take", "actor": "C02", "target": "P03_Y", "value": "右手"}, state, m)
    assert state["P03_Y"] == {"holder": "C02", "location": "右手"}
    assert state["P03_P"] == p["initial_state"]["P03_P"]
    apply({"kind": "pass", "actor": "C02", "target": "P03_Y", "value": "C01"}, state, m)
    assert state["P03_Y"]["holder"] == "C01"
    apply({"kind": "place", "actor": "C01", "target": "P03_Y", "value": "surface:E02:桌角"}, state, m)
    assert state["P03_Y"]["holder"] == "none"
    assert state["P03_Y"]["location"] == "surface:E02:桌角"
    assert state["P03_B"] == p["initial_state"]["P03_B"]


@pytest.mark.parametrize("mutation,error", [
    (lambda p: p["initial_state"]["P03_Y"].update(holder="C01"), "holder=none"),
    (lambda p: p["initial_state"]["P03_Y"].update(location="E01桌面"), "规范"),
    (lambda p: p["initial_state"]["P03_Y"].update(location="surface:E02:桌角"), "跨支持面"),
    (lambda p: p["beats"][0]["events"][0]["operations"][0].update(target="P03"), "独立prop"),
    (lambda p: p["beats"][0]["events"][0]["operations"][0].update(value="surface:E99:桌角"), "未显式登记"),
    (lambda p: p["beats"][0]["events"][0]["operations"][0].update(value="surface:E01:"), "规范"),
    (lambda p: p["beats"][0]["events"][0]["operations"][0].update(value="surface:E01: 手边"), "规范"),
    (lambda p: p["beats"][0]["events"][0]["operations"][0].update(value="surface:E01:手边 "), "规范"),
    (lambda p: p["beats"][0]["events"][0]["operations"][0].update(value="surface:E01:桌角"), "改变zone"),
    (lambda p: p["beats"][0]["events"][0]["operations"][0].update(value="surface:E01:手:边"), "规范"),
])
def test_invalid_slide_preconditions_rejected(mutation, error):
    p, s, m = sample()
    mutation(p)
    with pytest.raises(CreativeContractError, match=error):
        surface.validate_state_plan(p, s, m)


def test_slide_requires_explicit_support_surface_evidence_even_with_known_elements():
    p, s, m = sample()
    m.pop("surface_ids")
    with pytest.raises(CreativeContractError, match="支持面声明"):
        surface.validate_state_plan(p, s, m)


def test_registered_element_is_not_implicitly_a_supporting_surface():
    p, s, m = sample()
    m["surface_ids"] = ["E01"]
    p["beats"][0]["events"][0]["operations"][0]["value"] = "surface:E02:座面"
    with pytest.raises(CreativeContractError, match="未显式登记"):
        surface.validate_state_plan(p, s, m)
    schema = surface.build_state_plan_schema({"script": s, "static_visual_manifest": m})
    assert list(Draft202012Validator(schema).iter_errors(p))


def test_same_member_overlapping_read_write_is_rejected():
    p, s, m = sample()
    event = deepcopy(p["beats"][0]["events"][0])
    event.update(start=1, end=2)
    event["operations"][0]["value"] = "surface:E01:更近处"
    p["beats"][0]["events"].append(event)
    with pytest.raises(CreativeContractError, match="重叠"):
        surface.validate_state_plan(p, s, m)


def test_different_members_can_slide_concurrently_without_false_conflict():
    p, s, m = sample()
    event = deepcopy(p["beats"][0]["events"][0])
    event.update(start=1, end=2)
    event["operations"][0].update(target="P03_P", value="surface:E01:另一侧")
    p["beats"][0]["events"].append(event)
    surface.validate_state_plan(p, s, m)


def test_other_old_operation_semantics_remain_available():
    p, s, m = old_sample()
    p["schema"] = surface.VERSION
    result = surface.compile_state_plan(p, s, m)
    assert "拿起P01" in result["shots"][0]["visible_performance"]
    assert "sitting" in result["shots"][1]["end_state"]


@pytest.mark.parametrize("value", [[], [None], ["E01", "E01"], ["E99"]])
def test_invalid_explicit_surface_declaration_rejected(value):
    p, s, m = sample()
    m["surface_ids"] = value
    if not value:
        with pytest.raises(CreativeContractError):
            surface.validate_state_plan(p, s, m)
    else:
        with pytest.raises(CreativeContractError):
            surface.build_state_plan_schema({"script": s, "static_visual_manifest": m})

def test_visual_projection_is_copy_only_and_does_not_discard_component_assets():
    p, s, m = sample()
    original = deepcopy(m)
    visual = surface.legacy_visual_manifest(m)
    assert m == original
    assert "surface_ids" not in visual
    assert visual["props"] == m["props"]
    assert {p["id"] for p in visual["props"]} >= {"P03_Y", "P03_P", "P03_B"}


def test_unhashable_surface_list_is_contract_rejection():
    p, s, m = sample()
    m["surface_ids"] = [{}]
    with pytest.raises(CreativeContractError, match="字符串"):
        surface.build_state_plan_schema({"script": s, "static_visual_manifest": m})

def test_stand_and_wrong_holder_or_recipient_keep_old_preconditions():
    p, s, m = sample()
    state = deepcopy(p["initial_state"])
    state["C02"]["posture"] = "sitting"
    apply({"kind": "stand", "actor": "C02", "target": "", "value": "桌旁"}, state, m)
    assert state["C02"]["posture"] == "standing"
    assert state["C02"]["position"] == "桌旁"
    with pytest.raises(CreativeContractError, match="stand要求"):
        apply({"kind": "stand", "actor": "C02", "target": "", "value": "桌旁"}, state, m)
    apply({"kind": "take", "actor": "C02", "target": "P03_Y", "value": "右手"}, state, m)
    with pytest.raises(CreativeContractError, match="place要求"):
        apply({"kind": "place", "actor": "C01", "target": "P03_Y", "value": "surface:E01:桌角"}, state, m)
    with pytest.raises(CreativeContractError, match="pass要求"):
        apply({"kind": "pass", "actor": "C02", "target": "P03_Y", "value": "C02"}, state, m)


def test_existing_plain_prop_can_slide_if_unheld_on_same_declared_surface():
    p, s, m = sample()
    state = deepcopy(p["initial_state"])
    state["P01"] = {"holder": "none", "location": "surface:E01:左侧"}
    apply({"kind": "slide", "actor": "C02", "target": "P01", "value": "surface:E01:右侧"}, state, m)
    assert state["P01"] == {"holder": "none", "location": "surface:E01:右侧"}


def test_overlapping_slide_and_take_cannot_read_stale_unheld_member():
    p, s, m = sample()
    event = deepcopy(p["beats"][0]["events"][0])
    event.update(start=1, end=2)
    event["operations"][0].update(kind="take", target="P03_Y", value="右手")
    p["beats"][0]["events"].append(event)
    with pytest.raises(CreativeContractError, match="重叠"):
        surface.validate_state_plan(p, s, m)


@pytest.mark.parametrize("field,value", [("target", {}), ("value", []), ("actor", "C99"), ("kind", "hold")])
def test_schema_rejects_slide_type_errors_unknown_actor_and_invented_kind(field, value):
    p, s, m = sample()
    p["beats"][0]["events"][0]["operations"][0][field] = value
    schema = surface.build_state_plan_schema({"script": s, "static_visual_manifest": m})
    assert list(Draft202012Validator(schema).iter_errors(p))
