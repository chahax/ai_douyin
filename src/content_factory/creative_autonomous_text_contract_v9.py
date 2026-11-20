"""Sparse business attributes and executable occurrence evidence, without prose edits.

The original source scope and all native judgments remain immutable. This version
projects only protected attributes, and compiles occurrence windows from evidence
whose literal actor, kind and speech function actually match the source event.
Semantic classification and source alignment are model judgments, not guarantees.
"""
from __future__ import annotations

from copy import deepcopy
from . import creative_autonomous_text_contract_v8 as prior

base = prior.base
v2 = prior.v2
VERSION = "creative_autonomous_text_contract/v9"
CRITERIA = deepcopy(prior.CRITERIA)
FUNCTIONS = list(prior.FUNCTIONS)
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
build_review_schema = prior.build_review_schema
compile_review = prior.compile_review
validate_review = prior.validate_review
decide_review = prior.decide_review
project_legacy_review = prior.project_legacy_review
project_legacy_audit = prior.project_legacy_audit
build_source_fact_scope_schema = prior.build_source_fact_scope_schema
validate_source_fact_scope = prior.validate_source_fact_scope
compile_source_fact_scope = prior.compile_source_fact_scope
SOURCE_SCOPE_RULE = prior.SOURCE_SCOPE_RULE

# These categories concern new business attributes, not all legal-story prose.
# The projection retains source rule IDs and quotes; it supplies no new facts.
_CATEGORY_PROJECTION = {
    "employment_departure_timing": "employment_departure_timing",
    "contract_term": "contract_term",
    "employment_start_timing": "employment_start_timing",
    "wage_or_payment": "wage_or_payment",
    "compensation_or_liability": "compensation_or_liability",
    "follow_up_undertaking": "follow_up_undertaking",
    "procedural_action": "business_procedure",
    "other_legal_fact": "legal_rule",
}
ATTRIBUTE_TYPES = {
    "employment_departure_timing": ["departure_time", "departure_deadline"],
    "contract_term": ["contract_duration", "contract_end_time"],
    "employment_start_timing": ["employment_start_time"],
    "wage_or_payment": ["payment_amount", "payment_time", "payment_rule"],
    "compensation_or_liability": ["compensation_amount", "compensation_rule", "liability_rule"],
    "follow_up_undertaking": ["future_business_action", "business_promise"],
    "business_procedure": ["business_completion", "business_requirement", "business_sequence"],
    "legal_rule": ["legal_effect", "legal_rule"],
}
FACT_CATEGORIES = list(ATTRIBUTE_TYPES)
_LITERAL_TYPES = {"departure_time", "departure_deadline", "contract_duration", "contract_end_time",
    "employment_start_time", "payment_amount", "payment_time", "compensation_amount"}
MODALITIES = ["assertion", "presupposition", "conditional_undertaking", "future_intention"]
FACT_SCOPE_RULE = (
    "本审查只提取受保护类别的新增业务属性，不把全部正文写成事实白名单。"
    "每个category_extracts类别完整覆盖，可无claims；公司要求离开、本人没提辞职、拒签、纸笔移动、"
    "留坐呼气、私人求情和普通现场谈话时间不作为新业务属性。"
    "每句可能同时含多个类别：公司决定中出现离开期限，仍须另提departure_time/deadline；"
    "劝签请求中夹带本人后续替人办理、向公司解释的未来行动，仍须另提future_business_action。"
    "请求/质问本身不作断言；带业务预设才拆预设命题。希望公司解释不是说话人承诺解释。"
    "业务程序只指未给出的办理规定、条件、顺序、完成保证；不是现场推纸、收纸或走出门。"
    "法律规则只指新增法律效果/权利义务判断，不包括物理状态、情绪或正常拒签原话。"
    "attribute_value引用正文中具体属性原文，不写整句归一命题；quote用唯一完整原文子句。"
    "actor_id指业务主张的承担或决定主体，不是转述说话人。日期、金额和期限保留原文字面，"
    "不把相对离开时间归入公司决定而漏检。"
    "source_alignment独立比较该具体属性与源允许行为/规定：同类别allowance_id不证明符合；"
    "source_attribute_quote须是真实源allowance原文片段，源属性属于私人请托/动作/现场时间用context，"
    "不能拿context当未来业务承诺或法律规则；未给的属性用unsupported，无法判断用unknown。"
    "普通自然口语可自由表达；日期/金额等实际属性字面核对，业务行动/规则比较具体含义及承担人。"
    "source_alignment不能把限制句当许可，不能把实际未来业务安排缩成已有私人求情来放行。"
    "另列有唯一原文证据的语病、施事歧义、意义冲突；不代写替代台词。每个实际step都coverage，"
    "无敏感属性可claim_ids为空；未知进入unknown_items。"
)
AUDIT_RULE = prior.AUDIT_RULE + (
    "事件发生以实际kind、actor和speech_functions匹配的引用为锚；附带触发/上下文不能充当发生，"
    "严格先后只比较真正发生子句。一个实际请求或拒绝即可兑现单次义务；不存在真正发生仍失败。"
)


