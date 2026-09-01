"""Deterministic content-form and account-relevance classification helpers."""

from __future__ import annotations

from src.operations_accounts import AccountProfile
from src.trend_intelligence.domain import (
    DomainStrategyRegistry,
    DomainTopicContext,
    get_default_domain_registry,
)
from src.trend_intelligence.models import AccountContentRelevance, ContentEvidence


PRESENTATION_TERMS = {
    "talking_head": ["律师", "告诉你", "科普", "解读", "口播", "讲解"],
    "story_drama": ["重生", "复仇", "订婚", "妹妹", "未婚夫", "第1集", "第一集"],
    "screen_recording": ["聊天记录", "转账", "账单", "截图", "录屏", "判决书"],
    "text_cards": ["清单", "三步", "3步", "注意事项", "盘点", "合集"],
    "interview": ["采访", "连线", "咨询", "问律师", "街访"],
}


def classify_presentation(text: str) -> tuple[str, list[str]]:
    normalized = (text or "").lower()
    matched = {
        kind: [term for term in terms if term.lower() in normalized]
        for kind, terms in PRESENTATION_TERMS.items()
    }
    matched = {kind: values for kind, values in matched.items() if values}
    if not matched:
        return "unknown", ["仅有元数据，无法确认画面展示方式"]
    ordered = sorted(matched.items(), key=lambda item: len(item[1]), reverse=True)
    presentation = ordered[0][0] if len(ordered) == 1 else "mixed"
    features = [f"{kind}:{'、'.join(values)}" for kind, values in ordered]
    return presentation, features


def classify_hook(text: str) -> tuple[str, str]:
    value = (text or "").strip()
    head = value[:80]
    if any(term in head for term in ("吗", "怎么", "为什么", "？", "?")):
        return "question", head
    if any(term in head for term in ("却", "没想到", "不一定", "反而", "直到")):
        return "contrast", head
    if any(term in head for term in ("抢", "背叛", "逾期", "起诉", "离婚", "清算")):
        return "conflict", head
    if any(term in head for term in ("结果", "真相", "结局", "当场", "终于")):
        return "outcome_first", head
    return "statement", head


def score_account_relevance(
    profile: AccountProfile,
    *,
    title: str,
    hashtags: list[str],
    content_text: str,
    evidence: list[ContentEvidence],
    registry: DomainStrategyRegistry | None = None,
) -> AccountContentRelevance:
    active_registry = registry or get_default_domain_registry()
    strategy = active_registry.resolve(profile)
    topic = DomainTopicContext(
        title=title,
        keywords=list(profile.seed_keywords),
        representative_titles=[content_text[:500]],
        hashtags=list(hashtags),
        sample_count=1,
    )
    domain_fit = strategy.score_account_fit(profile, topic)
    searchable = " ".join((title, content_text, *hashtags)).lower()
    seed_matches = [
        term for term in profile.seed_keywords if term.lower() in searchable
    ]
    profile_matches = [
        term for term in profile.matching_terms() if term.lower() in searchable
    ]
    direct_coverage = len(set(seed_matches + profile_matches)) / max(
        1, len(set(profile.seed_keywords + profile.matching_terms()))
    )
    score = 0.7 * domain_fit.score + 30 * min(1.0, direct_coverage)
    if domain_fit.excluded_terms:
        score = 0.0
    relevant_evidence = [
        item
        for item in evidence
        if any(
            term.lower() in item.text.lower()
            for term in set(seed_matches + profile_matches + domain_fit.matched_terms)
        )
    ][:8]
    confidence = min(
        1.0,
        0.35
        + 0.1 * len(relevant_evidence)
        + 0.08 * len(seed_matches)
        + (0.15 if content_text and content_text != title else 0.0),
    )
    reasons = list(domain_fit.reasons)
    if seed_matches:
        reasons.append(f"命中账号种子词：{'、'.join(seed_matches)}")
    if not relevant_evidence:
        reasons.append("未找到带时间或通道的直接相关证据，相关度置信度受限。")
    return AccountContentRelevance(
        score=round(max(0.0, min(100.0, score)), 2),
        confidence=round(confidence, 3),
        matched_seed_keywords=seed_matches,
        matched_profile_terms=profile_matches,
        matched_topic_terms=list(domain_fit.matched_terms),
        excluded_terms=list(domain_fit.excluded_terms),
        reasons=reasons,
        evidence=relevant_evidence,
    )
