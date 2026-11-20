"""Independent literal checks for autonomous text; frozen v1 stays unchanged.

Review and literal audit are separate complete model responses. Schemas enforce
coverage and source identity, while decisions route explicit fail/unknown
findings. Neither checker edits prose or grants human quality approval.
"""
from __future__ import annotations

from copy import deepcopy

from . import creative_autonomous_text_contract_v1 as base

VERSION = "creative_autonomous_text_contract/v2"
CRITERIA = {**base.CRITERIA,
    "language_integrity": "逐字核对错别字、词义和语病；明确语言错误必须修复，不能仅放审美建议。"}
build_plan_schema = base.build_plan_schema
build_script_schema = base.build_script_schema
validate_plan = base.validate_plan
compile_script = base.compile_script
evidence_catalog = base.evidence_catalog
_digest = base._digest


def _facts(brief):
    rows = brief.get("facts", [])
    if not isinstance(rows, list):
        raise ValueError("brief.facts must be an array")
    result = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"].strip():
            raise ValueError("every fact needs an ID")
        if not isinstance(row.get("text"), str) or not row["text"].strip():
            raise ValueError("every fact needs its explicit source text")
        if row["id"] in result:
            raise ValueError("fact IDs must be unique")
        result[row["id"]] = row["text"]
    return result


def _states(brief):
    state = brief.get("initial_state", {})
    if not isinstance(state, dict):
        raise ValueError("brief.initial_state must be an object")
    result = {}
    for kind, keys in (("character", ("character_states", "characters")),
                       ("prop", ("prop_states", "props"))):
        present = [key for key in keys if key in state]
        if len(present) > 1:
            raise ValueError("initial state aliases cannot both be supplied")
        rows = state.get(present[0], []) if present else []
        if not isinstance(rows, list):
            raise ValueError("initial states must be arrays")
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"].strip():
                raise ValueError("every initial-state entity needs an ID")
            expected = row.get("expected_state")
            if not isinstance(expected, str) or not expected.strip():
                raise ValueError("every initial-state entity needs expected_state")
            key = (kind, row["id"])
            if key in result:
                raise ValueError("initial-state entities must be unique")
            if kind == "character" and row["id"] not in base._characters(brief):
                raise ValueError("initial-state character is not allowed by the brief")
            result[key] = expected
    return result


def _checks_schema(script, brief):
    refs = base._array_refs(list(evidence_catalog(script)))
    facts = _facts(brief)
    states = _states(brief)
    fact = base._obj({
        "fact_id": {"enum": list(facts)} if facts else False,
        "expected_fact": base._text(), "observed_fact": base._text(),
        "status": {"enum": ["pass", "fail", "unknown"]},
        "evidence_refs": deepcopy(refs), "required_revision": {"type": "string"},
    })
    state = base._obj({
        "entity_type": {"enum": ["character", "prop"]},
        "entity_id": {"enum": list(dict.fromkeys(key[1] for key in states))} if states else False,
        "expected_state": base._text(), "observed_state": base._text(),
        "status": {"enum": ["pass", "fail", "unknown"]},
        "evidence_refs": deepcopy(refs), "required_revision": {"type": "string"},
    })
    return {
        "fact_checks": {"type": "array", "minItems": len(facts),
                        "maxItems": len(facts), "items": fact},
        "initial_state_checks": {"type": "array", "minItems": len(states),
                                 "maxItems": len(states), "items": state},
    }


def build_review_schema(script, brief):
    schema = base.build_review_schema(script, brief)
    schema["properties"]["criteria"].update(minItems=len(CRITERIA), maxItems=len(CRITERIA))
    row = schema["properties"]["criteria"]["items"]
    row["properties"]["criterion"] = {"enum": list(CRITERIA)}
    schema["properties"].update(_checks_schema(script, brief))
    schema["required"].extend(["fact_checks", "initial_state_checks"])
    suggestion = schema["properties"]["suggestions"]["items"]
    suggestion["properties"]["finding_type"] = {"enum": ["optional_style", "language_error", "uncertain"],
        "description": "uncertain只用于影响必需语义、事实或语言判断的未知；未拿准的审美润色仍为optional_style。明确错字语病为language_error。"}
    suggestion["required"].append("finding_type")
    return schema


