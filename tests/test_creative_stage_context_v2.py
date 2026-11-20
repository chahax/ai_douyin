from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from src.content_factory.creative_stage_context_v2 import (
    ContextError, build_stage_context,
)


def sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


@pytest.fixture
def inputs():
    prior = {"title": "旧故事", "beats": [{"id": "b1", "text": "未签的纸被收回"}]}
    return {
        "source_packet": {
            "schema": "creative_compact_legal_context/v1/source_packet",
            "collection_run": {"run_id": "batch-1", "finished_at": "2026-10-12T15:41:14+00:00"},
            "account_profile": {"domain_strategy_id": "legal_services", "max_characters": 2},
            "source_identity": {"source_binding_sha256": "a" * 64,
                                "source_packet_semantic_sha256": "b" * 64,
                                "metadata_only_not_law_or_real_case": True},
            "candidate": {"candidate_id": "tag-issue:1", "family_id": "family:labor",
                          "anchor_tag_id": "tag:labor", "selected_item_ids": ["douyin:1", "douyin:2"],
                          "support_video_ids": ["1", "2"], "support_video_count": 2,
                          "related_tags": [{"tag_id": "tag:wage", "relation_kind": "observed_same_video_not_legal_equivalence"}]},
            "tag_catalog": [{"tag_id": "tag:labor", "label": "劳动争议", "family_ids": ["family:labor"],
                             "role": "legal_issue", "item_ids": ["douyin:1", "douyin:2"],
                             "support_video_ids": ["1", "2"], "supporting_unique_videos": 2},
                            {"tag_id": "tag:wage", "label": "工资", "family_ids": ["family:labor"],
                             "role": "legal_issue", "item_ids": ["douyin:1"],
                             "support_video_ids": ["1"], "supporting_unique_videos": 1}],
            "selected_relations": [{"edge_id": "edge:1", "source": "tag:labor", "target": "tag:wage",
                                    "relation_kind": "tag_cooccurrence", "support_video_count": 2,
                                    "support_video_ids": ["1", "2"], "support_item_ids": ["douyin:1", "douyin:2"]}],
            "selected_tag_families": [{"family_id": "family:labor", "selected_member_tag_ids": ["tag:labor"],
                                       "support_count_scope": "whole_batch_family_not_selected_candidate"}],
            "representative_metadata": [{"item_id": "douyin:1", "video_id": "1", "run_id": "batch-1",
                                         "title": "工资问题", "author": "甲", "hashtags": ["劳动争议"],
                                         "metric_value": 120, "metric_kind": "likes", "source_observation_sha256": "c" * 64}],
            "whole_batch_summary": {"selected_family_count": 7}, "sample_gate": {"passed": True},
            "projection_policy": {"old_projection": True}, "limitations": ["元数据并非视频内容"],
        },
        "verified_legal_context": {"sources": [{"url": "https://example.test/law"}],
                                   "facts": [{"id": "law1", "text": "规则只在满足关系认定条件时适用", "condition": "关系须另行认定"}]},
        "reference_fulltext": "R01完整参考：观察刺激，给反应时间。\n参考用于机制，不复制人物与剧情。",
        "expression_standards": {"criteria": {"causality": "刺激与回应", "ending": "场内选择"}},
        "production_preferences": {"language": "普通话", "no_subtitles": True, "whole_film_max_seconds": 180,
                                   "max_characters": 2, "prior_story_scope": {"prior_script_sha256": sha(prior),
                                                                            "full_prior_script": prior,
                                                                            "director_used": 7, "director_limit": 7,
                                                                            "director_remaining": 0}},
        "user_goal_contract": {"must_have": ["具体诉求", "阻力", "可见场内后果"]},
        "native_goal_document": {"status": "synthetic_offline_fixture", "local_consequence": "选择发生改变"},
        "brief": {"characters": [{"id": "a"}, {"id": "b"}], "facts": [{"id": "law1", "text": "条件原文保留"}]},
        "creative_scene_plan": {"beats": [{"id": "b1", "attempt": "索取记录", "opposition": "拒绝提供"}]},
        "full_current_script": {"title": "离线样例", "beats": [{"id": "b1", "steps": [{"kind": "dialogue", "text": "请把记录给我。"}]}]},
        "evidence_catalog": {"E0001": {"text": "请把记录给我。", "kind": "dialogue"}},
        "review_criteria": {"ending_consequence": "结尾回应本场诉求"},
    }


