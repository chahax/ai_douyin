"""Independent source-to-creative-plan acceptance; no model or media calls.

The gate reviews actual creative intent fields, not the plan's copied source
obligations. Stable evidence IDs compile to immutable plan paths and verbatim
text. Models own every semantic judgment; local code enforces coverage, hashes,
reference scope and routing. A failed plan is replaced only by a complete native
model plan. This module never edits the original plan or supplies new dialogue.
"""
from __future__ import annotations

from copy import deepcopy
from . import creative_autonomous_text_contract_v1 as base
from . import creative_autonomous_text_contract_v2 as sources

VERSION = "creative_scene_plan_gate/v1"
BEAT_FIELDS = ("trigger", "attempt", "state_change")
ENDING_FIELDS = ("attempt_result", "visible_consequence", "open_problem")
BEAT_CHECKS = ("action_purpose", "stimulus_causality", "physical_continuity", "source_fidelity")
FROZEN_PLAN_REPAIR = (
    "冻结brief与初态不变。由生成模型根据具体源要求和创作字段证据提交完整新计划；"
    "行动目的、拍数与安排可重构，不补字段、不本地拼接、不把禁止项变成新增剧情或台词。")
RULE = (
    "你是独立创作规划验收员。唯一事实和初态来自brief；完整plan是待审对象，不是事实权威。"
    "先逐source_obligation在真实creative beats的trigger/attempt/state_change找明确计划发生、"
    "持续状态或禁项未新增的证据；选creative_evidence_catalog的P引用ID，原文由程序解析。"
    "fact_refs、source_obligations、source_order里的来源复述不能证明创作拍真的安排了事件。"
    "source_obligations的mode同样是待审元数据，不能拿待审mode当事实标准；coverage_type独立按"
    "brief真实要求判断。event必须有明确发生，质问不能代替拒绝；摘要声称第二次不能补前面缺失的第一次。"
    "状态与缺席约束不要求被人物逐句念出，但不能把不要求做某事扩写为新增该请求后再拒绝。"
    "逐fact检查全部复合要求与禁令；逐initial检查真实起态与首个动作前提；逐源顺序检查"
    "实际计划动作先后，不由source_order自证。计划可灵活分拍或合拍，不要求固定数量。"
    "全部beat逐项查行动目的、当前刺激和策略因果、物件位置与动作前提、来源忠实度；"
    "计划里提及的物件推进不能留给后续写手再次创造另一移动。前后安排缺乏明确约束、"
    "或来源明确的唯一动作未被计划控制时如实fail或unknown，不能凭写手会看brief补齐放行。"
    "人物取得签名的目标不是签名完成一切手续的事实或效果保证；私人请托也不授权后续业务承诺。"
    "逐ending三字段检查本场结果、可见后果和未解问题；已经当面说明的事实不能在结尾恢复为"
    "未知，未解决争议不等于宣布决定的施事未说明。结尾可以由动作兑现，不强迫解释性告别。"
    "所有检查选实际创作字段证据，不引用另一来源义务、旧稿或预计正文。没有创作证据可空refs，"
    "填missing或unknown，不虚构证据。fail给具体可执行的完整规划修改目标，unknown保留。"
    "不要代写新计划或替代台词，不声称剧本、视频或人工审美通过。每项简短，按Schema完整提交。")
SCENE_PLAN_GATE_RULE = RULE


def _digest(value):
    return base._digest(value)


