from __future__ import annotations

"""Validate the authenticated frontend whole-video human review.

Acceptance makes the local candidate eligible for the later matching-Fanqie-task
gate.  It never authorizes upload or backfill by itself.
"""

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPTS_ROOT = Path(__file__).resolve().parent
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import prepare_task1_story_v61_full_review_packet as packet_module
import validate_task1_story_v61_full_batch_attestation as render_attestation_gate
import validate_task1_story_v61_smoke_review as smoke_review_gate


REVIEW_SCHEMA = packet_module.REVIEW_SCHEMA
PACKET_SCHEMA = packet_module.PACKET_SCHEMA
CERTIFICATE_SCHEMA = "fanqie_v61_full_review_certificate/v2"
EXPECTED_PLAN_SHA256 = packet_module.EXPECTED_PLAN_SHA256
DEFAULT_REVIEW = packet_module.DEFAULT_REVIEW
DEFAULT_CERTIFICATE = Path(r"D:\IT\ai_douyin\data\qa\task1_story_v61_full_review_certificate.json")


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


def _parse_timestamp(value: Any, name: str) -> datetime:
    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must include a timezone")
    if parsed > datetime.now(timezone.utc).astimezone(parsed.tzinfo):
        raise ValueError(f"{name} cannot be in the future")
    return parsed


