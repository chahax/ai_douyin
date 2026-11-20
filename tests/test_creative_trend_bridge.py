"""Meaningful offline gates for tag-to-original-story preparation."""
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import pytest
from jsonschema import ValidationError

from src.operations_accounts.models import AccountProfile
from src.content_factory.creative_brief import normalize_brief
from src.content_factory.creative_story_emotion import digest
from src.content_factory.creative_trend_bridge import (
    build_packet, build_direction_preview, build_writer_preview,
    validate_direction, validate_complete_story, render_selection_review, WRITER_CRITERIA)
from scripts.prepare_trend_creative_workflow import prepare, write_bundle

NOW = "2026-10-07T04:00:00+00:00"
ROOT = Path(__file__).resolve().parents[1]
STANDARDS = ROOT / "data/qa/loneliness_vs_current_story_20261007/round_03_knowledge_standards/EXPRESSION_STANDARDS_v1.json"
REFERENCE = ROOT / "data/reference_reviews/reusable_expression_20261001/EXPRESSION_REFERENCE.md"


def source_fixture():
    profile = asdict(AccountProfile("offline:sample", "offline-sample", "emotion_original",
        target_audiences=["成年职场观众"], seed_keywords=["职场边界", "自我选择"],
        negative_keywords=["保证胜诉"]))
    bound = {k: profile[k] for k in ("account_uuid", "profile_version", "domain_strategy_id", "strategy_version")}
    return {"account_profile": profile, "collection_run": {**bound, "run_id": "offline-batch", "status": "completed"},
        "opportunity": {**bound, "account_key": profile["account_key"], "opportunity_id": "offline-opportunity",
            "title": "职场边界", "status": "candidate", "selected_item_ids": [f"i{i}" for i in range(20)],
            "topic_labels": ["主动选择"], "recommended_duration_seconds": 15,
            "valid_from": "2026-10-07T00:00:00+00:00", "valid_until": "2026-10-08T00:00:00+00:00",
            "risks": ["不得保证胜诉"]},
        "observations": [{"run_id": "offline-batch", "item_id": f"i{i}", "video_id": f"v{i}",
            "title": "模拟样本，仅用于离线测试", "keyword": "职场边界" if i % 2 else "自我选择",
            "hashtags": ["职场"], "metric_value": 60_000, "metric_kind": "views",
            "collected_at": "2026-10-07T03:00:00+00:00"} for i in range(20)],
        "selection_policy": {"tag_scope": "account_positioning", "max_sample_age_hours": 72}}


def packet_fixture(source=None):
    return build_packet(source or source_fixture(), REFERENCE.read_text(encoding="utf-8"),
                        json.loads(STANDARDS.read_text(encoding="utf-8")), now=NOW)


def direction_fixture(packet, *, family=False):
    return {"schema": "trend_story_direction/v1", "packet_sha256": digest(packet),
        "creative_brief": {"schema": "creative_brief/v1", "title": "这次我来决定",
            "theme": "亲子选择" if family else "职场边界", "audience": "成年观众", "relationships": "母亲与成年女儿" if family else "同事关系",
            "audience_emotion": "被理解后释放", "visual_style": "克制写实", "turn": "短暂劝留后坚持自己的选择",
            "ending": "对方认领责任，主人公完成自己的安排", "duration_seconds": [60, 100],
            "duration_policy": "flexible", "constraints": ["不争吵，不夸大胜利"], "avoid": ["不要保证胜诉", "不照搬样片"]},
        "emotional_brief": {"audience_goal": "松一口气", "pressure": "对方的习惯性要求", "choice": "明确自己的安排",
            "consequence": "对方接回任务", "release": "主人公得到可见的放松", "creative_limits": ["克制真实"]},
        "account_fit": {"reason": "在账号情绪短剧定位内讨论明确选择", "proposed_format": "写实短剧"},
        "characters": [{"name": "小周", "goal": "完成自己的安排"}, {"name": "小李", "goal": "请求帮助"}],
        "tag_choices": [{"tag_id": packet["tag_catalog"][0]["tag_id"], "story_relevance": "让习惯性关系面对一次清晰选择"}]}


def confirmation_fixture(packet, direction):
    # This is a simulated test receipt, never a production user approval.
    return {"decision": "approved", "source": "user_message", "message_id": "simulated-test-only",
        "user_statement": "模拟确认，仅用于离线测试", "packet_sha256": digest(packet),
        "direction_sha256": digest(direction), "confirmed_at": NOW}


def test_source_evidence_reference_and_role_boundaries():
    packet = packet_fixture()
    request = build_direction_preview(packet, now=NOW)
    context = json.loads(request["messages"][1]["content"])
    assert context["reference_fulltext"] == REFERENCE.read_text(encoding="utf-8")
    assert {c["id"] for c in context["writer_expression_criteria"]} == set(WRITER_CRITERIA)
    assert {r["kind"] for r in context["tag_catalog"]} == {"observed_hashtag", "primary_query", "opportunity_topic_proposal"}
    assert packet["sample_gate"]["unique_videos"] == 20
    assert packet["sample_gate"]["total_views"] == 1_200_000
    assert "not_growth" in packet["heat_claim"]
    assert request["submitted"] is False and request["automatic_retry"] is False
    assert request["dispatch_allowed"] is False


