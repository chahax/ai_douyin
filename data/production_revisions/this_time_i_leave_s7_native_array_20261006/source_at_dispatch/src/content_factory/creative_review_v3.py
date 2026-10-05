"""Independent evidence-bound textual review, separate from legacy scoring."""
from __future__ import annotations
import json
import re
from copy import deepcopy
from .creative_workflow_contract import CreativeContractError

VERSION = "evidence_review_v3"
CHECKS = ("requirements", "timing", "continuity", "dialogue_timing", "first_frame", "assets")


def build_review_prompt(context: dict) -> str:
    joint = "shots" in context
    scope = "分镜与制作方案" if joint else "完整剧本"
    rows = context.get("shots", {}).get("shots", []) if joint else context.get("script", {}).get("beats", [])
    ids = [r["id"] for r in rows]
    prompt = f"""你是DeepSeek独立文字审核员。只审查{scope}，不代写、不评分、不宣称实际画面、声音、口型或媒体通过。
唯一输出JSON顶层字段恰为story_preserved(bool)、issues(array)、suggestions(array)、calibration_focus(array)、coverage(array)。有必修问题story_preserved=false，否则true。
issues每项字段：id、owner(writer/director)、location(已有B/SH编号)、severity(blocking/major)、rule、evidence、contradiction、impact、proposal、evidence_refs。只报告直接违反简报或真实叙事/制作错误；可选审美进入suggestions，每项location/proposal/reason。不要从猜测发明禁令，不按动作数量猜超时，同根因合并。
evidence_refs每项为{{"path":"输入字段点分路径","quote":"该叶子字段逐字片段"}}。只引用字符串/数字叶子，不引用对象数组；对白到dialogue.0.text。每条issue至少一条当前script/shots/production_design正文证据。原创简报优先于候选擅自加入的实现。
coverage逐行覆盖编号且各一次：{json.dumps(ids, ensure_ascii=False)}。每行{{"id":"当前编号","checks":{{...}}}}，checks固定六项：{', '.join(CHECKS)}。每项{{"status":"pass/fail/not_applicable","reason":"具体核对结果","evidence_refs":[],"issue_ids":[]}}。pass/fail必须有本行实际正文叶子证据。fail关联已列issues的id，其他状态issue_ids=[]。not_applicable只用于确实不适用的项目并解释；不能把漏写、缺证据当通过或不适用。明确需要而缺失的信息应fail，引用最近现有正文解释缺口。摘要声称完成不证明正文做到。
逐项要求：
requirements：核对简报硬约束、人物关系、转折、结尾主动者、道具数量；实际正文优先于event/premise自述。必须检查。
timing：按刺激→听到→反应→回应。剧本before→首句dialogue→during→次句dialogue→after，event/trigger只是摘要。重要对白规定的反应窗口必须在正文明确，可合法跨拍。空转重复动作若无明确违反仅建议。必须检查。
continuity：对照上一镜末与本镜首的视线、姿态、位置、持物者、道具落点和布局；有上一镜必须引用双方正文。分段首镜若有previous_shot就引用previous_shot，否则引用shots.shots前项。真正将已完成转头/坐下/交物重置到未发生起点才是错误；自然小动作和合理步行省略不自动构成矛盾。首拍描述初始状态，无上一镜也要检查内部连续性。必须检查。
dialogue_timing：有对白写实际台词字数、可用秒数、必要前后动作与反应所占时间，核算速度是否自然；不要只看总时长或将同时动作全部相加。无对白可not_applicable说明原因。不能声称已听过语速或声线。
first_frame：分镜首帧必须为动作发生前状态。逐项核对是否提前转头、站起、递出、接物、移杯、坐下或情绪反应；与上一镜尾及全局左右/朝向布局对照。分镜必须检查；剧本可not_applicable。文字通过不等于实际图片通过。
assets：核对所见人物、场景、道具与资产id/定义、画风、服装、左右布局匹配。区分历史合适资产和待生成资产，不假定复用已成功。未提供production_design的单段只检查当前可见需求，完整映射明确待后续联合审查，不把尚未生成的后续文件列缺失。剧本可not_applicable。
calibration_focus只列后续媒体验证项，不把已驳回假设变新硬条件。没问题/建议时数组为空。自己核查，不复制示例结论。"""
    if context.get("review_scope") == "storyboard_segment":
        prompt += """
本次范围限定（单节拍分镜审核，优先于上文全片用语）：
script只包含当前正在制作的节拍，shots只包含当前节拍的镜头。whole_story_outline或full_story_outline仅提供完整故事的前后文；其中后续节拍尚待制作，不能因本次shots没有后续节拍、全片转折、最终结尾或总时长而报缺失。只判断当前节拍是否忠实完成其script任务、符合适用于当前时点的brief约束，并与previous_shot衔接；不要要求当前拍提前兑现未来结尾或未来动作。未来约束留在相应节拍及最终全片复核。
六项coverage仍逐个引用当前镜头的实际正文，不能只引用全局shots.style、资产catalog或brief。即使assets检查的是全局画风/布局，也至少引用一条shots.shots.当前索引.具体叶子，再辅以全局字段证据；引用人物、场景、服装或道具的本镜描述说明此镜如何匹配全局要求。没有production_design时只核对当前可见资产需求，不虚构缺失后续资产设计。
对白时间按实际并行关系核算：甲说话时乙同步放杯、抬眼或换姿势，并不自动减少甲的可说话时间。只有明确必须在对白前后串行完成的动作、停顿、听后反应或对说话有实际限制的动作，才从可用对白时间扣除；先列明顺序和重叠，再提出有证据的时长问题。不要为了保守而将不同人物的同时动作全部串行相加。
"""
    return prompt


