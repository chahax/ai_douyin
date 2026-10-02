# -*- coding: utf-8 -*-
"""
src/content_factory/novel_splitter.py — V5-1 L1 LLM 拆镜

设计依据:
  - docs/design/v5-pure-video-pipeline.md §3 (L1 拆镜)
  - ship.md 附录 A.4.1 (L0 schema 校验) + A.4.2 (L1 业务校验) + A.5.2 (retry 参数变体)
  - 复用 I-4 (chat_completion_tracked) + I-3 (Pydantic schema 校验)
  - 复用 I-2 (容错模式：失败重试 + 异常分类)

流程:
  1. LLM 调用 (用 I-4 chat_completion_tracked, 自动记录 token/cost/cache)
  2. JSON 解析 + Pydantic schema 校验 (L0 失败 → ValidationError, 不重试)
  3. 业务规则校验 (段间连贯性、角色白名单 - L1 失败 → 触发 retry 变体)
  4. retry 3 次 (A.5.2): 默认 prompt → 加示例 prompt → 切备选模型 prompt

输入:
  - novel_text: str
  - novel_title: Optional[str]
  - style: str (默认 "dream_shaper_xl")

输出:
  - NovelSplit Pydantic model (含 novel_title, characters, scenes, total_duration_seconds)
  - 异常: 3 次 retry 全失败 → 抛 NovelSplitUnavailableError
"""

from __future__ import annotations

import json
import hashlib
import math
import re
import time
from dataclasses import asdict, is_dataclass
from typing import Any, Optional

from pydantic import ValidationError

from src.content_factory.novel_schemas import (
    MAX_SEGMENTS_MAX,
    MAX_SEGMENTS_MIN,
    SCENE_DURATION_MAX,
    NovelSplit,
    calc_max_segments,
)
from src.shared.llm_client import llm_client
from src.shared.logger import logger


# -------------------------------------------------------------------
# 异常类（I-2 风格的纯增量模块）
# -------------------------------------------------------------------


class NovelSplitError(Exception):
    """novel_splitter 异常的基类。"""
    error_class: str = "UNKNOWN"

    def __init__(self, message: str, *, attempts: int = 0, last_error: str = ""):
        super().__init__(message)
        self.attempts = attempts
        self.last_error = last_error


class NovelSplitUnavailableError(NovelSplitError):
    """3 次 retry 全失败后抛出。"""
    error_class = "UNAVAILABLE"


class NovelSplitSchemaError(NovelSplitError):
    """L0 schema 错误 (Pydantic 校验失败) — 不重试。"""
    error_class = "SCHEMA"


class NovelSplitBusinessError(NovelSplitError):
    """L1 业务规则违反 (角色不在白名单等) — 触发 retry。"""
    error_class = "BUSINESS"


# -------------------------------------------------------------------
# Prompt 模板 + 变体
# -------------------------------------------------------------------


# 变体 1: 默认 prompt
PROMPT_V1 = """你是一位专业的短视频分镜师。请将以下小说片段拆成 {max_segments} 个 3-5 秒的镜头。

## 小说标题
{title}

## 小说片段
{text}

## 输出要求（严格 JSON 格式）
{{
  "novel_title": "提取或推断的标题",
  "characters": ["角色1", "角色2"],
  "scenes": [
    {{
      "scene_id": 0,
      "narration": "这段场景的旁白文本（30-200 字）",
      "dialogue": [
        {{"speaker": "角色名", "text": "对白（5-100 字）", "emotion": "neutral"}}
      ],
      "first_frame_prompt": "DreamShaper XL 风格的英文 prompt，描述场景开始画面（20-200 字符）",
      "last_frame_prompt": "DreamShaper XL 风格的英文 prompt，描述场景结束画面（20-200 字符）",
      "duration_seconds": 4.0
    }}
  ]
}}

## 硬约束
- duration_seconds 必须在 3.0-5.0 之间
- dialogue 角色必须在 characters 列表中
- first_frame_prompt / last_frame_prompt 必须呼应（同一个场景的视觉延续）
- 输出只能有 JSON，不能有 markdown 代码块或其他说明
"""


