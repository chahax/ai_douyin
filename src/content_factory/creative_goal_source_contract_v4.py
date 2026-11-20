"""Independent static whole-plan contract, without opening prop state.

Origin aliases are exact catalog keys. Physical checks use declared atoms, not
guesses about Chinese prose. Honest provenance and dramatic effectiveness still
require a separate same-source semantic review.
"""
from __future__ import annotations

from copy import deepcopy
from collections.abc import Iterable
from typing import Any

from jsonschema import Draft202012Validator

from . import creative_goal_source_contract_v2 as prior

VERSION = "creative_goal_source_v4"
CLAIM_KINDS = prior.CLAIM_KINDS
GOAL_PLANNING_RULE = prior.GOAL_PLANNING_RULE + """
origin_ids只使用所给origin_catalog的精确短编号；原ID、来源路径与适用条件由目录提供，不能猜号或模糊匹配。
非推断claim的basis_claim_refs可省略；inference必须提交非空且有效的claim前提。
creative_choice和inference无外部来源时可省略origin_ids，省略只表示没有外部来源；其他kind必须提交非空准确来源。
道具在整片规划仅登记id、description、owner_character_id；owner只表示概念所有权，
不在道具清单填写存在、当前持有、支撑、位置、朝向或初态。未来引入道具的机制放在事件beats。
人物明确initial_state保留原文，不允许开场状态阶段为了迁就正文而更换这些人物位置。
开场道具状态另由完整原生setup提交，再与本计划SHA绑定；程序不从描述猜测当前状态。
人物数量遵守请求Schema中的输入上限；必要的strategy、stimulus、response、场内变化不能省略。
返修读取完整错误列表，提交完整新计划；不得把遗漏字段由本地补进原生稿。"""


class GoalContractError(ValueError):
    def __init__(self, code: str, detail: Any):
        self.code, self.detail = code, deepcopy(detail)
        super().__init__(code + ": " + str(detail))


def _pointer(parts):
    return "/" + "/".join(str(part).replace("~", "~0").replace("/", "~1") for part in parts) if parts else "$"


def _max_characters(max_characters, preferences=None):
    if preferences is not None and not isinstance(preferences, dict):
        raise GoalContractError("GOAL_PREFERENCE_INVALID", {"path": "/preferences", "message": "preferences must be an object"})
    configured = (preferences or {}).get("max_characters")
    if max_characters is not None and configured is not None and max_characters != configured:
        raise GoalContractError("GOAL_PREFERENCE_INVALID", {"path": "/preferences/max_characters", "message": "explicit and input limits differ"})
    value = max_characters if max_characters is not None else configured if configured is not None else 4
    if type(value) is not int or not 1 <= value <= 4:
        raise GoalContractError("GOAL_PREFERENCE_INVALID", {"path": "/preferences/max_characters", "message": "max_characters must be an integer from one to four"})
    return value


def _catalog_sets(origin_catalog):
    """The context builder's grouped catalog; no fuzzy or positional aliases."""
    if not isinstance(origin_catalog, dict) or set(origin_catalog) != {"platform_metadata", "verified_legal", "user"}:
        raise GoalContractError("GOAL_SOURCE_CATALOG_INVALID", {"path": "/origin_catalog", "message": "expected platform_metadata/verified_legal/user groups"})
    result = {kind: set() for kind in CLAIM_KINDS[:4]}
    seen = set()
    for group, rows in origin_catalog.items():
        if not isinstance(rows, dict):
            raise GoalContractError("GOAL_SOURCE_CATALOG_INVALID", {"path": _pointer(("origin_catalog", group)), "message": "catalog group must be an object"})
        for alias, entry in rows.items():
            path = _pointer(("origin_catalog", group, alias))
            if not isinstance(alias, str) or not alias.strip() or alias in seen or not isinstance(entry, dict):
                raise GoalContractError("GOAL_SOURCE_CATALOG_INVALID", {"path": path, "message": "blank/duplicate alias or malformed entry"})
            if not isinstance(entry.get("original_id"), str) or not entry["original_id"].strip() or not isinstance(entry.get("path"), str) or not entry["path"].strip():
                raise GoalContractError("GOAL_SOURCE_CATALOG_INVALID", {"path": path, "message": "exact original ID and source path are required"})
            if group == "user":
                kind = entry.get("authority")
                if kind not in ("user_constraint", "user_audience_goal"):
                    raise GoalContractError("GOAL_SOURCE_CATALOG_INVALID", {"path": path + "/authority", "message": "user authority kind is not explicit"})
            else:
                kind = group
            result[kind].add(alias)
            seen.add(alias)
    return result


