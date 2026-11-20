"""A source-bound full review contract, without clients or creative rewriting.

Keyed coverage is compiled once for the request and local validator.  State
witnesses check reported assertions; they do not infer states from prose or
prove that a reviewing model understood the screenplay correctly.
"""
from __future__ import annotations

from copy import deepcopy
from collections import Counter
import json

from jsonschema import Draft202012Validator, ValidationError

from . import creative_fresh_legal_text_pipeline_v1 as prior

VERSION = "creative_full_review_contract/v2"
GOAL_FIELDS = ("concrete_pursuit", "opposition_tactic_change", "emotional_change", "local_consequence")
STATE_KEYS = ("posture", "holder_character_id", "open", "support_entity_id", "location")
REVIEW_RULE = (
    "全文审查当前原生brief、plan、完整正文和用户创作目标。证据只来自正文steps的真实E编号和原文；"
    "摘要、trigger与event不能补演出。全部覆盖表按Schema规定的ID键返回，每键一次，不能空表代替逐句审查。"
    "逐句话轮说清对眼前听者采取的行动、承接的刺激及实际后续反应；职业用词不是禁词，不强造金句。"
    "逐动作检查必要前提，初态取第一次实际行为之前；坐下邀请不等于已坐下，所有权不等于当前持有。"
    "仅报告有原文支持的必要状态原子，不填逐秒动作、朝向或肌肉清单。前提引用首次起态或更早动作，"
    "后来动作不能倒填早期起态；合上后再合上、站着直接起身、桌上物品无取回直接在手中应明确失败。"
    "状态推断无法确定填unknown，不用pass隐藏。既有事实、独立法律来源和次序要求全部复核。"
    "四个场内功能独立检查：具体诉求、真实阻力与策略变化、刺激后的情绪改变、本次交锋的可见局部后果。"
    "法律争议可以开放，不等于人物本场没有选择、回应或后果；沉默可以承担功能但须有实际因果证据。"
    "每个pass提供当前原文证据；fail指出问题及完整新稿/新计划的返修目标，不代写台词，unknown停止。"
    "只报告文本证据，不声称人工审美或视频通过。Schema是请求合同，不是服务端强制生成保障。"
)

_COVERAGE_KEYS = {
    "plan_support": "plan_item_id", "fact_checks": "fact_id", "initial_checks": "initial_id",
    "observed_prop_initial": "prop_id", "literal_events": "source_ref", "obligations": "obligation_id",
    "order_checks": "order_id", "dialogue_checks": "dialogue_ref", "criteria": "criterion", "ending_checks": "field",
}


def _obj(fields):
    return {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}


def _refs(refs, minimum=0):
    return {"type": "array", "items": {"enum": list(refs)} if refs else False,
            "minItems": minimum, "uniqueItems": True}


def coverage_specification(script, brief, plan):
    """Authoritative identifiers for both outbound schema and inbound checks."""
    entries = prior.contract.evidence_catalog(script)
    return {
        "plan_support": prior.plan_review_ids(plan),
        "fact_checks": [row["id"] for row in brief["facts"]],
        "initial_checks": [kind + ":" + row["id"] for kind, key in
                           (("character", "character_states"), ("prop", "prop_states"))
                           for row in brief["initial_state"][key]],
        "observed_prop_initial": [row["id"] for row in brief["initial_state"]["prop_states"]],
        "literal_events": list(entries),
        "obligations": [row["id"] for row in plan["source_obligations"]],
        "order_checks": [row["before_id"] + ">" + row["after_id"] for row in plan["source_order"]],
        "dialogue_checks": [ref for ref, row in entries.items() if row["kind"] == "dialogue"],
        "criteria": list(prior.CRITERIA),
        "ending_checks": ["attempt_result", "visible_consequence", "open_problem"],
        "action_checks": [ref for ref, row in entries.items() if row["kind"] == "action"],
        "goal_checks": list(GOAL_FIELDS),
    }


def _initial_catalog(brief):
    return {"initial:" + kind + ":" + row["id"]: row
            for kind, key in (("character", "character_states"), ("prop", "prop_states"))
            for row in brief["initial_state"][key]}


def _judgement(refs):
    return _obj({"status": deepcopy(prior.STATUS), "source_refs": _refs(refs),
                 "reason": deepcopy(prior.TEXT), "required_revision": {"type": "string"}})


