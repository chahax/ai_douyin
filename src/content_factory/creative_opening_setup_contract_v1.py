"""Native opening state bound to an independently accepted static whole plan.

The validator does not complete fields, parse Chinese state descriptions or
change the plan. The native contract explicitly declares all current prop
states. Conceptual ownership remains in the original plan, not in this setup.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any

from jsonschema import Draft202012Validator

from . import creative_goal_source_contract_v4 as goals

VERSION = "creative_opening_setup/v1"
OPENING_SETUP_RULE = """根据已验收的完整规划，提交完整原生开场状态，不修改规划人物初态或静态道具归属。
characters精确覆盖规划中每个人物，scene_id、posture、location必须逐字保留其initial_state。
props精确覆盖静态道具清单；presence只声明开场present或absent，不把未来形成或中段引入当作当前已存在。
present的location记录明确的开场位置；尚未指定时只能填null，不能从owner猜位置或持有人。
holder_character_id只有已明确在开场持有的规划人物ID或null；null不等于概念所有者。
absent的holder_character_id、location、orientation必须全部为null，不允许同时声明当前物理状态。
owner仍从规划原生静态清单读取，不在本合同重写。不能用未来纸张属于谁推断开场谁拿着它。
不省略或增加人物、道具，不输出逐秒表演；若需修订，提交完整新setup，程序不补null、不拼接。"""


class OpeningSetupContractError(ValueError):
    def __init__(self, code: str, detail: Any):
        self.code, self.detail = code, deepcopy(detail)
        super().__init__(code + ": " + str(detail))


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def _obj(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


def _pointer(parts) -> str:
    return "/" + "/".join(str(part).replace("~", "~0").replace("/", "~1")
                            for part in parts) if parts else "$"


def _bindings(goal: Any):
    """Read valid native identity atoms only; no provenance or quality approval."""
    errors = list(Draft202012Validator(goals.build_goal_request_schema()).iter_errors(goal))
    if errors:
        raise OpeningSetupContractError("OPENING_SETUP_GOAL_INVALID", {
            "findings": [{"path": _pointer(error.absolute_path), "message": error.message}
                         for error in errors], "native_goal_modified": False})
    plan = goal["whole_plan"]
    bindings = {}
    seen = set()
    for label in ("characters", "scenes", "props"):
        indexed = {}
        for position, row in enumerate(plan[label]):
            identifier = row["id"]
            if identifier in seen:
                raise OpeningSetupContractError("OPENING_SETUP_GOAL_INVALID", {
                    "path": f"/whole_plan/{label}/{position}/id",
                    "message": "duplicate or colliding native identity", "native_goal_modified": False})
            seen.add(identifier)
            indexed[identifier] = row
        bindings[label] = indexed
    for identifier, actor in bindings["characters"].items():
        if actor["initial_state"]["scene_id"] not in bindings["scenes"]:
            raise OpeningSetupContractError("OPENING_SETUP_GOAL_INVALID", {
                "path": f"/whole_plan/characters/{identifier}/initial_state/scene_id",
                "message": "unknown declared initial scene", "native_goal_modified": False})
    for identifier, prop in bindings["props"].items():
        owner = prop["owner_character_id"]
        if owner is not None and owner not in bindings["characters"]:
            raise OpeningSetupContractError("OPENING_SETUP_GOAL_INVALID", {
                "path": f"/whole_plan/props/{identifier}/owner_character_id",
                "message": "unknown declared owner", "native_goal_modified": False})
    return bindings


def build_schema(goal: dict[str, Any]) -> dict[str, Any]:
    bindings = _bindings(goal)
    actor_ids = list(bindings["characters"])
    actors = {identifier: _obj({key: {"const": actor["initial_state"][key]}
                              for key in ("scene_id", "posture", "location")})
              for identifier, actor in bindings["characters"].items()}
    nullable_text = {"anyOf": [{"type": "string", "minLength": 1, "pattern": r"\S"},
                               {"type": "null"}]}
    prop_state = _obj({
        "presence": {"type": "string", "enum": ["present", "absent"]},
        "holder_character_id": {"enum": [*actor_ids, None]},
        "location": deepcopy(nullable_text),
        "orientation": deepcopy(nullable_text),
    })
    prop_state["allOf"] = [{
        "if": {"properties": {"presence": {"const": "absent"}}, "required": ["presence"]},
        "then": {"properties": {key: {"const": None}
                                for key in ("holder_character_id", "location", "orientation")}},
    }]
    schema = _obj({
        "schema": {"const": VERSION}, "goal_sha256": {"const": digest(goal)},
        "characters": _obj(actors),
        "props": _obj({identifier: deepcopy(prop_state) for identifier in bindings["props"]}),
    })
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(schema)
    return schema


def diagnose(document: Any, goal: dict[str, Any]) -> dict[str, Any]:
    findings = []
    try:
        schema = build_schema(goal)
    except OpeningSetupContractError as exc:
        return {"valid": False, "findings": [{"code": exc.code, "detail": deepcopy(exc.detail)}],
                "native_document_modified": False, "native_goal_modified": False,
                "semantic_quality_approved": False}
    for error in Draft202012Validator(schema).iter_errors(document):
        if error.validator == "required" and isinstance(error.instance, dict):
            findings.extend({"code": "OPENING_SETUP_SCHEMA_INVALID",
                             "path": _pointer((*error.absolute_path, field)),
                             "message": "required native field missing", "validator": "required"}
                            for field in error.validator_value if field not in error.instance)
        else:
            findings.append({"code": "OPENING_SETUP_SCHEMA_INVALID",
                             "path": _pointer(error.absolute_path),
                             "message": error.message, "validator": error.validator})
    # Record cross-field failures explicitly as diagnostics even though the
    # outgoing schema carries the same constraint. Malformed types stay safe.
    if isinstance(document, dict) and isinstance(document.get("props"), dict):
        for identifier, state in document["props"].items():
            if isinstance(state, dict) and state.get("presence") == "absent":
                for key in ("holder_character_id", "location", "orientation"):
                    if key in state and state[key] is not None:
                        findings.append({"code": "OPENING_SETUP_ABSENT_PROP_HAS_CURRENT_STATE",
                                         "path": _pointer(("props", identifier, key)),
                                         "message": "absent prop cannot declare current physical state"})
    findings.sort(key=lambda row: (row.get("path", ""), row["code"], row.get("message", "")))
    return {"valid": not findings, "findings": findings,
            "native_document_modified": False, "native_goal_modified": False,
            "semantic_quality_approved": False,
            "limitations": ["No current state is inferred from prose, static ownership or future beats.",
                            "Structural validity does not establish performance or creative quality."]}


def validate(document: dict[str, Any], goal: dict[str, Any]) -> dict[str, Any]:
    diagnosis = diagnose(document, goal)
    if not diagnosis["valid"]:
        raise OpeningSetupContractError(diagnosis["findings"][0]["code"], diagnosis)
    return deepcopy(document)
