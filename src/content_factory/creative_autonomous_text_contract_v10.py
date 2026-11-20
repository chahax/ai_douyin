"""Independent, source-bound adjudication of immutable sparse detector findings.

Language findings may cite any actual performed prose. Detection, adjudication
and compiled decisions are separate artifacts; no native finding is removed.
Known semantic violations are repaired first, and unresolved uncertainty can
never become a ready result. Frozen v1-v9 are unchanged.
"""
from __future__ import annotations
from copy import deepcopy
from . import creative_autonomous_text_contract_v9 as prior

for _name in ("base", "v2", "CRITERIA", "FUNCTIONS", "_digest", "FROZEN_SOURCE_REPAIR", "FROZEN_PLAN_REPAIR",
    "build_plan_schema", "compile_plan", "validate_plan", "build_script_schema", "compile_script",
    "evidence_catalog", "build_source_audit_schema", "compile_source_audit", "validate_source_audit",
    "decide_source_audit", "build_review_schema", "compile_review", "validate_review", "decide_review",
    "project_legacy_review", "project_legacy_audit", "build_source_fact_scope_schema",
    "validate_source_fact_scope", "compile_source_fact_scope", "SOURCE_SCOPE_RULE", "project_sensitive_scope",
    "ATTRIBUTE_TYPES", "FACT_CATEGORIES", "MODALITIES", "build_fact_scope_schema", "build_audit_schema",
    "compile_audit", "validate_audit", "decide_audit", "derive_event_evidence", "combine_decisions", "AUDIT_RULE"):
    globals()[_name] = getattr(prior, _name)
VERSION = "creative_autonomous_text_contract/v10"
FACT_SCOPE_RULE = prior.FACT_SCOPE_RULE.replace(
    "attribute_value引用正文中具体属性原文，不写整句归一命题；quote用唯一完整原文子句。",
    "日期、金额、期限的attribute_value必须是正文具体原文字面；其余业务语义属性可用归一命题，"
    "不能删限定语或改变承担人，始终以唯一真实quote为裁决依据。") + (
    "dialogue_findings字段沿用旧名称，可记录动作叙述等全部实际正文的语言问题；不能删除动作里的真实语病。")
ADJUDICATION_RULE = (
    "你是独立发现裁决员，完整读取同一冻结brief、正文和检测，逐原finding ID裁决，不修改原检测或正文。"
    "检测不是结论：区分人物正常拒签/意愿、现场动作、私人劝说与真实新增业务期限、规定、后续承担。"
    "confirmed_violation只用于有确切正文及源证据的违规或语病；context_or_source_supported须说明该发现为什么误报，"
    "并给真实source_evidence原文；拒签意愿应根据人物已给拒绝/未签源事实，不能仅凭整体剧情猜。"
    "同类别ID不能证明业务属性获允许。实际日期、金额、期限必须有具体源允许字面值，不能以情境或原请求放行。"
    "手续签完就结束等新增办理规定、本人以后向公司解释等业务未来行动，不能用源里的私人请托作业务授权。"
    "询问/期望公司解释不等于本人承诺解释；正常拒签也不等于新增法律规则。"
    "source_attribute_type=context表示原行为不是敏感业务属性；敏感来源支持须有具体同类型行为/规定的真实原文。"
    "non_business_context必须给context_type及实际正文解释，并指出真实源依据；不能只拿任意F3或整体主题免掉业务安排。"
    "语言发现可引用动作叙述及对白全部实际正文；独立复核语境、指代和句法，不能只看摘要把真实语病放行。"
    "source_attribute_quote仅填真实源allowance.value里的具体属性片段，source_evidence引用真实fact原文，禁止复述。"
    "判断未知如实unknown；检测未知若重复已知unsupported发现可据实confirmed，不重复保留同一问题未知；"
    "不得替编剧写补丁、替代台词或虚构人工批准。"
)


def validate_fact_scope_extract(value, script, brief, scope):
    """Same v9 wire/source checks, without its hidden spoken-only restriction."""
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
        prior.prior._actual_quote(row["source_ref"], row["quote"], entries)
        if finding["kind"] != "claim": continue
        if not row["attribute_value"].strip() or (row["attribute_type"] in prior._LITERAL_TYPES
                                                and row["attribute_value"] not in row["quote"]):
            raise ValueError("actual business attribute must be an unchanged fragment of its actual quote")
        alignment = row["source_alignment"]
        allowance = allowances.get(alignment["allowance_id"])
        quote = alignment["source_attribute_quote"]
        if allowance:
            if allowance["category"] != finding["category"] or (quote and quote not in allowance["value"]):
                raise ValueError("source alignment must cite its own original category allowance value")
        elif quote:
            raise ValueError("source alignment quote requires a real original allowance ID")
    return {"complete": True, "source_hash": _digest(value), "script_sha256": _digest(script),
        "brief_sha256": _digest(brief), "scope_sha256": _digest(scope), "step_count": len(entries),
        "all_performed_prose_language_checked": True, "semantic_quality_approved": False}


def _findings(extract):
    result = {row["id"]: {"kind": "claim", "category": category, "row": row}
              for category, row in prior._claims(extract)}
    for table, kind in (("dialogue_findings", "language"), ("unknown_items", "unknown")):
        for row in extract[table]: result[row["id"]] = {"kind": kind, "category": "", "row": row}
    return result


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
    return base._obj({"extract_sha256": {"const": _digest(extract)}, "script_sha256": {"const": _digest(script)},
        "brief_sha256": {"const": _digest(brief)}, "scope_sha256": {"const": _digest(scope)},
        "findings": {"type": "array", "minItems": len(ids), "maxItems": len(ids), "items": row}})


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
        "native_detection_changed": False, "semantic_quality_approved": False}


def _fail_first(result):
    if result["revision_requirements"]: result["status"] = "needs_whole_revision"
    result["known_semantic_violation_repaired_before_uncertainty"] = True
    return result


def decide_adjudication(value, extract, script, brief, scope):
    validation = validate_adjudication(value, extract, script, brief, scope)
    entries, findings = evidence_catalog(script), _findings(extract)
    projected = project_sensitive_scope(scope, brief)
    native_scope = prior.prior._native_scope(scope, brief)
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
            if row["attribute_type"] in prior._LITERAL_TYPES:
                supported = supported and verdict["basis_kind"] == "source_supported" and (
                    prior._compact(row["attribute_value"]) == prior._compact(verdict["source_attribute_quote"]))
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


def combine_adjudicated_decisions(review, audit, extract, adjudication, script, brief, plan, scope):
    primary = combine_decisions(review, audit, script, brief, plan)
    focused = decide_adjudication(adjudication, extract, script, brief, scope)
    values = {"review": review, "audit": audit, "extract": extract, "adjudication": adjudication}
    result = v2._result("combined", values, script, {"complete": True, "source_hash": _digest(values),
        "primary_and_literal": primary["validation"], "independent_adjudication": focused["validation"]},
        primary["revision_requirements"] + focused["revision_requirements"],
        primary["uncertainties"] + focused["uncertainties"])
    result.update(plan_sha256=_digest(plan), scope_sha256=_digest(scope), extract_sha256=_digest(extract),
        adjudication_sha256=_digest(adjudication), native_detection_changed=False,
        independent_finding_adjudication_required=True, event_evidence=primary["event_evidence"])
    return _fail_first(result)


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
