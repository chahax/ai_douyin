"""Full-source director wire routing; no paid model or media request."""
from copy import deepcopy
import json
import math
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from src.content_factory import creative_video_trial_direction_v2 as contract
from src.content_factory import creative_video_trial_contract_v1 as base


ROOT = Path(__file__).resolve().parents[1]
FIRST = ["B1.S01", "B1.S02"]


def actual_script():
    path = ROOT / "data/production_trials/autonomous_text_pipeline_20261011/legal_resignation_15/versions/07/FULL_SCRIPT.json"
    return json.loads(path.read_text(encoding="utf-8"))


def actual_rejected_492():
    path = ROOT / "data/production_revisions/selected_script_video_trial_20261011/script487_v1/call_492_whole_direction.json"
    return json.loads(path.read_text(encoding="utf-8"))


def complete_wire(script):
    """Mock only missing later creative metadata; old output is unchanged."""
    old = actual_rejected_492()["output"]
    rows = [{key: deepcopy(value) for key, value in old["segments"][0].items() if key != "source_refs"}]
    rows[0]["segment_id"] = "M001"
    sources = base.catalog(script)
    assignments = [{"source_ref": ref, "segment_id": "M001"} for ref in FIRST]
    for index, ref in enumerate(list(sources)[len(FIRST):], 2):
        segment_id = f"M{index:03d}"
        assignments.append({"source_ref": ref, "segment_id": segment_id})
        rows.append({"segment_id": segment_id, "information_change": "这一事件增加当前信息。",
            "observation": "观察当前动作或对话对象。", "emotional_turn": "接收对方的反应。",
            "cut_reason": "当前信息接收后转移观察。",
            "target_seconds": max(4, math.ceil(base.spoken_seconds(sources[ref]) + 0.5)), "reaction_reserve_seconds": 0.5})
    return {**{key: deepcopy(value) for key, value in old.items() if key != "segments"},
        "source_assignments": assignments, "segments": rows}


def test_actual_492_is_complete_transport_but_partial_whole_source_not_quality_pass():
    receipt = actual_rejected_492(); script = actual_script()
    assert receipt["status"] == "contract_rejected"
    assert receipt["response_metadata"]["response_body_complete"]
    assert receipt["response_metadata"]["finish_reason"] == "tool_calls"
    assert receipt["response_metadata"]["total_tokens"] == 16506
    assert receipt["output"]["segments"][0]["source_refs"] == FIRST
    with pytest.raises(ValueError, match="every source exactly once"):
        base.compile_whole_direction(receipt["output"], script)
    raw = complete_wire(script)
    raw["source_assignments"] = raw["source_assignments"][:2]
    raw["segments"] = raw["segments"][:1]
    with pytest.raises(ValueError, match="wire invalid"):
        contract.compile_direction(raw, script, FIRST)


def test_public_schema_complete_25_assignments_and_source_expansion_only():
    script = actual_script(); raw = complete_wire(script); before = deepcopy(raw)
    schema = contract.whole_direction_schema(script, FIRST)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(raw)
    assert len(schema["properties"]["source_assignments"]["prefixItems"]) == 25
    compiled = contract.compile_direction(raw, script, FIRST)
    assert compiled["native"] == before == raw and compiled["native_sha256"] == base.digest(raw)
    assert [ref for row in compiled["segments"] for ref in row["source_refs"]] == list(base.catalog(script))
    assert compiled["segments"][0]["source_refs"] == FIRST
    for native, expanded in zip(raw["segments"], compiled["expanded_v1_native"]["segments"]):
        assert {k: v for k, v in native.items() if k != "segment_id"} == {k: v for k, v in expanded.items() if k != "source_refs"}
    assert compiled["whole_source_coverage_complete"] and compiled["all_native_creative_values_preserved"]
    assert not compiled["machine_script_quality"] and not compiled["actual_media_quality_passed"]


@pytest.mark.parametrize("defect", ["missing", "wrong_ref", "extra", "first_owner"])
def test_public_source_assignments_cannot_be_partial_or_change_fixed_first_segment(defect):
    script = actual_script(); raw = complete_wire(script)
    if defect == "missing": raw["source_assignments"].pop()
    elif defect == "wrong_ref": raw["source_assignments"][2]["source_ref"] = "B1.S02"
    elif defect == "extra": raw["source_assignments"].append(deepcopy(raw["source_assignments"][-1]))
    else: raw["source_assignments"][2]["segment_id"] = "M001"
    with pytest.raises(ValueError, match="wire invalid"):
        contract.compile_direction(raw, script, FIRST)


def test_missing_segment_and_orphan_metadata_do_not_get_locally_repaired():
    script = actual_script(); raw = complete_wire(script)
    raw["segments"].pop()
    with pytest.raises(ValueError, match="missing segment metadata"):
        contract.compile_direction(raw, script, FIRST)
    raw = complete_wire(script)
    raw["segments"].append({**deepcopy(raw["segments"][-1]), "segment_id": "M025"})
    with pytest.raises(ValueError, match="orphan"):
        contract.compile_direction(raw, script, FIRST)


def test_noncontiguous_assignment_order_cannot_be_sorted_into_pass():
    script = actual_script(); raw = complete_wire(script)
    raw["source_assignments"][2]["segment_id"], raw["source_assignments"][3]["segment_id"] = (
        raw["source_assignments"][3]["segment_id"], raw["source_assignments"][2]["segment_id"])
    with pytest.raises(ValueError, match="original order"):
        contract.compile_direction(raw, script, FIRST)


def test_unknown_changed_source_oversize_film_and_fast_reading_are_rejected():
    script = actual_script(); raw = complete_wire(script)
    raw["availability"] = "unknown"
    with pytest.raises(ValueError, match="availability unknown"):
        contract.compile_direction(raw, script, FIRST)
    raw = complete_wire(script); raw["script_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="wire invalid"):
        contract.compile_direction(raw, script, FIRST)
    raw = complete_wire(script)
    for row in raw["segments"]: row["target_seconds"] = 15
    with pytest.raises(ValueError, match="180 second"):
        contract.compile_direction(raw, script, FIRST)
    raw = complete_wire(script); raw["segments"][0]["target_seconds"] = 4
    with pytest.raises(ValueError, match="normal speed"):
        contract.compile_direction(raw, script, FIRST)


def test_dialogue_is_whole_source_atom_not_an_editable_substring_assignment():
    script = actual_script(); raw = complete_wire(script)
    raw["source_assignments"][1]["text"] = base.catalog(script)["B1.S02"]["text"][:10]
    with pytest.raises(ValueError, match="wire invalid"):
        contract.compile_direction(raw, script, FIRST)


def test_first_refs_must_be_same_selected_opening_prefix():
    with pytest.raises(ValueError, match="contiguous source prefix"):
        contract.whole_direction_schema(actual_script(), ["B1.S02"])
