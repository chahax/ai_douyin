"""Cross-field evidence coverage; semantic decisions still require independent review."""
from __future__ import annotations
import json
from .creative_review_v3 import CHECKS, validate_v3_review
from .creative_workflow_contract import CreativeContractError

VERSION = "evidence_review_v4"
EXECUTION_FIELDS = ("start_state", "end_state", "visible_performance", "prompt", "camera", "composition", "cut_reason", "opening_prompt")


def _leaf_paths(node, root):
    if isinstance(node, dict):
        for key, item in node.items():
            yield from _leaf_paths(item, f"{root}.{key}")
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from _leaf_paths(item, f"{root}.{index}")
    elif isinstance(node, str) and node.strip() or type(node) in (int, float):
        yield root


def required_execution_paths(context):
    result = {}
    for index, shot in enumerate(context.get("shots", {}).get("shots", [])):
        root = f"shots.shots.{index}"
        paths = []
        for field in (*EXECUTION_FIELDS, "production_choices"):
            if field in shot:
                paths.extend(_leaf_paths(shot[field], f"{root}.{field}"))
        result[shot["id"]] = paths
    return result


def build_review_prompt(context):
    joint = "shots" in context
    rows = context.get("shots", {}).get("shots", []) if joint else context.get("script", {}).get("beats", [])
    ids = [row["id"] for row in rows]
    prompt = """你是DeepSeek独立文字审核员。审核当前稿，不代写、不评分，不宣称实际画面、声音或口型通过。
优先级：用户creative_brief显式硬约束最高；已确认script的动作主体、对白、因果和播放顺序约束分镜。previous_shot只证明已发生的末状态，不能代替当前剧本；event/premise/cut_reason等摘要不能推翻正文。发现正文与摘要相反也必须指出，因为它会被传入后续生成。
输出JSON顶层恰为story_preserved(bool)、issues(array)、suggestions(array)、calibration_focus(array)、coverage(array)。issues非空时story_preserved=false，否则true。
issue字段为id、owner(writer/director)、location(已有B/SH编号)、severity(blocking/major)、rule、evidence、contradiction、impact、proposal、evidence_refs。只列必修问题，同根因合并；proposal给修复目标，不代写。可选审美进入suggestions，每项location/proposal/reason；空数组合法。calibration_focus仅列后续媒体验证项。
evidence_refs每项为{"path":"输入中的点分路径","quote":"对应叶子逐字片段"}，不得引用对象数组；对白到dialogue.0.text。每个issue至少一条实际script/shots/production_design正文；矛盾类问题引用相反两方，不能仅引一句自称正确的说明。
coverage逐个编号且各一次，每行{"id":"当前编号","checks":{...}}，checks恰为requirements、timing、continuity、dialogue_timing、first_frame、assets。每项恰为status(pass/fail/not_applicable)、reason(具体对照结果)、evidence_refs(array)、issue_ids(array)。pass/fail必须引当前行正文；fail关联issues编号，其他状态issue_ids=[]。每条issue至少关联一个fail。缺失信息不能伪称通过；必须具备而缺失时引用现有字段说明缺口并fail。
审核方法：先通读所有执行字段和每条production_choices，再主动查找与当前判断相反的指令。同一动作逐一核对“谁→何时→起点→变化→结果”，不能靠“严格承接、首帧未完成、属于常态”等自我保证判断通过。相反说明即使藏在否定句、括号或末尾也计入。引用字段只是覆盖证据，不证明你的语义结论正确。
requirements：对照简报适用条件与实际正文，核对人物关系、行动主体、转折、结尾、道具；不得把正常解释或个人偏好升成禁令。必须检查。
timing：剧本实际播放为before→第一句dialogue→during→后续dialogue→after；分镜时间轴必须服从此序。对照visible_performance、prompt、production_choices，检查同一动作是否一处在对白前另一处禁止在对白前，反应是否先于刺激，主体是否偷换。必须检查。
continuity：检查上一镜末→本镜首→镜内各时点→本镜末，逐人物追踪视线、姿态、位置、持物者和固定布局。上一镜存在就引双方正文；不能只检查开头。机位变化可改变屏幕左右，但不能无动作改变人物与椅子/桌子的世界相对位置；必须给出实际动作或明确一致映射，不能用“场景常态”豁免。一个SH是一个连续镜头，camera/composition/prompt内安排硬切或两套机位应拆镜，planned_cut_requires_adapter仅描述镜间切换，不授权镜内硬切。连续运镜本身不是硬切。必须检查。
dialogue_timing：列实际台词字数、实际可用秒数及前后必要动作/停顿；区分串行和不同人物并行，不把同时动作全相加。有对白不可跳过，无对白可说明不适用。文字估算不能宣称听过语速或声线。
first_frame：比较start_state与visible_performance第一个动作、上一镜尾；首帧应是该动作发生前的静态状态。“已经开始下沉/转头/站起”仍是动作已发生，不能用“尚未完成”冒充动作前。若上镜实际已开始该动作，应按真实进度承接，不能重演。分镜必须检查；剧本可不适用。
assets：核对本镜可见人物/道具/场景与提供的资产定义、画风、服装、布局；未提供production_design时只查可见需求，映射待联合审核，不虚构缺失后续文件。剧本可不适用。文字通过不等于素材已复用成功。
需求、时序、连续性不得not_applicable。分镜timing需引visible_performance和prompt；continuity需引start_state、end_state和visible_performance；first_frame需引start_state和visible_performance（只要求实际存在的字段）。在本镜六项checks引用并集中覆盖下方全部执行路径，每个路径引用能支持核对的真实片段；可把各production_choices证据分配到相关检查，勿机械重复。reason写对照结论，不能只复述单方正面措辞。
"""
    prompt += "当前编号：" + json.dumps(ids, ensure_ascii=False)
    if joint:
        prompt += "\n本镜必须覆盖的执行证据路径：" + json.dumps(required_execution_paths(context), ensure_ascii=False)
    if context.get("review_scope") == "storyboard_segment":
        prompt += "\n当前仅审核script当前节拍和shots当前镜头；whole_story_outline/full_story_outline是背景，后续节拍尚未制作，不因本段没包含未来转折、全片结尾或总时长而报错，也不能要求提前兑现未来动作。适用当前拍的约束仍须严格检查。"
    return prompt


def validate_review_v4(value, context):
    # v3 establishes authentic leaf refs, row/check coverage and issue linkage first.
    validate_v3_review(value, context)
    if "shots" not in context:
        return
    coverage = {row["id"]: row["checks"] for row in value["coverage"]}
    required = required_execution_paths(context)
    comparisons = {"timing": ("visible_performance", "prompt"),
                   "continuity": ("start_state", "end_state", "visible_performance"),
                   "first_frame": ("start_state", "visible_performance")}
    for index, shot in enumerate(context["shots"]["shots"]):
        checks = coverage[shot["id"]]
        union = {ref["path"] for check in checks.values() for ref in check["evidence_refs"]}
        missing = set(required[shot["id"]]) - union
        if missing:
            raise CreativeContractError("v4执行字段未交叉核对: " + ", ".join(sorted(missing)))
        for check_name, fields in comparisons.items():
            expected = set()
            for field in fields:
                if field in shot:
                    expected.update(_leaf_paths(shot[field], f"shots.shots.{index}.{field}"))
            actual = {ref["path"] for ref in checks[check_name]["evidence_refs"]}
            if expected - actual:
                raise CreativeContractError(f"v4 {check_name}必须引用对照双方: " + ", ".join(sorted(expected - actual)))
