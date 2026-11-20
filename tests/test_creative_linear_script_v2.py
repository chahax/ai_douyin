from copy import deepcopy
import json

import pytest
from jsonschema import Draft202012Validator

from scripts.creative_linear_script_v2 import (
    EMPTY_ACTION, accept_linear_script, build_linear_script_schema,
    build_linear_script_messages,
)
from src.content_factory.creative_workflow_contract import CreativeContractError


def previous():
    return {"title": "旧稿", "selected_candidate_id": "C01", "beats": [
        {"id": "OLD1", "dialogue": [{"speaker": "方澄", "text": "旧句一"}]},
        {"id": "OLD2", "dialogue": [{"speaker": "林屿", "text": "旧句二"}]},
    ]}


def action(text):
    return {"kind": "action", "speaker": "", "text": text}


def dialogue(speaker, text):
    return {"kind": "dialogue", "speaker": speaker, "text": text}


def raw():
    return {"title": "完整新稿", "premise": "动作引发对白，对白引发反应。",
            "selected_candidate_id": "C01", "beats": [
        {"id": "NEW1", "duration_seconds": 12, "event": "拒绝与反应",
         "trigger": "明确自己的选择", "steps": [
             action("方澄先抬头看向林屿。"),
             dialogue("方澄", "这次我先走，你自己对吧。"),
             action("林屿握笔的手停住。"),
         ]},
        {"id": "NEW2", "duration_seconds": 7.5, "event": "独自开始核对",
         "trigger": "回应此前的选择", "steps": [
             action("林屿取出结算单。"), action("林屿落笔开始核对。")]}]}


def context():
    return {"script": previous(), "static_visual_manifest": {
        "characters": [{"id": "C01", "name": "方澄"}, {"id": "C02", "name": "林屿"}]},
        "reference_pack": [{"id": "R01", "text": "参考全文：刺激后保留可读反应。"}]}


def playback(derived_beat):
    actions = []
    for slot, speech_index in (("before", 0), ("during", 1), ("after", None)):
        if derived_beat[slot] != EMPTY_ACTION:
            actions.extend(("action", "", line) for line in derived_beat[slot].split("\n"))
        if speech_index is not None and speech_index < len(derived_beat["dialogue"]):
            row = derived_beat["dialogue"][speech_index]
            actions.append(("dialogue", row["speaker"], row["text"]))
    return actions


def test_complete_new_draft_replaces_whole_script_and_preserves_raw():
    old, generated = previous(), raw()
    before = deepcopy((old, generated))
    accepted = accept_linear_script(old, generated)
    assert [beat["id"] for beat in accepted["beats"]] == ["NEW1", "NEW2"]
    assert not any(beat["id"].startswith("OLD") for beat in accepted["beats"])
    assert accepted["selected_candidate_id"] == old["selected_candidate_id"]
    assert (old, generated) == before


def test_one_dialogue_actions_after_speech_are_after_not_ambiguous_during():
    accepted = accept_linear_script(previous(), raw())
    beat = accepted["beats"][0]
    assert beat["before"] == "方澄先抬头看向林屿。"
    assert beat["during"] == EMPTY_ACTION
    assert beat["after"] == "林屿握笔的手停住。"
    assert playback(beat) == [(step["kind"], step["speaker"], step["text"])
                              for step in raw()["beats"][0]["steps"]]


def test_two_dialogues_preserve_every_step_and_literal_line():
    generated = raw()
    generated["beats"][0]["steps"] = [
        action("方澄握住包带。"), dialogue("方澄", "这次我先走。"),
        action("林屿看向方澄。"), action("林屿停一下。"),
        dialogue("林屿", "我以为你会帮我的。"), action("方澄转向门口。")]
    accepted = accept_linear_script(previous(), generated)
    beat = accepted["beats"][0]
    assert beat["during"] == "林屿看向方澄。\n林屿停一下。"
    assert playback(beat) == [(step["kind"], step["speaker"], step["text"])
                              for step in generated["beats"][0]["steps"]]
    assert accepted["screenplay_markdown"].count("我以为你会帮我的。") == 1


def test_no_dialogue_and_empty_slots_add_no_action_or_speech():
    generated = raw()
    accepted = accept_linear_script(previous(), generated)
    beat = accepted["beats"][1]
    assert beat["before"] == "林屿取出结算单。\n林屿落笔开始核对。"
    assert beat["during"] == beat["after"] == EMPTY_ACTION
    assert beat["dialogue"] == []
    assert EMPTY_ACTION not in accepted["screenplay_markdown"]
    assert playback(beat) == [(step["kind"], step["speaker"], step["text"])
                              for step in generated["beats"][1]["steps"]]