@pytest.mark.parametrize("stage", ["goal_plan", "complete_script", "full_review"])
def test_each_stage_retains_complete_reference_law_and_standards_without_mutation(inputs, stage):
    original = deepcopy(inputs)
    result = build_stage_context(stage, inputs)
    p, m = result["payload"], result["manifest"]
    assert inputs == original
    assert p["reference_fulltext"] == original["reference_fulltext"]
    assert p["verified_legal_context"] == original["verified_legal_context"]
    assert p["expression_standards"] == original["expression_standards"]
    assert m["reference_proof"]["payload_occurrences"] == 1
    assert m["actual_provider_tokens"] is None
    assert m["client_constructed"] is m["dispatch_performed"] is False


def test_goal_planning_does_not_receive_old_locked_brief_or_complete_plan(inputs):
    result = build_stage_context("goal_plan", inputs)
    assert "brief" not in result["payload"]
    assert "creative_scene_plan" not in result["payload"]
    assert {"brief", "creative_scene_plan", "full_current_script"} <= {
        row["path"] for row in result["manifest"]["field_manifest"] if row["disposition"] == "omitted"}


def test_writer_keeps_native_goal_brief_and_plan_exact(inputs):
    p = build_stage_context("complete_script", inputs)["payload"]
    for key in ("native_goal_document", "brief", "creative_scene_plan"):
        assert p[key] == inputs[key]
    assert "full_current_script" not in p


def test_review_is_bound_to_every_byte_of_current_full_script(inputs):
    result = build_stage_context("full_review", inputs)
    assert result["payload"]["full_current_script"] == inputs["full_current_script"]
    assert result["manifest"]["full_current_script_sha256"] == sha(inputs["full_current_script"])
    changed = deepcopy(inputs)
    changed["full_current_script"]["beats"][0]["steps"][0]["text"] += "我现在就要。"
    assert build_stage_context("full_review", changed)["manifest"]["full_current_script_sha256"] != result["manifest"]["full_current_script_sha256"]


def test_source_projection_preserves_selected_item_identities_and_real_metadata(inputs):
    result = build_stage_context("complete_script", inputs)
    s = result["payload"]["source_packet"]
    original = inputs["source_packet"]
    assert s["candidate"]["selected_item_ids"] == original["candidate"]["selected_item_ids"]
    assert s["representative_metadata"] == original["representative_metadata"]
    assert s["source_identity"] == original["source_identity"]
    assert result["manifest"]["source_projection_input_sha256"] == sha(original)
    assert result["manifest"]["source_freshness_or_sample_gate_revalidated"] is False


def test_tag_and_edge_projection_keep_counts_and_original_row_sha(inputs):
    s = build_stage_context("complete_script", inputs)["payload"]["source_packet"]
    assert s["tag_observations"][0]["supporting_unique_videos"] == 2
    assert s["selected_relations"][0]["support_video_count"] == 2
    assert s["tag_observations"][0]["source_row_sha256"] == sha(inputs["source_packet"]["tag_catalog"][0])
    assert s["selected_relations"][0]["source_row_sha256"] == sha(inputs["source_packet"]["selected_relations"][0])
    assert "support_video_ids" not in s["tag_observations"][0]
    assert "support_item_ids" not in s["selected_relations"][0]


def test_repeated_support_lists_are_explicitly_omitted_in_manifest(inputs):
    m = build_stage_context("complete_script", inputs)["manifest"]
    omitted = {row["path"] for row in m["field_manifest"] if row["disposition"] == "omitted"}
    assert "source_packet.candidate.support_video_ids" in omitted
    assert "source_packet.tag_catalog/0.item_ids" in omitted
    assert "source_packet.selected_relations/0.support_item_ids" in omitted
    assert "source_packet.sample_gate" in omitted


