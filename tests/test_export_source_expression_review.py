from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from PIL import Image

from scripts.export_source_expression_review import export_review, representative_frames
from src.trend_intelligence.content_analysis.artifacts import sha256


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _fixture(tmp_path):
    original = tmp_path / "source.mp4"
    original.write_bytes(b"source identity fixture")
    digest = sha256(original)
    source = {"item_id": "douyin:101", "video_id": "101", "video": str(original),
              "source_video_sha256": digest, "title": "实物示范", "source_url": "https://www.douyin.com/video/101"}
    manifest = {"schema": "research_local_media/v1", "account_uuid": "account:test", "collection_run_id": "run:test",
                "items": [source], "selection": [{"item_id": "douyin:101", "video_id": "101"}]}
    receipt = {"schema": "source_media_receipt/v1", "account_uuid": "account:test", "collection_run_id": "run:test",
               "identity_confirmed": True, "duration_seconds": 6, **{key: source[key] for key in ("item_id", "video_id", "video", "source_video_sha256")}}
    receipt_path = _write(tmp_path / "receipt.json", receipt)
    source.update(acquisition_receipt=str(receipt_path), acquisition_receipt_sha256=sha256(receipt_path))
    manifest_path = _write(tmp_path / "manifest.json", manifest)
    return manifest_path, manifest, source


def _candidate(tmp_path, source, name, created_at, core="展示纸张"):
    folder = tmp_path / "analyses" / "hash" / name
    request = {"parameters": {"source_sha256": source["source_video_sha256"]}, "source_video_path": source["video"]}
    _write(folder / "request.json", request)
    frames, evidence = [], []
    for index, second in enumerate([0, 2, 4, 5.98], 1):
        path = folder / "frames" / f"frame_{index}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (40, 60), color=(index*40, 40, 80)).save(path)
        frames.append({"id": f"V{index:04d}", "time_seconds": second, "path": str(path), "sha256": sha256(path)})
        evidence.append({"id": f"V{index:04d}", "channel": "visual", "start_seconds": second,
                         "end_seconds": second, "text": f"纸张状态{index}"})
    frame_manifest = {"schema": "local_video_frame_manifest/v2", "source_video_path": source["video"],
                      "source_video_sha256": source["source_video_sha256"], "duration_seconds": 6, "frames": frames}
    manifest_path = _write(folder / "frame_manifest.json", frame_manifest)
    transcript = {"result": [], "provenance": {"schema": "local_audio_evidence/v2", "source_video_sha256": source["source_video_sha256"],
                    "status": "verified_no_speech", "status_reason": "probe verified no audio stream", "source_probe": {"streams": [{"codec_type": "video"}]},
                    "coverage_start_seconds": 0, "coverage_end_seconds": 6}}
    transcript_path = _write(folder / "transcript.json", transcript)
    expression = {"schema": "video_expression_analysis/v1", "core_message": {"text": core, "evidence_ids": ["V0001"]},
                  "expression_modes": [{"mode": "prop_demonstration", "evidence_ids": ["V0001"]}],
                  "visual_expression": [{"text": "纸张示范", "evidence_ids": ["V0002"]}], "audio_expression": [],
                  "conflict": {"status": "not_observed"}, "uncertainties": [], "evidence": evidence}
    qwen = {"schema": "local_qwen_frame_analysis/v2", "created_at": created_at, "source_video_sha256": source["source_video_sha256"],
            "frame_manifest_path": str(manifest_path), "frame_manifest_sha256": sha256(manifest_path),
            "transcript_sha256": sha256(transcript_path), "analyzed_frame_ids": [frame["id"] for frame in frames],
            "batches": [{"observations": [{"frame_id": item["id"], "event": item["text"]} for item in evidence]}],
            "answer": {"expression_analysis": expression}}
    return _write(folder / "qwen.json", qwen)


def _export(tmp_path, manifest):
    return export_review(manifest, output_root=tmp_path / "review", analysis_root=tmp_path / "analyses",
                         database=None, rejection_root=tmp_path / "rejections")


