"""Source-grounded highlight analysis for long-form novel promotion.

The novel is the factual source. Reference videos only contribute timing and
expression patterns; their plot, dialogue and characters are never copied into
the resulting highlight candidates.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from statistics import median
from typing import Any, Iterable


REPORT_SCHEMA = "novel_highlight_analysis/v1"
DEFAULT_CHUNK_CHARS = 6000
DEFAULT_OVERLAP_CHARS = 1200
MIN_VIDEO_SECONDS = 45
MAX_VIDEO_SECONDS = 180
DRIVER_NOVEL_HIGHLIGHT = "novel_highlight"
DRIVER_REFERENCE_VIDEO = "reference_video"
SUPPORTED_DRIVERS = {DRIVER_NOVEL_HIGHLIGHT, DRIVER_REFERENCE_VIDEO}


class NovelHighlightAnalysisError(RuntimeError):
    pass


@dataclass(slots=True)
class NovelTextChunk:
    index: int
    start_char: int
    end_char: int
    text: str


@dataclass(slots=True)
class ReferenceHighlightPattern:
    sample_count: int = 0
    median_duration_seconds: float | None = None
    median_hook_position_ratio: float | None = None
    median_peak_position_ratio: float | None = None
    conflict_patterns: list[str] = field(default_factory=list)
    evidence: list[dict[str, object]] = field(default_factory=list)


@dataclass(slots=True)
class NovelHighlightCandidate:
    highlight_id: str
    chunk_index: int
    source_start_char: int
    source_end_char: int
    source_start_quote: str
    source_end_quote: str
    title: str
    setup: str
    conflict: str
    turning_point: str
    emotional_peak: str
    aftershock: str
    cliffhanger: str
    characters: list[str]
    emotion_curve: list[str]
    conflict_score: float
    emotion_score: float
    reversal_score: float
    visual_score: float
    completeness_score: float
    weighted_score: float
    recommended_duration_seconds: int
    amplification_plan: list[dict[str, object]]


@dataclass(slots=True)
class NovelHighlightReport:
    novel_title: str
    source_sha256: str
    source_length: int
    chunk_count: int
    candidates: list[NovelHighlightCandidate]
    selected_highlight: NovelHighlightCandidate
    reference_pattern: ReferenceHighlightPattern
    driver_mode: str
    driver_decision: dict[str, object]
    schema: str = REPORT_SCHEMA
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class NovelHighlightAnalyzer:
    """Scan long text in bounded chunks and rank source-anchored highlights."""

    def __init__(
        self,
        client=None,
        *,
        chunk_chars: int = DEFAULT_CHUNK_CHARS,
        overlap_chars: int = DEFAULT_OVERLAP_CHARS,
        min_video_seconds: int = MIN_VIDEO_SECONDS,
        max_video_seconds: int = MAX_VIDEO_SECONDS,
    ) -> None:
        if chunk_chars < 1200:
            raise ValueError("chunk_chars must be at least 1200")
        if overlap_chars < 0 or overlap_chars >= chunk_chars // 2:
            raise ValueError("overlap_chars must be nonnegative and below half a chunk")
        if not 30 <= min_video_seconds <= max_video_seconds <= 300:
            raise ValueError("video duration range must be within 30-300 seconds")
        self.client = client
        self.chunk_chars = int(chunk_chars)
        self.overlap_chars = int(overlap_chars)
        self.min_video_seconds = int(min_video_seconds)
        self.max_video_seconds = int(max_video_seconds)

    def analyze(
        self,
        novel_text: str,
        *,
        novel_title: str = "",
        reference_analyses: Iterable[Any] = (),
        driver_mode: str = DRIVER_NOVEL_HIGHLIGHT,
    ) -> NovelHighlightReport:
        source = str(novel_text or "").strip()
        if len(source) < 200:
            raise NovelHighlightAnalysisError("小说文本不足200字，无法判断完整高光冲突段。")
        client = self.client
        driver_mode = str(driver_mode or "").strip()
        if driver_mode not in SUPPORTED_DRIVERS:
            raise NovelHighlightAnalysisError(
                f"不支持的小说剧本驱动模式: {driver_mode or 'empty'}"
            )
        if client is None:
            from src.shared.llm_client import LLMClient

            client = LLMClient()
        chunks = chunk_novel_text(
            source,
            chunk_chars=self.chunk_chars,
            overlap_chars=self.overlap_chars,
        )
        reference_pattern = analyze_reference_video_highlights(reference_analyses)
        if driver_mode == DRIVER_REFERENCE_VIDEO and (
            reference_pattern.sample_count == 0
            or reference_pattern.median_peak_position_ratio is None
        ):
            raise NovelHighlightAnalysisError(
                "参考视频驱动要求至少一份带时间证据的冲突峰值分析。"
            )
        candidates: list[NovelHighlightCandidate] = []
        for chunk in chunks:
            raw = client.chat_completion_tracked(
                _highlight_messages(
                    chunk,
                    novel_title=novel_title,
                    reference_pattern=reference_pattern,
                    driver_mode=driver_mode,
                ),
                caller="novel_highlight_analysis",
                temperature=0.2,
                json_mode=True,
                use_cache=True,
            )
            if not raw:
                continue
            candidates.extend(
                _parse_highlights(
                    raw,
                    chunk,
                    min_video_seconds=self.min_video_seconds,
                    max_video_seconds=self.max_video_seconds,
                    reference_pattern=reference_pattern,
                    driver_mode=driver_mode,
                )
            )
        candidates = _deduplicate(candidates)
        candidates.sort(key=lambda item: item.weighted_score, reverse=True)
        if not candidates:
            raise NovelHighlightAnalysisError(
                "模型没有返回能够在小说原文中精确定位的高光段。"
            )
        return NovelHighlightReport(
            novel_title=novel_title,
            source_sha256=hashlib.sha256(source.encode("utf-8")).hexdigest().upper(),
            source_length=len(source),
            chunk_count=len(chunks),
            candidates=candidates,
            selected_highlight=candidates[0],
            reference_pattern=reference_pattern,
            driver_mode=driver_mode,
            driver_decision=_driver_decision(driver_mode, reference_pattern),
        )


def chunk_novel_text(
    text: str,
    *,
    chunk_chars: int = DEFAULT_CHUNK_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[NovelTextChunk]:
    """Split long text near paragraph boundaries while retaining local overlap."""
    source = str(text or "")
    if not source:
        return []
    chunks: list[NovelTextChunk] = []
    start = 0
    while start < len(source):
        proposed = min(len(source), start + chunk_chars)
        end = proposed
        if proposed < len(source):
            floor = start + int(chunk_chars * 0.65)
            paragraph_break = source.rfind("\n", floor, proposed)
            sentence_break = max(
                source.rfind("。", floor, proposed),
                source.rfind("！", floor, proposed),
                source.rfind("？", floor, proposed),
            )
            boundary = max(paragraph_break, sentence_break)
            if boundary > start:
                end = boundary + 1
        chunks.append(NovelTextChunk(len(chunks), start, end, source[start:end]))
        if end >= len(source):
            break
        start = max(start + 1, end - overlap_chars)
    return chunks


def analyze_reference_video_highlights(
    analyses: Iterable[Any],
) -> ReferenceHighlightPattern:
    """Extract hook/turning-point positions from evidence-backed video analyses."""
    durations: list[float] = []
    hook_ratios: list[float] = []
    peak_ratios: list[float] = []
    conflict_patterns: list[str] = []
    evidence_rows: list[dict[str, object]] = []
    for analysis in analyses:
        duration = _get(analysis, "duration_seconds")
        expression = _get(analysis, "expression_analysis") or {}
        try:
            duration_value = float(duration)
        except (TypeError, ValueError):
            continue
        if duration_value <= 0:
            continue
        evidence = {
            str(row.get("id")): row
            for row in expression.get("evidence", [])
            if isinstance(row, dict) and row.get("id")
        }
        conflict = expression.get("conflict") or {}
        hook_seconds = _evidence_midpoint(conflict.get("trigger"), evidence)
        peak_seconds = _evidence_midpoint(conflict.get("turning_point"), evidence)
        if hook_seconds is not None:
            hook_ratios.append(min(1.0, max(0.0, hook_seconds / duration_value)))
        if peak_seconds is not None:
            peak_ratios.append(min(1.0, max(0.0, peak_seconds / duration_value)))
        for key in ("trigger", "opposition", "stakes", "turning_point"):
            node = conflict.get(key) or {}
            text = str(node.get("text") or "").strip()
            if (
                text
                and _evidence_midpoint(node, evidence) is not None
                and key not in conflict_patterns
            ):
                # Keep only the observed dramatic stage. Reference-video plot
                # wording must never become a source for the novel script.
                conflict_patterns.append(key)
        durations.append(duration_value)
        evidence_rows.append({
            "video_id": _get(analysis, "video_id") or _get(analysis, "item_id") or "",
            "duration_seconds": duration_value,
            "hook_seconds": hook_seconds,
            "peak_seconds": peak_seconds,
        })
    return ReferenceHighlightPattern(
        sample_count=len(durations),
        median_duration_seconds=round(median(durations), 2) if durations else None,
        median_hook_position_ratio=(
            round(median(hook_ratios), 4) if hook_ratios else None
        ),
        median_peak_position_ratio=(
            round(median(peak_ratios), 4) if peak_ratios else None
        ),
        conflict_patterns=conflict_patterns[:12],
        evidence=evidence_rows[:30],
    )


def render_highlight_report(report: NovelHighlightReport) -> str:
    selected = report.selected_highlight
    lines = [
        "# 小说高光与情绪冲突分析",
        "",
        f"- 小说：{report.novel_title or '未命名'}",
        f"- 原文字数：{report.source_length}",
        f"- 分段扫描：{report.chunk_count} 段",
        f"- 高光候选：{len(report.candidates)} 个",
        f"- 驱动模式：{report.driver_mode}",
        f"- 推荐时长：{selected.recommended_duration_seconds} 秒",
        "",
        "## 选中高光",
        "",
        f"- 标题：{selected.title}",
        f"- 原文位置：{selected.source_start_char}—{selected.source_end_char}",
        f"- 冲突：{selected.conflict}",
        f"- 转折：{selected.turning_point}",
        f"- 情绪峰值：{selected.emotional_peak}",
        f"- 峰值余波：{selected.aftershock}",
        f"- 断点：{selected.cliffhanger}",
        f"- 情绪曲线：{' → '.join(selected.emotion_curve)}",
        "",
        "## 放大节奏",
        "",
    ]
    for item in selected.amplification_plan:
        lines.append(
            f"- {item['stage']}：约 {item['duration_seconds']} 秒；{item['focus']}"
        )
    lines.extend([
        "",
        "参考视频只用于确定钩子、峰值位置和表达节奏；剧情事实全部来自上述原文位置。",
        "",
    ])
    return "\n".join(lines)


def _highlight_messages(
    chunk: NovelTextChunk,
    *,
    novel_title: str,
    reference_pattern: ReferenceHighlightPattern,
    driver_mode: str,
) -> list[dict[str, str]]:
    reference = (
        json.dumps(asdict(reference_pattern), ensure_ascii=False)
        if driver_mode == DRIVER_REFERENCE_VIDEO
        else "小说高光驱动：候选选择和时长只由小说原文决定"
    )
    prompt = f"""分析下面小说原文中的高光剧情。不要改写剧情，不要补写原文没有的事实。

