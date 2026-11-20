"""Compact native part references, retaining every semantic/physical duty.

Only newly submitted v4 IDs are expanded to unchanged source constants for
validation. Native statuses, findings and counterproof remain model output;
this compiler never adds a judgment or repairs a truncated older response.
"""
from __future__ import annotations

from copy import deepcopy
import re
import unicodedata

from jsonschema import Draft202012Validator, ValidationError

from . import creative_full_review_contract_v5 as reviews

VERSION = "creative_split_full_review_part/v4"
BUNDLE_VERSION = "creative_split_full_review_bundle/v4"
CONSISTENCY_CATALOG_VERSION = "creative_consistency_evidence_catalog/v1"
SEMANTIC_TABLES = ("beat_intent_checks", "dialogue_role_checks")
LEGACY_PART_TABLES = {
    "semantic": ("plan_support", "fact_checks", "literal_events", "obligations", "order_checks",
                 "dialogue_checks", "criteria", "ending_checks", "goal_checks", "legal_claims", "review_limitations"),
    "physical": ("initial_checks", "observed_prop_initial", "action_checks"),
}
PART_TABLES = {
    "semantic": ("plan_support", "fact_checks", "literal_events", "obligations", "order_checks",
                 "dialogue_checks", "criteria", "ending_checks", "goal_checks", "legal_claims", "review_limitations",
                 *SEMANTIC_TABLES, "unresolved_issues"),
    "physical": ("initial_checks", "observed_prop_initial", "action_checks"),
}
SOURCE_HEADERS = ("script_sha256", "brief_sha256", "plan_sha256", "legal_context_sha256",
                  "goal_contract_sha256", "opening_setup_sha256")
_ROW_TABLES = set(reviews.base.base._COVERAGE_KEYS) | {"action_checks", "goal_checks"}
REVIEW_RULE = reviews.REVIEW_RULE + (
    "当前响应只负责part_table_contract的表；两包仍阅读全文、当前目标与原生起态。"
    "语义包保留事实、目标、事件、义务、顺序、对白情绪、结尾法律及逐拍逐句所有检查，物理包保留完整状态和动作前提。"
    "revision_target：无明确fail填none；正文缺陷填script，完整规划或初态因果缺陷填plan。"
    "beat_intent_checks每拍两个原生event/trigger目标；父行只填显式status、counterexample_analysis与target_checks。"
    "每条真实对白dialogue_role_checks保留4个checks及显式父status；父status须保留子项fail/unknown，不再重复父判断的reason/revision/evidence。"
    "新两表的evidence/counterevidence只填当前实际E编号数组，不填对象、不抄引文，不引用目标T作实际事件。"
    "counterevidence只指尚未解决的反证；支持性前后文放evidence，不能放counterevidence后仍判pass。"
    "pass子项evidence非空、required_revision为空、counterevidence为空；逐句每个pass子项必须含自身E。fail明确完整返修要求，unknown保留不确定。"
    "speaker及整句原文由对白E键确切绑定，target_quote由目标T键绑定，不重复提交这些来源常量。"
    "实体以互斥短类型对象character_id、other_entity或unspecified表示；已登记人物用ID，其他实体用原文标签，无法判定用unspecified。"
    "propositions须用实际原文quote覆盖整句有意义字符，施事/受事/指称和negation.scope_quote仍精确绑定自身对白。"
    "listener_mode区分当面、自语、引用与不确定；quote_attribution保留确切引用片段与被引用者，不凭常识新增人物。"
    "先比字面命题、目的、刺激、反应和策略，再查具体内容是否真实演出；摘要、物件存在或有一行字不证明关键内容已写出。"
    "每项解释遵守Schema长度，直述关键依据与反例，不代写新戏；长度界限不证明服务必不截断。"
    "review_limitations仅写一般能力边界；具体遗漏、未兑现或不确定必须进unresolved_issues，选择当前table/item_id并将对应原生行判fail/unknown，不能主表pass而把具体缺陷藏在限制列表。"
    "全部通过只表示同源模型文本判断；程序不证明中文情绪因果、法律语义、人工审美或视频质量。"
)
EXPLANATION_LIMITS = {"reason": 160, "required_revision": 240, "counterexample_analysis": 160,
    "actual_reading": 240, "literal_meaning": 240, "character_purpose": 160,
    "purpose": 160, "turn_function": 160}


def _obj(fields):
    return {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}


def _text():
    return {"type": "string", "minLength": 1, "pattern": r"\S"}