@pytest.mark.parametrize("field", ["account_uuid", "profile_version", "domain_strategy_id", "strategy_version"])
@pytest.mark.parametrize("container", ["collection_run", "opportunity"])
def test_cross_account_and_version_refused(field, container):
    source = source_fixture(); source[container][field] = "other"
    with pytest.raises(ValueError, match="binding mismatch"):
        packet_fixture(source)


@pytest.mark.parametrize("fault", ["mixed_batch", "missing_item", "duplicate_item", "identity_conflict", "future_time", "untyped_hashtags"])
def test_source_contract_faults_refused(fault):
    source = source_fixture()
    if fault == "mixed_batch": source["observations"][0]["run_id"] = "other"
    elif fault == "missing_item": source["opportunity"]["selected_item_ids"].append("missing")
    elif fault == "duplicate_item": source["opportunity"]["selected_item_ids"].append("i0")
    elif fault == "identity_conflict": source["observations"].append(dict(source["observations"][0], video_id="changed"))
    elif fault == "future_time": source["observations"][0]["collected_at"] = "2027-01-01T00:00:00+00:00"
    else: source["observations"][0]["hashtags"] = "职场"
    with pytest.raises(ValueError): packet_fixture(source)


@pytest.mark.parametrize("fault,blocker", [("pending_scope", "tag_scope_not_confirmed"), ("stale", "sample_stale"),
    ("expired", "opportunity_outside_validity"), ("inactive", "account_profile_inactive"),
    ("rejected", "opportunity_not_eligible"), ("unknown_metric", "sample_gate_failed"),
    ("mixed_metrics", "sample_gate_failed"), ("deduplicated", "sample_gate_failed"),
    ("negative_title", "account_negative_keyword_match")])
def test_gate_failures_readable_but_no_request(fault, blocker):
    source = source_fixture()
    if fault == "pending_scope": source["selection_policy"]["tag_scope"] = "pending"
    elif fault == "stale": source["observations"][0]["collected_at"] = "2026-09-01T00:00:00+00:00"
    elif fault == "expired": source["opportunity"]["valid_until"] = "2026-10-07T01:00:00+00:00"
    elif fault == "inactive": source["account_profile"]["status"] = "paused"
    elif fault == "rejected": source["opportunity"]["status"] = "rejected"
    elif fault == "negative_title": source["observations"][0]["title"] = "保证胜诉"
    elif fault == "deduplicated": source["observations"][0]["video_id"] = "v1"
    elif fault == "mixed_metrics":
        for row in source["observations"][:10]: row["metric_kind"] = "likes"
    else:
        for row in source["observations"]: row["metric_kind"] = "displayed_unknown"
    packet = packet_fixture(source)
    assert blocker in packet["blockers"] and blocker in render_selection_review(packet)
    with pytest.raises(ValueError, match="preview blocked"): build_direction_preview(packet, now=NOW)


def test_tag_support_deduplicated_by_video():
    source = source_fixture(); source["observations"].append(deepcopy(source["observations"][0]))
    packet = packet_fixture(source)
    hashtag = next(r for r in packet["tag_catalog"] if r["kind"] == "observed_hashtag")
    assert hashtag["supporting_unique_videos"] == 20
    assert packet["sample_gate"]["total_views"] == 1_200_000


@pytest.mark.parametrize("change", ["title", "reference", "blockers"])
def test_frozen_packet_tampering_refused(change):
    packet = packet_fixture()
    if change == "title": packet["inputs"]["source"]["opportunity"]["title"] = "modified"
    elif change == "reference": packet["inputs"]["reference_fulltext"] = "shortened"
    else: packet["blockers"] = ["invented"]
    with pytest.raises(ValueError, match="changed"): build_direction_preview(packet, now=NOW)


def test_freshness_rechecked_before_writer_not_just_packet_time():
    packet = packet_fixture(); direction = direction_fixture(packet)
    with pytest.raises(ValueError, match="outside_validity"):
        build_writer_preview(packet, direction, confirmation_fixture(packet, direction), now="2026-10-09T04:00:00+00:00")


@pytest.mark.parametrize("fault", ["missing", "changed_direction", "wrong_packet", "no_statement", "not_user"])
def test_human_direction_confirmation_required(fault):
    packet = packet_fixture(); direction = direction_fixture(packet); confirmation = confirmation_fixture(packet, direction)
    if fault == "missing": confirmation = None
    elif fault == "changed_direction": direction["creative_brief"]["ending"] = "changed ending"
    elif fault == "wrong_packet": confirmation["packet_sha256"] = "wrong"
    elif fault == "no_statement": confirmation["user_statement"] = ""
    else: confirmation["source"] = "model_review"
    with pytest.raises(ValueError, match="confirmation required"):
        build_writer_preview(packet, direction, confirmation, now=NOW)


