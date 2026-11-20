from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from src.trend_intelligence.legal_tag_graph_v1 import build_graph, validate_graph


def source_fixture():
    source = {
        "account_profile": {"account_uuid": "account:legal", "profile_version": 1,
                            "domain_strategy_id": "legal_services", "strategy_version": "v1"},
        "collection_run": {"run_id": "run:1", "account_uuid": "account:legal",
                           "profile_version": 1, "status": "completed",
                           "domain_strategy_id": "legal_services", "strategy_version": "v1"},
        "opportunity": {"title": "offline", "account_uuid": "account:legal", "profile_version": 1,
                        "domain_strategy_id": "legal_services", "strategy_version": "v1"}, "selection_policy": {},
        "observations": [],
    }
    def row(video, author, tags, keyword="法律", metric=100):
        return {"run_id": "run:1", "item_id": "item:" + video, "video_id": video,
                "url": "https://example.com/video/" + video, "title": "未核验原始标题:" + video,
                "author": author, "hashtags": tags, "keyword": keyword,
                "root_keywords": [keyword], "metric_kind": "likes", "metric_value": metric}
    source["observations"] = [
        row("v1", "甲", ["被迫离职", "劳动仲裁", "抖来普法2026"]),
        row("v1", "甲", ["被迫离职", "劳动仲裁", "抖来普法2026"], "被迫离职", 110),
        row("v2", "乙", ["被迫离职", "劳动仲裁"]),
        row("v3", "丙", ["经济补偿", "赔偿金"]),
        row("v4", "甲", ["定金", "订金"]),
    ]
    return source


def node(graph, label):
    return next(x for x in graph["nodes"] if x["label"] == label)


def edge(graph, kind, left, right):
    return next(x for x in graph["edges"] if x["relation_kind"] == kind
                and x["source"] == left and x["target"] == right)


def test_same_video_cross_query_dedup_and_real_pair_statistics():
    source = source_fixture()
    graph = build_graph(source)
    assert graph["summary"]["observation_count"] == 5
    assert graph["summary"]["unique_video_count"] == 4
    assert node(graph, "被迫离职")["support_video_ids"] == ["v1", "v2"]
    assert node(graph, "被迫离职")["support_video_count"] == 2
    assert node(graph, "被迫离职")["visible_author_count"] == 2
    pair = edge(graph, "tag_cooccurrence", "tag:劳动仲裁", "tag:被迫离职")
    assert pair["support_video_ids"] == ["v1", "v2"]
    assert pair["support_item_ids"] == ["item:v1", "item:v2"]
    assert pair["support_video_count"] == 2
    assert pair["jaccard"] == 1.0
    assert pair["lift"] == 2.0
    assert pair["npmi"] == 1.0
    assert pair["creative_eligible"] is True
    query_pair = edge(graph, "keyword_hashtag", "keyword:被迫离职", "tag:劳动仲裁")
    assert query_pair["support_video_ids"] == ["v1"]
    assert query_pair["creative_eligible"] is False
    assert query_pair["matched_observation_item_ids"] == ["item:v1"]
    assert graph["eligibility_policy"]["cooccurrence_universe_video_count"] == 4
    validate_graph(graph, source)


def test_query_membership_does_not_invent_tag_cooccurrence():
    source = source_fixture()
    graph = build_graph(source)
    assert not any(x["relation_kind"] == "tag_cooccurrence"
                   and {x["source"], x["target"]} == {"tag:经济补偿", "tag:被迫离职"}
                   for x in graph["edges"])
    assert all(x["support_video_count"] <= 4 for x in graph["edges"])


