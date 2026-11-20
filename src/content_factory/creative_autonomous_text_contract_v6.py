"""Compile source quotes from frozen IDs, without rewriting creative plan fields.

The model owns the complete native plan. Wire output contains source IDs rather
than copied source prose. The compiler adds only the exact brief-owned quotes;
all semantic source and script checking stays with frozen v5. No service calls.
"""
from __future__ import annotations

from copy import deepcopy
from . import creative_autonomous_text_contract_v5 as prior

base = prior.base
v2 = prior.v2
VERSION = "creative_autonomous_text_contract/v6"
CRITERIA = deepcopy(prior.CRITERIA)
FUNCTIONS = list(prior.FUNCTIONS)
RELATIONS = list(prior.RELATIONS)
ORIENTATIONS = list(prior.ORIENTATIONS)
ANCHOR_TYPES = list(prior.ANCHOR_TYPES)
_digest = prior._digest
FROZEN_SOURCE_REPAIR = prior.FROZEN_SOURCE_REPAIR
FROZEN_PLAN_REPAIR = prior.FROZEN_PLAN_REPAIR
build_script_schema = prior.build_script_schema
compile_script = prior.compile_script
evidence_catalog = prior.evidence_catalog
build_review_schema = prior.build_review_schema
validate_review = prior.validate_review
decide_review = prior.decide_review
build_audit_schema = prior.build_audit_schema
validate_audit = prior.validate_audit
decide_audit = prior.decide_audit
combine_decisions = prior.combine_decisions


def build_plan_schema(brief):
    """Native wire Schema: frozen source text is resolved locally from IDs."""
    schema = prior.build_plan_schema(brief)
    for key in ("initial_conditions", "source_order"):
        row = schema["properties"][key]["items"]
        row["properties"].pop("source_quote")
        row["required"].remove("source_quote")
    schema["properties"]["initial_conditions"]["description"] = (
        "每个声明初态实体一条，通过entity_type/entity_id引用冻结expected_state。"
        "仅声明来源明确限定的物理原子；未明用unspecified。来源原文由本地编译器按ID解析，不生成或复述。")
    schema["properties"]["source_order"]["description"] = (
        "只列来源必须的event→event严格先后，每边用fact_id引用原事实。"
        "不从计划排列或同一次行动的不同描述推断两次发生；无来源先后为空。"
        "来源原文由本地编译器按fact_id解析，不生成或复述。")
    return schema


def compile_plan(raw, brief):
    """Add only exact source quotes; preserve every native creative value."""
    base._validate_schema(build_plan_schema(brief), raw, "native_plan")
    result = deepcopy(raw)
    states = v2._states(brief)
    facts = v2._facts(brief)
    for row in result["initial_conditions"]:
        row["source_quote"] = states[row["entity_type"], row["entity_id"]]
    for row in result["source_order"]:
        row["source_quote"] = facts[row["fact_id"]]
    # Reuse all frozen coverage, IDs, physical rules and ordering checks. Source
    # support remains a separate semantic audit, never a compiler inference.
    prior.validate_plan(result, brief)
    return result


def validate_plan(value, brief):
    """Validate native output and expose both native and compiled identities."""
    compiled = compile_plan(value, brief)
    validation = prior.validate_plan(compiled, brief)
    return {**validation, "source_hash": _digest(value),
            "raw_plan_sha256": _digest(value), "compiled_plan_sha256": _digest(compiled),
            "source_quotes_compiled_from_frozen_ids": True,
            "native_creative_values_unchanged": True}


SOURCE_AUDIT_TABLES = ("fact_coverage_checks", "source_obligation_checks",
                       "initial_condition_checks", "source_order_checks")


def build_source_audit_schema(plan, brief):
    """Native source-review output owns judgments, while IDs own source text."""
    schema = prior.build_source_audit_schema(plan, brief)
    for table in SOURCE_AUDIT_TABLES:
        row = schema["properties"][table]["items"]
        row["properties"].pop("source_quote")
        row["required"].remove("source_quote")
        # Keep the semantic scope explicit without asking the reviewer to copy
        # prose that is already deterministically identified by the row IDs.
        schema["properties"][table]["description"] = (
            schema["properties"][table]["description"].replace(
                "quote原样引用计划source_quote。", "来源文本由实体ID解析，不生成来源复写。")
            .replace("quote原样引用该边source_quote。", "来源文本由前后事件ID解析，不生成来源复写。")
            .replace("quote来自该fact，", "来源文本由该义务的fact_id解析，"))
    return schema


def compile_source_audit(raw, plan, brief):
    """Add only source metadata; preserve every native semantic judgment."""
    base._validate_schema(build_source_audit_schema(plan, brief), raw, "native_source_audit")
    result = deepcopy(raw)
    facts = v2._facts(brief)
    obligations = {row["id"]: row for row in plan["source_obligations"]}
    conditions = {(row["entity_type"], row["entity_id"]): row for row in plan["initial_conditions"]}
    orders = {(row["before_id"], row["after_id"]): row for row in plan["source_order"]}
    try:
        for row in result["fact_coverage_checks"]:
            row["source_quote"] = facts[row["fact_id"]]
        for row in result["source_obligation_checks"]:
            row["source_quote"] = facts[obligations[row["obligation_id"]]["fact_id"]]
        for row in result["initial_condition_checks"]:
            row["source_quote"] = conditions[row["entity_type"], row["entity_id"]]["source_quote"]
        for row in result["source_order_checks"]:
            row["source_quote"] = orders[row["before_id"], row["after_id"]]["source_quote"]
    except KeyError as error:
        raise ValueError("source audit selected an unknown compound source identity") from error
    prior.validate_source_audit(result, plan, brief)
    return result


def validate_source_audit(value, plan, brief):
    compiled = compile_source_audit(value, plan, brief)
    validation = prior.validate_source_audit(compiled, plan, brief)
    return {**validation, "source_hash": _digest(value),
            "raw_source_audit_sha256": _digest(value),
            "compiled_source_audit_sha256": _digest(compiled),
            "source_quotes_compiled_from_frozen_ids": True,
            "native_semantic_judgments_unchanged": True}


def decide_source_audit(value, plan, brief):
    compiled = compile_source_audit(value, plan, brief)
    result = prior.decide_source_audit(compiled, plan, brief)
    result.update(validation=validate_source_audit(value, plan, brief),
                  raw_source_audit_sha256=_digest(value),
                  compiled_source_audit_sha256=_digest(compiled),
                  native_semantic_judgments_unchanged=True)
    return result
