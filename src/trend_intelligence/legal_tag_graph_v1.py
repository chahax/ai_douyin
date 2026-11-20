"""Offline, source-bound legal tag families and observed cooccurrence.

The taxonomy is a conservative retrieval aid, not a legal ontology. No remote
calls, legal conclusions, audiovisual analysis, or accounting mutations occur.
"""
from __future__ import annotations

from collections import defaultdict
from itertools import combinations
import hashlib
import json
import math
from typing import Any

from .tag_graph import normalize_hashtag

SCHEMA = "legal_tag_families_graph/v1"
FAMILY_LABELS = {
    "family:labor": "劳动与用工",
    "family:marriage": "婚姻与家庭",
    "family:contract": "合同与履约",
    "family:debt": "债权与债务",
    "family:tort": "侵权与损害",
    "family:criminal": "刑事与犯罪",
    "family:general": "跨领域法律程序与规则",
}
CAMPAIGN_LABELS = frozenset({
    "抖来普法2026", "抖来学法", "抖音模拟法庭大赛", "创作阶梯计划",
    "秀出我的诉讼策略", "秀出我的诉讼攻略", "青年创作者成长计划",
    "深度理性计划", "真实生活分享计划", "民法温度典护万家",
    "抖音精选app征稿中", "来抖音精选App看天下事", "整点普法新花样",
})
CREATOR_LABELS = frozenset({
    "法律大白", "勤勤恳恳的张法师", "甘律带你掏老板", "郑州汪行",
})
LOCATIONS = frozenset({
    "上海", "北京", "深圳", "成都", "广东", "东莞", "合肥", "武汉",
    "郑州", "娄底", "永州", "缅甸", "滁州", "花岙岛",
})
DOMAIN_GENERIC = frozenset({
    "法律", "律师", "普法", "法律咨询", "律师咨询", "律师普法",
    "法律常识", "法律科普", "每天学点法律知识", "普法宣传", "普法日常",
    "普法小剧场", "普法栏目剧", "案例分享", "法不能向不法让步",
})
GENERIC_NOISE = frozenset({
    "热门", "热点", "上热门", "推荐", "抖音", "douyin", "知识", "分享",
    "干货分享", "经验分享", "真实分享", "直播录屏分享", "媒体原创",
    "万万没想到", "为爱发电", "以小博大", "搭梯子", "电锯惊魂",
    "钓标虾", "写手日常", "华为", "旗舰机型", "高通芯片", "国庆假期",
    "人民日报评", "热点新闻事件", "订酒店", "酒店没房", "赶海",
})
AUDIENCE_CONTEXT = frozenset({
    "职场", "职场PUA", "职场干货", "职场普法", "上班", "老员工",
    "公司", "上市公司", "打工人", "打工人加油", "打工人必看",
    "打工人的合法权益", "打工人的心酸", "外企打工人", "企业经营",
    "中小企业用工", "老百姓关心的话题", "情感", "工作交接",
})
LABOR_ISSUES = frozenset({
    "劳动纠纷", "劳动争议", "劳资纠纷", "辞退", "被辞退", "违法辞退",
    "恶意辞退", "变相辞退", "辞退谈判", "离职", "辞职", "劝退",
    "被迫离职", "被迫辞职", "逼迫离职", "被迫解除", "裁员", "待岗",
    "调岗", "调岗降薪", "降薪", "提供劳动条件", "克扣工资", "拖欠工资",
    "拖欠工资怎么办", "欠薪", "社保", "公积金", "加班费", "工伤",
    "劳务派遣", "外包", "外包退项", "退项", "严重违纪", "不胜任工作",
    "倒查考勤", "孕期被辞退", "用工合规", "用工风险", "负激励",
    "劳动纠纷我支招", "被迫离职怎么操作", "被迫离职要求",
})
LABOR_PROCEDURES = frozenset({
    "劳动仲裁", "在职仲裁", "劳动仲裁开庭", "劳动仲裁时效",
    "劳动仲裁流程怎么走", "劳动仲裁证据", "劳动监察", "劳动维权",
    "被迫离职通知书", "解除劳动合同通知书", "打工维权", "打工人维权",
})
PROCEDURES = frozenset({
    "仲裁", "仲裁开庭", "仲裁流程", "开庭", "开庭准备", "开庭技巧",
    "开庭流程", "起诉", "诉讼", "打官司", "强制执行", "裁决书", "调解书",
    "维护权益", "维权", "投诉", "行政处罚决定", "委托律师",
})
LABOR_OUTCOMES = frozenset({
    "经济补偿", "经济补偿金", "离职补偿", "离职赔偿",
    "辞退赔偿", "裁员补偿", "违法解除2N赔偿金", "双倍工资", "n", "2n",
})
RELATED_GROUPS = {
    "labor_exit": ("被迫离职", "逼迫离职", "被迫辞职", "被迫解除", "离职", "辞职",
                   "辞退", "被辞退", "违法辞退", "变相辞退", "劝退", "裁员"),
    "labor_pay": ("欠薪", "拖欠工资", "克扣工资", "加班费", "双倍工资"),
    "labor_procedure": ("劳动仲裁", "劳动监察", "劳动维权", "劳动仲裁证据",
                        "劳动纠纷", "劳动争议", "劳资纠纷"),
    "labor_compensation": ("经济补偿", "经济补偿金", "离职补偿", "离职赔偿",
                           "辞退赔偿", "违法解除2N赔偿金"),
    "contract_deposits": ("定金", "订金"),
}


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    return value.strip()


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() for x in value):
        raise ValueError(f"{field} must be an array of nonempty strings")
    return value


