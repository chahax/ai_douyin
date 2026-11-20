"""Explicit compatibility for source-bound contextual adjudication.

Old wire judgments remain valid artifacts. Incompatible exemptions become
whole-script revision evidence, not interface failures or edited judgments.
"""
from __future__ import annotations
from copy import deepcopy
import json
from . import creative_autonomous_text_contract_v10 as prior

for _name, _value in vars(prior).items():
    if not _name.startswith("_") and _name not in ("deepcopy", "prior"):
        globals()[_name] = _value
base, v2, _digest = prior.base, prior.v2, prior._digest
VERSION = "creative_autonomous_text_contract/v11"
_BUSINESS_CATEGORIES = {"follow_up_undertaking", "business_procedure", "legal_rule"}
_PERSONAL_CONTEXTS = ["employee_refusal", "current_intention", "request_for_company_response"]
_PERSONAL_SOURCE_CATEGORIES = {"employee_intention"}
_PHYSICAL_SOURCE_CATEGORIES = {"procedural_action", "performance_action", "document_fact"}
_PRESSURE_SOURCE_CATEGORIES = {"private_pressure", "follow_up_undertaking"}
ADJUDICATION_RULE = prior.ADJUDICATION_RULE + (
    "context兼容表是语义验收要求：business_promise/business_completion/business_sequence/future_business_action，"
    "private_pressure、scene_timing和existing_source_event不能作非business豁免；私人帮交差不是承诺、"
    "办理规定或法律效果的授权。个人拒签/当前意愿/要求公司解释可以据实际人物与同施事源意愿重新归类，"
    "必须引用原employee_intention允许事实的具体原文；不能拿人事私人请托引用代替员工拒签依据。"
    "物理动作仅可重分未来动作或办理过程，须匹配同施事的源物理/程序事实，不豁免明确business_promise或法律规则。"
    "business_requirement若检测实为个人交差压力，可有具体同施事源私人请托依据后按private_pressure裁决；"
    "这不能豁免签字就办完等完成保证，其真实含义仍须独立裁决。"
    "日期、金额、期限的context兼容表为空，只能使用真实原允许属性字面。"
    "不合兼容应confirmed_violation；不能改正文或检测原字段来通过。"
)


def contextual_compatibility(extract, brief):
    """Public decision table; classifies evidence use, never rewrites findings."""
    people = set(base._characters(brief))
    table = {}
    for key, finding in prior._findings(extract).items():
        if finding["kind"] != "claim": continue
        row, category = finding["row"], finding["category"]
        if row["attribute_type"] in prior.prior._LITERAL_TYPES:
            contexts = []
        elif category in _BUSINESS_CATEGORIES:
            contexts = list(_PERSONAL_CONTEXTS) if row["actor_id"] in people else []
            if category == "business_procedure" or (category == "follow_up_undertaking" and
                                                    row["attribute_type"] == "future_business_action"):
                contexts.append("physical_performance")
            if category == "business_procedure" and row["attribute_type"] == "business_requirement":
                contexts.append("private_pressure")
        else:
            # Other protected values still require their own v10 factual gate;
            # this compatibility change does not create a general exemption.
            contexts = []
        table[key] = {"category": category, "attribute_type": row["attribute_type"],
            "actor_id": row["actor_id"], "allowed_context_types": contexts,
            "source_supported_personal_categories": sorted(_PERSONAL_SOURCE_CATEGORIES),
            "source_supported_physical_categories": sorted(_PHYSICAL_SOURCE_CATEGORIES),
            "source_supported_pressure_categories": sorted(_PRESSURE_SOURCE_CATEGORIES)}
    return table


def build_adjudication_schema(extract, script, brief, scope):
    schema = prior.build_adjudication_schema(extract, script, brief, scope)
    schema["properties"]["findings"]["description"] = (
        "以下是语义验收兼容表。原wire类型保持不变，不合兼容的裁决被记录为完整正文必修，"
        "不是运输或接口错误；native检测和裁决不可改写。" +
        json.dumps(contextual_compatibility(extract, brief), ensure_ascii=False, separators=(",", ":")))
    return schema