def test_export_includes_entire_selected_cohort_and_never_marks_review_passed(tmp_path):
    path, manifest, source = _fixture(tmp_path)
    manifest["selection"].extend({"item_id": f"douyin:{item}", "video_id": str(item)} for item in range(102, 121))
    _write(path, manifest)
    _candidate(tmp_path, source, "attempt1", "2026-09-09T10:00:00+00:00")
    report = _export(tmp_path, path)
    assert report["selection_count"] == 20
    assert report["candidate_count"] == 1
    assert report["sources"][0]["analyzed_at_bjt"].startswith("2026-09-09T18:00:00")
    assert all(row["semantic_status"] == "not_reviewed_by_exporter" for row in report["sources"])
    row = report["sources"][0]
    assert Image.open(row["contact_sheet_path"]).width > 0
    assert Path(row["asr_text_path"]).is_file()
    assert report["sources"][1]["status"] == "pending_original"
    assert not list((tmp_path / "review").rglob("*.tmp"))


def test_existing_review_is_shown_only_when_bound_to_actual_version_and_source(tmp_path):
    path, _, source = _fixture(tmp_path)
    qwen = _candidate(tmp_path, source, "attempt1", "2026-09-09T10:00:00+00:00")
    review = {"schema": "source_expression_semantic_review/v1", "artifact_path": str(qwen),
              "artifact_sha256": sha256(qwen), "source_video_sha256": source["source_video_sha256"],
              "decision": "passed_with_limits", "blocked_for_script_generation": False,
              "reviewed_at": "2026-09-09T11:00:00+00:00", "limitations": ["未听原音"],
              "nonblocking_notes": [{"text": "纸张不证明内容真实"}]}
    review_path = _write(qwen.with_name("semantic_review.json"), review)
    original = review_path.read_bytes()
    result = _export(tmp_path, path)
    assert result["reviewed_candidate_count"] == 1
    assert result["sources"][0]["semantic_status"] == "not_reviewed_by_exporter"
    assert result["sources"][0]["existing_review"]["reviewed_at_bjt"].startswith("2026-09-09T19:00:00")
    report = (tmp_path / "review/review.md").read_text(encoding="utf-8")
    assert "画面如何表达" in report and "纸张示范" in report and "V0002" in report
    assert "未听原音" in report and "纸张不证明内容真实" in report
    assert review_path.read_bytes() == original
    review["source_video_sha256"] = "0" * 64
    _write(review_path, review)
    assert _export(tmp_path, path)["reviewed_candidate_count"] == 0


def test_incomplete_or_stale_approval_is_not_a_current_review(tmp_path):
    path, _, source = _fixture(tmp_path)
    qwen = _candidate(tmp_path, source, "attempt1", "2026-09-09T10:00:00+00:00")
    _write(qwen.with_name("semantic_review.json"), {"artifact_sha256": sha256(qwen), "decision": "passed"})
    result = _export(tmp_path, path)
    assert result["candidate_count"] == 1
    assert result["reviewed_candidate_count"] == 0
    assert result["all_selected_sources_reviewed"] is False


def test_comparison_requires_every_selected_review_and_keeps_group_denominators(tmp_path):
    items, candidates = [], []
    for index, metric in enumerate((100, 50, 20, 10)):
        folder = tmp_path / str(index)
        folder.mkdir()
        _, local_manifest, source = _fixture(folder)
        video = Path(source["video"])
        video.write_bytes(f"distinct original {index}".encode())
        source.update(item_id=f"douyin:{101+index}", video_id=str(101+index),
                      source_video_sha256=sha256(video), metric_kind="likes", metric_value=metric)
        receipt = json.loads(Path(source["acquisition_receipt"]).read_text(encoding="utf-8"))
        receipt.update({key: source[key] for key in ("item_id", "video_id", "source_video_sha256")})
        _write(Path(source["acquisition_receipt"]), receipt)
        source["acquisition_receipt_sha256"] = sha256(source["acquisition_receipt"])
        qwen = _candidate(folder, source, "attempt", "2026-09-09T10:00:00+00:00")
        source.update(qwen=str(qwen), transcript=str(qwen.with_name("transcript.json")))
        items.append(source)
        review = {"schema": "source_expression_semantic_review/v1", "artifact_path": str(qwen),
                  "artifact_sha256": sha256(qwen), "source_video_sha256": source["source_video_sha256"],
                  "decision": "passed_with_limits", "blocked_for_script_generation": False,
                  "reviewed_at": "2026-09-09T11:00:00+00:00"}
        candidates.append((qwen, review))
        if index < 3:
            _write(qwen.with_name("semantic_review.json"), review)
    manifest = {"schema": "research_local_media/v1", "account_uuid": "account:test",
                "collection_run_id": "run:test", "items": items}
    path = _write(tmp_path / "manifest.json", manifest)
    assert _export(tmp_path, path)["expression_patterns"] is None
    qwen, review = candidates[-1]
    _write(qwen.with_name("semantic_review.json"), review)
    result = _export(tmp_path, path)
    patterns = result["expression_patterns"]
    assert result["reviewed_candidate_count"] == 4
    assert patterns["creative_contribution_percent"] is None
    group = patterns["patterns"][0]["metric_groups"][0]
    assert (group["high_group_support"], group["high_group_size"]) == (1, 1)
    assert (group["comparison_group_support"], group["comparison_group_size"]) == (3, 3)
    assert group["high_source_item_ids"] == ["douyin:101"]
    assert group["contrast_available"] is False
    assert "average_account_relevance" not in patterns["patterns"][0]