# 变体 2: 加 1 个示例 + "避免常见错误" 提示
PROMPT_V2 = PROMPT_V1 + """

## 示例
{{
  "novel_title": "林晚的早晨",
  "characters": ["林晚", "陈默"],
  "scenes": [
    {{
      "scene_id": 0,
      "narration": "清晨的阳光透过窗帘，林晚站在窗前，深吸一口气。",
      "dialogue": [],
      "first_frame_prompt": "anime girl Lin Wan standing by a sunlit window, morning light, soft focus, DreamShaper XL",
      "last_frame_prompt": "anime girl Lin Wan turning towards camera, sun rays through curtain, close-up, DreamShaper XL",
      "duration_seconds": 4.0
    }}
  ]
}}

## 避免错误
- 不要把对话塞进 narration（对话走 dialogue 列表）
- duration 不要用 0 / 1 / 10 这种极端值
- character 名不要带空格或特殊符号
"""


# 变体 3: 切备选模型 + 简化 prompt
PROMPT_V3 = """将小说片段拆为 {max_segments} 个 3-5 秒分镜。

小说: {text}

输出 JSON:
{{
  "novel_title": "...",
  "characters": [...],
  "scenes": [
    {{
      "scene_id": 0,
      "narration": "...",
      "dialogue": [{{"speaker": "...", "text": "...", "emotion": "neutral"}}],
      "first_frame_prompt": "...",
      "last_frame_prompt": "...",
      "duration_seconds": 4.0
    }}
  ]
}}

约束: duration 3.0-5.0; characters 必填; first/last prompt 20-200 字符; 仅 JSON 输出。
"""


PROMPT_V4 = PROMPT_V1 + """

## 原文事实不足时的处理
- 可以把同一个有依据的瞬间拆成全景、人物特写、对白前停顿、对白发生、听者反应和余波，但不能新增事件。
- narration 必须是原文摘录或最小幅度的忠实转述，不能用常识补全。
- 画面中未知的地点、服饰、颜色、对手和动作保持未知，不要替它们取具体值。
- 每条首末帧 prompt 必须为 20-200 个字符；用 camera shot、framing、lighting 补足长度，不能用新剧情补足。
- 关键保护性对白的 emotion 使用 protective 或 determined；发现真相的反应可用 stunned。
"""


PROMPT_V5 = PROMPT_V4 + """

## 最终纠偏
- 先在心中为每个剧情名词和动作找到小说片段中的逐字证据；找不到就删掉。
- 允许重复同一受支持的事件来表现停顿与表情，不允许为避免重复而编出新动作。
- 输出前检查镜头数、每镜时长、提示词长度、对白逐字一致和总时长。
"""


PROMPT_VARIANTS = [PROMPT_V1, PROMPT_V2, PROMPT_V3, PROMPT_V4, PROMPT_V5]


# -------------------------------------------------------------------
# 主入口
# -------------------------------------------------------------------


