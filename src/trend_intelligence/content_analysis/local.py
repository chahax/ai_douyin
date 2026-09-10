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
from .artifacts import parse_model_json, sha256, transcript_evidence, validate_expression, verify_expression_evidence, require_no_semantic_rejection
from .classification import (
    classify_hook,
    classify_presentation,
    score_account_relevance,
)


class LocalQwenParaformerProvider:
    provider_id = "local_qwen_paraformer"
    provider_version = "v2"
    max_parallelism = 1

    def analyze(self, request: ContentAnalysisRequest) -> VideoContentAnalysis:
        if request.media_access_mode != "local_media_authorized":
            raise PermissionError("local analysis requires local_media_authorized")
        if not request.qwen_analysis_path and not request.transcript_path:
            raise ValueError("local analysis requires a Qwen or transcript artifact")
        if request.qwen_analysis_path:
            require_no_semantic_rejection(request.qwen_analysis_path)

        visual_payload = _read_json(request.qwen_analysis_path) if request.qwen_analysis_path else {}
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
        media = _media_evidence(request, visual_payload, transcript_payload)
        expression = visual.get("expression_analysis") or {}
        if expression:
            expression = validate_expression(expression, expression.get("evidence") or [],
                                             float(media.get("duration_seconds") or request.duration_seconds or 0))
            if visual_payload.get("schema") == "local_qwen_frame_analysis/v2":
                verify_expression_evidence(expression, _read_json(visual_payload["frame_manifest_path"]),
                                           transcript_payload, visual_batches=visual_payload.get("batches") or [],
                                           observation_review=visual_payload.get("observation_review"))
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
        if expression:
            evidence = [ContentEvidence(channel=item["channel"], text=item["text"],
                        start_seconds=item["start_seconds"], end_seconds=item["end_seconds"],
                        confidence=.75 if item["channel"] == "visual" else .82)
                        for item in expression["evidence"]]
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
        modes = {item.get("mode") for item in expression.get("expression_modes") or []}
        if modes:
            presentation = ("story_drama" if modes & {"conflict_drama", "case_reenactment"}
                            else "screen_recording" if modes == {"screen_demonstration"}
                            else "text_cards" if modes == {"text_cards"}
                            else "interview" if modes == {"interview"}
                            else "talking_head" if modes <= {"direct_explanation", "question_answer"}
                            else "mixed")
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
        uncertainties.append("仅完成抽样画面理解和语音文字识别；声线、语气、音乐、音效和口型匹配未分析。")
        uncertainties.append("核心表达及表达方式属于模型自动归纳候选，须独立复核语义保真，不能把结构校验当作人工通过。")
        analysis = VideoContentAnalysis(
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
            status="completed" if expression and media["visual"]["status"] == "completed" else "degraded",
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
            expression_analysis=expression,
            media_evidence=media,
        )
        from src.trend_intelligence.media_evidence import media_readiness
        readiness = media_readiness(analysis)
        if not readiness["ready"]:
            analysis.status = "degraded"
            analysis.uncertainties = _unique([*analysis.uncertainties, *readiness["reasons"]])
        return analysis


def _load_qwen(value: str) -> dict[str, Any]:
    payload = _read_json(value)
    answer = payload.get("answer", payload)
    if isinstance(answer, dict):
        return answer
    if not isinstance(answer, str):
        return {}
    return parse_model_json(answer)


def _media_evidence(request, visual, transcript):
    output = {
        "schema": "local_media_evidence/v1", "source_video_path": request.local_video_path,
        "source_video_sha256": "", "duration_seconds": request.duration_seconds,
        "visual": {"status": "unverified" if visual else "missing"},
        "audio": {"status": "unverified" if transcript else "missing", "prosody_status": "not_analyzed",
                  "speaker_identity_status": "not_analyzed", "lip_sync_status": "not_analyzed"},
    }
    if request.local_video_path and Path(request.local_video_path).is_file():
        output["source_video_sha256"] = sha256(request.local_video_path)
    if visual.get("schema") != "local_qwen_frame_analysis/v2":
        return output
    source_sha = output["source_video_sha256"]
    if not source_sha or visual.get("source_video_sha256") != source_sha:
        raise ValueError("Qwen artifact is not bound to the current original video")
    manifest_path = Path(visual["frame_manifest_path"])
    if sha256(manifest_path) != visual.get("frame_manifest_sha256"):
        raise ValueError("Qwen frame manifest changed")
    manifest = _read_json(str(manifest_path))
    if manifest.get("schema") != "local_video_frame_manifest/v2" or manifest.get("source_video_sha256") != source_sha:
        raise ValueError("frame manifest source mismatch")
    frames = manifest.get("frames") or []
    observed = visual.get("analyzed_frame_ids") or []
    if len(set(observed)) != len(frames) or len(observed) != len(frames) or set(observed) != {f["id"] for f in frames}:
        raise ValueError("not every sampled frame was actually analyzed")
    for frame in frames:
        if sha256(frame["path"]) != frame["sha256"]:
            raise ValueError("sampled frame changed since analysis")
    times = [frame["time_seconds"] for frame in frames]
    output["duration_seconds"] = manifest["duration_seconds"]
    output["visual"] = {"status": "completed", "artifact_path": request.qwen_analysis_path,
        "artifact_sha256": sha256(request.qwen_analysis_path), "frame_manifest_path": str(manifest_path),
        "frame_manifest_sha256": sha256(manifest_path), "sample_times_seconds": times,
        "total_sampled_frame_count": len(frames), "analyzed_frame_count": len(observed),
        "coverage_start_seconds": min(times), "coverage_end_seconds": max(times),
        "scope": "sampled images only; no continuous action or lip-sync verification"}
    provenance = transcript.get("provenance") or {}
    if (provenance.get("schema") != "local_audio_evidence/v2" or
            provenance.get("source_video_sha256") != source_sha or
            visual.get("transcript_sha256") != sha256(request.transcript_path)):
        raise ValueError("transcript provenance or Qwen fusion input changed")
    if provenance.get("audio_path") and sha256(provenance["audio_path"]) != provenance.get("audio_sha256"):
        raise ValueError("extracted audio changed since transcription")
    status = provenance.get("status")
    if status == "transcribed" and not transcript_evidence(transcript):
        raise ValueError("transcribed status requires actual timestamped speech")
    if status == "verified_no_speech":
        reason = provenance.get("status_reason")
        if not reason or transcript_evidence(transcript):
            raise ValueError("no-speech conclusion lacks evidence or contradicts transcription")
        if not provenance.get("audio_path"):
            probe = provenance.get("source_probe") or {}
            if "streams" not in probe or any(s.get("codec_type") == "audio" for s in probe["streams"]):
                raise ValueError("no-audio conclusion requires actual probe evidence")
        else:
            from .toolchain import _silent_pcm
            silent, covered = _silent_pcm(Path(provenance["audio_path"]))
            if not silent or covered < output["duration_seconds"] - .25:
                raise ValueError("no-speech conclusion requires full verified silent PCM")
    output["audio"].update({key: provenance.get(key) for key in (
        "status", "status_reason", "audio_path", "audio_sha256", "coverage_start_seconds", "coverage_end_seconds")})
    output["audio"].update({"artifact_path": request.transcript_path,
                            "artifact_sha256": sha256(request.transcript_path)})
    return output


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
