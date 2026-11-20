"""One new metadata batch is prepared without collection/provider/DB writes."""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from src.content_factory.creative_fresh_legal_source_v1 import (
    prepare_source_bundle, write_source_bundle, FreshSourceError)
from src.operations_accounts.models import AccountProfile

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "data/reference_reviews/reusable_expression_20261001/EXPRESSION_REFERENCE.md"
STANDARDS = ROOT / "data/qa/loneliness_vs_current_story_20261007/round_03_knowledge_standards/EXPRESSION_STANDARDS_v1.json"
FACTS = ROOT / "data/qa/legal_new_batch_script_flow_20261007/round_01/LABOUR_LEGAL_FACTS.json"
NOW = "2026-10-12T13:10:00Z"
FLOOR = "2026-10-12T13:07:32Z"
START = "2026-10-12T13:08:00Z"
FINISH = "2026-10-12T13:09:00Z"


def fixture(tmp_path):
    profile = asdict(AccountProfile("offline:new-legal", "account01", "legal_services",
        target_audiences=["劳动者"], seed_keywords=["劳动", "法律", "被迫离职"],
        allowed_formats=["案例拆解"], forbidden_formats=["保证胜诉"], negative_keywords=["保证胜诉"]))
    binding = {k: profile[k] for k in ("account_uuid", "profile_version", "domain_strategy_id", "strategy_version")}
    tdb, pdb = tmp_path / "trend.db", tmp_path / "profile.db"
    with sqlite3.connect(pdb) as db:
        db.executescript("""
          CREATE TABLE douyin_accounts (account_uuid TEXT,account_key TEXT,status TEXT);
          CREATE TABLE account_strategy_versions (account_uuid TEXT,profile_version INTEGER,
            domain_strategy_id TEXT,strategy_version TEXT,profile_json TEXT,is_active INTEGER);
          CREATE TABLE account_runtime_bindings (account_uuid TEXT,account_key TEXT,platform TEXT,public_uid TEXT,status TEXT);
        """)
        db.execute("INSERT INTO douyin_accounts VALUES (?,?,?)", (profile["account_uuid"], "account01", "active"))
        db.execute("INSERT INTO account_strategy_versions VALUES (?,?,?,?,?,?)",
            (*binding.values(), json.dumps(profile, ensure_ascii=False), 1))
        db.execute("INSERT INTO account_runtime_bindings VALUES (?,?,?,?,?)",
            (profile["account_uuid"], "account01", "douyin", "offline-public-uid", "active"))
    op = {**binding, "account_key": "account01", "opportunity_id": "op-new", "title": "劳动纠纷",
        "status": "candidate", "opportunity_score": 50.0,
        "selected_item_ids": [f"i{i}" for i in range(20)], "topic_labels": ["被迫离职"],
        "score_breakdown": {"account_relevance": 90}, "risks": [],
        "valid_from": START, "valid_until": "2026-10-13T13:09:00Z", "created_at": FINISH}
    with sqlite3.connect(tdb) as db:
        db.executescript("""
          CREATE TABLE trend_collection_runs (run_id TEXT PRIMARY KEY,provider TEXT,status TEXT,
            started_at TEXT,finished_at TEXT,account_uuid TEXT,profile_version INTEGER,domain_strategy_id TEXT,strategy_version TEXT);
          CREATE TABLE trend_content_opportunities (opportunity_id TEXT PRIMARY KEY,account_uuid TEXT,profile_version INTEGER,
            domain_strategy_id TEXT,strategy_version TEXT,status TEXT,score REAL,valid_until TEXT,payload_json TEXT,created_at TEXT);
          CREATE TABLE trend_items (item_id TEXT PRIMARY KEY,video_id TEXT,url TEXT,title TEXT,author TEXT);
          CREATE TABLE trend_observations (id INTEGER PRIMARY KEY,run_id TEXT,item_id TEXT,keyword TEXT,
            root_keywords_json TEXT,hashtags_json TEXT,metric_kind TEXT,metric_value INTEGER,metric_text TEXT,
            collected_at TEXT,sort_key TEXT,sort_label TEXT,rank INTEGER,query_kind TEXT,query_value TEXT,query_depth INTEGER);
        """)
        db.execute("INSERT INTO trend_collection_runs VALUES (?,?,?,?,?,?,?,?,?)",
            ("offline-new-batch", "authorized_web", "completed", START, FINISH, *binding.values()))
        for i in range(20):
            keyword = "被迫离职" if i % 2 else "劳动仲裁"
            hashtags = ["被迫离职", "劳动仲裁", "经济补偿金", "抖来普法2026", "北京劳动律师"]
            if i < 4:
                hashtags.append("降薪")
            db.execute("INSERT INTO trend_items VALUES (?,?,?,?,?)", (f"i{i}", f"v{i}",
                f"https://example.invalid/{i}", "离线样本，不是采集或生产回执", f"模拟作者{i % 4}"))
            db.execute("INSERT INTO trend_observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (i + 1, "offline-new-batch", f"i{i}", keyword, json.dumps([keyword]), json.dumps(hashtags),
                 "views", 60000, "6万播放", "2026-10-12T13:08:30Z", "sort", "热度", i + 1, "keyword", keyword, 0))
        insert_op(db, op)
    result = {"status": "completed", "exit_code": 0, "result": {"status": "completed",
        "collection_run_id": "offline-new-batch", "account_uuid": profile["account_uuid"],
        "account_key": "account01", "profile_version": 1, "sample_gate": {"passed": True}}}
    identity = {"healthy": True, "status": "healthy", "account_key": "account01", "profile_version": 1,
                "expected_public_id": "offline-public-uid", "actual_public_id": "offline-public-uid",
                "at_utc": "2026-10-12T13:07:40Z"}
    args = dict(collect_result=result, trend_db=tdb, profile_db=pdb,
        reference_fulltext_path=REFERENCE, standards_path=STANDARDS,
        verified_legal_context_path=FACTS, now=NOW, requested_after=FLOOR, identity_check=identity)
    return args, op, profile


