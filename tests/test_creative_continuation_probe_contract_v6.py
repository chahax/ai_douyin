"""Read-only actual507 regression and public spatial rules; no paid calls."""
from copy import deepcopy
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from src.content_factory import creative_continuation_probe_contract_v6 as probe
from src.content_factory import creative_continuation_probe_contract_v5 as prior
from src.content_factory import creative_video_trial_contract_v1 as base
from tests.test_creative_continuation_probe_contract_v5 import actual_script, COMPLETED, REFS, frozen_scene, approved_metadata, wire


def context(script):
    return probe.build_scene_continuity_context(script, frozen_scene(), approved_metadata())


def targets(raw):
    for key in raw["current_direction"]:
        yield "current_direction." + key, raw["current_direction"], key
    performance = raw["performance"]
    for key in ("continuous_performance", "ending_state"):
        yield "performance." + key, performance, key
    for index, goal in enumerate(performance["actor_goals"]):
        yield f"performance.actor_goals[{index}].immediate_objective", goal, "immediate_objective"
        yield f"performance.actor_goals[{index}].source_reception.response", goal["source_reception"], "response"
    for index, row in enumerate(performance["dialogue_delivery"]):
        for key in ("speech_tone", "listener_behavior"):
            yield f"performance.dialogue_delivery[{index}].{key}", row, key


def test_original507_is_preserved_but_new_contract_rejects_guessed_screen_positions():
    path = Path(__file__).resolve().parents[1] / "data/production_revisions/selected_script_video_trial_20261011/script487_continuation_v6/call_507_continuation_performance.json"
    before = path.read_bytes(); receipt = json.loads(before)
    native = receipt["document_output"]; original = deepcopy(native)
    script = actual_script()
    prior.compile_continuation_probe(native, script, COMPLETED, REFS,
        prior.build_scene_continuity_context(script, frozen_scene(), approved_metadata()))
    schema = probe.continuation_probe_schema(script, COMPLETED, REFS, context(script))
    assert list(Draft202012Validator(schema).iter_errors(native))
    with pytest.raises(ValueError, match=r"current_direction.observation: 下半画面"):
        probe.compile_continuation_probe(native, script, COMPLETED, REFS, context(script))
    assert native == original and path.read_bytes() == before


def test_normal_frame_retention_passes_without_changing_any_native_creative_text():
    script = actual_script(); raw = wire(script); original = deepcopy(raw)
    ctx = context(script); schema = probe.continuation_probe_schema(script, COMPLETED, REFS, ctx)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(raw)
    compiled = probe.compile_continuation_probe(raw, script, COMPLETED, REFS, ctx)
    assert compiled["native"] == original == raw
    assert compiled["native_sha256"] == base.digest(raw)
    assert compiled["scene_continuity_context"]["schema"] == probe.VERSION + "/scene_continuity_context"
    assert compiled["performance_compiled"]["native"] == raw["performance"]
    assert compiled["performance_compiled"]["duration_seconds"] == 12
    assert compiled["requires_independent_current_review_criteria_count"] == 10
    assert compiled["spatial_prose_guard_validated"] and not compiled["spatial_prose_guard_is_semantic_proof"]


def test_every_free_field_rejects_coordinates_in_public_schema_and_locates_failure():
    script = actual_script(); ctx = context(script)
    schema = probe.continuation_probe_schema(script, COMPLETED, REFS, ctx)
    paths = [path for path, _, _ in targets(wire(script))]
    assert len(paths) == 12
    for path in paths:
        raw = wire(script)
        _, owner, key = next(row for row in targets(raw) if row[0] == path)
        owner[key] += "周姐保持画右原位。"
        assert list(Draft202012Validator(schema).iter_errors(raw))
        with pytest.raises(ValueError) as error:
            probe.compile_continuation_probe(raw, script, COMPLETED, REFS, ctx)
        assert "unverified spatial declaration at " + path in str(error.value)


