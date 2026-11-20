"""Source-only temporal interpretation sidecar for immutable source obligations.

No plan, audit or adjudication is edited. Strict ordering is applicable only to
two independently source-classified one-off occurrences; other facts and every
native judgment remain in their original gates.
"""
from __future__ import annotations
from copy import deepcopy
from . import creative_autonomous_text_contract_v11 as prior

for _name, _value in vars(prior).items():
    if not _name.startswith("_") and _name not in ("deepcopy", "prior", "json"):
        globals()[_name] = _value
base, v2, _digest = prior.base, prior.v2, prior._digest
VERSION = "creative_autonomous_text_contract/v12"
ADJUDICATION_RULE = prior.ADJUDICATION_RULE + (
    "语言来源边界：language_context_correct只能用实际正文及已演出的上下文解释语法、施事和指代；"
    "不能拿brief的预期剧情改写字面说话人、行动者或意义。该basis的source_evidence必须为空数组，"
    "source_attribute_quote必须为空串；用源剧情作语法支持视为整稿必修。实际上下文解释写explanation，"
    "不要求第三次审查，不删原检测或改裁决。"
)
TEMPORAL_SCOPE_RULE = (
    "你是独立来源时间语义审查员，只读冻结brief与完整源计划，不读剧本、旧裁决或测试预期。"
    "逐source_obligation依据其fact_id真实源原文确定temporal_mode：one_off是源要求一次发生且可定位先后的事件；"
    "invariant是整个相关过程持续成立的不变状态或约束；absence是源禁止发生的行为/事实，不能当一次发生；"
    "未能确定用unknown。源计划原mode:event不是答案，不能让已有错误类型覆盖原文。"
    "持续未签/未取用等源不变约束不因早期状态已有表现，就变成必须发生在推物之前的另一个事件；"
    "也不能因为后面有一次状态表现，就把整场不变约束缩成那个时刻。"
    "每义务恰一次，fact_id必须等于该义务的原fact_id；source_quote引用该冻结fact的原文片段，禁止复述。"
    "不得删义务、手改源计划、补正文、制造新时间关系或声称创作质量通过。"
    "严格source_order仅两端都是one_off才有发生先后语义；不变/禁止要求仍由对应义务及事实核对。"
)


def build_adjudication_schema(extract, script, brief, scope):
    schema = prior.build_adjudication_schema(extract, script, brief, scope)
    fields = schema["properties"]["findings"]["items"]["properties"]
    fields["source_evidence"]["description"] = (
        "用于业务来源核对的真实源证据。language_context_correct的语法/施事放行只能依实际正文，"
        "此处必须为空数组；否则语义决策要求完整返修，旧wire格式仍可接收。")
    fields["source_attribute_quote"]["description"] = (
        "业务属性的真实源允许片段。language_context_correct必须为空串，不能用brief剧情改写原句施事。")
    return schema


def validate_adjudication(value, extract, script, brief, scope):
    base._validate_schema(build_adjudication_schema(extract, script, brief, scope), value, "finding_adjudication")
    result = prior.validate_adjudication(value, extract, script, brief, scope)
    result["language_source_boundary_checked_at_decision"] = True
    return result


def decide_adjudication(value, extract, script, brief, scope):
    result = prior.decide_adjudication(value, extract, script, brief, scope)
    result["validation"] = validate_adjudication(value, extract, script, brief, scope)
    findings = prior.prior._findings(extract)
    entries = evidence_catalog(script)
    for verdict in value["findings"]:
        finding = findings[verdict["finding_id"]]
        if (finding["kind"] != "language" or verdict["disposition"] != "context_or_source_supported"
                or verdict["basis_kind"] != "language_context_correct"
                or not (verdict["source_evidence"] or verdict["source_attribute_quote"])):
            continue
        row = finding["row"]
        v2._add(result["revision_requirements"], entries, "LANGUAGE_SOURCE_DEPENDENT_" + row["id"],
            [row["source_ref"]], "语言放行依赖未演出的来源剧情，不能据brief改写实际原句的施事、指代或意义；"
            "须由完整新正文消除原检测的问题。原检测：" + row["explanation"] +
            "；原裁决：" + verdict["explanation"], FROZEN_SOURCE_REPAIR)
        result["revision_requirements"][-1].update(finding_id=row["id"], extracted_quote=row["quote"],
            native_disposition=verdict["disposition"], source_evidence=deepcopy(verdict["source_evidence"]))
    return prior.prior._fail_first(result)


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
        language_source_boundary_enforced=True, event_evidence=primary["event_evidence"])
    return prior.prior._fail_first(result)


