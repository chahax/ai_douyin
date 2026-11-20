"""Independent review contract with descriptive turn labels and native witnesses.

The v3 state/order checks remain in force.  This module does not run the v3
response schema, rewrite evidence, infer physical states, or accept old reviews.
When a native opening setup is supplied, every initial witness is additionally
bound to that exact object and its unchanged compiler projection.
"""
from __future__ import annotations

from copy import deepcopy
import json

from jsonschema import Draft202012Validator, ValidationError

from . import creative_full_review_contract_v3 as base

VERSION = "creative_full_review_contract/v4"
GOAL_FIELDS = base.GOAL_FIELDS
STATE_KEYS = base.STATE_KEYS
coverage_specification = base.coverage_specification
REVIEW_RULE = base.REVIEW_RULE + (
    "turn_function是说明性文字：描述此句对听者所做的沟通行为，不是接受路由的分类枚举；"
    "必须实质非空，陈述、告知或复合言语行为也可如实描述。"
    "先找反例再判定；符合规划或摘要不能替代正文中的行为和可见结果。"
    "复合动作中每项必要前提、派生纸页、副本形成及去向、容器关闭与再取物都须检查。"
    "initial_evidence_catalog来自同一原生开场状态；前提quote逐字引用其对应初态或更早E原句，"
    "不得引用当前动作来证明当前动作之前已具备的条件，也不将所需状态当作实际状态。"
    "初态没有明示的状态原子不能据位置引文填成确定值；开合null或在场unknown不能支持pass，"
    "未证实的前提填actual_value=null并判unknown或fail，不能为通过补写初态。"
)


def _initial_rows(brief):
    rows = {}
    for kind, field in (("character", "character_states"), ("prop", "prop_states")):
        for row in brief["initial_state"][field]:
            key = "initial:" + kind + ":" + row["id"]
            if key in rows:
                raise ValueError("duplicate initial entity in compiler projection")
            rows[key] = row
    return rows


