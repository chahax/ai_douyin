"""Safe fallback analysis using only retained page metadata."""

from __future__ import annotations

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


class MetadataContentAnalysisProvider:
    provider_id = "metadata_heuristic"
    provider_version = "v1"
    max_parallelism = 4

    def analyze(self, request: ContentAnalysisRequest) -> VideoContentAnalysis:
        text = " ".join(
            value
            for value in (request.title, request.raw_text, *request.hashtags)
            if value
        )
        evidence = [ContentEvidence(channel="title", text=request.title, confidence=1.0)]
        evidence.extend(
            ContentEvidence(channel="hashtag", text=f"#{tag}", confidence=1.0)
            for tag in request.hashtags
        )
        if request.raw_text:
            evidence.append(
                ContentEvidence(
                    channel="visible_metadata",
                    text=request.raw_text[:1000],
                    confidence=0.8,
                )
            )
        presentation, presentation_features = classify_presentation(text)
        hook_type, hook_text = classify_hook(request.title)
        relevance = score_account_relevance(
            request.account_profile,
            title=request.title,
            hashtags=request.hashtags,
            content_text=text,
            evidence=evidence,
        )
        domain = request.account_profile.domain_strategy_id
        user_intents = (
            ["规则理解", "证据准备", "处理步骤", "咨询判断"]
            if domain == "legal_services"
            else ["题材偏好", "情绪回报", "追更", "求书名"]
        )
        duration = max(0.0, float(request.duration_seconds or 0.0))
        segments = [
            ContentSegment(
                start_seconds=0.0,
                end_seconds=duration,
                role="metadata_outline",
                summary=request.title,
            )
        ]
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
            status="degraded",
            media_access_mode="metadata_only",
            title=request.title,
            content_summary=request.title,
            topic_labels=_unique([*request.hashtags, *relevance.matched_topic_terms]),
            user_intents=user_intents,
            hook_type=hook_type,
            hook_text=hook_text,
            presentation_type=presentation,
            presentation_features=presentation_features,
            pacing="unknown",
            duration_seconds=request.duration_seconds,
            segments=segments,
            evidence=evidence,
            uncertainties=[
                "未读取视频、音频或逐帧内容，展示方式仅由标题和页面元数据推断。",
                "页面展示指标口径未知时，不据此推断播放量或完播率。",
            ],
            originality_boundaries=[
                "仅提取主题、用户问题和结构特征，不复用原视频完整文案。",
                "不得复制独特对白、镜头组合、角色设定或受版权保护的剧情表达。",
            ],
            relevance=relevance,
        )


def _unique(values: list[str]) -> list[str]:
    output: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized not in output:
            output.append(normalized)
    return output[:20]