def test_roles_keep_campaign_brand_and_ambiguous_labels_but_block_cores():
    source = source_fixture()
    additions = ["法律大白", "勤勤恳恳的张法师", "甘律带你掏老板", "北京劳动律师",
                 "上海", "待通知金", "赔偿", "秀出我的诉讼策略", "普法", "职场",
                 "东莞劳动纠纷", "广东劳动仲裁", "经济补偿律师"]
    for row in source["observations"][:3]:
        row["hashtags"].extend(additions)
    graph = build_graph(source)
    expected = {
        "法律大白": "creator_brand", "勤勤恳恳的张法师": "creator_brand",
        "甘律带你掏老板": "creator_brand", "北京劳动律师": "creator_brand",
        "上海": "location", "待通知金": "ambiguous", "赔偿": "ambiguous",
        "秀出我的诉讼策略": "campaign", "普法": "domain_generic", "职场": "audience_context",
        "东莞劳动纠纷": "legal_issue", "广东劳动仲裁": "legal_procedure",
        "经济补偿律师": "creator_brand",
    }
    for label, role in expected.items():
        assert node(graph, label)["role"] == role
        if role in {"creator_brand", "location", "ambiguous", "campaign", "domain_generic"}:
            assert node(graph, label)["creative_eligible"] is False
    assert node(graph, "东莞劳动纠纷")["locality_facets"] == ["东莞"]
    assert node(graph, "东莞劳动纠纷")["family_ids"] == ["family:labor"]
    assert node(graph, "赔偿")["family_ids"] == []
    assert node(graph, "待通知金")["label"] == "待通知金"
    assert not any(x["label"] == "代通知金" for x in graph["nodes"])


def test_only_orthographic_variants_merge_not_legal_concepts():
    source = source_fixture()
    source["observations"][0]["hashtags"].extend(["＃ＡBC", "abc", "被迫解除", "逼迫离职", "辞职", "辞退"])
    graph = build_graph(source)
    assert node(graph, "abc")["raw_labels"] == ["abc", "＃ＡBC"]
    for label in ["经济补偿", "赔偿金", "定金", "订金", "被迫解除", "逼迫离职", "辞职", "辞退"]:
        assert node(graph, label)["label"] == label
    related = edge(graph, "taxonomy_related", "tag:定金", "tag:订金")
    assert related["creative_eligible"] is False
    assert related["relation_basis"] == "curated_retrieval_relation_not_synonym_or_legal_equivalence"
    assert not any(x["relation_kind"] == "taxonomy_related"
                   and {x["source"], x["target"]} == {"tag:经济补偿", "tag:赔偿金"}
                   for x in graph["edges"])


def test_two_videos_from_same_visible_author_do_not_pass_diversity():
    source = source_fixture()
    source["observations"][2]["author"] = "甲"
    graph = build_graph(source)
    assert node(graph, "被迫离职")["support_video_count"] == 2
    assert node(graph, "被迫离职")["visible_author_count"] == 1
    assert node(graph, "被迫离职")["creative_eligible"] is False
    assert edge(graph, "tag_cooccurrence", "tag:劳动仲裁", "tag:被迫离职")["creative_eligible"] is False


def test_families_are_unique_video_sets_and_metrics_are_not_summed_across_queries():
    source = source_fixture()
    graph = build_graph(source)
    family = next(x for x in graph["families"] if x["family_id"] == "family:labor")
    assert family["support_video_ids"] == ["v1", "v2", "v3"]
    assert family["support_video_count"] == 3
    assert family["visible_author_count"] == 3
    doc = next(x for x in graph["documents"] if x["video_id"] == "v1")
    assert doc["metric_kind"] == "likes" and doc["metric_value"] == 100
    assert doc["titles"] == ["未核验原始标题:v1"]
    source["observations"][1]["metric_kind"] = "views"
    mixed = next(x for x in build_graph(source)["documents"] if x["video_id"] == "v1")
    assert mixed["metric_kind"] == "unknown" and mixed["metric_value"] is None
    assert {x["metric_kind"] for x in mixed["metric_evidence"]} == {"likes", "views"}


@pytest.mark.parametrize("mutation", ["wrong_run", "wrong_account", "wrong_version", "unfinished", "item_conflict", "string_hashtags", "wrong_strategy", "wrong_opportunity", "nonfinite"])
def test_rejects_mixed_run_account_and_malformed_metadata(mutation):
    source = source_fixture()
    if mutation == "wrong_run":
        source["observations"][0]["run_id"] = "other"
    elif mutation == "wrong_account":
        source["collection_run"]["account_uuid"] = "account:other"
    elif mutation == "wrong_version":
        source["collection_run"]["profile_version"] = 2
    elif mutation == "unfinished":
        source["collection_run"]["status"] = "awaiting_attention"
    elif mutation == "item_conflict":
        source["observations"][1]["video_id"] = "different"
    elif mutation == "string_hashtags":
        source["observations"][0]["hashtags"] = "劳动仲裁"
    elif mutation == "wrong_strategy":
        source["collection_run"]["strategy_version"] = "v2"
    elif mutation == "wrong_opportunity":
        source["opportunity"]["account_uuid"] = "account:other"
    elif mutation == "nonfinite":
        source["observations"][0]["metric_value"] = float("nan")
    with pytest.raises(ValueError):
        build_graph(source)


