"""Isolated candidate: independently classify atomic detected propositions.

No production runner imports this module. Detector metadata is preserved as
provenance; accurate semantic atom/source classification remains model work.
Local checks bind whole sources, quote coverage, actor roles and literal values.
"""
from __future__ import annotations

from copy import deepcopy
from . import creative_autonomous_text_contract_v13 as source
from . import creative_autonomous_text_contract_v10 as detection
from . import creative_autonomous_text_contract_v9 as attribute_contract
from . import creative_autonomous_text_contract_v1 as base

VERSION = "creative_claim_atoms_candidate/v1"
ATTRIBUTE_TYPES = sorted({q for types in attribute_contract.ATTRIBUTE_TYPES.values() for q in types})
CONTEXTS = ("none", "private_request", "current_signature_request", "employee_refusal", "current_intention", "request_for_company_response", "physical_performance", "scene_timing")
KINDS = ("business_assertion", "non_business_action", "language_error", "unknown")
RELATIONS = ("source_supported", "unsupported", "unknown")
_IGNORED_COVERAGE = set(" \r\n\t，。；、！？：,.!?;:\"“”‘’（）()")
_CONTEXT_SPEECH = {"private_request": {"request"}, "current_signature_request": {"request"}, "employee_refusal": {"refusal"},
    "current_intention": {"statement", "refusal"}, "request_for_company_response": {"request", "question"},
    "physical_performance": {"action"}, "scene_timing": {"statement", "action"}}
_CONTEXT_SOURCE = {"private_request": {"private_pressure", "follow_up_undertaking"},
    "current_signature_request": {"procedural_action", "document_fact"}, "employee_refusal": {"employee_intention"},
    "current_intention": {"employee_intention"}, "request_for_company_response": {"employee_intention", "procedural_action"},
    "physical_performance": {"procedural_action", "performance_action", "document_fact"}, "scene_timing": {"scene_time", "performance_action"}}
RULE = (
    "原检测只提出待核命题，类型/类别/业务主体不是不可更正的语义事实；原记录不改。"
    "逐原finding_id独立提取全部实际子命题或言语行动，用原quote精确起止片段覆盖，不能漏掉相邻准备状态、期限、办理保证。"
    "actual_actor_id取实际说话/行动者；represented_actor_id另记公司等被转述业务主体，不拿公司替代人事本人说话。"
    "每子项区分business_assertion、non_business_action、language_error、unknown；当前签字请求与准备状态、私下求情与未来办理承诺分别判断。"
    "private_request不能授权邻接业务承诺。当前请求须同施事实际来源行动；准备状态无来源则unknown，不因请求正常就整体pass。"
    "来源支持逐子项判其source_claim_kind/type/value，真引用和泛类别不证明存在具体业务属性。"
    "业务保证需具体来源业务原子，不可用私人请托或物理行动作业务许可；原日期金额字面风险必须保留相应属性原子，不能用context略去。"
    "语言判断只依据实际正文；未知如实保留。不得代写正文、修改检测或声称人工质量通过。")


def _digest(value):
    return base._digest(value)


def _inputs(extract, script, brief, scope):
    source.validate_fact_scope_extract(extract, script, brief, scope)
    source.project_sensitive_scope(scope, brief)
    findings = detection._findings(extract)
    catalog = source.evidence_catalog(script)
    facts = {q["id"]: q["text"] for q in brief.get("facts", [])}
    allowances = {q["id"]: q for q in scope["allowed_claims"]}
    for allowance in allowances.values():
        for ref in allowance["source_quotes"]:
            if ref["fact_id"] not in allowance["source_fact_ids"] or not ref["quote"].strip() or ref["quote"] not in facts[ref["fact_id"]]:
                raise ValueError("source citation must remain in its bound frozen fact")
    return findings, catalog, facts, allowances


