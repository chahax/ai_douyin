"""Source obligations and strict event order for autonomous text verification.

v1/v2 remain frozen. Source planning is model-authored from the brief; audit
reconstructs actual performed steps. Deterministic decisions reconcile the two
without editing source facts or inserting missing prose.
"""
from __future__ import annotations

from copy import deepcopy
from . import creative_autonomous_text_contract_v2 as prior

base = prior.base
VERSION = "creative_autonomous_text_contract/v3"
CRITERIA = deepcopy(prior.CRITERIA)
FUNCTIONS = ["action", "statement", "question", "request", "refusal", "other"]
build_script_schema = prior.build_script_schema
compile_script = prior.compile_script
evidence_catalog = prior.evidence_catalog
build_review_schema = prior.build_review_schema
validate_review = prior.validate_review
_digest = prior._digest
FROZEN_SOURCE_REPAIR = "冻结来源不得修改；由生成模型提交完整新正文，兑现该来源要求及实际先后，不补丁、不拼接、不改brief迁就当前稿。"


def build_plan_schema(brief):
    schema = prior.build_plan_schema(brief)
    facts = list(prior._facts(brief))
    obligation = base._obj({
        "id": base._text(), "fact_id": {"enum": facts} if facts else False,
        "mode": {"enum": ["event", "state", "absence"]}, "description": base._text(),
        "actor_id": {"enum": base._actors(brief) + [""]},
        "required_kind": {"enum": ["action", "dialogue", "either"]},
        "allowed_speech_functions": {"type": "array", "minItems": 1,
                                     "uniqueItems": True, "items": {"enum": FUNCTIONS}},
    })
    obligation["properties"]["distinct_from_ids"] = {
        "type": "array", "uniqueItems": True, "items": base._text(),
        "description": "仅来源明确要求不同发生时声明；不得禁止同一句对白完成多个目的。",
    }
    schema["properties"].update({
        "source_obligations": {"type": "array", "minItems": len(facts), "items": obligation},
        "source_order": {"type": "array", "uniqueItems": True,
                         "items": base._obj({"before_id": base._text(), "after_id": base._text()}),
                         "description": "只声明来源必须的严格先后，不把同时动作或装饰动作强行串行化。"},
    })
    schema["required"].extend(["source_obligations", "source_order"])
    return schema


