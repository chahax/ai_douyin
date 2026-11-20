"""Authenticate detector quotations against their own immutable source allowance.

This protocol repair accepts a genuine bound source-quote fragment as well as
an allowance's shorter value. It changes no native detection or judgment and
creates no semantic permission. Explicit local adjudication entry points avoid
calling frozen validators through predecessor-module closures.
"""
from __future__ import annotations
from copy import deepcopy
import json
from . import creative_autonomous_text_contract_v12 as prior
from . import creative_autonomous_text_contract_v11 as _v11
from . import creative_autonomous_text_contract_v10 as _v10
from . import creative_autonomous_text_contract_v9 as _v9
from . import creative_autonomous_text_contract_v8 as _v8

for _name, _value in vars(prior).items():
    if not _name.startswith("_") and _name not in ("deepcopy", "prior", "json"):
        globals()[_name] = _value
base, v2, _digest = prior.base, prior.v2, prior._digest
VERSION = "creative_autonomous_text_contract/v13"
_findings, _fail_first = _v10._findings, _v10._fail_first
_compatible_source = _v11._compatible_source
FACT_SCOPE_RULE = prior.FACT_SCOPE_RULE + (
    "检测来源引用验收：source_alignment.source_attribute_quote可引用选定同category allowance.value"
    "的原片段，也可引用该allowance.source_quotes里已绑定同fact_id的真实冻结原片段。"
    "不能引用别的allowance、未绑定fact、不同category或复述；原标点也属于真实原文。"
    "引用真实只证明来源定位，不证明该具体业务属性获允许；私人请托/现场动作的真实原文"
    "不能因此变成业务承诺、办理规定或法律效果的许可，仍须完整独立裁决。")
# The v12 semantic adjudication rules, contextual compatibility and language
# boundary remain unchanged. Source-supported business properties still need
# their concrete allowance value, not merely an authentic wider source quote.
ADJUDICATION_RULE = prior.ADJUDICATION_RULE


def _authenticated_allowance_quote(allowance, quote, brief):
    """A provenance domain, never a semantic property-alignment decision."""
    if quote in allowance["value"]:
        return True
    facts = v2._facts(brief)
    fact_ids = set(allowance["source_fact_ids"])
    return any(source["fact_id"] in fact_ids
               and source["fact_id"] in facts
               and source["quote"] in facts[source["fact_id"]]
               and quote in source["quote"]
               for source in allowance["source_quotes"])


def build_fact_scope_schema(script, brief, scope):
    schema = _v9.build_fact_scope_schema(script, brief, scope)
    items = schema["properties"]["category_extracts"]["items"]
    for table in items.get("oneOf", []):
        quote = table["properties"]["claims"]["items"]["properties"]["source_alignment"]["properties"]["source_attribute_quote"]
        quote["description"] = (
            "只引用本category选定allowance.value，或本allowance.source_quotes绑定同fact_id的真实原文片段；"
            "不能复述、跨allowance/事实/类别。真实引用只验证来源，不代表业务语义通过。")
    return schema


def validate_fact_scope_extract(value, script, brief, scope):
    """Same immutable wire/body checks; authenticate owned source quotations."""
    base._validate_schema(build_fact_scope_schema(script, brief, scope), value, "fact_scope_extract")
    body = {key: deepcopy(item) for key, item in script.items() if key != "selected_candidate_id"}
    if compile_script(body, brief) != script:
        raise ValueError("extract script changed compiler-bound source")
    projected = project_sensitive_scope(scope, brief)
    cats = [row["category"] for row in value["category_extracts"]]
    if len(cats) != len(set(cats)) or set(cats) != set(projected["protected_categories"]):
        raise ValueError("focused extract must cover every protected category exactly once")
    entries = evidence_catalog(script)
    if [row["source_ref"] for row in value["step_coverage"]] != list(entries):
        raise ValueError("focused extract must cover every actual step in original order")
    rows = _findings(value)
    if len(rows) != sum(len(row["claims"]) for row in value["category_extracts"]) + len(value["dialogue_findings"]) + len(value["unknown_items"]):
        raise ValueError("extract IDs must be unique across tables")
    links = []
    for coverage in value["step_coverage"]:
        for key, kind in (("claim_ids", "claim"), ("dialogue_finding_ids", "language"), ("unknown_ids", "unknown")):
            for item_id in coverage[key]:
                if item_id not in rows or rows[item_id]["kind"] != kind or rows[item_id]["row"]["source_ref"] != coverage["source_ref"]:
                    raise ValueError("extract coverage links a missing or different-step finding")
                links.append(item_id)
    if len(links) != len(set(links)) or set(links) != set(rows):
        raise ValueError("extract coverage must link every finding exactly once")
    allowances = {row["id"]: row for row in projected["source_allowances"]}
    for finding in rows.values():
        row = finding["row"]
        _v8._actual_quote(row["source_ref"], row["quote"], entries)
        if finding["kind"] != "claim": continue
        if not row["attribute_value"].strip() or (row["attribute_type"] in _v9._LITERAL_TYPES
                                                and row["attribute_value"] not in row["quote"]):
            raise ValueError("actual business attribute must be an unchanged fragment of its actual quote")
        alignment = row["source_alignment"]
        allowance = allowances.get(alignment["allowance_id"])
        quote = alignment["source_attribute_quote"]
        if allowance:
            if allowance["category"] != finding["category"] or (quote and not _authenticated_allowance_quote(allowance, quote, brief)):
                raise ValueError("source alignment must cite its own category allowance value or bound original source quote")
        elif quote:
            raise ValueError("source alignment quote requires a real original allowance ID")
    return {"complete": True, "source_hash": _digest(value), "script_sha256": _digest(script),
        "brief_sha256": _digest(brief), "scope_sha256": _digest(scope), "step_count": len(entries),
        "all_performed_prose_language_checked": True, "semantic_quality_approved": False,
        "source_quote_authentication": "own_category_value_or_bound_source_quote", "native_detection_changed": False}


