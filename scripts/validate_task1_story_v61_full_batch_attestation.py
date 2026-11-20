from __future__ import annotations

"""Verify the 19-shot render progress and its immutable machine receipt.

No user-held signing key is required.  The execute runner writes the final
progress first, then creates one exclusive receipt that binds its SHA-256,
renderer identity, plan and exact 19-shot boundary.
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPTS_ROOT = Path(__file__).resolve().parent
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import run_task1_story_v61_failed_smoke as smoke
import run_task1_story_v61_full_batch as full_batch


CERTIFICATE_SCHEMA = "fanqie_v61_full_batch_attestation/v1"
RECEIPT_SCHEMA = full_batch.RENDER_ATTESTATION_RECEIPT_SCHEMA
RECEIPT_KEYS = {
    "schema_version", "created_at", "task_id", "scope", "result",
    "receipt_path", "progress_path", "progress_sha256", "renderer_id",
    "plan_path", "plan_sha256", "shot_count",
}
FORBIDDEN_SIDE_EFFECT_KEYS = {
    "database_writes", "browser_operations", "douyin_uploads", "fanqie_backfills",
}
DEFAULT_PROGRESS = full_batch.DEFAULT_PROGRESS
DEFAULT_OUTPUT = Path(r"D:\IT\ai_douyin\data\qa\task1_story_v61_full_batch_attestation.json")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _load_json_bytes(path: Path) -> tuple[dict[str, Any], bytes, str]:
    if not path.is_file():
        raise ValueError(f"JSON file not found: {path}")
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value, raw, hashlib.sha256(raw).hexdigest().upper()


def _parse_timestamp(value: Any, field: str) -> datetime:
    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    if parsed > datetime.now(timezone.utc).astimezone(parsed.tzinfo):
        raise ValueError(f"{field} cannot be in the future")
    return parsed


def validate_attestation(progress_path: str | Path) -> dict[str, Any]:
    progress_file = Path(progress_path).resolve()
    progress, raw, progress_sha = _load_json_bytes(progress_file)
    if progress.get("schema_version") != "fanqie_v61_full_batch_progress/v2":
        raise ValueError("full-batch progress schema mismatch")
    if progress.get("task_id") != 1 or progress.get("scope") != "full_19_beat_render":
        raise ValueError("full-batch progress task/scope mismatch")
    if progress.get("result") != full_batch.EXPECTED_RESULT:
        raise ValueError("full-batch progress does not prove a completed render")
    if progress.get("render_attestation_required") is not True:
        raise ValueError("full-batch render attestation must be required")
    if progress.get("render_attestation_completed") is not True:
        raise ValueError("full-batch render attestation is not completed")
    signer_id = str(progress.get("render_signer_id") or "").strip()
    if not full_batch.SIGNER_ID_PATTERN.fullmatch(signer_id):
        raise ValueError("full-batch renderer identity is invalid")
    if progress.get("render_attestation_namespace") != full_batch.RENDER_ATTESTATION_NAMESPACE:
        raise ValueError("full-batch render receipt namespace mismatch")
    receipt_path = Path(
        str(progress.get("render_attestation_receipt_path") or "")
    ).resolve()
    if receipt_path != full_batch._render_attestation_receipt_path(progress_file):
        raise ValueError("full-batch render receipt path is not deterministic")
    receipt, _, receipt_sha = _load_json_bytes(receipt_path)
    if set(receipt) != RECEIPT_KEYS:
        raise ValueError("render attestation receipt field boundary mismatch")
    if receipt.get("schema_version") != RECEIPT_SCHEMA:
        raise ValueError("render attestation receipt schema mismatch")
    if receipt.get("task_id") != 1 or receipt.get("scope") != "full_19_beat_render":
        raise ValueError("render attestation receipt task/scope mismatch")
    if receipt.get("result") != full_batch.EXPECTED_RESULT:
        raise ValueError("render attestation receipt result mismatch")
    receipt_created = _parse_timestamp(
        receipt.get("created_at"), "render attestation receipt created_at"
    )
    progress_finished = _parse_timestamp(
        progress.get("finished_at"), "full-batch progress finished_at"
    )
    if receipt_created < progress_finished.astimezone(receipt_created.tzinfo):
        raise ValueError("render attestation receipt predates final progress")
    if Path(str(receipt.get("receipt_path") or "")).resolve() != receipt_path:
        raise ValueError("render attestation receipt self-path mismatch")
    if Path(str(receipt.get("progress_path") or "")).resolve() != progress_file:
        raise ValueError("render attestation receipt progress path mismatch")
    if str(receipt.get("progress_sha256") or "").upper() != progress_sha:
        raise ValueError("render attestation receipt progress SHA mismatch")
    if str(receipt.get("renderer_id") or "").strip() != signer_id:
        raise ValueError("render attestation receipt renderer mismatch")
    if receipt.get("shot_count") != 19:
        raise ValueError("render attestation receipt shot_count mismatch")

    plan_path = Path(str(progress.get("plan_path") or "")).resolve()
    if not plan_path.is_file() or _sha256(plan_path) != smoke.EXPECTED_PLAN_SHA256:
        raise ValueError("full-batch plan is missing or changed")
    plans = smoke._load_structured_scene_plan(str(plan_path), "")
    if len(plans) != 19:
        raise ValueError("full-batch plan must contain 19 beats")
    if Path(str(receipt.get("plan_path") or "")).resolve() != plan_path:
        raise ValueError("render attestation receipt plan path mismatch")
    if str(receipt.get("plan_sha256") or "").upper() != _sha256(plan_path):
        raise ValueError("render attestation receipt plan SHA mismatch")
    shots = progress.get("shots")
    if not isinstance(shots, list) or len(shots) != 19:
        raise ValueError("full-batch progress must contain 19 shots")
    if tuple(item.get("scene_id") for item in shots if isinstance(item, dict)) != tuple(
        plan.scene_id for plan in plans
    ):
        raise ValueError("full-batch shot order mismatch")
    gates = progress.get("gates")
    if not isinstance(gates, dict):
        raise ValueError("full-batch gates are missing")
    for key in (
        "smoke_machine_gate_passed", "full_audio_prepared",
        "full_runtime_preflight_passed", "full_19_shots_rendered",
    ):
        if gates.get(key) is not True:
            raise ValueError(f"full-batch gate {key} is not true")
    review_sequence = str(progress.get("review_sequence") or "smoke_then_full")
    if review_sequence == "full_video_only":
        if gates.get("smoke_human_review_passed") is not False or gates.get("full_review_first_authorized") is not True:
            raise ValueError("full-review-first gate boundary mismatch")
    elif gates.get("smoke_human_review_passed") is not True:
        raise ValueError("full-batch gate smoke_human_review_passed is not true")
    for key in (
        "full_video_human_approval_obtained", "matching_fanqie_task_confirmed",
        "publish_allowed", "fanqie_backfill_allowed",
    ):
        if gates.get(key) is not False:
            raise ValueError(f"full-batch gate {key} must remain false")
    if gates.get("full_video_human_review_required") is not True:
        raise ValueError("full-batch final human review must remain required")
    side_effects = progress.get("forbidden_side_effects")
    if (
        not isinstance(side_effects, dict)
        or set(side_effects) != FORBIDDEN_SIDE_EFFECT_KEYS
        or any(side_effects.get(key) != 0 for key in FORBIDDEN_SIDE_EFFECT_KEYS)
    ):
        raise ValueError("full-batch forbidden platform side effects must remain zero")
    for position, (plan, shot) in enumerate(zip(plans, shots, strict=True), start=1):
        if shot.get("position") != position or shot.get("missing"):
            raise ValueError(f"{plan.scene_id}: shot position/missing mismatch")
        assets = shot.get("assets")
        if not isinstance(assets, list) or len(assets) != 1:
            raise ValueError(f"{plan.scene_id}: shot must contain one asset")
        asset = assets[0]
        if not isinstance(asset, dict) or asset.get("scene_id") != plan.scene_id:
            raise ValueError(f"{plan.scene_id}: asset identity mismatch")
        expected_source = (
            ("machine_verified_unreviewed_smoke_candidate"
             if review_sequence == "full_video_only"
             else "frontend_human_approved_smoke_candidate")
            if plan.scene_id in smoke.FAILED_SHOT_IDS else "new_full_batch_render"
        )
        if shot.get("source") != expected_source:
            raise ValueError(f"{plan.scene_id}: render source mismatch")
        video = Path(str(asset.get("video_path") or "")).resolve()
        metadata = asset.get("metadata")
        if not video.is_file() or not isinstance(metadata, dict):
            raise ValueError(f"{plan.scene_id}: video/metadata is missing")
        if _sha256(video) != str(metadata.get("final_sha256") or "").upper():
            raise ValueError(f"{plan.scene_id}: video SHA mismatch")
        audio = Path(str(metadata.get("dialogue_audio_path") or "")).resolve()
        if not audio.is_file():
            raise ValueError(f"{plan.scene_id}: audio is missing")
        if _sha256(audio) != str(metadata.get("dialogue_audio_sha256") or "").upper():
            raise ValueError(f"{plan.scene_id}: audio SHA mismatch")

    return {
        "schema_version": CERTIFICATE_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "accepted": True, "task_id": 1, "scope": "full_19_beat_render",
        "signer_id": signer_id,
        "renderer_id": signer_id,
        "attestation_receipt_schema": RECEIPT_SCHEMA,
        "attestation_receipt_path": str(receipt_path),
        "attestation_receipt_sha256": receipt_sha,
        "attestation_namespace": full_batch.RENDER_ATTESTATION_NAMESPACE,
        "progress_path": str(progress_file), "progress_sha256": progress_sha,
        "plan_path": str(plan_path), "plan_sha256": _sha256(plan_path),
        "shot_count": 19,
        "gates": {
            "render_provenance_attested": True,
            "full_video_human_review_required": True,
            "full_video_human_review_passed": False,
            "matching_fanqie_task_confirmed": False,
            "douyin_upload_allowed": False,
            "fanqie_backfill_allowed": False,
        },
    }


def _write_new(path: Path, payload: dict[str, Any]) -> None:
    """Write a certificate exclusively so it cannot replace source evidence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
    except FileExistsError as exc:
        raise ValueError(f"Refusing to overwrite attestation evidence: {path}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify V6.1 full-batch render progress.")
    parser.add_argument("--progress", type=Path, default=DEFAULT_PROGRESS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        certificate = validate_attestation(args.progress.resolve())
    except ValueError as exc:
        print(json.dumps({
            "accepted": False, "error": str(exc),
            "full_video_human_review_passed": False,
            "douyin_upload_allowed": False, "fanqie_backfill_allowed": False,
        }, ensure_ascii=False, indent=2))
        return 2
    try:
        _write_new(args.output.resolve(), certificate)
    except ValueError as exc:
        print(json.dumps({
            "accepted": False, "error": str(exc),
            "full_video_human_review_passed": False,
            "douyin_upload_allowed": False, "fanqie_backfill_allowed": False,
        }, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(certificate, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