def split_novel(
    novel_text: str,
    novel_title: Optional[str] = "",
    style: str = "dream_shaper_xl",
    caller: str = "v5_novel_split",
    use_cache: bool = True,
    *,
    highlight_report: Any | None = None,
    target_duration_seconds: float | None = None,
) -> NovelSplit:
    """
    L1 拆镜主入口。

    Args:
        novel_text: 小说文本（>= 100 字）
        novel_title: 可选标题（空则让 LLM 抽取）
        style: 视觉风格（DreamShaper XL / AnythingXL / RealVisXL）
        caller: I-4 caller tag（用于 LLM 限流豁免判断 + 计量统计）
        use_cache: I-4 缓存开关
        highlight_report: novel_highlight_analysis/v1 报告；提供后只拆选中高光
        target_duration_seconds: 可覆盖报告建议时长，范围 30-300 秒

    Returns:
        NovelSplit Pydantic model

    Raises:
        NovelSplitSchemaError: L0 schema 失败（不重试，code bug）
        NovelSplitBusinessError: L1 业务失败（被 retry 内部吸收）
        NovelSplitUnavailableError: 3 次 retry 全失败
    """
    if not novel_text or len(novel_text.strip()) < 50:
        raise NovelSplitError(f"novel_text 太短: {len(novel_text)} chars (min 50)")

    source_text = novel_text.strip()
    require_source_grounding = highlight_report is not None
    highlight_direction = ""
    if highlight_report is not None:
        source_text, report_duration, highlight_direction = _bind_highlight_report(
            source_text,
            highlight_report,
        )
        if target_duration_seconds is None:
            target_duration_seconds = report_duration

    if target_duration_seconds is not None:
        target_duration_seconds = float(target_duration_seconds)
        if not 30 <= target_duration_seconds <= 300:
            raise NovelSplitError("target_duration_seconds 必须在 30-300 秒之间")
        max_segments = max(
            MAX_SEGMENTS_MIN,
            min(MAX_SEGMENTS_MAX, round(target_duration_seconds / 4.5)),
        )
        average_duration = target_duration_seconds / max_segments
        if average_duration > SCENE_DURATION_MAX:
            raise NovelSplitError(
                "目标时长超过当前分镜上限可承载范围，请提高 MAX_SEGMENTS_MAX"
            )
        highlight_direction += (
            f"\n- 成片目标总时长为 {target_duration_seconds:g} 秒，输出恰好 {max_segments} 镜，"
            f"平均每镜约 {average_duration:.2f} 秒。\n"
            "- 前两镜必须从情绪峰值中选取一个刺激和一个可见反应作高光预示，"
            "但不能提前播放最终回答；随后回到事件开端按因果推进。\n"
            "- 角色长对白必须按原文标点拆到连续镜头，每个片段仍须是原文中的逐字连续子串；"
            "按中文每秒约 4 个有效字并计入停顿，任何一镜的对白都不能超过镜头时长。\n"
            "- emotion 必须按该句的实际表演意图填写；冲突与峰值对白不能全部使用 neutral，"
            "并在关键刺激、发生当下和双方反应中体现 tense/angry/tender/conflicted/stunned 等变化。\n"
        )
    else:
        max_segments = calc_max_segments(len(source_text))
    title_for_prompt = novel_title or "(无标题，请根据内容推断)"

    last_error_msg = ""

    for attempt_idx, prompt_template in enumerate(PROMPT_VARIANTS, start=1):
        prompt = prompt_template.format(
            max_segments=max_segments,
            title=title_for_prompt,
            text=source_text,
        )
        if highlight_direction:
            prompt += highlight_direction
        if last_error_msg:
            prompt += (
                "\n## 上次结果被控制流拒绝\n"
                f"- {last_error_msg}\n"
                "- 修正这些问题后重新输出完整 JSON。\n"
            )

        messages = [
            {"role": "system", "content": "你只输出严格 JSON，不输出任何其他文字。"},
            {"role": "user", "content": prompt},
        ]

        logger.info(
            f"[v5 split] attempt {attempt_idx}/{len(PROMPT_VARIANTS)}, max_segments={max_segments}, "
            f"text_len={len(source_text)}, style={style}"
        )

        # 调 LLM（I-4 治理: 限流 + 缓存 + 计量 + 记录）
        raw = llm_client.chat_completion_tracked(
            messages,
            caller=caller,
            temperature=0.2 if require_source_grounding else 0.7,
            json_mode=True,
            use_cache=use_cache,
        )

        if not raw:
            last_error_msg = f"LLM 返回空 (attempt {attempt_idx})"
            logger.warning(f"[v5 split] {last_error_msg}")
            continue  # 进入下一个变体

        # JSON 解析
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            last_error_msg = f"JSON parse failed: {exc}"
            logger.warning(f"[v5 split] {last_error_msg}")
            continue  # 可能是 LLM 飘了, retry 变体

        # 强制 title
        if not data.get("novel_title") and novel_title:
            data["novel_title"] = novel_title

        # L0 schema 校验（一次性，不重试）
        try:
            result = NovelSplit.model_validate(data)
            if target_duration_seconds is not None:
                if abs(len(result.scenes) - max_segments) > 1:
                    last_error_msg = (
                        "镜头数偏离目标超过1镜: "
                        f"actual={len(result.scenes)}, target={max_segments}"
                    )
                    logger.warning(f"[v5 split] L1 业务失败: {last_error_msg}")
                    continue
                duration_repairs = _fit_dialogue_durations(result)
                if duration_repairs:
                    logger.info(
                        "[v5 split] 已按对白语速延长 {} 个镜头并重新计算总时长",
                        len(duration_repairs),
                    )
                tolerance = max(5.0, target_duration_seconds * 0.12)
                if abs(result.total_duration_seconds - target_duration_seconds) > tolerance:
                    last_error_msg = (
                        "总时长偏离高光目标: "
                        f"actual={result.total_duration_seconds:g}s, "
                        f"target={target_duration_seconds:g}s"
                    )
                    logger.warning(f"[v5 split] L1 业务失败: {last_error_msg}")
                    continue
            if require_source_grounding:
                dialogue_repairs = _restore_unique_source_dialogue(
                    result, source_text
                )
                if dialogue_repairs:
                    logger.info(
                        "[v5 split] 已把 {} 条仅标点不同的对白恢复为原文逐字文本",
                        len(dialogue_repairs),
                    )
                dialogue_errors = _find_unanchored_dialogue(result, source_text)
                if dialogue_errors:
                    last_error_msg = "；".join(dialogue_errors[:5])
                    logger.warning(
                        f"[v5 split] 原文对白校验失败: {last_error_msg}"
                    )
                    continue
                timing_errors = _find_dialogue_timing_errors(result)
                if timing_errors:
                    last_error_msg = "；".join(timing_errors[:5])
                    logger.warning(
                        f"[v5 split] 对白时长校验失败: {last_error_msg}"
                    )
                    continue
                emotion_errors = _find_dialogue_emotion_errors(result)
                if emotion_errors:
                    last_error_msg = "；".join(emotion_errors[:5])
                    logger.warning(
                        f"[v5 split] 情绪标签校验失败: {last_error_msg}"
                    )
                    continue
                grounding_errors = _audit_storyboard_grounding(
                    result,
                    source_text,
                    caller=caller,
                    use_cache=use_cache,
                )
                if grounding_errors:
                    last_error_msg = "；".join(grounding_errors[:5])
                    logger.warning(
                        f"[v5 split] 原文事实校验失败: {last_error_msg}"
                    )
                    continue
            logger.info(
                f"[v5 split] success: {len(result.scenes)} scenes, "
                f"{result.total_duration_seconds}s total, "
                f"{len(result.characters)} chars"
            )
            return result
        except ValidationError as exc:
            # Pydantic ValidationError 包含字段错 (e.g. duration_seconds=10 超出范围)
            # 这种通常是 prompt 飘了导致 LLM 输出格式错 (retry prompt 变体可能修复)
            last_error_msg = f"schema validation: {exc.errors()[0]['msg']}"
            logger.warning(f"[v5 split] L0 schema 失败: {last_error_msg}")
            continue

        # 不可达这里
    # 全部 retry 失败
    raise NovelSplitUnavailableError(
        f"{len(PROMPT_VARIANTS)} 次 retry 全失败: {last_error_msg}",
        attempts=len(PROMPT_VARIANTS),
        last_error=last_error_msg,
    )


