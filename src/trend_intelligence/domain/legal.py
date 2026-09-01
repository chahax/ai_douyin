"""Legal-services operation strategy."""

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


LEGAL_DEFAULT_TERMS = [
    "法律",
    "律师",
    "法院",
    "诉讼",
    "仲裁",
    "婚姻",
    "债务",
    "彩礼",
    "劳动",
    "合同",
    "赔偿",
    "证据",
]


class LegalServicesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    practice_areas: list[str] = Field(default_factory=list)
    consultation_cta: str = "提示结合个案咨询专业律师"
    require_authority_verification: bool = True
    require_case_disclaimer: bool = True


class LegalServicesStrategy(PydanticDomainStrategy):
    strategy_id = "legal_services"
    version = "v1"
    label = "法律服务与律所宣传"
    config_model = LegalServicesConfig

    def build_query_plan(self, profile: AccountProfile) -> DomainQueryPlan:
        config = self.validate_profile(profile)
        roots = unique_terms(
            profile.seed_keywords,
            profile.service_scope,
            config["practice_areas"],
        ) or ["法律科普"]
        related = unique_terms(
            [f"{root} 怎么办" for root in roots],
            [f"{root} 证据" for root in roots],
            [f"{root} 律师" for root in roots],
        )
        return DomainQueryPlan(
            root_keywords=roots,
            related_keywords=related,
            negative_keywords=profile.negative_keywords,
            intent_labels=["法律误区", "证据准备", "处理步骤", "咨询需求"],
            metadata={
                "strategy_id": self.strategy_id,
                "strategy_version": self.version,
                "account_uuid": profile.account_uuid,
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
                reasons=["命中账号排除词，不进入法律账号推荐。"],
            )
        preferred = unique_terms(profile.matching_terms(), LEGAL_DEFAULT_TERMS)
        matched = text_matches(topic.searchable_text, preferred)
        profile_matches = text_matches(topic.searchable_text, profile.matching_terms())
        score = min(100.0, 35.0 + 18.0 * len(matched) + 12.0 * len(profile_matches))
        reasons = (
            [f"命中法律账号主题：{', '.join(matched[:6])}"]
            if matched
            else ["未命中明确法律主题，只保留低相关候选。"]
        )
        return AccountFitEvidence(score=score, matched_terms=matched, reasons=reasons)

    def build_brief_blueprint(
        self,
        profile: AccountProfile,
        topic: DomainTopicContext,
    ) -> DomainBriefBlueprint:
        config = self.validate_profile(profile)
        title = topic.title or "该法律问题"
        risks = [
            "热门样本只用于发现用户关注点，不能作为法律事实或个案结论。",
            "法规时效、适用地域、主体身份和关键事实必须另行核验。",
            "不得承诺胜诉、结果或使用制造恐慌的确定性表达。",
            "不得复制代表视频的完整文案、镜头或独特表达。",
        ]
        if config["require_case_disclaimer"]:
            risks.append("成片需提示具体认定结合证据和个案事实。")
        return DomainBriefBlueprint(
            audience_questions=[
                f"遇到“{title}”时，普通人最容易误解什么？",
                "哪些事实条件会改变处理结果？",
                "需要提前保留什么证据，下一步应做什么？",
            ],
            angles=[
                "规则边界：说明一般规则、例外和适用条件",
                "证据清单：指出决定结果的材料和常见缺口",
                "律师实务：给出合规处理顺序和咨询准备",
            ],
            recommended_hook=(
                f"遇到{title}，先别急着下结论，这三个条件会直接影响处理结果。"
            ),
            script_structure=[
                "0—3秒：具体场景或反常识问题",
                "3—8秒：规则边界与关键例外",
                "8—13秒：证据和处理步骤",
                f"13—15秒：个案提示与合规咨询引导（{config['consultation_cta']}）",
            ],
            risks=risks,
            source_scope={
                "domain": "legal",
                "authority_verification_required": config[
                    "require_authority_verification"
                ],
            },
        )