def creative_evidence_catalog(plan):
    """Only actual creative fields and declared physical atoms, never fact_refs."""
    result = {}

    def add(path, text, kind, **metadata):
        if not isinstance(text, str) or (not text.strip() and kind != "initial_atom"):
            raise ValueError("creative evidence requires an actual plan string: " + path)
        ref = "P" + str(len(result) + 1).zfill(4)
        result[ref] = {"path": path, "quote": text, "kind": kind, **metadata}

    for field in ("title", "dramatic_question", "audience_arc"):
        add("plan." + field, plan[field], "scene_intent", field=field)
    for index, row in enumerate(plan["character_goals"]):
        for field in ("objective", "obstacle"):
            add(f"plan.character_goals.{index}.{field}", row[field], "character_goal",
                field=field, character_id=row["character_id"])
    for index, row in enumerate(plan["beats"]):
        for field in BEAT_FIELDS:
            add(f"plan.beats.{index}.{field}", row[field], "beat", field=field,
                beat_id=row["id"], beat_index=index, acting_character_id=row["acting_character_id"],
                target_character_id=row["target_character_id"])
    for field in ENDING_FIELDS:
        add("plan.ending." + field, plan["ending"][field], "ending", field=field)
    for index, row in enumerate(plan.get("initial_conditions", [])):
        for field in ("relation", "anchor_type", "anchor_id", "orientation"):
            # The empty anchor of unspecified is represented explicitly, not invented.
            text = row[field]
            add(f"plan.initial_conditions.{index}.{field}", text, "initial_atom", field=field,
                entity_type=row["entity_type"], entity_id=row["entity_id"],
                raw_value=row[field])
    return result


def _inputs(plan, brief):
    keys = ("title", "dramatic_question", "audience_arc", "character_goals", "beats", "ending")
    base.validate_plan({key: deepcopy(plan[key]) for key in keys}, brief)
    facts, states = sources._facts(brief), sources._states(brief)
    obligations = {row["id"]: row for row in plan["source_obligations"]}
    if len(obligations) != len(plan["source_obligations"]):
        raise ValueError("scene gate source obligation IDs must be unique")
    for row in obligations.values():
        if row["fact_id"] not in facts or row["mode"] not in ("event", "state", "absence"):
            raise ValueError("scene gate source obligation has an invalid frozen source or mode")
    edges = [(row["before_id"], row["after_id"]) for row in plan["source_order"]]
    if len(edges) != len(set(edges)) or any(a not in obligations or b not in obligations for a, b in edges):
        raise ValueError("scene gate source order has duplicate or missing source obligations")
    conditions = [(row["entity_type"], row["entity_id"]) for row in plan.get("initial_conditions", [])]
    if len(conditions) != len(set(conditions)) or set(conditions) != set(states):
        raise ValueError("scene gate requires the complete original initial-condition binding")
    return facts, states, obligations, edges, creative_evidence_catalog(plan)


def _refs(ids, minimum=0):
    return base._array_refs(ids, minimum)


def _check(refs, extra=None):
    result = base._obj({**(extra or {}), "status": {"enum": ["pass", "fail", "unknown"]},
        "explanation": base._text(), "evidence_refs": _refs(refs),
        "required_revision": {"type": "string"}})
    result["allOf"] = [
        {"if": {"properties": {"status": {"const": "pass"}}},
         "then": {"properties": {"evidence_refs": {"minItems": 1}}}},
        {"if": {"properties": {"status": {"const": "fail"}}},
         "then": {"properties": {"required_revision": {"type": "string", "pattern": r"\S"}}}}]
    return result


def _own_evidence(check, refs):
    check["allOf"].append({
        "if": {"properties": {"status": {"enum": ["pass", "fail"]}}},
        "then": {"properties": {"evidence_refs": {
            "contains": {"enum": refs}, "minContains": 1}}}})
    return check


def _table(row, identities, description):
    identities = list(identities)
    result = {"type": "array", "minItems": len(identities), "maxItems": len(identities),
              "items": row, "description": description}
    if identities:
        result["allOf"] = [{"contains": {"type": "object", "required": list(identity),
            "properties": {key: {"const": value} for key, value in identity.items()}},
            "minContains": 1, "maxContains": 1} for identity in identities]
    return result


