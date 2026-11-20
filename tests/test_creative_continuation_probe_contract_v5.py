"""Frame-owned camera and source cast checks; no media or model calls."""
from copy import deepcopy

from jsonschema import Draft202012Validator
import pytest

from src.content_factory import creative_continuation_probe_contract_v5 as probe
from src.content_factory import creative_continuation_probe_contract_v1 as timing
from src.content_factory import creative_video_trial_contract_v1 as base
from tests.test_creative_continuation_probe_contract_v4 import actual_script, COMPLETED, REFS, wire as v4_wire


def frozen_scene():
    return {"characters": [{"id": "xiaolin", "name": "小林", "role": "员工"},
        {"id": "zhou", "name": "周姐", "role": "人事主管"}],
        "scenes": [{"id": "meeting_room", "description": "同一小会议室"}],
        "initial_state": {"scene_id": "meeting_room",
            "character_states": [{"id": "xiaolin", "expected_state": "尚未听到公司决定"}],
            "prop_states": [{"id": "application", "expected_state": "旧稿最初的纸笔状态"}]}}


def approved_metadata():
    return {"path": "D:/offline/original.provider_last.png", "sha256": "a" * 64,
        "role": "first_frame", "source": "generation_service_original",
        "source_task_id": "offline-parent-task", "source_segment_id": "offline-parent-segment",
        "source_video_sha256": "b" * 64, "human_review_path": "D:/offline/receipt.human_review.json"}


def context(script):
    return probe.build_scene_continuity_context(script, frozen_scene(), approved_metadata())


def wire(script):
    raw = v4_wire(script)
    raw["performance"]["camera"] = "retain_approved_frame"
    return raw


def test_context_derives_complete_source_cast_scene_and_retains_metadata_without_pixel_guesses():
    script = actual_script(); source = frozen_scene(); frame = approved_metadata()
    before = (deepcopy(source), deepcopy(frame))
    result = probe.build_scene_continuity_context(script, source, frame)
    assert (source, frame) == before
    assert result["actor_ids"] == ["zhou", "xiaolin"] and result["actor_count"] == 2
    assert result["scene_id"] == "meeting_room" and result["approved_first_frame"] == frame
    assert result["source_scene_and_character_context_sha256"] == base.digest(source)
    assert result["approved_first_frame_metadata_sha256"] == base.digest(frame)
    assert not result["pixel_layout_inferred"] and not result["force_all_actors_in_frame"]
    assert result["preserve_frame_occlusion_and_out_of_frame"] and not result["additional_people_allowed"]
    assert result["approval_verification_is_runner_owned"]


def test_extra_missing_duplicate_cast_or_undeclared_scene_is_not_compiled():
    script = actual_script()
    for defect in ["third", "missing", "duplicate", "unknown_scene"]:
        source = frozen_scene()
        if defect == "third": source["characters"].append({"id": "other", "name": "第三人"})
        elif defect == "missing": source["characters"].pop()
        elif defect == "duplicate": source["characters"].append(deepcopy(source["characters"][0]))
        else: source["initial_state"]["scene_id"] = "new_office"
        with pytest.raises(ValueError): probe.build_scene_continuity_context(script, source, approved_metadata())


def test_camera_enum_is_public_and_old_free_camera_or_model_context_is_rejected():
    script = actual_script(); ctx = context(script)
    schema = probe.continuation_probe_schema(script, COMPLETED, REFS, ctx)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(wire(script))
    for camera in ["小林在左，周姐在右，正面换角度", "reverse_angle", "", {"mode": "retain_approved_frame"}]:
        raw = wire(script); raw["performance"]["camera"] = camera
        assert list(Draft202012Validator(schema).iter_errors(raw))
        with pytest.raises(ValueError): probe.compile_continuation_probe(raw, script, COMPLETED, REFS, ctx)
    raw = wire(script); raw["scene_continuity_context"] = ctx
    with pytest.raises(ValueError): probe.compile_continuation_probe(raw, script, COMPLETED, REFS, ctx)


def test_valid_native_and_creative_prose_survive_protocol_camera_expansion_and_normal_timing():
    script = actual_script(); raw = wire(script); original = deepcopy(raw)
    compiled = probe.compile_continuation_probe(raw, script, COMPLETED, REFS, context(script))
    assert raw == original == compiled["native"]
    assert compiled["native_sha256"] == base.digest(raw)
    assert compiled["performance_compiled"]["native"] == raw["performance"]
    projected = compiled["v1_projection_native"]
    assert projected["current_direction"] == raw["current_direction"]
    assert projected["performance"]["continuous_performance"] == raw["performance"]["continuous_performance"]
    assert projected["performance"]["camera"] == probe.CAMERA_INSTRUCTION
    for original_goal, goal in zip(raw["performance"]["actor_goals"], projected["performance"]["actor_goals"]):
        assert goal["immediate_objective"] == original_goal["immediate_objective"]
        assert goal["reception_of_current_stimulus"] == original_goal["source_reception"]["response"]
    assert compiled["v1_projection_compiled"] == timing.compile_continuation_probe(projected, script, COMPLETED, REFS)
    assert compiled["performance_compiled"]["duration_seconds"] == 12
    assert compiled["requires_independent_current_review_criteria_count"] == 10
    assert "独立8项审查" not in probe.RULE


