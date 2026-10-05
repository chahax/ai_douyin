"""Whole-story direction before complete scripts; no provider or media dispatch."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any

from jsonschema import Draft202012Validator

from src.content_factory.creative_workflow_contract import CreativeContractError

VERSION = "creative_story_direction_contract/v1"
WRITER_MODEL = "MiniMax-M3"
INPUT_FIELDS = (
    "creative_brief", "brief", "static_visual_manifest", "reference_pack",
    "material_ref", "reference_expression_rule", "selected_assets", "selected_asset_refs",
)
FORBIDDEN_FEEDBACK_CONTAINERS = {
    "script", "raw_linear_script", "previous_script", "previous_draft",
    "failed_script", "failed_draft", "previous_complete_local",
    "previous_complete_direction", "beats", "steps", "shots", "storyboard",
    "state_plan", "action_plan", "step_units", "operations",
}
FIELD_DICTIONARY = {
    "title": "本次完整故事方向的标题。",
    "relationship_pressure": "谁想达成什么，关系中的障碍是什么，选择要付出什么代价；用关系和行为说明。",
    "viewer_emotional_arc": "普通数组，按故事先后说明观众如何感受、为何变化。不是表情清单。",
    "causal_events": "普通数组，顺序就是故事因果推进。数量依完整故事需要，不按拍数或镜数凑项。",
    "id": "本方向内唯一的事件ID，只用于后续追踪。",
    "cause": "首事件说明目标和障碍；后续事件承接前一结果，说明为何引出新的行动或选择。",
    "visible_event": "观众实际看到或听到的事件及关系行为，不写抽象心理结论，不生成类型化微观操作。",
    "new_information": "这一事件让观众新知道什么，不能只是重复先前信息。",
    "emotional_turn": "事件如何改变观众感受及人物关系；具体感染力仍待方向审查。",
    "result": "行动或选择造成的后果、代价或关系变化，为下一事件提供原因。",
    "ending_action": "以结尾实际发生的行动兑现最后结果及关系变化，不以主题口号代替事件。",
    "asset_ids": "普通数组，仅使用输入已登记的人物、道具和固定场景元素ID；不要求把所有道具塞进故事。",
}
RULES = """使用指定工具提交一个完整故事方向，不写长分析、补丁或完整剧本。
先解决整片的目标、障碍、选择、代价以及关系行为，再组织观众情绪和事件因果。
因果事件数量按作品需要，不锁具体剧情、固定拍数、镜数或时长。
参考全文用于学习表达机制，不照搬其中剧情，也不把以前失败整稿的动作链作为模板。
本阶段不生成steps、逐拍表演、微观operations、持有状态、机位排时或对白时间窗。
完整方向确认后，由另一个阶段生成完整script及实际播放steps；导演再细化镜头与表演，程序编译状态和时间。
本合同的本地验收仅检查结构和登记来源，不能证明故事语义、情绪表达或制作交接通过。
"""


def _fail(code: str, message: str, path: str = "") -> None:
    error = CreativeContractError(code + ": " + message)
    error.detail = {
        "code": code, "path": path, "blocks_handoff": True,
        "automatic_retry": False, "semantic_approval": False,
    }
    raise error


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False,
            "required": list(properties), "properties": properties}


def _asset_catalog(context: dict[str, Any]) -> dict[str, dict[str, Any]]:
    manifest = context.get("static_visual_manifest")
    if not isinstance(manifest, dict):
        _fail("STORY_DIRECTION_SOURCE_REQUIRED", "必须提供完整登记资产清单")
    catalog: dict[str, dict[str, Any]] = {}
    scene = manifest.get("scene", {})
    if not isinstance(scene, dict):
        _fail("STORY_DIRECTION_ASSET_INVALID", "登记场景必须为对象")
    groups = (manifest.get("characters", []), manifest.get("props", []),
              scene.get("elements", []))
    for entries in groups:
        if not isinstance(entries, list):
            _fail("STORY_DIRECTION_ASSET_INVALID", "登记资产必须为数组")
        for entry in entries:
            asset_id = entry.get("id") if isinstance(entry, dict) else None
            if not isinstance(asset_id, str) or not asset_id.strip() or asset_id != asset_id.strip():
                _fail("STORY_DIRECTION_ASSET_INVALID", "登记资产必须有明确ID")
            if asset_id in catalog:
                _fail("STORY_DIRECTION_ASSET_INVALID", "登记资产ID重复", asset_id)
            catalog[asset_id] = deepcopy(entry)
    if not catalog:
        _fail("STORY_DIRECTION_SOURCE_REQUIRED", "登记资产清单不能为空")
    return catalog


def _creative_inputs(original_context: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(original_context, dict):
        _fail("STORY_DIRECTION_SOURCE_REQUIRED", "必须提供完整原始创作输入")
    if not any(isinstance(original_context.get(key), dict) and original_context[key]
               for key in ("creative_brief", "brief")):
        _fail("STORY_DIRECTION_SOURCE_REQUIRED", "必须提供完整创作brief")
    _asset_catalog(original_context)
    references = original_context.get("reference_pack")
    if not isinstance(references, list) or not references or any(
        not isinstance(row, dict) or not isinstance(row.get("text"), str)
        or not row["text"].strip() for row in references
    ):
        _fail("STORY_DIRECTION_REFERENCE_REQUIRED", "参考必须包含全文，不能只传路径或摘要")
    return {key: deepcopy(original_context[key]) for key in INPUT_FIELDS
            if key in original_context}


def _checked_feedback(feedback: Any) -> Any:
    def visit(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in FORBIDDEN_FEEDBACK_CONTAINERS:
                    _fail("STORY_DIRECTION_FEEDBACK_SOURCE_FORBIDDEN",
                          "反馈只传已核实的问题及必要证据，不传旧稿或动作链容器",
                          path + "." + key)
                visit(item, path + "." + str(key))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, path + "." + str(index))
    visit(feedback, "verified_feedback")
    return deepcopy(feedback)


def build_schema(original_context: dict[str, Any]) -> dict[str, Any]:
    catalog = _asset_catalog(original_context)
    def text(field: str) -> dict[str, Any]:
        return {"type": "string", "minLength": 1,
                "description": FIELD_DICTIONARY[field]}
    event = _object({field: text(field) for field in (
        "id", "cause", "visible_event", "new_information", "emotional_turn", "result",
    )})
    return {**_object({
        "title": text("title"), "relationship_pressure": text("relationship_pressure"),
        "viewer_emotional_arc": {"type": "array", "minItems": 2,
            "items": {"type": "string", "minLength": 1},
            "description": FIELD_DICTIONARY["viewer_emotional_arc"]},
        "causal_events": {"type": "array", "minItems": 2, "items": event,
                         "description": FIELD_DICTIONARY["causal_events"]},
        "ending_action": text("ending_action"),
        "asset_ids": {"type": "array", "minItems": 1, "uniqueItems": True,
            "items": {"type": "string", "enum": sorted(catalog)},
            "description": FIELD_DICTIONARY["asset_ids"]},
    }), "description": RULES}


def build_messages(original_context: dict[str, Any], verified_feedback: Any) -> list[dict[str, str]]:
    inputs = _creative_inputs(original_context)
    payload = {
        "protocol": VERSION, "context": inputs,
        "verified_feedback": _checked_feedback(verified_feedback),
        "field_dictionary": deepcopy(FIELD_DICTIONARY),
        "mode": "complete_whole_story_direction",
        "request_identity": {
            "original_context_sha256": _digest(original_context),
            "creative_inputs_sha256": _digest(inputs),
            "reference_pack_sha256": _digest(inputs["reference_pack"]),
        },
        "next_stage": "direction_confirmation_then_complete_script",
    }
    return [{"role": "system", "content": RULES},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False,
                                                 allow_nan=False)}]


def validate(direction: dict[str, Any], original_context: dict[str, Any]) -> dict[str, Any]:
    schema = build_schema(original_context)
    errors = list(Draft202012Validator(schema).iter_errors(direction))
    if errors:
        error = errors[0]
        _fail("STORY_DIRECTION_SCHEMA_INVALID", error.message,
              ".".join(map(str, error.absolute_path)))
    ids: set[str] = set()
    for index, event in enumerate(direction["causal_events"]):
        event_id = event["id"]
        if event_id != event_id.strip() or event_id in ids:
            _fail("STORY_DIRECTION_EVENT_ID_INVALID", "事件ID须唯一且无首尾空白",
                  f"causal_events.{index}.id")
        ids.add(event_id)
        for field, value in event.items():
            if not value.strip():
                _fail("STORY_DIRECTION_EMPTY_FIELD", "每事件的因果、可见事件、信息及后果必须完整填写",
                      f"causal_events.{index}.{field}")
    for field in ("title", "relationship_pressure", "ending_action"):
        if not direction[field].strip():
            _fail("STORY_DIRECTION_EMPTY_FIELD", "完整故事方向字段不能为空白", field)
    if any(not value.strip() for value in direction["viewer_emotional_arc"]):
        _fail("STORY_DIRECTION_EMPTY_FIELD", "观众感受阶段不能为空白", "viewer_emotional_arc")
    return {
        "status": "story_direction_structure_valid_pending_review",
        "protocol": VERSION, "direction_sha256": _digest(direction),
        "registered_asset_ids_checked": True, "unique_event_ids_checked": True,
        "causal_fields_covered": True, "causal_semantics_verified": False,
        "ending_action_semantics_verified": False, "semantic_approval": False,
        "production_ready": False, "automatic_media_submit": False,
        "requires_direction_confirmation": True,
        "next_stage": "complete_model_authored_script_then_full_review",
    }


build_story_direction_schema = build_schema
build_story_direction_messages = build_messages
validate_story_direction = validate