def build_schema(extract, script, brief, scope):
    findings, catalog, _, allowances = _inputs(extract, script, brief, scope)
    actors = sorted(set(base._characters(brief)) | {q["id"] for q in brief.get("actors", [])})
    support = base._obj({"allowance_id": {"enum": list(allowances)} if allowances else False,
        "source_quote": base._text(), "source_claim_kind": {"enum": ["business_assertion", "non_business_action", "unknown"]},
        "source_attribute_type": {"enum": ATTRIBUTE_TYPES + ["none", "unknown"]}, "source_attribute_value": {"type": "string"}})
    variants = []
    for key, finding in findings.items():
        entry = catalog[finding["row"]["source_ref"]]
        atom = base._obj({"id": base._text(), "quote_start": {"type": "integer", "minimum": 0},
            "quote_end": {"type": "integer", "minimum": 1}, "quote": base._text(),
            "actual_actor_id": {"const": entry["speaker"]} if entry["kind"] == "dialogue" else {"enum": actors + [""]},
            "represented_actor_id": {"enum": actors + [""]}, "speech_function": {"enum": ["statement", "request", "refusal", "question", "action", "unknown"]},
            "claim_kind": {"enum": list(KINDS)}, "context_action": {"enum": list(CONTEXTS)},
            "business_attribute_type": {"enum": ATTRIBUTE_TYPES + ["none", "unknown"]}, "attribute_value": {"type": "string"},
            "source_support": {"type": "array", "items": deepcopy(support), "uniqueItems": True},
            "source_relation": {"enum": list(RELATIONS)}, "explanation": base._text()})
        atom["properties"]["quote"]["description"] = "原finding.quote的[quote_start:quote_end]真实原文，全部子项覆盖不能静默漏命题。"
        atom["properties"]["source_support"]["description"] = "该allowance已登记source_quotes里的真实冻结原片段；不能仅引用归一value。source类型独立判定，不能借context免业务保证。"
        atom["allOf"] = [
            {"if": {"properties": {"claim_kind": {"const": "non_business_action"}}, "required": ["claim_kind"]},
             "then": {"properties": {"business_attribute_type": {"const": "none"}, "attribute_value": {"const": ""},
                 "context_action": {"enum": list(CONTEXTS[1:])}}}},
            {"if": {"properties": {"claim_kind": {"const": "business_assertion"}}, "required": ["claim_kind"]},
             "then": {"properties": {"business_attribute_type": {"enum": ATTRIBUTE_TYPES},
                 "attribute_value": {"type": "string", "minLength": 1}, "context_action": {"const": "none"}}}},
        ]
        atoms = {"type": "array", "minItems": 1, "items": atom}
        if finding["row"].get("attribute_type") in attribute_contract._LITERAL_TYPES:
            atoms["allOf"] = [{"contains": {"type": "object", "properties": {
                "claim_kind": {"enum": ["business_assertion", "unknown"]},
                "business_attribute_type": {"const": finding["row"]["attribute_type"]},
                "attribute_value": {"const": finding["row"]["attribute_value"]}},
                "required": ["claim_kind", "business_attribute_type", "attribute_value"]}, "minContains": 1}]
        variants.append(base._obj({"finding_id": {"const": key}, "atoms": atoms}))
    table = {"type": "array", "minItems": len(findings), "maxItems": len(findings),
        "items": {"oneOf": variants} if variants else False,
        "allOf": [{"contains": {"type": "object", "properties": {"finding_id": {"const": key}}, "required": ["finding_id"]},
                   "minContains": 1, "maxContains": 1} for key in findings]}
    return base._obj({"extract_sha256": {"const": _digest(extract)}, "script_sha256": {"const": _digest(script)},
        "brief_sha256": {"const": _digest(brief)}, "scope_sha256": {"const": _digest(scope)}, "findings": table})


def _true_source_fragment(quote, allowance):
    return bool(quote.strip()) and any(quote in q["quote"] for q in allowance["source_quotes"])