def build_scene_plan_gate_schema(plan, brief):
    facts, states, obligations, edges, entries = _inputs(plan, brief)
    refs = list(entries)
    beat_refs = [key for key, row in entries.items() if row["kind"] == "beat"]
    creative_refs = [key for key, row in entries.items() if row["kind"] != "initial_atom"]
    obligation = _check(beat_refs, {
        "obligation_id": {"enum": list(obligations)} if obligations else False,
        "coverage_type": {"enum": ["explicit_event", "state_preserved", "absent_as_required",
                                   "missing", "conflicting", "unknown"]}})
    obligation["allOf"].append({"if": {"properties": {"status": {"const": "pass"}}},
        "then": {"properties": {"coverage_type": {"enum": [
            "explicit_event", "state_preserved", "absent_as_required"]}}}})
    initial = _check(refs, {"entity_type": {"enum": ["character", "prop"]},
        "entity_id": {"enum": list(dict.fromkeys(entity for _, entity in states))} if states else False})
    beat_check = _check(creative_refs, {"source_fact_ids": _refs(list(facts))})
    beat = base._obj({"beat_id": {"enum": [row["id"] for row in plan["beats"]]},
                     "checks": base._obj({key: deepcopy(beat_check) for key in BEAT_CHECKS})})
    beat["allOf"] = [{
        "if": {"properties": {"beat_id": {"const": row["id"]}}},
        "then": {"properties": {"checks": {"properties": {
            key: _own_evidence(deepcopy(beat_check), [ref for ref in beat_refs
                if entries[ref]["beat_id"] == row["id"]]) for key in BEAT_CHECKS}}}}}
        for row in plan["beats"]]
    order = _check(beat_refs, {"before_id": {"enum": list(obligations)} if obligations else False,
        "after_id": {"enum": list(obligations)} if obligations else False,
        "before_evidence_refs": _refs(beat_refs), "after_evidence_refs": _refs(beat_refs),
        "planned_relation": {"enum": ["explicit_before", "not_scheduled", "reversed", "incompatible", "unknown"]}})
    order["allOf"].append({"if": {"properties": {"status": {"const": "pass"}}},
        "then": {"properties": {"planned_relation": {"const": "explicit_before"},
            "before_evidence_refs": {"minItems": 1}, "after_evidence_refs": {"minItems": 1}}}})
    ending = _check(creative_refs, {"field": {"enum": list(ENDING_FIELDS)},
                                   "source_fact_ids": _refs(list(facts))})
    ending["allOf"].extend({"if": {"properties": {"field": {"const": field}}},
        "then": {"allOf": [_own_evidence(_check(creative_refs), [ref for ref in creative_refs
            if entries[ref]["kind"] == "ending" and entries[ref]["field"] == field])["allOf"][-1]]}}
        for field in ENDING_FIELDS)
    return base._obj({"plan_sha256": {"const": _digest(plan)},
        "brief_sha256": {"const": _digest(brief)}, "catalog_sha256": {"const": _digest(entries)},
        "source_obligation_checks": _table(obligation, ({"obligation_id": key} for key in obligations),
            "逐源义务映射实际creative beat原文，不能引用source_obligations/fact_refs自证。"),
        "fact_checks": _table(_check(creative_refs, {"fact_id": {"enum": list(facts)} if facts else False}),
            ({"fact_id": key} for key in facts), "逐fact全部复合要求与禁止项核对实际创作字段。"),
        "initial_state_checks": _table(initial, ({"entity_type": kind, "entity_id": entity} for kind, entity in states),
            "逐来源初态与计划物理声明及首拍动作前提。"),
        "source_order_checks": _table(order, ({"before_id": before, "after_id": after} for before, after in edges),
            "逐来源顺序核对真实创作发生，不抄source_order证明顺序。"),
        "beat_checks": _table(beat, ({"beat_id": row["id"]} for row in plan["beats"]),
            "每beat四项完整覆盖，引用当前beat及必要上下文。"),
        "ending_checks": _table(ending, ({"field": field} for field in ENDING_FIELDS),
            "三字段逐一核对，尤其未解问题不能否定已知事实。")})


