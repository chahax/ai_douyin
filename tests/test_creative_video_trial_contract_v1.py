"""Focused offline preparation tests; no model, audio or video generation."""
from copy import deepcopy
import json
import math
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from src.content_factory import creative_video_trial_contract_v1 as contract


def actual_script():
    root = Path(__file__).resolve().parents[1] / "data/production_trials/autonomous_text_pipeline_20261011/legal_resignation_15"
    return json.loads((root / "versions/07/FULL_SCRIPT.json").read_text(encoding="utf-8"))


def direction(script, first_refs=None):
    sources = contract.catalog(script)
    first_refs = first_refs or list(sources)[:1]
    groups = [first_refs] + [[ref] for ref in list(sources)[len(first_refs):]]
    return {"script_sha256": contract.digest(script), "availability": "known",
        "whole_observation": "观察人在压力下如何回应对方。", "emotional_progression": "先听见，再理解冲突，最后作出选择。",
        "visual_style": "克制写实，固定空间中的自然谈话。", "segments": [{"source_refs": refs,
            "information_change": "当下事件推进一层。", "observation": "看行动和聆听如何影响关系。",
            "emotional_turn": "从准备到接收。", "cut_reason": "信息被接收后改变观察对象。",
            "target_seconds": max(4, math.ceil(sum(contract.spoken_seconds(sources[ref]) for ref in refs) + 0.5)),
            "reaction_reserve_seconds": 0.5} for refs in groups]}


def performance(script, refs, overlap=True):
    current = contract.opening_source(script, refs)
    dialogue_refs = [ref for ref, row in current["current_sources"].items() if row["kind"] == "dialogue"]
    return {"script_sha256": contract.digest(script), "source_refs": refs, "availability": "known",
        "continuous_performance": "两人坐在桌边，说明者做完当下动作并把注意力转向对方；聆听者随内容逐渐警觉，反应自然发生在交谈中。",
        "actor_goals": [{"actor_id": actor, "immediate_objective": "把自己的当下立场传递给对方。",
            "reception_of_current_stimulus": "看向对方并接收当前信息，留住情绪变化。"} for actor in current["actor_ids"]],
        "camera": "稳定中景，桌面和双方上身可见；关注聆听者，避免无意义切换。",
        "spoken_language": "zh-CN", "delivery": "自然普通话，按日常交谈速度表达，允许表情和动作同时发生。",
        "action_timings": [{"source_ref": ref, "duration_seconds": 2.5,
            "overlap_with": dialogue_refs[0] if overlap and dialogue_refs else "", "overlap_offset_seconds": 0}
            for ref, row in current["current_sources"].items() if row["kind"] == "action"],
        "post_reaction_seconds": 0.5, "ending_state": "双方停留在当前座位，当前道具保持本段动作完成后的状态。"}


def test_actual_487_whole_direction_covers_7_beats_25_steps_in_original_order():
    script = actual_script(); before = deepcopy(script)
    assert contract.digest(script) == "cbb125ea23dbefca1c314d53bc26ce7c231d1b3ab39b256b1b20d8dcde520d0d"
    catalog = contract.catalog(script)
    assert len(catalog) == 25 and len(script["beats"]) == 7
    assert list(catalog)[:3] == ["B1.S01", "B1.S02", "B1.S03"]
    raw = direction(script, ["B1.S01", "B1.S02"])
    Draft202012Validator.check_schema(contract.whole_direction_schema(script))
    compiled = contract.compile_whole_direction(raw, script)
    assert [ref for row in compiled["segments"] for ref in row["source_refs"]] == list(catalog)
    assert compiled["whole_source_coverage_complete"] and not compiled["machine_script_quality"]
    assert script == before


@pytest.mark.parametrize("defect", ["missing", "duplicate", "reorder"])
def test_whole_direction_source_ownership_cannot_drop_repeat_or_reorder(defect):
    script = actual_script(); raw = direction(script)
    if defect == "missing": raw["segments"].pop()
    elif defect == "duplicate": raw["segments"][1]["source_refs"] = raw["segments"][0]["source_refs"]
    else: raw["segments"][0], raw["segments"][1] = raw["segments"][1], raw["segments"][0]
    with pytest.raises(ValueError, match="every source exactly once"):
        contract.compile_whole_direction(raw, script)


def test_actual_opening_dialogue_exact_once_no_future_and_reference_reconstruction():
    script = actual_script(); refs = ["B1.S01", "B1.S02"]
    raw = performance(script, refs); original = deepcopy(raw)
    Draft202012Validator.check_schema(contract.opening_performance_schema(script, refs))
    compiled = contract.compile_opening_performance(raw, script, refs, user_trial_acceptance=True)
    prompt = contract.render_opening_prompt(compiled, script, actor_names={"zhou": "周姐", "xiaolin": "小林"})
    sources = contract.catalog(script)
    assert contract.spoken_characters(sources["B1.S02"]) == 40
    assert prompt.count(sources["B1.S02"]["text"]) == 1
    assert all(row["text"] not in prompt for ref, row in sources.items() if ref not in refs and row["kind"] == "dialogue")
    assert compiled["total_seconds"] == pytest.approx(40 / 3.3 + 0.5, abs=1e-6)
    assert compiled["duration_seconds"] == 13 and compiled["schedule"][0]["start_seconds"] == 0
    assert compiled["schedule"][1]["start_seconds"] == 0
    assert compiled["reference_mode"] == "reference_image_identity_environment_reconstruction"
    assert not compiled["resume_from_old_video"] and not compiled["machine_script_quality"]
    assert compiled["user_trial_acceptance"] and not compiled["actual_media_quality_passed"]
    assert compiled["after_generation_content_status"] == "awaiting_human_review"
    assert compiled["requires_human_approved_service_tail_for_next_segment"]
    assert compiled["timing_is_estimate"] and not compiled["measured_audio"] and not compiled["fit_scaled"]
    assert raw == original