def validate_plan(value, brief):
    base._validate_schema(build_plan_schema(brief), value, "plan")
    projected = {key: deepcopy(item) for key, item in value.items()
                 if key not in ("source_obligations", "source_order")}
    validation = prior.validate_plan(projected, brief)
    rows = value["source_obligations"]
    ids = [row["id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("source obligation IDs must be unique")
    if {row["fact_id"] for row in rows} != set(prior._facts(brief)):
        raise ValueError("source obligations must cover every brief fact")
    nodes = set(ids)
    for row in rows:
        distinct = row.get("distinct_from_ids", [])
        if not set(distinct).issubset(nodes) or row["id"] in distinct:
            raise ValueError("distinct obligations must name other known IDs")
        if row["mode"] == "event":
            functions = set(row["allowed_speech_functions"])
            if row["required_kind"] == "action" and functions != {"action"}:
                raise ValueError("action event obligations require the action speech function")
            if row["required_kind"] == "dialogue" and "action" in functions:
                raise ValueError("dialogue event obligations cannot use the action speech function")
    graph = {node: set() for node in nodes}
    for edge in value["source_order"]:
        before, after = edge["before_id"], edge["after_id"]
        if before not in nodes or after not in nodes or before == after:
            raise ValueError("source order must connect two different known obligations")
        graph[before].add(after)
    degrees = {node: 0 for node in nodes}
    for children in graph.values():
        for child in children:
            degrees[child] += 1
    ready = [node for node, degree in degrees.items() if degree == 0]
    visited = 0
    while ready:
        node = ready.pop()
        visited += 1
        for child in graph[node]:
            degrees[child] -= 1
            if degrees[child] == 0:
                ready.append(child)
    if visited != len(nodes):
        raise ValueError("source order must not contain cycles")
    return {**validation, "source_hash": _digest(value),
            "source_obligation_count": len(rows), "strict_order_count": len(value["source_order"]),
            "source_derived_from_brief_required": True}


def build_audit_schema(script, brief, plan):
    validate_plan(plan, brief)
    schema = prior.build_audit_schema(script, brief)
    refs = list(evidence_catalog(script))
    ids = [row["id"] for row in plan["source_obligations"]]
    schema["properties"]["obligation_evidence"] = {
        "type": "array", "minItems": len(ids), "maxItems": len(ids),
        "items": base._obj({
            "obligation_id": {"enum": ids} if ids else False,
            "actual_refs": base._array_refs(refs, 0),
            "status": {"enum": ["pass", "fail", "unknown"]},
            "explanation": base._text(),
        }),
    }
    schema["required"].append("obligation_evidence")
    event = schema["properties"]["literal_events"]["items"]
    event["properties"]["actual_actor"] = {
        "enum": base._actors(brief) + [""],
        "description": "实际行动施事；对白言语行为的actual_actor必须是实际speaker，话中公司的决定另按state义务核对。",
    }
    event["required"].append("actual_actor")
    return schema


def _prior_audit(value):
    projected = {key: deepcopy(item) for key, item in value.items() if key != "obligation_evidence"}
    for event in projected["literal_events"]:
        event.pop("actual_actor")
    return projected


def validate_audit(value, script, brief, plan):
    base._validate_schema(build_audit_schema(script, brief, plan), value, "audit")
    validation = prior.validate_audit(_prior_audit(value), script, brief)
    expected = {row["id"] for row in plan["source_obligations"]}
    actual = [row["obligation_id"] for row in value["obligation_evidence"]]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError("obligation evidence must cover every source obligation exactly once")
    for event in value["literal_events"]:
        if event["kind"] == "dialogue" and event["actual_actor"] != event["speaker"]:
            raise ValueError("dialogue actual_actor must equal its actual speaker")
    return {**validation, "source_hash": _digest(value), "plan_sha256": _digest(plan),
            "obligation_count": len(expected), "complete_source_event_evidence": True}


def _freeze_source_requirements(decision):
    result = deepcopy(decision)
    for key in ("revision_requirements", "uncertainties"):
        for row in result[key]:
            if row["code"].startswith(("FACT_", "INITIAL_")):
                row["required_revision"] = FROZEN_SOURCE_REPAIR
    return result


def decide_review(review, script, brief):
    # Retain the native review untouched; only the executable repair instruction
    # is source-owned. A reviewer cannot authorize rewriting the brief.
    return _freeze_source_requirements(prior.decide_review(review, script, brief))


def _event_decisions(audit, script, brief, plan, requirements, uncertainties):
    entries = evidence_catalog(script)
    positions = {ref: index for index, ref in enumerate(entries)}
    actual_events = {row["source_ref"]: row for row in audit["literal_events"]}
    proofs = {row["obligation_id"]: row for row in audit["obligation_evidence"]}
    obligations = {row["id"]: row for row in plan["source_obligations"]}

    def add(code, refs, problem, unknown=False):
        # Missing events have no fabricated quote. Existing performed text is
        # useful negative context, while the absent actual_refs remains visible.
        usable = list(dict.fromkeys(refs)) or list(entries)
        prior._add(uncertainties if unknown else requirements, entries, code,
                   usable, problem, FROZEN_SOURCE_REPAIR)

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
        for ref in refs:
            event = actual_events[ref]
            mismatch = []
            if obligation["required_kind"] != "either" and event["kind"] != obligation["required_kind"]:
                mismatch.append("事件类型不符")
            if obligation["actor_id"] and event["actual_actor"] != obligation["actor_id"]:
                mismatch.append("实际施事不符")
            if event["kind"] == "dialogue" and obligation["actor_id"] and event["speaker"] != obligation["actor_id"]:
                mismatch.append("实际说话人不符")
            if event["speech_function"] not in obligation["allowed_speech_functions"]:
                mismatch.append("言语行动不符，不能把质问或泛否定当作拒绝")
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
            add(code, left + right, "正文事件顺序不满足来源严格先后：" + before + "必须完整发生在" + after + "之前；同一事件不能同时充当先后两次。")


def decide_audit(audit, script, brief, plan):
    validation = validate_audit(audit, script, brief, plan)
    inherited = _freeze_source_requirements(prior.decide_audit(_prior_audit(audit), script, brief))
    requirements = deepcopy(inherited["revision_requirements"])
    uncertainties = deepcopy(inherited["uncertainties"])
    _event_decisions(audit, script, brief, plan, requirements, uncertainties)
    result = prior._result("audit", audit, script, validation, requirements, uncertainties)
    result["plan_sha256"] = _digest(plan)
    return result


def combine_decisions(review, audit, script, brief, plan):
    primary = decide_review(review, script, brief)
    literal = decide_audit(audit, script, brief, plan)
    requirements = primary["revision_requirements"] + literal["revision_requirements"]
    uncertainties = primary["uncertainties"] + literal["uncertainties"]
    result = prior._result("combined", {"review": review, "audit": audit}, script,
        {"complete": True, "source_hash": _digest({"review": review, "audit": audit}),
         "primary_review": primary["validation"], "literal_audit": literal["validation"]},
        requirements, uncertainties)
    result.update(review_sha256=_digest(review), audit_sha256=_digest(audit),
                  plan_sha256=_digest(plan), both_same_source_checks_required=True,
                  executable_source_events_required=True)
    return result