def test_dialogue_only_beat_uses_display_placeholders_without_invented_actions():
    generated = raw()
    generated["beats"][0]["steps"] = [dialogue("方澄", "这次我先走。")]
    beat = accept_linear_script(previous(), generated)["beats"][0]
    assert beat["before"] == beat["during"] == beat["after"] == EMPTY_ACTION
    assert playback(beat) == [("dialogue", "方澄", "这次我先走。")]


def test_total_duration_is_derived_once_from_model_beat_seconds():
    generated = raw()
    accepted = accept_linear_script(previous(), generated)
    assert "duration_seconds" not in generated
    assert accepted["duration_seconds"] == 19.5
    assert accepted["duration_seconds"] == sum(beat["duration_seconds"] for beat in generated["beats"])


@pytest.mark.parametrize("change,code", [
    (lambda value: value.update(selected_candidate_id="OTHER"), "LINEAR_IDENTITY_CHANGED"),
    (lambda value: value.update(duration_seconds=68), "LINEAR_SCHEMA_INVALID"),
    (lambda value: value.update(replace_beats=[]), "LINEAR_SCHEMA_INVALID"),
    (lambda value: value["beats"][0].update(steps={"item": []}), "LINEAR_SCHEMA_INVALID"),
    (lambda value: value["beats"][0]["steps"][0].update(speaker="方澄"), "LINEAR_ACTION_SPEAKER_INVALID"),
    (lambda value: value["beats"][0]["steps"][1].update(speaker=""), "LINEAR_SPEAKER_INVALID"),
    (lambda value: value["beats"][0]["steps"][1].update(speaker="不存在的人物"), "LINEAR_SCHEMA_INVALID"),
    (lambda value: value["beats"][1].update(id="NEW1"), "LINEAR_BEAT_ID_INVALID"),
    (lambda value: value["beats"][0].update(duration_seconds=True), "LINEAR_SCHEMA_INVALID"),
    (lambda value: value["beats"][0].update(duration_seconds=float("nan")), "LINEAR_DURATION_INVALID"),
])
def test_invalid_whole_submission_is_rejected_without_editing_raw(change, code):
    generated = raw()
    change(generated)
    snapshot = json.dumps(generated, ensure_ascii=False, sort_keys=True)
    with pytest.raises(CreativeContractError, match=code):
        accept_linear_script(previous(), generated)
    assert json.dumps(generated, ensure_ascii=False, sort_keys=True) == snapshot


def test_more_than_two_dialogues_requires_complete_new_submission():
    generated = raw()
    generated["beats"][0]["steps"] = [
        dialogue("方澄", "一"), dialogue("林屿", "二"), dialogue("方澄", "三")]
    with pytest.raises(CreativeContractError, match="LINEAR_TOO_MANY_DIALOGUES"):
        accept_linear_script(previous(), generated)


def test_plain_schema_and_messages_preserve_full_bound_sources():
    original_context, old, issues = context(), previous(), [{"id": "timing", "evidence": "完整证据"}]
    before = deepcopy((original_context, old, issues))
    schema = build_linear_script_schema(original_context)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(raw())
    assert set(schema["properties"]) == {"title", "premise", "selected_candidate_id", "beats"}
    beat = schema["properties"]["beats"]["items"]["properties"]
    assert set(beat) == {"id", "duration_seconds", "event", "trigger", "steps"}
    assert beat["steps"]["type"] == "array"
    assert beat["steps"]["items"]["properties"]["speaker"]["enum"] == ["", "方澄", "林屿"]
    messages = build_linear_script_messages(original_context, old, issues)
    payload = json.loads(messages[1]["content"])
    assert payload["context"] == original_context
    assert payload["context"]["reference_pack"] == original_context["reference_pack"]
    assert payload["previous_script"] == old and payload["issues"] == issues
    assert payload["revision_mode"] == "complete_new_script"
    assert (original_context, old, issues) == before


def test_previously_silent_bound_character_can_be_explicitly_validated():
    generated = raw()
    generated["beats"][0]["steps"][1]["speaker"] = "第三人"
    accepted = accept_linear_script(previous(), generated,
                                    character_names=["方澄", "林屿", "第三人"])
    assert accepted["beats"][0]["dialogue"][0]["speaker"] == "第三人"

def test_messages_define_narrative_beats_without_forcing_shots_or_single_actions():
    messages = build_linear_script_messages(context(), previous(), [])
    serialized = json.dumps(messages, ensure_ascii=False)
    assert "一拍一镜" not in serialized
    assert "一拍一个观察镜头" not in serialized
    payload = json.loads(messages[1]["content"])
    assert "情绪与因果单元" in payload["field_dictionary"]["beats"]
    assert "多个镜头" in payload["field_dictionary"]["beats"]
    assert "镜头划分由导演" in payload["field_dictionary"]["beats"]
    assert "观察对象切换" in messages[0]["content"]
    assert "对白接口限制" in messages[0]["content"]
    assert "不把一个动作拆成一拍" in messages[0]["content"]