def test_old_story_allowance_and_hash_survive_without_repeated_full_story(inputs):
    result = build_stage_context("complete_script", inputs)
    scope = result["payload"]["production_preferences"]["prior_story_scope"]
    assert scope["director_remaining"] == 0
    assert scope["director_used"] == scope["director_limit"] == 7
    assert scope["prior_script_sha256"] == inputs["production_preferences"]["prior_story_scope"]["prior_script_sha256"]
    assert "full_prior_script" not in scope
    assert result["manifest"]["lineage_gate_status"] == "separate_gate_required_before_any_candidate_dispatch"
    assert result["manifest"]["authorization_changed"] is result["manifest"]["allowance_reset"] is False


def test_prior_full_story_hash_mismatch_is_rejected(inputs):
    inputs["production_preferences"]["prior_story_scope"]["full_prior_script"]["title"] = "改了"
    with pytest.raises(ContextError, match="identity differ"):
        build_stage_context("complete_script", inputs)


def test_content_revision_retains_complete_native_previous_version_and_diagnostics(inputs):
    previous = {"title": "完整失败稿", "beats": [{"id": "b1", "steps": [{"kind": "dialogue", "text": "原句完整"}]}]}
    inputs.update(previous_complete_document=previous, revision_diagnostics={"issues": [{"ref": "b1", "error": "缺少回应"}]})
    result = build_stage_context("complete_script", inputs)
    assert result["payload"]["previous_complete_document"] == previous
    assert result["payload"]["revision_diagnostics"] == inputs["revision_diagnostics"]
    assert result["manifest"]["generation_mode"] == "bounded_content_revision"


def test_initial_generation_does_not_invent_revision_mode(inputs):
    result = build_stage_context("complete_script", inputs)
    assert "previous_complete_document" not in result["payload"]
    assert result["manifest"]["generation_mode"] == "initial_generation"


def test_review_omits_previous_full_version_and_diagnostics_with_recorded_reason(inputs):
    inputs.update(previous_complete_document={"title": "之前"}, revision_diagnostics={"error": "之前的失效诊断"})
    result = build_stage_context("full_review", inputs)
    assert "previous_complete_document" not in result["payload"]
    assert "revision_diagnostics" not in result["payload"]
    omitted = {row["path"]: row["reason"] for row in result["manifest"]["field_manifest"] if row["disposition"] == "omitted"}
    assert "previous_complete_document" in omitted
    assert "revision_diagnostics" in omitted


def test_revision_without_complete_previous_native_version_stops(inputs):
    inputs["revision_diagnostics"] = {"error": "无新稿"}
    with pytest.raises(ContextError, match="complete native previous"):
        build_stage_context("complete_script", inputs)


def test_revision_without_diagnostics_stops(inputs):
    inputs["previous_complete_document"] = {"title": "完整旧稿"}
    with pytest.raises(ContextError, match="explicit nonempty diagnostics"):
        build_stage_context("complete_script", inputs)


def test_explicit_legacy_diagnostic_alias_maps_without_loss(inputs):
    inputs.update(previous_complete_document={"title": "真实旧稿"},
                  complete_script_feasibility_diagnostics={"dialogue_rows": [{"ref": "E1", "characters": 49}]},
                  revision_requirements=[{"target": "complete_native_script", "requirement": "完整重写"}])
    result = build_stage_context("complete_script", inputs)
    assert result["payload"]["revision_diagnostics"] == inputs["complete_script_feasibility_diagnostics"]
    assert result["payload"]["revision_requirements"] == inputs["revision_requirements"]


def test_competing_diagnostic_sources_are_not_silently_chosen(inputs):
    inputs.update(revision_diagnostics={"error": "A"}, complete_script_feasibility_diagnostics={"error": "B"})
    with pytest.raises(ContextError, match="competing"):
        build_stage_context("complete_script", inputs)


def test_unknown_input_field_is_not_silently_discarded(inputs):
    inputs["unexpected_context"] = "未分配的上下文"
    with pytest.raises(ContextError, match="unmapped fields"):
        build_stage_context("complete_script", inputs)


