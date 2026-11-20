"""Offline metadata compiler candidate; old509 remains an immutable failure."""
from copy import deepcopy
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from src.content_factory import creative_continuation_probe_contract_v7 as probe
from src.content_factory import creative_continuation_probe_contract_v6 as prior
from src.content_factory import creative_video_trial_contract_v1 as base
from tests.test_creative_continuation_probe_contract_v5 import actual_script, COMPLETED, REFS, frozen_scene, approved_metadata, wire as full_wire


def context(script):
    return probe.build_scene_continuity_context(script, frozen_scene(), approved_metadata())


def wire(script):
    raw = full_wire(script)
    for key in ("script_sha256", "source_refs"): del raw[key]
    for key in ("script_sha256", "source_refs", "camera", "spoken_language"): del raw["performance"][key]
    return raw


def test_new_wire_has_no_constant_identity_metadata_and_compiles_from_frozen_inputs():
    script = actual_script(); raw = wire(script); ctx = context(script)
    schema = probe.continuation_probe_schema(script, COMPLETED, REFS, ctx)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(raw)
    assert set(schema["properties"]) == {"current_direction", "performance"}
    for key in ("script_sha256", "source_refs", "camera", "spoken_language"):
        assert key not in schema["properties"]["performance"]["properties"]
    assert base.digest(script) not in json.dumps(raw, ensure_ascii=False)
    compiled = probe.compile_continuation_probe(raw, script, COMPLETED, REFS, ctx)
    assert compiled["derived_metadata"] == {"script_sha256": base.digest(script), "source_refs": REFS,
        "camera": "retain_approved_frame", "spoken_language": "zh-CN"}
    assert compiled["performance_compiled"]["duration_seconds"] == 12
    assert compiled["requires_independent_current_review_criteria_count"] == 10
    assert compiled["deployment_scope"] == "offline_only" and not compiled["production_calls_authorized_by_contract"]
    assert "camera只能填" not in probe.RULE


def test_any_model_supplied_constant_identity_field_is_rejected_even_if_correct():
    script = actual_script(); ctx = context(script)
    for location, key, value in [("root", "script_sha256", base.digest(script)),
            ("root", "source_refs", REFS), ("performance", "script_sha256", "0" * 64),
            ("performance", "source_refs", REFS), ("performance", "camera", "retain_approved_frame"),
            ("performance", "spoken_language", "zh-CN")]:
        raw = wire(script)
        owner = raw if location == "root" else raw["performance"]
        owner[key] = deepcopy(value)
        before = deepcopy(raw)
        with pytest.raises(ValueError): probe.compile_continuation_probe(raw, script, COMPLETED, REFS, ctx)
        assert raw == before


def test_original509_native_is_neither_transformed_nor_rejudged_as_accepted():
    path = Path(__file__).resolve().parents[1] / "data/production_revisions/selected_script_video_trial_20261011/script487_continuation_v7/call_509_continuation_performance.json"
    before = path.read_bytes(); receipt = json.loads(before)
    native = json.loads(receipt["output"]["payload_json"])
    original = deepcopy(native); script = actual_script()
    assert receipt["status"] == "contract_rejected" and native["script_sha256"] != base.digest(script)
    with pytest.raises(ValueError): probe.compile_continuation_probe(native, script, COMPLETED, REFS, context(script))
    assert native == original and path.read_bytes() == before


def test_projection_injects_only_constants_and_preserves_every_native_creative_value():
    script = actual_script(); raw = wire(script); original = deepcopy(raw)
    compiled = probe.compile_continuation_probe(raw, script, COMPLETED, REFS, context(script))
    assert raw == original == compiled["native"]
    assert compiled["native_sha256"] == base.digest(raw)
    assert compiled["performance_compiled"]["native"] == raw["performance"]
    assert not compiled["creative_fields_rewritten"] and not compiled["legacy_failed_response_adopted"]
    projected = deepcopy(compiled["v6_projection_native"])
    for key in ("script_sha256", "source_refs"): del projected[key]
    for key in ("script_sha256", "source_refs", "camera", "spoken_language"): del projected["performance"][key]
    assert projected == raw
    assert compiled["v6_projection_sha256"] == base.digest(compiled["v6_projection_native"])
    assert compiled["derived_metadata_sha256"] == base.digest(compiled["derived_metadata"])
    v6ctx = prior.build_scene_continuity_context(script, frozen_scene(), approved_metadata())
    assert compiled["v6_projection_compiled"] == prior.compile_continuation_probe(
        compiled["v6_projection_native"], script, COMPLETED, REFS, v6ctx)