def build_goal_request_schema(*, max_characters=None, origin_catalog=None, preferences=None):
    schema = deepcopy(prior.build_goal_request_schema())
    schema["properties"]["contract_version"] = {"const": VERSION}
    claims = schema["properties"]["claims"]["items"]
    claims["required"].remove("basis_claim_refs")
    claims["required"].remove("origin_ids")
    claims["allOf"][0]["then"]["required"] = ["origin_ids"]
    claims["properties"]["basis_claim_refs"]["description"] = "Optional for non-inference claims; if supplied, every referenced claim must exist."
    claims["allOf"][-1]["then"]["required"] = ["basis_claim_refs"]
    if origin_catalog is not None:
        catalogs = _catalog_sets(origin_catalog)
        all_aliases = sorted(set().union(*catalogs.values()))
        claims["properties"]["origin_ids"]["items"] = {"enum": all_aliases} if all_aliases else False
        for kind in CLAIM_KINDS[:4]:
            ids = sorted(catalogs[kind])
            claims["allOf"].append({"if": {"properties": {"kind": {"const": kind}}},
                                    "then": {"properties": {"origin_ids": {"items": {"enum": ids} if ids else False}}}})
    plan = schema["properties"]["whole_plan"]["properties"]
    plan["characters"]["maxItems"] = _max_characters(max_characters, preferences)
    original_prop = plan["props"]["items"]["properties"]
    plan["props"]["items"] = prior._obj({key: deepcopy(original_prop[key])
                                        for key in ("id", "description", "owner_character_id")})
    Draft202012Validator.check_schema(schema)
    return schema


