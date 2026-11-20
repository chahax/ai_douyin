from __future__ import annotations

"""Read-only readiness audit for the task-1 V6.1 live-action pipeline.

The report selects the next legal operation but never performs TTS, GPU,
browser, database-write, upload, publish, or backfill work.
"""

import argparse
import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any


PROJECT_ROOT = Path(r"D:\IT\ai_douyin")
P0_ROOT = Path(r"D:\IT\ai_douyin_p0")
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
for root in (P0_ROOT, SCRIPTS_ROOT):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

import run_task1_story_v61_failed_smoke as smoke  # noqa: E402
import run_task1_story_v61_full_batch as full_batch  # noqa: E402
import prepare_task1_story_v61_window_packet as window_packet  # noqa: E402
import validate_task1_story_v61_full_batch_attestation as full_attestation_gate  # noqa: E402
import validate_task1_story_v61_full_review as full_review_gate  # noqa: E402
import validate_task1_story_v61_smoke_review as smoke_review_gate  # noqa: E402
from src.novel_promotion.publish_authorization import (  # noqa: E402
    AUTHORIZATION_SCHEMA,
    validate_publish_authorization,
)


SCHEMA = "fanqie_v61_execution_readiness/v1"
ALLOWED_TYPES = {"AIGC", "解说混剪"}
DEFAULT_OUTPUT = PROJECT_ROOT / "data/qa/task1_story_v61_execution_readiness.json"
DEFAULT_SMOKE_REVIEW = PROJECT_ROOT / "data/qa/task1_story_v61_failed_smoke_review.json"
DEFAULT_SMOKE_CERTIFICATE = PROJECT_ROOT / "data/qa/task1_story_v61_smoke_review_certificate.json"
DEFAULT_FULL_ATTESTATION = PROJECT_ROOT / "data/qa/task1_story_v61_full_batch_attestation.json"
DEFAULT_CANDIDATE = PROJECT_ROOT / "data/qa/task1_story_v61_full_candidate/candidate.mp4"
DEFAULT_FULL_REVIEW = PROJECT_ROOT / "data/qa/task1_story_v61_full_review.json"
DEFAULT_FULL_CERTIFICATE = PROJECT_ROOT / "data/qa/task1_story_v61_full_review_certificate.json"
DEFAULT_PUBLISH_AUTHORIZATION = PROJECT_ROOT / "data/qa/task1_story_publish_authorization.json"
EXPECTED_FANQIE_BOOK_ID = "7656344274241326104"
EXPECTED_PROMOTION_ALIAS = "我闭着眼睛玩"
_gpu_readiness = window_packet._gpu_readiness


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _artifact(
    path: Path, *, success_result: str | None = None,
    success_field: str = "result", success_value: Any = None,
) -> dict[str, Any]:
    value = _read_json(path)
    result = value.get("result") if value else None
    accepted = value.get("accepted") if value else None
    field_value = value.get(success_field) if value else None
    expected = success_result if success_field == "result" else success_value
    return {
        "path": str(path.resolve()),
        "exists": path.is_file(),
        "valid_json_object": value is not None,
        "result": result,
        "accepted": accepted,
        "ready": bool(
            value is not None
            and ((success_field == "result" and success_result is not None and result == success_result)
                 or (success_field != "result" and field_value == expected)
                 or (success_result is None and success_field == "result" and accepted is True))
        ),
    }


def _production_validation(label: str, callback) -> dict[str, Any]:
    try:
        result = callback()
        if not isinstance(result, dict):
            raise ValueError("validator must return a JSON object")
    except Exception as exc:
        return {"label": label, "passed": False, "error": str(exc)}
    return {
        "label": label,
        "passed": result.get("accepted") is True,
        "error": "",
        "evidence": result,
    }


