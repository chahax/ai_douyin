"""Offline source/timing checks; no model, media or tail extraction."""
from copy import deepcopy
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from src.content_factory import creative_continuation_probe_contract_v1 as probe
from src.content_factory import creative_video_trial_contract_v1 as base

COMPLETED = ["B1.S01", "B1.S02"]
REFS = ["B1.S03", "B1.S04"]


def actual_script():
    path = Path(__file__).resolve().parents[1] / "data/production_trials/autonomous_text_pipeline_20261011/legal_resignation_15/versions/07/FULL_SCRIPT.json"
    return json.loads(path.read_text(encoding="utf-8"))


def wire(script, completed=None, refs=None):
    completed = COMPLETED if completed is None else completed
    refs = REFS if refs is None else refs
    current = probe.continuation_source(script, completed, refs)
    sources = current["current_sources"]
    dialogues = [ref for ref, row in sources.items() if row["kind"] == "dialogue"]
    return {"script_sha256": base.digest(script), "source_refs": deepcopy(refs),
        "current_direction": {"information_change": "递给对方的申请被注意到。", "observation": "看接收者的目光怎样落到纸面。",
            "stimulus_reaction": "说明者继续当前劝说，接收者低头接收新的纸面信息。", "cut_reason": "当前信息被看清后结束。"},
        "performance": {"script_sha256": base.digest(script), "source_refs": deepcopy(refs), "availability": "known",
            "continuous_performance": "承接尾帧两人的座位和道具状态，说明者继续当前话，接收者在交谈中自然看向桌面。",
            "actor_goals": [{"actor_id": actor, "immediate_objective": "表达自己的当前立场。",
                "reception_of_current_stimulus": "接收对方当下的声音与视线变化。"} for actor in current["actor_ids"]],
            "camera": "延续尾帧空间，稳定双人中景，保持纸面与双方上身可见。",
            "spoken_language": "zh-CN", "delivery": "自然普通话，正常交谈速度，动作表情与谈话同步。",
            "action_timings": [{"source_ref": ref, "duration_seconds": 2.5,
                "overlap_with": next((target for target in dialogues if abs(refs.index(ref) - refs.index(target)) == 1), ""),
                "overlap_offset_seconds": 0} for ref, row in sources.items() if row["kind"] == "action"],
            "post_reaction_seconds": 0.5, "ending_state": "停留在原座位，道具保持本段完成后的状态。"}}


def test_actual_487_adjacent_scope_native_preserved_and_normal_overlap():
    script = actual_script(); before = deepcopy(script); raw = wire(script); original = deepcopy(raw)
    assert base.digest(script) == "cbb125ea23dbefca1c314d53bc26ce7c231d1b3ab39b256b1b20d8dcde520d0d"
    schema = probe.continuation_probe_schema(script, COMPLETED, REFS)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(raw)
    compiled = probe.compile_continuation_probe(raw, script, COMPLETED, REFS)
    perf = compiled["performance_compiled"]
    assert compiled["native"] == original == raw and script == before
    assert compiled["native_sha256"] == base.digest(raw)
    assert perf["normal_spoken_characters_per_second"] == 3.3
    assert perf["total_seconds"] == pytest.approx(base.spoken_seconds(base.catalog(script)[REFS[0]]) + 0.5, abs=1e-6)
    assert [row["source_ref"] for row in perf["schedule"]] == REFS
    assert perf["schedule"][0]["start_seconds"] == perf["schedule"][1]["start_seconds"] == 0
    assert perf["duration_seconds"] == 6 and perf["timing_is_estimate"]
    assert not perf["measured_audio"] and not perf["fit_scaled"]


def test_actual_prompt_current_sources_once_tail_mode_and_no_prior_or_future():
    script = actual_script(); raw = wire(script)
    raw["current_direction"]["cut_reason"] = "独立审查专用元文句，不可成为旁白。"
    compiled = probe.compile_continuation_probe(raw, script, COMPLETED, REFS)
    prompt = probe.render_prompt(compiled, script, {"zhou": "周姐", "xiaolin": "小林"})
    catalog = base.catalog(script)
    assert "first_frame" in prompt and "不重演前段动作" in prompt and "不重新造人或工牌" in prompt
    assert "reference_image" not in prompt
    assert raw["current_direction"]["cut_reason"] not in prompt
    assert prompt.count(catalog["B1.S03"]["text"]) == prompt.count(catalog["B1.S04"]["text"]) == 1
    assert catalog["B1.S01"]["text"] not in prompt
    assert all(row["text"] not in prompt for ref, row in catalog.items() if ref not in REFS and row["kind"] == "dialogue")
    projection = probe.continuation_source(script, COMPLETED, REFS)
    assert list(projection["current_sources"]) == REFS
    assert catalog["B1.S02"]["text"] not in json.dumps(projection, ensure_ascii=False)


def test_trial_not_whole_acceptance_and_tail_approval_not_fabricated():
    compiled = probe.compile_continuation_probe(wire(actual_script()), actual_script(), COMPLETED, REFS)
    assert compiled["requires_approved_service_tail_before_media"] and not compiled["service_tail_approval_verified"]
    assert compiled["requires_independent_current_review"] and not compiled["independent_current_review_complete"]
    assert compiled["requires_independent_current_review_criteria_count"] == 6
    assert not compiled["whole_direction_accepted"] and not compiled["whole_film_complete"]
    assert not compiled["machine_script_quality"] and not compiled["actual_media_quality_passed"]
    assert compiled["after_generation_content_status"] == "awaiting_human_review"
    forged = deepcopy(compiled); forged["service_tail_approval_verified"] = True
    with pytest.raises(ValueError, match="compilation changed"):
        probe.render_prompt(forged, actual_script())


