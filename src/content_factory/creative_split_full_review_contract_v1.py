"""Two complete source-bound native audits, never a counterfeit single audit."""
from __future__ import annotations

from copy import deepcopy
import re

from jsonschema import Draft202012Validator, ValidationError

from . import creative_full_review_contract_v5 as reviews

VERSION = "creative_split_full_review_part/v1"
BUNDLE_VERSION = "creative_split_full_review_bundle/v1"
PART_TABLES = {
    "semantic": ("plan_support", "fact_checks", "literal_events", "obligations", "order_checks",
                 "dialogue_checks", "criteria", "ending_checks", "goal_checks", "legal_claims", "review_limitations"),
    "physical": ("initial_checks", "observed_prop_initial", "action_checks"),
}
SOURCE_HEADERS = ("script_sha256", "brief_sha256", "plan_sha256", "legal_context_sha256",
                  "goal_contract_sha256", "opening_setup_sha256")
_ROW_TABLES = set(reviews.base.base._COVERAGE_KEYS) | {"action_checks", "goal_checks"}
REVIEW_RULE = reviews.REVIEW_RULE + (
    "当前响应只负责part_table_contract规定的表，每份仍阅读同一完整正文与原生目标和起态。"
    "语义审查负责信息先后、对白、情绪、对手策略促因、物件写了什么与其功能、结尾承诺和法律；"
    "物理审查负责起态、穿着、移动、取放、动作前提和状态连续。不要代另一包补表或填写另一包通过。"
    "revision_target是原生返修目标：无明确fail填none；有明确fail填script或plan。"
    "若缺陷来自整片规划的因果、物件内容或初态前提，明确填plan，不用正文迁就错误规划。"
)


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
    for table in part_table_contract(part, script, brief, plan)["required_tables"]:
        fields[table] = deepcopy(full["properties"][table])
    fields.update(schema={"const": VERSION}, part={"const": part}, context_sha256={"const": context_sha256},
                  revision_target={"enum": ["none", "script", "plan"]})
    schema = _prune_definitions({"type": "object", "properties": fields, "required": list(fields),
                                "additionalProperties": False}, full.get("$defs", {}))
    Draft202012Validator.check_schema(schema)
    return schema


def _part_evidence(document, part, script, brief, plan, *, opening_setup=None):
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
        if table not in document or table in ("literal_events", "review_limitations"):
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


def validate_part(document, part, script, brief, plan, legal_context, *, context_sha256,
                  goal_contract=None, opening_setup=None):
    old = reviews.base.base
    if not isinstance(document, dict):
        return old._error("SPLIT_REVIEW_SCHEMA_INVALID", "native review part must be a JSON object")
    try:
        Draft202012Validator(build_part_schema(part, script, brief, plan, legal_context,
            context_sha256=context_sha256, goal_contract=goal_contract, opening_setup=opening_setup)).validate(document)
        _part_evidence(document, part, script, brief, plan, opening_setup=opening_setup)
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
            "creative_quality_passed": False, "old_budget_reset": False}


def build_review_bundle(native_semantic_review, native_physical_review):
    return {"schema": BUNDLE_VERSION, "native_semantic_review": deepcopy(native_semantic_review),
            "native_physical_review": deepcopy(native_physical_review)}


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
                "uncertainties": [], "human_quality_approved": False, "creative_quality_passed": False}
    prior_halts = [result["status"] for result in results.values()
                   if result["status"].startswith(("halt_same_story", "halt_prior_story"))]
    if prior_halts:
        return {"valid": True, "accepted": False, "status": prior_halts[0], "requires_new_goal_plan": False,
                "revision_dispatch_blocked": True, "part_results": results,
                "findings": [item for result in results.values() for item in result["findings"]],
                "uncertainties": [item for result in results.values() for item in result["uncertainties"]],
                "review_origin": "two_native_same_source_parts", "native_single_full_review": False,
                "human_quality_approved": False, "creative_quality_passed": False, "old_budget_reset": False}
    if any(result["requires_new_goal_plan"] for result in results.values()):
        uncertainties = [item for result in results.values() for item in result["uncertainties"]]
        return {"valid": True, "accepted": False,
                "status": "halt_review_uncertain" if uncertainties else "halt_full_review_requires_new_complete_goal",
                "requires_new_goal_plan": True, "part_results": results,
                "findings": [item for result in results.values() for item in result["findings"]],
                "uncertainties": uncertainties, "review_origin": "two_native_same_source_parts",
                "native_single_full_review": False, "human_quality_approved": False,
                "creative_quality_passed": False, "old_budget_reset": False}
    # Both native parts remain unchanged. This projection is deterministic
    # compiler input only; it is not stored or described as a model response.
    projected = {key: deepcopy(parts["semantic"][key]) for key in SOURCE_HEADERS}
    projected["schema"] = reviews.VERSION
    for part, native in parts.items():
        for table in part_table_contract(part, script, brief, plan)["required_tables"]:
            if table in projected:
                return old._error("SPLIT_REVIEW_BUNDLE_INVALID", "part table ownership overlaps")
            projected[table] = deepcopy(native[table])
    result = reviews.validate_full_review(projected, script, brief, plan, legal_context,
        goal_contract=goal_contract, opening_setup=opening_setup)
    return {**result, "part_results": results, "review_origin": "two_native_same_source_parts",
            "native_single_full_review": False}
