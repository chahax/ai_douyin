"""Source-supported physical atoms, source audit and occurrence-only event proof.

Frozen v1-v4 are imported without mutation. Source quotes bind planning to the
brief; a separate source audit verifies their semantic support. Script audit
reconstructs the state before the first action and separates an event's actual
occurrence from supporting context. This module has no provider or media calls.
"""
from __future__ import annotations

from copy import deepcopy
from . import creative_autonomous_text_contract_v4 as prior

base = prior.base
v2 = prior.v2
VERSION = "creative_autonomous_text_contract/v5"
CRITERIA = deepcopy(prior.CRITERIA)
FUNCTIONS = list(prior.FUNCTIONS)
RELATIONS = ["on_surface", "inside_container", "held_by", "unspecified"]
ORIENTATIONS = ["face_up", "face_down", "unspecified"]
ANCHOR_TYPES = ["character", "prop", "scene", "unspecified"]
build_script_schema = prior.build_script_schema
compile_script = prior.compile_script
evidence_catalog = prior.evidence_catalog
build_review_schema = prior.build_review_schema
validate_review = prior.validate_review
decide_review = prior.decide_review
_digest = prior._digest
FROZEN_SOURCE_REPAIR = prior.FROZEN_SOURCE_REPAIR
FROZEN_PLAN_REPAIR = (
    "冻结brief、事实及初态不得修改；由生成模型提交完整新计划，完整覆盖来源要求，"
    "仅依据来源声明物理原子与必要严格先后，不本地补丁或迁就旧稿。")


def _props(brief):
    declared = base._ids(brief, "props", "prop_ids")
    initial = [entity for kind, entity in v2._states(brief) if kind == "prop"]
    return list(dict.fromkeys(declared + initial))


def _anchors(brief):
    return {"character": base._characters(brief), "prop": _props(brief),
            "scene": base._ids(brief, "scenes", "scene_ids"), "unspecified": [""]}


def _physical_schema(brief):
    states = v2._states(brief)
    anchors = _anchors(brief)
    row = base._obj({
        "entity_type": {"enum": ["character", "prop"]},
        "entity_id": {"enum": list(dict.fromkeys(key[1] for key in states))} if states else False,
        "relation": {"enum": RELATIONS,
            "description": "初始可观察关系；只有来源明确才约束。on_surface的character参照表示该人物面前的表面区域，不把人当表面。"},
        "anchor_type": {"enum": ANCHOR_TYPES},
        "anchor_id": {"type": "string"},
        "orientation": {"enum": ORIENTATIONS},
    })
    row["allOf"] = []
    for kind in ("character", "prop"):
        ids = [entity for entity_kind, entity in states if entity_kind == kind]
        row["allOf"].append({
            "if": {"properties": {"entity_type": {"const": kind}}},
            "then": {"properties": {"entity_id": {"enum": ids} if ids else False}}})
    for kind, ids in anchors.items():
        row["allOf"].append({
            "if": {"properties": {"anchor_type": {"const": kind}}},
            "then": {"properties": {"anchor_id": {"enum": ids} if ids else False}}})
    row["allOf"].extend([
        {"if": {"properties": {"relation": {"const": "held_by"}}},
         "then": {"properties": {"anchor_type": {"const": "character"}}}},
        {"if": {"properties": {"relation": {"not": {"const": "unspecified"}}}},
         "then": {"properties": {"anchor_type": {"enum": ["character", "prop", "scene"]},
                                  "anchor_id": base._text()}}},
    ])
    return row


def _check_quote(quote, original, label):
    if not quote.strip() or quote not in original:
        raise ValueError(label + " must be an unchanged nonempty fragment of its brief source")


def _unique_coverage(rows, keys, expected, label):
    actual = [tuple(row[key] for key in keys) for row in rows]
    if len(actual) != len(set(actual)) or set(actual) != set(expected):
        raise ValueError(label + " must cover every source item exactly once")


def _prior_plan(plan):
    projected = {key: deepcopy(value) for key, value in plan.items() if key != "initial_conditions"}
    for edge in projected["source_order"]:
        edge.pop("fact_id")
        edge.pop("source_quote")
    return projected


