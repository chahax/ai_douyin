"""Complete linear scripts with one explicit playback order and derived legacy slots."""
from __future__ import annotations

from copy import deepcopy
import json
import math
from typing import Any

from jsonschema import Draft202012Validator

from src.content_factory.creative_workflow_contract import CreativeContractError

VERSION = "complete_linear_script_v2"
EMPTY_ACTION = "（无新增动作）"
FIELD_DICTIONARY = {
    "beats": "普通数组。叙事拍按情绪与因果单元组织，可含多个镜头；镜头划分由导演决定。",
    "duration_seconds": "仅填写当前拍的完整秒数；整片总时长由程序求和。",
    "event": "本拍事件摘要，不代替实际表演步骤。",
    "trigger": "这拍为何推进信息、因果或观众感受。",
    "steps": "普通数组，数组顺序就是实际播放顺序。",
    "action": "可见动作或无对白的表演；speaker填空字符串，text写动作。",
    "dialogue": "真正说出的这一句；speaker填人物名，text只写原句。",
}
RULES = """提交完整新剧本，使用指定工具；不写分析、补丁或局部替换。
steps数组是唯一播放顺序：开口前动作、对白、听后反应按实际先后逐项填写。每拍最多两句对白只是现有对白接口限制，不把一个动作拆成一拍。
不要在action再次描述已经播放的同一次说话；不要生成before/during/after或重复填写整片总时长。
明确人物和道具的位置变更及取用前提，按情绪与因果推进组织叙事拍；保留必需的观察对象切换，镜头划分由导演安排，不为固定时长添加无作用动作。
参考全文与完整旧稿都在输入中，只学习表达机制。结合问题重新创作完整新稿，不把失效旧稿转换格式后当新交付。
"""


def _fail(code: str, message: str) -> None:
    error = CreativeContractError(code + ": " + message)
    error.detail = {"code": code, "blocks_handoff": True, "automatic_retry": False}
    raise error


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False,
            "required": list(properties), "properties": properties}


def _names(previous: dict[str, Any]) -> list[str]:
    return sorted({line["speaker"] for beat in previous.get("beats", [])
                   for line in beat.get("dialogue", [])
                   if isinstance(line, dict) and isinstance(line.get("speaker"), str)
                   and line["speaker"].strip()})


def _schema(candidate_id: str, names: list[str]) -> dict[str, Any]:
    text = {"type": "string", "minLength": 1}
    step = _object({
        "kind": {"type": "string", "enum": ["action", "dialogue"]},
        "speaker": {"type": "string", "enum": ["", *names],
                    "description": "action为空字符串；dialogue为实际人物名。"},
        "text": {**text, "description": "action写可见表演；dialogue只写这一句原文。"},
    })
    beat = _object({
        "id": {**text, "description": "完整新稿内唯一拍ID。"},
        "duration_seconds": {"type": "number", "exclusiveMinimum": 0, "maximum": 600,
                             "description": "只填本拍秒数，不重复生成总时长。"},
        "event": deepcopy(text), "trigger": deepcopy(text),
        "steps": {"type": "array", "minItems": 1, "items": step,
                  "description": "顺序就是播放顺序；每拍最多两句dialogue。"},
    })
    return _object({
        "title": deepcopy(text), "premise": deepcopy(text),
        "selected_candidate_id": {"type": "string", "const": candidate_id},
        "beats": {"type": "array", "minItems": 1, "items": beat},
    })


def build_linear_script_schema(context: dict[str, Any]) -> dict[str, Any]:
    names = sorted({row["name"] for row in context.get("static_visual_manifest", {}).get("characters", [])
                    if isinstance(row.get("name"), str) and row["name"].strip()})
    if not names:
        names = _names(context["script"])
    return _schema(context["script"]["selected_candidate_id"], names)


def build_linear_script_messages(
    context: dict[str, Any], previous_script: dict[str, Any], issues: Any
) -> list[dict[str, str]]:
    payload = {"protocol": VERSION, "context": deepcopy(context),
               "previous_script": deepcopy(previous_script), "issues": deepcopy(issues),
               "field_dictionary": deepcopy(FIELD_DICTIONARY),
               "revision_mode": "complete_new_script"}
    return [{"role": "system", "content": RULES},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]