def insert_op(db, op):
    db.execute("INSERT OR REPLACE INTO trend_content_opportunities VALUES (?,?,?,?,?,?,?,?,?,?)",
        (op["opportunity_id"], op["account_uuid"], op["profile_version"], op["domain_strategy_id"],
         op["strategy_version"], op["status"], op["opportunity_score"], op["valid_until"],
         json.dumps(op, ensure_ascii=False), op["created_at"]))


def mutate(args, sql, params=(), *, profile=False):
    with sqlite3.connect(args["profile_db"] if profile else args["trend_db"]) as db:
        db.execute(sql, params)


def test_full_exact_batch_wire_and_readonly_hashes(tmp_path):
    args, _, _ = fixture(tmp_path)
    before = {k: hashlib.sha256(args[k].read_bytes()).hexdigest() for k in ("trend_db", "profile_db")}
    bundle = prepare_source_bundle(**args)
    assert bundle["selected_core"]["title"] == "被迫离职"
    assert bundle["selected_core"]["support_video_count"] == 20
    assert not {"抖来普法2026", "北京劳动律师"} & {t["label"] for t in bundle["packet"]["tag_catalog"]}
    context = json.loads(bundle["direction_wire"]["messages"][1]["content"])
    assert context["reference_fulltext"] == REFERENCE.read_bytes().decode("utf-8-sig")
    assert {c["id"] for c in context["writer_expression_criteria"]} == {"V3", "A1", "A2", "A4", "E1", "R1"}
    assert context["verified_legal_context"] == json.loads(FACTS.read_text(encoding="utf-8"))
    assert bundle["direction_wire"]["submitted"] is False
    assert bundle["packet"]["human_direction_confirmation_inherited"] is False
    assert bundle["manifest"]["human_confirmation"] is False
    assert all(hashlib.sha256(args[k].read_bytes()).hexdigest() == h for k, h in before.items())
    assert all(bundle["manifest"][k] == 0 for k in ("model_calls", "media_calls", "collection_calls", "publishing_calls"))


def test_completed_metadata_waits_for_av_without_false_completion(tmp_path):
    args, _, _ = fixture(tmp_path)
    args["collect_result"]["status"] = "awaiting_media_analysis"
    args["collect_result"]["result"]["status"] = "awaiting_media_analysis"
    args["collect_result"]["exit_code"] = 1
    bundle = prepare_source_bundle(**args)
    assert bundle["manifest"]["collection_status_original"] == "awaiting_media_analysis"
    assert bundle["manifest"]["original_video_av_analysis_completed"] is False
    assert json.loads(bundle["content"]["COLLECTION_RESULT.json"])["status"] == "awaiting_media_analysis"