def _coverage(rows, keys, expected, label):
    actual = [tuple(row[key] for key in keys) for row in rows]
    if len(actual) != len(set(actual)) or set(actual) != set(expected):
        raise ValueError(label + " must cover every original item exactly once")


def _rows(value):
    for table, fields in (("source_obligation_checks", ("obligation_id",)),
                          ("fact_checks", ("fact_id",)),
                          ("initial_state_checks", ("entity_type", "entity_id")),
                          ("source_order_checks", ("before_id", "after_id")),
                          ("ending_checks", ("field",))):
        for row in value[table]:
            yield table, {key: row[key] for key in fields}, row
    for row in value["beat_checks"]:
        for check_name, check in row["checks"].items():
            yield "beat_checks", {"beat_id": row["beat_id"], "check": check_name}, check


def _resolved(refs, entries):
    return [{"ref_id": ref, **deepcopy(entries[ref])} for ref in refs]


def validate_scene_plan_gate(value, plan, brief):
    schema = build_scene_plan_gate_schema(plan, brief)
    base._validate_schema(schema, value, "scene_plan_gate")
    facts, states, obligations, edges, entries = _inputs(plan, brief)
    _coverage(value["source_obligation_checks"], ("obligation_id",), ((key,) for key in obligations), "obligation checks")
    _coverage(value["fact_checks"], ("fact_id",), ((key,) for key in facts), "fact checks")
    _coverage(value["initial_state_checks"], ("entity_type", "entity_id"), states, "initial checks")
    _coverage(value["source_order_checks"], ("before_id", "after_id"), edges, "order checks")
    _coverage(value["beat_checks"], ("beat_id",), ((row["id"],) for row in plan["beats"]), "beat checks")
    _coverage(value["ending_checks"], ("field",), ((key,) for key in ENDING_FIELDS), "ending checks")
    for table, identity, row in _rows(value):
        if row["status"] == "pass" and not row["evidence_refs"]:
            raise ValueError("passing scene-plan check requires actual creative evidence")
        if row["status"] == "fail" and not row["required_revision"].strip():
            raise ValueError("failed scene-plan check requires a complete-plan repair target")
        if table == "beat_checks" and row["status"] != "unknown" and not any(
                entries[ref].get("beat_id") == identity["beat_id"] for ref in row["evidence_refs"]):
            raise ValueError("beat check must cite its own actual creative beat field")
        if table == "ending_checks" and row["status"] != "unknown" and not any(
                entries[ref]["kind"] == "ending" and entries[ref]["field"] == identity["field"]
                for ref in row["evidence_refs"]):
            raise ValueError("ending check must cite the actual ending field under review")
    for row in value["source_order_checks"]:
        if row["status"] == "pass" and (row["planned_relation"] != "explicit_before" or
                                        not row["before_evidence_refs"] or not row["after_evidence_refs"]):
            raise ValueError("passing planned order needs both actual creative occurrences and explicit-before judgment")
    return {"complete": True, "source_hash": _digest(value), "plan_sha256": _digest(plan),
        "brief_sha256": _digest(brief), "catalog_sha256": _digest(entries),
        "source_obligation_count": len(obligations), "fact_count": len(facts),
        "initial_entity_count": len(states), "beat_count": len(plan["beats"]),
        "source_echo_is_not_creative_evidence": True, "native_plan_changed": False,
        "semantic_quality_approved": False}