def _receipt_matches_live_validation(
    receipt_path: Path, validation: dict[str, Any],
) -> bool:
    """Require the stored receipt to describe the exact evidence revalidated now.

    Validators stamp a fresh ``created_at`` on every invocation, so that field is
    deliberately excluded.  Every other certificate field (including source
    paths, hashes, signer/reviewer identity, scope, and gates) must match.
    """
    receipt = _read_json(receipt_path)
    evidence = validation.get("evidence")
    if (
        validation.get("passed") is not True
        or not isinstance(receipt, dict)
        or receipt.get("accepted") is not True
        or not isinstance(evidence, dict)
    ):
        return False
    stored = {key: value for key, value in receipt.items() if key != "created_at"}
    live = {key: value for key, value in evidence.items() if key != "created_at"}
    return stored == live


def _publish_authorization_artifact(path: Path) -> dict[str, Any]:
    value = _read_json(path)
    raw_signature = value.get("signature_path") if value else None
    signature_path = (
        Path(raw_signature).resolve()
        if isinstance(raw_signature, str) and raw_signature.strip()
        else None
    )
    return {
        "path": str(path.resolve()),
        "exists": path.is_file(),
        "valid_json_object": value is not None,
        "schema_version": value.get("schema_version") if value else None,
        "signature_path": str(signature_path) if signature_path else "",
        "signature_exists": bool(signature_path and signature_path.is_file()),
        # Structural readiness is informational.  The authoritative gate below
        # still revalidates signature, lifetime, DB rows, and all bound hashes.
        "ready": bool(
            value is not None
            and value.get("schema_version") == AUTHORIZATION_SCHEMA
            and signature_path is not None
            and signature_path.is_file()
        ),
    }


def _database(path: Path, *, now: datetime) -> dict[str, Any]:
    report: dict[str, Any] = {
        "path": str(path.resolve()), "exists": path.is_file(),
        "opened_read_only": False, "eligible_tasks": [], "error": "",
    }
    if not path.is_file():
        report["error"] = "database file is missing"
        return report
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect("file:" + str(path.resolve()) + "?mode=ro", uri=True)
        report["opened_read_only"] = True
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        required = {
            "fanqie_promotion_tasks", "fanqie_books", "fanqie_video_jobs",
            "fanqie_reviews", "fanqie_publish_records", "fanqie_bindings",
        }
        if not required.issubset(tables):
            report["error"] = "closed-loop tables are missing"
            return report
        rows = connection.execute(
            """
            SELECT t.id, t.task_uuid, t.version, t.status, t.publish_type,
                   t.promotion_alias, b.fanqie_book_id, t.valid_from, t.valid_until
            FROM fanqie_promotion_tasks AS t
            JOIN fanqie_books AS b ON b.id = t.book_id
            WHERE t.status IN ('active', 'approved')
              AND t.publish_type IN ('AIGC', '解说混剪')
              AND t.promotion_alias = ?
              AND b.fanqie_book_id = ?
            ORDER BY t.id
            """,
            (EXPECTED_PROMOTION_ALIAS, EXPECTED_FANQIE_BOOK_ID),
        ).fetchall()
        current = now.astimezone(timezone.utc)
        eligible: list[dict[str, Any]] = []
        for row in rows:
            item = dict(zip(
                ("id", "task_uuid", "version", "status", "publish_type", "promotion_alias",
                 "fanqie_book_id", "valid_from", "valid_until"), row,
            ))
            try:
                def parse_db_time(value: Any) -> datetime | None:
                    if not value:
                        return None
                    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                    return (
                        parsed.replace(tzinfo=timezone.utc)
                        if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
                    )
                start = parse_db_time(item["valid_from"])
                end = parse_db_time(item["valid_until"])
            except ValueError:
                continue
            if (start is None or current >= start) and (end is None or current <= end):
                eligible.append(item)
        report["eligible_tasks"] = eligible
        report["publish_record_count"] = connection.execute(
            "SELECT COUNT(1) FROM fanqie_publish_records"
        ).fetchone()[0]
        report["binding_count"] = connection.execute(
            "SELECT COUNT(1) FROM fanqie_bindings"
        ).fetchone()[0]
    except sqlite3.Error as exc:
        report["error"] = str(exc)
    finally:
        if connection is not None:
            connection.close()
    return report


