"""Simple tool export for modular creation; deterministic validation stays separate.

This module builds requests only. It neither dispatches models nor edits responses,
adopts drafts, generates media, or changes frozen governance and budget records.
"""
from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

from .creative_modular_contract import (
    INPUT, VERSION, build_direction_schema, build_local_schema, validate_direction,
)
from .creative_stage_contracts import digest

EXPORT_VERSION = "modular_simple_tool_export_v1"

DIRECTION_RULES = (
    "用指定工具提交完整整片规划；本次beats严格按context.script.beats顺序覆盖，"
    "不能漏拍、重复拍或新增拍。若存在full_story_script，先理解全片情绪和因果，"
    "但本次只输出script覆盖的拍。所有数组直接写[...]，不能用item/items对象包裹。"
    "人物引用填写清单ID，不填名字。刺激引用使用source_catalog的完整路径，"
    "只能引用本拍：事件只能before/after，对白允许before/during/after；"
    "这是当前编译器的表达边界，事件与反应并行不能伪写成可执行。"
    "minimum_seconds填写正数秒数，requirement.id全片唯一。"
    "initial_state只描述第一拍事件发生前，不能先写动作已经完成；"
    "owner_id是归属，不等于holder当前持有。道具在桌面或文件叠中时holder=none，"
    "不能同时标为人物手持。initial_state只填人物和移动道具，固定物不增加状态条目；"
    "座椅及固定元素ID只能来自manifest，不能新造。空间可坐侧、朝向和位置名称必须一致。"
    "保留原对白和事件，学习参考表达机制；局部动作与排时由后续模块完成。"
)
LOCAL_RULES = (
    "用指定工具提交当前拍完整局部表演；beat_id和input_sha256照输入填写。"
    "start_state由编译器给出，不能修改；情绪、因果、对白和摄影安排沿用整片规划及原剧本。"
    "groups、operations、performance_windows均直接是数组。"
    "groups.script_slot是串行源位置：before在第一句对白前，during在第一句完整说完后、"
    "其余句之前，after在全部对白后；这里的during不是说话期间。"
    "说话期间的表演写dialogue_performance，窗口anchor使用dialogue_N（从0计）。"
    "action组hold_subject为空字符串；hold组operations必须为空数组、hold_subject填人物ID。"
    "动作结束才改变状态，依赖前提的移动、转向、坐下或取放必须拆组。"
    "take/place/pass.target填移动道具ID；sit.target填清单固定可坐物ID；"
    "move/gaze/affect/face/stand.target为空字符串。value含义见operation_dictionary。"
    "place/pass前actor必须已经持有，take前道具必须无人持有；owner不代表持有。"
    "坐下开始前position及facing必须满足spatial_contract，不能同组补前提。"
    "每个requirement_id必须出现一次且指向真实组ID或dialogue_N；事件来源只允许前/后窗口。"
    "反应时长由实际组或对白窗口承载，不能用无表演的尾部余量抵扣。"
    "source_event_anchor填写承载本拍原事件的组ID；cut_after_event_id是最后完成的真实事件；"
    "completion_condition固定all_required_events_complete。时长可浮动，不增加无叙事作用的操作。"
)

