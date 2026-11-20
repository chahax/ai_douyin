"""Isolated contracts for local account → novel selection; no paid calls."""
import copy
import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.content_factory.account_novel_selection_v1 import discover_books, select_target_novel
from src.operations_accounts.models import AccountProfile
from src.trend_intelligence.models import ContentOpportunity

NOW = datetime(2026, 10, 16, 4, tzinfo=timezone.utc)


@pytest.fixture
def profile():
    return AccountProfile(account_uuid="account:novel", account_key="novel", domain_strategy_id="novel_promotion",
                          seed_keywords=["校园"], negative_keywords=["后宫"], domain_config={"genres": ["恋爱"]})


@pytest.fixture
def opportunity(profile):
    return ContentOpportunity(
        opportunity_id="chance1", account_uuid=profile.account_uuid, account_key=profile.account_key,
        profile_version=1, domain_strategy_id="novel_promotion", strategy_version="v1", cluster_id="cluster1",
        brief_id="brief1", title="校园恋爱高光", status="candidate", opportunity_score=80,
        score_breakdown={}, selected_item_ids=[], recommended_presentation="剧情", recommended_hook_type="悬念",
        recommended_pacing="自然", recommended_duration_seconds=90, recommended_publish_window="待定",
        recommended_workflow_profile="novel", topic_labels=["校园"],
        valid_from="2026-10-16T00:00:00+00:00", valid_until="2026-10-17T00:00:00+00:00")


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def book(root, book_id="1", name="校园恋爱", *, authorized=True, body=None, categories=None):
    folder = root / book_id
    folder.mkdir(parents=True)
    material = folder / "material.txt"
    material.write_bytes((body or "第1章 初遇\n她走进校园，抬头看着他。").encode("utf-8"))
    meta = {"book_id": book_id, "book_name": name, "abstract": name, "categories": categories or ["校园", "恋爱"],
            "chapters_fetched": 20, "total_chapters_seen": 100, "source_url": "https://example.test/book/" + book_id}
    write_json(folder / "meta.json", meta)
    if authorized:
        write_json(folder / "text_authorization.json", {
            "book_id": book_id, "source_sha256": hashlib.sha256(material.read_bytes()).hexdigest(),
            "allow_text_adaptation": True, "allow_model_input": True, "reference": "测试夹具明确文本许可"})
    return folder


def select(profile, opportunity, root, **kwargs):
    return select_target_novel(profile, opportunity, discover_books(root), now=NOW, **kwargs)


def test_discovery_and_deterministic_selection_with_bound_source(tmp_path, profile, opportunity):
    book(tmp_path, "b", name="校园初恋")
    book(tmp_path, "a", name="校园初恋")
    result = select(profile, opportunity, tmp_path)
    selected = result["selected_book"]
    assert result["schema"] == "account_novel_selection/v1"
    assert result["status"] == "selected"
    assert selected["book_id"] == "a"
    assert Path(selected["material_path"]).is_absolute()
    assert selected["metadata"]["book_id"] == "a"
    assert selected["acquisition_scope"]["observed_chapters"] == 1
    assert selected["acquisition_scope"]["chapters_fetched_reported"] == 20
    assert selected["acquisition_scope"]["partial_source"] is True
    assert result["account"] == asdict(profile)
    assert result["opportunity"] == asdict(opportunity)
    result["account"]["seed_keywords"].append("mutation")
    assert "mutation" not in profile.seed_keywords


def test_explicit_target_cannot_bypass_qualification(tmp_path, profile, opportunity):
    book(tmp_path, "a")
    book(tmp_path, "b", authorized=False)
    result = select(profile, opportunity, tmp_path, target_book_id="b")
    assert result["selected_book"] is None
    assert result["status"] == "needs_materials"
    assert select(profile, opportunity, tmp_path, target_book_id="a")["selected_book"]["book_id"] == "a"


def test_no_candidates_and_missing_root(tmp_path, profile, opportunity):
    assert discover_books(tmp_path / "absent") == []
    assert select(profile, opportunity, tmp_path)["status"] == "needs_materials"