def initial_evidence_catalog(brief, opening_setup=None):
    """Expose exact initial source objects, never words extracted from actions.

    The optional fallback preserves the API for existing offline fixtures. Live
    callers should supply the native setup; its fields and JSON-valued
    expected_state projections are compared without normalizing their prose.
    """
    rows = _initial_rows(brief)
    if opening_setup is None:
        return {key: {"entity_id": row["id"], "origin": "compiled_native_brief_projection",
                      "path": "/initial_state/" + ("character_states" if key.startswith("initial:character:") else "prop_states"),
                      "value": deepcopy(row)} for key, row in rows.items()}
    if not isinstance(opening_setup, dict):
        raise ValueError("opening setup must be the complete native JSON object")
    for kind, field in (("character", "characters"), ("prop", "props")):
        source = opening_setup.get(field)
        expected = {row["id"] for key, row in rows.items() if key.startswith("initial:" + kind + ":")}
        if not isinstance(source, dict) or set(source) != expected:
            raise ValueError("native setup and compiler initial entity coverage differ")
    catalog = {}
    for key, row in rows.items():
        field = "characters" if key.startswith("initial:character:") else "props"
        native = opening_setup[field][row["id"]]
        if not isinstance(native, dict):
            raise ValueError("native initial entity must be a JSON object")
        try:
            projected = json.loads(row["expected_state"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("native setup projection must preserve the original JSON state") from exc
        if base.prior.digest(projected) != base.prior.digest(native):
            raise ValueError("compiler initial projection differs from the native setup")
        catalog[key] = {"entity_id": row["id"], "origin": "native_opening_setup_document",
                        "path": "/" + field + "/" + row["id"], "value": deepcopy(native)}
    return catalog


def _source_fragments(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [json.dumps(value, ensure_ascii=False, separators=(",", ":"))] + [
            fragment for child in value.values() for fragment in _source_fragments(child)]
    if isinstance(value, list):
        return [fragment for child in value for fragment in _source_fragments(child)]
    return []


def _native_initial_atoms(source):
    """Only explicit values and typed placement relations, never Chinese NLP."""
    native = source["value"]
    atoms = {key: native[key] for key in ("posture", "location", "holder_character_id", "open", "presence")
             if key in native}
    kind = native.get("kind")
    if kind in ("actor", "scene", "prop", "absent"):
        atoms["presence"] = "absent" if kind == "absent" else "present"
        atoms["holder_character_id"] = native["actor_id"] if kind == "actor" else None
        reference = {"actor": "actor_id", "scene": "scene_id", "prop": "container_prop_id"}
        atoms["support_entity_id"] = native[reference[kind]] if kind != "absent" else None
        if kind == "absent":
            atoms["location"] = None
    elif "presence_at_start" in native:
        atoms["presence"] = native["presence_at_start"]
    return atoms


def build_review_schema(script, brief, plan, legal_context, *, goal_contract=None, opening_setup=None):
    initial_evidence_catalog(brief, opening_setup)
    if opening_setup is not None and goal_contract is not None:
        if opening_setup.get("goal_sha256") != base.prior.digest(goal_contract):
            raise ValueError("native opening setup belongs to a different complete goal")
    schema = base.build_review_schema(script, brief, plan, legal_context, goal_contract=goal_contract)

    def change_label(node):
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict) and "turn_function" in properties:
                properties["turn_function"] = {"type": "string", "minLength": 1, "pattern": r"\S",
                    "description": "Descriptive communication act; never an acceptance or routing enum."}
            for child in node.values():
                change_label(child)
        elif isinstance(node, list):
            for child in node:
                change_label(child)

    # Standard shared definitions also contain row schemas. The frozen v3
    # builder is reused, but neither its enum nor its response validator runs.
    change_label(schema)
    schema["properties"]["schema"] = {"const": VERSION}
    schema["properties"]["opening_setup_sha256"] = {
        "const": base.prior.digest(opening_setup) if opening_setup is not None else None}
    schema["required"] = list(schema["properties"])
    Draft202012Validator.check_schema(schema)
    return schema


def _validate_extra(document, script, brief, *, opening_setup=None):
    catalog = initial_evidence_catalog(brief, opening_setup)
    for row in document["dialogue_checks"].values():
        if not row["turn_function"].strip():
            raise ValueError("descriptive turn function cannot be whitespace")
    if opening_setup is not None:
        for row in document["action_checks"].values():
            for condition in row["preconditions"]:
                origin = condition["established_by"]
                if origin in catalog:
                    source = catalog[origin]
                    quote = condition["quote"]
                    if (source["entity_id"] != condition["entity_id"] or not quote.strip()
                            or not any(quote in fragment for fragment in _source_fragments(source["value"]))):
                        raise ValueError("initial-state witness must quote the same native setup entity")
                    atoms = _native_initial_atoms(source)
                    state_key = condition["state_key"]
                    if state_key not in atoms:
                        if row["status"] == "pass" or condition["actual_value"] is not None:
                            raise ValueError("initial-state witness does not explicitly establish this native setup atom")
                        continue
                    if not base._same_value(atoms[state_key], condition["actual_value"]):
                        raise ValueError("initial-state actual value contradicts an explicit native setup atom")
                    value = atoms[state_key]
                    unknown = ((state_key == "open" and value is None)
                               or (state_key == "presence" and value in (None, "unknown"))
                               or (state_key in ("posture", "location") and value is None
                                   and source["value"].get("kind") != "absent"))
                    if row["status"] == "pass" and unknown:
                        raise ValueError("unknown native setup atom cannot establish a passing precondition")
    # Earlier/current/future ordering, exact reported state values and quote
    # provenance were already present in v3; preserve those checks unchanged.
    base._validate_extra(document, script, brief)


def validate_full_review(document, script, brief, plan, legal_context, *, goal_contract=None, opening_setup=None):
    """Closed identity and content decisions; turn labels carry no authority."""
    if not isinstance(document, dict):
        return base._error("REVIEW_SCHEMA_INVALID", "full review must be a JSON object")
    if document.get("dialogue_checks") in ([], {}) and coverage_specification(script, brief, plan)["dialogue_checks"]:
        return base._error("DIALOGUE_COVERAGE_EMPTY", "all actual dialogue references require one review row", "dialogue_checks")
    try:
        schema = build_review_schema(script, brief, plan, legal_context,
                                     goal_contract=goal_contract, opening_setup=opening_setup)
        Draft202012Validator(schema).validate(document)
        legacy = base._legacy_document(document)
        legacy.pop("opening_setup_sha256")
        validation = base.prior.validate_review(legacy, script, brief, plan, legal_context)
        _validate_extra(document, script, brief, opening_setup=opening_setup)
    except ValidationError as exc:
        return base._error("REVIEW_SCHEMA_INVALID", exc.message, "/".join(str(part) for part in exc.absolute_path))
    except (ValueError, KeyError, TypeError) as exc:
        return base._error("REVIEW_EVIDENCE_INVALID", str(exc))
    decision = base.prior.decide_review(legacy, script, brief, plan, legal_context)
    findings, uncertainties = list(decision["revision_requirements"]), list(decision["uncertainties"])
    for table in ("action_checks", "goal_checks"):
        for identifier, row in document[table].items():
            item = {"target": "script", "table": table, "item_id": identifier, "finding": deepcopy(row)}
            if row["status"] == "fail":
                findings.append(item)
            elif row["status"] == "unknown":
                uncertainties.append(item)
    if decision["status"].startswith(("halt_same_story", "halt_prior_story")):
        status = decision["status"]
    else:
        status = "halt_review_uncertain" if uncertainties else "needs_whole_revision" if findings else "text_ready_for_director"
    return {"valid": True, "accepted": status == "text_ready_for_director", "status": status,
            "findings": findings, "uncertainties": uncertainties, "validation": validation,
            "semantic_review_is_model_judgement": True, "native_initial_projection_verified": opening_setup is not None,
            "human_quality_approved": False, "creative_quality_passed": False, "old_budget_reset": False}