小说：{novel_title or '未命名'}
原文绝对字符范围：{chunk.start_char}—{chunk.end_char}
参考视频表达统计：{reference}
当前驱动模式：{driver_mode}

输出严格 JSON：
{{
  "highlights": [
    {{
      "title": "高光名称",
      "start_quote": "原文中连续出现的准确起始短句",
      "end_quote": "原文中位于起始短句之后的准确结束短句",
      "setup": "冲突发生前必须保留的前因",
      "conflict": "双方目标、阻力和代价",
      "turning_point": "局势改变的具体事件",
      "emotional_peak": "人物情绪爆发及可见动作",
      "aftershock": "高光之后人物的反应和关系变化",
      "cliffhanger": "可在不篡改原文的前提下停住的位置",
      "characters": ["角色"],
      "emotion_curve": ["压抑", "对抗", "爆发", "错愕", "余波"],
      "scores": {{
        "conflict": 0,
        "emotion": 0,
        "reversal": 0,
        "visual": 0,
        "completeness": 0
      }}
    }}
  ]
}}

要求：
- 每项分数0—10；每段最多返回3个候选。
- start_quote和end_quote必须逐字来自所给原文，并共同包住完整的前因、升级、爆发和余波。
- 高光不能只是一句金句；必须有目标冲突、局势变化和人物反应。
- 参考视频只影响表达结构，严禁把参考视频剧情写进小说。

