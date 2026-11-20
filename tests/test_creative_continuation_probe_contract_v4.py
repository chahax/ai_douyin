"""Offline third-segment causes; no model, media or production dispatch."""
from copy import deepcopy

from jsonschema import Draft202012Validator
import pytest

from src.content_factory import creative_continuation_probe_contract_v4 as probe
from src.content_factory import creative_continuation_probe_contract_v3 as prior
from src.content_factory import creative_continuation_probe_contract_v1 as timing
from src.content_factory import creative_video_trial_contract_v1 as base
from tests.test_creative_continuation_probe_contract_v1 import actual_script

COMPLETED = ["B1.S01", "B1.S02", "B1.S03", "B1.S04"]
REFS = ["B2.S01", "B2.S02"]


def wire(script):
    return {"script_sha256": base.digest(script), "source_refs": REFS[:],
        "current_direction": {"information_change": "小林把纸面原因与公司刚作出的决定当面提出矛盾。",
            "observation": "小林开口的面部与指尖保持同一空间关系。",
            "stimulus_reaction": "上一段已经读清原因，小林带着不解质问，周姐听见他的话。",
            "cut_reason": "完整说完后留出对方接收的空间，不提前演下一轮。"},
        "performance": {"script_sha256": base.digest(script), "source_refs": REFS[:], "availability": "known",
            "continuous_performance": "承接目光仍在纸上的终态，小林自然开口，抬起手指悬在字上方，纸笔保持原位。",
            "actor_goals": [{"actor_id": "zhou", "immediate_objective": "听清小林当场指出的问题。",
                "source_reception": {"stimuli": [{"phase": "current", "source_ref": "B2.S01", "channel": "spoken"}],
                    "response": "听见对方指出矛盾，保持坐姿接收，不提前解释或劝说。"}},
                {"actor_id": "xiaolin", "immediate_objective": "把已读到的原因与公司决定之间的矛盾说清楚。",
                 "source_reception": {"stimuli": [{"phase": "completed", "source_ref": "B1.S04", "channel": "visible"}],
                    "response": "已经看清纸上原因，带着不解和不满开口，手指停住，不替周姐回答。"}}],
            "camera": "沿上一段空间保持小林面部可读，指尖入画而纸张不挪动。",
            "spoken_language": "zh-CN", "dialogue_delivery": [{"source_ref": "B2.S01",
                "speech_tone": "正常普通话，疑惑渐转明确，不急促念词。",
                "listener_behavior": "周姐听着，不接未来对白或提前劝说。"}],
            "action_timings": [{"source_ref": "B2.S02", "duration_seconds": 2,
                "overlap_with": "B2.S01", "overlap_offset_seconds": 4.3}],
            "post_reaction_seconds": 2,
            "ending_state": "小林手指悬在原因栏上方，不碰纸，纸笔仍在周姐侧，双方坐姿延续。"}}


def test_actual487_third_segment_can_bind_completed_visible_cause_and_current_listener():
    script = actual_script(); raw = wire(script); original = deepcopy(raw)
    schema = probe.continuation_probe_schema(script, COMPLETED, REFS)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(raw)
    compiled = probe.compile_continuation_probe(raw, script, COMPLETED, REFS)
    assert raw == original == compiled["native"]
    assert compiled["native_sha256"] == base.digest(raw)
    assert compiled["performance_compiled"]["native"] == raw["performance"]
    assert compiled["performance_compiled"]["duration_seconds"] == 12
    assert compiled["performance_compiled"]["total_seconds"] == pytest.approx(31 / 3.3 + 2, abs=1e-6)
    assert compiled["performance_compiled"]["normal_spoken_characters_per_second"] == 3.3
    assert compiled["stimulus_phase_channel_compatibility_validated"]
    assert compiled["requires_independent_current_review_criteria_count"] == 8


def test_phase_channel_self_speech_and_future_defects_are_publicly_rejected():
    script = actual_script(); schema = probe.continuation_probe_schema(script, COMPLETED, REFS)
    cases = [("xiaolin", "current", "B2.S01", "spoken"),
        ("zhou", "completed", "B1.S03", "spoken"),
        ("xiaolin", "completed", "B1.S04", "spoken"),
        ("zhou", "current", "B2.S01", "visible"),
        ("zhou", "current", "B2.S03", "spoken"),
        ("xiaolin", "current", "B1.S04", "visible"),
        ("xiaolin", "completed", "B2.S02", "visible"),
        ("xiaolin", "future", "B1.S04", "visible")]
    for actor, phase, ref, channel in cases:
        raw = wire(script)
        goal = next(q for q in raw["performance"]["actor_goals"] if q["actor_id"] == actor)
        goal["source_reception"]["stimuli"] = [{"phase": phase, "source_ref": ref, "channel": channel}]
        assert list(Draft202012Validator(schema).iter_errors(raw))
        with pytest.raises(ValueError): probe.compile_continuation_probe(raw, script, COMPLETED, REFS)


def test_old_v3_native_without_phase_is_not_silently_upgraded():
    script = actual_script(); raw = wire(script)
    for goal in raw["performance"]["actor_goals"]:
        for stimulus in goal["source_reception"]["stimuli"]: del stimulus["phase"]
    raw["performance"]["actor_goals"][1]["source_reception"]["stimuli"] = [
        {"source_ref": "B2.S02", "channel": "visible"}]
    prior.compile_continuation_probe(raw, script, COMPLETED, REFS)
    original = deepcopy(raw)
    with pytest.raises(ValueError): probe.compile_continuation_probe(raw, script, COMPLETED, REFS)
    assert raw == original