def _classify(label: str) -> tuple[str, list[str], str, list[str]]:
    """Explicit role rules; never convert metadata into legal equivalence."""
    localities = sorted(location for location in LOCATIONS if label.startswith(location))
    if label in CAMPAIGN_LABELS or label.endswith("创作计划") or label.endswith("征稿中"):
        return "campaign", [], "curated_campaign_label", localities
    if label in LOCATIONS:
        return "location", [], "curated_location_label", [label]
    if label in DOMAIN_GENERIC:
        return "domain_generic", [], "curated_generic_legal_label", localities
    if label in GENERIC_NOISE:
        return "generic_noise", [], "curated_generic_or_unrelated_label", localities
    if label in CREATOR_LABELS:
        return "creator_brand", [], "curated_creator_label", localities
    if label in LABOR_OUTCOMES:
        return "legal_outcome", ["family:labor"], "curated_labor_outcome_retrieval_label", localities
    if "律师" in label or "法师" in label or "律师事务所" in label:
        if label == "委托律师":
            return "legal_procedure", ["family:general"], "curated_engagement_procedure", localities
        return "creator_brand", [], "professional_or_creator_promotion_label", localities
    if label in AUDIENCE_CONTEXT:
        families = [] if label in {"情感", "老百姓关心的话题", "企业经营"} else ["family:labor"]
        return "audience_context", families, "curated_audience_context", localities
    if label in {"劳动法", "劳动合同法", "劳动合同法38条", "劳动法避坑"}:
        return "legal_rule", ["family:labor"], "curated_labor_rule_label", localities
    if label in LABOR_PROCEDURES or any(label.endswith(x) for x in ("劳动仲裁", "劳动仲裁证据")):
        return "legal_procedure", ["family:labor"], "curated_labor_procedure_label", localities
    if label in LABOR_ISSUES or label.endswith("劳动纠纷"):
        return "legal_issue", ["family:labor"], "curated_labor_issue_or_localized_issue", localities
    if label in PROCEDURES:
        return "legal_procedure", ["family:general"], "curated_cross_domain_procedure", localities
    if label in {"赔偿", "赔偿金", "待通知金", "罚款", "仲裁赢了", "一站办结"}:
        return "ambiguous", [], "needs_context_or_original_spelling_review", localities
    if label in {"劳动纠纷法律咨询", "劳动法咨询"}:
        return "domain_generic", ["family:labor"], "domain_consultation_label", localities
    if any(x in label for x in ("离婚", "彩礼", "抚养", "赡养", "恋爱纠纷", "闪婚", "出资买房")):
        role = "legal_procedure" if label == "起诉离婚" else "legal_issue"
        return role, ["family:marriage"], "curated_family_issue_terms", localities
    if label in {"合同", "合同纠纷", "违约", "定金", "订金", "签合同时需要注意什么"}:
        return "legal_issue", ["family:contract"], "curated_contract_issue_terms", localities
    if any(x in label for x in ("债务", "债权", "借款", "欠款", "借条", "还款")):
        return "legal_issue", ["family:debt"], "curated_debt_issue_terms", localities
    if label in {"医美纠纷", "医美风险", "交通事故", "侵权", "名誉", "肖像", "隐私"}:
        return "legal_issue", ["family:tort"], "curated_specific_tort_issue_terms", localities
    if label in {"刑事", "刑事辩护", "计算机犯罪", "非法经营", "刑事立案标准",
                 "抢劫罪怎么判刑", "诈骗罪量刑标准", "枪支管理", "模型枪", "外挂", "强拿硬要"} or label.endswith("罪"):
        role = "legal_rule" if "标准" in label or "判刑" in label else "legal_issue"
        return role, ["family:criminal"], "curated_criminal_issue_or_rule", localities
    if label in {"自首从轻", "退赃退赔", "酌定不起诉"}:
        return "legal_outcome", ["family:criminal"], "curated_criminal_outcome_label", localities
    return "ambiguous", [], "unclassified_metadata_requires_review", localities