def _references(refs, context):
    if not isinstance(refs, list):
        raise CreativeContractError("coverage.evidence_refs必须为数组")
    paths = []
    for ref in refs:
        try:
            path, quote = ref["path"], ref["quote"]
            if not isinstance(path, str) or not isinstance(quote, str) or not quote.strip():
                raise ValueError()
            target = context
            for part in path.split("."):
                target = target[int(part)] if isinstance(target, list) else target[part]
            valid = quote in target if isinstance(target, str) else type(target) in (int, float) and quote == json.dumps(target)
            if not valid:
                raise ValueError()
            paths.append(path)
        except (ValueError, KeyError, IndexError, TypeError):
            raise CreativeContractError("coverage引用路径或逐字证据无效: " + str(ref)) from None
    return paths


def validate_v3_review(value: dict, context: dict) -> None:
    # Local import avoids a module import cycle with the version registry.
    from .creative_review_gate import validate_review
    validate_review(value, context)
    top = {"story_preserved", "issues", "suggestions", "calibration_focus", "coverage"}
    if set(value) != top:
        raise CreativeContractError("v3审核顶层字段必须恰为" + ",".join(sorted(top)))
    if value["story_preserved"] != (not value["issues"]):
        raise CreativeContractError("v3 story_preserved与必修issues不一致")
    joint = "shots" in context
    rows = context.get("shots", {}).get("shots", []) if joint else context.get("script", {}).get("beats", [])
    root = "shots.shots" if joint else "script.beats"
    expected = [r["id"] for r in rows]
    coverage = value.get("coverage")
    if not isinstance(coverage, list) or any(not isinstance(r, dict) or not isinstance(r.get("id"), str) for r in coverage):
        raise CreativeContractError("coverage必须为带id的对象数组")
    actual = [r["id"] for r in coverage]
    if len(actual) != len(expected) or set(actual) != set(expected):
        raise CreativeContractError("coverage必须逐一覆盖全部当前beat/shot且不能重复")
    issue_ids = {i["id"] for i in value["issues"]}
    linked = set()
    for row in coverage:
        checks = row.get("checks")
        if not isinstance(checks, dict) or set(checks) != set(CHECKS):
            raise CreativeContractError("coverage.checks必须包含且仅包含六项检查")
        index = expected.index(row["id"])
        own = f"{root}.{index}."
        for name, check in checks.items():
            if not isinstance(check, dict) or set(check) != {"status", "reason", "evidence_refs", "issue_ids"}:
                raise CreativeContractError("coverage检查字段不完整")
            status = check["status"]
            if status not in ("pass", "fail", "not_applicable") or not isinstance(check["reason"], str) or not check["reason"].strip():
                raise CreativeContractError("coverage状态或reason无效")
            paths = _references(check["evidence_refs"], context)
            if status != "not_applicable" and not any(p.startswith(own) for p in paths):
                raise CreativeContractError("coverage pass/fail必须引用本行正文")
            if name in ("requirements", "timing", "continuity") and status == "not_applicable":
                raise CreativeContractError("需求、时序、连续性不能跳过")
            if joint and name == "first_frame" and status == "not_applicable":
                raise CreativeContractError("分镜首帧不能跳过")
            prev = f"{root}.{index - 1}." if index else "previous_shot." if context.get("previous_shot") else None
            if joint and name == "continuity" and prev and not any(p.startswith(prev) for p in paths):
                raise CreativeContractError("连续性检查必须引用上一镜正文")
            ids = check["issue_ids"]
            if not isinstance(ids, list) or any(not isinstance(i, str) or i not in issue_ids for i in ids):
                raise CreativeContractError("coverage关联未知issue")
            if (status == "fail") != bool(ids):
                raise CreativeContractError("coverage fail必须关联issue，其他状态不得关联")
            linked.update(ids)
    if linked != issue_ids:
        raise CreativeContractError("每条issue必须有对应fail检查")