def build_consistency_evidence_catalog(script, plan, *, goal_contract=None):
    """Separate actual steps from only native screenplay event/trigger targets.

    Paths point at unchanged native fields. No target is promoted to an E step,
    and no meaning or state is inferred from the quoted target.
    """
    entries = reviews.base.base.prior.contract.evidence_catalog(script)
    actual = {ref: {**deepcopy(row), "authority": "actual_performed_step",
        "document_path": row["path"].replace("script.", "native_script_document.", 1)}
        for ref, row in entries.items()}
    beats = script["beats"]
    ids = [row["id"] for row in beats]
    if len(ids) != len(set(ids)):
        raise ValueError("consistency catalog needs unique screenplay beat IDs")
    planned = {row["id"]: (index, row) for index, row in enumerate(plan["beats"])}
    if set(planned) != set(ids) or len(planned) != len(plan["beats"]):
        raise ValueError("consistency catalog plan and screenplay beat coverage differ")
    targets = {}

    def add(beat_id, suffix, path, quote, *, field):
        if not isinstance(quote, str) or not quote.strip():
            raise ValueError("consistency target must be a substantive source string")
        targets["T:" + beat_id + ":" + suffix] = {"authority": "target_assertion_only", "beat_id": beat_id,
            "document_path": path, "quote": quote, "field": field}

    for index, beat in enumerate(beats):
        for field in ("event", "trigger"):
            add(beat["id"], "script." + field, f"native_script_document.beats.{index}.{field}", beat[field], field=field)
    if goal_contract is not None:
        whole = goal_contract["whole_plan"]
        native = {row["id"]: (index, row) for index, row in enumerate(whole["beats"])}
        if set(native) != set(ids) or len(native) != len(whole["beats"]):
            raise ValueError("consistency catalog native goal and screenplay beat coverage differ")
    return {"schema": CONSISTENCY_CATALOG_VERSION, "actual_steps": actual, "target_assertions": targets,
        "source_context": {"authority": "same_source_context_only_not_performed_evidence",
            "plan_sha256": reviews.base.base.prior.digest(plan),
            "goal_contract_sha256": reviews.base.base.prior.digest(goal_contract) if goal_contract is not None else None,
            "existing_review_tables": ["plan_support", "fact_checks", "goal_checks"]},
        "semantic_extraction_authority": "reviewing_model_not_program", "semantic_meaning_programmatically_verified": False}


def _ref_evidence_schema(refs):
    return {"type": "array", "maxItems": len(refs), "uniqueItems": True,
            "items": {"enum": refs} if refs else False}


def _judgement_schema(refs, *, own_ref=None):
    row = _obj({"status": {"enum": ["pass", "fail", "unknown"]}, "reason": _text(),
        "required_revision": {"type": "string"}, "evidence": _ref_evidence_schema(refs),
        "counterevidence": _ref_evidence_schema(refs)})
    passed = {"required_revision": {"const": ""}, "counterevidence": {"maxItems": 0},
              "evidence": {"minItems": 1}}
    row["allOf"] = [
        {"if": {"properties": {"status": {"const": "pass"}}, "required": ["status"]},
         "then": {"properties": passed}},
        {"if": {"properties": {"status": {"const": "fail"}}, "required": ["status"]},
         "then": {"properties": {"required_revision": _text()}}}]
    if own_ref is not None:
        # One shared closed judgment, intersected with the current exact E.
        # This avoids copying the complete global E enum once per dialogue.
        return {"allOf": [row,
            {"if": {"properties": {"status": {"const": "pass"}}, "required": ["status"]},
             "then": {"properties": {"evidence": {"contains": {"const": own_ref}}}}}]}
    return row


def _semantic_schemas(script, brief, plan, goal_contract):
    catalog = build_consistency_evidence_catalog(script, plan, goal_contract=goal_contract)
    entries, targets = catalog["actual_steps"], catalog["target_assertions"]
    refs = list(entries)
    beats = {}
    for beat in script["beats"]:
        target_rows = {}
        for ref, target in targets.items():
            if target["beat_id"] == beat["id"]:
                row = _judgement_schema(refs)
                row["properties"]["actual_reading"] = _text()
                row["required"].append("actual_reading")
                target_rows[ref] = row
        beats[beat["id"]] = _obj({"status": {"enum": ["pass", "fail", "unknown"]},
            "counterexample_analysis": _text(), "target_checks": _obj(target_rows)})
    people = list(brief["constraints"]["allowed_character_ids"])
    entity = {"oneOf": [_obj({"character_id": {"enum": people}}),
        _obj({"other_entity": _text()}), _obj({"unspecified": {"type": ["string", "null"]}})]}
    entity_array = {"type": "array", "maxItems": 12, "uniqueItems": True, "items": entity}
    proposition = _obj({"quote": _text(), "agents": deepcopy(entity_array), "patients": deepcopy(entity_array),
        "referents": deepcopy(entity_array), "negation": _obj({"mode": {"enum": ["affirmed", "negated", "question", "unspecified"]},
            "scope_quote": {"type": ["string", "null"]}})})
    dialogue = {}
    for ref, actual in entries.items():
        if actual["kind"] != "dialogue":
            continue
        dialogue[ref] = _obj({"status": {"enum": ["pass", "fail", "unknown"]},
            "listener_id": {"enum": [None, *people]},
            "listener_mode": {"enum": ["addressed", "self_talk", "quoted_speech", "unspecified"]},
            "quote_attribution": _obj({"mode": {"enum": ["none", "direct_quote", "indirect_quote", "mixed"]},
                "attributed_to": deepcopy(entity), "quote_fragment": {"type": ["string", "null"]}}),
            "propositions": {"type": "array", "minItems": 1, "maxItems": 24, "items": proposition},
            "literal_meaning": _text(), "character_purpose": _text(),
            "checks": _obj({key: _judgement_schema(refs, own_ref=ref) for key in
                ("referents", "agent_patient", "negation_scope", "purpose_alignment")})})
    compact = reviews.base.base._compact_schema(_obj({"beat_intent_checks": _obj(beats),
        "dialogue_role_checks": _obj(dialogue)}))

    def rename(node):
        if isinstance(node, dict):
            return {key: (value.replace("#/$defs/shared_", "#/$defs/consistency_shared_", 1)
                          if key == "$ref" else rename(value)) for key, value in node.items()}
        if isinstance(node, list):
            return [rename(value) for value in node]
        return node

    definitions = {name.replace("shared_", "consistency_shared_", 1): rename(value)
                   for name, value in compact.get("$defs", {}).items()}
    return rename(compact["properties"]), definitions


