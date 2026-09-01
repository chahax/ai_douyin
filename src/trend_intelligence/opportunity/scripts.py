"""Versioned legal and novel script-brief strategies."""

from __future__ import annotations

import hashlib
from typing import Protocol

from src.operations_accounts import AccountProfile
from src.trend_intelligence.models import (
    ContentOpportunity,
    OpportunityScript,
    ScriptBeat,
)


class DomainScriptStrategy(Protocol):
    domain_strategy_id: str
    strategy_version: str

    def build(
        self,
        profile: AccountProfile,
        opportunity: ContentOpportunity,
        *,
        variant_id: str,
    ) -> OpportunityScript: ...


class DomainScriptStrategyRegistry:
    def __init__(self) -> None:
        self._strategies: dict[tuple[str, str], DomainScriptStrategy] = {}

    def register(self, strategy: DomainScriptStrategy, *, replace: bool = False) -> None:
        key = (strategy.domain_strategy_id, strategy.strategy_version)
        if key in self._strategies and not replace:
            raise ValueError(f"duplicate script strategy: {key[0]}/{key[1]}")
        self._strategies[key] = strategy

    def resolve(self, profile: AccountProfile) -> DomainScriptStrategy:
        try:
            return self._strategies[profile.strategy_key]
        except KeyError as exc:
            raise KeyError(
                f"no script strategy for {profile.domain_strategy_id}/"
                f"{profile.strategy_version}"
            ) from exc


class LegalOpportunityScriptStrategy:
    domain_strategy_id = "legal_services"
    strategy_version = "v1"

    def build(
        self,
        profile: AccountProfile,
        opportunity: ContentOpportunity,
        *,
        variant_id: str,
    ) -> OpportunityScript:
        _validate_binding(profile, opportunity)
        consultation_cta = str(
            profile.domain_config.get("consultation_cta")
            or "具体认定结合证据和个案事实，必要时咨询专业律师"
        )
        title = opportunity.title
        if variant_id == "A":
            beats = [
                ScriptBeat(
                    0,
                    5,
                    "hook",
                    "当事人看到催款、起诉或冲突信息，画面立即定格关键词。",
                    f"遇到{title}，网上那句‘一定怎样’可能少了关键条件。",
                    f"{title}｜先别急着下结论",
                ),
                ScriptBeat(
                    5,
                    10,
                    "rule_boundary",
                    "主体、时间、用途、约定四张信息卡依次出现。",
                    "先核对主体、时间、真实用途和双方约定，再判断规则与例外。",
                    "主体 · 时间 · 用途 · 约定",
                ),
                ScriptBeat(
                    10,
                    15,
                    "evidence_cta",
                    "合同、聊天、转账、通知按时间线排列，结尾出现合规提示。",
                    "把合同、聊天和资金记录按时间整理，别在证据不清时随口承认。",
                    "先留证据｜个案需核验",
                ),
            ]
        else:
            beats = [
                ScriptBeat(
                    0,
                    5,
                    "scenario_hook",
                    "左右分屏：一边是当事人的直觉判断，一边是证据材料。",
                    f"同样是{title}，为什么两个人的处理结果可能完全不同？",
                    "同一问题｜结果为何不同",
                ),
                ScriptBeat(
                    5,
                    10,
                    "fact_gap",
                    "缺失事实被红框标出，随后补上时间、身份和书面材料。",
                    "差别往往不在一句法条，而在关键事实能不能被证据证明。",
                    "事实决定适用｜证据决定证明",
                ),
                ScriptBeat(
                    10,
                    15,
                    "action_list",
                    "三步清单：停止扩大风险、固定证据、核验时效与程序。",
                    "先停损、再固定证据，最后核验时效和处理程序。",
                    "停损 · 固证 · 核验程序",
                ),
            ]
        return _script(
            profile,
            opportunity,
            variant_id=variant_id,
            title=f"{title}｜15秒法律说明 {variant_id}",
            beats=beats,
            cta=consultation_cta,
            source_requirements=[
                "必须使用发布时有效的法律法规、司法解释或权威机关材料。",
                "必须记录适用地域、主体身份、事实前提和检索日期。",
            ],
            fact_checks=[
                "逐句核验一般规则、例外、举证责任和程序时限。",
                "不得把热门视频、评论或标题当作法律依据。",
                "不得承诺胜诉、办案结果或制造确定性恐慌。",
            ],
        )