def _stats(left: set[str], right: set[str], universe_size: int,
           observed_joint: set[str] | None = None) -> dict[str, float | None]:
    support = len(left & right) if observed_joint is None else len(observed_joint)
    union = len(left) + len(right) - support
    jaccard = support / union if union else 0.0
    lift = (support * universe_size / (len(left) * len(right))) if left and right else None
    if not support:
        npmi = None
    elif support == universe_size:
        npmi = 0.0
    else:
        npmi = math.log(lift) / -math.log(support / universe_size)
    return {"jaccard": round(jaccard, 8),
            "lift": round(lift, 8) if lift is not None else None,
            "npmi": round(npmi, 8) if npmi is not None else None}


def build_graph(source: dict[str, Any]) -> dict[str, Any]:
    """Build a complete deterministic graph from one frozen collection source."""
    if not isinstance(source, dict):
        raise ValueError("source must be an object")
    profile = source.get("account_profile")
    run = source.get("collection_run")
    if not isinstance(profile, dict) or not isinstance(run, dict):
        raise ValueError("source requires account_profile and collection_run")
    account_id = _nonempty(profile.get("account_uuid"), "account_profile.account_uuid")
    version = profile.get("profile_version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError("account profile version must be a positive integer")
    run_id = _nonempty(run.get("run_id"), "collection_run.run_id")
    if run.get("account_uuid") != account_id or run.get("profile_version") != version:
        raise ValueError("collection account/profile binding mismatch")
    opportunity = source.get("opportunity")
    if not isinstance(opportunity, dict):
        raise ValueError("source requires a bound opportunity object")
    for key in ("domain_strategy_id", "strategy_version"):
        expected = _nonempty(profile.get(key), "account_profile." + key)
        if run.get(key) != expected:
            raise ValueError("collection domain strategy binding mismatch")
    for key in ("account_uuid", "profile_version", "domain_strategy_id", "strategy_version"):
        if opportunity.get(key) != profile[key]:
            raise ValueError("opportunity account/profile/strategy binding mismatch")
    if profile.get("account_key") is not None and opportunity.get("account_key") != profile["account_key"]:
        raise ValueError("opportunity account key binding mismatch")
    if run.get("status") != "completed":
        raise ValueError("collection run must be completed")
    observations = source.get("observations")
    if not isinstance(observations, list) or not observations:
        raise ValueError("source requires nonempty observations")
    rows_by_video: dict[str, list[dict[str, Any]]] = defaultdict(list)
    item_video: dict[str, str] = {}
    tag_variants: dict[str, set[str]] = defaultdict(set)
    keyword_videos: dict[str, set[str]] = defaultdict(set)
    keyword_tag_support: dict[tuple[str, str], set[str]] = defaultdict(set)
    keyword_tag_items: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in observations:
        if not isinstance(row, dict) or row.get("run_id") != run_id:
            raise ValueError("observation collection run mismatch")
        for key in ("account_uuid", "profile_version", "domain_strategy_id", "strategy_version"):
            if key in row and row[key] != profile[key]:
                raise ValueError("observation account/profile/strategy binding mismatch")
        item_id = _nonempty(row.get("item_id"), "observation.item_id")
        video_id = _nonempty(row.get("video_id"), "observation.video_id")
        if item_id in item_video and item_video[item_id] != video_id:
            raise ValueError("one item_id maps to conflicting video_ids")
        item_video[item_id] = video_id
        labels = _string_list(row.get("hashtags"), "observation.hashtags")
        normalized = {normalize_hashtag(label) for label in labels}
        if "" in normalized:
            raise ValueError("invalid empty or oversized hashtag")
        for label in labels:
            tag_variants[normalize_hashtag(label)].add(label)
        roots = row.get("root_keywords")
        if roots is None or roots == []:
            roots = [_nonempty(row.get("keyword"), "observation.keyword")]
        else:
            roots = _string_list(roots, "observation.root_keywords")
        for keyword in set(roots):
            keyword = _nonempty(keyword, "keyword")
            keyword_videos[keyword].add(video_id)
            for tag in normalized:
                keyword_tag_support[(keyword, tag)].add(video_id)
                keyword_tag_items[(keyword, tag)].add(item_id)
        rows_by_video[video_id].append(row)

    if "selected_item_ids" in opportunity:
        selected = _string_list(opportunity["selected_item_ids"], "opportunity.selected_item_ids")
        if not set(selected) <= set(item_video):
            raise ValueError("opportunity references items outside this collection")
    documents = []
    tag_videos: dict[str, set[str]] = defaultdict(set)
    authors_by_video: dict[str, set[str]] = {}
    items_by_video: dict[str, set[str]] = {}
    pairs: dict[tuple[str, str], set[str]] = defaultdict(set)
    for video_id, rows in sorted(rows_by_video.items()):
        tags = sorted({normalize_hashtag(tag) for row in rows for tag in row["hashtags"]})
        authors = {row["author"].strip() for row in rows
                   if isinstance(row.get("author"), str) and row["author"].strip()}
        authors_by_video[video_id] = authors
        items_by_video[video_id] = {row["item_id"] for row in rows}
        metrics: dict[str, list[float]] = defaultdict(list)
        for row in rows:
            value = row.get("metric_value")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("non-finite observed metric")
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
                kind = row.get("metric_kind")
                if kind in {"likes", "views"}:
                    metrics[kind].append(value)
        if len(metrics) == 1:
            metric_kind = next(iter(metrics))
            metric_value = min(metrics[metric_kind])
        else:
            metric_kind, metric_value = "unknown", None
        document = {
            "video_id": video_id, "item_ids": sorted(items_by_video[video_id]),
            "author_names": sorted(authors),
            "urls": sorted({row["url"] for row in rows if isinstance(row.get("url"), str) and row["url"]}),
            "titles": sorted({row["title"] for row in rows if isinstance(row.get("title"), str) and row["title"]}),
            "hashtag_labels": tags, "tag_ids": ["tag:" + tag for tag in tags],
            "keywords": sorted({root for row in rows for root in (row.get("root_keywords") or [row["keyword"]])}),
            "metric_kind": metric_kind, "metric_value": metric_value,
            "metric_evidence": [{"metric_kind": kind, "minimum_observed_value": min(values),
                                  "maximum_observed_value": max(values)} for kind, values in sorted(metrics.items())],
        }
        documents.append(document)
        for tag in tags:
            tag_videos[tag].add(video_id)
        for pair in combinations(tags, 2):
            pairs[pair].add(video_id)

    def evidence(videos: set[str]) -> dict[str, Any]:
        authors = {name for video in videos for name in authors_by_video[video]}
        return {"support_video_ids": sorted(videos),
                "support_item_ids": sorted({item for video in videos for item in items_by_video[video]}),
                "support_video_count": len(videos), "visible_author_count": len(authors)}

    nodes = []
    node_by_label = {}
    eligible_roles = {"legal_issue", "legal_procedure", "legal_rule", "legal_outcome", "audience_context"}
    for tag, videos in sorted(tag_videos.items()):
        role, families, basis, localities = _classify(tag)
        support = evidence(videos)
        node = {"tag_id": "tag:" + tag, "label": tag, "raw_labels": sorted(tag_variants[tag]),
                "role": role, "family_ids": families, "classification_basis": basis,
                "locality_facets": localities, **support,
                "creative_eligible": role in eligible_roles and len(videos) >= 2 and support["visible_author_count"] >= 2}
        nodes.append(node)
        node_by_label[tag] = node
    families = []
    for family_id, label in FAMILY_LABELS.items():
        members = [node for node in nodes if family_id in node["family_ids"]]
        videos = {video for node in members for video in node["support_video_ids"]}
        support = evidence(videos)
        families.append({"family_id": family_id, "label": label,
                         "member_tag_ids": sorted(node["tag_id"] for node in members), **support,
                         "classification_basis": "explicit_conservative_retrieval_taxonomy",
                         "creative_eligible_member_count": sum(node["creative_eligible"] for node in members)})

    edges = []
    total = len(documents)
    def add_edge(kind: str, left: str, right: str, videos: set[str], stats: dict[str, Any],
                 eligible: bool, basis: str, **extra: Any) -> None:
        identity = [kind, left, right]
        edges.append({"edge_id": "edge:" + _digest(identity)[:24], "relation_kind": kind,
                      "source": left, "target": right, **evidence(videos), **stats,
                      "creative_eligible": eligible, "relation_basis": basis, **extra})

    for (left, right), videos in sorted(pairs.items()):
        support = evidence(videos)
        eligible = (node_by_label[left]["creative_eligible"] and node_by_label[right]["creative_eligible"]
                    and len(videos) >= 2 and support["visible_author_count"] >= 2)
        add_edge("tag_cooccurrence", "tag:" + left, "tag:" + right, videos,
                 _stats(tag_videos[left], tag_videos[right], total), eligible,
                 "same_video_observed_hashtags")
    for (keyword, tag), videos in sorted(keyword_tag_support.items()):
        support = evidence(videos)
        eligible = node_by_label[tag]["creative_eligible"] and len(videos) >= 2 and support["visible_author_count"] >= 2
        add_edge("keyword_hashtag", "keyword:" + keyword, "tag:" + tag, videos,
                 _stats(keyword_videos[keyword], tag_videos[tag], total, videos), eligible,
                 "observed_query_to_hashtag", source_video_count=len(keyword_videos[keyword]),
                 matched_observation_item_ids=sorted(keyword_tag_items[(keyword, tag)]))
    related_pairs: dict[tuple[str, str], list[str]] = defaultdict(list)
    for group, labels in RELATED_GROUPS.items():
        for pair in combinations(sorted(set(labels) & set(tag_videos)), 2):
            related_pairs[pair].append(group)
    for (left, right), groups in sorted(related_pairs.items()):
        videos = tag_videos[left] & tag_videos[right]
        add_edge("taxonomy_related", "tag:" + left, "tag:" + right, videos,
                 _stats(tag_videos[left], tag_videos[right], total), False,
                 "curated_retrieval_relation_not_synonym_or_legal_equivalence", taxonomy_group_ids=groups)
    edges.sort(key=lambda edge: (edge["relation_kind"], edge["source"], edge["target"]))
    role_counts: dict[str, int] = defaultdict(int)
    edge_counts: dict[str, int] = defaultdict(int)
    for node in nodes:
        role_counts[node["role"]] += 1
    for edge in edges:
        edge_counts[edge["relation_kind"]] += 1
    return {
        "schema": SCHEMA, "source_sha256": _digest(source), "account_id": account_id,
        "account_profile_version": version, "collection_run_id": run_id,
        "documents": documents, "nodes": nodes, "families": families, "edges": edges,
        "keywords": [{"keyword_id": "keyword:" + keyword, "label": keyword,
                      "support_video_ids": sorted(videos), "support_video_count": len(videos)}
                     for keyword, videos in sorted(keyword_videos.items())],
        "summary": {"observation_count": len(observations), "unique_video_count": total,
                    "raw_hashtag_label_count": sum(len(v) for v in tag_variants.values()),
                    "normalized_tag_count": len(nodes), "family_count": len(families),
                    "nonempty_family_count": sum(bool(family["member_tag_ids"]) for family in families),
                    "creative_eligible_tag_count": sum(node["creative_eligible"] for node in nodes),
                    "role_counts": dict(sorted(role_counts.items())), "edge_counts": dict(sorted(edge_counts.items())),
                    "creative_eligible_cooccurrence_count": sum(edge["creative_eligible"] for edge in edges
                                                               if edge["relation_kind"] == "tag_cooccurrence")},
        "eligibility_policy": {"min_support_videos": 2, "min_visible_author_names": 2,
                               "cooccurrence_universe_video_count": total,
                               "synonym_normalization": "orthographic_NFKC_and_ASCII_case_only"},
        "limitations": [
            "标签来自同一批次的标题/页面元数据；未分析原始视频画面、声音或剧情。",
            "titles仅为原始标题的溯源信息，标题中的法律断言或剧情主张未经本模块核验。",
            "标签族由显式、保守的检索规则归类；不宣称自动发现语义或法律概念等价。",
            "同视频共现是观察关系，不证明因果、法律适用、平台总流量或创作质量。",
            "作者多样性按可见名称计算，不代表已核验的独立作者身份。",
            "活动、品牌、地域、泛标签和未分类标签保留在原始图中，不自动成为选题核心。",
            "每视频跨查询去重；点赞和播放不混加；同类重复指标使用最小观测值。",
            "同义处理只合并字形与大小写变体；经济补偿/赔偿、定金/订金、离职/辞退保持不同节点。",
            "单次搜索样本不等于全站热度，稀有标签的高lift不能替代视频数量和作者证据。",
        ],
    }


def validate_graph(graph: dict[str, Any], source: dict[str, Any]) -> None:
    """Reject changed bindings, invented evidence, classifications or statistics."""
    if not isinstance(graph, dict) or graph.get("schema") != SCHEMA:
        raise ValueError("graph schema mismatch")
    if graph.get("source_sha256") != _digest(source):
        raise ValueError("graph source binding changed")
    if graph != build_graph(source):
        raise ValueError("graph differs from deterministic source reconstruction")