def render_linear_screenplay(raw: dict[str, Any]) -> str:
    lines = [f"# {raw['title']}", ""]
    for beat in raw["beats"]:
        lines.extend([f"## {beat['id']} {beat['event']}", ""])
        for step in beat["steps"]:
            line = (f"**{step['speaker']}**：{step['text']}"
                    if step["kind"] == "dialogue" else step["text"])
            lines.extend([line, ""])
    return "\n".join(lines).strip()


def accept_linear_script(
    previous: dict[str, Any], raw: dict[str, Any], *,
    character_names: list[str] | None = None,
) -> dict[str, Any]:
    """Derive slots from a complete new script; preserve caller-owned raw exactly.

    The default speaker catalog uses the previous complete script. A caller
    admitting a previously silent character may pass the bound asset names.
    """
    if not isinstance(raw, dict):
        _fail("LINEAR_SCHEMA_INVALID", "必须提交完整对象")
    candidate = previous["selected_candidate_id"]
    if raw.get("selected_candidate_id") != candidate:
        _fail("LINEAR_IDENTITY_CHANGED", "完整新稿不能更换已选故事身份")
    names = sorted(set(character_names)) if character_names is not None else _names(previous)
    errors = list(Draft202012Validator(_schema(candidate, names)).iter_errors(raw))
    if errors:
        _fail("LINEAR_SCHEMA_INVALID", errors[0].message)
    accepted = deepcopy(raw)
    seen_ids = set()
    derived = []
    for beat in accepted["beats"]:
        if not beat["id"].strip() or beat["id"] in seen_ids:
            _fail("LINEAR_BEAT_ID_INVALID", "每拍ID必须非空且唯一")
        seen_ids.add(beat["id"])
        seconds = beat["duration_seconds"]
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds <= 600:
            _fail("LINEAR_DURATION_INVALID", "每拍必须为有限正秒数")
        for field in ("event", "trigger"):
            if not beat[field].strip():
                _fail("LINEAR_SCHEMA_INVALID", field + "不能为空白")
        dialogue_count = sum(step["kind"] == "dialogue" for step in beat["steps"])
        if dialogue_count > 2:
            _fail("LINEAR_TOO_MANY_DIALOGUES", "每拍最多两句，更多对白需另拍")
        slots = {"before": [], "during": [], "after": []}
        dialogue = []
        spoken = 0
        for step in beat["steps"]:
            if not step["text"].strip():
                _fail("LINEAR_STEP_TEXT_INVALID", "步骤正文不能为空白")
            if step["kind"] == "dialogue":
                if not step["speaker"] or step["speaker"] not in names:
                    _fail("LINEAR_SPEAKER_INVALID", "对白须有已绑定的真实人物名")
                dialogue.append({"speaker": step["speaker"], "text": step["text"]})
                spoken += 1
            else:
                if step["speaker"] != "":
                    _fail("LINEAR_ACTION_SPEAKER_INVALID", "action的speaker必须为空字符串")
                slot = "before" if spoken == 0 else (
                    "during" if dialogue_count == 2 and spoken == 1 else "after")
                slots[slot].append(step["text"])
        derived.append({
            "id": beat["id"], "duration_seconds": seconds,
            "event": beat["event"], "trigger": beat["trigger"],
            **{slot: "\n".join(actions) if actions else EMPTY_ACTION for slot, actions in slots.items()},
            "dialogue": dialogue,
        })
    total = sum(beat["duration_seconds"] for beat in derived)
    if not math.isfinite(total) or not 0 < total <= 600:
        _fail("LINEAR_DURATION_INVALID", "整片派生总时长超出现有0—600秒合同")
    if not accepted["title"].strip() or not accepted["premise"].strip():
        _fail("LINEAR_SCHEMA_INVALID", "标题和梗概不能为空白")
    return {"title": accepted["title"], "premise": accepted["premise"],
            "selected_candidate_id": candidate, "duration_seconds": total,
            "beats": derived, "screenplay_markdown": render_linear_screenplay(accepted)}