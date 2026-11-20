"""Focused endpoint-wire checks; no model or media call."""
from copy import deepcopy
import math

from jsonschema import Draft202012Validator
import pytest

from src.content_factory import creative_video_trial_direction_v3 as contract
from src.content_factory import creative_video_trial_contract_v1 as base
from tests.test_creative_video_trial_direction_v2 import actual_script, actual_rejected_492, FIRST


def complete_wire(script):
    old = actual_rejected_492()["output"]
    creative = {key: deepcopy(value) for key, value in old["segments"][0].items() if key != "source_refs"}
    rest = []
    for ref, source in list(base.catalog(script).items())[len(FIRST):]:
        rest.append({"information_change": "新增当前事件信息。", "observation": "观察当前行动对象。",
            "emotional_turn": "接收当下变化。", "cut_reason": "信息接收后切换观察。",
            "target_seconds": max(4, math.ceil(base.spoken_seconds(source) + 0.5)),
            "reaction_reserve_seconds": 0.5, "end_source_ref": ref})
    return {**{key: deepcopy(value) for key, value in old.items() if key != "segments"},
        "opening": creative, "remaining_segments": rest}


def test_public_wire_has_common_endpoint_items_no_25_assignment_copy_and_expands_full_source():
    script = actual_script(); raw = complete_wire(script); before = deepcopy(raw)
    schema = contract.whole_direction_schema(script, FIRST)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(raw)
    assert "source_assignments" not in schema["properties"]
    assert "prefixItems" not in schema["properties"]["remaining_segments"]
    assert "source_refs" not in schema["properties"]["opening"]["properties"]
    compiled = contract.compile_direction(raw, script, FIRST)
    assert compiled["native"] == before == raw
    assert [ref for row in compiled["segments"] for ref in row["source_refs"]] == list(base.catalog(script))
    assert compiled["segments"][0]["source_refs"] == FIRST
    assert compiled["native_cut_endpoints"] == [row["end_source_ref"] for row in raw["remaining_segments"]]
    for native, expanded in zip(raw["remaining_segments"], compiled["expanded_v1_native"]["segments"][1:]):
        assert {k: v for k, v in native.items() if k != "end_source_ref"} == {k: v for k, v in expanded.items() if k != "source_refs"}


@pytest.mark.parametrize("defect", ["duplicate", "reverse", "missing_tail", "empty", "opening_ref"])
def test_cut_endpoints_cannot_repeat_reverse_omit_tail_or_enter_opening(defect):
    script = actual_script(); raw = complete_wire(script)
    if defect == "duplicate": raw["remaining_segments"][1]["end_source_ref"] = raw["remaining_segments"][0]["end_source_ref"]
    elif defect == "reverse": raw["remaining_segments"][0], raw["remaining_segments"][1] = raw["remaining_segments"][1], raw["remaining_segments"][0]
    elif defect == "missing_tail": raw["remaining_segments"].pop()
    elif defect == "empty": raw["remaining_segments"] = []
    else: raw["remaining_segments"][0]["end_source_ref"] = FIRST[-1]
    with pytest.raises(ValueError): contract.compile_direction(raw, script, FIRST)


def test_unknown_wrong_digest_fast_speech_extra_source_fields_and_overlong_film_rejected():
    script = actual_script(); raw = complete_wire(script)
    raw["availability"] = "unknown"
    with pytest.raises(ValueError, match="availability unknown"): contract.compile_direction(raw, script, FIRST)
    raw = complete_wire(script); raw["script_sha256"] = "0" * 64
    with pytest.raises(ValueError): contract.compile_direction(raw, script, FIRST)
    raw = complete_wire(script); raw["opening"]["target_seconds"] = 4
    with pytest.raises(ValueError, match="normal speed"): contract.compile_direction(raw, script, FIRST)
    raw = complete_wire(script); raw["remaining_segments"][0]["source_refs"] = ["B1.S03"]
    with pytest.raises(ValueError): contract.compile_direction(raw, script, FIRST)
    raw = complete_wire(script)
    for row in [raw["opening"]] + raw["remaining_segments"]: row["target_seconds"] = 15
    with pytest.raises(ValueError, match="180 second"): contract.compile_direction(raw, script, FIRST)


def test_model_can_merge_adjacent_actions_by_choosing_a_later_cut_without_fixed_mirror_count():
    script = actual_script(); raw = complete_wire(script)
    # Last two source actions share one segment. The model cut is the final
    # source; compiler expands both, without proposing or adding a new cut.
    raw["remaining_segments"].pop(-2)
    raw["remaining_segments"][-1]["target_seconds"] = 8
    compiled = contract.compile_direction(raw, script, FIRST)
    assert compiled["segments"][-1]["source_refs"] == ["B7.S02", "B7.S03"]
    assert len(compiled["segments"]) == 1 + len(raw["remaining_segments"])
