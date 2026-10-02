from __future__ import annotations

"""Validate the machine + human review gate for task-1 V6.1 smoke clips.

The validator is deliberately platform-free.  It reads the render progress,
re-hashes and probes every candidate clip, verifies the exact seven-shot
boundary, then checks every human review field.  Acceptance authorizes only
the next local step (rendering all 19 reviewed beats); it never authorizes a
Douyin upload or Fanqie backfill.
"""

import argparse
import hashlib
import json
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = "fanqie_v61_failed_smoke_human_review/v1"
PROGRESS_SCHEMA = "fanqie_v61_failed_smoke_progress/v1"
CERTIFICATE_SCHEMA = "fanqie_v61_smoke_review_certificate/v2"
MACHINE_PACKET_SCHEMA = "fanqie_v61_smoke_machine_review_packet/v2"
EXPECTED_PLAN_SHA256 = (
    "D2C15C86B0AC57BE8CD26EF687C65C049D64B2069568707C8B699AE6D5828CB4"
)
SHOT_DURATIONS = {
    "b01_boast": 2.8,
    "b03_object_question": 1.8,
    "b04_confused_answer": 1.5,
    "b05_age_burst": 2.4,
    "b06_pull_away": 2.0,
    "b07_protest": 2.3,
    "b08_offer_one": 1.3,
}
SHOT_IDS = tuple(SHOT_DURATIONS)
SHOT_REVIEW_CHECKS = (
    "identity_consistent",
    "action_matches_reviewed_beat",
    "emotion_change_is_readable",
    "lip_sync_is_acceptable",
    "voice_emotion_and_pace_are_natural",
    "camera_motion_is_controlled",
    "anatomy_and_hands_are_plausible",
    "no_forbidden_visual_elements",
    "duration_within_tolerance",
)
GLOBAL_REVIEW_CHECKS = (
    "all_seven_shots_present",
    "all_outputs_match_recorded_sha256",
    "photorealistic_live_action_only",
    "no_anime_cartoon_chibi_or_digital_presenter",
    "no_explanatory_narration",
    "fixed_character_voices_consistent",
    "dialogue_is_clear_and_emotionally_natural",
    "pace_is_tight_without_slow_motion_or_long_hold",
    "no_readable_unapproved_text_logo_or_watermark",
    "approved_for_full_video_generation",
)
DEFAULT_REVIEW = Path(
    r"D:\IT\ai_douyin\data\qa\task1_story_v61_failed_smoke_review.json"
)
DEFAULT_PROGRESS = Path(
    r"D:\IT\ai_douyin\data\qa\task1_story_v61_failed_smoke_progress.json"
)
DEFAULT_CERTIFICATE = Path(
    r"D:\IT\ai_douyin\data\qa\task1_story_v61_smoke_review_certificate.json"
)
SCRIPTS_ROOT = Path(__file__).resolve().parent
DOWNSTREAM_SOURCE_FILES = {
    "smoke_review_packet": SCRIPTS_ROOT / "prepare_task1_story_v61_smoke_review_packet.py",
    "smoke_review_validator": SCRIPTS_ROOT / "validate_task1_story_v61_smoke_review.py",
    "full_batch_runner": SCRIPTS_ROOT / "run_task1_story_v61_full_batch.py",
    "full_batch_attestation_validator": SCRIPTS_ROOT / "validate_task1_story_v61_full_batch_attestation.py",
    "full_candidate_composer": SCRIPTS_ROOT / "compose_task1_story_v61_full_candidate.py",
    "full_review_packet": SCRIPTS_ROOT / "prepare_task1_story_v61_full_review_packet.py",
    "full_review_validator": SCRIPTS_ROOT / "validate_task1_story_v61_full_review.py",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _spoken_renderer_evidence(
    metadata: dict[str, Any], packet_candidate: dict[str, Any], scene_id: str
) -> dict[str, str]:
    renderer = str(metadata.get("spoken_renderer") or "").strip()
    if renderer == "sadtalker_fullframe":
        if (
            metadata.get("spoken_renderer_used") is not True
            or metadata.get("sadtalker_fullframe_used") is not True
            or metadata.get("musetalk_used") is not False
        ):
            raise ValueError(f"{scene_id}: SadTalker full-frame flags are invalid")
        artifact_path = Path(
            str(metadata.get("spoken_renderer_artifact_path") or "")
        ).resolve()
        artifact_sha = str(metadata.get("spoken_renderer_sha256") or "").upper()
        audit_path = Path(str(metadata.get("spoken_renderer_audit_path") or "")).resolve()
        audit_sha = str(metadata.get("spoken_renderer_audit_sha256") or "").upper()
        evidence = {
            "renderer": renderer,
            "artifact_path": str(artifact_path),
            "artifact_sha256": artifact_sha,
            "audit_path": str(audit_path),
            "audit_sha256": audit_sha,
            "per_stage_key": "spoken_renderer_sha256",
        }
    elif metadata.get("musetalk_used") is True:
        evidence = {
            "renderer": "musetalk_v15",
            "artifact_path": str(
                Path(str(metadata.get("musetalk_artifact_path") or "")).resolve()
            ),
            "artifact_sha256": str(metadata.get("musetalk_sha256") or "").upper(),
            "audit_path": "",
            "audit_sha256": "",
            "per_stage_key": "musetalk_sha256",
        }
    else:
        raise ValueError(f"{scene_id}: MuseTalk must be used or SadTalker full-frame evidence supplied")
    if evidence["renderer"] == "musetalk_v15" and not packet_candidate.get(
        "spoken_renderer"
    ):
        packet_candidate = {
            **packet_candidate,
            "spoken_renderer": "musetalk_v15",
            "spoken_renderer_artifact_path": str(
                Path(str(packet_candidate.get("musetalk_artifact_path") or "")).resolve()
            ),
            "spoken_renderer_sha256": str(
                packet_candidate.get("musetalk_sha256") or ""
            ).upper(),
            "spoken_renderer_audit_path": "",
            "spoken_renderer_audit_sha256": "",
        }
    packet_keys = {
        "renderer": "spoken_renderer",
        "artifact_path": "spoken_renderer_artifact_path",
        "artifact_sha256": "spoken_renderer_sha256",
        "audit_path": "spoken_renderer_audit_path",
        "audit_sha256": "spoken_renderer_audit_sha256",
    }
    for key, packet_key in packet_keys.items():
        if str(packet_candidate.get(packet_key) or "") != evidence[key]:
            raise ValueError(f"{scene_id}: spoken renderer {key} does not match machine packet")
    artifact_path = Path(evidence["artifact_path"])
    if not artifact_path.is_file() or _sha256(artifact_path) != evidence["artifact_sha256"]:
        if evidence["renderer"] == "musetalk_v15":
            raise ValueError(f"{scene_id}: MuseTalk stage artifact SHA mismatch")
        raise ValueError(f"{scene_id}: spoken renderer artifact is missing or changed")
    if evidence["audit_path"]:
        audit_path = Path(evidence["audit_path"])
        if not audit_path.is_file() or _sha256(audit_path) != evidence["audit_sha256"]:
            raise ValueError(f"{scene_id}: spoken renderer audit is missing or changed")
    return evidence


def _validate_rife_binding(
    metadata: dict[str, Any], packet_candidate: dict[str, Any],
    spoken: dict[str, str], final_sha: str, scene_id: str,
) -> dict[str, str]:
    if spoken["renderer"] != "sadtalker_fullframe":
        if str(packet_candidate.get("rife_binding_path") or "").strip():
            raise ValueError(f"{scene_id}: MuseTalk candidate cannot claim SadTalker RIFE binding")
        return {"path": "", "sha256": ""}
    path = Path(str(metadata.get("rife_binding_path") or "")).resolve()
    declared_sha = str(metadata.get("rife_binding_sha256") or "").upper()
    if not path.is_file() or len(declared_sha) != 64 or _sha256(path) != declared_sha:
        raise ValueError(f"{scene_id}: RIFE source/output binding is missing or changed")
    if path != Path(str(packet_candidate.get("rife_binding_path") or "")).resolve():
        raise ValueError(f"{scene_id}: RIFE binding path does not match machine packet")
    if declared_sha != str(packet_candidate.get("rife_binding_sha256") or "").upper():
        raise ValueError(f"{scene_id}: RIFE binding SHA does not match machine packet")
    value = _load_json(path)
    if (
        value.get("schema") != "fanqie_sadtalker_fullframe/rife_binding/v1"
        or str(value.get("source_sha256") or "").upper() != spoken["artifact_sha256"]
        or str(value.get("output_sha256") or "").upper() != final_sha
        or not str(value.get("rife_model") or "").strip()
        or not isinstance(value.get("rife_multiplier"), int)
        or value["rife_multiplier"] <= 0
        or value.get("delivery_fps") != 50
    ):
        raise ValueError(f"{scene_id}: RIFE source/output binding contract failed")
    return {"path": str(path), "sha256": declared_sha}


def current_downstream_source_contract() -> dict[str, dict[str, str]]:
    """Return the exact downstream implementation that a human review signs."""
    contract: dict[str, dict[str, str]] = {}
    for name, path in DOWNSTREAM_SOURCE_FILES.items():
        resolved = path.resolve()
        if not resolved.is_file():
            raise ValueError(f"Downstream source file not found: {resolved}")
        contract[name] = {"path": str(resolved), "sha256": _sha256(resolved)}
    return contract


def validate_downstream_source_contract(value: Any) -> dict[str, dict[str, str]]:
    if not isinstance(value, dict) or set(value) != set(DOWNSTREAM_SOURCE_FILES):
        raise ValueError("downstream source contract boundary mismatch")
    current = current_downstream_source_contract()
    normalized: dict[str, dict[str, str]] = {}
    for name, expected in current.items():
        item = value.get(name)
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            raise ValueError(f"downstream source contract entry invalid: {name}")
        declared_path = Path(str(item.get("path") or "")).resolve()
        declared_sha = str(item.get("sha256") or "").upper()
        if declared_path != Path(expected["path"]).resolve():
            raise ValueError(f"downstream source path mismatch: {name}")
        if declared_sha != expected["sha256"]:
            raise ValueError(f"downstream source changed after smoke review: {name}")
        normalized[name] = expected
    return normalized


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest().upper()


def _load_json_bytes(path: Path) -> tuple[dict[str, Any], bytes, str]:
    if not path.is_file():
        raise ValueError(f"JSON file not found: {path}")
    try:
        raw = path.read_bytes()
        data = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid JSON file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return data, raw, _sha256_bytes(raw)


def _load_json(path: Path) -> dict[str, Any]:
    return _load_json_bytes(path)[0]


def _parse_reviewed_at(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("reviewed_at is required")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("reviewed_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("reviewed_at must include a timezone")
    if parsed > datetime.now(timezone.utc).astimezone(parsed.tzinfo):
        raise ValueError("reviewed_at cannot be in the future")
    return text


def _parse_timestamp(value: Any, field: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed


def _probe_video(path: Path) -> dict[str, float]:
    command = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=avg_frame_rate:format=duration",
        "-of", "json", str(path),
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, check=False, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"ffprobe failed for {path}: {exc}") from exc
    if result.returncode != 0:
        raise ValueError(f"ffprobe rejected {path}: {result.stderr.strip()}")
    try:
        payload = json.loads(result.stdout)
        duration = float(payload["format"]["duration"])
        rate_text = str(payload["streams"][0]["avg_frame_rate"])
        numerator, denominator = rate_text.split("/", 1)
        fps = float(numerator) / float(denominator)
    except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"ffprobe returned invalid metadata for {path}") from exc
    return {"duration_seconds": duration, "fps": fps}


def _single_progress_asset(progress_shot: dict[str, Any], scene_id: str) -> dict[str, Any]:
    missing = progress_shot.get("missing")
    assets = progress_shot.get("assets")
    if missing:
        raise ValueError(f"{scene_id}: progress contains missing capabilities")
    if not isinstance(assets, list) or len(assets) != 1:
        raise ValueError(f"{scene_id}: progress must contain exactly one asset")
    asset = assets[0]
    if not isinstance(asset, dict) or asset.get("scene_id") != scene_id:
        raise ValueError(f"{scene_id}: progress asset identity mismatch")
    return asset


def validate_review(
    review_path: str | Path,
    *,
    progress_path: str | Path | None = None,
    probe_video=_probe_video,
) -> dict[str, Any]:
    review_file = Path(review_path).resolve()
    review, review_bytes, review_sha = _load_json_bytes(review_file)
    if review.get("schema_version") != SCHEMA:
        raise ValueError(f"schema_version must be {SCHEMA}")
    if review.get("task_id") != 1 or review.get("scope") != "failed_scene_smoke":
        raise ValueError("review task_id/scope mismatch")
    if str(review.get("plan_sha256") or "").upper() != EXPECTED_PLAN_SHA256:
        raise ValueError("review plan_sha256 mismatch")
    if review.get("review_status") != "approved":
        raise ValueError("review_status must be approved")
    if review.get("decision_source") != "authenticated_streamlit_frontend":
        raise ValueError("review was not approved by the authenticated frontend")
    reviewer = str(review.get("reviewer") or "").strip()
    if len(reviewer) < 2:
        raise ValueError("reviewer must identify the human reviewer")
    reviewed_at = _parse_reviewed_at(review.get("reviewed_at"))
    reviewer_id = str(review.get("reviewer_id") or reviewer).strip()
    if len(reviewer_id) < 2:
        raise ValueError("reviewer_id must identify the frontend reviewer")

    source_progress = Path(
        progress_path or str(review.get("source_progress_path") or "")
    ).resolve()
    progress, _, progress_sha = _load_json_bytes(source_progress)
    declared_progress_sha = str(
        review.get("reviewed_progress_sha256") or ""
    ).upper()
    if declared_progress_sha != progress_sha:
        raise ValueError("reviewed_progress_sha256 does not match current progress file")
    if progress.get("schema_version") != PROGRESS_SCHEMA:
        raise ValueError(f"progress schema_version must be {PROGRESS_SCHEMA}")
    if progress.get("task_id") != 1 or progress.get("scope") != "failed_scene_smoke":
        raise ValueError("progress task_id/scope mismatch")
    if str(progress.get("expected_plan_sha256") or "").upper() != EXPECTED_PLAN_SHA256:
        raise ValueError("progress plan SHA mismatch")
    if tuple(progress.get("selected_shot_ids") or ()) != SHOT_IDS:
        raise ValueError("progress does not contain the exact reviewed seven-shot boundary")
    if progress.get("result") != "FAILED_SCENE_SMOKE_RENDERED_AWAITING_HUMAN_REVIEW":
        raise ValueError("progress is not a successfully rendered smoke candidate")
    reviewed_timestamp = _parse_timestamp(reviewed_at, "reviewed_at")
    render_finished_at = _parse_timestamp(progress.get("finished_at"), "progress.finished_at")
    if reviewed_timestamp < render_finished_at.astimezone(reviewed_timestamp.tzinfo):
        raise ValueError("reviewed_at cannot be earlier than progress.finished_at")
    progress_gates = progress.get("gates")
    if not isinstance(progress_gates, dict):
        raise ValueError("progress gates are missing")
    for key in (
        "static_validation_passed", "audio_prepared",
        "runtime_preflight_passed", "failed_scene_smoke_rendered",
    ):
        if progress_gates.get(key) is not True:
            raise ValueError(f"progress machine gate {key} is not true")
    for key in (
        "human_video_approval_obtained", "matching_fanqie_task_confirmed",
        "publish_allowed", "fanqie_backfill_allowed",
    ):
        if progress_gates.get(key) is not False:
            raise ValueError(f"progress platform gate {key} must remain false")

    global_gates = review.get("global_gates")
    if not isinstance(global_gates, dict):
        raise ValueError("global_gates must be an object")
    for key in GLOBAL_REVIEW_CHECKS:
        if global_gates.get(key) is not True:
            raise ValueError(f"global_gates.{key} must be true")

    contact_sheet = Path(str(review.get("candidate_contact_sheet") or "")).resolve()
    if not contact_sheet.is_file():
        raise ValueError("candidate_contact_sheet must be an existing file")
    contact_sha = _sha256(contact_sheet)
    if str(review.get("candidate_contact_sheet_sha256") or "").upper() != contact_sha:
        raise ValueError("candidate_contact_sheet_sha256 mismatch")

    machine_packet_path = Path(
        str(review.get("machine_review_packet_path") or "")
    ).resolve()
    machine_packet, _, machine_packet_sha = _load_json_bytes(machine_packet_path)
    if str(review.get("machine_review_packet_sha256") or "").upper() != machine_packet_sha:
        raise ValueError("machine_review_packet_sha256 mismatch")
    if machine_packet.get("schema_version") != MACHINE_PACKET_SCHEMA:
        raise ValueError("machine review packet schema mismatch")
    if machine_packet.get("task_id") != 1 or machine_packet.get("scope") != "failed_scene_smoke":
        raise ValueError("machine review packet task/scope mismatch")
    if str(machine_packet.get("plan_sha256") or "").upper() != EXPECTED_PLAN_SHA256:
        raise ValueError("machine review packet plan SHA mismatch")
    if str(machine_packet.get("source_progress_sha256") or "").upper() != progress_sha:
        raise ValueError("machine review packet progress SHA mismatch")
    if str(machine_packet.get("contact_sheet_sha256") or "").upper() != contact_sha:
        raise ValueError("machine review packet contact-sheet SHA mismatch")
    if machine_packet.get("machine_gate_passed") is not True:
        raise ValueError("machine review packet gate is not passed")
    if machine_packet.get("machine_gate_scope") != "file_integrity_and_pipeline_provenance_only":
        raise ValueError("machine review packet gate scope mismatch")
    if machine_packet.get("human_visual_and_audio_semantic_review_required") is not True:
        raise ValueError("machine review packet must require human semantic review")
    if machine_packet.get("human_review_completed") is not False:
        raise ValueError("machine review packet must not self-approve human review")
    if machine_packet.get("full_19_shot_generation_allowed") is not False:
        raise ValueError("machine review packet must not open full generation")
    for key in ("douyin_upload_allowed", "fanqie_backfill_allowed"):
        if machine_packet.get(key) is not False:
            raise ValueError(f"machine review packet {key} must remain false")
    if machine_packet.get("candidate_count") != len(SHOT_IDS):
        raise ValueError("machine review packet candidate_count mismatch")
    if machine_packet.get("frames_per_candidate") != 3:
        raise ValueError("machine review packet frames_per_candidate must be three")
    downstream_source_contract = validate_downstream_source_contract(
        machine_packet.get("downstream_source_contract")
    )

    progress_shots = progress.get("shots")
    review_shots = review.get("shots")
    if not isinstance(progress_shots, list) or len(progress_shots) != len(SHOT_IDS):
        raise ValueError("progress must contain exactly seven shot results")
    if not isinstance(review_shots, list) or len(review_shots) != len(SHOT_IDS):
        raise ValueError("review must contain exactly seven shot decisions")
    progress_by_id = {
        item.get("scene_id"): item for item in progress_shots if isinstance(item, dict)
    }
    review_by_id = {
        item.get("scene_id"): item for item in review_shots if isinstance(item, dict)
    }
    if tuple(item.get("scene_id") for item in review_shots) != SHOT_IDS:
        raise ValueError("review shots must be in the exact reviewed order")
    if set(progress_by_id) != set(SHOT_IDS) or set(review_by_id) != set(SHOT_IDS):
        raise ValueError("progress/review shot IDs do not match the seven-shot boundary")
    packet_candidates = machine_packet.get("candidates")
    if not isinstance(packet_candidates, list) or len(packet_candidates) != len(SHOT_IDS):
        raise ValueError("machine review packet must contain seven candidates")
    if tuple(item.get("scene_id") for item in packet_candidates if isinstance(item, dict)) != SHOT_IDS:
        raise ValueError("machine review packet candidate order mismatch")
    packet_by_id = {item["scene_id"]: item for item in packet_candidates}

    candidates: list[dict[str, Any]] = []
    for scene_id in SHOT_IDS:
        progress_asset = _single_progress_asset(progress_by_id[scene_id], scene_id)
        review_shot = review_by_id[scene_id]
        packet_candidate = packet_by_id[scene_id]
        if review_shot.get("decision") != "approved":
            raise ValueError(f"{scene_id}: decision must be approved")
        for key in SHOT_REVIEW_CHECKS:
            if review_shot.get(key) is not True:
                raise ValueError(f"{scene_id}.{key} must be true")

        expected_duration = SHOT_DURATIONS[scene_id]
        try:
            declared_duration = float(review_shot.get("expected_duration_seconds"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{scene_id}: invalid expected duration") from exc
        if abs(declared_duration - expected_duration) > 0.001:
            raise ValueError(f"{scene_id}: expected duration was altered")

        progress_path_value = str(progress_asset.get("video_path") or "")
        candidate_path = Path(str(review_shot.get("candidate_path") or "")).resolve()
        if not candidate_path.is_file():
            raise ValueError(f"{scene_id}: candidate video is missing")
        if candidate_path != Path(progress_path_value).resolve():
            raise ValueError(f"{scene_id}: review candidate differs from progress asset")
        actual_sha = _sha256(candidate_path)
        review_sha = str(review_shot.get("candidate_sha256") or "").upper()
        metadata = progress_asset.get("metadata")
        if not isinstance(metadata, dict):
            raise ValueError(f"{scene_id}: progress asset metadata is missing")
        progress_sha_value = str(metadata.get("final_sha256") or "").upper()
        if not actual_sha or actual_sha != review_sha or actual_sha != progress_sha_value:
            raise ValueError(f"{scene_id}: candidate SHA does not match review/progress")
        if actual_sha != str(packet_candidate.get("video_sha256") or "").upper():
            raise ValueError(f"{scene_id}: candidate SHA does not match machine packet")
        if candidate_path != Path(str(packet_candidate.get("video_path") or "")).resolve():
            raise ValueError(f"{scene_id}: candidate path does not match machine packet")
        frames = packet_candidate.get("frames")
        if not isinstance(frames, list) or len(frames) != 3:
            raise ValueError(f"{scene_id}: machine packet must contain three review frames")
        frame_shas: set[str] = set()
        for frame_index, frame in enumerate(frames, start=1):
            if not isinstance(frame, dict):
                raise ValueError(f"{scene_id}: invalid machine packet frame")
            if frame.get("position") != frame_index:
                raise ValueError(f"{scene_id}: machine review frame position mismatch")
            expected_fraction = (0.15, 0.50, 0.85)[frame_index - 1]
            try:
                fraction = float(frame.get("fraction"))
                timestamp = float(frame.get("timestamp_seconds"))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{scene_id}: invalid review frame timing") from exc
            if abs(fraction - expected_fraction) > 0.0001:
                raise ValueError(f"{scene_id}: machine review frame fraction mismatch")
            expected_timestamp = max(0.0, min(expected_duration - 0.02, expected_duration * fraction))
            if abs(timestamp - expected_timestamp) > 0.001:
                raise ValueError(f"{scene_id}: machine review frame timestamp mismatch")
            frame_path = Path(str(frame.get("path") or "")).resolve()
            if not frame_path.is_file():
                raise ValueError(f"{scene_id}: machine review frame is missing")
            frame_sha = _sha256(frame_path)
            if frame_sha != str(frame.get("sha256") or "").upper():
                raise ValueError(f"{scene_id}: machine review frame SHA mismatch")
            frame_shas.add(frame_sha)
        if len(frame_shas) != 3:
            raise ValueError(f"{scene_id}: machine review frames must be distinct")
        if metadata.get("has_presenter") is not False:
            raise ValueError(f"{scene_id}: has_presenter must be false")
        spoken_evidence = _spoken_renderer_evidence(
            metadata, packet_candidate, scene_id
        )
        rife_binding = _validate_rife_binding(
            metadata, packet_candidate, spoken_evidence, actual_sha, scene_id
        )
        if not str(metadata.get("dialogue_audio_sha256") or "").strip():
            raise ValueError(f"{scene_id}: dialogue audio SHA is missing")
        dialogue_audio_path = Path(
            str(metadata.get("dialogue_audio_path") or "")
        ).resolve()
        if not dialogue_audio_path.is_file():
            raise ValueError(f"{scene_id}: dialogue audio file is missing")
        dialogue_audio_sha = _sha256(dialogue_audio_path)
        if dialogue_audio_sha != str(metadata.get("dialogue_audio_sha256") or "").upper():
            raise ValueError(f"{scene_id}: dialogue audio file SHA mismatch")
        if dialogue_audio_path != Path(
            str(packet_candidate.get("dialogue_audio_path") or "")
        ).resolve():
            raise ValueError(f"{scene_id}: dialogue audio path does not match machine packet")
        if dialogue_audio_sha != str(
            packet_candidate.get("dialogue_audio_sha256") or ""
        ).upper():
            raise ValueError(f"{scene_id}: dialogue audio SHA does not match machine packet")
        per_stage = metadata.get("per_stage_sha256")
        if not isinstance(per_stage, dict):
            raise ValueError(f"{scene_id}: per-stage SHA evidence is missing")
        if str(per_stage.get("dialogue_audio_sha256") or "").upper() != dialogue_audio_sha:
            raise ValueError(f"{scene_id}: per-stage dialogue SHA mismatch")
        if str(per_stage.get(spoken_evidence["per_stage_key"]) or "").upper() != (
            spoken_evidence["artifact_sha256"]
        ):
            raise ValueError(f"{scene_id}: per-stage spoken renderer SHA mismatch")
        if spoken_evidence["audit_sha256"] and str(
            per_stage.get("spoken_renderer_audit_sha256") or ""
        ).upper() != spoken_evidence["audit_sha256"]:
            raise ValueError(f"{scene_id}: per-stage spoken renderer audit SHA mismatch")
        if rife_binding["sha256"] and str(
            per_stage.get("rife_binding_sha256") or ""
        ).upper() != rife_binding["sha256"]:
            raise ValueError(f"{scene_id}: per-stage RIFE binding SHA mismatch")
        if str(per_stage.get("rife_sha256") or "").upper() != actual_sha:
            raise ValueError(f"{scene_id}: per-stage RIFE SHA mismatch")
        try:
            recorded_fps = float(metadata.get("rife_fps"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{scene_id}: recorded RIFE fps is invalid") from exc
        if abs(recorded_fps - 50.0) > 0.01:
            raise ValueError(f"{scene_id}: recorded RIFE fps must be 50")

        pre_probe_sha = actual_sha
        probed = probe_video(candidate_path)
        post_probe_sha = _sha256(candidate_path)
        if post_probe_sha != pre_probe_sha:
            raise ValueError(f"{scene_id}: candidate changed while it was being probed")
        actual_duration = float(probed["duration_seconds"])
        actual_fps = float(probed["fps"])
        if abs(actual_duration - expected_duration) > 0.12:
            raise ValueError(f"{scene_id}: actual duration is outside ±0.12s")
        if abs(actual_fps - 50.0) > 0.01:
            raise ValueError(f"{scene_id}: actual delivery fps must be 50")
        candidates.append({
            "scene_id": scene_id,
            "path": str(candidate_path),
            "sha256": actual_sha,
            "duration_seconds": round(actual_duration, 3),
            "fps": round(actual_fps, 3),
            "provider_name": str(progress_asset.get("provider_name") or ""),
            "metadata": metadata,
        })

    playback_started = _parse_timestamp(
        review.get("playback_started_at"), "playback_started_at"
    )
    playback_finished = _parse_timestamp(
        review.get("playback_finished_at"), "playback_finished_at"
    )
    minimum_playback = sum(SHOT_DURATIONS.values())
    if (playback_finished - playback_started).total_seconds() < minimum_playback - 0.25:
        raise ValueError("frontend playback interval does not cover all smoke candidates")
    if playback_finished > reviewed_timestamp:
        raise ValueError("frontend playback cannot finish after reviewed_at")
    attestation = review.get("frontend_attestation")
    if not isinstance(attestation, dict):
        raise ValueError("frontend review attestation is missing")
    expected_confirmations = {
        *(f"shot:{scene_id}" for scene_id in SHOT_IDS),
        *(f"global:{key}" for key in GLOBAL_REVIEW_CHECKS),
    }
    confirmations = attestation.get("confirmations")
    if not isinstance(confirmations, dict) or set(confirmations) != expected_confirmations:
        raise ValueError("frontend smoke confirmation boundary mismatch")
    if any(confirmations.get(key) is not True for key in expected_confirmations):
        raise ValueError("frontend smoke confirmation is incomplete")
    if sorted(attestation.get("required_checks") or []) != sorted(expected_confirmations):
        raise ValueError("frontend smoke required-check record mismatch")
    if [str(value or "").upper() for value in attestation.get("video_sha256s") or []] != [
        candidate["sha256"] for candidate in candidates
    ]:
        raise ValueError("frontend smoke candidate hash binding mismatch")
    if str(attestation.get("machine_packet_sha256") or "").upper() != machine_packet_sha:
        raise ValueError("frontend smoke machine-packet hash binding mismatch")

    return {
        "schema_version": CERTIFICATE_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "accepted": True,
        "task_id": 1,
        "scope": "failed_scene_smoke",
        "plan_sha256": EXPECTED_PLAN_SHA256,
        "reviewer": reviewer,
        "reviewer_id": reviewer_id,
        "reviewed_at": reviewed_at,
        "review_path": str(review_file),
        "review_sha256": review_sha,
        "approval_source": "authenticated_streamlit_frontend",
        "progress_path": str(source_progress),
        "progress_sha256": progress_sha,
        "contact_sheet_path": str(contact_sheet),
        "contact_sheet_sha256": contact_sha,
        "machine_review_packet_path": str(machine_packet_path),
        "machine_review_packet_sha256": machine_packet_sha,
        "downstream_source_contract": downstream_source_contract,
        "candidates": candidates,
        "gates": {
            "machine_smoke_gate_passed": True,
            "human_smoke_review_passed": True,
            "full_19_shot_generation_allowed": True,
            "full_video_human_review_required": True,
            "matching_fanqie_task_confirmed": False,
            "douyin_upload_allowed": False,
            "fanqie_backfill_allowed": False,
        },
    }


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate task-1 V6.1 seven-shot machine and human review gates."
    )
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--progress", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_CERTIFICATE)
    args = parser.parse_args(argv)
    try:
        certificate = validate_review(
            args.review,
            progress_path=args.progress,
        )
    except ValueError as exc:
        rejected = {
            "schema_version": CERTIFICATE_SCHEMA,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "accepted": False,
            "error": str(exc),
            "gates": {
                "full_19_shot_generation_allowed": False,
                "douyin_upload_allowed": False,
                "fanqie_backfill_allowed": False,
            },
        }
        _write_json_atomic(args.output.resolve(), rejected)
        print(json.dumps(rejected, ensure_ascii=False, indent=2))
        return 2
    _write_json_atomic(args.output.resolve(), certificate)
    print(json.dumps(certificate, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