def test_bare_mode_names_cannot_pass_evidence_gate_or_break_result_export(tmp_path):
    path, _, source = _fixture(tmp_path)
    qwen = _candidate(tmp_path, source, "attempt1", "2026-09-09T10:00:00+00:00")
    payload = json.loads(qwen.read_text(encoding="utf-8"))
    payload["answer"]["expression_analysis"]["expression_modes"] = ["direct_explanation"]
    _write(qwen, payload)
    result = _export(tmp_path, path)
    assert result["candidate_count"] == 0
    assert "expression_modes" in result["sources"][0]["excluded_candidates"][0]["reason"]


def test_newest_candidate_uses_recorded_time_even_when_mtime_order_is_opposite(tmp_path):
    path, _, source = _fixture(tmp_path)
    old = _candidate(tmp_path, source, "older", "2026-09-09T08:00:00+00:00", "旧候选")
    new = _candidate(tmp_path, source, "newer", "2026-09-09T10:00:00+00:00", "新候选")
    os.utime(old, (2_000_000_000, 2_000_000_000))
    os.utime(new, (1, 1))
    report = _export(tmp_path, path)
    assert report["sources"][0]["core_message"]["text"] == "新候选"


def test_rejected_newer_candidate_is_skipped_read_only(tmp_path):
    path, _, source = _fixture(tmp_path)
    _candidate(tmp_path, source, "older", "2026-09-09T08:00:00+00:00", "旧候选")
    rejected = _candidate(tmp_path, source, "newer", "2026-09-09T10:00:00+00:00", "错误候选")
    review_path = _write(rejected.with_name("semantic_review.json"), {"artifact_sha256": sha256(rejected), "decision": "failed"})
    before = review_path.read_bytes()
    report = _export(tmp_path, path)
    assert report["sources"][0]["core_message"]["text"] == "旧候选"
    assert "semantic review" in report["sources"][0]["excluded_candidates"][0]["reason"]
    assert review_path.read_bytes() == before
    assert not (tmp_path / "rejections").exists()


def test_permanent_rejection_still_blocks_if_nearby_review_changed(tmp_path):
    path, _, source = _fixture(tmp_path)
    qwen = _candidate(tmp_path, source, "attempt", "2026-09-09T08:00:00+00:00")
    digest = sha256(qwen)
    _write(tmp_path / "rejections" / f"{digest}.json", {"artifact_sha256": digest, "decision": "failed"})
    _write(qwen.with_name("semantic_review.json"), {"artifact_sha256": digest, "decision": "passed"})
    report = _export(tmp_path, path)
    assert report["candidate_count"] == 0
    assert report["sources"][0]["status"] == "no_eligible_candidate"


def test_frame_hash_change_excludes_complete_looking_candidate(tmp_path):
    path, _, source = _fixture(tmp_path)
    qwen = _candidate(tmp_path, source, "attempt", "2026-09-09T08:00:00+00:00")
    frame = qwen.parent / "frames" / "frame_2.jpg"
    frame.write_bytes(b"changed")
    report = _export(tmp_path, path)
    assert report["candidate_count"] == 0
    assert "frame changed" in report["sources"][0]["excluded_candidates"][0]["reason"]