def _check_tables(value, script, brief):
    facts = _facts(brief)
    ids = [row["fact_id"] for row in value["fact_checks"]]
    if len(ids) != len(set(ids)) or set(ids) != set(facts):
        raise ValueError("fact_checks must cover every brief fact exactly once")
    for row in value["fact_checks"]:
        if row["expected_fact"] != facts[row["fact_id"]]:
            raise ValueError("fact check changed the brief's expected source fact")
    states = _states(brief)
    keys = [(row["entity_type"], row["entity_id"]) for row in value["initial_state_checks"]]
    if len(keys) != len(set(keys)) or set(keys) != set(states):
        raise ValueError("initial_state_checks must cover every declared entity exactly once")
    for row in value["initial_state_checks"]:
        if row["expected_state"] != states[(row["entity_type"], row["entity_id"])]:
            raise ValueError("initial-state check changed the brief's expected state")
    return {"fact_count": len(facts), "initial_entity_count": len(states)}


def _base_review(value):
    projected = {key: deepcopy(value[key]) for key in
                 ("script_sha256", "criteria", "dialogue_readings", "issues", "suggestions")}
    projected["criteria"] = [row for row in projected["criteria"]
                             if row["criterion"] != "language_integrity"]
    for row in projected["suggestions"]:
        row.pop("finding_type")
    return projected


def validate_review(value, script, brief):
    base._validate_schema(build_review_schema(script, brief), value, "review")
    keys = [row["criterion"] for row in value["criteria"]]
    if len(keys) != len(set(keys)) or set(keys) != set(CRITERIA):
        raise ValueError("review.criteria must cover all seven criteria exactly once")
    validation = base.validate_review(_base_review(value), script, brief)
    return {**validation, **_check_tables(value, script, brief),
            "source_hash": _digest(value), "criteria_count": len(CRITERIA),
            "explicit_language_errors_mandatory": True}


def build_audit_schema(script, brief):
    entries = evidence_catalog(script)
    event = base._obj({
        "source_ref": {"enum": list(entries)}, "kind": {"enum": ["action", "dialogue"]},
        "speaker": {"enum": base._characters(brief) + [""]},
        "event_type": base._text(), "actual_action": base._text(),
        "speech_function": {"enum": ["action", "statement", "question", "request", "refusal", "other"],
            "description": "question包括质问和反问；含否定词不等于refusal。只有实际原句表达不实施对方要求时才是refusal，不能用event或premise补出拒绝。"},
        "negative_or_refusal": {"type": "boolean",
            "description": "泛否定或拒绝的记录，不单独证明明确拒绝；必须结合speech_function和当前实际原句。"},
        "props_origin": {"type": "string"}, "props_destination": {"type": "string"},
    })
    return base._obj({
        "script_sha256": {"const": _digest(script)}, **_checks_schema(script, brief),
        "literal_events": {"type": "array", "minItems": len(entries),
                           "maxItems": len(entries), "items": event},
    })


def validate_audit(value, script, brief):
    body = {key: deepcopy(val) for key, val in script.items() if key != "selected_candidate_id"}
    if compile_script(body, brief) != script:
        raise ValueError("audit script differs from compiler-bound complete source")
    base._validate_schema(build_audit_schema(script, brief), value, "audit")
    entries = evidence_catalog(script)
    ids = [row["source_ref"] for row in value["literal_events"]]
    if ids != list(entries):
        raise ValueError("literal_events must cover every performed step exactly once in actual source order")
    for row in value["literal_events"]:
        original = entries[row["source_ref"]]
        if row["kind"] != original["kind"] or row["speaker"] != original["speaker"]:
            raise ValueError("literal event changed the actual source kind or speaker")
        if row["kind"] == "action" and row["speech_function"] != "action":
            raise ValueError("literal action cannot be classified as a spoken refusal")
        if row["kind"] == "dialogue" and row["speech_function"] == "action":
            raise ValueError("literal dialogue cannot be classified as a source action step")
        if row["speech_function"] == "refusal" and row["negative_or_refusal"] is not True:
            raise ValueError("literal refusal conflicts with negative_or_refusal flag")
    return {"source_hash": _digest(value), "script_sha256": _digest(script),
            "brief_sha256": _digest(brief), "complete": True,
            "literal_step_count": len(ids), **_check_tables(value, script, brief),
            "performed_step_evidence_only": True, "semantic_quality_approved": False}


