"""Adapter for Qwen frame-analysis and Paraformer transcript artifacts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src.trend_intelligence.models import (
    ContentEvidence,
    ContentSegment,
    VideoContentAnalysis,
)

from .base import ContentAnalysisRequest, stable_analysis_id
from .classification import (
    classify_hook,
    classify_presentation,
    score_account_relevance,
)


class LocalQwenParaformerProvider:
    provider_id = "local_qwen_paraformer"
    provider_version = "v1"
    max_parallelism = 1

    def analyze(self, request: ContentAnalysisRequest) -> VideoContentAnalysis:
        if request.media_access_mode != "local_media_authorized":
            raise PermissionError("local analysis requires local_media_authorized")
        if not request.qwen_analysis_path and not request.transcript_path:
            raise ValueError("local analysis requires a Qwen or transcript artifact")

        visual = _load_qwen(request.qwen_analysis_path) if request.qwen_analysis_path else {}
        transcript_payload = (
            _read_json(request.transcript_path) if request.transcript_path else {}
        )
        scene_payload = (
            _read_json(request.scene_alignment_path)
            if request.scene_alignment_path
            else {}
        )
        transcript = _transcript_text(transcript_payload)
        visual_summary = str(visual.get("summary") or "").strip()
        visible_text = _strings(visual.get("visible_text"))
        editing_style = _strings(visual.get("editing_style"))
        retention = _strings(visual.get("hook_and_retention"))
        combined = " ".join(
            (
                request.title,
                visual_summary,
                transcript,
                *visible_text,
                *editing_style,
                *retention,
            )
        )
        evidence = _visual_evidence(visual)
        evidence.extend(_scene_evidence(scene_payload))
        if transcript and not any(item.channel == "asr" for item in evidence):
            evidence.append(
                ContentEvidence(channel="asr", text=transcript[:2000], confidence=0.82)
            )
        evidence.insert(
            0, ContentEvidence(channel="title", text=request.title, confidence=1.0)
        )
        inferred_presentation, presentation_features = classify_presentation(combined)
        declared_presentation = str(visual.get("presentation_type") or "").strip()
        presentation = (
            declared_presentation
            if declared_presentation
            in {
                "talking_head",
                "story_drama",
                "screen_recording",
                "text_cards",
                "interview",
                "mixed",
                "unknown",
            }
            else inferred_presentation
        )
        presentation_features = _unique([*presentation_features, *editing_style])
        hook_text = retention[0] if retention else request.title
        hook_type, _ = classify_hook(hook_text)
        relevance = score_account_relevance(
            request.account_profile,
            title=request.title,
            hashtags=request.hashtags,
            content_text=combined,
            evidence=evidence,
        )
        uncertainties = _strings(visual.get("uncertainties"))
        if not transcript:
            uncertainties.append("未取得可用语音转写，口播内容和对白判断不完整。")
        if not visual:
            uncertainties.append("未取得 Qwen 关键帧分析，视觉展示方式判断不完整。")
        return VideoContentAnalysis(
            analysis_id=stable_analysis_id(
                request,
                provider_id=self.provider_id,
                provider_version=self.provider_version,
            ),
            item_id=request.item_id,
            video_id=request.video_id,
            account_uuid=request.account_profile.account_uuid,
            profile_version=request.account_profile.profile_version,
            provider_id=self.provider_id,
            provider_version=self.provider_version,
            input_fingerprint=request.input_fingerprint(),
            status="completed" if visual and transcript else "degraded",
            media_access_mode=request.media_access_mode,
            title=request.title,
            content_summary=visual_summary or transcript[:500] or request.title,
            transcript_summary=transcript[:1000],
            visual_summary=visual_summary,
            topic_labels=_unique(
                [
                    *_strings(visual.get("topic_labels")),
                    *_strings(visual.get("content_category")),
                    *request.hashtags,
                    *relevance.matched_topic_terms,
                ]
            ),
            user_intents=(
                _strings(visual.get("user_intents"))
                or _domain_intents(request.account_profile.domain_strategy_id)
            ),
            hook_type=hook_type,
            hook_text=hook_text,
            presentation_type=presentation,
            presentation_features=presentation_features,
            pacing=_declared_or_inferred_pacing(visual, editing_style, scene_payload),
            duration_seconds=request.duration_seconds,
            segments=_segments(visual, scene_payload, request.duration_seconds),
            evidence=evidence[:30],
            uncertainties=_unique(uncertainties),
            originality_boundaries=[
                "分析结果只复用抽象主题、节奏、钩子类型和展示形式。",
                "不得复用原视频完整转写、连续对白、独特镜头顺序或可识别角色设定。",
            ],
            relevance=relevance,
        )


def _load_qwen(value: str) -> dict[str, Any]:
    payload = _read_json(value)
    answer = payload.get("answer", payload)
    if isinstance(answer, dict):
        return answer
    if not isinstance(answer, str):
        return {}
    normalized = answer.strip()
    normalized = re.sub(r"^```(?:json)?\s*", "", normalized, flags=re.I)
    normalized = re.sub(r"\s*```$", "", normalized)
    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", normalized, flags=re.S)
        if not match:
            return {"summary": normalized[:1000]}
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {"summary": normalized[:1000]}
    return parsed if isinstance(parsed, dict) else {}


def _read_json(value: str) -> dict[str, Any]:
    path = Path(value).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"analysis artifact must be an object: {path}")
    return payload


def _transcript_text(payload: dict[str, Any]) -> str:
    fragments: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            text = value.get("text")
            if isinstance(text, str) and text.strip():
                fragments.append(text.strip())
            for key, child in value.items():
                if key != "text":
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload.get("result", payload))
    return " ".join(_unique(fragments))


def _visual_evidence(visual: dict[str, Any]) -> list[ContentEvidence]:
    output: list[ContentEvidence] = []
    for item in visual.get("visual_timeline") or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("event") or "").strip()
        if not text:
            continue
        second = _time_to_seconds(str(item.get("time") or ""))
        output.append(
            ContentEvidence(
                channel="visual",
                text=text,
                start_seconds=second,
                confidence=0.75,
            )
        )
    output.extend(
        ContentEvidence(channel="ocr", text=value, confidence=0.68)
        for value in _strings(visual.get("visible_text"))
    )
    return output


def _scene_evidence(payload: dict[str, Any]) -> list[ContentEvidence]:
    output: list[ContentEvidence] = []
    for item in payload.get("scenes") or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("asr_text") or item.get("summary") or "").strip()
        if text:
            output.append(
                ContentEvidence(
                    channel="asr",
                    text=text,
                    start_seconds=_number(item.get("start")),
                    end_seconds=_number(item.get("end")),
                    confidence=0.85,
                )
            )
    return output


def _segments(
    visual: dict[str, Any],
    scenes: dict[str, Any],
    duration: float | None,
) -> list[ContentSegment]:
    output: list[ContentSegment] = []
    for item in visual.get("content_structure") or []:
        if not isinstance(item, dict):
            continue
        start = _number(item.get("start"))
        end = _number(item.get("end"))
        if start is None or end is None or end < start:
            continue
        output.append(
            ContentSegment(
                start_seconds=start,
                end_seconds=end,
                role=str(item.get("role") or "beat"),
                summary=str(item.get("summary") or ""),
            )
        )
    if output:
        return output
    for index, item in enumerate(scenes.get("scenes") or []):
        if not isinstance(item, dict):
            continue
        start = _number(item.get("start")) or 0.0
        end = _number(item.get("end"))
        if end is None:
            end = start
        summary = str(item.get("asr_text") or item.get("summary") or "").strip()
        output.append(
            ContentSegment(start, max(start, end), f"scene_{index + 1}", summary)
        )
    if output:
        return output
    timeline = [
        item for item in visual.get("visual_timeline") or [] if isinstance(item, dict)
    ]
    points = [(_time_to_seconds(str(item.get("time") or "")), item) for item in timeline]
    points = [(value, item) for value, item in points if value is not None]
    for index, (start, item) in enumerate(points):
        end = (
            points[index + 1][0]
            if index + 1 < len(points)
            else max(start, float(duration or start))
        )
        output.append(
            ContentSegment(
                start_seconds=start,
                end_seconds=end,
                role="visual_beat",
                summary=str(item.get("event") or ""),
            )
        )
    return output


def _classify_pacing(styles: list[str], scenes: dict[str, Any]) -> str:
    text = " ".join(styles)
    if any(term in text for term in ("快", "密集", "频繁", "跳切")):
        return "fast"
    if any(term in text for term in ("慢", "舒缓", "长镜头")):
        return "slow"
    if len(scenes.get("scenes") or []) >= 6:
        return "fast"
    return "balanced" if styles or scenes else "unknown"


def _declared_or_inferred_pacing(
    visual: dict[str, Any], styles: list[str], scenes: dict[str, Any]
) -> str:
    declared = str(visual.get("pacing") or "").strip()
    if declared in {"fast", "balanced", "slow", "unknown"}:
        return declared
    return _classify_pacing(styles, scenes)


def _domain_intents(domain: str) -> list[str]:
    if domain == "legal_services":
        return ["规则理解", "证据准备", "风险判断", "咨询意图"]
    if domain == "novel_promotion":
        return ["题材偏好", "爽点", "悬念", "追更意图"]
    return ["信息获取", "互动意图"]


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _unique(values: list[str]) -> list[str]:
    output: list[str] = []
    for value in values:
        if value and value not in output:
            output.append(value)
    return output[:30]


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _time_to_seconds(value: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*秒", value)
    return float(match.group(1)) if match else None