def _bound_explanations(node):
    if isinstance(node, dict):
        for name, field in node.get("properties", {}).items():
            if name in EXPLANATION_LIMITS and isinstance(field, dict):
                field["maxLength"] = EXPLANATION_LIMITS[name]
        for value in node.values():
            _bound_explanations(value)
    elif isinstance(node, list):
        for value in node:
            _bound_explanations(value)


def _expand_semantic(document, script, plan, *, goal_contract=None):
    """Bind IDs and constants only, after raw v4 Schema acceptance.

    This private copy is compiler input, never a native response. No judgment,
    explanation, failure, counterproof or missing witness is manufactured.
    """
    catalog = build_consistency_evidence_catalog(script, plan, goal_contract=goal_contract)
    entries, targets = catalog["actual_steps"], catalog["target_assertions"]
    result = deepcopy(document)

    def entity(value):
        if "character_id" in value:
            return {"kind": "character", "character_id": value["character_id"], "label": None}
        if "other_entity" in value:
            return {"kind": "other_entity", "character_id": None, "label": value["other_entity"]}
        return {"kind": "unspecified", "character_id": None, "label": value["unspecified"]}

    def judgment(row):
        for key in ("evidence", "counterevidence"):
            row[key] = [{"source_ref": ref, "quote": entries[ref]["quote"]} for ref in row[key]]

    for row in result["beat_intent_checks"].values():
        for ref, child in row["target_checks"].items():
            judgment(child)
            child["target_quote"] = targets[ref]["quote"]
    for ref, row in result["dialogue_role_checks"].items():
        row["speaker_id"], row["quote"] = entries[ref]["speaker"], entries[ref]["quote"]
        row["quote_attribution"]["attributed_to"] = entity(row["quote_attribution"]["attributed_to"])
        for proposition in row["propositions"]:
            for key in ("agents", "patients", "referents"):
                proposition[key] = [entity(value) for value in proposition[key]]
        for child in row["checks"].values():
            judgment(child)
    return result


def _part(part):
    if part not in PART_TABLES:
        raise ValueError("review part must be semantic or physical")
    return part


