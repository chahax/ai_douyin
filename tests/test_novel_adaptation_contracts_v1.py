"""Offline contract evidence; fixtures are invented, never production sources."""
from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from src.content_factory.novel_adaptation_contracts_v1 import (
    PROMPTS, REVIEW_DIMENSIONS, REVIEW_SCHEMA, SCHEMAS, STAGES,
    render_screenplay, resolve_selection_range, resolve_source_ref,
    validate_review, validate_stage,
)


def example_context():
    """Public tiny full-route fixture for independent runtime fake clients."""
    text = "小林站在门口。母亲把信递给小林，说父亲留下了地址。小林接信后决定出发。"
    ref = {"quote": "小林站在门口。"}
    later = {"quote": "母亲把信递给小林，说父亲留下了地址。"}
    ending = {"quote": "小林接信后决定出发。"}
    world = {"era": "原文未交代", "daily_context": "家庭日常", "space_and_prior_events": "门口，母亲带来父亲的信", "unknowns": ["确切年代"]}
    characters = [
        {"id": "C1", "name": "小林", "identity": "孩子", "personality": "果断", "situation": "在门口接信", "goal": "找到父亲", "relationships": "C2的孩子", "source_refs": [ref, ending]},
        {"id": "C2", "name": "母亲", "identity": "母亲", "personality": "克制", "situation": "递信", "goal": "告知地址", "relationships": "C1的母亲", "source_refs": [later]},
    ]
    analysis = {"world": world, "characters": characters,
                "storyline": [{"id": "L1", "cause": "父亲留下地址", "event": "母亲递信", "consequence": "小林决定出发", "source_refs": [later, ending]}],
                "highlights": [{"id": "H1", "kind": "emotional_peak", "description": "接到父亲的线索", "reason": "从等待转为行动", "storyline_ids": ["L1"], "character_ids": ["C1", "C2"], "source_refs": [later, ending]}]}
    plan = {"title": "门口的信", "selected_character_ids": ["C1", "C2"], "selected_highlight_ids": ["H1"],
            "source_ref": {"start_quote": ref["quote"], "end_quote": ending["quote"]},
            "start_state": "小林等在门口", "end_state": "小林准备出发",
            "causal_beats": [{"id": f"B{i}", "phase": phase, "description": description, "character_ids": ["C1", "C2"], "source_refs": [anchor]}
                             for i, (phase, description, anchor) in enumerate([
                                 ("setup", "小林在门口", ref), ("stimulus", "母亲递信", later),
                                 ("reaction", "小林接信", ending), ("escalation", "决定寻找父亲", ending),
                                 ("cliffhanger", "即将出发", ending)], 1)],
            "preserved_facts": [{"id": "F1", "description": "父亲留下地址", "source_refs": [later]}],
            "changes": [{"description": "间接引述转成直接对白", "reason": "使母亲自然告知线索", "mainline_impact": "保留递信后出发的主线"}],
            "target_duration_seconds": 12}
    states = [{"character_id": "C1", "action": "伸手接信", "expression": "惊讶", "gaze": "信封"},
              {"character_id": "C2", "action": "松开信封", "expression": "克制", "gaze": "小林的脸"}]
    screenplay = {"title": "门口的信", "world": deepcopy(world), "characters": deepcopy(characters), "duration_seconds": 12,
                  "scenes": [{"id": "S1", "timeline": "递信当时", "time": "白天", "location": "门口", "present_character_ids": ["C1", "C2"],
                              "start_state": "小林站在门口，母亲靠近", "end_state": "小林攥着信准备离开",
                              "events": [
                                  {"id": "E1", "kind": "action", "actor_id": "C2", "text": "母亲递出信。", "duration_seconds": 2, "character_states": deepcopy(states), "stimulus_event_id": "", "emotional_focus": False},
                                  {"id": "E2", "kind": "dialogue", "actor_id": "C2", "text": "这是你爸留下的地址。", "duration_seconds": 4, "character_states": deepcopy(states), "stimulus_event_id": "", "emotional_focus": True},
                                  {"id": "E3", "kind": "reaction", "actor_id": "C1", "text": "小林低头读信，抬眼看母亲。", "duration_seconds": 2, "character_states": deepcopy(states), "stimulus_event_id": "E2", "emotional_focus": False},
                                  {"id": "E4", "kind": "dialogue", "actor_id": "C1", "text": "我现在就去找他。", "duration_seconds": 4, "character_states": deepcopy(states), "stimulus_event_id": "", "emotional_focus": False},
                              ]}],
                  "ending": {"type": "cliffhanger", "description": "小林将踏上寻找父亲的路"}, "adaptation_notes": ["对白为自然改写，保留父亲留地址和小林出发的因果。"]}
    return {"source": {"binding_id": "test-source", "book_id": "test-book", "title": "测试小说", "text": text,
                       "scope": "独立测试片段", "full_source_sha256": "program-full", "excerpt_sha256": "program-excerpt", "start_character": 0, "end_character": len(text)},
            "analysis": analysis, "adaptation_plan": plan, "screenplay": screenplay}


