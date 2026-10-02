"""Scoped evidence review with explicit playback semantics and source asset checks."""
from __future__ import annotations
import json
from .creative_review_v3 import validate_v3_review
from .creative_review_v4 import build_review_prompt as _v4_prompt, required_execution_paths, _leaf_paths
from .creative_workflow_contract import CreativeContractError

VERSION = "evidence_review_v5"


def required_asset_sources(context):
    # Actual source definitions, never the shot's claim that it matches them.
    return list(_leaf_paths(context.get("shots", {}).get("style", {}), "shots.style"))


def build_review_prompt(context):
    prompt = _v4_prompt(context)
    prompt = prompt.replace("在本镜六项checks引用并集中覆盖下方全部执行路径", "在本镜六项checks及其关联的同镜issues引用中合计覆盖下方全部执行路径")
    prompt += """
规则解释边界（以下说明用于精确执行上述规则，不新增审美禁令）：
1. 固定机位只锁定摄影机，不锁定演员位置、朝向、画面占比或初始景别。演员从桌边朝纵深走两步、转成侧背影可以在同一固定镜头自然发生。composition的初始构图不默认是每一秒的恒定姿态；只有明确写“全程保持某姿态/尺寸/位置”且与实际动作直接冲突，或明确硬切/换机位，才报必修问题。不能凭“可能出画”推断必然硬切。
2. 按结构字段还原播放：before → dialogue[0] → during → dialogue[1]（若有）→ after。during里“走两步、自然道别离开”这类摘要不能推翻独立dialogue的播放位置，也不能凭日常措辞强制对白与步行同步。例如before松肩、dialogue说再见、during转身走、after同伴坐下，先对白后走路是忠实执行。只有明确同步要求或正文间实际矛盾才报错。
3. 时间区间“0.0–1.5秒完成松肩”表示从初始状态开始执行动作，不等于0.0秒首帧已松肩。start_state仍紧、随后区间松肩合法，无须无依据额外插入静止等待。首帧明确写已松肩/已开始松肩却要重复松肩，或接受对白结束之前已松肩，才是实际冲突。0秒的采样状态与其后连续运动必须区分。
4. assets必须核对实际shots.style源字段：character_lock只应保留身份、稳定外貌、服装，不应强迫每镜重演“拿起文件夹/保持紧肩”等动态动作或临时情绪。核对style中动作与本镜start_state、时间轴是否冲突，不能仅引用shot自称“不提前/严格一致”就判通过。不要因同镜道具允许落桌或人物后续坐下就把它们解释为换人或身份改变。未提供production_design时资产映射留待后续，现有style冲突仍应查出。
5. 每项check仍引用本镜正文并说明比较结论；同一check关联的同镜issue中已有真实证据可复用，无须复制到check里。全部执行路径的覆盖可计入本镜issues证据；不同镜issue不算。每个对照双方仍必须存在于该check或它关联的同镜issue中。assets还需引用实际style源叶子，与本镜可见需求对照；source不存在时不可编造路径。
以上只是语义边界，不预设当前稿合格。优先寻找能支持正常解释的实际正文，再报告有相反证据仍无法成立的冲突；已知动态style污染不能因镜内局部正确被放过。
"""
    if "shots" in context:
        prompt += "\nassets需核对并引用的实际源路径：" + json.dumps(required_asset_sources(context), ensure_ascii=False)
    return prompt


def validate_review_v5(value, context):
    validate_v3_review(value, context)
    if "shots" not in context:
        return
    coverage = {row["id"]: row["checks"] for row in value["coverage"]}
    required = required_execution_paths(context)
    issues = {issue["id"]: issue for issue in value["issues"]}
    comparisons = {"timing": ("visible_performance", "prompt"),
                   "continuity": ("start_state", "end_state", "visible_performance"),
                   "first_frame": ("start_state", "visible_performance")}
    for index, shot in enumerate(context["shots"]["shots"]):
        checks = coverage[shot["id"]]
        own_issues = {key: issue for key, issue in issues.items() if issue["location"] == shot["id"]}
        def paths_for(check):
            refs = list(check["evidence_refs"])
            for issue_id in check["issue_ids"]:
                refs.extend(own_issues.get(issue_id, {}).get("evidence_refs", []))
            return {ref["path"] for ref in refs}
        union = {path for check in checks.values() for path in paths_for(check)}
        union.update(ref["path"] for issue in own_issues.values() for ref in issue["evidence_refs"])
        missing = set(required[shot["id"]]) - union
        if missing:
            raise CreativeContractError("v5执行字段未交叉核对: " + ", ".join(sorted(missing)))
        for name, fields in comparisons.items():
            expected = {path for field in fields if field in shot
                        for path in _leaf_paths(shot[field], f"shots.shots.{index}.{field}")}
            if expected - paths_for(checks[name]):
                raise CreativeContractError(f"v5 {name}必须引用对照双方: " + ", ".join(sorted(expected - paths_for(checks[name]))))
        missing_sources = set(required_asset_sources(context)) - paths_for(checks["assets"])
        if missing_sources:
            raise CreativeContractError("v5 assets必须引用实际style源: " + ", ".join(sorted(missing_sources)))