def test_unknown_source_field_is_not_silently_discarded(inputs):
    inputs["source_packet"]["unclassified_payload"] = {"secret": "新数据"}
    with pytest.raises(ContextError, match="source_packet has unmapped"):
        build_stage_context("complete_script", inputs)


def test_missing_stage_full_script_is_rejected(inputs):
    del inputs["full_current_script"]
    with pytest.raises(ContextError, match="requires full_current_script"):
        build_stage_context("full_review", inputs)


def test_duplicate_reference_nested_in_retained_plan_stops(inputs):
    inputs["creative_scene_plan"]["copied_reference"] = "重复前缀：" + inputs["reference_fulltext"]
    with pytest.raises(ContextError, match="exactly once"):
        build_stage_context("complete_script", inputs)


def test_explicit_budget_stops_without_truncating_full_script(inputs):
    original = deepcopy(inputs["full_current_script"])
    inputs["context_policy"] = {"max_payload_characters": 20, "max_payload_utf8_bytes": 100}
    with pytest.raises(ContextError, match="no content truncated"):
        build_stage_context("full_review", inputs)
    assert inputs["full_current_script"] == original


def test_unicode_measurement_reports_real_bytes_without_claiming_tokens(inputs):
    result = build_stage_context("full_review", inputs)
    encoded = json.dumps(result["payload"], ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    assert result["manifest"]["payload_identity"]["characters"] == len(encoded)
    assert result["manifest"]["payload_identity"]["utf8_bytes"] == len(encoded.encode("utf-8"))
    assert result["manifest"]["payload_identity"]["utf8_bytes"] > result["manifest"]["payload_identity"]["characters"]
    assert result["manifest"]["token_estimate_performed"] is False


def test_unbound_metadata_identity_is_rejected(inputs):
    inputs["source_packet"]["representative_metadata"][0]["item_id"] = "douyin:other"
    with pytest.raises(ContextError, match="identity must be unique and selected"):
        build_stage_context("complete_script", inputs)


def test_future_director_stage_is_not_claimed_as_supported(inputs):
    with pytest.raises(ContextError, match="separate contracts"):
        build_stage_context("director", inputs)


def test_cross_batch_representative_metadata_is_rejected(inputs):
    inputs["source_packet"]["representative_metadata"][0]["run_id"] = "old-batch"
    with pytest.raises(ContextError, match="exact video and collection run"):
        build_stage_context("complete_script", inputs)


def test_duplicate_selected_tag_identity_is_rejected(inputs):
    inputs["source_packet"]["tag_catalog"].append(deepcopy(inputs["source_packet"]["tag_catalog"][0]))
    with pytest.raises(ContextError, match="tag identities must be unique"):
        build_stage_context("complete_script", inputs)


def test_unmapped_relation_endpoint_is_rejected(inputs):
    inputs["source_packet"]["selected_relations"][0]["target"] = "tag:invented"
    with pytest.raises(ContextError, match="endpoints must map"):
        build_stage_context("complete_script", inputs)


def test_actual_529_source_projection_has_one_full_r01_and_retains_all_selected_ids(inputs):
    root = Path(__file__).resolve().parents[1]
    receipt = root / "data/production_trials/m31_flash_script_test_20261013/round_01/call_529_m31_complete_script_01.json"
    if not receipt.exists():
        pytest.skip("immutable actual receipt not in this checkout")
    old = json.loads(receipt.read_text(encoding="utf-8"))
    actual = json.loads(old["request"]["messages"][1]["content"])
    for key in ("source_packet", "verified_legal_context", "reference_fulltext", "expression_standards", "production_preferences"):
        inputs[key] = actual[key]
    result = build_stage_context("goal_plan", inputs)
    assert len(result["payload"]["reference_fulltext"]) == 2313
    assert result["payload"]["source_packet"]["candidate"]["selected_item_ids"] == actual["source_packet"]["candidate"]["selected_item_ids"]
    assert len(result["payload"]["source_packet"]["representative_metadata"]) == 6
    assert result["manifest"]["payload_identity"]["characters"] < len(old["request"]["messages"][1]["content"])