def _context(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("part context identity must be a canonical SHA256")
    return value


def part_table_contract(part, script, brief, plan):
    _part(part)
    coverage = reviews.coverage_specification(script, brief, plan)
    coverage.update(beat_intent_checks=[beat["id"] for beat in script["beats"]],
                    dialogue_role_checks=list(coverage["dialogue_checks"]))
    owned = PART_TABLES[part]
    active = {table: list(coverage[table]) for table in owned if table in coverage and coverage[table]}
    always = [table for table in owned if table not in coverage]
    required = [table for table in owned if table in active or table in always]
    if part == "semantic" and brief.get("prior_story_scope"):
        required.append("prior_story_relation")
    return {"part": part, "required_tables": required,
            "omitted_zero_tables": [table for table in owned if table in coverage and not coverage[table]],
            "coverage": active}


def _prune_definitions(schema, definitions):
    """Keep the exact reachable shared definitions; do not duplicate rows."""
    needed = set()

    def visit(node):
        if isinstance(node, dict):
            if "$ref" in node:
                ref = node["$ref"]
                if not ref.startswith("#/$defs/"):
                    raise ValueError("only standard local shared definitions can be retained")
                name = ref[len("#/$defs/"):]
                if name not in definitions:
                    raise ValueError("part schema has an unresolved shared definition")
                if name not in needed:
                    needed.add(name)
                    visit(definitions[name])
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(schema)
    if needed:
        schema["$defs"] = {name: deepcopy(definitions[name]) for name in definitions if name in needed}
    return schema


def build_part_schema(part, script, brief, plan, legal_context, *, context_sha256,
                      goal_contract=None, opening_setup=None):
    _part(part)
    _context(context_sha256)
    full = reviews.build_review_schema(script, brief, plan, legal_context,
        goal_contract=goal_contract, opening_setup=opening_setup)
    fields = {key: deepcopy(full["properties"][key]) for key in SOURCE_HEADERS}
    semantic, semantic_definitions = _semantic_schemas(script, brief, plan, goal_contract) if part == "semantic" else ({}, {})
    for table in part_table_contract(part, script, brief, plan)["required_tables"]:
        if table != "unresolved_issues":
            fields[table] = deepcopy(semantic[table] if table in semantic else full["properties"][table])
    if part == "semantic":
        targets = []
        limit = 0
        for table in PART_TABLES[part]:
            if table in ("literal_events", "review_limitations", "unresolved_issues") or table not in fields:
                continue
            coverage = part_table_contract(part, script, brief, plan)["coverage"]
            if table in coverage:
                item = {"enum": coverage[table]}
                limit += len(coverage[table])
            elif table == "legal_claims":
                item = {"type": "integer", "minimum": 0}
                limit += len(reviews.base.base.prior.contract.evidence_catalog(script))
            else:
                continue
            targets.append({"properties": {"table": {"const": table}, "item_id": item},
                            "required": ["table", "item_id"]})
        issue = _obj({"table": {"type": "string"}, "item_id": {"type": ["string", "integer"]},
            "status": {"enum": ["fail", "unknown"]}, "reason": _text(), "required_revision": {"type": "string"}})
        issue["allOf"] = [{"oneOf": targets},
            {"if": {"properties": {"status": {"const": "fail"}}, "required": ["status"]},
             "then": {"properties": {"required_revision": _text()}}}]
        fields["unresolved_issues"] = {"type": "array", "maxItems": limit, "uniqueItems": True, "items": issue}
    fields.update(schema={"const": VERSION}, part={"const": part}, context_sha256={"const": context_sha256},
                  revision_target={"enum": ["none", "script", "plan"]})
    if part == "semantic" and "dialogue_checks" in fields:
        # Keep the original shared judgment intact. This intersection merely
        # compiles the exact identity/order checks already enforced below; it
        # cannot prove that a later step is a meaningful emotional reaction.
        entries = reviews.base.base.prior.contract.evidence_catalog(script)
        refs = list(entries)
        for ref, original in fields["dialogue_checks"]["properties"].items():
            index = refs.index(ref)
            earlier, later = refs[:index], refs[index + 1:]
            restriction = {"properties": {
                "stimulus_ref": {"enum": [None, *earlier]},
                "reaction_refs": {"type": "array", "minItems": 0,
                    "items": {"enum": later} if later else False,
                    "maxItems": len(later), "uniqueItems": True}}}
            fields["dialogue_checks"]["properties"][ref] = {
                "allOf": [deepcopy(original), restriction]}
    schema = _prune_definitions({"type": "object", "properties": fields, "required": list(fields),
                                "additionalProperties": False}, {**full.get("$defs", {}), **semantic_definitions})
    _bound_explanations(schema)
    Draft202012Validator.check_schema(schema)
    return schema


def _part_evidence(document, part, script, brief, plan, *, opening_setup=None, goal_contract=None):
    old = reviews.base.base
    entries = old.prior.contract.evidence_catalog(script)
    # These empty iteration sets are not missing audit rows or a native full
    # review. Only the owned, schema-complete actual rows are checked here.
    if part == "physical":
        selected = {table: deepcopy(document.get(table, {})) for table in
                    ("action_checks", "initial_checks", "observed_prop_initial")}
        selected.update(dialogue_checks={}, goal_checks={})
        reviews.base._validate_extra(selected, script, brief, opening_setup=opening_setup)
    else:
        refs = list(entries)
        for ref, row in document.get("dialogue_checks", {}).items():
            if row["status"] == "pass" and ref not in row["source_refs"]:
                raise ValueError("passing dialogue check must include its own actual dialogue reference")
            if not row["purpose"].strip() or not row["turn_function"].strip():
                raise ValueError("dialogue purpose and descriptive function must be substantive")
            if row["stimulus_ref"] is not None and refs.index(row["stimulus_ref"]) >= refs.index(ref):
                raise ValueError("dialogue stimulus must precede its actual dialogue step")
            if any(refs.index(reaction) <= refs.index(ref) for reaction in row["reaction_refs"]):
                raise ValueError("dialogue reaction must follow its actual dialogue step")
        for row in document["goal_checks"].values():
            if row["status"] == "pass" and not row["evidence"]:
                raise ValueError("passing scene-goal check requires actual screenplay evidence")
            for witness in row["evidence"]:
                old._quote(witness, entries)
                if witness["source_ref"] not in row["source_refs"]:
                    raise ValueError("goal witness must be part of its actual source references")
    for table in PART_TABLES[part]:
        if table not in document or table in ("literal_events", "review_limitations", *SEMANTIC_TABLES, "unresolved_issues"):
            continue
        rows = document[table].values() if isinstance(document[table], dict) else document[table]
        for row in rows:
            if row["status"] == "pass" and row["required_revision"]:
                raise ValueError("passing check cannot carry a mandatory revision")
            if row["status"] == "fail" and not row["required_revision"].strip():
                raise ValueError("failed check needs an explicit complete revision target")
    if part == "physical":
        props = {row["id"]: row for row in brief["initial_state"]["prop_states"]}
        for identifier, row in document.get("observed_prop_initial", {}).items():
            if row["status"] == "pass" and any(row[field] != props[identifier][field]
                for field in ("holder_character_id", "support", "orientation")):
                raise ValueError("passed actual initial prop atoms conflict with frozen native declarations")
        return
    literal = document.get("literal_events", {})
    for ref, row in literal.items():
        if (entries[ref]["kind"] == "action" and row["speech_functions"] != ["action"]
                or entries[ref]["kind"] == "dialogue" and "action" in row["speech_functions"]):
            raise ValueError("literal speech functions conflict with original step kind")
    positions = {ref: index for index, ref in enumerate(entries)}

    def occurrence(item):
        quote = item["quote"]
        ref = item["source_ref"]
        if not quote.strip() or quote not in entries[ref]["quote"]:
            raise ValueError("occurrence quote must come from the unchanged actual step")
        if not set(item["speech_functions"]).issubset(literal[ref]["speech_functions"]):
            raise ValueError("occurrence invents a speech function")
        start = entries[ref]["quote"].find(quote)
        return positions[ref], start, start + len(quote)

    obligations = {row["id"]: row for row in plan["source_obligations"]}
    seen = {}
    for identifier, row in document.get("obligations", {}).items():
        spec = obligations[identifier]
        keys = set()
        for witness in row["occurrence_evidence"]:
            occurrence(witness)
            key = (witness["source_ref"], witness["quote"])
            if key in keys:
                raise ValueError("duplicate occurrence evidence")
            keys.add(key)
            if spec["mode"] == "event" and row["status"] == "pass":
                actual = entries[witness["source_ref"]]
                if spec["required_kind"] != "either" and actual["kind"] != spec["required_kind"]:
                    raise ValueError("event witness has wrong step kind")
                if not set(spec["allowed_speech_functions"]) & set(witness["speech_functions"]):
                    raise ValueError("event witness lacks the required speech function")
                if (spec["actor_id"] in brief["constraints"]["allowed_character_ids"]
                        and spec["required_kind"] == "dialogue" and actual["speaker"] != spec["actor_id"]):
                    raise ValueError("event witness has wrong on-screen speaker")
        if row["status"] == "pass" and spec["mode"] == "event" and not keys:
            raise ValueError("passed event must actually occur")
        seen[identifier] = keys
    for identifier, spec in obligations.items():
        row = document["obligations"][identifier]
        if row["status"] != "pass" or spec["mode"] != "event":
            continue
        for other in spec.get("distinct_from_ids", []):
            other_row = document["obligations"][other]
            if other_row["status"] != "pass":
                continue
            for left in row["occurrence_evidence"]:
                for right in other_row["occurrence_evidence"]:
                    a, b = occurrence(left), occurrence(right)
                    if a[0] == b[0] and max(a[1], b[1]) < min(a[2], b[2]):
                        raise ValueError("distinct events cannot share an overlapping occurrence")
    for identifier, row in document.get("order_checks", {}).items():
        before_id, after_id = identifier.split(">")
        if row["status"] == "pass" and (not row["before"] or not row["after"]):
            raise ValueError("passed strict order needs actual witnesses")
        for key, source_id in (("before", before_id), ("after", after_id)):
            for witness in row[key]:
                occurrence(witness)
                if (witness["source_ref"], witness["quote"]) not in seen[source_id]:
                    raise ValueError("strict-order witness is not an occurrence of its obligation")
        if row["status"] == "pass" and not any((occurrence(a)[0] < occurrence(b)[0]
                or occurrence(a)[0] == occurrence(b)[0] and occurrence(a)[2] <= occurrence(b)[1])
                for a in row["before"] for b in row["after"]):
            raise ValueError("strict order is not shown by nonoverlapping occurrences")
    for row in document["legal_claims"]:
        if not row["quote"].strip() or row["quote"] not in entries[row["source_ref"]]["quote"]:
            raise ValueError("legal claim is not quoted from the actual text")
        if row["status"] == "pass" and not row["legal_fact_refs"]:
            raise ValueError("passed legal claim needs independent legal support")
    if "prior_story_relation" in document:
        relation = document["prior_story_relation"]
        if not relation["reason"].strip():
            raise ValueError("prior-story relation needs a substantive reason")
        for witness in relation["current_evidence"]:
            old._quote(witness, entries)
    _validate_semantic_evidence(document, script, plan, goal_contract=goal_contract)


def _validate_semantic_evidence(document, script, plan, *, goal_contract=None):
    """Check reported meaning bindings, never independently interpret prose."""
    catalog = build_consistency_evidence_catalog(script, plan, goal_contract=goal_contract)
    entries, targets = catalog["actual_steps"], catalog["target_assertions"]
    beat_position = {beat["id"]: index for index, beat in enumerate(script["beats"])}

    def quote(witness):
        ref = witness["source_ref"]
        if ref not in entries or not witness["quote"].strip() or witness["quote"] not in entries[ref]["quote"]:
            raise ValueError("semantic witness must quote an unchanged actual E step, never a target assertion")

    def judgment(row, *, own_ref=None):
        for witness in [*row["evidence"], *row["counterevidence"]]:
            quote(witness)
        if row["status"] == "pass":
            if row["required_revision"] or row["counterevidence"]:
                raise ValueError("passing semantic check cannot hide a mandatory revision or unresolved counterevidence")
            if not row["evidence"]:
                raise ValueError("passing semantic check needs actual E evidence")
            if own_ref is not None and not any(item["source_ref"] == own_ref for item in row["evidence"]):
                raise ValueError("passing dialogue-role check needs its own actual E quote")
        elif row["status"] == "fail" and not row["required_revision"].strip():
            raise ValueError("failed semantic check needs an explicit complete revision target")

    def aggregate(row, children):
        # Unknown has priority over definite failure, matching the dispatch
        # boundary. A model cannot hide one uncertain subcheck in a passing row.
        expected = "unknown" if any(item["status"] == "unknown" for item in children) else (
            "fail" if any(item["status"] == "fail" for item in children) else "pass")
        if row["status"] != expected:
            raise ValueError("semantic row status must preserve its reported subcheck failure or uncertainty")

    issue_targets = set()
    for issue in document["unresolved_issues"]:
        table, identifier = issue["table"], issue["item_id"]
        pointer = (table, identifier)
        if pointer in issue_targets:
            raise ValueError("each concrete unresolved target must appear once")
        issue_targets.add(pointer)
        rows = document[table]
        if isinstance(rows, list):
            if type(identifier) is not int or not 0 <= identifier < len(rows):
                raise ValueError("unresolved issue must identify an existing native array row")
        elif identifier not in rows:
            raise ValueError("unresolved issue must identify an existing native coverage row")
        if rows[identifier]["status"] != issue["status"]:
            raise ValueError("concrete unresolved issue cannot be hidden behind a passing or different-status native table row")

    for beat_id, row in document["beat_intent_checks"].items():
        checks = list(row["target_checks"].values())
        aggregate(row, checks)
        for ref, item in row["target_checks"].items():
            judgment(item)
            target = targets[ref]
            if any(beat_position[entries[w["source_ref"]]["beat_id"]] > beat_position[beat_id]
                   for w in item["evidence"]):
                raise ValueError("later beat cannot supply the current target's performed evidence")
            # A trigger may be established in an earlier beat. The current
            # event needs an actual step in this beat; neither uses metadata.
            earlier_allowed = target["field"] == "trigger"
            if item["status"] == "pass" and not earlier_allowed and not any(
                    entries[w["source_ref"]]["beat_id"] == beat_id for w in item["evidence"]):
                raise ValueError("passing current beat intent needs an actual step from that beat")
    for ref, row in document.get("dialogue_role_checks", {}).items():
        checks = list(row["checks"].values())
        aggregate(row, checks)
        for item in checks:
            judgment(item, own_ref=ref)
        if row["listener_mode"] == "self_talk" and row["listener_id"] not in (None, row["speaker_id"]):
            raise ValueError("self-talk cannot report a different addressed listener")
        if row["listener_mode"] == "unspecified" and row["listener_id"] is not None:
            raise ValueError("unspecified listener must remain null")
        if row["listener_mode"] == "addressed" and row["listener_id"] is None and row["status"] == "pass":
            raise ValueError("passing addressed dialogue must identify its listener")
        attribution = row["quote_attribution"]
        fragment = attribution["quote_fragment"]
        if attribution["mode"] == "none":
            if fragment is not None or attribution["attributed_to"]["kind"] != "unspecified":
                raise ValueError("unquoted speech cannot invent a quote attribution")
        elif not isinstance(fragment, str) or not fragment.strip() or fragment not in row["quote"]:
            raise ValueError("quote attribution must bind a real fragment of its actual dialogue")
        covered = set()
        for proposition in row["propositions"]:
            fragment = proposition["quote"]
            text = row["quote"]
            if fragment not in text:
                raise ValueError("proposition must bind an exact fragment of its own actual dialogue")
            # Locate all identical occurrences; overlapping fragments are legal
            # for compound predicates and do not force one unique subject.
            start = text.find(fragment)
            while start >= 0:
                covered.update(range(start, start + len(fragment)))
                start = text.find(fragment, start + 1)
            negation = proposition["negation"]
            scope = negation["scope_quote"]
            if negation["mode"] == "affirmed" and scope is not None:
                raise ValueError("affirmative proposition cannot report a negation scope")
            if negation["mode"] == "negated" and (not isinstance(scope, str) or not scope.strip() or scope not in fragment):
                raise ValueError("reported negation scope must quote the actual proposition fragment")
            if scope is not None and (not scope.strip() or scope not in fragment):
                raise ValueError("reported proposition scope must quote its actual fragment")
        if any(index not in covered and not char.isspace() and not unicodedata.category(char).startswith("P")
               for index, char in enumerate(row["quote"])):
            raise ValueError("dialogue propositions must bind every substantive character of the actual line")


def validate_part(document, part, script, brief, plan, legal_context, *, context_sha256,
                  goal_contract=None, opening_setup=None):
    old = reviews.base.base
    if not isinstance(document, dict):
        return old._error("SPLIT_REVIEW_SCHEMA_INVALID", "native review part must be a JSON object")
    try:
        Draft202012Validator(build_part_schema(part, script, brief, plan, legal_context,
            context_sha256=context_sha256, goal_contract=goal_contract, opening_setup=opening_setup)).validate(document)
        expanded = _expand_semantic(document, script, plan, goal_contract=goal_contract) if part == "semantic" else deepcopy(document)
        _part_evidence(expanded, part, script, brief, plan, opening_setup=opening_setup, goal_contract=goal_contract)
    except ValidationError as exc:
        return old._error("SPLIT_REVIEW_SCHEMA_INVALID", exc.message, "/".join(str(x) for x in exc.absolute_path))
    except (ValueError, KeyError, TypeError) as exc:
        return old._error("SPLIT_REVIEW_EVIDENCE_INVALID", str(exc))
    findings, uncertainties = [], []
    for table in PART_TABLES[part]:
        if table not in document or table in ("literal_events", "review_limitations"):
            continue
        rows = document[table].items() if isinstance(document[table], dict) else enumerate(document[table])
        for identifier, row in rows:
            item = {"target": "plan" if table == "plan_support" else "script", "table": table,
                    "item_id": identifier, "part": part, "finding": deepcopy(row)}
            if row["status"] == "fail":
                findings.append(item)
            elif row["status"] == "unknown":
                uncertainties.append(item)
    revision_target = document["revision_target"]
    if findings and revision_target == "none":
        return old._error("SPLIT_REVIEW_TARGET_INVALID", "a failed native review part must declare script or plan revision")
    if not findings and revision_target != "none":
        return old._error("SPLIT_REVIEW_TARGET_INVALID", "a part without a definite failure cannot declare a revision target")
    if any(item["table"] == "plan_support" for item in findings) and revision_target != "plan":
        return old._error("SPLIT_REVIEW_TARGET_INVALID", "a failed native plan-support check requires a plan revision target")
    for item in findings:
        item["target"] = revision_target
    status = "halt_review_uncertain" if uncertainties else "needs_whole_revision" if findings else "review_part_passed"
    if part == "semantic" and brief.get("prior_story_scope"):
        relation = document["prior_story_relation"]["relation"]
        if old.prior.story_body_digest(script) == old.prior.story_body_digest(brief["prior_story_scope"]["full_prior_script"]) or relation == "same_story":
            status = "halt_same_story_prior_allowance_exhausted"
        elif relation == "unknown":
            status = "halt_prior_story_relation_unknown"
    prior_halted = status.startswith(("halt_same_story", "halt_prior_story"))
    return {"valid": True, "accepted": status == "review_part_passed", "status": status, "part": part,
            "findings": findings, "uncertainties": uncertainties,
            "revision_target": revision_target, "requires_new_goal_plan": revision_target == "plan" and not prior_halted,
            "revision_dispatch_blocked": prior_halted,
            "complete_same_source_full_review": False, "human_quality_approved": False,
            "creative_quality_passed": False, "old_budget_reset": False,
            "split_review_contract_version": VERSION, "native_part_sha256": old.prior.digest(document),
            "reference_expansion_sha256": old.prior.digest(expanded),
            "reference_expansion_is_compiler_input": True, "native_response_rewritten": False,
            "semantic_review_is_model_judgement": True,
            "semantic_meaning_programmatically_verified": False}


def build_review_bundle(native_semantic_review, native_physical_review):
    return {"schema": BUNDLE_VERSION, "native_semantic_review": deepcopy(native_semantic_review),
            "native_physical_review": deepcopy(native_physical_review)}


def _bundle_metadata():
    return {"split_review_contract_version": VERSION, "split_review_bundle_version": BUNDLE_VERSION,
            "semantic_review_is_model_judgement": True, "semantic_meaning_programmatically_verified": False}


def validate_bundle(bundle, script, brief, plan, legal_context, *, semantic_context_sha256,
                    physical_context_sha256, goal_contract=None, opening_setup=None):
    old = reviews.base.base
    if (not isinstance(bundle, dict) or set(bundle) != {"schema", "native_semantic_review", "native_physical_review"}
            or bundle.get("schema") != BUNDLE_VERSION):
        return old._error("SPLIT_REVIEW_BUNDLE_INVALID", "bundle must contain exactly the two original native review parts")
    if semantic_context_sha256 == physical_context_sha256:
        return old._error("SPLIT_REVIEW_BUNDLE_INVALID", "independent part contexts cannot share one identity")
    parts = {part: bundle["native_" + part + "_review"] for part in PART_TABLES}
    contexts = {"semantic": semantic_context_sha256, "physical": physical_context_sha256}
    results = {part: validate_part(parts[part], part, script, brief, plan, legal_context,
        context_sha256=contexts[part], goal_contract=goal_contract, opening_setup=opening_setup) for part in PART_TABLES}
    if not all(result["valid"] for result in results.values()):
        return {"valid": False, "accepted": False, "status": "halt_split_review_contract", "part_results": results,
                "findings": [item for result in results.values() for item in result["findings"]],
                "uncertainties": [], "human_quality_approved": False, "creative_quality_passed": False,
                **_bundle_metadata()}
    prior_halts = [result["status"] for result in results.values()
                   if result["status"].startswith(("halt_same_story", "halt_prior_story"))]
    if prior_halts:
        return {"valid": True, "accepted": False, "status": prior_halts[0], "requires_new_goal_plan": False,
                "revision_dispatch_blocked": True, "part_results": results,
                "findings": [item for result in results.values() for item in result["findings"]],
                "uncertainties": [item for result in results.values() for item in result["uncertainties"]],
                "review_origin": "two_native_same_source_parts", "native_single_full_review": False,
                "human_quality_approved": False, "creative_quality_passed": False, "old_budget_reset": False,
                **_bundle_metadata()}
    if any(result["requires_new_goal_plan"] for result in results.values()):
        uncertainties = [item for result in results.values() for item in result["uncertainties"]]
        return {"valid": True, "accepted": False,
                "status": "halt_review_uncertain" if uncertainties else "halt_full_review_requires_new_complete_goal",
                "requires_new_goal_plan": True, "part_results": results,
                "findings": [item for result in results.values() for item in result["findings"]],
                "uncertainties": uncertainties, "review_origin": "two_native_same_source_parts",
                "native_single_full_review": False, "human_quality_approved": False,
                "creative_quality_passed": False, "old_budget_reset": False, **_bundle_metadata()}
    # Both native parts remain unchanged. This projection is deterministic
    # compiler input only; it is not stored or described as a model response.
    projected = {key: deepcopy(parts["semantic"][key]) for key in SOURCE_HEADERS}
    projected["schema"] = reviews.VERSION
    for part, native in parts.items():
        for table in part_table_contract(part, script, brief, plan)["required_tables"]:
            if table in (*SEMANTIC_TABLES, "unresolved_issues"):
                continue
            if table in projected:
                return old._error("SPLIT_REVIEW_BUNDLE_INVALID", "part table ownership overlaps")
            projected[table] = deepcopy(native[table])
    result = reviews.validate_full_review(projected, script, brief, plan, legal_context,
        goal_contract=goal_contract, opening_setup=opening_setup)
    if result["valid"]:
        # v5 still checks all physical and legacy semantic conditions. New
        # native consistency rows remain original parts; they are never added
        # to or presented as a counterfeit native full-review response.
        findings = [item for part_result in results.values() for item in part_result["findings"]]
        uncertainties = [item for part_result in results.values() for item in part_result["uncertainties"]]
        status = "halt_review_uncertain" if uncertainties else "needs_whole_revision" if findings else "text_ready_for_director"
        result = {**result, "findings": findings, "uncertainties": uncertainties,
                  "status": status, "accepted": status == "text_ready_for_director"}
    return {**result, "part_results": results, "review_origin": "two_native_same_source_parts",
            "native_single_full_review": False, **_bundle_metadata()}