def test_request_cannot_rebind_same_bytes_at_a_different_original_path(tmp_path):
    path, _, source = _fixture(tmp_path)
    qwen = _candidate(tmp_path, source, "attempt", "2026-09-09T08:00:00+00:00")
    different = tmp_path / "different_source.mp4"
    different.write_bytes(Path(source["video"]).read_bytes())
    request_path = qwen.with_name("request.json")
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["source_video_path"] = str(different)
    _write(request_path, request)
    report = _export(tmp_path, path)
    assert report["candidate_count"] == 0
    assert "request source path" in report["sources"][0]["excluded_candidates"][0]["reason"]


def test_changed_original_is_invalid_before_selecting_existing_analysis(tmp_path):
    path, _, source = _fixture(tmp_path)
    _candidate(tmp_path, source, "attempt", "2026-09-09T08:00:00+00:00")
    Path(source["video"]).write_bytes(b"different original")
    report = _export(tmp_path, path)
    assert report["sources"][0]["status"] == "invalid_original"
    assert "source hash changed" in report["sources"][0]["issues"][0]


def test_asr_fusion_hash_change_excludes_candidate(tmp_path):
    path, _, source = _fixture(tmp_path)
    qwen = _candidate(tmp_path, source, "attempt", "2026-09-09T08:00:00+00:00")
    transcript_path = qwen.with_name("transcript.json")
    payload = json.loads(transcript_path.read_text(encoding="utf-8"))
    payload["extra"] = "changed"
    _write(transcript_path, payload)
    report = _export(tmp_path, path)
    assert report["candidate_count"] == 0
    assert "transcript provenance" in report["sources"][0]["excluded_candidates"][0]["reason"]


def test_missing_created_at_is_not_replaced_with_file_time(tmp_path):
    path, _, source = _fixture(tmp_path)
    qwen = _candidate(tmp_path, source, "attempt", "")
    report = _export(tmp_path, path)
    assert report["candidate_count"] == 0
    assert "created_at" in report["sources"][0]["excluded_candidates"][0]["reason"]


def test_failed_attempt_is_excluded(tmp_path):
    path, _, source = _fixture(tmp_path)
    qwen = _candidate(tmp_path, source, "attempt", "2026-09-09T08:00:00+00:00")
    _write(qwen.with_name("failed.json"), {"status": "failed"})
    assert _export(tmp_path, path)["candidate_count"] == 0


def test_metrics_are_unknown_without_explicit_likes_kind(tmp_path):
    path, manifest, _ = _fixture(tmp_path)
    manifest["items"][0].update(metric_value=123456, metric_kind="displayed_unknown")
    _write(path, manifest)
    assert _export(tmp_path, path)["sources"][0]["likes"] is None


def test_database_metrics_are_bound_to_account_and_batch_without_schema_writes(tmp_path):
    path, manifest, _ = _fixture(tmp_path)
    database = tmp_path / "metrics.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE trend_collection_runs (run_id TEXT, account_uuid TEXT)")
        connection.execute("CREATE TABLE trend_items (item_id TEXT, title TEXT)")
        connection.execute("CREATE TABLE trend_observations (run_id TEXT, item_id TEXT, metric_value INTEGER, metric_kind TEXT, collected_at TEXT)")
        connection.executemany("INSERT INTO trend_collection_runs VALUES (?,?)", [("run:test", "account:test"), ("other", "account:other")])
        connection.execute("INSERT INTO trend_items VALUES ('douyin:101','数据库标题')")
        connection.executemany("INSERT INTO trend_observations VALUES (?,?,?,?,?)", [
            ("run:test", "douyin:101", 500, "likes_user_confirmed", "2026-09-09T08:00:00+00:00"),
            ("run:test", "douyin:101", 520, "likes", "2026-09-09T08:00:00+00:00"),
            ("other", "douyin:101", 999999, "likes", "2026-09-09T08:00:00+00:00")])
    before = database.read_bytes()
    report = export_review(path, output_root=tmp_path / "review", analysis_root=tmp_path / "analyses", database=database)
    assert report["sources"][0]["likes"]["value"] == 500
    assert report["sources"][0]["title"] == "数据库标题"
    assert database.read_bytes() == before


