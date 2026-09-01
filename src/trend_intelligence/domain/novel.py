"""Novel-promotion operation strategy."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

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
                "前三秒应先展示人物困境、背叛还是高能结果？",
                "在哪个反转前断开最容易形成搜索或追更意图？",
            ],
            angles=[
                "悬念钩子：先给高风险结果，再回到冲突起点",
                "人设爽点：突出身份落差、误判和反击",
                "情绪回报：围绕委屈、背叛、反转和清算推进",
            ],
            recommended_hook=(
                f"所有人都以为她会输，直到“{title}”背后的秘密被当众揭开。"
            ),
            script_structure=[
                "0—3秒：身份、背叛或危险结果",
                "3—8秒：主角困境和关键关系",
                "8—13秒：证据、身份或局势反转",
                f"13—15秒：停在回报前并给出阅读引导（{config['reading_cta']}）",
            ],
            risks=risks,
            source_scope={
                "domain": "novel",
                "promotion_platform": config["promotion_platform"],
                "authorized_chapters_required": config[
                    "require_authorized_chapters"
                ],
            },
        )