def validate(value, extract, script, brief, scope):
    base._validate_schema(build_schema(extract, script, brief, scope), value, "claim_atoms")
    findings, _, _, allowances = _inputs(extract, script, brief, scope)
    atom_ids, count = [], 0
    for verdict in value["findings"]:
        original = findings[verdict["finding_id"]]["row"]["quote"]
        covered = set()
        for atom in verdict["atoms"]:
            atom_ids.append(atom["id"]); count += 1
            start, end = atom["quote_start"], atom["quote_end"]
            if not 0 <= start < end <= len(original) or original[start:end] != atom["quote"]:
                raise ValueError("atomic quote span must be unchanged original finding evidence")
            covered.update(range(start, end))
            if atom["claim_kind"] == "business_assertion" and atom["attribute_value"] not in atom["quote"]:
                raise ValueError("business attribute must remain an actual atom quote fragment")
            for support in atom["source_support"]:
                if not _true_source_fragment(support["source_quote"], allowances[support["allowance_id"]]):
                    raise ValueError("source quote must belong to its own registered allowance")
                if support["source_claim_kind"] == "business_assertion" and (
                    support["source_attribute_type"] not in ATTRIBUTE_TYPES or not support["source_attribute_value"].strip() or
                    support["source_attribute_value"] not in support["source_quote"]):
                    raise ValueError("source business atom needs its own actual typed attribute")
        if any(i not in covered and char not in _IGNORED_COVERAGE for i, char in enumerate(original)):
            raise ValueError("atomic coverage cannot omit original sub-propositions")
    if len(atom_ids) != len(set(atom_ids)):
        raise ValueError("atom IDs must be globally unique")
    return {"complete": True, "atom_count": count, "source_hash": _digest(value),
        "extract_sha256": _digest(extract), "script_sha256": _digest(script), "brief_sha256": _digest(brief),
        "scope_sha256": _digest(scope), "original_detection_changed": False, "semantic_quality_proven": False}


def _context_supported(atom, allowances):
    if atom["speech_function"] not in _CONTEXT_SPEECH.get(atom["context_action"], set()): return False
    return any(support["source_claim_kind"] == "non_business_action" and
        allowances[support["allowance_id"]]["category"] in _CONTEXT_SOURCE.get(atom["context_action"], set()) and
        allowances[support["allowance_id"]]["actor_id"] in ("", atom["actual_actor_id"])
        for support in atom["source_support"])


def _business_supported(atom, scope, brief, allowances):
    projected = source.project_sensitive_scope(scope, brief)
    category = next(key for key, values in attribute_contract.ATTRIBUTE_TYPES.items() if atom["business_attribute_type"] in values)
    if any(q["category"] == category and q["mode"] == "absence" for q in projected["restrictions"]): return False
    actor = atom["represented_actor_id"] or atom["actual_actor_id"]
    projected_allowances = {q["id"]: q for q in projected["source_allowances"]}
    for support in atom["source_support"]:
        allowance = allowances[support["allowance_id"]]
        projected_allowance = projected_allowances.get(support["allowance_id"])
        if (support["source_claim_kind"] != "business_assertion" or support["source_attribute_type"] != atom["business_attribute_type"]
                or not projected_allowance or projected_allowance["category"] != category or allowance["actor_id"] not in ("", actor)):
            continue
        if atom["business_attribute_type"] in attribute_contract._LITERAL_TYPES and (
                "".join(atom["attribute_value"].split()) != "".join(support["source_attribute_value"].split())):
            continue
        return True
    return False


def decide(value, extract, script, brief, scope):
    validation = validate(value, extract, script, brief, scope)
    findings, catalog, _, allowances = _inputs(extract, script, brief, scope)
    failures, uncertainties = [], []
    for verdict in value["findings"]:
        original = findings[verdict["finding_id"]]
        for atom in verdict["atoms"]:
            if atom["source_relation"] == "unknown" or atom["claim_kind"] == "unknown":
                target = uncertainties
            elif atom["source_relation"] == "unsupported" or atom["claim_kind"] == "language_error":
                target = failures
            elif atom["claim_kind"] == "non_business_action":
                target = None if _context_supported(atom, allowances) else failures
            else:
                target = None if _business_supported(atom, scope, brief, allowances) else failures
            if target is None: continue
            entry = catalog[original["row"]["source_ref"]]
            target.append({"code": "CLAIM_ATOM_" + verdict["finding_id"] + "_" + atom["id"],
                "finding_id": verdict["finding_id"], "atom_id": atom["id"], "quote": atom["quote"],
                "source_ref": original["row"]["source_ref"], "path": entry["path"],
                "actual_claim_kind": atom["claim_kind"], "problem": atom["explanation"],
                "required_revision": source.FROZEN_SOURCE_REPAIR})
    return {"status": "needs_whole_revision" if failures else "halt_review_uncertain" if uncertainties else "claim_atoms_ready",
        "validation": validation, "revision_requirements": failures, "uncertainties": uncertainties,
        "original_detection": deepcopy(extract), "original_detection_sha256": _digest(extract),
        "original_detection_changed": False, "candidate_not_integrated_into_production": True,
        "semantic_quality_proven": False, "human_quality_approved": False}