def project_sensitive_scope(scope, brief):
    """Read-only projection of the original typed scope, with its original SHA."""
    native = prior._native_scope(scope, brief)
    restrictions = []
    for row in native["restrictions"]:
        if row["category"] in _CATEGORY_PROJECTION:
            # A broad prohibition of new legal/business facts protects every
            # sensitive business family, even if the earlier source extractor
            # did not separately enumerate a salary or payment restriction.
            targets = FACT_CATEGORIES if row["category"] == "other_legal_fact" else [
                _CATEGORY_PROJECTION[row["category"]]]
            for category in targets:
                copied = deepcopy(row)
                copied.update(original_category=row["category"], original_restriction_id=row["id"],
                              category=category, id=row["id"] + "::" + category)
                restrictions.append(copied)
    categories = [key for key in FACT_CATEGORIES if any(row["category"] == key for row in restrictions)]
    allowed = []
    for row in native["allowed_claims"]:
        category = _CATEGORY_PROJECTION.get(row["category"])
        if category in categories:
            copied = deepcopy(row)
            copied["original_category"] = row["category"]
            copied["category"] = category
            allowed.append(copied)
    return {"brief_sha256": _digest(brief), "scope_sha256": _digest(scope),
        "protected_categories": categories, "restrictions": restrictions,
        "source_allowances": allowed, "source_classification_model_extracted": True,
        "semantic_quality_approved": False}


def _claim_schema(category, refs, brief, projected):
    allowance_ids = [row["id"] for row in projected["source_allowances"] if row["category"] == category]
    alignment = base._obj({
        "status": {"enum": ["supported", "unsupported", "unknown"]},
        "allowance_id": {"enum": allowance_ids + [""]},
        "source_attribute_quote": {"type": "string"},
        "source_attribute_type": {"enum": ATTRIBUTE_TYPES[category] + ["context", "none", "unknown"]},
        "explanation": base._text(),
    })
    alignment["allOf"] = [{"if": {"properties": {"status": {"const": "supported"}}},
        "then": {"properties": {"allowance_id": {"enum": allowance_ids} if allowance_ids else False,
                                 "source_attribute_quote": {"type": "string", "minLength": 1}}}}]
    return base._obj({"id": base._text(), "source_ref": {"enum": refs}, "quote": base._text(),
        "actor_id": {"enum": base._actors(brief) + [""]},
        "attribute_type": {"enum": ATTRIBUTE_TYPES[category]}, "attribute_value": base._text(),
        "modality": {"enum": MODALITIES}, "source_alignment": alignment})


def build_fact_scope_schema(script, brief, scope):
    projected = project_sensitive_scope(scope, brief)
    refs = list(evidence_catalog(script))
    categories = projected["protected_categories"]
    tables = [base._obj({"category": {"const": category},
        "claims": {"type": "array", "items": _claim_schema(category, refs, brief, projected)}})
        for category in categories]
    origin = {"id": base._text(), "source_ref": {"enum": refs}, "quote": base._text()}
    finding = base._obj({**origin, "issue_type": {"enum": ["ungrammatical", "ambiguous_actor", "meaning_conflict"]},
                        "explanation": base._text()})
    unknown = base._obj({**origin, "topic": base._text(), "explanation": base._text()})
    ids = {"type": "array", "uniqueItems": True, "items": base._text()}
    coverage = base._obj({"source_ref": {"enum": refs}, "claim_ids": deepcopy(ids),
        "dialogue_finding_ids": deepcopy(ids), "unknown_ids": deepcopy(ids)})
    return base._obj({"script_sha256": {"const": _digest(script)}, "brief_sha256": {"const": _digest(brief)},
        "scope_sha256": {"const": _digest(scope)},
        "category_extracts": {"type": "array", "minItems": len(categories), "maxItems": len(categories),
            "items": {"oneOf": tables} if tables else False,
            "allOf": [{"contains": {"type": "object", "properties": {"category": {"const": category}},
                                      "required": ["category"]}, "minContains": 1, "maxContains": 1}
                      for category in categories]},
        "dialogue_findings": {"type": "array", "items": finding},
        "unknown_items": {"type": "array", "items": unknown},
        "step_coverage": {"type": "array", "minItems": len(refs), "maxItems": len(refs), "items": coverage}})


