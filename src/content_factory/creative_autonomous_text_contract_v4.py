"""Atomic source speech acts, with literal multi-function dialogue evidence.

Frozen v1-v3 are unchanged. Source events have one required function; an actual
utterance may perform several functions. Only source-required strict ordering
or explicit distinctness requires separate occurrences.
"""
from __future__ import annotations

from copy import deepcopy
from . import creative_autonomous_text_contract_v3 as prior

base = prior.base
v2 = prior.prior
VERSION = "creative_autonomous_text_contract/v4"
CRITERIA = deepcopy(prior.CRITERIA)
FUNCTIONS = list(prior.FUNCTIONS)
build_script_schema = prior.build_script_schema
compile_script = prior.compile_script
evidence_catalog = prior.evidence_catalog
build_review_schema = prior.build_review_schema
validate_review = prior.validate_review
decide_review = prior.decide_review
_digest = prior._digest
FROZEN_SOURCE_REPAIR = prior.FROZEN_SOURCE_REPAIR


def build_plan_schema(brief):
    schema = prior.build_plan_schema(brief)
    obligation = schema["properties"]["source_obligations"]["items"]
    obligation["allOf"] = [{
        "if": {"properties": {"mode": {"const": "event"}}},
        "then": {
            "properties": {"allowed_speech_functions": {"maxItems": 1}},
            "allOf": [
                {"if": {"properties": {"required_kind": {"const": "action"}}},
                 "then": {"properties": {"allowed_speech_functions": {
                     "type": "array", "minItems": 1, "maxItems": 1,
                     "items": {"const": "action"}}}}},
                {"if": {"properties": {"required_kind": {"const": "dialogue"}}},
                 "then": {"properties": {"allowed_speech_functions": {
                     "type": "array", "minItems": 1, "maxItems": 1,
                     "items": {"enum": [f for f in FUNCTIONS if f != "action"]}}}}},
            ],
        },
    }]
    obligation["properties"]["allowed_speech_functions"]["description"] = (
        "event义务仅一个行事功能，不用question/refusal/statement的OR混合掩盖缺失；"
        "同一fact可拆多个原子义务，同一真实对白可兑现多个义务。")
    schema["properties"]["source_order"]["description"] = (
        "端点必须均为mode=event的已知义务，不能连state或absence。"
        "只写来源必要的严格先后，不把同句可同时完成的告知/请求拆成先后。")
    return schema


def validate_plan(value, brief):
    base._validate_schema(build_plan_schema(brief), value, "plan")
    validation = prior.validate_plan(value, brief)
    obligations = {row["id"]: row for row in value["source_obligations"]}
    for edge in value["source_order"]:
        if any(obligations[edge[key]]["mode"] != "event" for key in ("before_id", "after_id")):
            raise ValueError("strict source_order endpoints must both be event obligations, not state or absence")
    return {**validation, "source_hash": _digest(value),
            "atomic_event_function_required": True, "strict_order_event_endpoints_only": True}


def build_audit_schema(script, brief, plan):
    validate_plan(plan, brief)
    schema = prior.build_audit_schema(script, brief, plan)
    event = schema["properties"]["literal_events"]["items"]
    event["properties"]["speech_functions"] = {
        "type": "array", "minItems": 1, "uniqueItems": True,
        "items": {"enum": FUNCTIONS},
        "description": "仅原句实际完成的行事功能，可有statement+request或question+refusal；"
                       "不从源义务或摘要补功能。primary speech_function须在此数组。",
    }
    event["required"].append("speech_functions")
    event["allOf"] = [
        {"if": {"properties": {"kind": {"const": "action"}}},
         "then": {"properties": {"speech_functions": {
             "type": "array", "minItems": 1, "maxItems": 1, "items": {"const": "action"}}}}},
        {"if": {"properties": {"kind": {"const": "dialogue"}}},
         "then": {"properties": {"speech_functions": {
             "type": "array", "minItems": 1, "uniqueItems": True,
             "items": {"enum": [f for f in FUNCTIONS if f != "action"]}}}}},
    ]
    return schema


def _prior_audit(value):
    projected = deepcopy(value)
    for event in projected["literal_events"]:
        event.pop("speech_functions")
    return projected


def validate_audit(value, script, brief, plan):
    base._validate_schema(build_audit_schema(script, brief, plan), value, "audit")
    validation = prior.validate_audit(_prior_audit(value), script, brief, plan)
    for event in value["literal_events"]:
        if event["speech_function"] not in event["speech_functions"]:
            raise ValueError("primary speech_function must be in actual speech_functions")
        if "refusal" in event["speech_functions"] and event["negative_or_refusal"] is not True:
            raise ValueError("actual refusal function conflicts with negative_or_refusal flag")
    return {**validation, "source_hash": _digest(value), "actual_multiple_functions_supported": True}