def build_plan_schema(brief):
    schema = prior.build_plan_schema(brief)
    states = v2._states(brief)
    condition = _physical_schema(brief)
    condition["properties"]["source_quote"] = {
        **base._text(), "description": "对应brief.initial_state该实体expected_state的原文片段；不引用旧稿。"}
    condition["required"].append("source_quote")
    schema["properties"]["initial_conditions"] = {
        "type": "array", "minItems": len(states), "maxItems": len(states), "items": condition,
        "description": "每个声明初态实体一条。未被原来源明确限定的关系、位置参照和朝向用unspecified，不凭场面习惯补设定。"}
    schema["required"].append("initial_conditions")
    order = schema["properties"]["source_order"]["items"]
    order["properties"].update({
        "fact_id": {"enum": list(v2._facts(brief))} if v2._facts(brief) else False,
        "source_quote": {**base._text(), "description": "该fact原文中支持这两个不同发生必须严格先后的片段；同一次请求的不同描述不算两次。"},
    })
    order["required"].extend(["fact_id", "source_quote"])
    schema["properties"]["source_order"]["description"] = (
        "只列来源必须的event→event严格先后，并为每边给fact_id及原文source_quote。"
        "不从规划排列或同一次行动的不同描述推断两次发生；无来源先后用空数组。")
    return schema


def validate_plan(value, brief):
    base._validate_schema(build_plan_schema(brief), value, "plan")
    validation = prior.validate_plan(_prior_plan(value), brief)
    states = v2._states(brief)
    _unique_coverage(value["initial_conditions"], ("entity_type", "entity_id"), states,
                     "plan.initial_conditions")
    for row in value["initial_conditions"]:
        key = row["entity_type"], row["entity_id"]
        _check_quote(row["source_quote"], states[key], "initial condition source_quote")
    pairs = [(edge["before_id"], edge["after_id"]) for edge in value["source_order"]]
    if len(pairs) != len(set(pairs)):
        raise ValueError("source_order must not duplicate an event pair with other quote metadata")
    facts = v2._facts(brief)
    for edge in value["source_order"]:
        _check_quote(edge["source_quote"], facts[edge["fact_id"]], "source_order source_quote")
    return {**validation, "source_hash": _digest(value), "brief_sha256": _digest(brief),
            "initial_condition_count": len(states), "source_quotes_bound": True,
            "source_support_requires_independent_audit": True}


def _finding(properties):
    return base._obj({**properties, "status": {"enum": ["pass", "fail", "unknown"]},
        "source_quote": base._text(), "explanation": base._text(),
        "required_revision": {"type": "string"}})


def _table(items, count, description):
    return {"type": "array", "minItems": count, "maxItems": count,
            "items": items, "description": description}


def build_source_audit_schema(plan, brief):
    validate_plan(plan, brief)
    facts = v2._facts(brief)
    obligations = {row["id"]: row for row in plan["source_obligations"]}
    states = v2._states(brief)
    initial = _finding({
        "entity_type": {"enum": ["character", "prop"]},
        "entity_id": {"enum": list(dict.fromkeys(key[1] for key in states))} if states else False,
    })
    order = _finding({
        "before_id": {"enum": list(obligations)} if obligations else False,
        "after_id": {"enum": list(obligations)} if obligations else False,
        "fact_id": {"enum": list(facts)} if facts else False,
    })
    obligation = _finding({"obligation_id": {"enum": list(obligations)} if obligations else False})
    coverage = _finding({"fact_id": {"enum": list(facts)} if facts else False,
                         "obligation_ids": base._array_refs(list(obligations), 0)})
    return base._obj({
        "plan_sha256": {"const": _digest(plan)}, "brief_sha256": {"const": _digest(brief)},
        "fact_coverage_checks": _table(coverage, len(facts),
            "逐fact核对复合来源的全部必要事件、状态、禁止项是否完整拆出。只看事实及源义务；缺项或把质问复合描述当已拒绝须fail，不补写新义务。"),
        "source_obligation_checks": _table(obligation, len(obligations),
            "逐义务核对其mode、施事、步骤类型和唯一行事功能是否由对应fact原文支持。quote来自该fact，不能借计划摘要自己证明自己。"),
        "initial_condition_checks": _table(initial, len(states),
            "逐初态核对声明的每个非unspecified物理原子是否由该expected_state及brief上下文明确支持；quote原样引用计划source_quote。"),
        "source_order_checks": _table(order, len(plan["source_order"]),
            "逐边核对该原文是否真的要求两个不同发生严格先后。语义上同一次请求的两种描述不能通过。quote原样引用该边source_quote。"),
    })