def _bind_highlight_report(
    novel_text: str,
    report: Any,
) -> tuple[str, float, str]:
    """Bind a highlight report to the exact novel source and selected span."""
    if is_dataclass(report):
        payload = asdict(report)
    elif isinstance(report, dict):
        payload = report
    elif hasattr(report, "to_dict"):
        payload = report.to_dict()
    else:
        raise NovelSplitError("highlight_report 必须是字典或高光报告对象")
    if payload.get("schema") != "novel_highlight_analysis/v1":
        raise NovelSplitError("highlight_report schema 无效")
    source_sha = hashlib.sha256(novel_text.encode("utf-8")).hexdigest().upper()
    if str(payload.get("source_sha256") or "").upper() != source_sha:
        raise NovelSplitError("高光报告与当前小说原文哈希不一致")
    selected = payload.get("selected_highlight")
    if not isinstance(selected, dict):
        raise NovelSplitError("高光报告缺少 selected_highlight")
    try:
        start = int(selected["source_start_char"])
        end = int(selected["source_end_char"])
        duration = float(selected["recommended_duration_seconds"])
    except (KeyError, TypeError, ValueError) as exc:
        raise NovelSplitError("高光报告位置或推荐时长无效") from exc
    if not 0 <= start < end <= len(novel_text):
        raise NovelSplitError("高光报告的原文位置越界")
    segment = novel_text[start:end]
    start_quote = str(selected.get("source_start_quote") or "")
    end_quote = str(selected.get("source_end_quote") or "")
    if not start_quote or not segment.startswith(start_quote):
        raise NovelSplitError("高光起始引文与小说原文不一致")
    if not end_quote or not segment.endswith(end_quote):
        raise NovelSplitError("高光结束引文与小说原文不一致")
    stages = selected.get("amplification_plan") or []
    driver_mode = str(payload.get("driver_mode") or "novel_highlight")
    stage_text = "；".join(
        f"{item.get('stage')}约{item.get('duration_seconds')}秒：{item.get('focus')}"
        for item in stages
        if isinstance(item, dict)
    )
    direction = f"""

## 已绑定的高光导演约束
- 当前驱动模式：{driver_mode}。
- 只能使用上方选中原文区间中的剧情事实，不得补入参考视频或小说其他区间的情节。
- 原文没有说明的地点、对手身份、冲突类型、车辆、服饰、结果和人物动作都必须保持未说明；不得为了画面具体而自行补全。
- 遇到“麻烦”“危险”“有人”等泛称时，用人物特写、虚焦遮挡或未知阻力表达，不能擅自改成混混、债主、绑架、车祸等具体事件。
- 所有人物对白必须逐字出现在选中原文中；不能把旁白或他人的话改成角色对白。
- 运镜、景别、光线和原文情绪直接支持的微表情可以设计，但不能借此增加剧情事实。
- 完整保留必要前因、冲突升级、情绪峰值和峰值余波。
- 情绪峰值必须拆成至少三个相邻镜头：关键刺激/对白之前、发生当下、说完或做完后的双方反应。
- 旁白只负责无法画出的必要信息，人物动作和对白承担主要推进。
- 高光标题：{selected.get('title') or '未命名'}
- 冲突：{selected.get('conflict') or '以原文为准'}
- 转折：{selected.get('turning_point') or '以原文为准'}
- 峰值：{selected.get('emotional_peak') or '以原文为准'}
- 余波：{selected.get('aftershock') or '以原文为准'}
- 节奏分配：{stage_text or '按前因、升级、峰值、余波、悬念分配'}
"""
    return segment, duration, direction