def diagnose_goal_document(document, *, source_ids: Iterable[str] = (), legal_ids: Iterable[str] = (),
                           user_constraint_ids: Iterable[str] = (), max_characters=None,
                           origin_catalog=None, preferences=None):
    """Collect every safely decidable error with actual JSON paths, never fix it."""
    findings, seen = [], set()
    def add(code, path, message, **details):
        identity = (code, path, message)
        if identity not in seen:
            findings.append({"code": code, "path": path, "message": message, **deepcopy(details)})
            seen.add(identity)

    try:
        schema = build_goal_request_schema(max_characters=max_characters, origin_catalog=origin_catalog, preferences=preferences)
    except GoalContractError as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        add(exc.code, detail.get("path", "$"), detail.get("message", str(exc)))
        schema = build_goal_request_schema()
    for error in Draft202012Validator(schema).iter_errors(document):
        if error.validator == "required" and isinstance(error.instance, dict):
            for missing in error.validator_value:
                if missing not in error.instance:
                    add("GOAL_SCHEMA_INVALID", _pointer((*error.absolute_path, missing)), "required native field missing", validator="required")
        else:
            add("GOAL_SCHEMA_INVALID", _pointer(error.absolute_path), error.message, validator=error.validator)

    catalogs = {}
    for kind, values, label in (("platform_metadata", source_ids, "source_ids"),
                                ("verified_legal", legal_ids, "legal_ids"),
                                ("user_constraint", user_constraint_ids, "user_constraint_ids")):
        try:
            catalogs[kind] = prior._external_ids(values, label)
        except (prior.GoalContractError, TypeError) as exc:
            add("GOAL_SOURCE_CATALOG_INVALID", "/" + label, str(exc))
            catalogs[kind] = set()
    catalogs["user_audience_goal"] = set(catalogs["user_constraint"])
    if origin_catalog is not None:
        try:
            explicit = _catalog_sets(origin_catalog)
            for kind in ("platform_metadata", "verified_legal"):
                if catalogs[kind] and catalogs[kind] != explicit[kind]:
                    add("GOAL_SOURCE_CATALOG_INVALID", "/origin_catalog/" + kind, "catalog aliases differ from exact supplied source IDs")
            if catalogs["user_constraint"] and catalogs["user_constraint"] != explicit["user_constraint"] | explicit["user_audience_goal"]:
                add("GOAL_SOURCE_CATALOG_INVALID", "/origin_catalog/user", "user aliases differ from exact supplied user IDs")
            catalogs = explicit
        except GoalContractError as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            add(exc.code, detail.get("path", "/origin_catalog"), detail.get("message", str(exc)))
    namespace_groups = [catalogs["platform_metadata"], catalogs["verified_legal"],
                        catalogs["user_constraint"] | catalogs["user_audience_goal"]]
    if any(namespace_groups[a] & namespace_groups[b] for a in range(3) for b in range(a + 1, 3)):
        add("GOAL_SOURCE_CATALOG_INVALID", "/origin_catalog", "authority namespaces overlap")

    def rows(value, path):
        indexed, positions = {}, {}
        if not isinstance(value, list):
            return indexed, positions, []
        safe = []
        for i, row in enumerate(value):
            if not isinstance(row, dict):
                continue
            safe.append((i, row))
            identifier = row.get("id")
            if not isinstance(identifier, str) or not identifier.strip():
                continue
            if identifier in indexed:
                add("GOAL_DUPLICATE_ID", _pointer((*path, i, "id")), "duplicate native ID", duplicate_id=identifier,
                    first_path=_pointer((*path, positions[identifier], "id")))
            else:
                indexed[identifier], positions[identifier] = row, i
        return indexed, positions, safe

    def ref_values(value):
        return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []

    def require_refs(value, ids, path):
        if not isinstance(value, list):
            return
        for i, identifier in enumerate(value):
            if isinstance(identifier, str) and identifier not in ids:
                add("GOAL_REFERENCE_UNKNOWN", _pointer((*path, i)), "unknown exact reference", reference=identifier)

    def cycles(edges, paths):
        visiting, done, stack = set(), set(), []
        def visit(item):
            if item in visiting:
                cycle = stack[stack.index(item):]
                for member in cycle:
                    add("GOAL_REFERENCE_CYCLE", paths[member], "reference cycle", cycle=cycle)
                return
            if item in done:
                return
            visiting.add(item)
            stack.append(item)
            for parent in edges.get(item, []):
                if parent in edges:
                    visit(parent)
            stack.pop()
            visiting.remove(item)
            done.add(item)
        for item in edges:
            visit(item)

    if not isinstance(document, dict):
        return {"valid": False, "findings": findings, "native_document_modified": False, "semantic_quality_approved": False}
    claims, claim_positions, claim_rows = rows(document.get("claims"), ("claims",))
    claim_ids, covered_user = set(claims), set()
    for index, claim in claim_rows:
        kind = claim.get("kind")
        origin = claim.get("origin_ids")
        if isinstance(kind, str) and kind in catalogs and isinstance(origin, list):
            for j, identifier in enumerate(origin):
                if isinstance(identifier, str) and identifier not in catalogs[kind]:
                    add("GOAL_ORIGIN_CLASS_MISMATCH", _pointer(("claims", index, "origin_ids", j)), "origin is not in the declared authority class", kind=kind, reference=identifier)
            if kind in ("user_constraint", "user_audience_goal"):
                covered_user.update(set(ref_values(origin)) & catalogs[kind])
        require_refs(claim.get("basis_claim_refs"), claim_ids, ("claims", index, "basis_claim_refs"))
    missing_user = (catalogs["user_constraint"] | catalogs["user_audience_goal"]) - covered_user
    if missing_user:
        add("GOAL_USER_REQUIREMENT_UNCOVERED", "/claims", "selected user requirements are not represented", missing_origin_ids=sorted(missing_user))
    cycles({identifier: ref_values(row.get("basis_claim_refs")) for identifier, row in claims.items()},
           {identifier: _pointer(("claims", claim_positions[identifier], "basis_claim_refs")) for identifier in claims})

    plan = document.get("whole_plan")
    if not isinstance(plan, dict):
        return {"valid": not findings, "findings": findings, "native_document_modified": False, "semantic_quality_approved": False}
    characters, char_positions, char_rows = rows(plan.get("characters"), ("whole_plan", "characters"))
    scenes, scene_positions, scene_rows = rows(plan.get("scenes"), ("whole_plan", "scenes"))
    props, prop_positions, prop_rows = rows(plan.get("props"), ("whole_plan", "props"))
    beats, beat_positions, beat_rows = rows(plan.get("beats"), ("whole_plan", "beats"))
    entities = [(characters, char_positions, "characters"), (scenes, scene_positions, "scenes"), (props, prop_positions, "props")]
    for group, positions, label in entities:
        for identifier in group:
            if sum(identifier in other for other, _, _ in entities) > 1:
                add("GOAL_ENTITY_ID_COLLISION", _pointer(("whole_plan", label, positions[identifier], "id")),
                    "character, scene and prop identity namespaces overlap", entity_id=identifier)
    for index, actor in char_rows:
        state = actor.get("initial_state")
        if isinstance(state, dict) and isinstance(state.get("scene_id"), str) and state["scene_id"] not in scenes:
            add("GOAL_REFERENCE_UNKNOWN", _pointer(("whole_plan", "characters", index, "initial_state", "scene_id")), "unknown scene", reference=state["scene_id"])
    for index, prop in prop_rows:
        path = ("whole_plan", "props", index)
        owner = prop.get("owner_character_id")
        if isinstance(owner, str) and owner not in characters:
            add("GOAL_REFERENCE_UNKNOWN", _pointer((*path, "owner_character_id")),
                "unknown declared owner", reference=owner)

    strategy_effects = []
    for index, beat in beat_rows:
        path = ("whole_plan", "beats", index)
        for field, known in (("scene_id", scenes), ("actor_id", characters)):
            if isinstance(beat.get(field), str) and beat[field] not in known:
                add("GOAL_REFERENCE_UNKNOWN", _pointer((*path, field)), "unknown declared identity", reference=beat[field])
        references = ref_values(beat.get("claim_refs"))
        require_refs(beat.get("claim_refs"), claim_ids, (*path, "claim_refs"))
        if isinstance(beat.get("claim_refs"), list) and all(ref in claims for ref in references) and not any(claims[ref].get("kind") == "creative_choice" for ref in references):
            add("GOAL_DRAMATIC_CHOICE_UNTRACED", _pointer((*path, "claim_refs")), "beat needs a declared creative choice")
        strategy = beat.get("strategy")
        strategy_effects.append(strategy.get("effect") if isinstance(strategy, dict) else None)
    if strategy_effects and all(effect in ("establishes", "maintains", "changes", "abandons") for effect in strategy_effects) and not any(effect in ("changes", "abandons") for effect in strategy_effects):
        add("GOAL_STRATEGY_SHIFT_MISSING", "/whole_plan/beats", "whole plan declares no strategy change")
    audience = plan.get("audience_path")
    if isinstance(audience, dict):
        references = ref_values(audience.get("claim_refs"))
        require_refs(audience.get("claim_refs"), claim_ids, ("whole_plan", "audience_path", "claim_refs"))
        if isinstance(audience.get("claim_refs"), list) and all(ref in claims for ref in references) and not any(claims[ref].get("kind") == "user_audience_goal" for ref in references):
            add("GOAL_AUDIENCE_UNTRACED", "/whole_plan/audience_path/claim_refs", "audience path needs a user audience goal")
    ending = plan.get("ending")
    if isinstance(ending, dict):
        references = ref_values(ending.get("claim_refs"))
        require_refs(ending.get("claim_refs"), claim_ids, ("whole_plan", "ending", "claim_refs"))
        require_refs(ending.get("evidence_beat_ids"), set(beats), ("whole_plan", "ending", "evidence_beat_ids"))
        if isinstance(ending.get("claim_refs"), list) and all(ref in claims for ref in references) and not any(claims[ref].get("kind") == "creative_choice" for ref in references):
            add("GOAL_DRAMATIC_CHOICE_UNTRACED", "/whole_plan/ending/claim_refs", "ending needs a declared creative choice")
        listed = plan.get("beats")
        if isinstance(listed, list) and listed and isinstance(listed[-1], dict) and isinstance(listed[-1].get("id"), str) and isinstance(ending.get("evidence_beat_ids"), list) and listed[-1]["id"] not in ending["evidence_beat_ids"]:
            add("GOAL_ENDING_UNTRACED", "/whole_plan/ending/evidence_beat_ids", "final beat is absent from the ending evidence")
    findings.sort(key=lambda row: (row["path"], row["code"], row["message"]))
    return {"valid": not findings, "findings": findings, "native_document_modified": False,
            "semantic_quality_approved": False,
            "limitations": ["No natural-language state or source semantics inferred; semantic audit remains required.",
                            "Checks whose necessary fields are malformed or missing cannot establish additional semantic facts."]}


def validate_goal_document(document, *, source_ids: Iterable[str] = (), legal_ids: Iterable[str] = (),
                           user_constraint_ids: Iterable[str] = (), max_characters=None,
                           origin_catalog=None, preferences=None):
    diagnosis = diagnose_goal_document(document, source_ids=source_ids, legal_ids=legal_ids,
        user_constraint_ids=user_constraint_ids, max_characters=max_characters,
        origin_catalog=origin_catalog, preferences=preferences)
    if not diagnosis["valid"]:
        raise GoalContractError(diagnosis["findings"][0]["code"], diagnosis)
    return deepcopy(document)


def build_user_goal_contract():
    document = prior.build_user_goal_contract()
    document["contract_version"] = VERSION + "/user_goals"
    return document