DIRECTION_FIELD_DICTIONARY = {
    "schema/context_sha256/duration_policy": "照工具枚举填写，context_sha256见请求身份；不用自行计算。",
    "emotional_arc/causal_chain/ending_intent": "全片感受递进、事件因果链数组、结尾给观众留下的感受。",
    "initial_state": "第一拍事件前每个人物的posture/position/gaze/affect/facing及每件移动道具的holder/location。",
    "spatial_contract.seats": "固定座椅seat_id、坐前可达位置access_positions数组、坐前required_facing；未知朝向用null。",
    "beats": "严格按本次script顺序的数组；每拍保留purpose/composition/camera/dialogue_mode/cut_reason。",
    "new_information/observation_object/stimulus/audience_feeling": "本拍新增事实、主要看谁或什么、刺激内容、期望观众感受。",
    "performance_requirements": "数组，每项{id,subject,stimulus_source,relation,minimum_seconds}；id唯一，subject人物ID，source本拍规范路径。",
    "relation": "before在刺激前，during在刺激期间，after在刺激结束后；事件不可during，允许对白during。",
}
LOCAL_FIELD_DICTIONARY = {
    "schema/beat_id/input_sha256": "照工具枚举及request_identity填写；输入身份由本地生成。",
    "duration_seconds": "该拍完整时长，正数；须容纳全部动作、锁定对白与指定反应窗口。",
    "groups": "数组，每项{id,script_slot,kind,duration_seconds,hold_subject,performance,operations}；id全片唯一。",
    "dialogue_performance": "真实对白期间的可见嘴部、呼吸和情绪表演；不改台词。",
    "reaction": "{anchor,subject,meaning}：真实事件ID或dialogue_N、人物ID、反应在叙事中的意义。",
    "source_event_anchor": "groups中承载原事件的组ID，不能编造。",
    "performance_windows": "数组，每项{requirement_id,anchor}；完整覆盖当前拍全部表演要求。",
    "cut_after_event_id/completion_condition": "最后完成的组ID或dialogue_N；固定all_required_events_complete。",
}
OPERATION_DICTIONARY = {
    "move/sit/stand": "value为动作结束后的明确位置；sit.target为固定可坐物ID，move/stand.target为空。",
    "face": "target为空，value为身体朝向；gaze是视线，不能替代face。",
    "gaze/affect": "target为空，value分别为视线目标/可见表情。",
    "take": "target为移动道具ID，value为拿起后的手持或佩戴位置。",
    "place": "target为当前持有的移动道具ID，value为落点位置或固定元素ID。",
    "pass": "target为当前持有的移动道具ID，value为接收人物ID。",
}
DIRECTION_STRUCTURE_EXAMPLE = {
    "note": "另一场景的单拍条目结构示例；不是当前计划，勿复制人物、来源、关系和数值。完整输出还须包含全部根字段与当前所有拍。",
    "beat": {
        "beat_id": "DEMO_B9", "purpose": "察觉关系变化", "composition": "观察回应者",
        "camera": "稳定中近景", "dialogue_mode": "画内对白", "cut_reason": "反应形成新的事实",
        "new_information": "对方不再回避", "observation_object": "回应者", "stimulus": "听到一句邀请",
        "audience_feeling": "迟疑渐缓",
        "performance_requirements": [{
            "id": "DEMO_R9", "subject": "DEMO_C9",
            "stimulus_source": "script.beats.8.dialogue.0.text",
            "relation": "after", "minimum_seconds": 1.5,
        }],
    },
}
LOCAL_STRUCTURE_EXAMPLE = {
    "note": "另一场景的局部字段结构示例；不是当前安排，真实输出须包含全部工具必填字段，不复制demo值。",
    "groups": [{
        "id": "DEMO_HOLD", "script_slot": "after", "kind": "hold", "duration_seconds": 1.5,
        "hold_subject": "DEMO_C9", "performance": "停留在人物可读的表情变化", "operations": [],
    }],
    "performance_windows": [{"requirement_id": "DEMO_R9", "anchor": "DEMO_HOLD"}],
}