def validate_source_audit(value, plan, brief):
    base._validate_schema(build_source_audit_schema(plan, brief), value, "source_audit")
    facts = v2._facts(brief)
    obligations = {row["id"]: row for row in plan["source_obligations"]}
    conditions = {(row["entity_type"], row["entity_id"]): row for row in plan["initial_conditions"]}
    edges = {(row["before_id"], row["after_id"]): row for row in plan["source_order"]}
    _unique_coverage(value["fact_coverage_checks"], ("fact_id",), ((key,) for key in facts),
                     "source_audit.fact_coverage_checks")
    _unique_coverage(value["source_obligation_checks"], ("obligation_id",),
                     ((key,) for key in obligations), "source_audit.source_obligation_checks")
    _unique_coverage(value["initial_condition_checks"], ("entity_type", "entity_id"), conditions,
                     "source_audit.initial_condition_checks")
    _unique_coverage(value["source_order_checks"], ("before_id", "after_id"), edges,
                     "source_audit.source_order_checks")
    for row in value["fact_coverage_checks"]:
        expected = {key for key, obligation in obligations.items() if obligation["fact_id"] == row["fact_id"]}
        if set(row["obligation_ids"]) != expected:
            raise ValueError("source fact coverage must bind exactly its declared obligations")
        _check_quote(row["source_quote"], facts[row["fact_id"]], "fact coverage source_quote")
    for row in value["source_obligation_checks"]:
        fact = facts[obligations[row["obligation_id"]]["fact_id"]]
        _check_quote(row["source_quote"], fact, "obligation source_quote")
    for row in value["initial_condition_checks"]:
        if row["source_quote"] != conditions[row["entity_type"], row["entity_id"]]["source_quote"]:
            raise ValueError("source audit changed an initial condition's source quote")
    for row in value["source_order_checks"]:
        expected = edges[row["before_id"], row["after_id"]]
        if row["fact_id"] != expected["fact_id"] or row["source_quote"] != expected["source_quote"]:
            raise ValueError("source audit changed a strict order's source binding")
    return {"complete": True, "source_hash": _digest(value), "plan_sha256": _digest(plan),
            "brief_sha256": _digest(brief), "all_source_support_checks_required": True,
            "semantic_quality_approved": False}


def decide_source_audit(value, plan, brief):
    validation = validate_source_audit(value, plan, brief)
    requirements, uncertainties = [], []
    table_specs = [
        ("fact_coverage_checks", "SOURCE_FACT_COVERAGE_", ("fact_id",)),
        ("source_obligation_checks", "SOURCE_OBLIGATION_", ("obligation_id",)),
        ("initial_condition_checks", "SOURCE_INITIAL_", ("entity_type", "entity_id")),
        ("source_order_checks", "SOURCE_ORDER_SUPPORT_", ("before_id", "after_id")),
    ]
    for table, prefix, keys in table_specs:
        for row in value[table]:
            if row["status"] == "pass":
                continue
            target = uncertainties if row["status"] == "unknown" else requirements
            target.append({"code": prefix + "_".join(row[key] for key in keys),
                "source_quote": row["source_quote"], "problem": row["explanation"],
                "required_revision": FROZEN_PLAN_REPAIR, "plan_table": table,
                "source_item": {key: row[key] for key in keys},
                "evidence_text": row["source_quote"]})
    return {"status": "halt_source_uncertain" if uncertainties else
            "needs_whole_plan_revision" if requirements else "source_contract_ready",
            "source_audit_sha256": _digest(value), "plan_sha256": _digest(plan),
            "brief_sha256": _digest(brief), "validation": validation,
            "revision_requirements": requirements, "uncertainties": uncertainties,
            "human_quality_approved": False, "human_approved": False,
            "creative_quality_passed": False, "automatic_media_submit": False,
            "decision_basis": "independent_same_source_plan_support_not_script_quality"}


