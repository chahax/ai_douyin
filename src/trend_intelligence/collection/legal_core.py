"""One legal core tag, evidence-bound neighbours and a bounded new collection request.

Pure preparation: historical associations can seed new searches, never prove current heat.
"""
from __future__ import annotations
from collections import defaultdict
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import hashlib
import json
import math

from src.operations_accounts.models import AccountProfile
from src.trend_intelligence.domain.legal import LEGAL_DEFAULT_TERMS, LegalServicesStrategy
from src.trend_intelligence.providers.base import TrendCollectionRequest
from src.trend_intelligence.sample_gate import evaluate_sample, VIEW_KINDS, LIKE_KINDS
from src.trend_intelligence.tag_graph import normalize_hashtag, GENERIC_EXPANSION_TAGS

VERSION = "legal_core_topic_plan/v1"
# Search vocabulary, not legal rules or an authoritative legal taxonomy.
LEGAL_SEARCH_FAMILIES = {
    "劳动": ("劳动", "工资", "加班", "离职", "辞退", "裁员", "社保", "工伤", "年假"),
    "婚姻": ("婚姻", "离婚", "夫妻", "彩礼", "抚养", "赡养", "结婚"),
    "合同": ("合同", "违约", "租赁", "定金", "订金", "买卖", "履约"),
    "债务": ("债务", "债权", "借款", "欠钱", "欠款", "还款", "借条", "催收"),
    "侵权": ("侵权", "赔偿", "交通事故", "损害", "名誉", "肖像", "隐私"),
    "刑事": ("刑事", "刑法", "犯罪", "诈骗", "盗窃", "拘留", "取保"),
}
GENERIC_LEGAL_TAGS = {"法律", "律师", "法律科普", "普法", "法律知识", "法律咨询"}
NOISE_TAGS = GENERIC_EXPANSION_TAGS | {"抖音小助手", "正能量", "热点新闻", "每日分享", "dou+"}


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def _time(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timezone-aware timestamp required")
    return result.astimezone(timezone.utc)


def legal_related_terms(profile: AccountProfile) -> tuple[str, ...]:
    if profile.domain_strategy_id != "legal_services":
        raise ValueError("legal account profile required")
    LegalServicesStrategy().validate_profile(profile)
    terms = [*LEGAL_DEFAULT_TERMS, "普法", *profile.seed_keywords, *profile.service_scope,
             *profile.domain_config.get("practice_areas", [])]
    terms += [t for family in LEGAL_SEARCH_FAMILIES.values() for t in family]
    return tuple(sorted({t.strip() for t in terms if isinstance(t, str) and t.strip()}))


def legal_topic_tag_exclusion(tag):
    """Separate issue tags from generic/creator promotion; lexical heuristic only."""
    value = normalize_hashtag(tag)
    if value in NOISE_TAGS or value in GENERIC_LEGAL_TAGS:
        return "generic_or_promotional"
    if "律师" in value and not any(t in value for t in ("律师费", "委托律师", "请律师", "找律师", "律师执业")):
        return "creator_or_location_brand_tag"
    return ""


def _jaccard(left, right):
    return len(left & right) / max(1, len(left | right))


def build_legal_core_plan(profile, observations, core_tag, *, now,
                          max_related_tags=4, min_support_videos=2,
                          min_unique_authors=2, max_sample_age_hours=72, max_pages=30):
    """Prepare one same-batch follow-up; do not blend old observations into new heat."""
    terms = legal_related_terms(profile)
    core = normalize_hashtag(core_tag)
    if not core or core in NOISE_TAGS or any(t.casefold() in core.casefold() for t in profile.negative_keywords):
        raise ValueError("invalid core tag")
    aliases = {t for family in LEGAL_SEARCH_FAMILIES.values() if any(t in core for t in family) for t in family}
    if not any(t.casefold() in core.casefold() for t in terms):
        raise ValueError("core tag has no legal-domain evidence")
    for value in (min_support_videos, min_unique_authors, max_sample_age_hours, max_pages):
        if type(value) is not int or value < 1:
            raise ValueError("positive integer collection bounds required")
    if type(max_related_tags) is not int or not 0 <= max_related_tags <= 6:
        raise ValueError("related tag count must be 0..6")
    current = _time(now)
    rows = [asdict(r) if is_dataclass(r) else dict(r) for r in observations]
    run_ids = {r.get("run_id", "") for r in rows}
    if rows and (len(run_ids) != 1 or "" in run_ids):
        raise ValueError("one identified source batch required")
    if any(not r.get("video_id") or not r.get("item_id") for r in rows):
        raise ValueError("source video/item identity required")
    captured = [_time(r["collected_at"]) for r in rows]
    if any(t > current for t in captured):
        raise ValueError("future source observation")
    identity_map = {}
    for row in rows:
        identity = identity_map.setdefault(row["item_id"], row["video_id"])
        if identity != row["video_id"]:
            raise ValueError("conflicting source identity")
    by_video = defaultdict(list)
    for row in rows:
        by_video[row["video_id"]].append(row)
    documents = {}
    for video_id, entries in sorted(by_video.items()):
        tags = {normalize_hashtag(t) for r in entries for t in r.get("hashtags", [])}
        tags.discard("")
        text = " ".join([*[r.get("title", "") for r in entries], *sorted(tags)]).casefold()
        authors = sorted({r.get("author", "").strip() for r in entries if r.get("author", "").strip()})
        legal = any(t.casefold() in text for t in terms)
        excluded = any(t.casefold() in text for t in profile.negative_keywords)
        if core in GENERIC_LEGAL_TAGS:
            anchored = legal  # General legal core covers the account's visible legal topics.
        else:
            anchored = core.casefold() in text or any(t.casefold() in text for t in aliases)
        valid_ranks = [r["rank"] for r in entries if type(r.get("rank")) is int and r["rank"] > 0]
        documents[video_id] = {"tags": tags, "legal": legal and not excluded,
            "anchored": anchored and legal and not excluded, "author": authors[0] if authors else "",
            "rank": min(valid_ranks) if valid_ranks else None,
            "item_ids": sorted({r["item_id"] for r in entries}), "entries": entries}
    anchored_docs = {v: d for v, d in documents.items() if d["anchored"]}
    counts = defaultdict(set)
    all_counts = defaultdict(set)
    for v, doc in documents.items():
        for tag in doc["tags"]:
            all_counts[tag].add(v)
            if doc["anchored"]:
                counts[tag].add(v)
    candidates = []
    n_all, n_core = len(documents), len(anchored_docs)
    for tag, support_ids in sorted(counts.items()):
        authors = {anchored_docs[v]["author"] for v in support_ids if anchored_docs[v]["author"]}
        reasons = []
        if tag == core: reasons.append("same_as_core")
        exclusion = legal_topic_tag_exclusion(tag)
        if exclusion: reasons.append(exclusion)
        if not any(t.casefold() in tag.casefold() for t in terms): reasons.append("legal_tag_meaning_unverified")
        if any(t.casefold() in tag.casefold() for t in profile.negative_keywords): reasons.append("excluded_term")
        if len(support_ids) < min_support_videos: reasons.append("insufficient_unique_video_support")
        if len(authors) < min_unique_authors: reasons.append("insufficient_author_name_diversity")
        coverage = len(support_ids) / max(1, n_core)
        p_joint = len(support_ids) / max(1, n_all)
        lift = (coverage / (len(all_counts[tag]) / max(1, n_all))) if all_counts[tag] else 0
        npmi = math.log(lift) / -math.log(p_joint) if lift > 0 and 0 < p_joint < 1 else 0.0
        rank_strength = sum(1 / math.log2(anchored_docs[v]["rank"] + 1)
            for v in support_ids if anchored_docs[v]["rank"] is not None) / len(support_ids)
        score = 100 * (0.5 * coverage + 0.2 * min(1, len(authors) / len(support_ids))
                       + 0.2 * max(0, npmi) + 0.1 * rank_strength)
        candidates.append({"tag": tag, "support_video_ids": sorted(support_ids),
            "supporting_item_ids": sorted({i for v in support_ids for i in anchored_docs[v]["item_ids"]}),
            "support_unique_videos": len(support_ids), "author_display_names": sorted(authors),
            "core_coverage": round(coverage, 6), "lift": round(lift, 6), "npmi": round(npmi, 6),
            "relation_score": round(score, 4), "rejection_reasons": reasons, "selected": False})
    eligible = [c for c in candidates if not c["rejection_reasons"]]
    selected = []
    while eligible and len(selected) < max_related_tags:
        def diversity_score(candidate):
            overlap = max((_jaccard(set(candidate["support_video_ids"]), set(old["support_video_ids"]))
                           for old in selected), default=0)
            return 0.75 * candidate["relation_score"] - 25 * overlap
        chosen = sorted(eligible, key=lambda c: (-diversity_score(c), c["tag"]))[0]
        chosen["diversity_selection_score"] = round(diversity_score(chosen), 4)
        chosen["selected"] = True
        selected.append(chosen); eligible.remove(chosen)
    keywords = [core, *[c["tag"] for c in selected]]
    sorts = ("comprehensive", "most_liked", "latest")
    estimated_pages = len(keywords) * len(sorts)
    if estimated_pages > max_pages:
        raise ValueError("same-batch plan exceeds page cap; never silently split a sample batch")
    request = TrendCollectionRequest(keywords=keywords, sorts=sorts, limit_per_sort=20,
        expand_related_tags=False, related_tag_domain="legal_services", related_tag_filter_terms=terms,
        related_tag_excluded_terms=tuple(profile.negative_keywords),
        min_related_tag_support_videos=min_support_videos, min_related_tag_unique_authors=min_unique_authors)
    age = (current - min(captured)).total_seconds() / 3600 if captured else None
    gate = evaluate_sample(rows)
    blockers = ["fresh_same_batch_collection_and_analysis_required"]
    if not gate.passed: blockers.append("source_sample_gate_incomplete")
    if age is None or age > max_sample_age_hours: blockers.append("source_sample_stale_or_missing")
    if not selected: blockers.append("related_tag_evidence_insufficient")
    if profile.status != "active": blockers.append("account_inactive")
    metrics = {}
    for kind, accepted in (("views", VIEW_KINDS), ("likes", LIKE_KINDS)):
        valid_per_video = [[r["metric_value"] for r in d["entries"]
            if r.get("metric_kind") in accepted and type(r.get("metric_value")) is int and r["metric_value"] >= 0]
            for d in anchored_docs.values()]
        metrics[kind] = {"confirmed_total": sum(min(vals) for vals in valid_per_video if vals),
                         "missing_unique_videos": sum(not vals for vals in valid_per_video)}
    inputs = {"profile": asdict(profile), "core_tag": core, "observations": rows,
        "bounds": {"max_related_tags": max_related_tags, "min_support_videos": min_support_videos,
            "min_unique_authors": min_unique_authors, "max_sample_age_hours": max_sample_age_hours, "max_pages": max_pages}}
    return {"schema": VERSION, "plan_id": "legal-core:" + _hash({"inputs": inputs, "created_at": now})[:24], "created_at": now,
        "account_uuid": profile.account_uuid, "account_key": profile.account_key,
        "profile_version": profile.profile_version, "domain_strategy_id": profile.domain_strategy_id,
        "strategy_version": profile.strategy_version, "core_tag": core, "inputs": inputs,
        "source_sha256": _hash(inputs), "source_run_id": next(iter(run_ids)) if run_ids else "",
        "source_unique_videos": n_all, "core_legal_unique_videos": n_core,
        "candidates": candidates, "related_tags": [c["tag"] for c in selected],
        "collection_request": asdict(request), "estimated_pages": estimated_pages,
        "source_sample_gate": gate.to_dict(), "source_age_hours": age, "typed_metric_evidence": metrics,
        "creative_handoff_blockers": blockers, "status": "collection_plan_prepared_not_executed",
        "association_basis": "visible_legal_metadata_and_direct_cooccurrence_not_semantic_model_or_causal_proof",
        "diversity_basis": "MMR_style_with_support_set_Jaccard_not_KeyBERT_embeddings",
        "author_identity_basis": "display_names_only_not_verified_creator_ids",
        "source_role": "historical_association_seeds_to_revalidate_in_new_batch",
        "current_hot_topic_verified": False, "submitted": False, "automatic_retry": False}


def request_from_legal_core_plan(plan, profile, *, headless=False, manual_verification_seconds=0):
    """Validate the frozen plan and actual account before any browser operation."""
    if plan.get("schema") != VERSION or profile.status != "active":
        raise ValueError("active legal core plan/account required")
    inputs = plan["inputs"]
    if inputs["profile"] != asdict(profile):
        raise ValueError("core plan belongs to different or changed account strategy")
    rebuilt = build_legal_core_plan(profile, inputs["observations"], inputs["core_tag"],
        now=plan["created_at"], **inputs["bounds"])
    if _hash(plan) != _hash(rebuilt):
        raise ValueError("core plan source or derived request changed")
    values = dict(rebuilt["collection_request"])
    for key in ("sorts", "related_tag_filter_terms", "related_tag_excluded_terms"):
        values[key] = tuple(values[key])
    values.update(headless=headless, web_crawler_enabled=True,
                  manual_verification_timeout_seconds=manual_verification_seconds)
    return TrendCollectionRequest(**values)
