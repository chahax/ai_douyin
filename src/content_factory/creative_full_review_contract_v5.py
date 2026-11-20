"""Independent zero-coverage protocol; never repairs a native model response."""
from __future__ import annotations

from copy import deepcopy

from jsonschema import Draft202012Validator, ValidationError

from . import creative_full_review_contract_v4 as base

VERSION = "creative_full_review_contract/v5"
GOAL_FIELDS = base.GOAL_FIELDS
STATE_KEYS = base.STATE_KEYS
coverage_specification = base.coverage_specification
initial_evidence_catalog = base.initial_evidence_catalog
REVIEW_RULE = base.REVIEW_RULE + (
    "review_table_contract是程序生成的当前覆盖目录；只返回required_tables中的表，非零表逐ID完整覆盖。"
    "omitted_zero_tables在当前来源确为零项，响应不得返回这些表，连空对象也省略；不写通用总评替代逐项判断。"
)


def review_table_contract(script, brief, plan):
    coverage = coverage_specification(script, brief, plan)
    active = {table: list(ids) for table, ids in coverage.items() if ids}
    always = ["legal_claims", "review_limitations"]
    if brief.get("prior_story_scope"):
        always.append("prior_story_relation")
    return {"required_tables": [*active, *always],
            "omitted_zero_tables": [table for table, ids in coverage.items() if not ids],
            "coverage": active}


def build_review_schema(script, brief, plan, legal_context, *, goal_contract=None, opening_setup=None):
    schema = base.build_review_schema(script, brief, plan, legal_context,
                                     goal_contract=goal_contract, opening_setup=opening_setup)
    for table in review_table_contract(script, brief, plan)["omitted_zero_tables"]:
        schema["properties"].pop(table)
    schema["properties"]["schema"] = {"const": VERSION}
    schema["required"] = list(schema["properties"])
    Draft202012Validator.check_schema(schema)
    return schema


def _compiled_view(document, script, brief, plan):
    """Only verified zero rows get empty internal containers, never judgments."""
    value = deepcopy(document)
    for table in review_table_contract(script, brief, plan)["omitted_zero_tables"]:
        if table in value:
            raise ValueError("zero-coverage table must be omitted by the native response")
        value[table] = {}
    return value


def _validate_compiled_view(value, script, brief, plan, legal_context, *, goal_contract=None, opening_setup=None):
    old = base.base
    legacy = old._legacy_document(value)
    legacy.pop("opening_setup_sha256")
    validation = old.prior.validate_review(legacy, script, brief, plan, legal_context)
    base._validate_extra(value, script, brief, opening_setup=opening_setup)
    decision = old.prior.decide_review(legacy, script, brief, plan, legal_context)
    findings, uncertainties = list(decision["revision_requirements"]), list(decision["uncertainties"])
    for table in ("action_checks", "goal_checks"):
        for identifier, row in value[table].items():
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
            "requires_new_goal_plan": any(item.get("target") == "plan" for item in findings),
            "semantic_review_is_model_judgement": True, "native_initial_projection_verified": opening_setup is not None,
            "human_quality_approved": False, "creative_quality_passed": False, "old_budget_reset": False}


def validate_full_review(document, script, brief, plan, legal_context, *, goal_contract=None, opening_setup=None):
    if not isinstance(document, dict):
        return base.base._error("REVIEW_SCHEMA_INVALID", "full review must be a JSON object")
    coverage = coverage_specification(script, brief, plan)
    if document.get("dialogue_checks") in ([], {}) and coverage["dialogue_checks"]:
        return base.base._error("DIALOGUE_COVERAGE_EMPTY", "all actual dialogue references require one review row", "dialogue_checks")
    try:
        Draft202012Validator(build_review_schema(script, brief, plan, legal_context,
            goal_contract=goal_contract, opening_setup=opening_setup)).validate(document)
        value = _compiled_view(document, script, brief, plan)
        return _validate_compiled_view(value, script, brief, plan, legal_context,
            goal_contract=goal_contract, opening_setup=opening_setup)
    except ValidationError as exc:
        return base.base._error("REVIEW_SCHEMA_INVALID", exc.message, "/".join(str(part) for part in exc.absolute_path))
    except (ValueError, KeyError, TypeError) as exc:
        return base.base._error("REVIEW_EVIDENCE_INVALID", str(exc))