@pytest.mark.parametrize("mutation", ["support", "classification", "title", "statistic", "source"])
def test_complete_reconstruction_rejects_invented_or_changed_graph(mutation):
    source = source_fixture()
    graph = build_graph(source)
    if mutation == "support":
        graph["nodes"][0]["support_video_ids"].append("invented")
    elif mutation == "classification":
        graph["nodes"][0]["role"] = "legal_issue"
    elif mutation == "title":
        graph["documents"][0]["titles"] = ["changed"]
    elif mutation == "statistic":
        graph["edges"][0]["lift"] = 999
    elif mutation == "source":
        source["opportunity"]["title"] = "changed candidate"
    with pytest.raises(ValueError):
        validate_graph(graph, source)


def test_reproducible_without_mutating_source():
    source = source_fixture()
    original = deepcopy(source)
    graph = build_graph(source)
    assert graph == build_graph(source)
    assert source == original
    assert graph["source_sha256"] == hashlib.sha256(json.dumps(source, ensure_ascii=False,
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    reversed_source = deepcopy(source)
    reversed_source["observations"].reverse()
    reversed_graph = build_graph(reversed_source)
    for section in ["nodes", "edges", "families", "documents"]:
        assert graph[section] == reversed_graph[section]
    assert graph["source_sha256"] != reversed_graph["source_sha256"]


def test_actual_fresh_batch_is_complete_traceable_and_read_only():
    path = Path("data/qa/legal_new_batch_script_flow_20261007/round_02/creative_source/TREND_SOURCE.json")
    before = path.read_bytes()
    source = json.loads(before.decode("utf-8-sig"))
    graph = build_graph(source)
    validate_graph(graph, source)
    assert graph["summary"]["observation_count"] == 287
    assert graph["summary"]["unique_video_count"] == 154
    assert graph["summary"]["raw_hashtag_label_count"] == 255
    assert graph["summary"]["normalized_tag_count"] == 255
    assert graph["account_id"] == "account:9e5f9e75192fa45becb945bc"
    assert graph["collection_run_id"] == "4406d5c2451a4b599a5e802a1c065a33"
    assert graph["summary"]["edge_counts"]["tag_cooccurrence"] > 0
    assert graph["summary"]["edge_counts"]["keyword_hashtag"] == 335
    videos = {row["video_id"] for row in source["observations"]}
    assert all(set(node["support_video_ids"]) <= videos for node in graph["nodes"])
    assert all(set(edge["support_video_ids"]) <= videos for edge in graph["edges"])
    assert node(graph, "被迫离职")["support_video_count"] == 14
    assert node(graph, "劳动仲裁")["support_video_count"] > 40
    assert node(graph, "抖来普法2026")["role"] == "campaign"
    assert node(graph, "法律大白")["role"] == "creator_brand"
    assert node(graph, "经济补偿律师")["role"] == "creator_brand"
    assert path.read_bytes() == before


def test_query_edge_statistics_use_observed_query_tag_joint_not_union_inferred_tags():
    source = source_fixture()
    source["observations"] = source["observations"][:3]
    source["observations"][0]["hashtags"] = ["劳动仲裁"]
    source["observations"][0]["keyword"] = "法律"
    source["observations"][0]["root_keywords"] = ["法律"]
    source["observations"][1]["hashtags"] = ["被迫离职"]
    source["observations"][1]["keyword"] = "被迫离职"
    source["observations"][1]["root_keywords"] = ["被迫离职"]
    source["observations"][2]["hashtags"] = ["劳动仲裁", "被迫离职"]
    graph = build_graph(source)
    observed = edge(graph, "keyword_hashtag", "keyword:法律", "tag:被迫离职")
    assert observed["support_video_ids"] == ["v2"]
    assert observed["jaccard"] == pytest.approx(1 / 3, abs=1e-8)
    assert observed["lift"] == 0.5
    assert observed["npmi"] == -1.0