def canonicalize_unique_leaf_refs(value, context):
    """Expand an existing container reference only when its quote identifies one leaf.

    Never edits evidence text, statuses, issues, conclusions or the caller's object.
    Ambiguous matches (including an exact match plus a substring elsewhere) stay invalid.
    """
    result = deepcopy(value)
    changes = []
    if not isinstance(result, dict):
        return result, changes

    def leaf_matches(node, path, quote):
        if isinstance(node, dict):
            matches = []
            for key, child in node.items():
                if isinstance(key, str) and "." not in key:
                    matches.extend(leaf_matches(child, path + "." + key, quote))
            return matches
        if isinstance(node, list):
            matches = []
            for index, child in enumerate(node):
                matches.extend(leaf_matches(child, path + "." + str(index), quote))
            return matches
        if isinstance(node, str) and quote in node:
            return [path]
        if type(node) in (int, float) and quote == json.dumps(node):
            return [path]
        return []

    def repair_refs(refs, location):
        if not isinstance(refs, list):
            return
        for index, ref in enumerate(refs):
            if not isinstance(ref, dict):
                continue
            path, quote = ref.get("path"), ref.get("quote")
            if not isinstance(path, str) or not isinstance(quote, str) or not quote.strip():
                continue
            target = context
            try:
                for part in path.split("."):
                    if isinstance(target, list):
                        if not part.isdecimal():
                            raise ValueError()
                        target = target[int(part)]
                    elif isinstance(target, dict):
                        target = target[part]
                    else:
                        raise ValueError()
            except (ValueError, KeyError, IndexError, TypeError):
                # One known envelope alias only; never search arbitrary missing paths.
                alias = re.fullmatch(r"shots\.shots\.(\d+)\.media_assumptions\.(\d+)\.assumption", path)
                if not alias:
                    continue
                shot_index, assumption_index = (int(index) for index in alias.groups())
                try:
                    actual_shots = context["shots"]["shots"]
                    if not isinstance(actual_shots, list) or shot_index >= len(actual_shots):
                        continue
                    aliased = context["shots"]["media_assumptions"][assumption_index]["assumption"]
                except (KeyError, IndexError, TypeError):
                    continue
                valid = quote in aliased if isinstance(aliased, str) else type(aliased) in (int, float) and quote == json.dumps(aliased)
                if not valid:
                    continue
                canonical = f"shots.media_assumptions.{assumption_index}.assumption"
                ref["path"] = canonical
                changes.append({"reference_path": location + "." + str(index),
                                "from_path": path, "to_path": canonical, "quote": quote})
                continue
            if not isinstance(target, (dict, list)):
                # Known production_choices indexing error only; preserve correct leaf refs.
                indexed = re.fullmatch(r"shots\.shots\.(\d+)\.production_choices\.(\d+)", path)
                if not indexed or not isinstance(target, str) or quote in target:
                    continue
                try:
                    siblings = context["shots"]["shots"][int(indexed.group(1))]["production_choices"]
                except (KeyError, IndexError, TypeError):
                    continue
                if not isinstance(siblings, list):
                    continue
                matches = [i for i, sibling in enumerate(siblings)
                           if isinstance(sibling, str) and quote in sibling]
                if len(matches) != 1:
                    continue
                canonical = f"shots.shots.{int(indexed.group(1))}.production_choices.{matches[0]}"
                ref["path"] = canonical
                changes.append({"reference_path": location + "." + str(index),
                                "from_path": path, "to_path": canonical, "quote": quote})
                continue
            matches = leaf_matches(target, path, quote)
            if len(matches) != 1:
                continue
            ref["path"] = matches[0]
            changes.append({"reference_path": location + "." + str(index),
                            "from_path": path, "to_path": matches[0], "quote": quote})

    issues = result.get("issues")
    if isinstance(issues, list):
        for index, issue in enumerate(issues):
            if isinstance(issue, dict):
                repair_refs(issue.get("evidence_refs"), f"issues.{index}.evidence_refs")
    coverage = result.get("coverage")
    if isinstance(coverage, list):
        for index, row in enumerate(coverage):
            if not isinstance(row, dict) or not isinstance(row.get("checks"), dict):
                continue
            for name, check in row["checks"].items():
                if isinstance(check, dict):
                    repair_refs(check.get("evidence_refs"), f"coverage.{index}.checks.{name}.evidence_refs")
    return result, changes