def validate_review(
    review_path: str | Path,
    *,
    probe_video=packet_module._probe,
    extract_frame=packet_module._extract,
    build_contact=packet_module._contact,
    validate_render_attestation=render_attestation_gate.validate_attestation,
    validate_smoke_review=smoke_review_gate.validate_review,
) -> dict[str, Any]:
    review_file = Path(review_path).resolve()
    review, review_bytes, review_sha = _load_json_bytes(review_file)
    if review.get("schema_version") != REVIEW_SCHEMA:
        raise ValueError("whole-video review schema mismatch")
    if review.get("task_id") != 1 or review.get("scope") != "full_19_beat_candidate":
        raise ValueError("whole-video review task/scope mismatch")
    if str(review.get("plan_sha256") or "").upper() != EXPECTED_PLAN_SHA256:
        raise ValueError("whole-video review plan SHA mismatch")
    if review.get("review_status") != "approved" or review.get("decision") != "approved":
        raise ValueError("whole-video review must be approved")
    if review.get("decision_source") != "authenticated_streamlit_frontend":
        raise ValueError("whole-video review was not approved by the authenticated frontend")
    reviewer = str(review.get("reviewer") or "").strip()
    reviewer_id = str(review.get("reviewer_id") or reviewer).strip()
    if len(reviewer) < 2 or len(reviewer_id) < 2:
        raise ValueError("whole-video reviewer identity is invalid")
    reviewed_at = _parse_timestamp(review.get("reviewed_at"), "reviewed_at")
    checks = review.get("checks")
    if not isinstance(checks, dict) or set(checks) != set(packet_module.GLOBAL_CHECKS):
        raise ValueError("whole-video review checks schema mismatch")
    for key in packet_module.GLOBAL_CHECKS:
        if checks.get(key) is not True:
            raise ValueError(f"checks.{key} must be true")

    machine_path = Path(str(review.get("machine_review_packet_path") or "")).resolve()
    machine, _, machine_sha = _load_json_bytes(machine_path)
    if machine_sha != str(review.get("machine_review_packet_sha256") or "").upper():
        raise ValueError("whole-video machine packet SHA mismatch")
    if machine.get("schema_version") != PACKET_SCHEMA:
        raise ValueError("whole-video machine packet schema mismatch")
    if machine.get("task_id") != 1 or machine.get("scope") != "full_19_beat_candidate":
        raise ValueError("whole-video machine packet task/scope mismatch")
    if str(machine.get("plan_sha256") or "").upper() != EXPECTED_PLAN_SHA256:
        raise ValueError("whole-video machine packet plan SHA mismatch")
    if machine.get("machine_gate_scope") != "whole_video_file_integrity_and_media_structure_only":
        raise ValueError("whole-video machine packet gate scope mismatch")
    if machine.get("human_visual_audio_editorial_review_required") is not True:
        raise ValueError("whole-video machine packet must require human review")
    if machine.get("machine_gate_passed") is not True:
        raise ValueError("whole-video machine gate is not passed")
    for key in (
        "human_full_video_review_completed", "matching_fanqie_task_confirmed",
        "douyin_upload_allowed", "fanqie_backfill_allowed",
    ):
        if machine.get(key) is not False:
            raise ValueError(f"whole-video machine packet {key} must remain false")

    audit_path = Path(str(machine.get("candidate_audit_path") or "")).resolve()
    audit, _, audit_sha = _load_json_bytes(audit_path)
    if audit_sha != str(machine.get("candidate_audit_sha256") or "").upper():
        raise ValueError("whole-video candidate audit SHA mismatch")
    if audit.get("schema_version") != packet_module.AUDIT_SCHEMA:
        raise ValueError("whole-video candidate audit schema mismatch")
    if audit.get("shot_count") != 19 or audit.get("machine_composition_gate_passed") is not True:
        raise ValueError("whole-video candidate audit does not prove 19-shot composition")
    for key in (
        "human_full_video_review_completed", "matching_fanqie_task_confirmed",
        "douyin_upload_allowed", "fanqie_backfill_allowed",
    ):
        if audit.get(key) is not False:
            raise ValueError(f"whole-video candidate audit {key} must remain false")
    source_progress_path = Path(str(audit.get("source_progress_path") or "")).resolve()
    render_attestation = validate_render_attestation(source_progress_path)
    if render_attestation.get("accepted") is not True:
        raise ValueError("full-batch render attestation is not accepted")
    if str(render_attestation.get("progress_sha256") or "").upper() != str(
        audit.get("source_progress_sha256") or ""
    ).upper():
        raise ValueError("candidate audit render-attestation progress SHA mismatch")
    renderer_id = str(render_attestation.get("signer_id") or "").strip()
    if not renderer_id or renderer_id != str(audit.get("render_attestation_signer_id") or "").strip():
        raise ValueError("candidate audit renderer identity mismatch")
    receipt_path = Path(
        str(render_attestation.get("attestation_receipt_path") or "")
    ).resolve()
    receipt_sha = str(
        render_attestation.get("attestation_receipt_sha256") or ""
    ).upper()
    if (
        audit.get("render_attestation_receipt_schema")
        != render_attestation_gate.RECEIPT_SCHEMA
        or Path(str(audit.get("render_attestation_receipt_path") or "")).resolve()
        != receipt_path
        or str(audit.get("render_attestation_receipt_sha256") or "").upper()
        != receipt_sha
    ):
        raise ValueError("candidate audit render receipt binding mismatch")
    if renderer_id == reviewer_id:
        raise ValueError("whole-video renderer and frontend reviewer must be different identities")
    review_sequence = str(audit.get("review_sequence") or "smoke_then_full")
    if review_sequence == "full_video_only":
        if audit.get("smoke_human_review_claimed") is not False:
            raise ValueError("full-review-first audit must not claim smoke human approval")
        smoke_machine_path = Path(
            str(audit.get("smoke_machine_packet_path") or "")
        ).resolve()
        smoke_machine_sha = str(
            audit.get("smoke_machine_packet_sha256") or ""
        ).upper()
        if not smoke_machine_path.is_file() or _sha256(smoke_machine_path) != smoke_machine_sha:
            raise ValueError("full-review-first smoke machine packet changed")
        smoke_machine = _load_json_bytes(smoke_machine_path)[0]
        if (
            smoke_machine.get("schema_version")
            != "fanqie_v61_smoke_machine_review_packet/v2"
            or smoke_machine.get("machine_gate_passed") is not True
        ):
            raise ValueError("full-review-first smoke machine packet is invalid")
        smoke_candidates = [
            {"scene_id": item.get("scene_id"), "path": item.get("video_path"),
             "sha256": item.get("video_sha256")}
            for item in smoke_machine.get("candidates", []) if isinstance(item, dict)
        ]
        expected_reused_source = "machine_verified_unreviewed_smoke_candidate"
    else:
        smoke_review_path = Path(str(audit.get("smoke_review_path") or "")).resolve()
        smoke_progress_path = Path(str(audit.get("smoke_progress_path") or "")).resolve()
        smoke_certificate = validate_smoke_review(
            smoke_review_path, progress_path=smoke_progress_path,
        )
        if str(smoke_certificate.get("review_sha256") or "").upper() != str(
            audit.get("smoke_review_sha256") or ""
        ).upper():
            raise ValueError("candidate audit smoke-review SHA mismatch")
        if str(smoke_certificate.get("progress_sha256") or "").upper() != str(
            audit.get("smoke_progress_sha256") or ""
        ).upper():
            raise ValueError("candidate audit smoke-progress SHA mismatch")
        smoke_candidates = smoke_certificate.get("candidates", [])
        expected_reused_source = "frontend_human_approved_smoke_candidate"
    revalidated_candidates = [
        {
            "scene_id": item.get("scene_id"),
            "path": str(Path(str(item.get("path") or "")).resolve()),
            "sha256": str(item.get("sha256") or "").upper(),
        }
        for item in smoke_candidates
        if isinstance(item, dict)
    ]
    if len(revalidated_candidates) != 7 or revalidated_candidates != audit.get(
        "smoke_review_candidates"
    ):
        raise ValueError("candidate audit reused shots differ from bound smoke evidence")
    audit_shots = audit.get("shots")
    if not isinstance(audit_shots, list) or len(audit_shots) != 19:
        raise ValueError("candidate audit must contain exactly 19 source shots")
    audit_by_id = {
        item.get("scene_id"): item for item in audit_shots if isinstance(item, dict)
    }
    for accepted in revalidated_candidates:
        source = audit_by_id.get(accepted["scene_id"])
        if not isinstance(source, dict):
            raise ValueError("bound smoke candidate missing from final candidate audit")
        if source.get("source") != expected_reused_source:
            raise ValueError("bound smoke candidate source changed before final review")
        if Path(str(source.get("video_path") or "")).resolve() != Path(
            accepted["path"]
        ).resolve() or str(source.get("video_sha256") or "").upper() != accepted["sha256"]:
            raise ValueError("bound smoke candidate provenance mismatch at final review")
    manifest_path = Path(str(machine.get("story_manifest_path") or "")).resolve()
    subtitle_path = Path(str(machine.get("subtitle_path") or "")).resolve()
    if not manifest_path.is_file() or _sha256(manifest_path) != str(
        machine.get("story_manifest_sha256") or ""
    ).upper():
        raise ValueError("whole-video story manifest SHA mismatch")
    if not subtitle_path.is_file() or _sha256(subtitle_path) != str(
        machine.get("subtitle_sha256") or ""
    ).upper():
        raise ValueError("whole-video subtitle SHA mismatch")
    if Path(str(audit.get("story_manifest_path") or "")).resolve() != manifest_path:
        raise ValueError("candidate audit story manifest path mismatch")
    if str(audit.get("story_manifest_sha256") or "").upper() != _sha256(manifest_path):
        raise ValueError("candidate audit story manifest SHA mismatch")
    if Path(str(audit.get("subtitle_path") or "")).resolve() != subtitle_path:
        raise ValueError("candidate audit subtitle path mismatch")
    if str(audit.get("subtitle_sha256") or "").upper() != _sha256(subtitle_path):
        raise ValueError("candidate audit subtitle SHA mismatch")

    candidate = Path(str(review.get("candidate_path") or "")).resolve()
    if candidate != Path(str(machine.get("candidate_path") or "")).resolve():
        raise ValueError("whole-video candidate path mismatch")
    candidate_sha = _sha256(candidate) if candidate.is_file() else ""
    if not candidate_sha or candidate_sha != str(review.get("candidate_sha256") or "").upper():
        raise ValueError("whole-video candidate SHA mismatch with frontend review")
    if candidate_sha != str(machine.get("candidate_sha256") or "").upper():
        raise ValueError("whole-video candidate SHA mismatch with machine packet")
    if Path(str(audit.get("candidate_path") or "")).resolve() != candidate:
        raise ValueError("candidate audit whole-video path mismatch")
    if candidate_sha != str(audit.get("candidate_sha256") or "").upper():
        raise ValueError("candidate audit whole-video SHA mismatch")
    if str(review.get("playback_candidate_sha256") or "").upper() != candidate_sha:
        raise ValueError("playback candidate SHA mismatch")
    contact = Path(str(review.get("contact_sheet_path") or "")).resolve()
    if contact != Path(str(machine.get("contact_sheet_path") or "")).resolve():
        raise ValueError("whole-video contact-sheet path mismatch")
    contact_sha = _sha256(contact) if contact.is_file() else ""
    if not contact_sha or contact_sha != str(review.get("contact_sheet_sha256") or "").upper():
        raise ValueError("whole-video contact-sheet SHA mismatch with frontend review")
    if contact_sha != str(machine.get("contact_sheet_sha256") or "").upper():
        raise ValueError("whole-video contact-sheet SHA mismatch with machine packet")

    frames = machine.get("frames")
    if not isinstance(frames, list) or len(frames) != len(packet_module.SAMPLE_FRACTIONS):
        raise ValueError("whole-video machine packet sample count mismatch")
    frame_hashes: set[str] = set()
    verification_root = Path(tempfile.mkdtemp(prefix="fanqie_v61_full_review_"))
    extracted_items: list[tuple[str, Path]] = []
    try:
        for position, (frame, fraction) in enumerate(
            zip(frames, packet_module.SAMPLE_FRACTIONS, strict=True), start=1
        ):
            if not isinstance(frame, dict) or frame.get("position") != position:
                raise ValueError("whole-video review frame position mismatch")
            if abs(float(frame.get("fraction")) - fraction) > 0.0001:
                raise ValueError("whole-video review frame fraction mismatch")
            expected_timestamp = float(machine.get("probe", {}).get("duration_seconds")) * fraction
            if abs(float(frame.get("timestamp_seconds")) - expected_timestamp) > 0.001:
                raise ValueError("whole-video review frame timestamp mismatch")
            frame_path = Path(str(frame.get("path") or "")).resolve()
            frame_sha = _sha256(frame_path) if frame_path.is_file() else ""
            if not frame_sha or frame_sha != str(frame.get("sha256") or "").upper():
                raise ValueError("whole-video review frame SHA mismatch")
            extracted = verification_root / f"frame_{position:02d}.png"
            extract_frame(candidate, extracted, expected_timestamp)
            if _sha256(extracted) != frame_sha:
                raise ValueError("whole-video review frame is not derived from candidate")
            frame_hashes.add(frame_sha)
            extracted_items.append((f"{position:02d} / {expected_timestamp:.2f}s", extracted))
        if len(frame_hashes) != len(frames):
            raise ValueError("whole-video review frames must be distinct")
        rebuilt_contact = verification_root / "contact_sheet.png"
        build_contact(extracted_items, rebuilt_contact)
        if _sha256(rebuilt_contact) != contact_sha:
            raise ValueError("whole-video contact sheet is not derived from candidate")
    finally:
        shutil.rmtree(verification_root, ignore_errors=True)

    pre_probe_sha = candidate_sha
    probe = probe_video(candidate)
    if _sha256(candidate) != pre_probe_sha:
        raise ValueError("whole-video candidate changed during probe")
    if abs(float(probe["duration_seconds"]) - packet_module.EXPECTED_DURATION) > 0.30:
        raise ValueError("whole-video duration outside tolerance")
    if abs(float(probe["fps"]) - 50.0) > 0.01 or probe.get("audio_present") is not True:
        raise ValueError("whole-video media structure is invalid")
    playback_started = _parse_timestamp(review.get("playback_started_at"), "playback_started_at")
    playback_finished = _parse_timestamp(review.get("playback_finished_at"), "playback_finished_at")
    if playback_finished < playback_started:
        raise ValueError("playback_finished_at cannot precede playback_started_at")
    if (playback_finished - playback_started).total_seconds() < float(probe["duration_seconds"]) - 0.25:
        raise ValueError("playback interval does not cover the complete candidate duration")
    if playback_finished > reviewed_at:
        raise ValueError("playback cannot finish after reviewed_at")
    attestation = review.get("frontend_attestation")
    if not isinstance(attestation, dict):
        raise ValueError("frontend review attestation is missing")
    expected_confirmations = {
        f"check:{key}" for key in packet_module.GLOBAL_CHECKS
    }
    confirmations = attestation.get("confirmations")
    if not isinstance(confirmations, dict) or set(confirmations) != expected_confirmations:
        raise ValueError("frontend review confirmation boundary mismatch")
    if any(confirmations.get(key) is not True for key in expected_confirmations):
        raise ValueError("frontend review confirmation is incomplete")
    if attestation.get("all_required_checks_confirmed") is not True:
        raise ValueError("frontend review aggregate confirmation is missing")
    if sorted(attestation.get("required_checks") or []) != sorted(expected_confirmations):
        raise ValueError("frontend review required-check record mismatch")
    if [str(value or "").upper() for value in attestation.get("video_sha256s") or []] != [candidate_sha]:
        raise ValueError("frontend review candidate hash binding mismatch")
    if str(attestation.get("machine_packet_sha256") or "").upper() != machine_sha:
        raise ValueError("frontend review machine-packet hash binding mismatch")
    actual_playback = (playback_finished - playback_started).total_seconds()
    if abs(float(attestation.get("actual_playback_seconds") or 0) - actual_playback) > 0.01:
        raise ValueError("frontend review playback record mismatch")
    if abs(float(attestation.get("required_playback_seconds") or 0) - float(probe["duration_seconds"])) > 0.30:
        raise ValueError("frontend review required playback duration mismatch")
    created_at = _parse_timestamp(machine.get("created_at"), "machine.created_at")
    if reviewed_at < created_at.astimezone(reviewed_at.tzinfo):
        raise ValueError("whole-video review predates machine evidence")

    return {
        "schema_version": CERTIFICATE_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "accepted": True, "task_id": 1, "scope": "full_19_beat_candidate",
        "plan_sha256": EXPECTED_PLAN_SHA256,
        "reviewer": reviewer, "reviewer_id": reviewer_id,
        "reviewed_at": review.get("reviewed_at"),
        "review_path": str(review_file), "review_sha256": review_sha,
        "approval_source": "authenticated_streamlit_frontend",
        "machine_review_packet_path": str(machine_path),
        "machine_review_packet_sha256": machine_sha,
        "candidate_audit_path": str(audit_path), "candidate_audit_sha256": audit_sha,
        "story_manifest_path": str(manifest_path),
        "story_manifest_sha256": _sha256(manifest_path),
        "subtitle_path": str(subtitle_path), "subtitle_sha256": _sha256(subtitle_path),
        "candidate_path": str(candidate), "candidate_sha256": candidate_sha,
        "contact_sheet_path": str(contact), "contact_sheet_sha256": contact_sha,
        "probe": probe,
        "renderer_id": renderer_id,
        "playback_started_at": review.get("playback_started_at"),
        "playback_finished_at": review.get("playback_finished_at"),
        "non_authoritative_receipt": True,
        "must_revalidate_frontend_review": True,
        "gates": {
            "full_video_machine_gate_passed": True,
            "full_video_human_review_passed": True,
            "matching_fanqie_task_required": True,
            "matching_fanqie_task_confirmed": False,
            "douyin_upload_allowed": False,
            "fanqie_backfill_allowed": False,
        },
    }


def _write_new(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb"):
            pass
    except FileExistsError as exc:
        raise ValueError(f"Refusing to overwrite whole-video review receipt: {path}") from exc
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        path.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate frontend-approved V6.1 whole-video review.")
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--output", type=Path, default=DEFAULT_CERTIFICATE)
    args = parser.parse_args(argv)
    try:
        certificate = validate_review(args.review.resolve())
    except ValueError as exc:
        print(json.dumps({
            "accepted": False, "error": str(exc),
            "matching_fanqie_task_confirmed": False,
            "douyin_upload_allowed": False, "fanqie_backfill_allowed": False,
        }, ensure_ascii=False, indent=2))
        return 2
    try:
        _write_new(args.output.resolve(), certificate)
    except ValueError as exc:
        print(json.dumps({
            "accepted": False, "error": str(exc),
            "matching_fanqie_task_confirmed": False,
            "douyin_upload_allowed": False, "fanqie_backfill_allowed": False,
        }, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(certificate, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
