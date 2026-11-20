"""Independent knowledge-state review of a plan's three actual ending fields.

The model owns semantic extraction and comparison. Local checks bind immutable
creative fields and frozen fact fragments, then route findings without editing
the original plan or replacing any other scene-plan gate.
"""
from __future__ import annotations

from copy import deepcopy
from . import creative_autonomous_text_contract_v1 as base
from . import creative_autonomous_text_contract_v2 as sources

VERSION = "creative_plan_ending_scope/v1"
FIELDS = ("attempt_result", "visible_consequence", "open_problem")
KNOWLEDGE_TYPES = ("known_result", "open_dispute", "unknown_fact", "future_undertaking", "procedural_assumption")
RELATIONS = ("compatible", "contradicted", "unsupported", "unknown")
FROZEN_PLAN_REPAIR = (
    "冻结brief及初态不变。由生成模型提交完整新创作计划，使结尾的实际结果、可见后果与未解问题"
    "符合源事实及前面已安排的行动；不补字段、不本地替换、不把已知事实降为未知，不新增业务程序或后续承担。")
RULE = (
    "你是独立结尾知识状态审查员，只读冻结brief和实际创作计划字段，不读source_obligations、"
    "来源合同复述、旧裁决或测试预期。逐ending三个字段提取全部具体实际命题或疑问，"
    "包括一字段内混合的不同命题；quote必须是该字段真实原片段，proposition简明还原其意义，"
    "proposition_mode区分asserted与questioned。每个字段至少一项，不能只复述整字段整体pass而漏掉子命题。"
    "knowledge_type区分本场已知结果known_result、尚未解决的争议open_dispute、"
    "计划声称事实未知unknown_fact、未来承担future_undertaking、程序性假设procedural_assumption。"
    "source_relation分别判断compatible、contradicted、unsupported、unknown；依据brief真实fact片段"
    "及前面实际创作安排解释，不以来源合同自证，不把自己的解释加进计划。"
    "争议未解决不等于事实未说明：明确的决定施事、原因或已发生行动，不能因后续程序未完成"
    "就回退成不知道是谁决定。没有来源说正式书面通知尚缺，不能自行增加尚未正式说明、"
    "尚未确认等程序条件来豁免已经当面明确的事实；当面说明与正式通知不是可随意互换的概念。"
    "未知问题可以开放，但必须与来源及前面实际安排相容；追问已有答案不因问句形式自动合法。"
    "未签成只能说明本场要求受阻，不能自动保证手续已结束、后续如何处理或谁将承诺办理。"
    "自然动作后果可与前面安排相容；不要把普通表演细节一概当新法律事实。"
    "source_refs只填真实fact_id及该fact原文片段，不复写expected或复述来源；没有源依据可空数组，"
    "如实unsupported或unknown，不虚构引文。来源引用真实不等于具体结尾命题成立。"
    "contradicted/unsupported给完整计划必修目标；无法判断用unknown，不代写计划或替代台词，"
    "不修改原scene gate判断，不声称完整剧本、视频或人工审美通过。每项简短，按Schema完整提交。")


def _digest(value):
    return base._digest(value)


def creative_projection(plan):
    """Source-obligation prose and previous judgments never enter this gate."""
    creative = {key: deepcopy(plan[key]) for key in
                ("title", "dramatic_question", "audience_arc", "character_goals", "ending")}
    creative["beats"] = [{key: deepcopy(row[key]) for key in
        ("id", "trigger", "attempt", "acting_character_id", "target_character_id", "state_change")}
        for row in plan["beats"]]
    return creative


def _inputs(plan, brief):
    base.validate_plan({key: deepcopy(plan[key]) for key in
        ("title", "dramatic_question", "audience_arc", "character_goals", "beats", "ending")}, brief)
    creative = creative_projection(plan)
    return creative, sources._facts(brief)