def build_audit_schema(script, brief, plan):
    validate_plan(plan, brief)
    schema = prior.build_audit_schema(script, brief, _prior_plan(plan))
    schema["properties"]["plan_sha256"] = {"const": _digest(plan)}
    schema["required"].append("plan_sha256")
    refs = list(evidence_catalog(script))
    conditions = _physical_schema(brief)
    conditions["properties"].update({
        "status": {"enum": ["known", "unknown"],
            "description": "known表示由实际正文证据还原的初始物理值，不是满足期望；无法还原必要物理值为unknown。"},
        "observed_state": base._text(), "evidence_refs": base._array_refs(refs, 0),
    })
    conditions["required"].extend(["status", "observed_state", "evidence_refs"])
    conditions["allOf"].append({
        "if": {"properties": {"status": {"const": "known"}}, "anyOf": [
            {"properties": {field: {"not": {"const": "unspecified"}}}}
            for field in ("relation", "anchor_type", "orientation")]},
        "then": {"properties": {"evidence_refs": base._array_refs(refs, 1)}},
    })
    conditions["description"] = (
        "只从实际正文最初行动之前还原该实体的关系、位置参照和朝向；"
        "例如从容器中取出可证明取出前在容器内，不能用取出后位置代替。"
        "不得抄期望初态或用premise/event补实际正文；无法还原明确unknown，未明原子unspecified。")
    schema["properties"]["actual_initial_conditions"] = _table(conditions,
        len(plan["initial_conditions"]), "覆盖每个源初态实体；报告正文最初动作前实际值，不报告是否满足期望。")
    schema["required"].append("actual_initial_conditions")
    proof = schema["properties"]["obligation_evidence"]["items"]
    proof["properties"].pop("actual_refs")
    proof["required"].remove("actual_refs")
    proof["properties"].update({
        "occurrence_refs": {**base._array_refs(refs, 0),
            "description": "真正完成该义务事件的正文步骤。只放发生本体，不把触发、铺垫、听者反应或前后支持混入；缺事件为空。"},
        "support_refs": {**base._array_refs(refs, 0),
            "description": "触发、语境或后果的真实正文证据，可为空；不能替代发生，不用于施事/功能/顺序匹配。"},
    })
    proof["required"].extend(["occurrence_refs", "support_refs"])
    proof["properties"]["occurrence_spans"] = {
        "type": "array", "uniqueItems": True,
        "items": base._obj({"ref_id": {"enum": refs}, "quote": base._text()}),
        "description": "可选发生子句。存在时每个occurrence_ref恰一条原文quote，且quote在该步骤中唯一出现；不能猜重复片段位置。严格先后共享一个对白步骤时，分别给真正前后发生的非重叠子句。无此字段按完整步骤边界，不强制拆句。",
    }
    return schema


def _prior_audit(value):
    projected = {key: deepcopy(item) for key, item in value.items()
                 if key not in ("plan_sha256", "actual_initial_conditions")}
    for row in projected["obligation_evidence"]:
        row["actual_refs"] = row.pop("occurrence_refs")
        row.pop("support_refs")
        row.pop("occurrence_spans", None)
    return projected


def validate_audit(value, script, brief, plan):
    base._validate_schema(build_audit_schema(script, brief, plan), value, "audit")
    validation = prior.validate_audit(_prior_audit(value), script, brief, _prior_plan(plan))
    expected = [(row["entity_type"], row["entity_id"]) for row in plan["initial_conditions"]]
    _unique_coverage(value["actual_initial_conditions"], ("entity_type", "entity_id"), expected,
                     "audit.actual_initial_conditions")
    entries = evidence_catalog(script)
    for proof in value["obligation_evidence"]:
        if "occurrence_spans" not in proof:
            continue
        ids = [span["ref_id"] for span in proof["occurrence_spans"]]
        if len(ids) != len(set(ids)) or set(ids) != set(proof["occurrence_refs"]):
            raise ValueError("occurrence_spans must cover every occurrence_ref exactly once")
        for span in proof["occurrence_spans"]:
            quote = span["quote"]
            original = entries[span["ref_id"]]["quote"]
            start = original.find(quote)
            if not quote.strip() or start < 0:
                raise ValueError("occurrence span quote must be a nonempty unchanged source substring")
            if original.find(quote, start + 1) >= 0:
                raise ValueError("occurrence span quote has multiple source positions; do not guess")
    for row in value["actual_initial_conditions"]:
        if row["status"] == "known" and not row["evidence_refs"]:
            # Unconstrained physical atoms may all be unspecified, but declaring
            # a reconstructed physical value as known always needs actual prose.
            if any(row[key] != "unspecified" for key in ("relation", "anchor_type", "orientation")):
                raise ValueError("known actual initial atoms need performed-step evidence")
    return {**validation, "source_hash": _digest(value), "plan_sha256": _digest(plan),
            "brief_sha256": _digest(brief), "actual_initial_before_action_required": True,
            "occurrence_and_support_separated": True}


