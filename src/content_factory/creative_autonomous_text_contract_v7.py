"""Review wire outputs identify frozen sources without rewriting source prose.

The compiler adds expected facts and initial states from IDs only. Native
observations, statuses, explanations and repair judgments are never rewritten.
Explicit legacy projections remove only those two source-metadata fields after
old-wire structural and same-source checks. Frozen v1-v6 stay unchanged.
"""
from __future__ import annotations

from copy import deepcopy
from . import creative_autonomous_text_contract_v6 as prior

base = prior.base
v2 = prior.v2
VERSION = "creative_autonomous_text_contract/v7"
CRITERIA = deepcopy(prior.CRITERIA)
FUNCTIONS = list(prior.FUNCTIONS)
RELATIONS = list(prior.RELATIONS)
ORIENTATIONS = list(prior.ORIENTATIONS)
ANCHOR_TYPES = list(prior.ANCHOR_TYPES)
_digest = prior._digest
FROZEN_SOURCE_REPAIR = prior.FROZEN_SOURCE_REPAIR
FROZEN_PLAN_REPAIR = prior.FROZEN_PLAN_REPAIR
build_plan_schema = prior.build_plan_schema
compile_plan = prior.compile_plan
validate_plan = prior.validate_plan
build_script_schema = prior.build_script_schema
compile_script = prior.compile_script
evidence_catalog = prior.evidence_catalog
build_source_audit_schema = prior.build_source_audit_schema
compile_source_audit = prior.compile_source_audit
validate_source_audit = prior.validate_source_audit
decide_source_audit = prior.decide_source_audit


def _wire_schema(schema):
    for table, field in (("fact_checks", "expected_fact"),
                         ("initial_state_checks", "expected_state")):
        row = schema["properties"][table]["items"]
        row["properties"].pop(field)
        row["required"].remove(field)
        schema["properties"][table]["description"] = (
            "通过已有fact_id或entity_type/entity_id引用冻结来源；"
            "只报告正文实际观察与审查判断，期望来源原文由本地编译，不生成复述。")
    return schema


def build_review_schema(script, brief):
    return _wire_schema(prior.build_review_schema(script, brief))


def build_audit_schema(script, brief, plan):
    return _wire_schema(prior.build_audit_schema(script, brief, plan))


def _source_metadata(value, brief):
    result = deepcopy(value)
    facts = v2._facts(brief)
    states = v2._states(brief)
    try:
        for row in result["fact_checks"]:
            row["expected_fact"] = facts[row["fact_id"]]
        for row in result["initial_state_checks"]:
            row["expected_state"] = states[row["entity_type"], row["entity_id"]]
    except KeyError as error:
        raise ValueError("review selected an unknown compound source identity") from error
    return result


def compile_review(raw, script, brief):
    base._validate_schema(build_review_schema(script, brief), raw, "native_review")
    result = _source_metadata(raw, brief)
    prior.validate_review(result, script, brief)
    return result


def compile_audit(raw, script, brief, plan):
    base._validate_schema(build_audit_schema(script, brief, plan), raw, "native_audit")
    result = _source_metadata(raw, brief)
    prior.validate_audit(result, script, brief, plan)
    return result


def validate_review(value, script, brief):
    compiled = compile_review(value, script, brief)
    validation = prior.validate_review(compiled, script, brief)
    return {**validation, "source_hash": _digest(value),
            "raw_review_sha256": _digest(value), "compiled_review_sha256": _digest(compiled),
            "source_metadata_compiled_from_frozen_ids": True,
            "native_semantic_judgments_unchanged": True}


def validate_audit(value, script, brief, plan):
    compiled = compile_audit(value, script, brief, plan)
    validation = prior.validate_audit(compiled, script, brief, plan)
    return {**validation, "source_hash": _digest(value),
            "raw_audit_sha256": _digest(value), "compiled_audit_sha256": _digest(compiled),
            "source_metadata_compiled_from_frozen_ids": True,
            "native_semantic_judgments_unchanged": True}


def decide_review(value, script, brief):
    compiled = compile_review(value, script, brief)
    result = prior.decide_review(compiled, script, brief)
    result.update(validation=validate_review(value, script, brief),
                  raw_review_sha256=_digest(value), compiled_review_sha256=_digest(compiled),
                  native_semantic_judgments_unchanged=True)
    return result


def decide_audit(value, script, brief, plan):
    compiled = compile_audit(value, script, brief, plan)
    result = prior.decide_audit(compiled, script, brief, plan)
    result.update(validation=validate_audit(value, script, brief, plan),
                  raw_audit_sha256=_digest(value), compiled_audit_sha256=_digest(compiled),
                  native_semantic_judgments_unchanged=True)
    return result


def combine_decisions(review, audit, script, brief, plan):
    compiled_review = compile_review(review, script, brief)
    compiled_audit = compile_audit(audit, script, brief, plan)
    result = prior.combine_decisions(compiled_review, compiled_audit, script, brief, plan)
    native = {"review": review, "audit": audit}
    compiled = {"review": compiled_review, "audit": compiled_audit}
    result.update(
        raw_review_sha256=_digest(review), compiled_review_sha256=_digest(compiled_review),
        raw_audit_sha256=_digest(audit), compiled_audit_sha256=_digest(compiled_audit),
        raw_combined_sha256=_digest(native), compiled_combined_sha256=_digest(compiled),
        native_semantic_judgments_unchanged=True)
    result["validation"].update(
        source_hash=_digest(native),
        primary_review=validate_review(review, script, brief),
        literal_audit=validate_audit(audit, script, brief, plan))
    return result


def _project_source_metadata(value):
    result = deepcopy(value)
    for row in result["fact_checks"]:
        row.pop("expected_fact")
    for row in result["initial_state_checks"]:
        row.pop("expected_state")
    return result


def project_legacy_review(value, script, brief):
    """Adapt a known full old-wire review, dropping source metadata only."""
    base._validate_schema(prior.build_review_schema(script, brief), value, "legacy_review")
    result = _project_source_metadata(value)
    validate_review(result, script, brief)
    return result


def project_legacy_audit(value, script, brief, plan):
    """Adapt a known full old-wire audit, dropping source metadata only."""
    base._validate_schema(prior.build_audit_schema(script, brief, plan), value, "legacy_audit")
    result = _project_source_metadata(value)
    validate_audit(result, script, brief, plan)
    return result