def _claims(value):
    return [(table["category"], row) for table in value["category_extracts"] for row in table["claims"]]


def validate_fact_scope_extract(value, script, brief, scope):
    base._validate_schema(build_fact_scope_schema(script, brief, scope), value, "fact_scope_extract")
    body = {key: deepcopy(item) for key, item in script.items() if key != "selected_candidate_id"}
    if compile_script(body, brief) != script:
        raise ValueError("extract script changed compiler-bound source")
    projected = project_sensitive_scope(scope, brief)
    category_ids = [table["category"] for table in value["category_extracts"]]
    if len(category_ids) != len(set(category_ids)) or set(category_ids) != set(projected["protected_categories"]):
        raise ValueError("focused extract must cover every protected category exactly once")
    entries = evidence_catalog(script)
    if [row["source_ref"] for row in value["step_coverage"]] != list(entries):
        raise ValueError("focused extract must cover every actual step in original order")
    allowances = {row["id"]: row for row in projected["source_allowances"]}
    all_claims = [row for _, row in _claims(value)]
    specs = [(all_claims, "claim_ids"), (value["dialogue_findings"], "dialogue_finding_ids"),
             (value["unknown_items"], "unknown_ids")]
    all_ids = []
    for native_rows, key in specs:
        rows = {row["id"]: row for row in native_rows}
        if len(rows) != len(native_rows):
            raise ValueError("extract IDs must be unique")
        all_ids.extend(rows)
        linked = []
        for coverage in value["step_coverage"]:
            for item_id in coverage[key]:
                if item_id not in rows or rows[item_id]["source_ref"] != coverage["source_ref"]:
                    raise ValueError("extract coverage links a missing or different-step finding")
                linked.append(item_id)
        if len(linked) != len(set(linked)) or set(linked) != set(rows):
            raise ValueError("extract coverage must link every finding exactly once")
        for row in rows.values():
            prior._actual_quote(row["source_ref"], row["quote"], entries)
            if key == "dialogue_finding_ids" and entries[row["source_ref"]]["kind"] != "dialogue":
                raise ValueError("dialogue finding must cite an actual spoken step")
    if len(all_ids) != len(set(all_ids)):
        raise ValueError("extract IDs must be unique across tables")
    for category, row in _claims(value):
        if not row["attribute_value"].strip() or row["attribute_value"] not in row["quote"]:
            raise ValueError("actual business attribute must be an unchanged fragment of its actual quote")
        alignment = row["source_alignment"]
        allowance = allowances.get(alignment["allowance_id"])
        source_quote = alignment["source_attribute_quote"]
        if allowance:
            if allowance["category"] != category:
                raise ValueError("source alignment allowance has a different protected category")
            if source_quote and source_quote not in allowance["value"]:
                raise ValueError("source alignment must cite an unchanged original allowance value fragment")
        elif source_quote:
            raise ValueError("source alignment quote requires a real original allowance ID")
        if alignment["status"] == "supported" and (not allowance or not source_quote.strip()):
            raise ValueError("supported alignment requires an actual allowance and original attribute quote")
    return {"complete": True, "source_hash": _digest(value), "script_sha256": _digest(script),
        "brief_sha256": _digest(brief), "scope_sha256": _digest(scope),
        "protected_categories": projected["protected_categories"], "step_count": len(entries),
        "semantic_quality_approved": False}


def _compact(value):
    return "".join(value.split())