def _find_unanchored_dialogue(result: NovelSplit, source_text: str) -> list[str]:
    """Reject generated dialogue that cannot be located verbatim in the source."""
    errors: list[str] = []
    compact_source = "".join(source_text.split())
    for scene in result.scenes:
        for line in scene.dialogue:
            compact_line = "".join(line.text.strip().split())
            if compact_line and compact_line not in compact_source:
                errors.append(
                    f"scene {scene.scene_id} 对白不在原文：{line.text}"
                )
    return errors


def _estimate_dialogue_seconds(value: str) -> float:
    """Estimate an expressive Chinese line at roughly four units per second."""
    units = sum(char.isalnum() for char in value)
    comma_pauses = len(re.findall(r"[，、,；;：:]", value)) * 0.12
    sentence_pauses = len(re.findall(r"[。！？!?]", value)) * 0.22
    ellipsis_pauses = len(re.findall(r"……|\.\.\.", value)) * 0.35
    expressive_pauses = len(re.findall(r"[~～]", value)) * 0.12
    return units / 4.0 + comma_pauses + sentence_pauses + ellipsis_pauses + expressive_pauses


def _find_dialogue_timing_errors(result: NovelSplit) -> list[str]:
    errors: list[str] = []
    for scene in result.scenes:
        seconds = sum(_estimate_dialogue_seconds(line.text) for line in scene.dialogue)
        if seconds > scene.duration_seconds + 0.25:
            errors.append(
                f"scene {scene.scene_id} 对白约需{seconds:.1f}秒，镜头只有{scene.duration_seconds:g}秒"
            )
    return errors


