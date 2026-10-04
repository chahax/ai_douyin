from copy import deepcopy
import inspect
import json

from jsonschema import Draft202012Validator
import pytest

from scripts import creative_story_direction_contract_v1 as contract
from src.content_factory.creative_workflow_contract import CreativeContractError


def context():
    return {
        "creative_brief": {"theme": "第一次把自己的时间放在前面",
            "relationships": "两人长期的帮助关系", "audience_emotion": "理解、紧张、余味",
            "turn": "拒绝产生真实后果", "ending": "具体行为兑现变化",
            "constraints": ["先建立自然可信的关系压力"]},
        "static_visual_manifest": {
            "characters": [{"id": "C01", "name": "甲"}, {"id": "C02", "name": "乙"}],
            "props": [{"id": "P01", "name": "纸张", "owner_id": "C02"}],
            "scene": {"name": "办公室", "elements": [{"id": "E01", "name": "门"}]},
            "render": {"visual_medium": "真人", "palette": "暖灰"},
        },
        "reference_pack": [{"id": "R01", "path": "reference.md",
            "text": "完整参考起点\n表达机制：具体刺激改变反应。\n完整参考终点"}],
        "reference_expression_rule": "借鉴机制，不照搬剧情。",
        "selected_assets": [{"id": "C01", "path": "selected_character.png"}],
        "script": {"title": "FAILED_SCRIPT_SENTINEL", "beats": [{"before": "FAILED_ACTION_CHAIN"}]},
        "raw_linear_script": {"title": "FAILED_RAW_SENTINEL", "beats": [{"steps": ["失败旧动作链"]}]},
        "previous_script": {"title": "FAILED_PREVIOUS_SENTINEL"},
    }


def direction():
    return {
        "title": "把选择交还给彼此",
        "relationship_pressure": "甲想准时离开，乙习惯她帮忙；甲担心拒绝会伤及关系。",
        "viewer_emotional_arc": ["看懂甲为什么难以拒绝", "因选择而紧张", "看到行动变化后留下余味"],
        "causal_events": [
            {"id": "EV1", "cause": "乙沿用过去被帮助的习惯",
             "visible_event": "乙把未完工作交给甲并提及她前次替自己收尾",
             "new_information": "甲的帮助已变成对方的默认期待",
             "emotional_turn": "观众理解甲的顾虑并感到压力",
             "result": "甲必须在自己的安排和关系惯例之间选择"},
            {"id": "EV2", "cause": "默认期待使甲继续付出自己的时间",
             "visible_event": "甲拒绝留下，乙第一次接回自己的工作",
             "new_information": "边界开始产生对双方都可见的后果",
             "emotional_turn": "观众为拒绝紧张并观察关系能否承受",
             "result": "乙承担自己的任务，甲必须真正离开而不再收尾"},
        ],
        "ending_action": "甲离开办公室，乙留在自己的任务前开始处理。",
        "asset_ids": ["C01", "C02", "P01", "E01"],
    }


def test_actual_request_messages_preserve_full_brief_assets_and_reference():
    original = context()
    feedback = [{"id": "F01", "evidence": "之前事件未建立选择代价", "verified": True}]
    before = deepcopy((original, feedback))
    messages = contract.build_messages(original, feedback)
    payload = json.loads(messages[1]["content"])
    assert payload["context"]["creative_brief"] == original["creative_brief"]
    assert payload["context"]["static_visual_manifest"] == original["static_visual_manifest"]
    assert payload["context"]["reference_pack"] == original["reference_pack"]
    assert payload["context"]["selected_assets"] == original["selected_assets"]
    assert payload["context"]["reference_pack"][0]["text"] == original["reference_pack"][0]["text"]
    assert payload["verified_feedback"] == feedback
    assert (original, feedback) == before
    assert payload["request_identity"]["reference_pack_sha256"]


def test_failed_whole_scripts_and_action_chains_are_not_creative_templates():
    messages = contract.build_messages(context(), [])
    serialized = json.dumps(messages, ensure_ascii=False)
    for marker in ("FAILED_SCRIPT_SENTINEL", "FAILED_ACTION_CHAIN",
                   "FAILED_RAW_SENTINEL", "FAILED_PREVIOUS_SENTINEL", "失败旧动作链"):
        assert marker not in serialized
    payload = json.loads(messages[1]["content"])
    assert not {"script", "raw_linear_script", "previous_script"} & set(payload["context"])