@pytest.mark.parametrize("fault", ["invented_tag", "duplicate_character", "blank_relationship", "wrong_packet"])
def test_invalid_direction_cannot_become_script(fault):
    packet = packet_fixture(); direction = direction_fixture(packet)
    if fault == "invented_tag": direction["tag_choices"][0]["tag_id"] = "invented"
    elif fault == "duplicate_character": direction["characters"][1]["name"] = "小周"
    elif fault == "blank_relationship": direction["creative_brief"]["relationships"] = " "
    else: direction["packet_sha256"] = "wrong"
    with pytest.raises((ValueError, ValidationError)): validate_direction(direction, packet)


def test_generic_writer_preserves_entire_brief_and_changed_genre():
    requests = []
    for family in (False, True):
        source = source_fixture()
        if family:
            source["account_profile"]["seed_keywords"] = ["亲子选择", "自我选择"]
            source["opportunity"]["title"] = "亲子选择"
            for row in source["observations"]:
                if row["keyword"] == "职场边界": row["keyword"] = "亲子选择"
                row["hashtags"] = ["亲子"]
        packet = packet_fixture(source)
        direction = direction_fixture(packet, family=family)
        request = build_writer_preview(packet, direction, confirmation_fixture(packet, direction), now=NOW)
        context = json.loads(request["messages"][1]["content"])
        assert context["creative_brief"] == direction["creative_brief"]
        assert context["reference_fulltext"] == REFERENCE.read_text(encoding="utf-8")
        assert normalize_brief(context["creative_brief"])["duration_policy"] == "flexible"
        assert request["submitted"] is False and request["dispatch_allowed"] is False
        assert "方澄" not in request["messages"][0]["content"]
        requests.append(request)
    assert requests[0]["context_sha256"] != requests[1]["context_sha256"]


def test_story_local_constraints_visible_in_tool_schema():
    packet = packet_fixture(); direction = direction_fixture(packet)
    request = build_writer_preview(packet, direction, confirmation_fixture(packet, direction), now=NOW)
    schema = request["tool_definition"]["function"]["parameters"]
    story = {"title": "完整正文示例", "premise": "事件推进", "selected_candidate_id": schema["properties"]["selected_candidate_id"]["const"],
        "beats": [{"id": "E1", "event": "明确选择", "trigger": "同伴询问", "steps": [
            {"kind": "action", "speaker": "", "text": "小周停下，面对小李。"},
            {"kind": "dialogue", "speaker": "小周", "text": "这次我来决定。"}]}]}
    assert validate_complete_story(story, direction)["creative_quality_passed"] is False
    for step_index, wrong_speaker in ((0, "小周"), (1, "未确认人物")):
        bad = deepcopy(story); bad["beats"][0]["steps"][step_index]["speaker"] = wrong_speaker
        with pytest.raises(ValidationError): validate_complete_story(bad, direction)
    bad = deepcopy(story); bad["beats"].append(deepcopy(bad["beats"][0]))
    with pytest.raises(ValueError, match="duplicate beat"): validate_complete_story(bad, direction)


def test_cli_preparation_immutable_replay_and_no_source_mutation(tmp_path):
    source = tmp_path / "source.json"; source.write_text(json.dumps(source_fixture(), ensure_ascii=False), encoding="utf-8")
    before = source.read_bytes()
    values = prepare(source, REFERENCE, STANDARDS, now=NOW)
    out = tmp_path / "out"; write_bundle(out, values); write_bundle(out, values)
    assert source.read_bytes() == before
    assert values["EVIDENCE.json"]["model_calls"] == 0
    changed = deepcopy(values); changed["SOURCE_PACKET.json"]["status"] = "forged"
    changed["new.txt"] = "must not be written when preflight fails"
    with pytest.raises(ValueError, match="different output"): write_bundle(out, changed)
    assert not (out / "new.txt").exists()


def test_account_scope_and_site_wide_are_distinct_proposals():
    source = source_fixture()
    source["account_profile"]["seed_keywords"] = ["完全不相关定位"]
    source["account_profile"]["target_audiences"] = []
    packet = packet_fixture(source)
    assert "account_topic_fit_unverified" in packet["blockers"]
    source["selection_policy"]["tag_scope"] = "site_wide"
    packet = packet_fixture(source)
    assert "account_topic_fit_unverified" not in packet["blockers"]


def test_forbidden_content_format_not_relabelled_as_account_fit():
    source = source_fixture(); source["account_profile"]["allowed_formats"] = ["写实短剧"]
    packet = packet_fixture(source); direction = direction_fixture(packet)
    direction["account_fit"]["proposed_format"] = "产品广告"
    with pytest.raises(ValueError, match="content format"):
        validate_direction(direction, packet)


def test_saved_source_packet_roundtrip_can_prepare_exact_confirmed_writer():
    packet=json.loads(json.dumps(packet_fixture()))
    direction=direction_fixture(packet)
    preview=build_writer_preview(packet,direction,confirmation_fixture(packet,direction),now=NOW)
    assert preview["submitted"] is False
