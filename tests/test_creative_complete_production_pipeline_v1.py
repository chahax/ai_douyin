"""Offline whole-film planning, state carry and current-only request regression."""
from copy import deepcopy
import json

from jsonschema import Draft202012Validator
import pytest

from src.content_factory import creative_complete_production_pipeline_v1 as complete
from src.content_factory import creative_shared_production_contract_v1 as shared
from tests.test_creative_shared_production_contract_v1 import production_fixture


def complete_fixture():
    script, manifest, _ = production_fixture()
    frozen_context = next(row for row in manifest["provenance_catalog"] if row["source_id"] == "frozen_source_context")
    context = json.loads(frozen_context["text"])
    context["initial_state"] = {"scene_id": "meeting_room", "character_states": [
        {"id": aid, "location": "隔桌相对", "expected_state": "坐在桌边"} for aid in complete._actors(manifest)],
        "prop_states": [{"id": "paper", "expected_state": "桌面上的纸", "holder_character_id": None, "facing": "面朝上"}]}
    frozen_context["text"] = json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    frozen_context["sha256"] = shared.text_sha256(frozen_context["text"])
    manifest["source_context_sha256"] = complete.digest(context)
    manifest["scenes"][0]["setting"]["sources"] = [{"source_id": "frozen_source_context", "quote": frozen_context["text"]}]
    initial = complete.build_initial_state(context, manifest)
    creative = {"information_change": "接收本段新增要求", "observation": "说话人与听者的即时反应",
        "emotional_turn": "从等待转入交涉", "cut_reason": "让新回应获得接收空间", "target_seconds": 4,
        "reaction_reserve_seconds": .5}
    native_direction = {"availability": "known", "whole_observation": "同桌交涉的两人",
        "emotional_progression": "要求到回应", "visual_style": "写实职场",
        "segments": [{**creative, "end_source_ref": ref} for ref in ("B1.S02", "B1.S03")]}
    direction = complete.compile_direction(native_direction, script, manifest)
    end1 = deepcopy(initial)
    next(x for x in end1["actors"] if x["id"] == "xiaolin")["knowledge"] = "接收到查看桌上纸张的要求"
    native_first = {"availability": "known", "continuous_performance": "两人自然交谈，听者随话看向桌面，不重新起身。",
        "actor_goals": [
            {"actor_id": "zhou", "immediate_objective": "把注意力带到纸上", "source_reception": {
                "stimuli": [{"phase": "current", "source_ref": "B1.S01", "channel": "visible"}], "response": "从桌上现有纸张开始说明"}},
            {"actor_id": "xiaolin", "immediate_objective": "先听懂对方要求", "source_reception": {
                "stimuli": [{"phase": "current", "source_ref": "B1.S02", "channel": "spoken"}], "response": "听着看向桌面"}}],
        "dialogue_delivery": [{"source_ref": "B1.S02", "speech_tone": "普通交谈", "listener_behavior": "自然接收要求"}],
        "action_timings": [{"source_ref": "B1.S01", "duration_seconds": 1, "overlap_with": "B1.S02", "overlap_offset_seconds": 0}],
        "post_reaction_seconds": .5, "ending_state": end1,
        "state_changes": [{"path": "actors.xiaolin.knowledge", "source_ref": "B1.S02", "quote": "请看这张纸。"}]}
    first = complete.compile_performance(native_first, script, manifest, direction["segments"][0], initial, [])
    native_second = {"availability": "known", "continuous_performance": "小林接着答话，周姐自然听取，没有重新铺设纸张。",
        "actor_goals": [
            {"actor_id": "zhou", "immediate_objective": "听清对方回应", "source_reception": {
                "stimuli": [{"phase": "current", "source_ref": "B1.S03", "channel": "spoken"}], "response": "维持坐姿接收回应"}},
            {"actor_id": "xiaolin", "immediate_objective": "说明自己需要先看", "source_reception": {
                "stimuli": [{"phase": "completed", "source_ref": "B1.S02", "channel": "spoken"}], "response": "在收到的要求上提出查看"}}],
        "dialogue_delivery": [{"source_ref": "B1.S03", "speech_tone": "平常交谈", "listener_behavior": "听到回应后留在座位上"}],
        "action_timings": [], "post_reaction_seconds": .5, "ending_state": deepcopy(end1), "state_changes": []}
    second = complete.compile_performance(native_second, script, manifest, direction["segments"][1], end1, ["B1.S01", "B1.S02"])
    return script, manifest, initial, direction, [first, second]


def test_whole_direction_source_endpoints_and_metadata_are_program_owned():
    script, manifest, _, direction, _ = complete_fixture()
    Draft202012Validator.check_schema(complete.whole_direction_schema(script, manifest))
    assert "script_sha256" not in complete.whole_direction_schema(script, manifest)["properties"]
    assert [r for s in direction["segments"] for r in s["source_refs"]] == ["B1.S01", "B1.S02", "B1.S03"]
    for defect in ("duplicate", "missing_tail", "constant"):
        raw = deepcopy(direction["native"])
        if defect == "duplicate": raw["segments"][1]["end_source_ref"] = "B1.S02"
        elif defect == "missing_tail": raw["segments"].pop()
        else: raw["script_sha256"] = complete.digest(script)
        with pytest.raises(ValueError): complete.compile_direction(raw, script, manifest)