def test_first_action_may_overlap_current_speech_but_serial_timing_is_not_force_scaled():
    script = actual_script(); refs = ["B1.S01", "B1.S02"]
    raw = performance(script, refs, overlap=False)
    raw["action_timings"][0]["duration_seconds"] = 2.0
    serial = contract.compile_opening_performance(raw, script, refs)
    assert serial["total_seconds"] == pytest.approx(2.0 + 40 / 3.3 + 0.5, abs=1e-6)
    raw["action_timings"][0]["duration_seconds"] = 4
    with pytest.raises(ValueError, match="fifteen seconds"):
        contract.compile_opening_performance(raw, script, refs)


@pytest.mark.parametrize("refs", [["B1.S02"], ["B1.S01", "B1.S03"], ["B1.S02", "B1.S01"]])
def test_opening_cannot_skip_initial_action_or_jump_to_future(refs):
    with pytest.raises(ValueError, match="contiguous source prefix"):
        contract.opening_performance_schema(actual_script(), refs)


def test_opening_projection_has_only_current_text_not_whole_future_script():
    script = actual_script(); refs = ["B1.S01", "B1.S02"]
    projected = contract.opening_source(script, refs)
    serial = json.dumps(projected, ensure_ascii=False)
    sources = contract.catalog(script)
    assert sources["B1.S02"]["text"] in serial and sources["B1.S03"]["text"] not in serial
    assert sources["B7.S03"]["text"] not in serial
    assert projected["actor_ids"] == ["zhou", "xiaolin"]


@pytest.mark.parametrize("copy_ref", ["B1.S02", "B1.S03"])
def test_model_instruction_prose_cannot_recopy_current_or_future_dialogue(copy_ref):
    script = actual_script(); refs = ["B1.S01", "B1.S02"]
    raw = performance(script, refs)
    raw["continuous_performance"] += contract.catalog(script)[copy_ref]["text"]
    with pytest.raises(ValueError, match="copied current or future"):
        contract.compile_opening_performance(raw, script, refs)


def test_unknown_source_identity_future_overlap_and_unknown_timing_are_rejected():
    script = actual_script(); refs = ["B1.S01", "B1.S02"]
    raw = performance(script, refs)
    raw["availability"] = "unknown"
    with pytest.raises(ValueError, match="availability unknown"):
        contract.compile_opening_performance(raw, script, refs)
    raw = performance(script, refs); raw["script_sha256"] = "0" * 64
    with pytest.raises(ValueError): contract.compile_opening_performance(raw, script, refs)
    raw = performance(script, refs); raw["action_timings"][0]["overlap_with"] = "B1.S03"
    with pytest.raises(ValueError): contract.compile_opening_performance(raw, script, refs)
    raw = performance(script, refs); raw["action_timings"][0]["duration_seconds"] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        contract.compile_opening_performance(raw, script, refs)


def test_whole_segment_requires_complete_normal_speed_speech_and_known_availability():
    script = actual_script(); raw = direction(script, ["B1.S01", "B1.S02", "B1.S03"])
    raw["segments"][0]["target_seconds"] = 15
    with pytest.raises(ValueError, match="normal speed"):
        contract.compile_whole_direction(raw, script)
    raw = direction(script); raw["availability"] = "unknown"
    with pytest.raises(ValueError, match="availability unknown"):
        contract.compile_whole_direction(raw, script)


def test_compiled_text_timing_and_actor_mapping_cannot_be_modified_after_compilation():
    script = actual_script(); refs = ["B1.S01", "B1.S02"]
    compiled = contract.compile_opening_performance(performance(script, refs), script, refs)
    changed = deepcopy(compiled); changed["schedule"][1]["original_text"] = "被改掉的原台词。"
    with pytest.raises(ValueError, match="compilation source"):
        contract.render_opening_prompt(changed, script)
    with pytest.raises(ValueError, match="actual source speaker IDs"):
        contract.render_opening_prompt(compiled, script, actor_names={"invented_third": "第三人"})
    changed_script = deepcopy(script); changed_script["beats"][0]["steps"][1]["text"] += "另加一句。"
    with pytest.raises(ValueError, match="different source"):
        contract.render_opening_prompt(compiled, changed_script)


@pytest.mark.parametrize("beat_count", [1, 7, 12])
def test_generic_scripts_use_positional_ids_and_no_old_four_beat_or_source380_lock(beat_count):
    script = {"title": "其他选定正文", "beats": [{"id": f"scene-{i}", "steps": [
        {"kind": "action", "speaker": "", "text": "甲把杯子放在桌上。"},
        {"kind": "dialogue", "speaker": "actor_a", "text": "今天我们把事情说清楚。"},
        {"kind": "dialogue", "speaker": "actor_b", "text": "我先听你讲完。"}]} for i in range(beat_count)]}
    raw = direction(script, ["B1.S01", "B1.S02"])
    compiled = contract.compile_whole_direction(raw, script)
    assert len(contract.catalog(script)) == beat_count * 3
    assert compiled["script_sha256"] == contract.digest(script)
    opening = contract.compile_opening_performance(performance(script, ["B1.S01", "B1.S02"]), script, ["B1.S01", "B1.S02"])
    prompt = contract.render_opening_prompt(opening, script)
    assert "今天我们把事情说清楚。" in prompt and "我先听你讲完。" not in prompt