@pytest.mark.parametrize("key", ["raw_linear_script", "script", "steps", "operations"])
def test_feedback_cannot_smuggle_a_failed_script_or_action_container(key):
    with pytest.raises(CreativeContractError, match="STORY_DIRECTION_FEEDBACK_SOURCE_FORBIDDEN"):
        contract.build_messages(context(), [{"evidence": {key: {"text": "失效模板"}}}])


def test_schema_only_has_direction_fields_and_plain_arrays():
    schema = contract.build_schema(context())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(direction())
    assert set(schema["properties"]) == {
        "title", "relationship_pressure", "viewer_emotional_arc",
        "causal_events", "ending_action", "asset_ids",
    }
    for field in ("viewer_emotional_arc", "causal_events", "asset_ids"):
        assert schema["properties"][field]["type"] == "array"
        assert "items" in schema["properties"][field]
        assert "prefixItems" not in schema["properties"][field]
        assert "maxItems" not in schema["properties"][field]
    assert set(schema["properties"]["causal_events"]["items"]["properties"]) == {
        "id", "cause", "visible_event", "new_information", "emotional_turn", "result",
    }
    assert all(key not in json.dumps(schema) for key in ('"if"', '"then"', '"prefixItems"'))


@pytest.mark.parametrize("field", ["viewer_emotional_arc", "causal_events", "asset_ids"])
def test_array_item_object_is_rejected(field):
    value = direction()
    value[field] = {"item": value[field]}
    with pytest.raises(CreativeContractError, match="STORY_DIRECTION_SCHEMA_INVALID"):
        contract.validate(value, context())


def test_unknown_and_duplicate_assets_are_rejected():
    value = direction()
    value["asset_ids"].append("UNREGISTERED")
    with pytest.raises(CreativeContractError, match="STORY_DIRECTION_SCHEMA_INVALID"):
        contract.validate(value, context())
    value["asset_ids"] = ["C01", "C01"]
    with pytest.raises(CreativeContractError, match="STORY_DIRECTION_SCHEMA_INVALID"):
        contract.validate(value, context())


def test_event_ids_are_unique_and_validation_preserves_the_complete_model_value():
    value = direction()
    snapshot = deepcopy(value)
    result = contract.validate(value, context())
    assert value == snapshot
    assert result["status"] == "story_direction_structure_valid_pending_review"
    assert result["semantic_approval"] is False and result["production_ready"] is False
    assert result["causal_semantics_verified"] is False
    value["causal_events"][1]["id"] = value["causal_events"][0]["id"]
    with pytest.raises(CreativeContractError, match="STORY_DIRECTION_EVENT_ID_INVALID"):
        contract.validate(value, context())


@pytest.mark.parametrize("field", ["cause", "visible_event", "new_information", "emotional_turn", "result"])
def test_every_causal_event_requires_real_nonblank_fields(field):
    value = direction()
    value["causal_events"][0][field] = " \n "
    with pytest.raises(CreativeContractError, match="STORY_DIRECTION_EMPTY_FIELD"):
        contract.validate(value, context())


def test_ending_and_causal_structure_cannot_be_missing_or_blank():
    for change in (lambda value: value.update(ending_action=" \n "),
                   lambda value: value.update(causal_events=[])):
        value = direction()
        change(value)
        with pytest.raises(CreativeContractError):
            contract.validate(value, context())


def test_full_reference_required_instead_of_path_only():
    original = context()
    original["reference_pack"][0].pop("text")
    with pytest.raises(CreativeContractError, match="STORY_DIRECTION_REFERENCE_REQUIRED"):
        contract.build_messages(original, [])


def test_micro_operations_or_duration_are_not_accepted_as_story_direction():
    for field in ("steps", "operations", "duration_seconds", "beats"):
        value = direction()
        value[field] = []
        with pytest.raises(CreativeContractError, match="STORY_DIRECTION_SCHEMA_INVALID"):
            contract.validate(value, context())


def test_no_provider_dispatch_or_media_capability_is_imported_or_executed():
    source = inspect.getsource(contract)
    for forbidden in ("CreativeRoleClients", "OpenAI(", "get_usage_limits", "requests.", "httpx."):
        assert forbidden not in source
    assert contract.WRITER_MODEL == "MiniMax-M3"
    result = contract.validate(direction(), context())
    assert not result["automatic_media_submit"]
    assert result["requires_direction_confirmation"]
    assert result["next_stage"] == "complete_model_authored_script_then_full_review"