def example_review():
    return {"whole_text_reviewed": True, "summary": "离线假审查，不证明创作品质", "dimensions": [
        {"dimension": dimension, "assessment": "该维度已检查，未发现必须返修问题。"} for dimension in REVIEW_DIMENSIONS], "issues": []}


@pytest.mark.parametrize("stage", STAGES)
def test_valid_stages(stage):
    context = example_context()
    assert validate_stage(stage, context[stage], context) == []


def test_schemas_are_valid_and_do_not_require_model_identity():
    for schema in (*SCHEMAS.values(), REVIEW_SCHEMA):
        Draft202012Validator.check_schema(schema)
    for schema in SCHEMAS.values():
        assert not {"source_sha256", "candidate_id", "screenplay_markdown"} & set(schema["properties"])


def test_rewritten_dialogue_is_allowed():
    context = example_context()
    dialogue = context["screenplay"]["scenes"][0]["events"][1]["text"]
    assert dialogue not in context["source"]["text"]
    assert validate_stage("screenplay", context["screenplay"], context) == []
    assert "允许重写对白" in PROMPTS["screenplay"]


def test_source_anchor_resolver_never_guesses_duplicate():
    assert resolve_source_ref("甲乙甲", {"quote": "甲", "occurrence": 1}) == (2, 3)
    with pytest.raises(ValueError, match="SOURCE_AMBIGUOUS"):
        resolve_source_ref("甲乙甲", {"quote": "甲"})
    with pytest.raises(ValueError, match="SOURCE_OCCURRENCE"):
        resolve_source_ref("甲乙甲", {"quote": "甲", "occurrence": 2})
    with pytest.raises(ValueError, match="SOURCE_QUOTE"):
        resolve_source_ref("甲乙甲", {"quote": "原文没有"})


def test_source_selection_program_locates_half_open_range():
    assert resolve_selection_range("前文。开头。正文。结尾。后文。", {"start_quote": "开头。", "end_quote": "结尾。"}) == (3, 12)
    with pytest.raises(ValueError, match="SOURCE_RANGE"):
        resolve_selection_range("开头。结尾。", {"start_quote": "结尾。", "end_quote": "开头。"})


def test_duplicate_and_nonexistent_source_references_aggregate():
    context = example_context()
    value = deepcopy(context["analysis"])
    value["characters"].append(deepcopy(value["characters"][0]))
    value["storyline"][0]["source_refs"] = [{"quote": "假的原文引证"}]
    value["highlights"][0]["character_ids"] = ["missing", "missing"]
    codes = {issue["code"] for issue in validate_stage("analysis", value, context)}
    assert {"DUPLICATE_ID", "SOURCE_QUOTE", "UNKNOWN_REFERENCE", "DUPLICATE_REFERENCE"} <= codes


def test_plan_missing_causal_phases_and_selected_ids_aggregate():
    context = example_context()
    value = deepcopy(context["adaptation_plan"])
    value["causal_beats"] = value["causal_beats"][:1]
    value["selected_character_ids"] = ["missing"]
    value["selected_highlight_ids"] = ["missing"]
    issues = validate_stage("adaptation_plan", value, context)
    assert {"SCHEMA", "UNKNOWN_REFERENCE", "MISSING_CAUSAL_PHASE", "MISSING_ENDING"} <= {i["code"] for i in issues}
    assert all(issue["responsible_stage"] == "adaptation_plan" for issue in issues)


def test_plan_evidence_must_lie_inside_selected_range():
    context = example_context()
    value = deepcopy(context["adaptation_plan"])
    value["source_ref"] = {"start_quote": "小林接信后决定出发。", "end_quote": "小林接信后决定出发。"}
    assert "OUTSIDE_SELECTED_RANGE" in {i["code"] for i in validate_stage("adaptation_plan", value, context)}


def test_screenplay_all_structural_timing_faults_are_aggregated():
    context = example_context()
    value = deepcopy(context["screenplay"])
    scene = value["scenes"][0]
    scene["events"][1]["duration_seconds"] = 0.1
    scene["events"][1]["actor_id"] = "unknown"
    scene["events"][1]["character_states"].pop()
    scene["events"][2]["stimulus_event_id"] = "future"
    scene["events"][3]["id"] = "E1"
    value["duration_seconds"] = 999
    issues = validate_stage("screenplay", value, context)
    codes = {issue["code"] for issue in issues}
    assert {"ACTOR_NOT_PRESENT", "PRESENT_STATE_COVERAGE", "SPEECH_TIME_LOWER_BOUND", "EMOTION_WINDOW", "STIMULUS_ORDER", "DUPLICATE_EVENT_ID", "DURATION_SUM", "MISSING_VISIBLE_REACTION"} <= codes


def test_mixed_language_speech_time_is_added_not_maximum():
    context = example_context()
    value = deepcopy(context["screenplay"])
    event = value["scenes"][0]["events"][1]
    event["text"] = "一二三四五六 one two three"
    event["duration_seconds"] = 1
    assert "SPEECH_TIME_LOWER_BOUND" in {i["code"] for i in validate_stage("screenplay", value, context)}