def test_completed_context_has_only_exact_prefix_and_never_future_or_playback_sources():
    script = actual_script(); source = probe.continuation_source(script, COMPLETED, REFS)
    assert list(source["completed_stimulus_sources"]) == COMPLETED
    assert list(source["current_sources"]) == REFS
    assert "B2.S03" not in source["completed_stimulus_sources"]
    assert source["completed_sources_are_context_only"] and source["only_current_source_refs_are_performed"]
    for completed, refs in [(COMPLETED[1:], REFS), (COMPLETED[::-1], REFS),
            (COMPLETED, ["B2.S02"]), (COMPLETED, ["B2.S01", "B2.S03"])]:
        with pytest.raises(ValueError): probe.continuation_source(script, completed, refs)


def test_projection_keeps_all_prose_but_past_metadata_is_never_rendered_or_scheduled():
    script = actual_script(); raw = wire(script)
    compiled = probe.compile_continuation_probe(raw, script, COMPLETED, REFS)
    projected = compiled["v1_projection_native"]
    assert projected["current_direction"] == raw["current_direction"]
    for original, row in zip(raw["performance"]["actor_goals"], projected["performance"]["actor_goals"]):
        assert original["immediate_objective"] == row["immediate_objective"]
        assert original["source_reception"]["response"] == row["reception_of_current_stimulus"]
        assert "current_stimuli" not in row and "source_reception" not in row
    assert compiled["v1_projection_sha256"] == base.digest(projected)
    assert compiled["v1_projection_compiled"] == timing.compile_continuation_probe(projected, script, COMPLETED, REFS)
    assert [row["source_ref"] for row in compiled["performance_compiled"]["schedule"]] == REFS
    prompt = probe.render_prompt(compiled, script, {"zhou": "周姐", "xiaolin": "小林"})
    catalog = base.catalog(script)
    for ref in REFS: assert prompt.count(catalog[ref]["text"]) == 1
    for ref in COMPLETED + ["B2.S03", "B2.S04"]: assert catalog[ref]["text"] not in prompt
    for goal in raw["performance"]["actor_goals"]: assert goal["source_reception"]["response"] in prompt
    assert "已完成的刺激不重演" in prompt and "不朗读" in prompt


def test_dialogue_copy_guard_still_blocks_completed_current_and_future_with_local_path():
    script = actual_script(); catalog = base.catalog(script)
    for ref in ["B1.S03", "B2.S01", "B2.S03"]:
        raw = wire(script)
        raw["performance"]["actor_goals"][1]["source_reception"]["response"] += catalog[ref]["text"].rstrip("。！？")
        with pytest.raises(ValueError, match=r"performance.actor_goals\[1\].source_reception.response"):
            probe.compile_continuation_probe(raw, script, COMPLETED, REFS)


def test_native_context_projection_timing_and_approval_tampering_never_render():
    script = actual_script(); compiled = probe.compile_continuation_probe(wire(script), script, COMPLETED, REFS)
    for defect in ["native", "context", "projection", "compiled_projection", "approval", "source"]:
        changed = deepcopy(compiled)
        if defect == "native": changed["native"]["performance"]["actor_goals"][1]["source_reception"]["stimuli"][0]["phase"] = "current"
        elif defect == "context": changed["completed_stimulus_sources"]["B1.S04"]["text"] += "改字"
        elif defect == "projection": changed["v1_projection_native"]["performance"]["delivery"] += "改字"
        elif defect == "compiled_projection": changed["v1_projection_compiled"]["performance_compiled"]["schedule"][0]["original_text"] = "改字"
        elif defect == "approval": changed["service_tail_approval_verified"] = True
        else: changed["script_sha256"] = "0" * 64
        with pytest.raises(ValueError): probe.render_prompt(changed, script)


def test_source_metadata_does_not_approve_media_or_prove_free_text_semantics():
    script = actual_script(); raw = wire(script)
    raw["performance"]["availability"] = "unknown"
    with pytest.raises(ValueError, match="availability unknown"):
        probe.compile_continuation_probe(raw, script, COMPLETED, REFS)
    raw = wire(script)
    raw["performance"]["actor_goals"][1]["source_reception"]["response"] = "先无因抬头复位，再重新低头看纸。"
    compiled = probe.compile_continuation_probe(raw, script, COMPLETED, REFS)
    assert not compiled["stimulus_prose_semantics_verified"] and not compiled["independent_current_review_complete"]
    assert not compiled["service_tail_approval_verified"] and not compiled["actual_media_quality_passed"]
    assert not compiled["machine_quality"] and not compiled["whole_film_complete"]
    assert compiled["after_generation_content_status"] == "awaiting_human_review"


def test_current_action_overlap_preserves_normal_speed_and_never_fits_overlong_range():
    script = actual_script(); raw = wire(script)
    compiled = probe.compile_continuation_probe(raw, script, COMPLETED, REFS)
    action = compiled["performance_compiled"]["schedule"][1]
    assert action["start_seconds"] == 4.3 and action["end_seconds"] == 6.3
    assert not compiled["performance_compiled"]["fit_scaled"] and not compiled["performance_compiled"]["measured_audio"]
    raw["performance"]["action_timings"][0]["overlap_with"] = ""
    raw["performance"]["action_timings"][0]["overlap_offset_seconds"] = 0
    raw["performance"]["action_timings"][0]["duration_seconds"] = 5
    with pytest.raises(ValueError, match="exceeds fifteen seconds"):
        probe.compile_continuation_probe(raw, script, COMPLETED, REFS)
