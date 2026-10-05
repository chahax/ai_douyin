"""Compact comparative review; evidence completeness is not semantic approval."""
from copy import deepcopy
import json
from .creative_review_v3 import build_review_prompt as base_prompt, validate_v3_review
from .creative_workflow_contract import CreativeContractError
VERSION = "evidence_review_v6"

def comparison_requirements(context):
    requirements = {}
    for i, shot in enumerate(context.get("shots", {}).get("shots", [])):
        own = f"shots.shots.{i}."
        required = {"timing": ["script.beats."], "first_frame": [own + "start_state", own + "visible_performance"]}
        if context.get("creative_brief"):
            required["requirements"] = ["creative_brief."]
        elif context.get("brief"):
            required["requirements"] = ["brief."]
        if context.get("shots", {}).get("style"):
            required["assets"] = ["shots.style."]
        if context.get("state_plan"):
            required["continuity"] = ["state_plan."]
        requirements[shot["id"]] = required
    return requirements

def build_review_prompt(context):
    prompt = base_prompt(context) + """
本版本采用简洁对照证据，不要求把所有执行字段逐字重复六遍。每项仍须当前镜正文及相应来源；下方规定的路径前缀只需各一条真实相关叶子，不代表引用了就审查通过。reason说明双方是否相符。
全片state_plan是被审核的计划，不是正确答案：对照剧本实际先后、初始状态、events动作与changes、对白窗口、反应窗口；检查将来坐下/拿取等动作的前置条件是否在先前成立。不能因程序契约通过就忽略自由文本和状态变化不一致。
首态是t=0，0秒开始的动作区间并不要求先增加静止等待；已经到达目的地却又重复到达才是矛盾。末态里的“抬眼看向/已坐下”通常记录动作结果，不默认是新动作或再做一次。固定摄影机允许人物移动、走向纵深、自然改变画面占比；只有明确要求全程不变才产生冲突。
对白按真实字数/已分配对白窗口核算；中文字计1，拉丁词计2。5单位/秒为执行上限，低于上限且有串行反应空间不能仅凭“偏紧、可能、未声明语速”列必修；审美慢读放suggestions，实际语速留媒体审核。不同人物并行动作不重复扣时。明确停顿/情绪要求仍须核查。
审查production_design时核对其资产映射和opening_prompt与对应镜首态；计划及编译prompt若相冲突必须报告，不能只审其中一个。
""" + "\n每镜每项最少对照来源前缀：" + json.dumps(comparison_requirements(context), ensure_ascii=False)
    from .creative_review_evidence_ids import enabled as ids_enabled, build_prompt as ids_prompt
    if ids_enabled(context):
        return ids_prompt(context, prompt)
    from .creative_review_evidence_catalog import enabled, prompt_addendum
    return prompt + (prompt_addendum(context) if enabled(context) else "")

def evidence_gaps(value, context):
    gaps = []
    joint = "shots" in context
    rows = context.get("shots", {}).get("shots", []) if joint else context.get("script", {}).get("beats", [])
    indexes = {row["id"]: i for i, row in enumerate(rows)}
    requirements = comparison_requirements(context)
    if not isinstance(value, dict) or not isinstance(value.get("coverage"), list):
        return gaps
    for i, row in enumerate(value["coverage"]):
        if not isinstance(row, dict) or row.get("id") not in indexes or not isinstance(row.get("checks"), dict):
            continue
        index = indexes[row["id"]]
        own = ("shots.shots" if joint else "script.beats") + f".{index}."
        for name, check in row["checks"].items():
            if not isinstance(check, dict) or not isinstance(check.get("evidence_refs"), list):
                continue
            paths = [r.get("path", "") for r in check["evidence_refs"] if isinstance(r, dict) and isinstance(r.get("path"), str)]
            prefixes = list(requirements.get(row["id"], {}).get(name, []))
            if check.get("status") in ("pass", "fail"):
                prefixes.append(own)
            if joint and name == "continuity":
                previous = f"shots.shots.{index-1}." if index else "previous_shot." if context.get("previous_shot") else None
                if previous:
                    prefixes.append(previous)
            missing = [p for p in prefixes if not any(path.startswith(p) for path in paths)]
            if missing:
                gaps.append({"check_path": f"coverage.{i}.checks.{name}.evidence_refs", "missing_source_prefixes": missing})
    return gaps


def validate_review_v6(value, context):
    from .creative_review_evidence_catalog import enabled, validate_evidence
    if enabled(context):
        validate_evidence(value, context)
    gaps = evidence_gaps(value, context)
    if gaps:
        raise CreativeContractError("v6缺少对照证据: " + json.dumps(gaps, ensure_ascii=False))
    validate_v3_review(value, context)
    requirements = comparison_requirements(context)
    for i, row in enumerate(value["coverage"]):
        for name, prefixes in requirements.get(row["id"], {}).items():
            check = row["checks"][name]
            paths = [ref["path"] for ref in check["evidence_refs"]]
            missing = [prefix for prefix in prefixes if not any(p.startswith(prefix) for p in paths)]
            if missing:
                raise CreativeContractError(f"coverage.{i}.checks.{name}.evidence_refs 缺少对照来源: " + ", ".join(missing))

def build_review_repair(problem, context, original):
    from .creative_review_evidence_ids import enabled as ids_enabled, build_repair as ids_repair, FIELD
    if ids_enabled(context):
        legacy_context={k:v for k,v in context.items() if k!=FIELD}
        return ids_repair(problem,context,original,build_review_prompt(legacy_context))
    instruction = ("修复审核JSON契约，不重新创作或改变审核结论。完整原文在review_context，目标契约在target_contract。"
        "只补全/修正evidence_refs中的真实叶子路径和逐字引用，原issues、status、reason、issue_ids、suggestions、calibration_focus逐字保留。"
        "不得因补证失败删除问题或改为通过。返回完整审核对象，不返回patches。若确无支持原结论的证据，保留结论并让审核停止等待人工处理，不编造。")
    payload = {"validation_error": problem, "review_context": deepcopy(context),
        "invalid_review": deepcopy(original), "target_contract": build_review_prompt(context),
        "required_comparisons": comparison_requirements(context), "missing_check_paths": evidence_gaps(original, context)}
    from .creative_review_evidence_catalog import enabled, diagnostics
    if enabled(context):
        payload["evidence_diagnostics"] = diagnostics(original, context)
    return instruction, payload

def validate_repair_preserves_conclusions(original, corrected):
    def without_refs(value):
        if isinstance(value, dict):
            return {k: without_refs(v) for k,v in value.items() if k != "evidence_refs"}
        if isinstance(value, list):
            return [without_refs(v) for v in value]
        return value
    if without_refs(original) != without_refs(corrected):
        raise CreativeContractError("v6审核补证不得改变原问题、结论或覆盖状态")
