"""Offline source-reception/delivery checks; no model or media requests."""
from copy import deepcopy
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from src.content_factory import creative_continuation_probe_contract_v3 as probe
from src.content_factory import creative_continuation_probe_contract_v2 as prior
from src.content_factory import creative_video_trial_contract_v1 as base
from tests.test_creative_continuation_probe_contract_v2 import wire as v2_wire
from tests.test_creative_continuation_probe_contract_v1 import actual_script, COMPLETED, REFS


def wire(script):
    raw = v2_wire(script)
    for goal in raw["performance"]["actor_goals"]:
        goal["source_reception"] = {"stimuli": goal.pop("current_stimuli"),
            "response": goal.pop("reception_of_current_stimulus")}
    raw["performance"].pop("delivery")
    raw["performance"]["dialogue_delivery"] = [{"source_ref": "B1.S03",
        "speech_tone": "正常普通话，语气平稳，保留话音落下的空间。",
        "listener_behavior": "接收者顺着当下注意力看向纸面，不新增抬头复位。"}]
    return raw


def test_actual487_new_schema_native_identity_and_normal_timing_are_preserved():
    script = actual_script(); raw = wire(script); before = deepcopy(raw)
    schema = probe.continuation_probe_schema(script, COMPLETED, REFS)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(raw)
    compiled = probe.compile_continuation_probe(raw, script, COMPLETED, REFS)
    assert compiled["native"] == raw == before
    assert compiled["native_sha256"] == base.digest(raw)
    assert compiled["performance_compiled"]["native"] == raw["performance"]
    assert compiled["performance_compiled"]["duration_seconds"] == 6
    assert compiled["performance_compiled"]["normal_spoken_characters_per_second"] == 3.3
    assert compiled["requires_independent_current_review_criteria_count"] == 8
    assert not compiled["source_references_are_spoken_content"] and compiled["deterministic_projection_only"]


def test_wrong_reception_delivery_types_and_old_fields_are_publicly_rejected():
    script = actual_script(); schema = probe.continuation_probe_schema(script, COMPLETED, REFS)
    for defect in ["reception_string", "stimuli_object", "response_number", "delivery_string", "old_field"]:
        raw = wire(script); goal = raw["performance"]["actor_goals"][0]
        if defect == "reception_string": goal["source_reception"] = "看到对方反应"
        elif defect == "stimuli_object": goal["source_reception"]["stimuli"] = {"source_ref": "B1.S04", "channel": "visible"}
        elif defect == "response_number": goal["source_reception"]["response"] = 1
        elif defect == "delivery_string": raw["performance"]["dialogue_delivery"] = "正常说话"
        else: goal["reception_of_current_stimulus"] = "旧字段"
        assert list(Draft202012Validator(schema).iter_errors(raw))
        with pytest.raises(ValueError): probe.compile_continuation_probe(raw, script, COMPLETED, REFS)


def test_current_stimulus_channel_compatibility_still_rejects_self_speech_or_future():
    script = actual_script(); schema = probe.continuation_probe_schema(script, COMPLETED, REFS)
    for actor, ref, channel in [("zhou", "B1.S03", "spoken"), ("xiaolin", "B1.S04", "spoken"),
            ("xiaolin", "B1.S03", "visible"), ("xiaolin", "B2.S01", "spoken")]:
        raw = wire(script)
        goal = next(row for row in raw["performance"]["actor_goals"] if row["actor_id"] == actor)
        goal["source_reception"]["stimuli"] = [{"source_ref": ref, "channel": channel}]
        assert list(Draft202012Validator(schema).iter_errors(raw))
        with pytest.raises(ValueError): probe.compile_continuation_probe(raw, script, COMPLETED, REFS)


def test_each_dialogue_delivery_must_cover_exact_current_source_once_in_order():
    script = actual_script(); schema = probe.continuation_probe_schema(script, COMPLETED, REFS)
    for defect in ["missing", "duplicate", "previous", "future", "action"]:
        raw = wire(script); rows = raw["performance"]["dialogue_delivery"]
        if defect == "missing": rows.clear()
        elif defect == "duplicate": rows.append(deepcopy(rows[0]))
        else: rows[0]["source_ref"] = {"previous": "B1.S02", "future": "B2.S01", "action": "B1.S04"}[defect]
        assert list(Draft202012Validator(schema).iter_errors(raw))
        with pytest.raises(ValueError): probe.compile_continuation_probe(raw, script, COMPLETED, REFS)


