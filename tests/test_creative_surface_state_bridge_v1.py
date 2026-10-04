"""Offline screenplay-slot bridge tests for typed surface moves."""
from copy import deepcopy
import pytest
from jsonschema import Draft202012Validator

from scripts import creative_surface_state_bridge_v1 as bridge
from src.content_factory.creative_workflow_contract import CreativeContractError
from tests.test_creative_surface_state_v1 import sample as physical_sample


def sample():
    p, s, m = physical_sample()
    p["schema"] = bridge.VERSION
    p["beats"][0]["events"][0].update(phase="before_first_line", script_slot="before", dialogue_index=-1)
    p["beats"][1]["events"][0].update(phase="no_dialogue", script_slot="after", dialogue_index=-1)
    p["beats"][0]["events"].append({"start": 2, "end": 4, "phase": "first_line_delivery",
        "script_slot": "dialogue_performance", "dialogue_index": 0,
        "performance": "自然说出完整原对白，情绪感染力待审", "operations": []})
    return p, s, m


def test_bridge_schema_and_compile_use_new_state_not_old_hardcoded_dependency():
    p, s, m = sample()
    raw = deepcopy((p, s, m))
    schema = bridge.build_state_plan_schema({"script": s, "static_visual_manifest": m})
    Draft202012Validator(schema).validate(p)
    bridge.validate_state_plan(p, s, m)
    result = bridge.compile_state_plan(p, s, m)
    assert "slide" in result["shots"][0]["visible_performance"]
    assert (p, s, m) == raw


def test_slide_cannot_be_misclassified_as_dialogue_performance():
    p, s, m = sample()
    p["beats"][0]["events"][-1]["operations"] = [
        {"kind": "slide", "actor": "C02", "target": "P03_Y", "value": "surface:E01:对方面前"}]
    with pytest.raises(CreativeContractError, match="关键动作"):
        bridge.validate_state_plan(p, s, m)


def test_bridge_does_not_hide_cross_surface_slide():
    p, s, m = sample()
    p["beats"][0]["events"][0]["operations"][0]["value"] = "surface:E02:对方面前"
    with pytest.raises(CreativeContractError, match="跨支持面"):
        bridge.validate_state_plan(p, s, m)


def test_after_and_during_still_cannot_run_while_dialogue_is_being_delivered():
    p, s, m = sample()
    event = p["beats"][0]["events"][0]
    event.update(start=2, end=4, phase="after_last_line", script_slot="after")
    with pytest.raises(CreativeContractError, match="提前"):
        bridge.validate_state_plan(p, s, m)


def test_new_schema_rejects_collection_target_and_noncanonical_destination():
    p, s, m = sample()
    schema = bridge.build_state_plan_schema({"script": s, "static_visual_manifest": m})
    p["beats"][0]["events"][0]["operations"][0]["target"] = "P03"
    assert list(Draft202012Validator(schema).iter_errors(p))
    p["beats"][0]["events"][0]["operations"][0].update(target="P03_Y", value="E01桌面")
    assert list(Draft202012Validator(schema).iter_errors(p))