def test_actual_prompt_contains_closed_cast_same_scene_frame_authority_without_old_initial_state_or_past_playback():
    script = actual_script(); raw = wire(script)
    compiled = probe.compile_continuation_probe(raw, script, COMPLETED, REFS, context(script))
    prompt = probe.render_prompt(compiled, script, {"zhou": "周姐", "xiaolin": "小林"})
    assert "本场闭合演员表：周姐、小林，共2人" in prompt
    assert "不新增入场者、旁观者、额外人物或分身" in prompt
    assert "延续同一场景" in prompt and "绝对布局以输入原帧为准" in prompt
    assert "当前情境与新增信息（不复演过去）：" + raw['current_direction']['information_change'] in prompt
    assert 'meeting_room' not in prompt
    assert "保留原帧已有的遮挡和出画，不强制所有人同时居中" in prompt
    assert probe.CAMERA_INSTRUCTION in prompt
    assert "小林在左" not in prompt and "周姐在右" not in prompt
    assert "尚未听到公司决定" not in prompt and "旧稿最初的纸笔状态" not in prompt
    assert "offline-parent-task" not in prompt and "receipt.human_review.json" not in prompt
    catalog = base.catalog(script)
    for ref in REFS: assert prompt.count(catalog[ref]["text"]) == 1
    for ref in COMPLETED + ["B2.S03", "B2.S04"]: assert catalog[ref]["text"] not in prompt


def test_context_hash_source_frame_and_projection_changes_are_blocked_before_render():
    script = actual_script(); ctx = context(script)
    for field, value in [("script_sha256", "0" * 64), ("scene_id", "hallway"),
            ("actor_ids", ["zhou", "xiaolin", "other"]), ("force_all_actors_in_frame", True),
            ("pixel_layout_inferred", True)]:
        changed = deepcopy(ctx); changed[field] = value
        with pytest.raises(ValueError): probe.continuation_source(script, COMPLETED, REFS, changed)
    compiled = probe.compile_continuation_probe(wire(script), script, COMPLETED, REFS, ctx)
    for defect in ["camera", "frame", "projection", "approval"]:
        changed = deepcopy(compiled)
        if defect == "camera": changed["native"]["performance"]["camera"] = "reverse_angle"
        elif defect == "frame": changed["scene_continuity_context"]["approved_first_frame"]["sha256"] = "c" * 64
        elif defect == "projection": changed["v1_projection_native"]["performance"]["camera"] += "改字"
        else: changed["service_tail_approval_verified"] = True
        with pytest.raises(ValueError): probe.render_prompt(changed, script)


def test_tail_metadata_must_bind_service_original_identity_but_cannot_replace_runner_approval():
    script = actual_script()
    for field, value in [("source", "assistant_extracted_frame"), ("role", "reference_image"),
            ("sha256", "unknown"), ("source_video_sha256", None)]:
        frame = approved_metadata(); frame[field] = value
        with pytest.raises(ValueError): probe.build_scene_continuity_context(script, frozen_scene(), frame)
    frame = approved_metadata(); frame["left_character"] = "xiaolin"
    with pytest.raises(ValueError): probe.build_scene_continuity_context(script, frozen_scene(), frame)
    compiled = probe.compile_continuation_probe(wire(script), script, COMPLETED, REFS, context(script))
    assert not compiled["service_tail_approval_verified"] and not compiled["actual_spatial_continuity_verified"]
    assert not compiled["actual_media_quality_passed"] and not compiled["machine_quality"]
    assert compiled["after_generation_content_status"] == "awaiting_human_review"


def test_causal_phase_future_copy_and_unknown_guards_remain_independent_of_camera_fix():
    script = actual_script(); ctx = context(script)
    raw = wire(script)
    raw["performance"]["actor_goals"][1]["source_reception"]["stimuli"] = [{
        "phase": "current", "source_ref": "B2.S01", "channel": "spoken"}]
    with pytest.raises(ValueError): probe.compile_continuation_probe(raw, script, COMPLETED, REFS, ctx)
    raw = wire(script); raw["performance"]["continuous_performance"] += base.catalog(script)["B2.S03"]["text"]
    with pytest.raises(ValueError, match="performance.continuous_performance"):
        probe.compile_continuation_probe(raw, script, COMPLETED, REFS, ctx)
    raw = wire(script); raw["performance"]["availability"] = "unknown"
    with pytest.raises(ValueError, match="availability unknown"):
        probe.compile_continuation_probe(raw, script, COMPLETED, REFS, ctx)
    raw = wire(script); raw["performance"]["ending_state"] = "凭空多一位旁观者坐下。"
    compiled = probe.compile_continuation_probe(raw, script, COMPLETED, REFS, ctx)
    assert not compiled["independent_current_review_complete"]
    assert not compiled["actual_spatial_continuity_verified"]