@pytest.mark.parametrize("status", ["partial", "human_required", "running", "stopped_exception", "unknown"])
def test_incomplete_known_wrapper_stops(tmp_path, status):
    args, _, _ = fixture(tmp_path)
    args["collect_result"]["status"] = args["collect_result"]["result"]["status"] = status
    with pytest.raises(FreshSourceError, match="COLLECTION_INCOMPLETE"):
        prepare_source_bundle(**args)


@pytest.mark.parametrize("fault", ["account", "version", "bool_version", "sample", "exit", "nested_status", "missing_run"])
def test_cli_identity_and_completion_gates(tmp_path, fault):
    args, _, _ = fixture(tmp_path)
    w, r = args["collect_result"], args["collect_result"]["result"]
    if fault == "account": r["account_uuid"] = "other"
    elif fault == "version": r["profile_version"] = 2
    elif fault == "bool_version": r["profile_version"] = True
    elif fault == "sample": r["sample_gate"]["passed"] = False
    elif fault == "exit": w["exit_code"] = 1
    elif fault == "nested_status": r["status"] = "human_required"
    else: r["collection_run_id"] = ""
    with pytest.raises(FreshSourceError):
        prepare_source_bundle(**args)


@pytest.mark.parametrize("fault", ["uid", "not_healthy", "old", "future", "version", "bool_version", "after_start"])
def test_fresh_live_current_identity_required(tmp_path, fault):
    args, _, _ = fixture(tmp_path)
    c = args["identity_check"]
    if fault == "uid": c["actual_public_id"] = "other"
    elif fault == "not_healthy": c["healthy"] = False
    elif fault == "old": c["at_utc"] = "2026-10-11T13:07:00Z"
    elif fault == "future": c["at_utc"] = "2026-10-13T13:07:00Z"
    elif fault == "version": c["profile_version"] = 2
    elif fault == "bool_version": c["profile_version"] = True
    else: c["at_utc"] = FINISH
    with pytest.raises(FreshSourceError):
        prepare_source_bundle(**args)


@pytest.mark.parametrize("fault", ["inactive", "strategy_changed", "format", "binding_inactive"])
def test_current_profile_sql_gates(tmp_path, fault):
    args, _, profile = fixture(tmp_path)
    if fault == "inactive": mutate(args, "UPDATE douyin_accounts SET status='inactive'", profile=True)
    elif fault == "binding_inactive": mutate(args, "UPDATE account_runtime_bindings SET status='inactive'", profile=True)
    elif fault == "strategy_changed": mutate(args, "UPDATE account_strategy_versions SET profile_version=2", profile=True)
    else:
        profile["forbidden_formats"] = ["案例拆解"]
        mutate(args, "UPDATE account_strategy_versions SET profile_json=?", (json.dumps(profile),), profile=True)
    with pytest.raises(FreshSourceError):
        prepare_source_bundle(**args)


@pytest.mark.parametrize("fault", ["incomplete", "old", "future", "binding", "old_observation", "future_observation", "sample_gate"])
def test_exact_new_sql_batch_and_recomputed_sample(tmp_path, fault):
    args, _, _ = fixture(tmp_path)
    if fault == "incomplete": mutate(args, "UPDATE trend_collection_runs SET status='partial'")
    elif fault == "old": mutate(args, "UPDATE trend_collection_runs SET started_at='2026-10-11T13:08:00Z'")
    elif fault == "future": mutate(args, "UPDATE trend_collection_runs SET finished_at='2026-10-13T13:09:00Z'")
    elif fault == "binding": mutate(args, "UPDATE trend_collection_runs SET profile_version=2")
    elif fault == "old_observation": mutate(args, "UPDATE trend_observations SET collected_at='2026-10-11T13:08:30Z' WHERE id=1")
    elif fault == "future_observation": mutate(args, "UPDATE trend_observations SET collected_at='2026-10-13T13:08:30Z' WHERE id=1")
    else: mutate(args, "UPDATE trend_observations SET metric_value=1")
    with pytest.raises(FreshSourceError):
        prepare_source_bundle(**args)