def test_planned_initial_state_preserves_explicit_legacy_description_and_unknowns():
    _, _, initial, _, _ = complete_fixture()
    assert all(x["posture"] == "坐在桌边" and x["gaze"] is None and x["emotion"] is None for x in initial["actors"])
    assert initial["props"][0]["anchor"] == "桌面上的纸"
    assert initial["props"][0]["holder"] is None
    assert "owner" not in initial["props"][0]


def test_first_film_state_cannot_silently_change_frozen_initial_source():
    script, manifest, initial, direction, rows = complete_fixture()
    changed = deepcopy(initial); changed["actors"][0]["emotion"] = "自己补写情绪"
    with pytest.raises(ValueError, match="frozen initial"):
        complete.compile_performance(rows[0]["native"], script, manifest, direction["segments"][0], changed, [])
    with pytest.raises(ValueError, match="frozen source"):
        complete.compile_complete(direction, rows, script, manifest, changed)


def test_generic_performance_first_and_later_ranges_have_normal_timing_and_exact_speech():
    script, manifest, initial, direction, performances = complete_fixture()
    for i, row in enumerate(performances):
        Draft202012Validator.check_schema(complete.performance_schema(script, manifest, direction["segments"][i], row["planned_initial_state"], row["completed_refs"]))
        assert row["normal_spoken_characters_per_second"] == 3.3
        assert row["service_tail_approval_verified"] is False
        prompt = complete.render_prompt(row, script, manifest)
        expected = "请看这张纸。" if i == 0 else "我先看一下。"
        absent = "我先看一下。" if i == 0 else "请看这张纸。"
        assert prompt.count(expected) == 1
        assert absent not in prompt
    result = complete.compile_complete(direction, performances, script, manifest, initial)
    assert result["whole_source_coverage_complete"] and result["whole_film_performance_complete"]
    assert result["planned_state_chain_complete"] and not result["actual_media_quality_passed"]
    assert not result["human_approved"] and not result["calls_authorized"]


@pytest.mark.parametrize("defect", ["missing_change", "wrong_quote", "future_evidence", "owner", "third_actor", "own_speech", "wrong_phase", "too_slow", "spatial"])
def test_source_state_cast_and_timing_failures_are_isolated_before_media(defect):
    script, manifest, initial, direction, performances = complete_fixture()
    raw = deepcopy(performances[0]["native"])
    if defect == "missing_change": raw["state_changes"] = []
    elif defect == "wrong_quote": raw["state_changes"][0]["quote"] = "不在来源中的证据"
    elif defect == "future_evidence": raw["state_changes"][0]["source_ref"] = "B1.S03"
    elif defect == "owner": raw["ending_state"]["props"][0]["owner"] = "xiaolin"
    elif defect == "third_actor": raw["ending_state"]["actors"][0]["id"] = "visitor"
    elif defect == "own_speech": raw["actor_goals"][0]["source_reception"]["stimuli"] = [{"phase": "current", "source_ref": "B1.S02", "channel": "spoken"}]
    elif defect == "wrong_phase": raw["actor_goals"][1]["source_reception"]["stimuli"][0]["phase"] = "completed"
    elif defect == "too_slow": raw["action_timings"][0]["duration_seconds"] = 15
    else: raw["continuous_performance"] = "小林站到画面右侧，改成特写。"
    before = deepcopy(raw)
    with pytest.raises(ValueError): complete.compile_performance(raw, script, manifest, direction["segments"][0], initial, [])
    assert raw == before


def test_complete_handoff_rejects_missing_segment_state_jump_and_fixed_manifest_drift():
    script, manifest, initial, direction, rows = complete_fixture()
    for defect in ("missing", "state_jump", "fixed_manifest", "speech_patch"):
        changed = deepcopy(rows)
        if defect == "missing": changed.pop()
        elif defect == "state_jump": changed[1]["planned_initial_state"]["actors"][0]["location"] = "门外"
        elif defect == "fixed_manifest": changed[1]["global_manifest_sha256"] = "f" * 64
        else: changed[1]["schedule"][0]["original_text"] = "手动缩句"
        with pytest.raises(ValueError): complete.compile_complete(direction, changed, script, manifest, initial)


def test_actual_shared_context_is_projected_once_and_current_dialogue_still_isolated():
    script, manifest, _, _, performances = complete_fixture()
    _, _, dynamic = production_fixture()
    dynamic["global_manifest_sha256"] = shared.digest(manifest)
    ctx = shared.compile_segment_context(manifest, script, dynamic, performances[0]["source_refs"])
    prompt = complete.render_prompt(performances[0], script, manifest, ctx)
    assert prompt.count(ctx["prompt_fragment"]) == 1
    assert prompt.count("请看这张纸。") == 1
    assert "我先看一下。" not in prompt
    changed = deepcopy(ctx); changed["global_manifest_sha256"] = "f" * 64
    with pytest.raises(ValueError): complete.render_prompt(performances[0], script, manifest, changed)
