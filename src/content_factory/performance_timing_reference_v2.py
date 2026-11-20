"""State-aware spoken-text estimates for new briefs, never a quality gate."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import unicodedata

from . import content_end_pacing_v1 as pacing

VERSION = "performance_timing_reference/v2"
ACTION_RANGES = {
    "ordinary_expression_already_present": {"label": "普通神情已经成立", "min": 0, "max": 0},
    "gaze_shift_or_nod": {"label": "目光转移或点头", "min": 0.2, "max": 0.6},
    "single_table_pick_place_or_short_push": {"label": "桌面单步拿放或短推", "min": 0.5, "max": 1.2},
    "inner_pocket_take_or_simple_ticket_storage": {"label": "掏内袋取物或简单收票", "min": 0.8, "max": 1.8},
    "simple_handover": {"label": "简单递交", "min": 1, "max": 2},
    "normal_stand_up": {"label": "正常起身", "min": 1, "max": 2},
    "walk_one_to_two_metres": {"label": "短距1至2米走位", "min": 1, "max": 3,
        "note": "仅粗略参考，须依实际距离、障碍和人物状态核对。"},
}
REACTION_RANGES = {
    "already_established_state": {"label": "已经成立的神情状态", "visible_change": {"min": 0, "max": 0},
        "extra_after_dialogue": {"min": 0, "max": 0, "default": 0}},
    "key_information_understood_confirmation": {"label": "听懂关键信息后的确认", "visible_change": {"min": 0.3, "max": 0.7},
        "extra_after_dialogue": {"min": 0, "max": 0.3, "default": 0}},
    "defensive_release_guilt_or_relief": {"label": "防备松开、愧疚或释然的短暂变化", "visible_change": {"min": 0.4, "max": 1},
        "extra_after_dialogue": {"min": 0, "max": 0.4, "default": 0}},
    "important_choice_or_holding_back_tears": {"label": "重要选择或压住泪意的短暂变化", "visible_change": {"min": 0.6, "max": 1.2},
        "extra_after_dialogue": {"min": 0, "max": 0.6, "default": 0}},
}
DELIVERY_STATES = {
    "ordinary_explanation": {"label": "平静说明", "min": 3.5, "max": 4.5},
    "brisk_exchange": {"label": "利落追问或回答", "min": 4, "max": 5},
    "measured_emphasis": {"label": "认真强调或克制承认", "min": 3, "max": 4},
    "smiling_or_teary_fluent": {"label": "带笑或眼中有泪但说话仍连贯", "min": 3, "max": 4},
    "audible_choking": {"label": "声音明确哽咽或断句", "min": 2.5, "max": 3.5},
}
RULES = {
    "scope": "这些数值只是项目创作排时初值，不是录音实测、行业硬标准、已证实的成片规律或内容分类器。不要求动作、情绪演满区间，不按字数或估算秒数判内容通过。",
    "state_change_and_extra": "情绪状态可贯穿对白；短暂可见变化与对白之后的额外停留分开判断。变化尽量在刺激到达后的对白或下一句回应中显现，已经成立的状态不另加时间，台词后默认额外停留为0。",
    "no_double_count": "可见变化与extra_after_dialogue不是两个必加时间窗，不能重复计算同一次反应。已在对白中完成的变化不能在对白后重新演一次；只有真实尚未完成且有具体作用的部分才计额外时间，重要反应也不能全部设为0。",
    "exception": "特定重大表演可以超出参考区间，但应说明具体刺激、表达作用及镜头可读性，不以程序硬拒。情绪标签本身不产生固定秒数；低声、愧疚、怒气不自动放慢，眼里有泪不等于声音哽咽。只有明确可听到的哽咽断句才选audible_choking。",
    "spoken_units": "先把数字、日期、英文缩写、金额、单位及特殊符号转写为本句实际要说的汉字读法，再按声明读法的汉字数量估算。逐字数量只是发音量代理，不证明真实音节或录音时长；儿化、轻声等须按实际读法调整。辅助函数不猜未展开英数的读法；有未确认部分时仅给已知汉字的部分估算，不冒充完整对白时长。",
    "pause": "逗号、句号等标点不自动增加停顿；pause_seconds仅包含明确声明且尚未在声音窗口中计算的真实停连，不与同一停顿重复相加。秒/发音单位为每秒发音单位范围的倒数：最短=单位数/最快语速+明确停顿，最长=单位数/最慢语速+明确停顿。",
    "per_utterance_review": "编剧和自然导演按每句实际说法、说话状态、声明读法的发音量、预计声音时长、明确停连、接话间隙及同窗动作和反应逐句核对。DeepSeek在全文及最终实际提示词审核中逐句区分声音时长与整个互动窗，未知读法如实列出；若容量异常，指出具体句子、影响及编剧、导演、整理或编译责任层。沿原输出合同用自然文字说明，不要求新增JSON、工具或固定标题，不按字数单独自动给pass或revise。",
    "parallel_and_dependencies": "同一并行组按max(对白时间, 可并行动作或反应时间)估算；组内先计算真实先后依赖，再比较可并行分支的最长耗时。不同组只按真实依赖顺序累加，不把取物、递交和听者反应无因地全部串行，也不把必须依次完成的动作强当并行。",
    "content_end": "段末状态不是额外hold窗口。最后必要对白、动作和关键反应完成即收段，普通尾部补时为0；不补发呆、慢动作或重复动作凑参考总长，压缩不靠催词、瞬移或全稿比例缩秒。",
    "service_and_bounds": "保留冻结brief的显式最短、最长及target+tolerance硬范围；服务仍按4至15秒整数最短可行档，内容不足最低档应并入邻段或重新分段，不空填。审核员、估算函数和SDK编译器不自动改正文或导演原定秒数。",
    "actual_prompt_and_authority": "估算的小数秒只留内部分析，实际Seedance Mini提示词按动作、对白、反应顺序与并行关系表达，不强压小数时点。MiniMax与DeepSeek五阶段读取同一完整profile；旧运行不补写、不迁移，不新增模型、媒体、重试、续段或发布权限，视频仍由用户人工审核。",
}


def _seconds_per_unit(rate):
    return {"min": 1 / rate["max"], "max": 1 / rate["min"]}


def profile():
    states = {key: {"label": value["label"], "units_per_second": {"min": value["min"], "max": value["max"]},
        "seconds_per_unit": _seconds_per_unit(value)} for key, value in DELIVERY_STATES.items()}
    content = dict(version=VERSION, basis="project_creative_estimates_not_industry_standard_or_recorded_measurements",
        count_basis="declared_hanzi_reading_proxy_not_audio_measurement",
        content_classifier=False, hard_duration_gate=False, action_reference_seconds=deepcopy(ACTION_RANGES),
        reaction_reference_seconds=deepcopy(REACTION_RANGES), dialogue_delivery_states=states,
        ordinary_tail_padding_seconds=0, requirements=deepcopy(RULES))
    digest = hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    return {**content, "sha256": digest}


def _is_hanzi(char):
    point = ord(char)
    return (0x3400 <= point <= 0x4DBF or 0x4E00 <= point <= 0x9FFF
        or 0xF900 <= point <= 0xFAFF or 0x20000 <= point <= 0x2FA1F
        or 0x30000 <= point <= 0x3347F or char == "〇")


def estimate_dialogue(spoken_text, delivery_state, pause_seconds=0):
    """Estimate explicitly transcribed speech only; never change or approve text."""
    if not isinstance(spoken_text, str):
        raise ValueError("spoken_text须为实际发音文字")
    if not isinstance(delivery_state, str) or delivery_state not in DELIVERY_STATES:
        raise ValueError("请选择明确的delivery_state；不能按愧疚、低声或怒气自动分类")
    if (type(pause_seconds) not in (int, float) or not math.isfinite(pause_seconds) or pause_seconds < 0):
        raise ValueError("pause_seconds须为非负有限数值，不接受bool或未声明停顿")
    units = sum(_is_hanzi(char) for char in spoken_text)
    unknown = sorted({char for char in spoken_text if not _is_hanzi(char)
        and (unicodedata.category(char)[0] in {"L", "N", "S"} or char in "%‰‱/@#&^_")})
    rate = DELIVERY_STATES[delivery_state]
    seconds = {"min": units / rate["max"] + pause_seconds,
               "max": units / rate["min"] + pause_seconds}
    complete = not unknown
    return dict(schema="dialogue_estimate/v2", profile_version=VERSION, profile_sha256=profile()["sha256"],
        count_basis="declared_hanzi_reading_proxy_not_audio_measurement",
        spoken_text=spoken_text, delivery_state=delivery_state, units=units,
        units_per_second={"min": rate["min"], "max": rate["max"]}, seconds_per_unit=_seconds_per_unit(rate),
        pause_seconds=pause_seconds, min_seconds=seconds["min"] if complete else None,
        max_seconds=seconds["max"] if complete else None,
        partial_hanzi_seconds=seconds if not complete else None,
        estimation_complete=complete, requires_reading_confirmation=not complete,
        unexpanded_characters=unknown, quality_gate=False, changes_text_or_duration=False)


def apply_brief(brief):
    result = pacing.apply_brief(brief)
    expected = profile()
    if "performance_timing_reference" in result and result["performance_timing_reference"] != expected:
        raise ValueError("已有performance_timing_reference不是本v2，不能覆盖或迁移旧规范")
    result["performance_timing_reference"] = expected
    return result


def _runtime():
    return pacing._runtime()


def prepare_source(source_run_dir, *, brief=None, runtime=None, **kwargs):
    path = Path(source_run_dir).resolve() / "BINDING.json"
    if path.exists():
        frozen_brief = pacing._read_binding(path).get("brief")
        if (not isinstance(frozen_brief, dict) or frozen_brief.get("content_end_pacing") != pacing.policy()
                or frozen_brief.get("performance_timing_reference") != profile()):
            raise ValueError("已有运行未冻结完全匹配的content_end和performance v2，请使用原恢复入口；不能补写旧稿")
        if brief is None:
            brief = frozen_brief
    return pacing.prepare_source(source_run_dir, brief=apply_brief(brief),
        runtime=runtime if runtime is not None else _runtime(), **kwargs)
