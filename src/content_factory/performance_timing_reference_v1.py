"""Project performance estimates for new briefs; no classifier or dispatch."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from . import content_end_pacing_v1 as pacing

VERSION = "performance_timing_reference/v1"
ACTION_RANGES = {
    "ordinary_expression_already_present": {"label": "普通神情已经成立", "min": 0, "max": 0, "note": "额外展开时间为0，开镜直接展示当前状态。"},
    "gaze_shift_or_nod": {"label": "目光转移或点头", "min": 0.2, "max": 0.6},
    "single_table_pick_place_or_short_push": {"label": "桌面单步拿放或短推", "min": 0.5, "max": 1.2},
    "inner_pocket_take_or_simple_ticket_storage": {"label": "掏内袋取物或简单收票", "min": 0.8, "max": 1.8},
    "simple_handover": {"label": "简单递交", "min": 1, "max": 2},
    "normal_stand_up": {"label": "正常起身", "min": 1, "max": 2},
    "walk_one_to_two_metres": {"label": "短距1至2米走位", "min": 1, "max": 3, "note": "仅粗略参考，须依实际距离、障碍、姿势和人物状态调整，不准瞬移。"},
}
REACTION_RANGES = {
    "mild_question_or_surprise_onset": {"label": "轻微疑问或意外初显", "min": 0.3, "max": 0.8},
    "key_information_understood_confirmation": {"label": "听懂关键信息后的确认", "min": 0.8, "max": 1.5},
    "key_change_defensive_to_relieved": {"label": "防备到释然等关键变化", "min": 1, "max": 2.5},
    "holding_back_tears_or_important_choice": {"label": "压住泪意或重要选择", "min": 1.5, "max": 3},
}
RULES = {
    "scope": "以上是项目创作排时的粗略估算起点，不是行业统一硬标准、已证实的成片规律或内容分类器。按具体动作、刺激、变化和镜头可读性选择参考，不要求演满区间，不按区间或字数自动判定内容通过。",
    "parallel_group": "同一并行组的估时取max(对白时间, 可并行动作或反应时间)，不把能够同时发生的动作、视线、说话和听者反应逐项相加。若组内有真实先后依赖，先按依赖计算各连续分支，再取可并行分支的最长时间。",
    "sequential_groups": "不同组只有存在真实先后依赖才顺序累加；例如必须先拿到物品才能收入口袋。用取物、递交、听见后的具体反应明确依赖，不能一律视为并行，也不能无因地串行拉长。",
    "reaction_purpose": "重要反应只按具体作用选择：说明新信息造成什么理解、判断或关系变化；可以在对白和推物过程中显现，不必等说完后再演一遍。不要把重要反应全部设为0，也不要套用固定表情停留。",
    "end_state": "段末状态只是有效动作完成时的状态，不是另加一个hold窗口。最后必要对白、动作和关键反应完成即收段，普通尾部补时为0，不用发呆、凝视、慢动作或重复动作凑总长。",
    "dialogue": "普通对白参考每秒3至4个实际发音汉字，重点情绪对白参考每秒2.5至3.5个；数字、日期和缩写按实际读法估算，标点不当作发音汉字。仅辅助自然试读，字数不是质量门，不能为满足估值催念台词。",
    "service_and_bounds": "保留冻结brief全部显式硬范围和原服务能力门。4至15秒整数服务段选择能容纳必要内容的最短可行档，内容不足最低档则并入邻段或重分段，不能空填；参考总长不能诱导补动作。编译器和审核员不自动改导演原定秒数。",
    "actual_prompt": "小数秒区间和内部并行估时只用于创作分析；Seedance Mini实际提示词按动作、对白、反应的发生顺序以及并行关系表达，不强压小数秒时点，不直接把估时表当作视频内容。",
    "authority_and_preservation": "MiniMax创作与DeepSeek同源全文及全部实际请求复审读取同一完整profile；参考表不取代内容审核。旧运行不补写、不迁移，不改变预算、计数、未知结果停点、媒体人工审核或发布授权，本规范不发起任何服务调用。",
}


def profile():
    content = dict(version=VERSION,
        basis="project_creative_estimates_not_industry_standard",
        content_classifier=False, hard_duration_gate=False,
        action_reference_seconds=deepcopy(ACTION_RANGES),
        reaction_reference_seconds=deepcopy(REACTION_RANGES),
        dialogue_reference_phonated_hanzi_per_second={
            "ordinary": {"min": 3, "max": 4}, "key_emotional": {"min": 2.5, "max": 3.5}},
        ordinary_tail_padding_seconds=0, requirements=deepcopy(RULES))
    digest = hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    return {**content, "sha256": digest}


def apply_brief(brief):
    result = pacing.apply_brief(brief)
    expected = profile()
    if "performance_timing_reference" in result and result["performance_timing_reference"] != expected:
        raise ValueError("已有performance_timing_reference不同，不能覆盖或迁移旧规范")
    result["performance_timing_reference"] = expected
    return result


def _runtime():
    return pacing._runtime()


def prepare_source(source_run_dir, *, brief=None, runtime=None, **kwargs):
    path = Path(source_run_dir).resolve() / "BINDING.json"
    if path.exists():
        frozen_brief = pacing._read_binding(path).get("brief")
        if (not isinstance(frozen_brief, dict)
                or frozen_brief.get("content_end_pacing") != pacing.policy()
                or frozen_brief.get("performance_timing_reference") != profile()):
            raise ValueError("已有运行未冻结两个完全匹配的新规范，请使用原恢复入口；不能补写旧稿")
        if brief is None:
            brief = frozen_brief
    return pacing.prepare_source(source_run_dir, brief=apply_brief(brief),
        runtime=runtime if runtime is not None else _runtime(), **kwargs)