def _initial_decisions(audit, script, plan, requirements, uncertainties):
    entries = evidence_catalog(script)
    actual = {(row["entity_type"], row["entity_id"]): row for row in audit["actual_initial_conditions"]}
    for expected in plan["initial_conditions"]:
        key = expected["entity_type"], expected["entity_id"]
        row = actual[key]
        fields = [field for field in ("relation", "anchor_type", "orientation")
                  if expected[field] != "unspecified"]
        if expected["anchor_type"] != "unspecified":
            fields.append("anchor_id")
        if not fields:
            continue  # No physical atom was asserted; the legacy state checks still apply.
        code = "INITIAL_" + expected["entity_type"].upper() + "_" + expected["entity_id"]
        refs = row["evidence_refs"]
        if row["status"] == "unknown":
            v2._add(uncertainties, entries, code, refs,
                "正文最初行动前的必要初态无法还原：" + row["observed_state"] +
                "；冻结来源：" + expected["source_quote"], FROZEN_SOURCE_REPAIR)
            continue
        unresolved = [field for field in fields if row[field] in ("unspecified", "")]
        if unresolved:
            v2._add(uncertainties, entries, code, refs,
                "正文初态必要原子未知：" + "/".join(unresolved) +
                "；正文观察：" + row["observed_state"], FROZEN_SOURCE_REPAIR)
        mismatches = [field for field in fields if field not in unresolved and row[field] != expected[field]]
        if mismatches:
            v2._add(requirements, entries, code, refs,
                "最初行动前的物理初态违反冻结来源：" +
                "；".join(field + "期望=" + expected[field] + "，实际=" + row[field]
                          for field in mismatches) + "；正文观察：" + row["observed_state"],
                FROZEN_SOURCE_REPAIR)


def _occurrence_bounds(proof, entries, positions):
    spans = {row["ref_id"]: row["quote"] for row in proof.get("occurrence_spans", [])}
    result = {}
    for ref in proof["occurrence_refs"]:
        original = entries[ref]["quote"]
        quote = spans.get(ref, original)
        start = original.index(quote)
        result[ref] = ((positions[ref], start), (positions[ref], start + len(quote)))
    return result