def test_no_matching_book_does_not_take_first(tmp_path, profile, opportunity):
    book(tmp_path, name="悬疑推理", categories=["刑侦"])
    result = select(profile, opportunity, tmp_path)
    assert result["status"] == "no_matching_book"
    assert result["selected_book"] is None
    assert "no_opportunity_match" in result["rankings"][0]["exclusion_reasons"]


def test_negative_keyword_exclusion_even_explicit_target(tmp_path, profile, opportunity):
    book(tmp_path, name="校园后宫恋爱")
    result = select(profile, opportunity, tmp_path, target_book_id="1")
    assert result["selected_book"] is None
    assert any("negative_keywords" in reason for reason in result["rankings"][0]["exclusion_reasons"])


@pytest.mark.parametrize("field,value", [
    ("account_uuid", "another"), ("account_key", "another"), ("profile_version", 2),
    ("domain_strategy_id", "legal"), ("strategy_version", "v2"), ("opportunity_id", ""),
    ("status", "rejected"), ("status", "expired"), ("status", "used"),
    ("valid_from", "2026-10-17T00:00:00+00:00"),
    ("valid_until", "2026-10-16T04:00:00+00:00"),
    ("valid_until", "2026-10-17T00:00:00"), ("valid_until", ""),
])
def test_invalid_opportunity_rejected_before_selection(tmp_path, profile, opportunity, field, value):
    setattr(opportunity, field, value)
    with pytest.raises(ValueError):
        select(profile, opportunity, tmp_path, target_book_id="1")


@pytest.mark.parametrize("field,value", [("domain_strategy_id", "legal"), ("strategy_version", "v2"), ("status", "paused")])
def test_invalid_account(tmp_path, profile, opportunity, field, value):
    setattr(profile, field, value)
    with pytest.raises(ValueError):
        select(profile, opportunity, tmp_path)


@pytest.mark.parametrize("field,value", [
    ("book_id", "2"), ("source_sha256", "0" * 64), ("allow_text_adaptation", False),
    ("allow_model_input", 1), ("reference", ""),
])
def test_authorization_contract(tmp_path, profile, opportunity, field, value):
    folder = book(tmp_path)
    path = folder / "text_authorization.json"
    auth = json.loads(path.read_text(encoding="utf-8"))
    auth[field] = value
    write_json(path, auth)
    assert select(profile, opportunity, tmp_path)["selected_book"] is None


@pytest.mark.parametrize("file", ["material.txt", "meta.json", "text_authorization.json"])
def test_discovered_file_hash_tampering(tmp_path, profile, opportunity, file):
    folder = book(tmp_path)
    candidates = discover_books(tmp_path)
    path = folder / file
    path.write_bytes(path.read_bytes() + b" ")
    result = select_target_novel(profile, opportunity, candidates, now=NOW)
    assert result["selected_book"] is None
    assert result["rankings"][0]["exclusion_reasons"]


def test_metadata_identity_conflict(tmp_path, profile, opportunity):
    book(tmp_path)
    candidates = discover_books(tmp_path)
    candidates[0]["book_id"] = "other"
    assert select_target_novel(profile, opportunity, candidates, now=NOW)["selected_book"] is None


def test_conflicting_book_id_and_identical_duplicates(tmp_path, profile, opportunity):
    book(tmp_path)
    candidates = discover_books(tmp_path)
    duplicate = copy.deepcopy(candidates[0])
    assert select_target_novel(profile, opportunity, candidates + [duplicate], now=NOW)["status"] == "selected"
    duplicate["authorization"]["reference"] = "conflicting license"
    result = select_target_novel(profile, opportunity, candidates + [duplicate], now=NOW)
    assert result["selected_book"] is None
    assert all("conflicting_book_id" in row["exclusion_reasons"] for row in result["rankings"])