def test_contact_selection_retains_first_last_intermediate_and_claim_frames():
    frames = [{"id": f"V{index:04d}", "time_seconds": float(index)} for index in range(50)]
    expression = {"core_message": {"text": "证据", "evidence_ids": ["V0048", "V0025"]},
                  "conflict": {"turning_point": {"text": "转折", "evidence_ids": ["V0017"]}}}
    selected = representative_frames(frames, expression, 12)
    ids = {row["id"] for row in selected}
    assert len(ids) == 12
    assert {"V0000", "V0049", "V0048", "V0025", "V0017"} <= ids
    assert selected == sorted(selected, key=lambda row: row["time_seconds"])


def test_explicit_manifest_qwen_outside_cache_uses_explicit_transcript(tmp_path):
    path, manifest, source = _fixture(tmp_path)
    original = _candidate(tmp_path, source, "attempt", "2026-09-09T08:00:00+00:00", "原始归纳")
    repaired = tmp_path / "external_repair" / "qwen.json"
    payload = json.loads(original.read_text(encoding="utf-8"))
    payload["created_at"] = "2026-09-09T10:00:00+00:00"
    payload["answer"]["expression_analysis"]["core_message"]["text"] = "新候选归纳"
    _write(repaired, payload)
    manifest["items"][0].update(qwen=str(repaired), transcript=str(original.with_name("transcript.json")))
    _write(path, manifest)
    report = _export(tmp_path, path)
    assert report["sources"][0]["core_message"]["text"] == "新候选归纳"
    assert report["sources"][0]["qwen_artifact_path"] == str(repaired)
    assert report["sources"][0]["transcript_artifact_path"] == str(original.with_name("transcript.json"))


def test_explicit_repaired_observations_are_verified_against_bound_review(tmp_path):
    path, manifest, source = _fixture(tmp_path)
    original = _candidate(tmp_path, source, "attempt", "2026-09-09T08:00:00+00:00")
    payload = json.loads(original.read_text(encoding="utf-8"))
    frame_manifest = json.loads(Path(payload["frame_manifest_path"]).read_text(encoding="utf-8"))
    frame = frame_manifest["frames"][0]
    review = {"schema": "source_visual_observation_review/v1", "source_video_sha256": source["source_video_sha256"],
              "frame_manifest": {"path": payload["frame_manifest_path"], "sha256": payload["frame_manifest_sha256"]},
              "original_artifacts": [{"kind": "qwen_analysis", "path": str(original), "sha256": sha256(original)}],
              "scope_limitations": ["仅核对静帧，未判断声音"],
              "corrections": [{"frame_id": frame["id"], "frame_sha256": frame["sha256"], "time_seconds": frame["time_seconds"],
                               "original_text": "纸张状态1", "corrected_text": "画中画出现纸张，主画面人物未持纸张", "review_reason": "区分主画面与画中画",
                               "reviewer": "test_fixture", "reviewed_at": "2026-09-09T09:00:00+00:00"}]}
    review_path = _write(tmp_path / "external_repair" / "observation_review.json", review)
    payload["observation_review"] = {"path": str(review_path), "sha256": sha256(review_path)}
    payload["created_at"] = "2026-09-09T10:00:00+00:00"
    payload["answer"]["expression_analysis"]["evidence"][0]["text"] = review["corrections"][0]["corrected_text"]
    repaired = _write(tmp_path / "external_repair" / "qwen.json", payload)
    manifest["items"][0].update(qwen=str(repaired), transcript=str(original.with_name("transcript.json")))
    _write(path, manifest)
    report = _export(tmp_path, path)
    assert report["sources"][0]["qwen_artifact_path"] == str(repaired)
    assert report["sources"][0]["observation_review"] == payload["observation_review"]
    review["corrections"][0]["corrected_text"] = "伪造后修改"
    _write(review_path, review)
    report = _export(tmp_path, path)
    assert report["sources"][0]["qwen_artifact_path"] == str(original)
    assert any("SHA256 changed" in item["reason"] for item in report["sources"][0]["excluded_candidates"])