原文：
{chunk.text}
"""
    return [
        {"role": "system", "content": "你是小说剧情编辑，只输出严格JSON。"},
        {"role": "user", "content": prompt},
    ]


def _parse_highlights(
    raw: str,
    chunk: NovelTextChunk,
    *,
    min_video_seconds: int,
    max_video_seconds: int,
    reference_pattern: ReferenceHighlightPattern,
    driver_mode: str,
) -> list[NovelHighlightCandidate]:
    text = str(raw).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    rows = payload.get("highlights") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    output: list[NovelHighlightCandidate] = []
    for row in rows[:3]:
        if not isinstance(row, dict):
            continue
        start_quote = str(row.get("start_quote") or "").strip()
        end_quote = str(row.get("end_quote") or "").strip()
        if len(start_quote) < 4 or len(end_quote) < 4:
            continue
        local_start = chunk.text.find(start_quote)
        if local_start < 0:
            continue
        local_end_start = chunk.text.find(end_quote, local_start)
        if local_end_start < 0:
            continue
        local_end = local_end_start + len(end_quote)
        if local_end <= local_start:
            continue
        required_story_fields = (
            "setup",
            "conflict",
            "turning_point",
            "emotional_peak",
            "aftershock",
        )
        if any(not str(row.get(name) or "").strip() for name in required_story_fields):
            continue
        scores = row.get("scores") or {}
        values = {
            name: _bounded_score(scores.get(name))
            for name in ("conflict", "emotion", "reversal", "visual", "completeness")
        }
        weighted = round(
            values["conflict"] * 0.25
            + values["emotion"] * 0.25
            + values["reversal"] * 0.20
            + values["visual"] * 0.15
            + values["completeness"] * 0.15,
            3,
        )
        start = chunk.start_char + local_start
        end = chunk.start_char + local_end
        emotions = _strings(row.get("emotion_curve"))[:8]
        if len(emotions) < 4:
            continue
        duration = _recommended_duration(
            end - start,
            len(emotions),
            values["emotion"],
            minimum=min_video_seconds,
            maximum=max_video_seconds,
            driver_mode=driver_mode,
            reference_pattern=reference_pattern,
        )
        candidate_id = "highlight:" + hashlib.sha256(
            f"{start}|{end}|{start_quote}|{end_quote}".encode("utf-8")
        ).hexdigest()[:20]
        output.append(NovelHighlightCandidate(
            highlight_id=candidate_id,
            chunk_index=chunk.index,
            source_start_char=start,
            source_end_char=end,
            source_start_quote=start_quote,
            source_end_quote=end_quote,
            title=str(row.get("title") or "未命名高光").strip(),
            setup=str(row.get("setup") or "").strip(),
            conflict=str(row.get("conflict") or "").strip(),
            turning_point=str(row.get("turning_point") or "").strip(),
            emotional_peak=str(row.get("emotional_peak") or "").strip(),
            aftershock=str(row.get("aftershock") or "").strip(),
            cliffhanger=str(row.get("cliffhanger") or "").strip(),
            characters=_strings(row.get("characters"))[:12],
            emotion_curve=emotions,
            conflict_score=values["conflict"],
            emotion_score=values["emotion"],
            reversal_score=values["reversal"],
            visual_score=values["visual"],
            completeness_score=values["completeness"],
            weighted_score=weighted,
            recommended_duration_seconds=duration,
            amplification_plan=_amplification_plan(
                duration,
                reference_pattern,
                driver_mode=driver_mode,
            ),
        ))
    return output


def _recommended_duration(
    span_chars: int,
    emotion_steps: int,
    emotion_score: float,
    *,
    minimum: int,
    maximum: int,
    driver_mode: str,
    reference_pattern: ReferenceHighlightPattern,
) -> int:
    if (
        driver_mode == DRIVER_REFERENCE_VIDEO
        and reference_pattern.median_duration_seconds is not None
    ):
        duration = int(
            math.ceil(reference_pattern.median_duration_seconds / 15) * 15
        )
        return max(minimum, min(maximum, duration))
    if span_chars <= 800:
        duration = 45
    elif span_chars <= 1800:
        duration = 60
    elif span_chars <= 3500:
        duration = 90
    elif span_chars <= 6000:
        duration = 120
    else:
        duration = 150
    if emotion_steps >= 6:
        duration += 15
    if emotion_score >= 9:
        duration += 15
    # A very short source span cannot support a long sequence without the
    # storyboard inventing locations, opponents or extra actions.  Emotion
    # intensity may change the pacing inside the sequence, but it must not
    # create more story information than the selected text contains.
    information_ceiling = (
        45 if span_chars <= 400 else
        60 if span_chars <= 800 else
        90 if span_chars <= 1800 else
        120 if span_chars <= 3500 else
        150
    )
    duration = min(duration, information_ceiling)
    duration = int(math.ceil(duration / 15) * 15)
    return max(minimum, min(maximum, duration))


def _amplification_plan(
    duration: int,
    reference_pattern: ReferenceHighlightPattern,
    *,
    driver_mode: str,
) -> list[dict[str, object]]:
    hook_position = (
        reference_pattern.median_hook_position_ratio
        if driver_mode == DRIVER_REFERENCE_VIDEO
        else None
    )
    peak_position = (
        reference_pattern.median_peak_position_ratio
        if driver_mode == DRIVER_REFERENCE_VIDEO
        else None
    )
    hook_ratio = min(0.12, max(0.08, (hook_position or 0.03) + 0.07))
    peak_center = min(0.68, max(0.50, peak_position or 0.625))
    before_peak = peak_center - 0.125
    setup_ratio = 0.15
    escalation_ratio = before_peak - hook_ratio - setup_ratio
    peak_ratio = 0.25
    cliffhanger_ratio = 0.10
    aftershock_ratio = 1.0 - before_peak - peak_ratio - cliffhanger_ratio
    stages = (
        ("高光预示", hook_ratio, "先让观众看到失控结果或关键动作，不提前讲完整答案。"),
        ("必要前因", setup_ratio, "只保留理解人物目标和关系所需的信息。"),
        ("冲突升级", escalation_ratio, "用连续行动和对白提高压力，避免解释性旁白堆积。"),
        ("情绪峰值", peak_ratio, "放大关键对白前、中、后的表情、停顿、身体反应和对手反馈。"),
        ("峰值余波", aftershock_ratio, "保留震惊、犹豫、崩溃或关系变化，使高光真正落地。"),
        ("悬念断点", cliffhanger_ratio, "停在下一步行动前，以授权平台内搜索或继续阅读收束。"),
    )
    allocated = 0
    output = []
    for index, (stage, ratio, focus) in enumerate(stages):
        seconds = duration - allocated if index == len(stages) - 1 else round(duration * ratio)
        allocated += seconds
        output.append({"stage": stage, "duration_seconds": seconds, "focus": focus})
    return output


def _driver_decision(
    driver_mode: str,
    reference_pattern: ReferenceHighlightPattern,
) -> dict[str, object]:
    if driver_mode == DRIVER_REFERENCE_VIDEO:
        return {
            "story_facts_from": "novel_source_only",
            "highlight_selection_from": "novel_candidates",
            "duration_from": "reference_video_median",
            "hook_and_peak_positions_from": "reference_video_evidence",
            "reference_sample_count": reference_pattern.sample_count,
        }
    return {
        "story_facts_from": "novel_source_only",
        "highlight_selection_from": "novel_conflict_ranking",
        "duration_from": "novel_span_and_emotion_steps",
        "hook_and_peak_positions_from": "novel_editorial_curve",
        "reference_sample_count": reference_pattern.sample_count,
    }


def _deduplicate(
    candidates: list[NovelHighlightCandidate],
) -> list[NovelHighlightCandidate]:
    output: list[NovelHighlightCandidate] = []
    for candidate in sorted(candidates, key=lambda item: item.weighted_score, reverse=True):
        duplicate = False
        for existing in output:
            intersection = max(
                0,
                min(candidate.source_end_char, existing.source_end_char)
                - max(candidate.source_start_char, existing.source_start_char),
            )
            shorter = max(
                1,
                min(
                    candidate.source_end_char - candidate.source_start_char,
                    existing.source_end_char - existing.source_start_char,
                ),
            )
            if intersection / shorter >= 0.6:
                duplicate = True
                break
        if not duplicate:
            output.append(candidate)
    return output


def _evidence_midpoint(node: Any, evidence: dict[str, dict]) -> float | None:
    if not isinstance(node, dict):
        return None
    points = []
    for evidence_id in node.get("evidence_ids") or []:
        row = evidence.get(str(evidence_id))
        if not row:
            continue
        try:
            start = float(row.get("start_seconds"))
            end = float(row.get("end_seconds"))
        except (TypeError, ValueError):
            continue
        points.append((start + end) / 2)
    return median(points) if points else None


def _bounded_score(value: Any) -> float:
    try:
        return round(min(10.0, max(0.0, float(value))), 2)
    except (TypeError, ValueError):
        return 0.0


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _get(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)