def test_completed_prefix_and_next_scope_cannot_skip_replay_reorder_or_be_empty():
    script = actual_script()
    cases = [([], REFS), (["B1.S02"], REFS), (list(reversed(COMPLETED)), REFS),
        (COMPLETED, []), (COMPLETED, ["B1.S02"]), (COMPLETED, ["B1.S04"]),
        (COMPLETED, list(reversed(REFS))), (COMPLETED, ["B1.S03", "B2.S01"])]
    for completed, refs in cases:
        with pytest.raises(ValueError): probe.continuation_probe_schema(script, completed, refs)
    # Frozen opening logic still rejects this next range; it is not weakened.
    with pytest.raises(ValueError, match="source prefix"):
        base.opening_performance_schema(script, REFS)


def test_public_wire_rejects_previous_future_and_nonadjacent_overlap():
    script = actual_script(); raw = wire(script)
    schema = probe.continuation_probe_schema(script, COMPLETED, REFS)
    for target in ["B1.S02", "B2.S01"]:
        changed = deepcopy(raw); changed["performance"]["action_timings"][0]["overlap_with"] = target
        assert list(Draft202012Validator(schema).iter_errors(changed))
        with pytest.raises(ValueError): probe.compile_continuation_probe(changed, script, COMPLETED, REFS)
    changed = deepcopy(raw); changed["performance"]["action_timings"][0].update(overlap_with="", overlap_offset_seconds=1)
    assert list(Draft202012Validator(schema).iter_errors(changed))


def test_unknown_nonfinite_and_overlong_full_sentence_stop_without_speed_scaling():
    script = actual_script(); raw = wire(script)
    raw["performance"]["availability"] = "unknown"
    with pytest.raises(ValueError, match="availability unknown"):
        probe.compile_continuation_probe(raw, script, COMPLETED, REFS)
    raw = wire(script); raw["performance"]["action_timings"][0]["duration_seconds"] = float("nan")
    with pytest.raises(ValueError, match="finite seconds"):
        probe.compile_continuation_probe(raw, script, COMPLETED, REFS)
    longer = REFS + ["B2.S01"]
    raw = wire(script, refs=longer); raw["performance"]["post_reaction_seconds"] = 3
    before = deepcopy(raw)
    with pytest.raises(ValueError, match="fifteen seconds"):
        probe.compile_continuation_probe(raw, script, COMPLETED, longer)
    assert raw == before


def test_instructions_cannot_copy_previous_current_or_future_full_dialogue():
    script = actual_script(); catalog = base.catalog(script)
    for ref in ["B1.S02", "B1.S03", "B2.S01"]:
        for field in ["direction", "performance"]:
            changed = wire(script)
            if field == "direction": changed["current_direction"]["observation"] += catalog[ref]["text"]
            else: changed["performance"]["continuous_performance"] += catalog[ref]["text"]
            with pytest.raises(ValueError, match="copied current or future"):
                probe.compile_continuation_probe(changed, script, COMPLETED, REFS)


def test_source_digest_source_slots_and_compiled_timing_cannot_be_changed():
    script = actual_script()
    for field in ["outer_digest", "performance_digest", "scope"]:
        raw = wire(script)
        if field == "outer_digest": raw["script_sha256"] = "0" * 64
        elif field == "performance_digest": raw["performance"]["script_sha256"] = "0" * 64
        else: raw["performance"]["source_refs"] = ["B1.S04"]
        with pytest.raises(ValueError): probe.compile_continuation_probe(raw, script, COMPLETED, REFS)
    compiled = probe.compile_continuation_probe(wire(script), script, COMPLETED, REFS)
    compiled["performance_compiled"]["schedule"][0]["original_text"] = "本地改词"
    with pytest.raises(ValueError, match="compilation changed"): probe.render_prompt(compiled, script)
    changed_script = deepcopy(script); changed_script["beats"][0]["steps"][2]["text"] += "本地修改"
    with pytest.raises(ValueError, match="different selected source"): probe.render_prompt(compiled, changed_script)


def test_other_candidate_dialogue_only_and_action_only_scopes_are_reusable():
    script = {"beats": [{"steps": [{"kind": "action", "speaker": "", "text": "母亲放下碗。"},
        {"kind": "dialogue", "speaker": "mother", "text": "快吃吧。"},
        {"kind": "action", "speaker": "", "text": "女儿抬头。"}]}]}
    for completed, refs in [(["B1.S01"], ["B1.S02"]), (["B1.S01", "B1.S02"], ["B1.S03"])]:
        raw = wire(script, completed, refs)
        schema = probe.continuation_probe_schema(script, completed, refs)
        Draft202012Validator.check_schema(schema)
        compiled = probe.compile_continuation_probe(raw, script, completed, refs)
        assert compiled["performance_compiled"]["duration_seconds"] == 4
        prompt = probe.render_prompt(compiled, script, {"mother": "母亲"})
        for ref in refs: assert prompt.count(base.catalog(script)[ref]["text"]) == 1
    all_actions = {"beats": [{"steps": [{"kind": "action", "speaker": "", "text": "产品转向光源。"},
        {"kind": "action", "speaker": "", "text": "机身停止转动。"}]}]}
    schema = probe.continuation_probe_schema(all_actions, ["B1.S01"], ["B1.S02"])
    Draft202012Validator.check_schema(schema)
    compiled = probe.compile_continuation_probe(wire(all_actions, ["B1.S01"], ["B1.S02"]), all_actions, ["B1.S01"], ["B1.S02"])
    assert compiled["performance_compiled"]["native"]["actor_goals"] == []