def _fit_dialogue_durations(result: NovelSplit) -> list[dict[str, float | int]]:
    """Extend a slightly short shot when its line still fits the 5s hard cap."""
    repairs: list[dict[str, float | int]] = []
    for scene in result.scenes:
        seconds = sum(_estimate_dialogue_seconds(line.text) for line in scene.dialogue)
        if seconds <= scene.duration_seconds + 0.25 or seconds > 5.0:
            continue
        revised = min(5.0, math.ceil(seconds * 2.0) / 2.0)
        before = scene.duration_seconds
        scene.duration_seconds = revised
        repairs.append(
            {
                "scene_id": scene.scene_id,
                "before_seconds": before,
                "after_seconds": revised,
            }
        )
    if repairs:
        object.__setattr__(
            result,
            "total_duration_seconds",
            sum(scene.duration_seconds for scene in result.scenes),
        )
    return repairs


def _find_dialogue_emotion_errors(result: NovelSplit) -> list[str]:
    lines = [line for scene in result.scenes for line in scene.dialogue]
    if len(lines) < 4:
        return []
    expressive = sum(line.emotion != "neutral" for line in lines)
    required = max(2, math.ceil(len(lines) * 0.35))
    if expressive < required:
        return [
            f"对白情绪标签过平：{len(lines)}句仅{expressive}句非neutral，至少需要{required}句"
        ]
    tail_start = max(0, math.floor(len(result.scenes) * 0.6))
    tail_emotions = {
        line.emotion
        for scene in result.scenes[tail_start:]
        for line in scene.dialogue
        if line.emotion != "neutral"
    }
    if not tail_emotions.intersection({"tender", "surprised", "conflicted", "stunned", "tense"}):
        return ["情绪峰值与余波没有可表演的非neutral情绪标签"]
    return []


def _dialogue_skeleton(value: str) -> str:
    """Keep only letters and numbers for conservative punctuation repair."""
    return "".join(char for char in value if char.isalnum())


def _source_dialogue_candidates(source_text: str) -> list[str]:
    """Return explicitly quoted utterances from the selected source span."""
    patterns = (
        r"“([^”\n]{1,200})”",
        r"‘([^’\n]{1,200})’",
        r"「([^」\n]{1,200})」",
        r'"([^"\n]{1,200})"',
    )
    candidates: list[str] = []
    for pattern in patterns:
        candidates.extend(match.strip() for match in re.findall(pattern, source_text))
    return list(dict.fromkeys(item for item in candidates if item))


def _restore_unique_source_dialogue(
    result: NovelSplit, source_text: str
) -> list[dict[str, str | int]]:
    """Restore punctuation only when one quoted source line is an exact match.

    Models sometimes turn an ellipsis into exclamation marks even after being
    told to quote verbatim.  The candidate must have the same letters/numbers
    and must be unique among explicit source quotations.  Wording changes,
    combined lines, and ambiguous matches remain hard failures.
    """
    compact_source = "".join(source_text.split())
    by_skeleton: dict[str, list[str]] = {}
    for candidate in _source_dialogue_candidates(source_text):
        skeleton = _dialogue_skeleton(candidate)
        if skeleton:
            by_skeleton.setdefault(skeleton, []).append(candidate)

    repairs: list[dict[str, str | int]] = []
    for scene in result.scenes:
        for line in scene.dialogue:
            original = line.text.strip()
            if not original or "".join(original.split()) in compact_source:
                continue
            candidates = list(dict.fromkeys(by_skeleton.get(_dialogue_skeleton(original), [])))
            if len(candidates) != 1:
                continue
            replacement = candidates[0]
            line.text = replacement
            repairs.append(
                {
                    "scene_id": scene.scene_id,
                    "before": original,
                    "after": replacement,
                }
            )
    return repairs