def _event_decisions(audit, script, plan, requirements, uncertainties):
    entries = evidence_catalog(script)
    positions = {ref: index for index, ref in enumerate(entries)}
    events = {row["source_ref"]: row for row in audit["literal_events"]}
    proofs = {row["obligation_id"]: row for row in audit["obligation_evidence"]}
    obligations = {row["id"]: row for row in plan["source_obligations"]}

    def add(code, refs, support, problem, unknown=False):
        occurrence = list(dict.fromkeys(refs))
        context = list(dict.fromkeys(support))
        # Missing occurrence has no invented evidence: support or body can be
        # negative context, while occurrence_refs remains explicitly empty.
        usable = occurrence + [ref for ref in context if ref not in occurrence]
        usable = usable or list(entries)
        target = uncertainties if unknown else requirements
        v2._add(target, entries, code, usable, problem, FROZEN_SOURCE_REPAIR)
        target[-1].update(occurrence_refs=occurrence, support_refs=context,
                         negative_context_only=not bool(occurrence))

    for key, obligation in obligations.items():
        proof = proofs[key]
        refs, support = proof["occurrence_refs"], proof["support_refs"]
        if proof["status"] == "unknown":
            add("SOURCE_EVENT_" + key, refs, support, "来源义务：" + obligation["description"] +
                "；审计未明：" + proof["explanation"], True)
        elif proof["status"] == "fail":
            add("SOURCE_EVENT_" + key, refs, support, "来源义务：" + obligation["description"] +
                "；正文未兑现：" + proof["explanation"])
        if obligation["mode"] != "event":
            continue
        if not refs:
            add("SOURCE_EVENT_" + key, [], support, "来源事件缺少实际正文发生：" + obligation["description"])
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
                add("SOURCE_EVENT_" + key, [ref], support, "来源事件：" + obligation["description"] +
                    "；" + "；".join(mismatch) + "。字面重建：" + event["actual_action"])
        for other in obligation.get("distinct_from_ids", []):
            left_bounds = _occurrence_bounds(proof, entries, positions)
            right_bounds = _occurrence_bounds(proofs[other], entries, positions)
            overlap = [ref for ref in set(left_bounds).intersection(right_bounds)
                       if max(left_bounds[ref][0], right_bounds[ref][0]) <
                          min(left_bounds[ref][1], right_bounds[ref][1])]
            if overlap:
                add("SOURCE_EVENT_" + key, sorted(overlap, key=positions.get), support,
                    "来源明确要求与" + other + "不同发生，重叠发生子句不能充当这两次事件。")
    for edge in plan["source_order"]:
        before, after = edge["before_id"], edge["after_id"]
        left, right = proofs[before]["occurrence_refs"], proofs[after]["occurrence_refs"]
        support = proofs[before]["support_refs"] + proofs[after]["support_refs"]
        code = "SOURCE_ORDER_" + before + "_BEFORE_" + after
        if not left or not right:
            add(code, left + right, support, "来源严格先后缺少实际事件证据：" + before +
                "必须发生在" + after + "之前；来源原文：" + edge["source_quote"])
        else:
            left_bounds = _occurrence_bounds(proofs[before], entries, positions)
            right_bounds = _occurrence_bounds(proofs[after], entries, positions)
            # End positions are exclusive: adjacent source clauses are ordered,
            # while overlap or a reversed clause cannot be separate occurrences.
            if max(bound[1] for bound in left_bounds.values()) > min(bound[0] for bound in right_bounds.values()):
                add(code, left + right, support, "正文事件顺序不满足来源严格先后：" + before +
                    "必须完整发生在" + after + "之前；共享步骤需要明确非重叠的原文发生子句；来源原文：" + edge["source_quote"])


def decide_audit(audit, script, brief, plan):
    validation = validate_audit(audit, script, brief, plan)
    projected = _prior_audit(audit)
    audit_v2 = prior.prior._prior_audit(prior._prior_audit(projected))
    inherited = prior.prior._freeze_source_requirements(v2.decide_audit(audit_v2, script, brief))
    requirements = deepcopy(inherited["revision_requirements"])
    uncertainties = deepcopy(inherited["uncertainties"])
    _initial_decisions(audit, script, plan, requirements, uncertainties)
    _event_decisions(audit, script, plan, requirements, uncertainties)
    result = v2._result("audit", audit, script, validation, requirements, uncertainties)
    result["plan_sha256"] = _digest(plan)
    result["physical_initial_atoms_required"] = True
    result["occurrence_and_support_separated"] = True
    return result


def combine_decisions(review, audit, script, brief, plan):
    primary = decide_review(review, script, brief)
    literal = decide_audit(audit, script, brief, plan)
    value = {"review": review, "audit": audit}
    result = v2._result("combined", value, script,
        {"complete": True, "source_hash": _digest(value),
         "primary_review": primary["validation"], "literal_audit": literal["validation"]},
        primary["revision_requirements"] + literal["revision_requirements"],
        primary["uncertainties"] + literal["uncertainties"])
    result.update(review_sha256=_digest(review), audit_sha256=_digest(audit),
        plan_sha256=_digest(plan), both_same_source_checks_required=True,
        executable_atomic_source_events_required=True, physical_initial_atoms_required=True,
        occurrence_and_support_separated=True)
    return result