def decide_fact_scope_extract(value, script, brief, scope):
    validation = validate_fact_scope_extract(value, script, brief, scope)
    projected = project_sensitive_scope(scope, brief)
    allowances = {row["id"]: row for row in projected["source_allowances"]}
    entries = evidence_catalog(script)
    requirements, uncertainties = [], []

    def add(target, code, row, problem):
        v2._add(target, entries, code, [row["source_ref"]], problem, FROZEN_SOURCE_REPAIR)
        target[-1].update(extracted_quote=row["quote"], claim_id=row["id"])

    for category, row in _claims(value):
        alignment = row["source_alignment"]
        if alignment["status"] == "unknown" or alignment["source_attribute_type"] == "unknown":
            add(uncertainties, "FACT_SCOPE_UNKNOWN_" + row["id"], row,
                "敏感业务属性与来源关系未明：" + category + "；" + alignment["explanation"])
            continue
        allowance = allowances.get(alignment["allowance_id"])
        forbidden = any(item["category"] == category and item["mode"] == "absence"
                        for item in projected["restrictions"])
        matched = (alignment["status"] == "supported" and allowance is not None
                   and allowance["actor_id"] in ("", row["actor_id"])
                   and alignment["source_attribute_type"] == row["attribute_type"])
        if matched and row["attribute_type"] in _LITERAL_TYPES:
            # Only the actual protected value is compared; surrounding dialogue
            # remains free. Source dates/amounts may not be paraphrased away.
            matched = _compact(row["attribute_value"]) == _compact(alignment["source_attribute_quote"])
        if forbidden or not matched:
            add(requirements, "FACT_SCOPE_" + row["id"], row,
                "实际正文引入未获来源支持的敏感业务属性：" + category + "/" + row["attribute_type"] +
                "；实际属性：" + row["attribute_value"] + "；来源关系：" + alignment["explanation"] +
                "。私人请托、物理动作或同类别源ID不能授权新的业务期限、规定或后续承担。")
    for row in value["dialogue_findings"]:
        add(requirements, "LANGUAGE_FOCUSED_" + row["id"], row, row["issue_type"] + "：" + row["explanation"])
    for row in value["unknown_items"]:
        add(uncertainties, "FACT_SCOPE_UNKNOWN_" + row["id"], row, row["topic"] + "：" + row["explanation"])
    result = v2._result("fact_scope_extract", value, script, validation, requirements, uncertainties)
    result.update(scope_sha256=_digest(scope), sensitive_attributes_only=True,
                  source_alignment_model_judgment_required=True)
    return result


build_audit_schema = prior.build_audit_schema


def _event_mismatch(obligation, event):
    errors = []
    if obligation["required_kind"] != "either" and event["kind"] != obligation["required_kind"]:
        errors.append("kind")
    if obligation["actor_id"] and event["actual_actor"] != obligation["actor_id"]:
        errors.append("actor")
    if event["kind"] == "dialogue" and obligation["actor_id"] and event["speaker"] != obligation["actor_id"]:
        errors.append("speaker")
    if obligation["allowed_speech_functions"][0] not in event["speech_functions"]:
        errors.append("speech_function")
    return errors


def _derived_audit(value, script, brief, plan):
    # Expand optional spans and perform all original native source/type/coverage
    # checks before deriving anything. Never sanitize a malformed model output.
    derived = prior._expanded_audit(value, script, brief, plan)
    entries = evidence_catalog(script)
    events = {row["source_ref"]: row for row in derived["literal_events"]}
    obligations = {row["id"]: row for row in plan["source_obligations"]}
    reports = []
    for proof in derived["obligation_evidence"]:
        obligation = obligations[proof["obligation_id"]]
        native_refs = list(proof["occurrence_refs"])
        classified = []
        for ref in native_refs:
            mismatch = _event_mismatch(obligation, events[ref]) if obligation["mode"] == "event" else []
            classified.append({"ref_id": ref, "quote": entries[ref]["quote"],
                "matching": not bool(mismatch), "mismatch_fields": mismatch})
        matching = [row["ref_id"] for row in classified if row["matching"]]
        unusable = [row["ref_id"] for row in classified if not row["matching"]]
        proof["occurrence_refs"] = matching
        proof["support_refs"] = list(dict.fromkeys(proof["support_refs"] + unusable))
        if "occurrence_spans" in proof:
            proof["occurrence_spans"] = [row for row in proof["occurrence_spans"] if row["ref_id"] in matching]
        reports.append({"obligation_id": proof["obligation_id"], "mode": obligation["mode"],
            "native_occurrence_refs": native_refs, "matching_occurrence_refs": matching,
            "unusable_context_refs": unusable, "support_refs": deepcopy(proof["support_refs"]),
            "native_status": proof["status"], "native_explanation": proof["explanation"],
            "matching_occurrence_spans": deepcopy(proof.get("occurrence_spans", [])),
            "evidence_classification": classified})
    # This validates the compiled evidence view without altering status/reasons.
    prior.prior.validate_audit(derived, script, brief, plan)
    return derived, reports


