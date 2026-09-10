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
        focus, subject_title = _legal_subject(profile, opportunity)
        if variant_id == "A":
            beats = _legal_variant_a_beats(focus)
        else:
            beats = [
                ScriptBeat(
                    0,
                    5,
                    "scenario_hook",
                    "左右分屏：一边是当事人的直觉判断，一边是证据材料。",
                    f"同样是{focus}，为什么处理结果可能完全不同？",
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
            title=f"{subject_title}｜15秒法律说明 {variant_id}",
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


LEGAL_SCOPE_ALIASES = {
    "婚姻家事": ("婚姻", "离婚", "夫妻", "抚养", "家事"),
    "劳动争议": ("劳动", "工资", "加班", "工伤", "辞退", "离职", "工作群"),
    "合同纠纷": ("合同", "违约", "合作方"),
    "债权债务": ("债权", "债务", "欠款", "借款", "还款"),
    "交通事故": ("交通事故", "车祸", "事故责任"),
}


def _legal_subject(
    profile: AccountProfile,
    opportunity: ContentOpportunity,
) -> tuple[str, str]:
    """Prefer an account service line over a broad or unrelated trend title."""
    primary_corpus = " ".join([opportunity.title, *opportunity.topic_labels])
    evidence_corpus = " ".join(opportunity.evidence)
    configured = list(
        profile.domain_config.get("practice_areas") or profile.service_scope
    )
    titles = {
        "婚姻家事": "婚姻纠纷咨询：先准备哪三类证据？",
        "劳动争议": "劳动争议维权：先准备哪三类证据？",
        "合同纠纷": "合同纠纷处理：先准备哪三类证据？",
        "债权债务": "债务纠纷处理：先准备哪三类证据？",
        "交通事故": "交通事故处理：先准备哪三类证据？",
    }
    for corpus in (primary_corpus, evidence_corpus):
        for area in configured:
            normalized = str(area or "").strip()
            aliases = LEGAL_SCOPE_ALIASES.get(normalized, (normalized,))
            if any(alias and alias in corpus for alias in aliases):
                return normalized, titles.get(normalized, f"{normalized}：先准备哪些证据？")
    fallback = opportunity.title.strip() or "法律问题"
    return fallback, f"{fallback}：先核对事实与证据"


def _legal_variant_a_beats(focus: str) -> list[ScriptBeat]:
    if focus == "婚姻家事":
        lines = (
            ("婚姻纠纷先别只争对错，证据才能还原事实。", "婚姻纠纷｜先固定证据"),
            ("保存聊天、转账和财产线索，再按时间排序。", "聊天 · 转账 · 财产线索"),
            ("然后核对诉求与期限，个案应结合证据判断。", "核诉求 · 看期限 · 做判断"),
        )
    elif focus == "劳动争议":
        lines = (
            ("被辞退先别只靠口头争论，证据决定能否证明。", "劳动争议｜先固定证据"),
            ("保存合同、考勤、工资记录和解除通知。", "合同 · 考勤 · 工资 · 通知"),
            ("然后核对仲裁时效，个案应结合事实判断。", "看时效｜个案需核验"),
        )
    elif focus == "合同纠纷":
        lines = (
            ("合同起争议，先别只截一张聊天记录。", "合同纠纷｜证据要成链"),
            ("保存合同原件、履行记录、付款和往来沟通。", "合同 · 履行 · 付款 · 沟通"),
            ("再核对违约事实与期限，个案应结合证据判断。", "核违约 · 看期限"),
        )
    elif focus == "债权债务":
        lines = (
            ("对方欠钱不还，先别只拿一张转账截图。", "债务纠纷｜证据要成链"),
            ("保存借款合意、资金交付和催款记录。", "合意 · 交付 · 催款"),
            ("再核对主体与期限，个案应结合证据判断。", "核主体 · 看期限"),
        )
    elif focus == "交通事故":
        lines = (
            ("事故发生后，先别只顾着争谁对谁错。", "交通事故｜先固定现场"),
            ("保存现场影像、认定材料、病历和费用凭证。", "现场 · 认定 · 病历 · 票据"),
            ("再核对责任与损失，个案应结合证据判断。", "核责任 · 算损失"),
        )
    else:
        lines = (
            (f"遇到{focus}，先别急着相信确定性结论。", f"{focus}｜先别急着下结论"),
            ("先核对主体、时间、真实事实和书面材料。", "主体 · 时间 · 事实 · 材料"),
            ("再整理证据和诉求，个案应由专业律师判断。", "先固证｜个案需核验"),
        )
    visuals = (
        "冲突关键词立即定格，右侧出现证据文件夹。",
        "证据卡片依次进入时间线，重要字段高亮。",
        "三步清单落版，结尾显示个案核验提示。",
    )
    roles = ("hook", "evidence_list", "evidence_cta")
    return [
        ScriptBeat(index * 5, (index + 1) * 5, roles[index], visuals[index], line, caption)
        for index, (line, caption) in enumerate(lines)
    ]


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
