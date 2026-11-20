"""Explicit mutually exclusive physical positions for a native opening.

Ownership belongs to the static whole plan.  A prop's physical position is
either an actor, a scene, another prop, or absence; no prose is parsed to
invent a holder or support.  JSON Schema checks local types and exact IDs;
the validator checks cross-prop availability and cycles in the container graph.
Structural validity is not a semantic or creative-quality judgement.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any

from jsonschema import Draft202012Validator

from . import creative_goal_source_contract_v4 as goals

VERSION = "creative_opening_setup/v3"
ACTOR_MODES = ("handheld", "worn", "carried")
OPENING_SETUP_RULE = """提交与当前整片规划SHA绑定的完整原生开场状态，保留所有人物initial_state原文。
characters精确覆盖全部人物，scene_id、posture、location逐字复制规划初态，不为正文改位置。
props精确覆盖静态道具清单，每项只选一种物理位置kind：actor、scene、prop、absent。
actor用于人物当前手持(handheld)、穿戴(worn)或携带(carried)：明确actor_id、mode和身体上的location。
scene用于放在已登记场景中的道具：明确scene_id和真实location，没有holder或actor_id。
prop用于位于另一件已登记道具内、附着其上或由其承托：明确container_prop_id和相对location，没有holder。
容器必须在开场已存在，不得引用自己、不存在的道具、演员或场景，不得形成环。
例如柜内搁板上的本子用scene；别在本子封面的笔用prop，不能把两者都说成人物持有。
absent只填kind，不填写orientation、任何当前位置、容器、人物或携带方式；缺席物件没有物理方向。
已存在道具的location必须明确非空，orientation保留明确原文或null，不猜朝向。
owner仅在整片规划静态清单，不是物理持有或支撑证据；不同人持有也不改变所有权。
未来生成的纸页、副本或中段取来的材料不能提前放在开场；这些形成机制仍在事件中明确。
不输出逐秒动作、额外道具或台词。返修提交完整原生新版，本地不补字段、不猜中文支撑、不拼接。"""


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


def _bindings(goal: Any) -> dict[str, dict[str, Any]]:
    errors = list(Draft202012Validator(goals.build_goal_request_schema()).iter_errors(goal))
    if errors:
        raise OpeningSetupContractError("OPENING_SETUP_GOAL_INVALID", {
            "findings": [{"path": _pointer(error.absolute_path), "message": error.message}
                         for error in errors], "native_goal_modified": False})
    bindings, seen = {}, set()
    for label in ("characters", "scenes", "props"):
        indexed = {}
        for position, row in enumerate(goal["whole_plan"][label]):
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


def _position_branches(identifier: str, bindings: dict[str, Any]) -> dict[str, dict[str, Any]]:
    text = {"type": "string", "minLength": 1, "pattern": r"\S"}
    orientation = {"anyOf": [deepcopy(text), {"type": "null"}]}
    branches = {
        "actor": _obj({"kind": {"const": "actor"},
            "actor_id": {"enum": list(bindings["characters"])},
            "mode": {"enum": list(ACTOR_MODES)},
            "location": deepcopy(text), "orientation": deepcopy(orientation)}),
        "scene": _obj({"kind": {"const": "scene"},
            "scene_id": {"enum": list(bindings["scenes"])},
            "location": deepcopy(text), "orientation": deepcopy(orientation)}),
        "absent": _obj({"kind": {"const": "absent"}}),
    }
    containers = [candidate for candidate in bindings["props"] if candidate != identifier]
    if containers:
        branches["prop"] = _obj({"kind": {"const": "prop"},
            "container_prop_id": {"enum": containers},
            "location": deepcopy(text), "orientation": deepcopy(orientation)})
    return branches


def build_schema(goal: dict[str, Any]) -> dict[str, Any]:
    """Exact native coverage, exclusive kinds and local typed references.

    Cross-prop availability and directed cycles are checked by diagnose/
    validate.  Do not expand quadratic availability conditions or enumerate
    exponentially many cycles in the model's request schema.
    """
    bindings = _bindings(goal)
    actors = {identifier: _obj({key: {"const": actor["initial_state"][key]}
                              for key in ("scene_id", "posture", "location")})
              for identifier, actor in bindings["characters"].items()}
    prop_fields = {identifier: {"type": "object", "required": ["kind"],
                               "oneOf": list(_position_branches(identifier, bindings).values())}
                   for identifier in bindings["props"]}
    schema = _obj({"schema": {"const": VERSION}, "goal_sha256": {"const": digest(goal)},
                   "characters": _obj(actors), "props": _obj(prop_fields)})
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(schema)
    return schema


def _schema_findings(error, prefix=()):
    path = (*prefix, *error.absolute_path)
    if error.validator == "required" and isinstance(error.instance, dict):
        return [{"code": "OPENING_SETUP_SCHEMA_INVALID", "path": _pointer((*path, field)),
                 "message": "required native field missing", "validator": "required"}
                for field in error.validator_value if field not in error.instance]
    return [{"code": "OPENING_SETUP_SCHEMA_INVALID", "path": _pointer(path),
             "message": ("physical position must match exactly one declared kind and its fields"
                         if error.validator == "oneOf" else error.message),
             "validator": error.validator}]


def _container_findings(document: Any, bindings: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(document, dict) or not isinstance(document.get("props"), dict):
        return []
    declared, states = bindings["props"], document["props"]
    findings, graph = [], {}
    for identifier, state in states.items():
        if identifier not in declared or not isinstance(state, dict) or state.get("kind") != "prop":
            continue
        container = state.get("container_prop_id")
        path = _pointer(("props", identifier, "container_prop_id"))
        if not isinstance(container, str) or container not in declared or container not in states:
            findings.append({"code": "OPENING_SETUP_CONTAINER_UNKNOWN", "path": path,
                             "message": "container must be an existing declared prop"})
        elif container == identifier:
            findings.append({"code": "OPENING_SETUP_CONTAINER_SELF", "path": path,
                             "message": "a prop cannot contain or support itself"})
        elif not isinstance(states[container], dict) or states[container].get("kind") == "absent":
            findings.append({"code": "OPENING_SETUP_CONTAINER_ABSENT", "path": path,
                             "message": "a container must be present in the same opening"})
        else:
            graph[identifier] = container
    completed, reported = set(), set()
    for start in graph:
        trail, positions = [], {}
        current = start
        while current in graph and current not in completed:
            if current in positions:
                cycle = trail[positions[current]:]
                identity = frozenset(cycle)
                if identity not in reported:
                    findings.append({"code": "OPENING_SETUP_CONTAINER_CYCLE",
                        "path": _pointer(("props", current, "container_prop_id")),
                        "message": "container positions must not form a directed cycle",
                        "cycle_prop_ids": [*cycle, current]})
                    reported.add(identity)
                break
            positions[current] = len(trail)
            trail.append(current)
            current = graph[current]
        completed.update(trail)
    return findings


def diagnose(document: Any, goal: dict[str, Any]) -> dict[str, Any]:
    try:
        bindings, schema = _bindings(goal), build_schema(goal)
    except OpeningSetupContractError as exc:
        return {"valid": False, "findings": [{"code": exc.code, "detail": deepcopy(exc.detail)}],
                "native_document_modified": False, "native_goal_modified": False,
                "semantic_quality_approved": False}
    findings = []
    for error in Draft202012Validator(schema).iter_errors(document):
        findings.extend(_schema_findings(error))
        # The oneOf error alone hides the useful wrong field in a format repair.
        if error.validator == "oneOf" and isinstance(error.instance, dict):
            path = tuple(error.absolute_path)
            if len(path) == 2 and path[0] == "props" and path[1] in bindings["props"]:
                branches = _position_branches(path[1], bindings)
                kind = error.instance.get("kind")
                if isinstance(kind, str) and kind in branches:
                    for child in Draft202012Validator(branches[kind]).iter_errors(error.instance):
                        findings.extend(_schema_findings(child, path))
    findings.extend(_container_findings(document, bindings))
    findings.sort(key=lambda row: (row.get("path", ""), row["code"], row.get("message", "")))
    return {"valid": not findings, "findings": findings,
            "native_document_modified": False, "native_goal_modified": False,
            "semantic_quality_approved": False,
            "limitations": ["Typed positions do not prove consistency of free-text locations or future events.",
                            "No current holder or support is inferred from ownership or Chinese prose.",
                            "Container availability and cycle validation are local; request Schema is not a server guarantee."]}


def validate(document: dict[str, Any], goal: dict[str, Any]) -> dict[str, Any]:
    diagnosis = diagnose(document, goal)
    if not diagnosis["valid"]:
        raise OpeningSetupContractError(diagnosis["findings"][0]["code"], diagnosis)
    return deepcopy(document)


def project_legacy_prop_states(document: dict[str, Any], goal: dict[str, Any]) -> list[dict[str, Any]]:
    """Pure explicit-ID mapping to legacy scene/prop/actor support atoms.

    Nested props are supported by the declared container, not held by its
    owner or its container's actor.  Native mode and all native state fields
    are retained in expected_state.  No absent prop obtains physical atoms.
    """
    native = validate(document, goal)
    result = []
    for prop in goal["whole_plan"]["props"]:
        identifier, state = prop["id"], native["props"][prop["id"]]
        kind = state["kind"]
        holder = state["actor_id"] if kind == "actor" else None
        reference = {"actor": "actor_id", "scene": "scene_id", "prop": "container_prop_id"}
        support = {"entity_type": kind, "entity_id": state[reference[kind]]} if kind != "absent" else None
        result.append({"id": identifier,
            "expected_state": json.dumps(state, ensure_ascii=False, separators=(",", ":")),
            "holder_character_id": holder, "support": support,
            "location": state["location"] if kind != "absent" else None,
            "orientation": state["orientation"] if kind != "absent" else None,
            "presence_at_start": "absent" if kind == "absent" else "present",
            "owner_character_id": prop["owner_character_id"], "anchor": None, "facing": None})
    return result