def build_temporal_scope_schema(plan, brief):
    obligations = plan["source_obligations"]
    variants = [base._obj({"obligation_id": {"const": row["id"]},
        "fact_id": {"const": row["fact_id"]},
        "temporal_mode": {"enum": ["one_off", "invariant", "absence", "unknown"]},
        "source_quote": base._text(), "explanation": base._text()}) for row in obligations]
    return base._obj({"plan_sha256": {"const": _digest(plan)}, "brief_sha256": {"const": _digest(brief)},
        "obligations": {"type": "array", "minItems": len(obligations), "maxItems": len(obligations),
            "items": {"oneOf": variants} if variants else False}})


def validate_temporal_scope(value, plan, brief):
    base._validate_schema(build_temporal_scope_schema(plan, brief), value, "source_temporal_scope")
    ids = [row["obligation_id"] for row in value["obligations"]]
    expected = {row["id"] for row in plan["source_obligations"]}
    if len(ids) != len(set(ids)) or set(ids) != expected:
        raise ValueError("source temporal scope must cover every original obligation exactly once")
    facts = v2._facts(brief)
    for row in value["obligations"]:
        if not row["source_quote"].strip() or row["source_quote"] not in facts[row["fact_id"]]:
            raise ValueError("temporal source quote must be an unchanged frozen fact fragment")
    known = all(row["temporal_mode"] != "unknown" for row in value["obligations"])
    return {"complete": True, "source_hash": _digest(value), "plan_sha256": _digest(plan),
        "brief_sha256": _digest(brief), "source_temporal_known": known, "availability_unknown": not known,
        "source_temporal_semantics_model_classified": True, "semantic_quality_approved": False}


def decide_temporal_scope(value, plan, brief):
    validation = validate_temporal_scope(value, plan, brief)
    uncertainties = [deepcopy(row) for row in value["obligations"] if row["temporal_mode"] == "unknown"]
    return {"status": "halt_source_uncertain" if uncertainties else "source_contract_ready",
        "validation": validation, "temporal_scope_sha256": _digest(value), "plan_sha256": _digest(plan),
        "brief_sha256": _digest(brief), "uncertainties": uncertainties,
        "native_source_plan_changed": False, "human_quality_approved": False, "creative_quality_passed": False}


def derive_temporal_order_evidence(value, plan, brief):
    validation = validate_temporal_scope(value, plan, brief)
    modes = {row["obligation_id"]: row for row in value["obligations"]}
    rows = []
    for edge in plan["source_order"]:
        before, after = modes[edge["before_id"]], modes[edge["after_id"]]
        rows.append({"source_order": deepcopy(edge),
            "decision_code": "SOURCE_ORDER_" + edge["before_id"] + "_BEFORE_" + edge["after_id"],
            "strict_occurrence_order_applicable": before["temporal_mode"] == after["temporal_mode"] == "one_off",
            "before_temporal_source": deepcopy(before), "after_temporal_source": deepcopy(after)})
    return {"validation": validation, "plan_sha256": _digest(plan), "brief_sha256": _digest(brief),
        "temporal_scope_sha256": _digest(value), "orders": rows,
        "native_plan_changed": False, "non_order_obligation_gates_preserved": True,
        "source_temporal_semantics_model_classified": True}


def combine_temporal_decisions(review, audit, extract, adjudication, script, brief, plan, scope, temporal):
    source = decide_temporal_scope(temporal, plan, brief)
    result = combine_adjudicated_decisions(review, audit, extract, adjudication, script, brief, plan, scope)
    report = derive_temporal_order_evidence(temporal, plan, brief)
    result.update(temporal_scope_sha256=_digest(temporal), derived_temporal_order_evidence=report,
        native_plan_changed=False, native_audit_changed=False, native_adjudication_changed=False)
    result["validation"]["source_temporal_scope"] = source["validation"]
    if source["status"] == "halt_source_uncertain":
        result["status"] = "halt_source_uncertain"
        result["source_temporal_uncertainties"] = source["uncertainties"]
        return result
    skipped = {row["decision_code"] for row in report["orders"] if not row["strict_occurrence_order_applicable"]}
    # Remove only the derived strict-order finding. Native proof status, source
    # event facts, initial conditions and business findings remain unchanged.
    removed = [deepcopy(row) for row in result["revision_requirements"] if row["code"] in skipped]
    result["revision_requirements"] = [row for row in result["revision_requirements"] if row["code"] not in skipped]
    result["derived_temporal_order_evidence"]["inapplicable_strict_order_findings"] = removed
    result["status"] = ("needs_whole_revision" if result["revision_requirements"] else
                        "halt_review_uncertain" if result["uncertainties"] else "text_ready_for_director")
    return result