def derive_event_evidence(value, script, brief, plan):
    derived, reports = _derived_audit(value, script, brief, plan)
    return {"script_sha256": _digest(script), "brief_sha256": _digest(brief), "plan_sha256": _digest(plan),
        "raw_audit_sha256": _digest(value), "derived_audit_sha256": _digest(derived),
        "obligations": reports, "native_judgments_changed": False,
        "strict_order_uses_matching_occurrences_only": True,
        "semantic_quality_approved": False}


def compile_audit(value, script, brief, plan):
    derived, _ = _derived_audit(value, script, brief, plan)
    return prior.prior.compile_audit(derived, script, brief, plan)


def validate_audit(value, script, brief, plan):
    derived, reports = _derived_audit(value, script, brief, plan)
    compiled = prior.prior.compile_audit(derived, script, brief, plan)
    validation = prior.prior.validate_audit(derived, script, brief, plan)
    return {**validation, "source_hash": _digest(value), "raw_audit_sha256": _digest(value),
        "derived_audit_sha256": _digest(derived), "compiled_audit_sha256": _digest(compiled),
        "matching_occurrence_evidence_compiled": True, "native_judgments_changed": False,
        "event_evidence_report_sha256": _digest(reports)}


def decide_audit(value, script, brief, plan):
    derived, _ = _derived_audit(value, script, brief, plan)
    result = prior.prior.decide_audit(derived, script, brief, plan)
    result.update(validation=validate_audit(value, script, brief, plan), raw_audit_sha256=_digest(value),
        compiled_audit_sha256=_digest(compile_audit(value, script, brief, plan)),
        event_evidence=derive_event_evidence(value, script, brief, plan))
    return result


def combine_decisions(review, audit, script, brief, plan):
    primary = decide_review(review, script, brief)
    literal = decide_audit(audit, script, brief, plan)
    values = {"review": review, "audit": audit}
    result = v2._result("combined", values, script, {"complete": True, "source_hash": _digest(values),
        "primary_review": primary["validation"], "literal_audit": literal["validation"]},
        primary["revision_requirements"] + literal["revision_requirements"],
        primary["uncertainties"] + literal["uncertainties"])
    result.update(plan_sha256=_digest(plan), review_sha256=_digest(review), audit_sha256=_digest(audit),
        raw_audit_sha256=_digest(audit), compiled_audit_sha256=literal["compiled_audit_sha256"],
        both_same_source_checks_required=True, executable_atomic_source_events_required=True,
        physical_initial_atoms_required=True, occurrence_and_support_separated=True,
        event_evidence=literal["event_evidence"])
    return result


def combine_scope_decisions(review, audit, extract, script, brief, plan, scope):
    primary = combine_decisions(review, audit, script, brief, plan)
    focused = decide_fact_scope_extract(extract, script, brief, scope)
    values = {"review": review, "audit": audit, "extract": extract}
    result = v2._result("combined", values, script, {"complete": True, "source_hash": _digest(values),
        "primary_and_literal": primary["validation"], "focused_scope": focused["validation"]},
        primary["revision_requirements"] + focused["revision_requirements"],
        primary["uncertainties"] + focused["uncertainties"])
    result.update(plan_sha256=_digest(plan), scope_sha256=_digest(scope), review_sha256=_digest(review),
        audit_sha256=_digest(audit), extract_sha256=_digest(extract),
        independent_scope_extract_required=True, event_evidence=primary["event_evidence"])
    return result


combine_fact_scope_decisions = combine_scope_decisions
