"""Focused stimuli-channel checks; no provider/media operations."""
from copy import deepcopy

from jsonschema import Draft202012Validator
import pytest

from src.content_factory import creative_continuation_probe_contract_v2 as probe
from src.content_factory import creative_continuation_probe_contract_v1 as prior
from src.content_factory import creative_video_trial_contract_v1 as base
from tests.test_creative_continuation_probe_contract_v1 import actual_script, wire as v1_wire, COMPLETED, REFS


def wire(script):
    raw = v1_wire(script)
    for goal in raw["performance"]["actor_goals"]:
        goal["current_stimuli"] = [{"source_ref": "B1.S04", "channel": "visible"}]
        if goal["actor_id"] == "xiaolin":
            goal["current_stimuli"].insert(0, {"source_ref": "B1.S03", "channel": "spoken"})
    return raw


def goal(raw, actor):
    return next(row for row in raw["performance"]["actor_goals"] if row["actor_id"] == actor)


def test_actual_source_channel_schema_and_native_metadata_are_preserved():
    script = actual_script(); raw = wire(script); before = deepcopy(raw)
    schema = probe.continuation_probe_schema(script, COMPLETED, REFS)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(raw)
    compiled = probe.compile_continuation_probe(raw, script, COMPLETED, REFS)
    assert compiled["native"] == raw == before
    assert compiled["performance_compiled"]["native"] == raw["performance"]
    assert compiled["native_sha256"] == base.digest(before)
    assert goal(compiled["native"], "zhou")["current_stimuli"] == [{"source_ref": "B1.S04", "channel": "visible"}]
    assert compiled["stimulus_source_channel_compatibility_validated"]
    assert not compiled["stimulus_prose_semantics_verified"]
    assert compiled["requires_independent_current_review_criteria_count"] == 8


def test_projection_only_removes_stimuli_and_keeps_all_creative_fields_and_timing():
    script = actual_script(); raw = wire(script)
    compiled = probe.compile_continuation_probe(raw, script, COMPLETED, REFS)
    expected = deepcopy(raw)
    for row in expected["performance"]["actor_goals"]: del row["current_stimuli"]
    assert compiled["v1_timing_projection_compiled"] == prior.compile_continuation_probe(expected, script, COMPLETED, REFS)
    assert compiled["v1_timing_projection_sha256"] == base.digest(expected)
    perf = compiled["performance_compiled"]
    assert perf["schedule"] == compiled["v1_timing_projection_compiled"]["performance_compiled"]["schedule"]
    assert perf["normal_spoken_characters_per_second"] == 3.3 and perf["duration_seconds"] == 6


def test_each_actor_requires_nonempty_stimuli_in_public_schema():
    script = actual_script(); schema = probe.continuation_probe_schema(script, COMPLETED, REFS)
    for actor in ["zhou", "xiaolin"]:
        for missing in [True, False]:
            raw = wire(script)
            if missing: del goal(raw, actor)["current_stimuli"]
            else: goal(raw, actor)["current_stimuli"] = []
            assert list(Draft202012Validator(schema).iter_errors(raw))
            with pytest.raises(ValueError): probe.compile_continuation_probe(raw, script, COMPLETED, REFS)


def test_prior_future_and_unknown_source_paths_cannot_be_current_stimuli():
    script = actual_script(); schema = probe.continuation_probe_schema(script, COMPLETED, REFS)
    for ref in ["B1.S02", "B2.S01", "B999.S01"]:
        raw = wire(script); goal(raw, "xiaolin")["current_stimuli"] = [{"source_ref": ref, "channel": "spoken"}]
        assert list(Draft202012Validator(schema).iter_errors(raw))
        with pytest.raises(ValueError): probe.compile_continuation_probe(raw, script, COMPLETED, REFS)


def test_action_spoken_dialogue_visible_and_own_speech_are_publicly_invalid():
    script = actual_script(); schema = probe.continuation_probe_schema(script, COMPLETED, REFS)
    for actor, ref, channel in [("xiaolin", "B1.S04", "spoken"), ("xiaolin", "B1.S03", "visible"),
            ("zhou", "B1.S03", "spoken"), ("zhou", "B1.S04", "thought")]:
        raw = wire(script); goal(raw, actor)["current_stimuli"] = [{"source_ref": ref, "channel": channel}]
        assert list(Draft202012Validator(schema).iter_errors(raw))
        with pytest.raises(ValueError): probe.compile_continuation_probe(raw, script, COMPLETED, REFS)


def test_repeated_stimulus_or_fake_actor_cannot_pass():
    script = actual_script(); raw = wire(script)
    goal(raw, "zhou")["current_stimuli"] *= 2
    with pytest.raises(ValueError): probe.compile_continuation_probe(raw, script, COMPLETED, REFS)
    raw = wire(script); goal(raw, "zhou")["actor_id"] = "unseen_person"
    with pytest.raises(ValueError): probe.compile_continuation_probe(raw, script, COMPLETED, REFS)


def test_render_uses_exact_v1_creative_projection_not_metadata_or_direction():
    script = actual_script(); raw = wire(script)
    raw["current_direction"]["cut_reason"] = "独立渠道审查专用元文句。"
    compiled = probe.compile_continuation_probe(raw, script, COMPLETED, REFS)
    prompt = probe.render_prompt(compiled, script, {"zhou": "周姐", "xiaolin": "小林"})
    assert prompt == prior.render_prompt(compiled["v1_timing_projection_compiled"], script, {"zhou": "周姐", "xiaolin": "小林"})
    assert "current_stimuli" not in prompt and raw["current_direction"]["cut_reason"] not in prompt
    for ref in REFS: assert prompt.count(base.catalog(script)[ref]["text"]) == 1
    assert base.catalog(script)["B2.S01"]["text"] not in prompt


def test_compiled_metadata_projection_source_and_approval_tampering_cannot_render():
    script = actual_script(); compiled = probe.compile_continuation_probe(wire(script), script, COMPLETED, REFS)
    for kind in ["native", "projection", "approval", "source"]:
        changed = deepcopy(compiled)
        if kind == "native": goal(changed["native"], "xiaolin")["current_stimuli"].pop(0)
        elif kind == "projection": changed["v1_timing_projection_compiled"]["native"]["performance"]["ending_state"] += "篡改"
        elif kind == "approval": changed["service_tail_approval_verified"] = True
        else: changed["script_sha256"] = "0" * 64
        with pytest.raises(ValueError): probe.render_prompt(changed, script)
    assert compiled["requires_approved_service_tail_before_media"] and not compiled["service_tail_approval_verified"]
    assert not compiled["whole_direction_accepted"] and not compiled["whole_film_complete"]
    assert compiled["after_generation_content_status"] == "awaiting_human_review"


def test_valid_stimulus_metadata_cannot_prove_free_prose_causality_or_completion():
    script = actual_script(); raw = wire(script)
    goal(raw, "xiaolin")["reception_of_current_stimulus"] = "被周姐说出的个人原因压住了目光。"
    raw["performance"]["ending_state"] = "还没读完纸上的原因栏。"
    compiled = probe.compile_continuation_probe(raw, script, COMPLETED, REFS)
    # An explicit boundary, not an acceptable creative sample: schema cannot
    # infer meaning from this prose. Independent semantic review must reject it.
    assert compiled["native"] == raw and not compiled["stimulus_prose_semantics_verified"]
    assert compiled["requires_independent_current_review"] and not compiled["independent_current_review_complete"]