def _event_decisions(audit, script, plan, requirements, uncertainties):
    entries = evidence_catalog(script)
    positions = {ref: index for index, ref in enumerate(entries)}
    events = {row["source_ref"]: row for row in audit["literal_events"]}
    proofs = {row["obligation_id"]: row for row in audit["obligation_evidence"]}
    obligations = {row["id"]: row for row in plan["source_obligations"]}

    def add(code, refs, problem, unknown=False):
        usable = list(dict.fromkeys(refs)) or list(entries)
        target = uncertainties if unknown else requirements
        v2._add(target, entries, code, usable, problem, FROZEN_SOURCE_REPAIR)
        target[-1]["claimed_actual_refs"] = list(refs)
        target[-1]["negative_context_only"] = not bool(refs)

    for key, obligation in obligations.items():
        proof = proofs[key]
        refs = proof["actual_refs"]
        if proof["status"] == "unknown":
            add("SOURCE_EVENT_" + key, refs, "来源义务：" + obligation["description"] +
                "；审计未明：" + proof["explanation"], True)
        elif proof["status"] == "fail":
            add("SOURCE_EVENT_" + key, refs, "来源义务：" + obligation["description"] +
                "；正文未兑现：" + proof["explanation"])
        if obligation["mode"] != "event":
            continue
        if not refs:
            add("SOURCE_EVENT_" + key, [], "来源事件缺少实际正文发生：" + obligation["description"])
            continue
        expected_function = obligation["allowed_speech_functions"][0]
        for ref in refs:
            event = events[ref]
            mismatch = []
            if obligation["required_kind"] != "either" and event["kind"] != obligation["required_kind"]:
                mismatch.append("事件类型不符")
            if obligation["actor_id"] and event["actual_actor"] != obligation["actor_id"]:
                mismatch.append("实际施事不符")
            if event["kind"] == "dialogue" and obligation["actor_id"] and event["speaker"] != obligation["actor_id"]:
                mismatch.append("实际说话人不符")
            if expected_function not in event["speech_functions"]:
                mismatch.append("缺少要求的原子行事功能" + expected_function + "，实际" +
                                "/".join(event["speech_functions"]))
            if mismatch:
                add("SOURCE_EVENT_" + key, [ref], "来源事件：" + obligation["description"] +
                    "；" + "；".join(mismatch) + "。字面重建：" + event["actual_action"])
        for other in obligation.get("distinct_from_ids", []):
            overlap = set(refs).intersection(proofs[other]["actual_refs"])
            if overlap:
                add("SOURCE_EVENT_" + key, sorted(overlap, key=positions.get),
                    "来源明确要求与" + other + "不同发生，同一实际步骤不能充当这两次事件。")

    for edge in plan["source_order"]:
        before, after = edge["before_id"], edge["after_id"]
        left, right = proofs[before]["actual_refs"], proofs[after]["actual_refs"]
        code = "SOURCE_ORDER_" + before + "_BEFORE_" + after
        if not left or not right:
            add(code, left + right, "来源严格先后缺少实际事件证据：" + before + "必须发生在" + after + "之前。")
        elif max(positions[ref] for ref in left) >= min(positions[ref] for ref in right):
            add(code, left + right, "正文事件顺序不满足来源严格先后：" + before + "必须完整发生在" + after +
                "之前；同一事件不能同时充当先后两次。")


def decide_audit(audit, script, brief, plan):
    validation = validate_audit(audit, script, brief, plan)
    audit_v2 = prior._prior_audit(_prior_audit(audit))
    inherited = prior._freeze_source_requirements(v2.decide_audit(audit_v2, script, brief))
    requirements = deepcopy(inherited["revision_requirements"])
    uncertainties = deepcopy(inherited["uncertainties"])
    _event_decisions(audit, script, plan, requirements, uncertainties)
    result = v2._result("audit", audit, script, validation, requirements, uncertainties)
    result["plan_sha256"] = _digest(plan)
    return result


def combine_decisions(review, audit, script, brief, plan):
    primary = decide_review(review, script, brief)
    literal = decide_audit(audit, script, brief, plan)
    result = v2._result("combined", {"review": review, "audit": audit}, script,
        {"complete": True, "source_hash": _digest({"review": review, "audit": audit}),
         "primary_review": primary["validation"], "literal_audit": literal["validation"]},
        primary["revision_requirements"] + literal["revision_requirements"],
        primary["uncertainties"] + literal["uncertainties"])
    result.update(review_sha256=_digest(review), audit_sha256=_digest(audit),
                  plan_sha256=_digest(plan), both_same_source_checks_required=True,
                  executable_atomic_source_events_required=True)
    return result