@pytest.mark.parametrize("fault", [[], {}, None, 3])
def test_wrong_types_cannot_crash_aggregate_validator(fault):
    context = example_context()
    value = deepcopy(context["screenplay"])
    value["characters"][0]["id"] = fault
    value["scenes"][0]["events"][0]["actor_id"] = fault
    value["scenes"][0]["events"][1]["stimulus_event_id"] = fault
    value["duration_seconds"] = 500
    context["analysis"]["characters"][0]["id"] = fault
    issues = validate_stage("screenplay", value, context)
    assert "SCHEMA" in {i["code"] for i in issues}
    assert "DURATION_SUM" in {i["code"] for i in issues}


@pytest.mark.parametrize("duration", [float("nan"), float("inf"), -1, True])
def test_illegal_numbers_cannot_be_accepted(duration):
    context = example_context()
    value = deepcopy(context["screenplay"])
    value["duration_seconds"] = duration
    assert validate_stage("screenplay", value, context)


def test_review_requires_true_whole_text_all_dimensions_and_responsible_stage():
    context = example_context()
    assert validate_review(example_review(), context) == []
    review = example_review()
    review["whole_text_reviewed"] = False
    review["dimensions"] = review["dimensions"][:1]
    review["issues"] = [{"severity": "major", "location": "S1 E2", "evidence": "原文没有此动机", "impact": "主线偏移", "proposal": "重新分析动机"}]
    codes = {issue["code"] for issue in validate_review(review, context)}
    assert {"SCHEMA", "REVIEW_COVERAGE"} <= codes


def test_review_major_mainline_issue_is_preserved_for_runtime_repair():
    context = example_context()
    review = example_review()
    issue = {"severity": "major", "location": "analysis.characters.C1.goal", "evidence": "找到父亲", "impact": "审查模型认为动机依据不足", "proposal": "重新核对源动机", "responsible_stage": "analysis"}
    review["issues"] = [issue]
    assert validate_review(review, context) == []
    assert review["issues"][0] == issue  # validity does not erase a semantic failure


@pytest.mark.parametrize("context", [None, [], {"source": []}, {"source": {"text": ""}}])
def test_broken_context_returns_diagnostics(context):
    assert validate_review(example_review(), context)
    assert validate_stage("analysis", example_context()["analysis"], context)


def test_causal_plan_ending_must_be_last():
    context = example_context()
    value = deepcopy(context["adaptation_plan"])
    value["causal_beats"][3], value["causal_beats"][4] = value["causal_beats"][4], value["causal_beats"][3]
    assert "CAUSAL_ENDING_ORDER" in {i["code"] for i in validate_stage("adaptation_plan", value, context)}


def test_hiding_all_emotional_focus_is_not_structural_completion():
    context = example_context()
    value = deepcopy(context["screenplay"])
    for event in value["scenes"][0]["events"]:
        event["emotional_focus"] = False
    assert "MISSING_EMOTIONAL_FOCUS" in {i["code"] for i in validate_stage("screenplay", value, context)}


def test_reading_projection_complete_deterministic_and_never_mutates_native():
    value = example_context()["screenplay"]
    original = deepcopy(value)
    reading = render_screenplay(value)
    assert reading == render_screenplay(value)
    assert value == original
    for scene in value["scenes"]:
        for event in scene["events"]:
            assert event["text"] in reading
            for state in event["character_states"]:
                assert all(state[key] in reading for key in ("action", "expression", "gaze"))
        assert scene["end_state"] in reading
    assert value["ending"]["description"] in reading
    assert all(note in reading for note in value["adaptation_notes"])


@pytest.mark.parametrize("stage", STAGES)
def test_non_object_drafts_fail_without_crashing(stage):
    assert validate_stage(stage, [], example_context())


def test_unknown_stage_is_programming_error():
    with pytest.raises(ValueError, match="unknown adaptation stage"):
        validate_stage("video", {}, {})


@pytest.mark.parametrize("stage", ["analysis", "screenplay"])
def test_narrator_is_reserved_and_cannot_mislabel_an_ordinary_character(stage):
    context = example_context()
    value = deepcopy(context[stage])
    value["characters"][0]["id"] = "narrator"
    if stage == "screenplay":
        context["adaptation_plan"]["selected_character_ids"] = ["narrator", "C2"]
        scene = value["scenes"][0]
        scene["present_character_ids"] = ["narrator", "C2"]
        for event in scene["events"]:
            if event["actor_id"] == "C1":
                event["actor_id"] = "narrator"
            for state in event["character_states"]:
                if state["character_id"] == "C1":
                    state["character_id"] = "narrator"
    assert "RESERVED_CHARACTER_ID" in {i["code"] for i in validate_stage(stage, value, context)}
    assert "角色ID不得使用保留值narrator" in PROMPTS[stage]