def compile_scene_plan_gate(value, plan, brief):
    validation = validate_scene_plan_gate(value, plan, brief)
    entries = creative_evidence_catalog(plan)
    compiled = deepcopy(value)
    for table, _, row in _rows(compiled):
        refs = row["evidence_refs"]
        if table == "source_order_checks":
            refs = list(dict.fromkeys(refs + row["before_evidence_refs"] + row["after_evidence_refs"]))
            row["before_evidence"] = _resolved(row["before_evidence_refs"], entries)
            row["after_evidence"] = _resolved(row["after_evidence_refs"], entries)
        row["evidence"] = _resolved(refs, entries)
    compiled["source_fact_texts"] = deepcopy(sources._facts(brief))
    compiled["source_initial_states"] = [{"entity_type": kind, "entity_id": entity, "expected_state": text}
        for (kind, entity), text in sources._states(brief).items()]
    compiled["validation"] = validation
    return compiled


def decide_scene_plan_gate(value, plan, brief):
    validation = validate_scene_plan_gate(value, plan, brief)
    facts, states, obligations, _, entries = _inputs(plan, brief)
    requirements, uncertainties = [], []
    prefixes = {"source_obligation_checks": "CREATIVE_SOURCE_OBLIGATION_", "fact_checks": "CREATIVE_FACT_",
        "initial_state_checks": "CREATIVE_INITIAL_", "source_order_checks": "CREATIVE_ORDER_",
        "beat_checks": "CREATIVE_BEAT_", "ending_checks": "CREATIVE_ENDING_"}
    for table, identity, row in _rows(value):
        mode_conflict = (table == "source_obligation_checks" and row["status"] == "pass" and
            row["coverage_type"] != {"event": "explicit_event", "state": "state_preserved", "absence": "absent_as_required"}[
                obligations[identity["obligation_id"]]["mode"]])
        if row["status"] == "pass" and not mode_conflict: continue
        target = uncertainties if row["status"] == "unknown" else requirements
        source_facts = list(row.get("source_fact_ids", []))
        if table == "source_obligation_checks": source_facts = [obligations[identity["obligation_id"]]["fact_id"]]
        elif table == "fact_checks": source_facts = [identity["fact_id"]]
        elif table == "source_order_checks":
            source_facts = list(dict.fromkeys(obligations[identity[key]]["fact_id"] for key in ("before_id", "after_id")))
        refs = row["evidence_refs"]
        if table == "source_order_checks":
            refs = list(dict.fromkeys(refs + row["before_evidence_refs"] + row["after_evidence_refs"]))
        item = {"code": prefixes[table] + "_".join(identity.values()), "source_item": identity,
            "plan_table": table, "native_status": row["status"], "problem": row["explanation"],
            "required_revision": FROZEN_PLAN_REPAIR, "model_repair_target": row["required_revision"],
            "evidence": _resolved(refs, entries),
            "source_evidence": [{"fact_id": key, "text": facts[key]} for key in source_facts]}
        if mode_conflict:
            item.update(code="CREATIVE_SOURCE_MODE_" + identity["obligation_id"],
                problem="待审计划声明的义务mode与独立模型按brief给出的覆盖方式不一致；不能拿旧mode自证正确。",
                plan_declared_mode=obligations[identity["obligation_id"]]["mode"],
                model_coverage_type=row["coverage_type"],
                native_explanation=row["explanation"],
                model_repair_target="依据冻结事实及原生审查证据重建完整计划中的义务类型与实际创作发生安排；不能把待审mode当事实或改brief。")
        if table == "initial_state_checks": item["source_initial_state"] = states[(identity["entity_type"], identity["entity_id"])]
        target.append(item)
    return {"status": "needs_whole_plan_revision" if requirements else "halt_source_uncertain" if uncertainties else "scene_plan_ready",
        "gate_sha256": _digest(value), "plan_sha256": _digest(plan), "brief_sha256": _digest(brief),
        "validation": validation, "revision_requirements": requirements, "uncertainties": uncertainties,
        "compiled_gate_sha256": _digest(compile_scene_plan_gate(value, plan, brief)),
        "native_plan_changed": False, "native_judgments_changed": False,
        "complete_native_plan_revision_required": bool(requirements),
        "human_approved": False, "human_quality_approved": False,
        "creative_quality_passed": False, "automatic_media_submit": False}