class NovelOpportunityScriptStrategy:
    domain_strategy_id = "novel_promotion"
    strategy_version = "v1"

    def build(
        self,
        profile: AccountProfile,
        opportunity: ContentOpportunity,
        *,
        variant_id: str,
    ) -> OpportunityScript:
        _validate_binding(profile, opportunity)
        reading_cta = str(
            profile.domain_config.get("reading_cta")
            or "引导在授权平台内搜索书名或继续阅读"
        )
        title = opportunity.title
        if variant_id == "A":
            beats = [
                ScriptBeat(
                    0,
                    5,
                    "conflict_hook",
                    "用授权章节中的最高压关系冲突开场，第一秒显示人物身份落差。",
                    "【主角】被所有人判定出局时，【对手】还不知道真正的底牌已经出现。",
                    f"{title}｜她真的输了？",
                ),
                ScriptBeat(
                    5,
                    10,
                    "escalation",
                    "只展示授权章节已发生的证据、身份或关系变化，不新增剧情事实。",
                    "【对手】刚说完最后一句狠话，现场却出现了谁也解释不了的证据。",
                    "她以为局面已定",
                ),
                ScriptBeat(
                    10,
                    15,
                    "cliffhanger",
                    "脚步、来电或文件停在揭晓前一拍，画面切黑。",
                    "【主角】抬头只说了一句：现在，轮到我问你了。",
                    "反转将在下一秒发生",
                ),
            ]
        else:
            beats = [
                ScriptBeat(
                    0,
                    5,
                    "outcome_first",
                    "先给授权章节中的高能结果画面，再快速回到冲突起点。",
                    "后来他们才知道，今天亲手赶走的人，才是决定结局的那一个。",
                    "他们赶走了最不该得罪的人",
                ),
                ScriptBeat(
                    5,
                    10,
                    "relationship_pressure",
                    "用两到三个近景强化误判、背叛或身份压力。",
                    "【主角】没有解释，只把那份藏了很久的东西放到桌上。",
                    "她不解释，只亮证据",
                ),
                ScriptBeat(
                    10,
                    15,
                    "search_intent",
                    "停在授权章节的原有悬念点，出现书名/平台占位。",
                    "门外的人叫出她真正的身份，全场突然安静。",
                    "书名与授权平台｜待素材绑定",
                ),
            ]
        return _script(
            profile,
            opportunity,
            variant_id=variant_id,
            title=f"{title}｜15秒小说推广 {variant_id}",
            beats=beats,
            cta=reading_cta,
            source_requirements=[
                "绑定目标小说、授权平台、授权章节范围和书名。",
                "将【主角】【对手】等占位符替换为授权原文中的角色与事实。",
                "每个剧情事实必须能回指授权章节，不得凭热门样本补写目标小说情节。",
            ],
            fact_checks=[
                "核对人物关系、身份、证据、事件顺序和悬念点与授权章节一致。",
                "不得泄露核心大结局，不得使用盗版、免费全集或虚假收益引导。",
            ],
        )


def default_script_registry() -> DomainScriptStrategyRegistry:
    registry = DomainScriptStrategyRegistry()
    registry.register(LegalOpportunityScriptStrategy())
    registry.register(NovelOpportunityScriptStrategy())
    return registry


def _script(
    profile: AccountProfile,
    opportunity: ContentOpportunity,
    *,
    variant_id: str,
    title: str,
    beats: list[ScriptBeat],
    cta: str,
    source_requirements: list[str],
    fact_checks: list[str],
) -> OpportunityScript:
    script_id = "script:" + hashlib.sha256(
        "|".join(
            (
                opportunity.opportunity_id,
                profile.domain_strategy_id,
                profile.strategy_version,
                variant_id,
            )
        ).encode("utf-8")
    ).hexdigest()[:24]
    return OpportunityScript(
        script_id=script_id,
        opportunity_id=opportunity.opportunity_id,
        account_uuid=profile.account_uuid,
        domain_strategy_id=profile.domain_strategy_id,
        strategy_version=profile.strategy_version,
        variant_id=variant_id,
        title=title,
        status="draft",
        target_duration_seconds=15.0,
        beats=beats,
        cta=cta,
        source_requirements=source_requirements,
        fact_check_requirements=fact_checks,
        originality_requirements=[
            "热门样本只提供抽象题材、钩子类型、节奏和展示方式，不复制连续表达。",
            "成片镜头、台词、角色视觉和音乐必须重新创作或具有合法授权。",
        ],
        workflow_snapshot={
            "account_profile": f"{profile.account_key}/v{profile.profile_version}",
            "domain_strategy": f"{profile.domain_strategy_id}/{profile.strategy_version}",
            "content_analysis": "selected_at_opportunity_build",
            "presentation": opportunity.recommended_presentation,
            "workflow_profile": opportunity.recommended_workflow_profile,
        },
    )


def _validate_binding(
    profile: AccountProfile, opportunity: ContentOpportunity
) -> None:
    if profile.account_uuid != opportunity.account_uuid:
        raise ValueError("opportunity does not belong to account")
    if profile.profile_version != opportunity.profile_version:
        raise ValueError("opportunity was built from a different account profile version")
    if profile.domain_strategy_id != opportunity.domain_strategy_id:
        raise ValueError("opportunity domain does not match account profile")