def _validate_authorization(path: Path, db_path: Path, now: datetime) -> dict[str, Any]:
    auth = _read_json(path)
    if auth is None:
        raise ValueError("publish authorization is missing or invalid JSON")
    task_binding = auth.get("task") or {}
    video_binding = auth.get("video") or {}
    task_id = task_binding.get("id")
    video_id = video_binding.get("job_id")
    key = str(auth.get("publish_idempotency_key") or "")
    if not isinstance(task_id, int) or not isinstance(video_id, int) or not key:
        raise ValueError("publish authorization database binding is incomplete")
    connection = sqlite3.connect("file:" + str(db_path.resolve()) + "?mode=ro", uri=True)
    try:
        task_row = connection.execute(
            "SELECT id,task_uuid,version,book_id,promotion_alias,publish_type,"
            "status,valid_from,valid_until "
            "FROM fanqie_promotion_tasks WHERE id=?", (task_id,),
        ).fetchone()
        video_row = connection.execute(
            "SELECT id,job_uuid,task_id,video_mode,output_path,output_sha256 "
            "FROM fanqie_video_jobs WHERE id=? AND task_id=?", (video_id, task_id),
        ).fetchone()
        if task_row is None or video_row is None:
            raise ValueError("authorized task/video no longer exists in the closed-loop database")
        book_row = connection.execute(
            "SELECT id,fanqie_book_id FROM fanqie_books WHERE id=?", (task_row[3],),
        ).fetchone()
        review_row = connection.execute(
            "SELECT machine_gate_passed,approved_sha256 FROM fanqie_reviews "
            "WHERE video_job_id=? AND decision IN ('approved','approved_with_override') "
            "ORDER BY id DESC LIMIT 1",
            (video_id,),
        ).fetchone()
        if book_row is None or review_row is None:
            raise ValueError("authorized book/approved review no longer exists")
        task = SimpleNamespace(**dict(zip(
            ("id", "task_uuid", "version", "book_id", "promotion_alias", "publish_type",
             "status", "valid_from", "valid_until"),
            task_row,
        )))
        video = SimpleNamespace(**dict(zip(
            ("id", "job_uuid", "task_id", "video_mode", "output_path", "output_sha256"),
            video_row,
        )))
        book = SimpleNamespace(id=book_row[0], fanqie_book_id=book_row[1])
        review = SimpleNamespace(
            machine_gate_passed=bool(review_row[0]), approved_sha256=review_row[1],
        )
        expected_key = f"closed-loop-publish-{task.task_uuid}-{video.job_uuid}"
        if key != expected_key:
            raise ValueError("publish authorization idempotency key is not canonical")
        return validate_publish_authorization(
            path, task=task, book=book, video_job=video, review=review,
            now=now, idempotency_key=expected_key,
        )
    finally:
        connection.close()