def test_recognized_collector_header_never_enters_story_source(tmp_path, profile, opportunity):
    raw = "小说名称：校园恋爱\n书籍 ID：1\n作者：作者\n作品简介：未获取后续剧情，保镖出现。\n详情页：https://example.test\n\n第1章 初遇\n校园里的初遇。\n第2章 认识\n两人谈话。"
    book(tmp_path, body=raw)
    selected = select(profile, opportunity, tmp_path)["selected_book"]
    assert selected["source_text"].startswith("第1章 初遇")
    assert "保镖" not in selected["source_text"]
    span = selected["source_span"]
    assert raw[span["start"]:span["end"]] == selected["source_text"]
    assert span["sha256"] == hashlib.sha256(selected["source_text"].encode()).hexdigest()
    assert selected["acquisition_scope"]["observed_chapters"] == 2


def test_plain_prose_is_not_guessed_or_cut(tmp_path, profile, opportunity):
    raw = "校园里，她说：以后再见。\n这不是带章节标题的采集文件。"
    book(tmp_path, body=raw)
    selected = select(profile, opportunity, tmp_path)["selected_book"]
    assert selected["source_text"] == raw
    assert selected["source_span"]["start"] == 0
    assert selected["chapters"] == []


def test_collector_without_chapter_evidence_is_rejected(tmp_path, profile, opportunity):
    book(tmp_path, body="小说名称：校园恋爱\n作品简介：简介不是正文。")
    assert select(profile, opportunity, tmp_path)["selected_book"] is None


def test_relative_candidate_paths_and_inline_authorization(tmp_path, profile, opportunity):
    folder = book(tmp_path)
    candidates = discover_books(tmp_path)
    candidate = candidates[0]
    candidate["material_path"] = "material.txt"
    candidate.pop("authorization_path")
    candidate.pop("authorization_sha256")
    selected = select_target_novel(profile, opportunity, candidates, now=NOW)["selected_book"]
    assert selected["material_path"] == str((folder / "material.txt").resolve())
    assert selected["authorization_path"] is None


def test_missing_material_keeps_evidence(tmp_path, profile, opportunity):
    folder = book(tmp_path)
    (folder / "material.txt").unlink()
    result = select(profile, opportunity, tmp_path)
    assert result["status"] == "needs_materials"
    assert len(result["rankings"]) == 1


def test_approved_opportunity_accepted(tmp_path, profile, opportunity):
    opportunity.status = "approved"
    book(tmp_path)
    assert select(profile, opportunity, tmp_path)["status"] == "selected"


def test_generic_negative_terms_still_exclude(tmp_path, profile, opportunity):
    profile.negative_keywords = ["小说"]
    book(tmp_path, name="校园小说恋爱")
    assert select(profile, opportunity, tmp_path)["selected_book"] is None


def test_chapter_title_in_abstract_does_not_define_body(tmp_path, profile, opportunity):
    raw = "小说名称：校园恋爱\n书籍 ID：1\n作品简介：\n第999章 保镖降临\n未获取后续情节\n详情页：https://example.test\n\n第1章 初遇\n校园里的初遇。"
    book(tmp_path, body=raw)
    selected = select(profile, opportunity, tmp_path)["selected_book"]
    assert selected["source_text"].startswith("第1章 初遇")
    assert "保镖" not in selected["source_text"]
    assert len(selected["chapters"]) == 1


def test_collector_identity_must_match(tmp_path, profile, opportunity):
    book(tmp_path, body="小说名称：校园恋爱\n书籍 ID：2\n作品简介：简介\n详情页：https://example.test\n第1章 初遇\n正文")
    assert select(profile, opportunity, tmp_path)["selected_book"] is None


def test_boolean_version_rejected(tmp_path, profile, opportunity):
    profile.profile_version = True
    with pytest.raises(ValueError, match="integer"):
        select(profile, opportunity, tmp_path)


def test_malformed_metadata_is_excluded_without_losing_other_books(tmp_path, profile, opportunity):
    folder = book(tmp_path, "bad")
    path = folder / "meta.json"
    metadata = json.loads(path.read_text(encoding="utf-8"))
    metadata["categories"] = None
    write_json(path, metadata)
    book(tmp_path, "good")
    assert select(profile, opportunity, tmp_path)["selected_book"]["book_id"] == "good"