def _add(target, entries, code, refs, problem, revision):
    evidence = [{"ref_id": ref, "path": entries[ref]["path"], "quote": entries[ref]["quote"]}
                for ref in refs]
    target.append({"code": code, "evidence_refs": evidence,
                   "evidence_text": "\n".join(row["quote"] for row in evidence),
                   "problem": problem, "required_revision": revision})


def _table_decisions(value, entries, requirements, uncertainties):
    for row in value["fact_checks"]:
        if row["status"] == "pass":
            continue
        target = uncertainties if row["status"] == "unknown" else requirements
        _add(target, entries, "FACT_" + row["fact_id"], row["evidence_refs"],
             "来源要求：" + row["expected_fact"] + "；正文观察：" + row["observed_fact"],
             row["required_revision"] or "完整新稿中兑现该来源事实，不用摘要代替实际对白或动作。")
    for row in value["initial_state_checks"]:
        if row["status"] == "pass":
            continue
        target = uncertainties if row["status"] == "unknown" else requirements
        _add(target, entries, "INITIAL_" + row["entity_type"].upper() + "_" + row["entity_id"],
             row["evidence_refs"], "初始要求：" + row["expected_state"] +
             "；正文观察：" + row["observed_state"], row["required_revision"] or
             "完整新稿从已声明起态开始，不凭空增加拿取、翻转或角色站坐变化。")


def _result(kind, value, script, validation, requirements, uncertainties):
    requirements = list({_digest(row): row for row in requirements}.values())
    return {"status": "halt_review_uncertain" if uncertainties else
            "needs_whole_revision" if requirements else "text_ready_for_director",
            "script_sha256": _digest(script), kind + "_sha256": _digest(value),
            "validation": validation, "revision_requirements": requirements,
            "uncertainties": uncertainties, "human_quality_approved": False,
            "human_approved": False, "creative_quality_passed": False,
            "automatic_media_submit": False,
            "decision_basis": "explicit_same_source_review_and_literal_facts_not_human_adoption"}


def decide_review(review, script, brief):
    validation = validate_review(review, script, brief)
    inherited = base.decide_review(_base_review(review), script, brief)
    requirements = deepcopy(inherited["revision_requirements"])
    uncertainties = deepcopy(inherited["uncertainties"])
    entries = evidence_catalog(script)
    _table_decisions(review, entries, requirements, uncertainties)
    language = next(row for row in review["criteria"] if row["criterion"] == "language_integrity")
    if language["status"] != "pass":
        target = uncertainties if language["status"] == "unknown" else requirements
        _add(target, entries, "LANGUAGE_INTEGRITY", language["evidence_refs"], language["explanation"],
             language["required_revision"] or "由生成模型提交完整新稿，修复真实错字、词义或语法错误。")
    for row in review["suggestions"]:
        if row["finding_type"] == "language_error":
            _add(requirements, entries, "LANGUAGE_ERROR_" + row["code"], row["evidence_refs"],
                 row["assessment"], "完整新稿修复已明确发现的语言错误，不能仅以审美建议放行。")
        elif row["finding_type"] == "uncertain":
            _add(uncertainties, entries, "SUGGESTION_UNCERTAIN_" + row["code"], row["evidence_refs"],
                 row["assessment"], "核实该疑义，不能将未知意见转为文本通过。")
    return _result("review", review, script, validation, requirements, uncertainties)


def decide_audit(audit, script, brief):
    validation = validate_audit(audit, script, brief)
    requirements, uncertainties = [], []
    _table_decisions(audit, evidence_catalog(script), requirements, uncertainties)
    return _result("audit", audit, script, validation, requirements, uncertainties)


def combine_decisions(review, audit, script, brief):
    primary = decide_review(review, script, brief)
    literal = decide_audit(audit, script, brief)
    requirements = primary["revision_requirements"] + literal["revision_requirements"]
    uncertainties = primary["uncertainties"] + literal["uncertainties"]
    result = _result("combined", {"review": review, "audit": audit}, script,
                     {"complete": True, "source_hash": _digest({"review": review, "audit": audit}),
                      "primary_review": primary["validation"], "literal_audit": literal["validation"]},
                     requirements, uncertainties)
    result.update(review_sha256=_digest(review), audit_sha256=_digest(audit),
                  both_same_source_checks_required=True)
    return result