def build_adjudication_schema(extract, script, brief, scope):
    validate_fact_scope_extract(extract, script, brief, scope)
    ids = list(_findings(extract))
    fact_ids = list(v2._facts(brief))
    kinds = list(dict.fromkeys(kind for values in ATTRIBUTE_TYPES.values() for kind in values))
    row = base._obj({"finding_id": {"enum": ids} if ids else False,
        "disposition": {"enum": ["confirmed_violation", "context_or_source_supported", "unknown"]},
        "basis_kind": {"enum": ["sensitive_attribute_violation", "source_supported", "non_business_context",
                                  "language_error", "language_context_correct", "uncertain"]},
        "source_evidence": {"type": "array", "uniqueItems": True, "items": base._obj({
            "fact_id": {"enum": fact_ids} if fact_ids else False, "quote": base._text()})},
        "source_attribute_type": {"enum": kinds + ["context", "none", "unknown"]},
        "context_type": {"enum": ["employee_refusal", "current_intention", "physical_performance", "scene_timing",
                                    "private_pressure", "request_for_company_response", "existing_source_event"]},
        "source_attribute_quote": {"type": "string"}, "explanation": base._text()})
    row["required"].remove("context_type")
    row["allOf"] = [{"if": {"properties": {"disposition": {"const": "context_or_source_supported"}}},
        "then": {"properties": {"basis_kind": {"enum": ["source_supported", "non_business_context", "language_context_correct"]}}}},
        {"if": {"properties": {"disposition": {"const": "confirmed_violation"}}},
         "then": {"properties": {"basis_kind": {"enum": ["sensitive_attribute_violation", "language_error"]}}}},
        {"if": {"properties": {"disposition": {"const": "unknown"}}},
         "then": {"properties": {"basis_kind": {"const": "uncertain"}}}},
        {"if": {"properties": {"basis_kind": {"const": "non_business_context"}}},
         "then": {"required": ["context_type"], "properties": {"source_evidence": {"minItems": 1},
                                                                      "source_attribute_type": {"const": "context"}}}}]
    schema = base._obj({"extract_sha256": {"const": _digest(extract)}, "script_sha256": {"const": _digest(script)},
        "brief_sha256": {"const": _digest(brief)}, "scope_sha256": {"const": _digest(scope)},
        "findings": {"type": "array", "minItems": len(ids), "maxItems": len(ids), "items": row}})
    schema["properties"]["findings"]["description"] = (
        "语义验收兼容表不改变原wire：不合兼容须完整返修，不是接口错误。" +
        json.dumps(contextual_compatibility(extract, brief), ensure_ascii=False, separators=(",", ":")))
    fields = schema["properties"]["findings"]["items"]["properties"]
    fields["source_evidence"]["description"] = (
        "真实冻结fact来源。language_context_correct只能依实际正文，必须为空数组；否则整稿返修。")
    fields["source_attribute_quote"]["description"] = (
        "具体业务属性仍须真实源allowance.value片段；来源定位真实不代表语义许可。"
        "language_context_correct必须为空串，不能依brief改写实际原句施事。")
    return schema


def validate_adjudication(value, extract, script, brief, scope):
    base._validate_schema(build_adjudication_schema(extract, script, brief, scope), value, "finding_adjudication")
    findings = _findings(extract)
    ids = [row["finding_id"] for row in value["findings"]]
    if len(ids) != len(set(ids)) or set(ids) != set(findings):
        raise ValueError("adjudication must cover every original detection ID exactly once")
    facts = v2._facts(brief)
    for row in value["findings"]:
        for evidence in row["source_evidence"]:
            if not evidence["quote"].strip() or evidence["quote"] not in facts[evidence["fact_id"]]:
                raise ValueError("adjudication source quote must be an unchanged frozen fact fragment")
    return {"complete": True, "source_hash": _digest(value), "extract_sha256": _digest(extract),
        "script_sha256": _digest(script), "brief_sha256": _digest(brief), "scope_sha256": _digest(scope),
        "native_detection_changed": False, "semantic_quality_approved": False,
        "context_compatibility_sha256": _digest(contextual_compatibility(extract, brief)),
        "semantic_exemptions_checked_at_decision": True,
        "language_source_boundary_checked_at_decision": True,
        "source_quote_authentication": "own_category_value_or_bound_source_quote"}