def test_all_free_instruction_fields_block_dialogue_copy_with_local_field_path():
    script = actual_script()
    for source_ref in ["B1.S03", "B2.S01"]:
        quote = base.catalog(script)[source_ref]["text"].rstrip("。")
        for field in ["direction", "continuous", "objective", "response", "tone", "listener", "camera", "ending"]:
            raw = wire(script); perf = raw["performance"]
            if field == "direction": raw["current_direction"]["observation"] += quote; path = "current_direction.observation"
            elif field == "continuous": perf["continuous_performance"] += quote; path = "performance.continuous_performance"
            elif field == "objective": perf["actor_goals"][0]["immediate_objective"] += quote; path = "performance.actor_goals[0].immediate_objective"
            elif field == "response": perf["actor_goals"][0]["source_reception"]["response"] += quote; path = "performance.actor_goals[0].source_reception.response"
            elif field == "tone": perf["dialogue_delivery"][0]["speech_tone"] += quote; path = "performance.dialogue_delivery[0].speech_tone"
            elif field == "listener": perf["dialogue_delivery"][0]["listener_behavior"] += quote; path = "performance.dialogue_delivery[0].listener_behavior"
            elif field == "camera": perf["camera"] += quote; path = "performance.camera"
            else: perf["ending_state"] += quote; path = "performance.ending_state"
            with pytest.raises(ValueError) as exc: probe.compile_continuation_probe(raw, script, COMPLETED, REFS)
            assert "copied current or future source dialogue" in str(exc.value) and path in str(exc.value)


def test_deterministic_projection_preserves_prose_and_render_injects_source_only_once():
    script = actual_script(); raw = wire(script)
    compiled = probe.compile_continuation_probe(raw, script, COMPLETED, REFS)
    projected = compiled["v2_projection_native"]
    assert projected["current_direction"] == raw["current_direction"]
    for original, row in zip(raw["performance"]["actor_goals"], projected["performance"]["actor_goals"]):
        assert row["immediate_objective"] == original["immediate_objective"]
        assert row["reception_of_current_stimulus"] == original["source_reception"]["response"]
        assert row["current_stimuli"] == original["source_reception"]["stimuli"]
    assert compiled["v2_projection_sha256"] == base.digest(projected)
    assert compiled["v2_projection_compiled"] == prior.compile_continuation_probe(projected, script, COMPLETED, REFS)
    prompt = probe.render_prompt(compiled, script, {"zhou": "周姐", "xiaolin": "小林"})
    for ref in REFS: assert prompt.count(base.catalog(script)[ref]["text"]) == 1
    assert base.catalog(script)["B1.S02"]["text"] not in prompt and base.catalog(script)["B2.S01"]["text"] not in prompt
    for row in raw["performance"]["dialogue_delivery"]:
        assert row["speech_tone"] in prompt and row["listener_behavior"] in prompt
    for row in raw["performance"]["actor_goals"]: assert row["source_reception"]["response"] in prompt
    assert "来源编号、刺激渠道及演法说明" in prompt and "不朗读" in prompt


def test_original502_is_not_silently_migrated_or_accepted_by_new_wire():
    root = Path(__file__).resolve().parents[1] / "data/production_revisions/selected_script_video_trial_20261011/script487_continuation_v3"
    path = root / "call_502_continuation_performance.json"
    before = path.read_bytes(); receipt = json.loads(before)
    native = receipt["document_output"]
    with pytest.raises(ValueError): probe.compile_continuation_probe(native, actual_script(), COMPLETED, REFS)
    assert path.read_bytes() == before and receipt["status"] == "contract_rejected"


def test_projection_native_digest_approval_tampering_and_unknown_never_render():
    script = actual_script(); compiled = probe.compile_continuation_probe(wire(script), script, COMPLETED, REFS)
    for defect in ["native", "projection", "compiled_projection", "approval", "source"]:
        changed = deepcopy(compiled)
        if defect == "native": changed["native"]["performance"]["dialogue_delivery"][0]["speech_tone"] += "改字"
        elif defect == "projection": changed["v2_projection_native"]["performance"]["delivery"] += "改字"
        elif defect == "compiled_projection": changed["v2_projection_compiled"]["performance_compiled"]["schedule"][0]["original_text"] = "改字"
        elif defect == "approval": changed["service_tail_approval_verified"] = True
        else: changed["script_sha256"] = "0" * 64
        with pytest.raises(ValueError): probe.render_prompt(changed, script)
    raw = wire(script); raw["performance"]["availability"] = "unknown"
    with pytest.raises(ValueError, match="availability unknown"): probe.compile_continuation_probe(raw, script, COMPLETED, REFS)
    raw = wire(script); raw["performance"]["actor_goals"][1]["source_reception"]["response"] = "先抬头复位再低头。"
    unresolved_semantics = probe.compile_continuation_probe(raw, script, COMPLETED, REFS)
    assert not unresolved_semantics["stimulus_prose_semantics_verified"]
    assert not unresolved_semantics["independent_current_review_complete"] and not unresolved_semantics["actual_media_quality_passed"]
    assert not unresolved_semantics["service_tail_approval_verified"]
    assert unresolved_semantics["after_generation_content_status"] == "awaiting_human_review"