def _audit_storyboard_grounding(
    result: NovelSplit,
    source_text: str,
    *,
    caller: str,
    use_cache: bool,
) -> list[str]:
    """Use a second, low-temperature pass to reject unsupported story facts."""
    payload = result.model_dump(mode="json")
    prompt = f"""你是小说分镜的原文事实审计员。逐镜把旁白、对白、首帧和尾帧拆成原子事实，再为每个原子事实寻找原文中的逐字依据。没有逐字依据就判定为 unsupported，不得用常识或剧情合理性放行。

## 原文
{source_text}

## 待审分镜
{json.dumps(payload, ensure_ascii=False)}

## 审计边界
- 地点、对手身份、冲突类型、车辆、服饰、关系、动作结果和对白必须得到原文直接支持。
- 原文中的泛称必须保持泛化。例如“遇到麻烦”不能变成“被混混围堵”。
- 允许摄影层面的景别、运镜、光线、构图，以及原文情绪直接支持的细微表情。
- close-up、wide shot、static camera、controlled lighting、soft focus、fade to black 等纯摄影或剪辑词不是剧情事实，审计时必须忽略；只核对画面中的人物、物件、地点、服饰、颜色、关系、动作与结果。
- 将原文已经写明的人物拍进画面本身不是新增事实；只有给人物增加原文没有的行为、外貌属性或所处地点才算新增。
- emotion 标签可以由同一句对白的直接语义支持，例如“别怕，我罩着你”支持 protective；不得要求原文逐字出现英文情绪标签。
- 人物身份不能反推服饰和地点；“校花学姐”不能推出“穿校服”或“在校园/校门口”。
- “带着一面包车的保镖出现”只能支持人物、面包车、保镖和出现，不能推出车辆颜色、急刹、谁从车里下来、保镖穿黑西装或列队。
- “遇到麻烦”不能推出围观者、对手、独自求助、寻找出路、势单力薄或麻烦的解决结果。
- 原文只说眼前的发现时，不能推出“人生从此改变”等未来结果。
- 不审美，只审原文事实。发现一项就列出对应 scene_id 和简短原因。

只输出严格 JSON：
{{"checked_scene_count":{len(result.scenes)},"unsupported":[{{"scene_id":0,"reason":"增加了原文没有的具体事实"}}]}}
如果全部有依据，输出：{{"checked_scene_count":{len(result.scenes)},"unsupported":[]}}
"""
    raw = llm_client.chat_completion_tracked(
        [
            {"role": "system", "content": "你只输出严格 JSON，事实不明时从严判定。"},
            {"role": "user", "content": prompt},
        ],
        caller=f"{caller}_source_grounding",
        temperature=0.0,
        json_mode=True,
        use_cache=use_cache,
    )
    if not raw:
        return ["原文事实审计无返回，按失败处理"]
    try:
        audit = json.loads(raw)
    except json.JSONDecodeError:
        return ["原文事实审计返回了无效 JSON，按失败处理"]
    if audit.get("checked_scene_count") != len(result.scenes):
        return ["原文事实审计未逐镜完成，按失败处理"]
    unsupported = audit.get("unsupported")
    if not isinstance(unsupported, list):
        return ["原文事实审计缺少 unsupported 列表，按失败处理"]
    errors: list[str] = []
    for item in unsupported:
        if not isinstance(item, dict):
            errors.append("原文事实审计返回了无效问题项")
            continue
        scene_id = item.get("scene_id", "?")
        reason = str(item.get("reason") or "存在原文未支持的事实").strip()
        errors.append(f"scene {scene_id}：{reason}")
    return errors