@pytest.mark.parametrize("fault", ["old_candidate", "mixed_items", "score_mismatch", "no_issue"])
def test_no_old_candidate_or_arbitrary_core(tmp_path, fault):
    args, op, _ = fixture(tmp_path)
    if fault == "old_candidate": op["created_at"] = "2026-10-11T13:09:00Z"
    elif fault == "mixed_items": op["selected_item_ids"].append("old-item")
    elif fault == "score_mismatch":
        mutate(args, "UPDATE trend_content_opportunities SET score=99")
    else: mutate(args, "UPDATE trend_observations SET hashtags_json='[\"抖来普法2026\",\"北京劳动律师\"]'")
    if fault in {"old_candidate", "mixed_items"}:
        with sqlite3.connect(args["trend_db"]) as db: insert_op(db, op)
    with pytest.raises(FreshSourceError, match="NO_ELIGIBLE_NEW_OPPORTUNITY"):
        prepare_source_bundle(**args)


def test_highest_eligible_opportunity_and_core_without_old_rows(tmp_path):
    args, op, _ = fixture(tmp_path)
    with sqlite3.connect(args["trend_db"]) as db:
        insert_op(db, {**deepcopy(op), "opportunity_id": "op-high", "opportunity_score": 70.0})
        insert_op(db, {**deepcopy(op), "opportunity_id": "op-old", "opportunity_score": 99.0,
                       "created_at": "2026-10-11T13:09:00Z"})
        db.execute("INSERT INTO trend_items VALUES ('old-i','old-v','https://example.invalid/old','old','old-author')")
        db.execute("INSERT INTO trend_observations SELECT 50,'old-run','old-i',keyword,root_keywords_json,"
                   "'[\"降薪\"]',metric_kind,9999999,metric_text,collected_at,sort_key,sort_label,rank,"
                   "query_kind,query_value,query_depth FROM trend_observations WHERE id=1")
    bundle = prepare_source_bundle(**args)
    assert bundle["source"]["opportunity"]["opportunity_id"] == "op-high"
    assert bundle["selected_core"]["title"] == "被迫离职"
    assert len(bundle["source"]["observations"]) == 20
    assert "old-v" not in bundle["selected_core"]["support_video_ids"]


def test_future_inputs_and_insufficient_standards_stop(tmp_path):
    args, _, _ = fixture(tmp_path)
    args["requested_after"] = "2026-10-13T13:07:32Z"
    with pytest.raises(FreshSourceError, match="INPUT_FROM_FUTURE"): prepare_source_bundle(**args)
    args["requested_after"] = FLOOR
    facts = json.loads(FACTS.read_text(encoding="utf-8"))
    facts["verified_at"] = "2026-10-13T13:07:32Z"
    args["verified_legal_context_path"] = facts
    with pytest.raises(FreshSourceError, match="INPUT_FROM_FUTURE"): prepare_source_bundle(**args)
    args["verified_legal_context_path"] = FACTS
    args["standards_path"] = {"criteria": []}
    with pytest.raises(FreshSourceError, match="NO_ELIGIBLE_NEW_OPPORTUNITY"): prepare_source_bundle(**args)


def test_immutable_bundle_exact_replay_and_preflight_conflict(tmp_path):
    args, _, _ = fixture(tmp_path)
    bundle = prepare_source_bundle(**args)
    output = tmp_path / "bundle"
    first = write_source_bundle(output, bundle)
    replay = write_source_bundle(output, bundle)
    assert first["written"] and not replay["written"]
    assert replay["replayed"] == list(bundle["content"])
    conflicting = deepcopy(bundle)
    conflicting["content"]["SOURCE_PACKET.json"] += b" "
    with pytest.raises(FreshSourceError, match="BUNDLE_INVALID"):
        write_source_bundle(output, conflicting)
    assert (output / "SOURCE_PACKET.json").read_bytes() == bundle["content"]["SOURCE_PACKET.json"]
    (output / "R01_FULL.md").write_bytes(b"existing different content")
    with pytest.raises(FreshSourceError, match="BUNDLE_CONFLICT"):
        write_source_bundle(output, bundle)


def test_file_json_rejects_duplicate_identity_before_any_output(tmp_path):
    args, _, _ = fixture(tmp_path)
    path = tmp_path / "duplicate.json"
    path.write_text('{"healthy": true, "healthy": false}', encoding="utf-8")
    args["identity_check"] = path
    with pytest.raises(FreshSourceError, match="INPUT_JSON_INVALID"): prepare_source_bundle(**args)


def test_unverified_legal_family_coverage_never_selected(tmp_path):
    args, _, _ = fixture(tmp_path)
    args["legal_context_family_ids"] = ("family:marriage",)
    with pytest.raises(FreshSourceError, match="LEGAL_CONTEXT_COVERAGE_INVALID"):
        prepare_source_bundle(**args)