def _compact_schema(schema):
    """Share repeated schema subtrees, never property-name dictionaries.

    This is standard local JSON Schema, not a claim about provider enforcement.
    The exact outgoing tool parameters still require a later live acceptance.
    """
    counts, originals = Counter(), {}
    keywords = {"type", "enum", "const", "properties", "items", "anyOf", "allOf", "$ref"}

    def key(node):
        return json.dumps(node, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def count(node):
        if isinstance(node, dict):
            if keywords.intersection(node):
                identity = key(node)
                if len(identity) >= 180:
                    counts[identity] += 1
                    originals[identity] = node
            for value in node.values():
                count(value)
        elif isinstance(node, list):
            for value in node:
                count(value)

    count(schema)
    names = {identity: "shared_" + str(i + 1).zfill(3)
             for i, identity in enumerate(sorted(identity for identity, n in counts.items() if n > 1))}
    if not names:
        return schema

    def replace(node, *, skip=None):
        if isinstance(node, dict):
            if keywords.intersection(node):
                identity = key(node)
                if identity in names and identity != skip:
                    return {"$ref": "#/$defs/" + names[identity]}
            return {field: replace(value) for field, value in node.items()}
        if isinstance(node, list):
            return [replace(value) for value in node]
        return node

    compact = replace(schema)
    compact["$defs"] = {name: replace(originals[identity], skip=identity) for identity, name in names.items()}
    return compact


def build_review_schema(script, brief, plan, legal_context, *, goal_contract=None):
    schema = deepcopy(prior.review_schema(script, brief, plan, legal_context))
    fields = schema["properties"]
    coverage = coverage_specification(script, brief, plan)
    entries = prior.contract.evidence_catalog(script)
    refs, actions = list(entries), coverage["action_checks"]
    for table, key in _COVERAGE_KEYS.items():
        row_schema = deepcopy(fields[table]["items"])
        row_schema["properties"].pop(key)
        row_schema["required"].remove(key)
        if table == "literal_events":
            # Each source-bound schema fixes kind and speaker, rather than an
            # enum that permits one source to be replaced by another actor.
            keyed = {}
            for ref in coverage[table]:
                item = deepcopy(row_schema)
                item["properties"]["kind"] = {"const": entries[ref]["kind"]}
                item["properties"]["speaker"] = {"const": entries[ref]["speaker"]}
                keyed[ref] = item
            fields[table] = _obj(keyed)
        else:
            fields[table] = _obj({ref: deepcopy(row_schema) for ref in coverage[table]})
    for ref, item in fields["dialogue_checks"]["properties"].items():
        extra = {
            "turn_function": {"enum": ["request", "refusal", "justification", "pressure", "clarification",
                                        "concession", "evasion", "reassurance", "acknowledgment", "other"]},
            "purpose": deepcopy(prior.TEXT),
            # Shared reference vocabulary keeps the tool schema compact;
            # semantic before/after ordering is checked against the catalog.
            "stimulus_ref": {"enum": [None, *refs]},
            "reaction_refs": _refs(refs),
            "emotional_change": {"type": ["string", "null"], "minLength": 1},
        }
        item["properties"].update(extra)
        item["required"].extend(extra)
    entities = [row["id"] for key in ("character_states", "prop_states") for row in brief["initial_state"][key]]
    scalar = {"type": ["string", "boolean", "number", "null"]}
    atom = {"entity_id": {"enum": entities}, "state_key": {"enum": list(STATE_KEYS)}}
    action_fields = {}
    for ref in actions:
        precondition = _obj({**deepcopy(atom), "expected_value": scalar, "actual_value": scalar,
                            "established_by": {"enum": [*_initial_catalog(brief), *actions]}, "quote": deepcopy(prior.TEXT)})
        change = _obj({**deepcopy(atom), "before": scalar, "after": scalar, "quote": deepcopy(prior.TEXT)})
        item = _judgement(refs)
        extra = {"subjects": _refs(entities, 1),
                 "preconditions": {"type": "array", "items": precondition, "maxItems": 8},
                 "state_changes": {"type": "array", "items": change, "maxItems": 8}}
        item["properties"].update(extra)
        item["required"].extend(extra)
        action_fields[ref] = item
    fields["action_checks"] = _obj(action_fields)
    witness = _obj({"source_ref": {"enum": refs} if refs else False, "quote": deepcopy(prior.TEXT)})
    goal_item = _judgement(refs)
    goal_item["properties"]["evidence"] = {"type": "array", "items": witness, "maxItems": 8}
    goal_item["required"].append("evidence")
    fields["goal_checks"] = _obj({key: deepcopy(goal_item) for key in GOAL_FIELDS})
    fields["schema"] = {"const": VERSION}
    fields["goal_contract_sha256"] = {"const": prior.digest(goal_contract) if goal_contract is not None else None}
    schema["required"] = list(fields)
    compact = _compact_schema(schema)
    Draft202012Validator.check_schema(compact)
    return compact


def _error(code, reason, path=""):
    return {"valid": False, "accepted": False, "findings": [{"code": code, "reason": reason, "path": path}],
            "uncertainties": [], "human_quality_approved": False, "creative_quality_passed": False}


def _same_value(left, right):
    # JSON booleans and numbers are distinct state assertions.
    return type(left) is type(right) and left == right


def _quote(witness, entries):
    quote = witness["quote"]
    if not quote.strip() or quote not in entries[witness["source_ref"]]["quote"]:
        raise ValueError("evidence quote must be an unchanged current step substring")


def _initial_text(row):
    return "\n".join(value for value in row.values() if isinstance(value, str))


def _known_initial(brief):
    known = {}
    for row in brief["initial_state"]["character_states"]:
        for key in ("posture", "location"):
            if row.get(key) is not None:
                known[row["id"], key] = row[key]
    for row in brief["initial_state"]["prop_states"]:
        known[row["id"], "holder_character_id"] = row["holder_character_id"]
        known[row["id"], "support_entity_id"] = row["support"]["entity_id"] if row["support"] else None
    return known


def _check_state_value(atom, value, brief):
    state_key = atom[1]
    actors = {row["id"] for row in brief["initial_state"]["character_states"]}
    entities = actors | {row["id"] for row in brief["initial_state"]["prop_states"]}
    scenes = {row["id"] for row in brief["scenes"]}
    if atom[0] in actors and state_key in ("holder_character_id", "open", "support_entity_id"):
        raise ValueError("prop-only state key cannot be assigned to an actor")
    if atom[0] not in actors and state_key == "posture":
        raise ValueError("actor posture cannot be assigned to a prop")
    if state_key == "holder_character_id" and value is not None and value not in actors:
        raise ValueError("holder state must refer to a declared on-screen character")
    if state_key == "support_entity_id" and value is not None and value not in entities | scenes:
        raise ValueError("support state must refer to a declared entity")
    if state_key == "open" and value is not None and type(value) is not bool:
        raise ValueError("open state must be a boolean or unknown null")
    if state_key in ("posture", "location") and value is not None and not isinstance(value, str):
        raise ValueError("posture/location state must use explicit text or unknown null")


def _validate_extra(document, script, brief):
    entries = prior.contract.evidence_catalog(script)
    refs = list(entries)
    initials = _initial_catalog(brief)
    known = _known_initial(brief)
    changes = {}
    first_use = {}
    for ref in (ref for ref in refs if entries[ref]["kind"] == "action"):
        row = document["action_checks"][ref]
        for entity in row["subjects"]:
            first_use.setdefault(entity, ref)
        if row["status"] == "pass" and ref not in row["source_refs"]:
            raise ValueError("passing action check must include its own actual action reference")
        seen_conditions, seen_changes = set(), set()
        for condition in row["preconditions"]:
            entity = condition["entity_id"]
            atom = (entity, condition["state_key"])
            if entity not in row["subjects"] or atom in seen_conditions:
                raise ValueError("precondition entity must be a checked subject, once per state key")
            seen_conditions.add(atom)
            _check_state_value(atom, condition["expected_value"], brief)
            _check_state_value(atom, condition["actual_value"], brief)
            origin = condition["established_by"]
            if origin in initials:
                if (initials[origin]["id"] != entity or not condition["quote"].strip()
                    or condition["quote"] not in _initial_text(initials[origin])):
                    raise ValueError("initial-state witness must quote the same declared entity")
            else:
                if refs.index(origin) >= refs.index(ref):
                    raise ValueError("action precondition must be established by an earlier actual action")
                _quote({"source_ref": origin, "quote": condition["quote"]}, entries)
                if atom not in changes.get(origin, {}) or not _same_value(changes[origin][atom], condition["actual_value"]):
                    raise ValueError("precondition witness must establish that reported earlier action state")
            if row["status"] == "pass":
                if not _same_value(condition["actual_value"], condition["expected_value"]):
                    raise ValueError("passing action has an unsatisfied reported precondition")
                if atom in known and not _same_value(known[atom], condition["actual_value"]):
                    raise ValueError("passing action precondition contradicts the latest reported state")
        changes[ref] = {}
        for change in row["state_changes"]:
            atom = (change["entity_id"], change["state_key"])
            if change["entity_id"] not in row["subjects"] or atom in seen_changes:
                raise ValueError("state change entity must be a checked subject, once per state key")
            seen_changes.add(atom)
            _check_state_value(atom, change["before"], brief)
            _check_state_value(atom, change["after"], brief)
            _quote({"source_ref": ref, "quote": change["quote"]}, entries)
            if row["status"] == "pass" and atom in known and not _same_value(known[atom], change["before"]):
                raise ValueError("passing state change contradicts its last established before state")
            # Failed/unknown assertions cannot establish a state for a later
            # passing action or silently overwrite earlier known atoms.
            if row["status"] == "pass":
                known[atom] = change["after"]
                changes[ref][atom] = change["after"]
    for table in ("initial_checks", "observed_prop_initial"):
        for initial_id, row in document[table].items():
            entity = initial_id.split(":", 1)[1] if table == "initial_checks" else initial_id
            if row["status"] == "pass" and entity in first_use:
                if first_use[entity] not in row["source_refs"]:
                    raise ValueError("initial-state check must include the first reported entity action")
                if any(refs.index(ref) > refs.index(first_use[entity]) for ref in row["source_refs"]):
                    raise ValueError("later actions cannot repair a passing earliest initial-state check")
    for table in ("action_checks", "goal_checks"):
        for row in document[table].values():
            if row["status"] == "pass" and row["required_revision"]:
                raise ValueError("passing check cannot carry mandatory revision")
            if row["status"] == "fail" and not row["required_revision"].strip():
                raise ValueError("failed check needs a complete revision target")
    for ref, row in document["dialogue_checks"].items():
        if row["status"] == "pass" and ref not in row["source_refs"]:
            raise ValueError("passing dialogue check must include its own actual dialogue reference")
        if not row["purpose"].strip():
            raise ValueError("dialogue purpose cannot be whitespace")
        if row["stimulus_ref"] is not None and refs.index(row["stimulus_ref"]) >= refs.index(ref):
            raise ValueError("dialogue stimulus must precede its actual dialogue step")
        if any(refs.index(reaction) <= refs.index(ref) for reaction in row["reaction_refs"]):
            raise ValueError("dialogue reaction must follow its actual dialogue step")
    for row in document["goal_checks"].values():
        if row["status"] == "pass" and not row["evidence"]:
            raise ValueError("passing scene-goal check requires actual screenplay evidence")
        for witness in row["evidence"]:
            _quote(witness, entries)
            if witness["source_ref"] not in row["source_refs"]:
                raise ValueError("goal witness must be part of its checked current source references")


def _legacy_document(document):
    value = deepcopy(document)
    for table, key in _COVERAGE_KEYS.items():
        value[table] = [{key: identifier, **deepcopy(row)} for identifier, row in value[table].items()]
    for row in value["dialogue_checks"]:
        for key in ("turn_function", "purpose", "stimulus_ref", "reaction_refs", "emotional_change"):
            row.pop(key)
    for key in ("schema", "goal_contract_sha256", "action_checks", "goal_checks"):
        value.pop(key)
    return value


def validate_full_review(document, script, brief, plan, legal_context, *, goal_contract=None):
    """Contract validity and content verdict are deliberately separate."""
    if not isinstance(document, dict):
        return _error("REVIEW_SCHEMA_INVALID", "full review must be a JSON object")
    if document.get("dialogue_checks") in ([], {}) and coverage_specification(script, brief, plan)["dialogue_checks"]:
        return _error("DIALOGUE_COVERAGE_EMPTY", "all actual dialogue references require one review row", "dialogue_checks")
    try:
        Draft202012Validator(build_review_schema(script, brief, plan, legal_context, goal_contract=goal_contract)).validate(document)
        legacy = _legacy_document(document)
        validation = prior.validate_review(legacy, script, brief, plan, legal_context)
        _validate_extra(document, script, brief)
    except ValidationError as exc:
        return _error("REVIEW_SCHEMA_INVALID", exc.message, "/".join(str(part) for part in exc.absolute_path))
    except (ValueError, KeyError, TypeError) as exc:
        return _error("REVIEW_EVIDENCE_INVALID", str(exc))
    decision = prior.decide_review(legacy, script, brief, plan, legal_context)
    findings, uncertainties = list(decision["revision_requirements"]), list(decision["uncertainties"])
    for table in ("action_checks", "goal_checks"):
        for identifier, row in document[table].items():
            item = {"target": "script", "table": table, "item_id": identifier, "finding": deepcopy(row)}
            if row["status"] == "fail":
                findings.append(item)
            elif row["status"] == "unknown":
                uncertainties.append(item)
    if decision["status"].startswith("halt_same_story") or decision["status"].startswith("halt_prior_story"):
        status = decision["status"]
    else:
        status = "halt_review_uncertain" if uncertainties else "needs_whole_revision" if findings else "text_ready_for_director"
    return {"valid": True, "accepted": status == "text_ready_for_director", "status": status,
            "findings": findings, "uncertainties": uncertainties, "validation": validation,
            "semantic_review_is_model_judgement": True, "human_quality_approved": False,
            "creative_quality_passed": False, "old_budget_reset": False}
