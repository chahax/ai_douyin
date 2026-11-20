"""Small offline isolated-opening checks; no provider/media operations."""
from copy import deepcopy

from jsonschema import Draft202012Validator
import pytest

from src.content_factory import creative_opening_probe_contract_v1 as probe
from src.content_factory import creative_video_trial_contract_v1 as base
from tests.test_creative_video_trial_contract_v1 import actual_script, performance

REFS = ["B1.S01", "B1.S02"]


def wire(script):
    return {"script_sha256": base.digest(script), "source_refs": REFS,
        "current_direction": {"information_change": "当下公司决定被告知。", "observation": "保留双方上身与桌面。",
            "stimulus_reaction": "对方先接收通知，脸上的平静渐渐收紧。", "cut_reason": "当前通知完整说完后留在接收者身上。"},
        "performance": performance(script, REFS)}


def test_public_wire_native_identity_and_trial_review_flags_remain_separate():
    script = actual_script(); raw = wire(script); before = deepcopy(raw)
    schema = probe.opening_probe_schema(script, REFS)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(raw)
    compiled = probe.compile_opening_probe(raw, script, REFS)
    assert compiled["native"] == before == raw
    assert compiled["current_direction"] == raw["current_direction"]
    assert compiled["trial_route"] == "isolated_opening_probe" and compiled["user_trial_acceptance"]
    assert not compiled["whole_direction_accepted"] and not compiled["wholeperformance"]
    assert not compiled["machine_quality"] and not compiled["actual_media_quality_passed"]
    assert compiled["requires_independent_current_review"] and not compiled["independent_current_review_complete"]
    assert compiled["requires_independent_current_review_criteria_count"] == 6
    assert compiled["after_generation_content_status"] == "awaiting_human_review"


def test_video_prompt_has_exact_current_source_only_no_direction_narration():
    script = actual_script(); raw = wire(script)
    raw["current_direction"]["cut_reason"] = "独立导演证据专用句，不是旁白。"
    compiled = probe.compile_opening_probe(raw, script, REFS)
    prompt = probe.render_prompt(compiled, script, actor_names={"zhou": "周姐", "xiaolin": "小林"})
    assert prompt == base.render_opening_prompt(compiled["performance_compiled"], script, actor_names={"zhou": "周姐", "xiaolin": "小林"})
    assert raw["current_direction"]["cut_reason"] not in prompt
    sources = base.catalog(script)
    assert prompt.count(sources["B1.S02"]["text"]) == 1
    assert sources["B1.S03"]["text"] not in prompt
    assert compiled["performance_compiled"]["total_seconds"] == pytest.approx(40 / 3.3 + 0.5, abs=1e-6)
    assert not compiled["performance_compiled"]["resume_from_old_video"]


def test_direction_cannot_recopy_current_or_future_dialogue():
    script = actual_script(); raw = wire(script)
    for ref in ["B1.S02", "B1.S03"]:
        changed = deepcopy(raw)
        changed["current_direction"]["stimulus_reaction"] += base.catalog(script)[ref]["text"]
        with pytest.raises(ValueError, match="copied current or future"):
            probe.compile_opening_probe(changed, script, REFS)


def test_unknown_current_performance_overlong_timing_and_wrong_source_are_not_allowed():
    script = actual_script(); raw = wire(script)
    raw["performance"]["availability"] = "unknown"
    with pytest.raises(ValueError, match="availability unknown"):
        probe.compile_opening_probe(raw, script, REFS)
    raw = wire(script); raw["performance"]["action_timings"][0].update(overlap_with="", duration_seconds=4)
    with pytest.raises(ValueError, match="fifteen seconds"):
        probe.compile_opening_probe(raw, script, REFS)
    raw = wire(script); raw["script_sha256"] = "0" * 64
    with pytest.raises(ValueError): probe.compile_opening_probe(raw, script, REFS)


def test_scope_and_postcompilation_tampering_cannot_bypass_current_prefix():
    script = actual_script(); raw = wire(script)
    raw["source_refs"] = ["B1.S02"]
    with pytest.raises(ValueError): probe.compile_opening_probe(raw, script, REFS)
    with pytest.raises(ValueError, match="contiguous source prefix"):
        probe.opening_probe_schema(script, ["B1.S02"])
    compiled = probe.compile_opening_probe(wire(script), script, REFS)
    compiled["current_direction"]["information_change"] = "本地修改创作。"
    with pytest.raises(ValueError, match="compilation changed"):
        probe.render_prompt(compiled, script)