def test_required_local_references_types_and_spatial_guards_stay_strict():
    script = actual_script(); ctx = context(script)
    for defect in ["future_delivery", "future_action", "wrong_phase", "self_speech", "spatial", "missing_delivery", "availability"]:
        raw = wire(script); perf = raw["performance"]
        if defect == "future_delivery": perf["dialogue_delivery"][0]["source_ref"] = "B2.S03"
        elif defect == "future_action": perf["action_timings"][0]["source_ref"] = "B2.S04"
        elif defect == "wrong_phase": perf["actor_goals"][1]["source_reception"]["stimuli"][0]["phase"] = "current"
        elif defect == "self_speech": perf["actor_goals"][1]["source_reception"]["stimuli"] = [
            {"phase": "current", "source_ref": "B2.S01", "channel": "spoken"}]
        elif defect == "spatial": raw["current_direction"]["observation"] = "周姐保持画右原位，小林侧脸中近景。"
        elif defect == "missing_delivery": del perf["dialogue_delivery"]
        else: perf["availability"] = "unknown"
        with pytest.raises(ValueError): probe.compile_continuation_probe(raw, script, COMPLETED, REFS, ctx)
    raw = wire(script); raw["performance"]["dialogue_delivery"][0]["speech_tone"] += base.catalog(script)["B2.S03"]["text"]
    with pytest.raises(ValueError): probe.compile_continuation_probe(raw, script, COMPLETED, REFS, ctx)


def test_derived_metadata_native_context_and_projection_tampering_all_block_render():
    script = actual_script(); compiled = probe.compile_continuation_probe(wire(script), script, COMPLETED, REFS, context(script))
    for defect in ["metadata", "native", "projection", "compiled_projection", "context", "approval", "source"]:
        changed = deepcopy(compiled)
        if defect == "metadata": changed["derived_metadata"]["script_sha256"] = "0" * 64
        elif defect == "native": changed["native"]["performance"]["ending_state"] += "另写终态"
        elif defect == "projection": changed["v6_projection_native"]["performance"]["spoken_language"] = "ja-JP"
        elif defect == "compiled_projection": changed["v6_projection_compiled"]["performance_compiled"]["schedule"][0]["original_text"] = "换台词"
        elif defect == "context": changed["scene_continuity_context"]["scene_id"] = "hallway"
        elif defect == "approval": changed["service_tail_approval_verified"] = True
        else: changed["script_sha256"] = "0" * 64
        with pytest.raises(ValueError): probe.render_prompt(changed, script)


def test_render_injects_current_source_once_and_keeps_closed_cast_and_frame_authority():
    script = actual_script(); raw = wire(script)
    compiled = probe.compile_continuation_probe(raw, script, COMPLETED, REFS, context(script))
    prompt = probe.render_prompt(compiled, script, {"zhou": "周姐", "xiaolin": "小林"})
    catalog = base.catalog(script)
    for ref in REFS: assert prompt.count(catalog[ref]["text"]) == 1
    for ref in COMPLETED + ["B2.S03", "B2.S04"]: assert catalog[ref]["text"] not in prompt
    assert "本场闭合演员表：周姐、小林，共2人" in prompt
    assert "绝对布局以输入原帧为准" in prompt and "自然中文普通话" in prompt
    for goal in raw["performance"]["actor_goals"]: assert goal["source_reception"]["response"] in prompt
    assert not compiled["actual_media_quality_passed"] and not compiled["service_tail_approval_verified"]
    assert compiled["after_generation_content_status"] == "awaiting_human_review"


def test_source_context_wrong_binding_and_nonadjacent_scope_cannot_be_hidden_by_metadata_compilation():
    script = actual_script(); ctx = context(script)
    changed = deepcopy(script); changed["title"] += "另稿"
    with pytest.raises(ValueError): probe.compile_continuation_probe(wire(script), changed, COMPLETED, REFS, ctx)
    changed = deepcopy(ctx); changed["script_sha256"] = "0" * 64
    with pytest.raises(ValueError): probe.continuation_probe_schema(script, COMPLETED, REFS, changed)
    with pytest.raises(ValueError): probe.compile_continuation_probe(wire(script), script, COMPLETED, ["B2.S02"], ctx)
    assert probe.continuation_source(script, COMPLETED, REFS, ctx)["fixed_response_metadata_generated_by_model"] is False
