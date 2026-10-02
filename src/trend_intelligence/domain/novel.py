"""Novel-promotion operation strategy."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.operations_accounts import AccountProfile

from .base import (
    AccountFitEvidence,
    DomainBriefBlueprint,
    DomainQueryPlan,
    DomainTopicContext,
    PydanticDomainStrategy,
    text_matches,
    unique_terms,
)


NOVEL_DEFAULT_TERMS = [
    "小说",
    "推文",
    "书荒",
    "重生",
    "复仇",
    "大女主",
    "古言",
    "现言",
    "爽文",
    "完结",
    "反转",
]


class NovelPromotionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    genres: list[str] = Field(default_factory=list)
    promotion_platform: str = "番茄小说"
    require_authorized_chapters: bool = True
    reading_cta: str = "引导在平台内搜索书名或继续阅读"
    script_driver: Literal["novel_highlight", "reference_video"] = "novel_highlight"
    highlight_scan_chunk_chars: int = Field(default=6000, ge=1200, le=12000)
    highlight_scan_overlap_chars: int = Field(default=1200, ge=0, le=3000)
    min_video_seconds: int = Field(default=45, ge=30, le=180)
    default_video_seconds: int = Field(default=60, ge=30, le=240)
    max_video_seconds: int = Field(default=180, ge=45, le=300)

    @model_validator(mode="after")
    def _validate_ranges(self) -> "NovelPromotionConfig":
        if self.highlight_scan_overlap_chars >= self.highlight_scan_chunk_chars // 2:
            raise ValueError("highlight scan overlap must be below half a chunk")
        if not (
            self.min_video_seconds
            <= self.default_video_seconds
            <= self.max_video_seconds
        ):
            raise ValueError("novel video duration must satisfy min <= default <= max")
        return self


class NovelPromotionStrategy(PydanticDomainStrategy):
    strategy_id = "novel_promotion"
    version = "v1"
    label = "小说推文与推广"
    config_model = NovelPromotionConfig

    def build_query_plan(self, profile: AccountProfile) -> DomainQueryPlan:
        config = self.validate_profile(profile)
        roots = unique_terms(
            profile.seed_keywords,
            profile.service_scope,
            config["genres"],
        ) or ["小说推文"]
        related = unique_terms(
            [f"{root} 一口气看完" for root in roots],
            [f"{root} 高能反转" for root in roots],
            [f"{root} 完结" for root in roots],
        )
        return DomainQueryPlan(
            root_keywords=roots,
            related_keywords=related,
            negative_keywords=profile.negative_keywords,
            intent_labels=["题材偏好", "爽点", "悬念", "求书名", "阅读意图"],
            metadata={
                "strategy_id": self.strategy_id,
                "strategy_version": self.version,
                "account_uuid": profile.account_uuid,
                "promotion_platform": config["promotion_platform"],
            },
        )

    def score_account_fit(
        self,
        profile: AccountProfile,
        topic: DomainTopicContext,
    ) -> AccountFitEvidence:
        self.validate_profile(profile)
        excluded = text_matches(topic.searchable_text, profile.negative_keywords)
        if excluded:
            return AccountFitEvidence(
                score=0,
                excluded_terms=excluded,
                reasons=["命中账号排除词，不进入小说推广推荐。"],
            )
        preferred = unique_terms(profile.matching_terms(), NOVEL_DEFAULT_TERMS)
        matched = text_matches(topic.searchable_text, preferred)
        profile_matches = text_matches(topic.searchable_text, profile.matching_terms())
        score = min(100.0, 30.0 + 18.0 * len(matched) + 14.0 * len(profile_matches))
        reasons = (
            [f"命中小说账号主题：{', '.join(matched[:6])}"]
            if matched
            else ["未命中明确小说题材，只保留低相关候选。"]
        )
        return AccountFitEvidence(score=score, matched_terms=matched, reasons=reasons)

    def build_brief_blueprint(
        self,
        profile: AccountProfile,
        topic: DomainTopicContext,
    ) -> DomainBriefBlueprint:
        config = self.validate_profile(profile)
        title = topic.title or "该小说题材"
        risks = [
            "热门样本只用于分析题材、节奏和用户兴趣，不得复制完整剧情或文案。",
            "剧本必须使用目标推广小说的授权章节或任务材料。",
            "不得编造目标小说不存在的桥段，不得泄露核心大结局。",
            "不得使用盗版、免费全集或虚假收益等违规引导。",
        ]
        return DomainBriefBlueprint(
            audience_questions=[
                f"喜欢“{title}”的用户最期待哪种身份冲突和情绪回报？",
                "长文本中哪一段同时具备完整前因、冲突升级、情绪爆发和人物余波？",
                "参考视频的高光出现在什么时间位置，如何只借表达节奏放大小说原有高光？",
                "在哪个原文悬念点断开最容易形成搜索或追更意图？",
            ],
            angles=[
                "高光定位：分段扫描长文本，对冲突、情绪、反转、可视化和完整度排序",
                "高光放大：保留必要前因，让峰值前后的动作、表情和对手反应获得镜头时间",
                "动态时长：根据选中高光的事件跨度和情绪台阶，在配置范围内决定成片长度",
            ],
            recommended_hook=(
                f"从“{title}”授权原文选中高光的可见后果开场，"
                "隐藏造成后果的最后一个信息。"
            ),
            script_structure=[
                "前10%：高光预示，只展示失控结果或关键动作",
                "10%—25%：必要前因，建立人物目标与关系",
                "25%—50%：冲突连续升级，以行动和对白推进",
                "50%—75%：呈现剧情反转并放大情绪峰值，保留关键对白前、中、后的反应",
                "75%—90%：保留峰值余波和关系变化",
                f"最后10%：停在原文悬念点并给出阅读引导（{config['reading_cta']}）",
            ],
            risks=risks,
            source_scope={
                "domain": "novel",
                "promotion_platform": config["promotion_platform"],
                "authorized_chapters_required": config[
                    "require_authorized_chapters"
                ],
                "highlight_analysis_required": True,
                "highlight_analysis_schema": "novel_highlight_analysis/v1",
                "script_driver": config["script_driver"],
                "available_script_drivers": ["novel_highlight", "reference_video"],
                "video_duration_seconds": {
                    "minimum": config["min_video_seconds"],
                    "default": config["default_video_seconds"],
                    "maximum": config["max_video_seconds"],
                },
            },
        )