def _decide_base_adjudication(value, extract, script, brief, scope):
    validation = validate_adjudication(value, extract, script, brief, scope)
    entries, findings = evidence_catalog(script), _findings(extract)
    projected = project_sensitive_scope(scope, brief)
    native_scope = _v8._native_scope(scope, brief)
    allowed_fact_ids = {fact_id for allowance in native_scope["allowed_claims"] for fact_id in allowance["source_fact_ids"]}
    requirements, uncertainties = [], []
    for verdict in value["findings"]:
        finding = findings[verdict["finding_id"]]
        row = finding["row"]
        disposition = verdict["disposition"]
        problem = verdict["explanation"]
        supported = disposition == "context_or_source_supported"
        if supported and finding["kind"] == "claim":
            evidence = verdict["source_evidence"]
            if verdict["basis_kind"] == "non_business_context":
                supported = (verdict["source_attribute_type"] == "context" and any(
                    item["fact_id"] in allowed_fact_ids for item in evidence))
            elif verdict["basis_kind"] == "source_supported":
                supported = verdict["source_attribute_type"] == row["attribute_type"] and any(
                    allowance["category"] == finding["category"]
                    and allowance["actor_id"] in ("", row["actor_id"])
                    and bool(verdict["source_attribute_quote"].strip())
                    and verdict["source_attribute_quote"] in allowance["value"]
                    and any(item["fact_id"] in allowance["source_fact_ids"] and
                            verdict["source_attribute_quote"] in item["quote"] for item in evidence)
                    for allowance in projected["source_allowances"])
            else: supported = False
            # Literal dates/amounts cannot be dismissed by a broad context claim.
            if row["attribute_type"] in _v9._LITERAL_TYPES:
                supported = supported and verdict["basis_kind"] == "source_supported" and (
                    _v9._compact(row["attribute_value"]) == _v9._compact(verdict["source_attribute_quote"]))
            if verdict["basis_kind"] != "non_business_context" and any(
                    rule["category"] == finding["category"] and rule["mode"] == "absence"
                    for rule in projected["restrictions"]): supported = False
        elif supported and finding["kind"] == "language":
            supported = verdict["basis_kind"] == "language_context_correct"
        elif supported:
            supported = verdict["basis_kind"] in ("source_supported", "non_business_context", "language_context_correct")
            if verdict["basis_kind"] != "language_context_correct": supported = supported and bool(verdict["source_evidence"])
        if disposition == "unknown":
            target, code = uncertainties, "ADJUDICATION_UNKNOWN_" + row["id"]
        elif disposition == "confirmed_violation" or not supported:
            target, code = requirements, ("LANGUAGE_FOCUSED_" if finding["kind"] == "language" else "FACT_SCOPE_") + row["id"]
            if disposition != "confirmed_violation": problem = "裁决未提供符合该具体敏感属性的真实源支持：" + problem
        else: continue
        v2._add(target, entries, code, [row["source_ref"]], problem, FROZEN_SOURCE_REPAIR)
        target[-1].update(finding_id=row["id"], extracted_quote=row["quote"], disposition=disposition,
                          source_evidence=deepcopy(verdict["source_evidence"]))
    result = v2._result("adjudication", value, script, validation, requirements, uncertainties)
    result.update(extract_sha256=_digest(extract), scope_sha256=_digest(scope), native_detection_changed=False)
    return _fail_first(result)


def _decide_context_adjudication(value, extract, script, brief, scope):
    validation = validate_adjudication(value, extract, script, brief, scope)
    result = _decide_base_adjudication(value, extract, script, brief, scope)
    findings = _findings(extract)
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
    return _fail_first(result)


def decide_adjudication(value, extract, script, brief, scope):
    result = _decide_context_adjudication(value, extract, script, brief, scope)
    result["validation"] = validate_adjudication(value, extract, script, brief, scope)
    findings = _findings(extract)
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
    return _fail_first(result)


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
    return _fail_first(result)


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


def decide_fact_scope_extract(value, script, brief, scope):
    """Conservative unadjudicated route; never release detections unaudited."""
    validation = validate_fact_scope_extract(value, script, brief, scope)
    rows = _findings(value)
    return {"status": "halt_review_uncertain" if rows else "text_ready_for_director",
        "validation": validation, "script_sha256": _digest(script), "extract_sha256": _digest(value),
        "revision_requirements": [], "uncertainties": [{"code": "FINDING_ADJUDICATION_REQUIRED", "finding_id": key}
                                                         for key in rows],
        "human_quality_approved": False, "human_approved": False, "creative_quality_passed": False,
        "automatic_media_submit": False}
