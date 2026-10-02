from __future__ import annotations

import importlib.util
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts/audit_task1_story_v61_execution_readiness.py"


def _write_full_smoke_progress(module, path: Path) -> None:
    path.write_text(json.dumps({
        "result": "FAILED_SCENE_SMOKE_RENDERED_AWAITING_HUMAN_REVIEW",
        "selected_shot_ids": list(module.smoke.FAILED_SHOT_IDS),
        "shots": [
            {"scene_id": scene_id} for scene_id in module.smoke.FAILED_SHOT_IDS
        ],
        "gates": {"failed_scene_smoke_rendered": True},
    }), encoding="utf-8")


def _module():
    spec = importlib.util.spec_from_file_location("v61_readiness", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._gpu_readiness = lambda: {
        "ready": True,
        "error": "",
        "minimum_free_mib": 8192,
        "maximum_utilization_percent": 80,
        "devices": [{"index": 0, "memory_free_mib": 12000, "utilization_percent": 5}],
    }
    return module


def _db(path: Path, *, eligible: bool = False) -> None:
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE fanqie_books(id INTEGER PRIMARY KEY, fanqie_book_id TEXT);
        CREATE TABLE fanqie_promotion_tasks(
            id INTEGER PRIMARY KEY, task_uuid TEXT, version INTEGER, status TEXT,
            publish_type TEXT, promotion_alias TEXT, book_id INTEGER,
            valid_from TEXT, valid_until TEXT
        );
        CREATE TABLE fanqie_publish_records(id INTEGER PRIMARY KEY);
        CREATE TABLE fanqie_bindings(id INTEGER PRIMARY KEY);
        CREATE TABLE fanqie_video_jobs(id INTEGER PRIMARY KEY);
        CREATE TABLE fanqie_reviews(id INTEGER PRIMARY KEY);
    """)
    connection.execute("INSERT INTO fanqie_books VALUES(1, '7656344274241326104')")
    connection.execute(
        "INSERT INTO fanqie_promotion_tasks VALUES(1, 'task', 1, ?, ?, '我闭着眼睛玩', 1, ?, ?)",
        ("active" if eligible else "revision_required", "AIGC" if eligible else "AI数字人",
         "2026-08-01 00:00:00", "2026-12-31 23:59:59"),
    )
    connection.commit()
    connection.close()


def test_execution_is_immediately_available_but_platform_stays_closed(tmp_path: Path) -> None:
    module = _module()
    database = tmp_path / "closed_loop.db"
    _db(database)
    report = module.audit(
        db_path=database,
        now=datetime(2026, 8, 13, 23, 0, tzinfo=timezone.utc),
    )
    assert report["gates"]["tts_gpu_window_open"] is True
    assert report["next_action"] == "render_seven_shot_smoke_to_new_immutable_paths"
    assert report["gates"]["douyin_upload_allowed"] is False
    assert report["gates"]["fanqie_backfill_allowed"] is False
    assert report["database"]["opened_read_only"] is True
    assert report["database"]["eligible_tasks"] == []
    assert all(value == 0 for value in report["forbidden_side_effects"].values())


def test_after_window_without_smoke_selects_seven_shot_render(tmp_path: Path) -> None:
    module = _module()
    database = tmp_path / "closed_loop.db"
    _db(database, eligible=True)
    report = module.audit(
        db_path=database,
        now=datetime(2026, 8, 19, 0, 0, tzinfo=timezone.utc),
    )
    assert report["next_action"] == "render_seven_shot_smoke_to_new_immutable_paths"
    assert len(report["database"]["eligible_tasks"]) == 1
    assert report["gates"]["signed_publish_authorization_present"] is False


def test_busy_gpu_is_reported_and_changes_render_next_action(tmp_path: Path) -> None:
    module = _module()
    database = tmp_path / "closed_loop.db"
    _db(database)
    module._gpu_readiness = lambda: {
        "ready": False,
        "error": "GPU is already busy",
        "minimum_free_mib": 8192,
        "maximum_utilization_percent": 80,
        "devices": [{"index": 0, "memory_free_mib": 12800, "utilization_percent": 99}],
    }
    report = module.audit(db_path=database)
    assert report["gates"]["gpu_resource_ready"] is False
    assert report["gpu"]["error"] == "GPU is already busy"
    assert report["next_action"] == "wait_for_gpu_resource_before_seven_shot_render"


def test_single_shot_progress_cannot_claim_seven_shot_smoke(tmp_path: Path) -> None:
    module = _module()
    database = tmp_path / "closed_loop.db"
    _db(database)
    progress = tmp_path / "diagnostic.json"
    progress.write_text(json.dumps({
        "result": "FAILED_SCENE_SMOKE_RENDERED_AWAITING_HUMAN_REVIEW",
        "selected_shot_ids": ["b01_boast"],
        "shots": [{"scene_id": "b01_boast"}],
        "gates": {"failed_scene_smoke_rendered": True},
    }), encoding="utf-8")
    report = module.audit(db_path=database, smoke_progress=progress)
    assert report["gates"]["smoke_rendered"] is False
    assert report["next_action"] == "render_seven_shot_smoke_to_new_immutable_paths"


def test_wrong_book_or_alias_is_not_a_matching_task(tmp_path: Path) -> None:
    module = _module()
    database = tmp_path / "closed_loop.db"
    _db(database, eligible=True)
    connection = sqlite3.connect(database)
    connection.execute("UPDATE fanqie_books SET fanqie_book_id='wrong'")
    connection.commit()
    connection.close()
    report = module.audit(
        db_path=database,
        now=datetime(2026, 8, 19, 0, 0, tzinfo=timezone.utc),
    )
    assert report["database"]["eligible_tasks"] == []
    assert report["gates"]["matching_aigc_or_commentary_task_present"] is False


def test_database_without_video_jobs_or_reviews_fails_completeness(tmp_path: Path) -> None:
    module = _module()
    database = tmp_path / "incomplete.db"
    connection = sqlite3.connect(database)
    connection.executescript("""
        CREATE TABLE fanqie_books(id INTEGER PRIMARY KEY, fanqie_book_id TEXT);
        CREATE TABLE fanqie_promotion_tasks(id INTEGER PRIMARY KEY);
        CREATE TABLE fanqie_publish_records(id INTEGER PRIMARY KEY);
        CREATE TABLE fanqie_bindings(id INTEGER PRIMARY KEY);
    """)
    connection.close()
    report = module.audit(db_path=database)
    assert report["database"]["error"] == "closed-loop tables are missing"
    assert report["database"]["eligible_tasks"] == []


def test_expired_exact_task_is_not_eligible(tmp_path: Path) -> None:
    module = _module()
    database = tmp_path / "closed_loop.db"
    _db(database, eligible=True)
    connection = sqlite3.connect(database)
    connection.execute(
        "UPDATE fanqie_promotion_tasks SET valid_until='2026-08-18T20:39:59+08:00'"
    )
    connection.commit()
    connection.close()
    report = module.audit(
        db_path=database,
        now=datetime(2026, 8, 19, 0, 0, tzinfo=timezone.utc),
    )
    assert report["database"]["eligible_tasks"] == []


def test_closed_window_does_not_block_non_gpu_human_review(
    monkeypatch, tmp_path: Path,
) -> None:
    module = _module()
    database = tmp_path / "closed_loop.db"
    _db(database)
    progress = tmp_path / "smoke_progress.json"
    _write_full_smoke_progress(module, progress)
    monkeypatch.setattr(module, "_artifact", lambda path, **kwargs: {
        "path": str(path), "exists": True, "valid_json_object": True,
        "result": "FAILED_SCENE_SMOKE_RENDERED_AWAITING_HUMAN_REVIEW",
        "accepted": None,
        "ready": path == module.smoke.DEFAULT_PROGRESS,
    })
    report = module.audit(
        db_path=database,
        smoke_progress=progress,
        now=datetime(2026, 8, 13, 23, 0, tzinfo=timezone.utc),
    )
    assert report["gates"]["smoke_rendered"] is True
    assert report["next_action"] == "complete_seven_shot_review_in_streamlit"


def test_full_video_only_sequence_skips_obsolete_smoke_human_review(
    monkeypatch, tmp_path: Path,
) -> None:
    module = _module()
    database = tmp_path / "closed_loop.db"
    _db(database)
    progress = tmp_path / "full_progress.json"
    attestation = tmp_path / "full_attestation.json"
    candidate = tmp_path / "candidate.mp4"
    progress.write_text(json.dumps({
        "result": module.full_batch.EXPECTED_RESULT,
        "review_sequence": "full_video_only",
        "gates": {
            "smoke_human_review_passed": False,
            "full_review_first_authorized": True,
            "full_19_shots_rendered": True,
        },
    }), encoding="utf-8")
    attestation.write_text("{}", encoding="utf-8")
    candidate.write_bytes(b"candidate")
    original_artifact = module._artifact

    def artifact(path, **kwargs):
        if path in {progress, attestation}:
            return {
                "path": str(path), "exists": True, "valid_json_object": True,
                "result": module.full_batch.EXPECTED_RESULT,
                "accepted": True, "ready": True,
            }
        return original_artifact(path, **kwargs)

    monkeypatch.setattr(module, "_artifact", artifact)
    monkeypatch.setattr(
        module, "_production_validation",
        lambda label, callback: {
            "label": label, "passed": True, "error": "",
            "evidence": {"accepted": True},
        },
    )
    monkeypatch.setattr(
        module, "_receipt_matches_live_validation", lambda *args: True,
    )
    report = module.audit(
        db_path=database,
        full_batch_progress=progress,
        full_attestation=attestation,
        candidate=candidate,
    )
    assert report["gates"]["full_review_first_authorized"] is True
    assert report["gates"]["smoke_human_review_passed"] is False
    assert report["next_action"] == "complete_full_video_review_in_streamlit"


def test_live_validation_without_matching_receipt_remains_closed(
    monkeypatch, tmp_path: Path,
) -> None:
    module = _module()
    database = tmp_path / "closed_loop.db"
    _db(database)
    progress = tmp_path / "smoke_progress.json"
    review = tmp_path / "smoke_review.json"
    certificate = tmp_path / "smoke_certificate.json"
    _write_full_smoke_progress(module, progress)
    review.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(module.smoke_review_gate, "validate_review", lambda *args, **kwargs: {
        "schema_version": "fanqie_v61_smoke_review_certificate/v2",
        "approval_source": "authenticated_streamlit_frontend",
        "created_at": "live", "accepted": True,
        "task_id": 1, "review_sha256": "CURRENT",
    })
    original_artifact = module._artifact

    def artifact(path, **kwargs):
        if path == progress:
            return {
                "path": str(path), "exists": True, "valid_json_object": True,
                "result": "FAILED_SCENE_SMOKE_RENDERED_AWAITING_HUMAN_REVIEW",
                "accepted": None, "ready": True,
            }
        return original_artifact(path, **kwargs)

    monkeypatch.setattr(module, "_artifact", artifact)
    report = module.audit(
        db_path=database, smoke_progress=progress, smoke_review=review,
        smoke_certificate=certificate,
        now=datetime(2026, 8, 13, 23, 0, tzinfo=timezone.utc),
    )
    assert report["production_validations"]["smoke_human_review"]["passed"] is True
    assert report["production_validations"]["smoke_human_review"][
        "receipt_matches_live_validation"
    ] is False
    assert report["gates"]["smoke_human_review_passed"] is False
    assert report["next_action"] == "complete_seven_shot_review_in_streamlit"


def test_stale_receipt_cannot_satisfy_live_validation(tmp_path: Path) -> None:
    module = _module()
    receipt = tmp_path / "certificate.json"
    receipt.write_text(
        '{"schema_version":"fanqie_v61_smoke_review_certificate/v2",'
        '"approval_source":"authenticated_streamlit_frontend","created_at":"old",'
        '"accepted":true,"review_sha256":"OLD"}',
        encoding="utf-8",
    )
    validation = {
        "passed": True,
        "evidence": {
            "schema_version": "fanqie_v61_smoke_review_certificate/v2",
            "approval_source": "authenticated_streamlit_frontend",
            "created_at": "new",
            "accepted": True, "review_sha256": "CURRENT",
        },
    }
    assert module._receipt_matches_live_validation(receipt, validation) is False
    validation["evidence"]["review_sha256"] = "OLD"
    assert module._receipt_matches_live_validation(receipt, validation) is True


@pytest.mark.parametrize("result", [{}, {"accepted": False}, None, []])
def test_production_validation_requires_explicit_true_acceptance(result) -> None:
    module = _module()
    validation = module._production_validation("test", lambda: result)
    assert validation["passed"] is False


def test_two_matching_tasks_fail_exactly_one_cardinality(tmp_path: Path) -> None:
    module = _module()
    database = tmp_path / "closed_loop.db"
    _db(database, eligible=True)
    connection = sqlite3.connect(database)
    connection.execute(
        "INSERT INTO fanqie_promotion_tasks VALUES(2, 'task-2', 1, 'active', "
        "'AIGC', ?, 1, '2026-08-01T00:00:00+00:00', "
        "'2026-12-31T23:59:59+00:00')",
        (module.EXPECTED_PROMOTION_ALIAS,),
    )
    connection.commit()
    connection.close()
    report = module.audit(
        db_path=database,
        now=datetime(2026, 8, 19, 0, 0, tzinfo=timezone.utc),
    )
    assert len(report["database"]["eligible_tasks"]) == 2
    assert report["gates"]["matching_aigc_or_commentary_task_present"] is False


def test_future_exact_task_is_not_eligible(tmp_path: Path) -> None:
    module = _module()
    database = tmp_path / "closed_loop.db"
    _db(database, eligible=True)
    connection = sqlite3.connect(database)
    connection.execute(
        "UPDATE fanqie_promotion_tasks SET valid_from='2026-08-20T00:00:00+00:00'"
    )
    connection.commit()
    connection.close()
    report = module.audit(
        db_path=database,
        now=datetime(2026, 8, 19, 0, 0, tzinfo=timezone.utc),
    )
    assert report["database"]["eligible_tasks"] == []


def test_workflow_approved_exact_task_remains_eligible(tmp_path: Path) -> None:
    module = _module()
    database = tmp_path / "closed_loop.db"
    _db(database, eligible=True)
    connection = sqlite3.connect(database)
    connection.execute("UPDATE fanqie_promotion_tasks SET status='approved'")
    connection.commit()
    connection.close()
    report = module.audit(
        db_path=database,
        now=datetime(2026, 8, 19, 0, 0, tzinfo=timezone.utc),
    )
    assert len(report["database"]["eligible_tasks"]) == 1