def build_schema(plan, brief):
    creative, facts = _inputs(plan, brief)
    finding = base._obj({
        "id": base._text(), "quote": base._text(), "proposition": base._text(),
        "proposition_mode": {"enum": ["asserted", "questioned"]},
        "knowledge_type": {"enum": list(KNOWLEDGE_TYPES)},
        "source_relation": {"enum": list(RELATIONS)},
        "source_refs": {"type": "array", "uniqueItems": True, "items": base._obj({
            "fact_id": {"enum": list(facts)} if facts else False, "quote": base._text()})},
        "explanation": base._text(), "required_revision": {"type": "string"},
    })
    finding["properties"]["quote"]["description"] = "所属ending field实际原文片段；必须逐字位于该字段，不是正文或别的计划字段。"
    finding["properties"]["source_refs"]["description"] = "仅该fact_id真实冻结fact的原文片段，不复述、不跨事实引用；缺源可空。"
    variants = [base._obj({"field": {"const": field},
        "findings": {"type": "array", "minItems": 1, "items": deepcopy(finding)}}) for field in FIELDS]
    return base._obj({"plan_sha256": {"const": _digest(plan)},
        "creative_plan_sha256": {"const": _digest(creative)}, "brief_sha256": {"const": _digest(brief)},
        "ending_fields": {"type": "array", "minItems": len(FIELDS), "maxItems": len(FIELDS),
            "items": {"oneOf": variants}, "allOf": [
                {"contains": {"type": "object", "properties": {"field": {"const": field}}, "required": ["field"]},
                 "minContains": 1, "maxContains": 1} for field in FIELDS],
            "description": "三个ending字段各恰一次；每字段逐子命题/疑问提取，finding id全表唯一。"}})


def validate(value, plan, brief):
    base._validate_schema(build_schema(plan, brief), value, "plan_ending_scope")
    creative, facts = _inputs(plan, brief)
    fields = [row["field"] for row in value["ending_fields"]]
    if len(fields) != len(set(fields)) or set(fields) != set(FIELDS):
        raise ValueError("ending scope must cover every actual ending field exactly once")
    ids = []
    for field in value["ending_fields"]:
        for row in field["findings"]:
            ids.append(row["id"])
            if not row["quote"].strip() or row["quote"] not in creative["ending"][field["field"]]:
                raise ValueError("ending finding quote must be an unchanged fragment of its own field")
            for ref in row["source_refs"]:
                if not ref["quote"].strip() or ref["quote"] not in facts[ref["fact_id"]]:
                    raise ValueError("ending source quote must be an unchanged fragment of its bound frozen fact")
    if len(ids) != len(set(ids)):
        raise ValueError("ending finding IDs must be globally unique")
    return {"complete": True, "source_hash": _digest(value), "plan_sha256": _digest(plan),
        "creative_plan_sha256": _digest(creative), "brief_sha256": _digest(brief),
        "finding_count": len(ids), "native_plan_changed": False, "semantic_quality_approved": False}


def decide(value, plan, brief):
    validation = validate(value, plan, brief)
    requirements, uncertainties = [], []
    for field in value["ending_fields"]:
        for row in field["findings"]:
            if row["source_relation"] == "compatible":
                continue
            target = uncertainties if row["source_relation"] == "unknown" else requirements
            target.append({"code": "ENDING_SCOPE_" + row["id"], "field": field["field"],
                "finding_id": row["id"], "native_source_relation": row["source_relation"],
                "knowledge_type": row["knowledge_type"], "proposition": row["proposition"],
                "proposition_mode": row["proposition_mode"], "problem": row["explanation"],
                "evidence": [{"path": "plan.ending." + field["field"], "quote": row["quote"]}],
                "source_evidence": deepcopy(row["source_refs"]),
                "required_revision": FROZEN_PLAN_REPAIR, "model_repair_target": row["required_revision"]})
    return {"status": "needs_whole_plan_revision" if requirements else
            "halt_source_uncertain" if uncertainties else "ending_scope_ready",
        "validation": validation, "plan_sha256": _digest(plan), "brief_sha256": _digest(brief),
        "revision_requirements": requirements, "uncertainties": uncertainties,
        "known_failure_repaired_before_uncertainty": True, "native_plan_changed": False,
        "native_judgments_changed": False, "other_scene_gate_replaced": False,
        "human_approved": False, "human_quality_approved": False,
        "creative_quality_passed": False, "automatic_media_submit": False}