def _serialize(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def source_catalog(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Return canonical references grouped by the current compilation beat."""
    entries = []
    for index, beat in enumerate(context["script"]["beats"]):
        entries.append({
            "beat_id": beat["id"],
            "event": f"script.beats.{index}.event",
            "dialogue": [
                f"script.beats.{index}.dialogue.{i}.text"
                for i in range(len(beat["dialogue"]))
            ],
        })
    return entries


def entity_catalog(context: dict[str, Any]) -> dict[str, Any]:
    manifest = context["static_visual_manifest"]
    return {
        "characters": [{"id": c["id"], "name": c.get("name", "")} for c in manifest["characters"]],
        "props": [{"id": p["id"], "name": p.get("name", ""), "owner_id": p.get("owner_id")}
                  for p in manifest["props"]],
        "fixed_elements": [{"id": e["id"], "name": e.get("name", "")}
                           for e in manifest.get("scene", {}).get("elements", [])],
    }


def _simple_schema(value: Any) -> Any:
    """Remove conditional tool encoding; original local validators still enforce it."""
    if isinstance(value, list):
        return [_simple_schema(item) for item in value]
    if not isinstance(value, dict):
        return deepcopy(value)
    result = {}
    for key, item in value.items():
        if key == "allOf":
            if not isinstance(item, list) or any(not isinstance(part, dict) or "if" not in part for part in item):
                raise ValueError("unrecognized allOf requires an explicit tool adapter")
            continue
        if key in {"if", "then", "else"}:
            raise ValueError("unexpected standalone conditional requires an explicit tool adapter")
        if key == "prefixItems":
            raise ValueError("prefixItems must be flattened explicitly before simple export")
        if key == "const":
            result["enum"] = [deepcopy(item)]
        else:
            result[key] = _simple_schema(item)
    return result


def build_direction_tool_schema(context: dict[str, Any]) -> dict[str, Any]:
    """Export simple enums and ordinary arrays, without weakening adoption gates."""
    source = build_direction_schema(context)
    beats = source["properties"]["beats"]
    units = beats.pop("prefixItems")
    unit = deepcopy(units[0])
    unit["properties"]["beat_id"] = {"type": "string", "enum": [b["id"] for b in context["script"]["beats"]]}
    paths = [path for row in source_catalog(context) for path in [row["event"], *row["dialogue"]]]
    requirement = unit["properties"]["performance_requirements"]["items"]
    requirement["properties"]["stimulus_source"] = {"type": "string", "enum": paths}
    beats["items"] = unit
    result = _simple_schema(source)
    result["description"] = DIRECTION_RULES
    props = result["properties"]
    props["initial_state"]["description"] = DIRECTION_FIELD_DICTIONARY["initial_state"]
    props["beats"]["items"]["properties"]["performance_requirements"]["description"] = (
        DIRECTION_FIELD_DICTIONARY["performance_requirements"] + DIRECTION_FIELD_DICTIONARY["relation"]
    )
    seats = props["spatial_contract"]["properties"]["seats"]["items"]["properties"]["seat_id"]
    seats.update(enum=[e["id"] for e in context["static_visual_manifest"].get("scene", {}).get("elements", [])])
    return result


def build_local_tool_schema(context: dict[str, Any], direction: dict[str, Any], beat_id: str) -> dict[str, Any]:
    """Export the local module's shape; compiler retains all operation preconditions."""
    validate_direction(direction, context)
    result = _simple_schema(build_local_schema(context, direction, beat_id))
    result["description"] = LOCAL_RULES
    operation = result["properties"]["groups"]["items"]["properties"]["operations"]["items"]
    manifest = context["static_visual_manifest"]
    operation["properties"]["target"]["enum"] = [
        "", *[p["id"] for p in manifest["props"]],
        *[e["id"] for e in manifest.get("scene", {}).get("elements", [])],
    ]
    return result


def _messages(system: str, payload: dict[str, Any], revision_feedback: Any) -> list[dict[str, str]]:
    if revision_feedback is not None:
        payload["revision_feedback"] = deepcopy(revision_feedback)
        system += "本次为返修：生成完整新稿，禁止只提交补丁或拼接旧稿；新稿仍须全文重新校验和复审。"
    return [{"role": "system", "content": system}, {"role": "user", "content": _serialize(payload)}]


def build_direction_request_messages(context: dict[str, Any], *, revision_feedback: Any = None) -> list[dict[str, str]]:
    """Include the unabridged context, actual reference text and selected asset refs."""
    payload = {
        "tool_export_version": EXPORT_VERSION,
        "context": deepcopy(context),
        "request_identity": {"context_sha256": digest(context)},
        "entity_catalog": entity_catalog(context),
        "source_catalog": source_catalog(context),
        "field_dictionary": deepcopy(DIRECTION_FIELD_DICTIONARY),
        "structure_example": deepcopy(DIRECTION_STRUCTURE_EXAMPLE),
    }
    return _messages(DIRECTION_RULES, payload, revision_feedback)


def build_local_request_messages(local_input: dict[str, Any], *, revision_feedback: Any = None) -> list[dict[str, str]]:
    """Transmit compiler-derived start state with all bound upstream source material."""
    if local_input.get("schema") != INPUT or local_input.get("protocol") != VERSION:
        raise ValueError("local request requires an input from build_local_input")
    context, direction = local_input["context"], local_input["direction"]
    validate_direction(direction, context)
    if local_input["beat_id"] not in [row["beat_id"] for row in direction["beats"]]:
        raise ValueError("local beat is outside the validated direction")
    payload = {
        "tool_export_version": EXPORT_VERSION,
        "local_input": deepcopy(local_input),
        "request_identity": {"input_sha256": digest(local_input)},
        "entity_catalog": entity_catalog(context),
        "source_catalog": source_catalog(context),
        "field_dictionary": deepcopy(LOCAL_FIELD_DICTIONARY),
        "operation_dictionary": deepcopy(OPERATION_DICTIONARY),
        "structure_example": deepcopy(LOCAL_STRUCTURE_EXAMPLE),
    }
    return _messages(LOCAL_RULES, payload, revision_feedback)