def audit(
    *, db_path: Path, now: datetime | None = None,
    smoke_progress: Path = smoke.DEFAULT_PROGRESS,
    smoke_review: Path = DEFAULT_SMOKE_REVIEW,
    smoke_certificate: Path = DEFAULT_SMOKE_CERTIFICATE,
    full_batch_progress: Path = full_batch.DEFAULT_PROGRESS,
    full_attestation: Path = DEFAULT_FULL_ATTESTATION,
    candidate: Path = DEFAULT_CANDIDATE,
    full_review: Path = DEFAULT_FULL_REVIEW,
    full_certificate: Path = DEFAULT_FULL_CERTIFICATE,
    publish_authorization: Path = DEFAULT_PUBLISH_AUTHORIZATION,
) -> dict[str, Any]:
    observed = now or datetime.now(timezone.utc)
    window = smoke._execution_window(observed)
    artifacts = {
        "smoke_progress": _artifact(
            smoke_progress,
            success_result="FAILED_SCENE_SMOKE_RENDERED_AWAITING_HUMAN_REVIEW",
        ),
        "smoke_review": _artifact(
            smoke_review, success_field="review_status", success_value="approved",
        ),
        "smoke_certificate": _artifact(smoke_certificate),
        "full_batch_progress": _artifact(
            full_batch_progress, success_result=full_batch.EXPECTED_RESULT,
        ),
        "full_batch_attestation": _artifact(full_attestation),
        "full_candidate": {
            "path": str(candidate.resolve()),
            "exists": candidate.is_file(),
        },
        "full_review": _artifact(
            full_review, success_field="review_status", success_value="approved",
        ),
        "full_review_certificate": _artifact(full_certificate),
        "publish_authorization": _publish_authorization_artifact(publish_authorization),
    }
    database = _database(db_path, now=observed)
    gpu = _gpu_readiness()
    smoke_progress_payload = _read_json(smoke_progress)
    full_batch_progress_payload = _read_json(full_batch_progress)
    full_batch_gates = (
        full_batch_progress_payload.get("gates")
        if isinstance(full_batch_progress_payload, dict)
        and isinstance(full_batch_progress_payload.get("gates"), dict)
        else {}
    )
    full_review_first_authorized = bool(
        isinstance(full_batch_progress_payload, dict)
        and full_batch_progress_payload.get("review_sequence") == "full_video_only"
        and full_batch_gates.get("full_review_first_authorized") is True
        and full_batch_gates.get("smoke_human_review_passed") is False
    )
    exact_smoke_boundary = bool(
        smoke_progress_payload
        and smoke_progress_payload.get("result")
        == "FAILED_SCENE_SMOKE_RENDERED_AWAITING_HUMAN_REVIEW"
        and smoke_progress_payload.get("selected_shot_ids") == list(smoke.FAILED_SHOT_IDS)
        and isinstance(smoke_progress_payload.get("shots"), list)
        and [
            item.get("scene_id") for item in smoke_progress_payload["shots"]
            if isinstance(item, dict)
        ] == list(smoke.FAILED_SHOT_IDS)
        and (smoke_progress_payload.get("gates") or {}).get(
            "failed_scene_smoke_rendered"
        ) is True
    )
    artifacts["smoke_progress"]["ready"] = exact_smoke_boundary
    artifacts["smoke_progress"]["exact_seven_shot_boundary"] = exact_smoke_boundary
    validations = {
        "smoke_human_review": _production_validation(
            "production seven-shot review validator",
            lambda: smoke_review_gate.validate_review(
                smoke_review, progress_path=smoke_progress,
            ),
        ),
        "full_render_attestation": _production_validation(
            "production 19-shot render-attestation validator",
            lambda: full_attestation_gate.validate_attestation(full_batch_progress),
        ),
        "full_video_human_review": _production_validation(
            "production whole-video human-review validator",
            lambda: full_review_gate.validate_review(full_review),
        ),
        "publish_authorization": _production_validation(
            "production publish-authorization validator",
            lambda: _validate_authorization(publish_authorization, db_path, observed),
        ),
    }
    receipt_bindings = {
        "smoke_human_review": smoke_certificate,
        "full_render_attestation": full_attestation,
        "full_video_human_review": full_certificate,
    }
    for validation_name, receipt_path in receipt_bindings.items():
        validations[validation_name]["receipt_matches_live_validation"] = (
            _receipt_matches_live_validation(
                receipt_path, validations[validation_name],
            )
        )
    gates = {
        "tts_gpu_window_open": window["open"],
        "gpu_resource_ready": gpu.get("ready") is True,
        "smoke_rendered": exact_smoke_boundary,
        "smoke_human_review_passed": bool(
            artifacts["smoke_certificate"]["ready"]
            and validations["smoke_human_review"]["receipt_matches_live_validation"]
        ),
        "full_review_first_authorized": full_review_first_authorized,
        "full_19_shots_rendered": artifacts["full_batch_progress"]["ready"],
        "full_render_attested": bool(
            artifacts["full_batch_attestation"]["ready"]
            and validations["full_render_attestation"]["receipt_matches_live_validation"]
        ),
        "full_candidate_exists": artifacts["full_candidate"]["exists"],
        "full_video_human_review_passed": bool(
            artifacts["full_review_certificate"]["ready"]
            and validations["full_video_human_review"]["receipt_matches_live_validation"]
        ),
        "matching_aigc_or_commentary_task_present": len(database["eligible_tasks"]) == 1,
        "signed_publish_authorization_present": validations["publish_authorization"]["passed"],
        "douyin_upload_allowed": False,
        "fanqie_backfill_allowed": False,
    }
    if (
        not gates["full_review_first_authorized"]
        and not gates["smoke_rendered"]
        and not gates["gpu_resource_ready"]
    ):
        next_action = "wait_for_gpu_resource_before_seven_shot_render"
    elif not gates["full_review_first_authorized"] and not gates["smoke_rendered"]:
        next_action = "render_seven_shot_smoke_to_new_immutable_paths"
    elif (
        not gates["full_review_first_authorized"]
        and not gates["smoke_human_review_passed"]
    ):
        next_action = "complete_seven_shot_review_in_streamlit"
    elif not gates["full_19_shots_rendered"] and not gates["gpu_resource_ready"]:
        next_action = "wait_for_gpu_resource_before_remaining_twelve_shots"
    elif not gates["full_19_shots_rendered"]:
        next_action = "render_remaining_twelve_shots"
    elif not gates["full_render_attested"]:
        next_action = "validate_full_render_integrity"
    elif not gates["full_candidate_exists"]:
        next_action = "compose_immutable_full_candidate"
    elif not gates["full_video_human_review_passed"]:
        next_action = "complete_full_video_review_in_streamlit"
    elif not gates["matching_aigc_or_commentary_task_present"]:
        next_action = "obtain_one_matching_active_aigc_or_commentary_fanqie_task"
    elif not gates["signed_publish_authorization_present"]:
        next_action = "capture_fresh_live_list_and_issue_15_minute_publish_authorization"
    else:
        next_action = "publish_only_via_authorized_p3_command"
    return {
        "schema_version": SCHEMA,
        "observed_at": observed.astimezone(timezone.utc).isoformat(),
        "execution_window": window,
        "gpu": gpu,
        "database": database,
        "artifacts": artifacts,
        "production_validations": validations,
        "gates": gates,
        "next_action": next_action,
        "forbidden_side_effects": {
            "tts_calls": 0, "gpu_calls": 0, "database_writes": 0,
            "browser_operations": 0, "douyin_uploads": 0, "fanqie_backfills": 0,
        },
    }


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit V6.1 execution readiness without side effects.")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--smoke-progress", type=Path, default=smoke.DEFAULT_PROGRESS)
    parser.add_argument("--smoke-review", type=Path, default=DEFAULT_SMOKE_REVIEW)
    parser.add_argument("--smoke-certificate", type=Path, default=DEFAULT_SMOKE_CERTIFICATE)
    parser.add_argument("--full-batch-progress", type=Path, default=full_batch.DEFAULT_PROGRESS)
    parser.add_argument("--full-attestation", type=Path, default=DEFAULT_FULL_ATTESTATION)
    parser.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--full-review", type=Path, default=DEFAULT_FULL_REVIEW)
    parser.add_argument("--full-certificate", type=Path, default=DEFAULT_FULL_CERTIFICATE)
    parser.add_argument("--publish-authorization", type=Path, default=DEFAULT_PUBLISH_AUTHORIZATION)
    args = parser.parse_args(argv)
    report = audit(
        db_path=args.db.resolve(), smoke_progress=args.smoke_progress.resolve(),
        smoke_review=args.smoke_review.resolve(),
        smoke_certificate=args.smoke_certificate.resolve(),
        full_batch_progress=args.full_batch_progress.resolve(),
        full_attestation=args.full_attestation.resolve(), candidate=args.candidate.resolve(),
        full_review=args.full_review.resolve(), full_certificate=args.full_certificate.resolve(),
        publish_authorization=args.publish_authorization.resolve(),
    )
    _write_atomic(args.output.resolve(), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