def test_named_coordinate_and_camera_classes_are_rejected_without_semantic_patch():
    script = actual_script(); ctx = context(script)
    schema = probe.continuation_probe_schema(script, COMPLETED, REFS, ctx)
    for phrase in ["周姐画右", "小林画左", "人在画面左侧", "人在画面右侧", "纸在下半画面",
            "上半画面留给两人", "纸在画面下半幅", "小林侧脸中近景", "换成过肩镜头", "俯拍", "反打", "重新设置机位"]:
        raw = wire(script); raw["current_direction"]["observation"] = phrase
        assert list(Draft202012Validator(schema).iter_errors(raw))
        original = deepcopy(raw)
        with pytest.raises(ValueError): probe.compile_continuation_probe(raw, script, COMPLETED, REFS, ctx)
        assert raw == original


def test_source_relative_hands_and_props_are_not_mistaken_for_screen_coordinates():
    script = actual_script(); raw = wire(script)
    for _, owner, key in targets(raw):
        owner[key] += "右手食指悬停，纸笔仍在周姐一侧。"
    before = deepcopy(raw)
    compiled = probe.compile_continuation_probe(raw, script, COMPLETED, REFS, context(script))
    assert raw == before == compiled["native"]
    assert compiled["performance_compiled"]["normal_spoken_characters_per_second"] == 3.3


def test_camera_enum_and_context_injection_cannot_bypass_public_guard():
    script = actual_script(); ctx = context(script)
    raw = wire(script); raw["performance"]["camera"] = "周姐在画面右侧"
    with pytest.raises(ValueError): probe.compile_continuation_probe(raw, script, COMPLETED, REFS, ctx)
    raw = wire(script); raw["scene_continuity_context"] = ctx
    with pytest.raises(ValueError): probe.compile_continuation_probe(raw, script, COMPLETED, REFS, ctx)
    changed = deepcopy(ctx); changed["spatial_layout_authority"] = "model_guessed_right"
    with pytest.raises(ValueError): probe.continuation_source(script, COMPLETED, REFS, changed)
    changed = deepcopy(ctx); changed["frame_right_actor"] = "zhou"
    with pytest.raises(ValueError): probe.continuation_probe_schema(script, COMPLETED, REFS, changed)


def test_current_only_render_keeps_frame_authority_and_never_renders_old_context_or_sources():
    script = actual_script(); raw = wire(script)
    compiled = probe.compile_continuation_probe(raw, script, COMPLETED, REFS, context(script))
    prompt = probe.render_prompt(compiled, script, {"zhou": "周姐", "xiaolin": "小林"})
    assert "本场闭合演员表：周姐、小林，共2人" in prompt
    assert "绝对布局以输入原帧为准" in prompt
    assert prior.CAMERA_INSTRUCTION in prompt
    catalog = base.catalog(script)
    for ref in REFS: assert prompt.count(catalog[ref]["text"]) == 1
    for ref in COMPLETED + ["B2.S03", "B2.S04"]: assert catalog[ref]["text"] not in prompt
    assert "尚未听到公司决定" not in prompt
    for path, _, _ in targets(raw): assert path not in prompt


def test_projection_or_context_tamper_unknown_and_semantic_falsepass_remain_blocked_or_unverified():
    script = actual_script(); compiled = probe.compile_continuation_probe(wire(script), script, COMPLETED, REFS, context(script))
    for defect in ["native", "projection", "context", "approval"]:
        changed = deepcopy(compiled)
        if defect == "native": changed["native"]["performance"]["ending_state"] = "小林在画左。"
        elif defect == "projection": changed["v1_projection_native"]["performance"]["camera"] = "改机位"
        elif defect == "context": changed["scene_continuity_context"]["scene_id"] = "hallway"
        else: changed["service_tail_approval_verified"] = True
        with pytest.raises(ValueError): probe.render_prompt(changed, script)
    raw = wire(script); raw["performance"]["availability"] = "unknown"
    with pytest.raises(ValueError, match="availability unknown"):
        probe.compile_continuation_probe(raw, script, COMPLETED, REFS, context(script))
    raw = wire(script); raw["performance"]["ending_state"] = "额外一名旁观者坐下。"
    unresolved = probe.compile_continuation_probe(raw, script, COMPLETED, REFS, context(script))
    assert not unresolved["actual_spatial_continuity_verified"]
    assert not unresolved["independent_current_review_complete"] and not unresolved["actual_media_quality_passed"]
    assert unresolved["after_generation_content_status"] == "awaiting_human_review"