def validate_adjudication(value, extract, script, brief, scope):
    # Public schema contains the same wire shape and extra semantic descriptions.
    # Semantic incompatibility is decided below, not rejected as malformed wire.
    base._validate_schema(build_adjudication_schema(extract, script, brief, scope), value, "finding_adjudication")
    result = prior.validate_adjudication(value, extract, script, brief, scope)
    result.update(context_compatibility_sha256=_digest(contextual_compatibility(extract, brief)),
                  semantic_exemptions_checked_at_decision=True)
    return result


def _compatible_source(verdict, finding, scope, brief):
    native = prior.prior.prior._native_scope(scope, brief)
    row = finding["row"]
    kinds = (_PHYSICAL_SOURCE_CATEGORIES if verdict["context_type"] == "physical_performance" else
             _PRESSURE_SOURCE_CATEGORIES if verdict["context_type"] == "private_pressure" else
             _PERSONAL_SOURCE_CATEGORIES)
    return any(allowance["category"] in kinds and allowance["actor_id"] in ("", row["actor_id"])
        and any(evidence["fact_id"] in allowance["source_fact_ids"] and
                (evidence["quote"] in allowance["value"] or allowance["value"] in evidence["quote"])
                for evidence in verdict["source_evidence"])
        for allowance in native["allowed_claims"])


def decide_adjudication(value, extract, script, brief, scope):
    validation = validate_adjudication(value, extract, script, brief, scope)
    result = prior.decide_adjudication(value, extract, script, brief, scope)
    findings = prior._findings(extract)
    table = contextual_compatibility(extract, brief)
    entries = evidence_catalog(script)
    for verdict in value["findings"]:
        key = verdict["finding_id"]
        if (key not in table or verdict["disposition"] != "context_or_source_supported"
                or verdict["basis_kind"] != "non_business_context"):
            continue
        expected = table[key]
        if (verdict["context_type"] in expected["allowed_context_types"]
                and _compatible_source(verdict, findings[key], scope, brief)):
            continue
        row = findings[key]["row"]
        problem = ("非business豁免不合来源/属性兼容：" + expected["category"] + "/" +
            expected["attribute_type"] + "不能以" + verdict["context_type"] + "作此处免责依据；"
            "允许context=" + "/".join(expected["allowed_context_types"]) +
            "。私人请托不支持业务承诺/办理规定，个人拒签需同施事源意愿，物理动作需具体源动作。"
            "原裁决解释：" + verdict["explanation"])
        v2._add(result["revision_requirements"], entries, "ADJUDICATION_CONTEXT_" + key,
                [row["source_ref"]], problem, FROZEN_SOURCE_REPAIR)
        result["revision_requirements"][-1].update(finding_id=key, extracted_quote=row["quote"],
            native_disposition=verdict["disposition"], source_evidence=deepcopy(verdict["source_evidence"]))
    result.update(validation=validation, contextual_compatibility=table, native_detection_changed=False,
                  native_adjudication_changed=False)
    return prior._fail_first(result)


def combine_adjudicated_decisions(review, audit, extract, adjudication, script, brief, plan, scope):
    primary = combine_decisions(review, audit, script, brief, plan)
    focused = decide_adjudication(adjudication, extract, script, brief, scope)
    values = {"review": review, "audit": audit, "extract": extract, "adjudication": adjudication}
    result = v2._result("combined", values, script, {"complete": True, "source_hash": _digest(values),
        "primary_and_literal": primary["validation"], "independent_adjudication": focused["validation"]},
        primary["revision_requirements"] + focused["revision_requirements"],
        primary["uncertainties"] + focused["uncertainties"])
    result.update(plan_sha256=_digest(plan), scope_sha256=_digest(scope), extract_sha256=_digest(extract),
        adjudication_sha256=_digest(adjudication), native_detection_changed=False, native_adjudication_changed=False,
        independent_finding_adjudication_required=True, contextual_compatibility=focused["contextual_compatibility"],
        event_evidence=primary["event_evidence"])
    return prior._fail_first(result)
