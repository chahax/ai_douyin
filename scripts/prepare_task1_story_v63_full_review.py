"""Prepare the immutable V6.3 complete-candidate frontend review packet."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.content_factory.video_smoothness import analyze_video_smoothness


DEFAULT_CANDIDATE_DIR = ROOT / r"data\qa\task1_story_v63_full_candidate_20260822_visual_retention_v1"
DEFAULT_REVIEW = ROOT / r"data\qa\task1_story_v63_full_review_visual_retention_v1_20260822.json"
CHECKS = {
    "complete_video_watched_from_start_to_finish",
    "all_19_beats_and_32_microshots_present_in_order",
    "glossy_high_saturation_live_action_style_has_strong_visual_appeal",
    "neon_confrontation_gold_reversal_and_red_blue_chase_phases_are_distinct",
    "character_identity_hair_and_wardrobe_are_consistent",
    "full_body_leg_and_weight_transfer_actions_are_readable",
    "actions_are_continuous_without_stutter_or_unwanted_chaining",
    "hands_fingers_phone_booklet_and_car_geometry_are_plausible",
    "facial_expressions_and_emotional_turns_are_readable",
    "hard_cuts_are_motivated_and_retention_pace_is_effective",
    "cuts_audio_and_subtitles_are_synchronized",
    "subtitle_text_is_correct_readable_and_safe",
    "no_black_frame_long_freeze_logo_watermark_or_visual_artifact",
    "approved_as_internal_candidate_only_not_for_upload",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _write_atomic(path: Path, value: dict[str, object]) -> None:
    pending = path.with_suffix(path.suffix + ".pending")
    pending.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pending.replace(path)


def _probe(path: Path) -> dict[str, object]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "stream=codec_type,codec_name,width,height,r_frame_rate:format=duration,size,bit_rate",
            "-of", "json", str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode:
        raise RuntimeError(result.stderr[-1000:])
    payload = json.loads(result.stdout)
    video = next(row for row in payload["streams"] if row["codec_type"] == "video")
    audio = next(row for row in payload["streams"] if row["codec_type"] == "audio")
    return {
        "width": int(video["width"]),
        "height": int(video["height"]),
        "fps": str(video["r_frame_rate"]),
        "video_codec": str(video["codec_name"]),
        "audio_codec": str(audio["codec_name"]),
        "duration_seconds": round(float(payload["format"]["duration"]), 3),
        "size_bytes": int(payload["format"]["size"]),
        "bit_rate": int(payload["format"]["bit_rate"]),
    }


def _technical_scan(path: Path) -> dict[str, object]:
    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-i", str(path),
            "-vf", "freezedetect=n=-45dB:d=0.50,blackdetect=d=0.20:pix_th=0.05",
            "-af", "silencedetect=n=-45dB:d=1.0", "-f", "null", "NUL",
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode:
        raise RuntimeError(result.stderr[-2000:])
    silences = [float(value) for value in re.findall(r"silence_duration:\s*([0-9.]+)", result.stderr)]
    return {
        "freeze_event_count": len(re.findall(r"freeze_start:", result.stderr)),
        "black_event_count": len(re.findall(r"black_start:", result.stderr)),
        "silence_gap_count_over_1s": len(silences),
        "longest_silence_gap_seconds": round(max(silences, default=0.0), 3),
        "silence_gaps_require_human_audio_review": True,
    }


def _make_contact_sheet(candidate: Path, contact: Path) -> None:
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(candidate), "-vf",
            "fps=12/40.8,scale=270:480:flags=lanczos,tile=4x3:padding=4:margin=4:color=black",
            "-frames:v", "1", "-update", "1", str(contact),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode or not contact.is_file() or contact.stat().st_size <= 0:
        raise RuntimeError(f"contact sheet failed: {result.stderr[-1000:]}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-dir", type=Path, default=DEFAULT_CANDIDATE_DIR)
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    candidate_dir = args.candidate_dir.resolve()
    candidate = candidate_dir / "candidate.mp4"
    audit_path = candidate_dir / "compose_audit.json"
    for required in (candidate, audit_path):
        if not required.is_file() or required.stat().st_size <= 0:
            raise FileNotFoundError(required)
    audit = _load(audit_path)
    if audit.get("schema_version") != "fanqie_v63_visual_retention_candidate/v1":
        raise ValueError("unexpected V6.3 candidate audit schema")
    candidate_sha = _sha256(candidate)
    if str(audit.get("candidate_sha256") or "").upper() != candidate_sha:
        raise ValueError("candidate changed after composition audit")
    if len(audit.get("microshots") or []) != 32:
        raise ValueError("candidate audit does not contain 32 micro-shots")
    for key in ("reference_video_pixels_used", "reference_people_used", "reference_watermark_used"):
        if audit.get(key) is not False:
            raise ValueError(f"V6.3 audit must keep {key}=false")

    progress_path = Path(str(audit["render_progress_path"])).resolve()
    progress = _load(progress_path)
    if progress.get("schema_version") != "fanqie_v63_render_progress/v1" or progress.get("success") is not True:
        raise ValueError("V6.3 render progress is incomplete")
    rows = progress.get("shots") or []
    if len(rows) != 19 or any(row.get("status") != "rendered" for row in rows):
        raise ValueError("V6.3 render progress does not contain 19 rendered units")
    partition = progress.get("renderer_partition")
    if not isinstance(partition, dict) or set(partition) != {
        "local_framepack_i2v", "deterministic_camera_motion_candidate_only"
    }:
        raise ValueError("V6.3 renderer partition is invalid")
    if len(partition["local_framepack_i2v"]) != 11 or len(partition["deterministic_camera_motion_candidate_only"]) != 8:
        raise ValueError("V6.3 renderer counts must be exactly 11 action and 8 stable inserts")
    disclosed = [*partition["local_framepack_i2v"], *partition["deterministic_camera_motion_candidate_only"]]
    if len(disclosed) != 19 or len(set(disclosed)) != 19:
        raise ValueError("V6.3 renderer partition must cover exactly 19 unique scenes")
    for row in rows:
        output = Path(str(row["output_path"])).resolve()
        if not output.is_file() or _sha256(output) != row["output_sha256"]:
            raise ValueError(f"V6.3 source render changed: {row.get('scene_id')}")
        metrics = row.get("motion_metrics") or {}
        if float(metrics.get("duplicate_ratio", 1.0)) > (0.12 if row["renderer"] == "local_framepack_i2v" else 0.28):
            raise ValueError(f"V6.3 scene motion gate failed: {row.get('scene_id')}")
        if row["renderer"] == "local_framepack_i2v" and float(metrics.get("mean_frame_distance", 0.0)) < 0.5:
            raise ValueError(f"V6.3 action scene has insufficient motion: {row.get('scene_id')}")
        if float(metrics.get("smoothness_score", 0.0)) < 65.0:
            raise ValueError(f"V6.3 scene is not smooth enough: {row.get('scene_id')}")

    plan_path = Path(str(audit["plan_path"])).resolve()
    plan_sha = _sha256(plan_path)
    if str(audit.get("plan_sha256") or "").upper() != plan_sha:
        raise ValueError("candidate audit plan binding changed")
    plan = _load(plan_path)
    branch = (plan.get("variants") or {}).get("visual_retention_v1") or {}
    if plan.get("schema_version") != "fanqie_v63_visual_retention_workflow/v1":
        raise ValueError("unexpected V6.3 plan schema")
    if any(branch.get(key) is not False for key in (
        "reference_video_pixels_allowed", "reference_people_allowed", "reference_watermark_allowed",
        "publish_allowed", "fanqie_backfill_allowed",
    )):
        raise ValueError("V6.3 plan lost a provenance or publication guard")

    probe = _probe(candidate)
    if (probe["width"], probe["height"], probe["fps"]) != (1080, 1920, "30/1"):
        raise ValueError(f"candidate video format is invalid: {probe}")
    if abs(float(probe["duration_seconds"]) - 40.8) > 0.08:
        raise ValueError("candidate duration is outside the V6.3 boundary")
    scan = _technical_scan(candidate)
    if scan["freeze_event_count"] or scan["black_event_count"]:
        raise ValueError(f"candidate technical scan failed: {scan}")
    temporal_metrics = analyze_video_smoothness(
        candidate, analysis_fps=15.0, analysis_width=160, duplicate_threshold=0.12
    )
    if float(temporal_metrics["duplicate_ratio"]) > 0.12:
        raise ValueError(f"whole-video duplicate ratio failed: {temporal_metrics}")
    if float(temporal_metrics["mean_frame_distance"]) < 4.5:
        raise ValueError(f"whole-video motion density failed: {temporal_metrics}")

    frames_dir = candidate_dir / "review_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    frames: list[dict[str, object]] = []
    for index, timestamp in enumerate((1.0, 4.8, 8.6, 12.4, 16.2, 20.0, 23.8, 27.6, 31.4, 35.2, 39.0), start=1):
        frame = frames_dir / f"frame_{index:02d}_{timestamp:04.1f}s.png"
        result = subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{timestamp:.3f}", "-i", str(candidate), "-frames:v", "1", "-update", "1", str(frame)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode or not frame.is_file():
            raise RuntimeError(f"frame extraction failed at {timestamp}: {result.stderr[-1000:]}")
        frames.append({"timestamp_seconds": timestamp, "path": str(frame), "sha256": _sha256(frame)})
    contact = candidate_dir / "contact_sheet.png"
    _make_contact_sheet(candidate, contact)

    packet = {
        "schema_version": "fanqie_v63_full_machine_review_packet/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "task_id": 1,
        "scope": "v63_full_visual_retention_candidate",
        "variant": "visual_retention_v1",
        "plan_path": str(plan_path),
        "plan_sha256": plan_sha,
        "candidate_path": str(candidate),
        "candidate_sha256": candidate_sha,
        "candidate_audit_path": str(audit_path),
        "candidate_audit_sha256": _sha256(audit_path),
        "render_progress_path": str(progress_path),
        "render_progress_sha256": _sha256(progress_path),
        "contact_sheet_path": str(contact),
        "contact_sheet_sha256": _sha256(contact),
        "probe": probe,
        "technical_scan": scan,
        "temporal_metrics": temporal_metrics,
        "frames": frames,
        "render_disclosure": {
            "renderer_units": {key: len(value) for key, value in partition.items()},
            "microshot_count": 32,
            "all_media_generated_locally": True,
            "reference_video_pixels_used": False,
        },
        "machine_gate_passed": True,
        "visual_style_motion_and_retention_require_human_confirmation": True,
        "human_full_video_review_completed": False,
        "douyin_upload_allowed": False,
        "fanqie_backfill_allowed": False,
    }
    packet_path = candidate_dir / "machine_review_packet.json"
    _write_atomic(packet_path, packet)

    review_path = args.review.resolve()
    if review_path.exists() and not args.force:
        raise FileExistsError(review_path)
    review = {
        "schema_version": "fanqie_v63_full_human_review/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "task_id": 1,
        "target_promotion_task_id": None,
        "scope": "v63_full_visual_retention_candidate",
        "variant": "visual_retention_v1",
        "plan_path": str(plan_path),
        "plan_sha256": plan_sha,
        "review_status": "pending_review",
        "decision": None,
        "reviewer": "",
        "reviewed_at": None,
        "notes": "",
        "candidate_path": str(candidate),
        "candidate_sha256": candidate_sha,
        "contact_sheet_path": str(contact),
        "contact_sheet_sha256": _sha256(contact),
        "machine_review_packet_path": str(packet_path),
        "machine_review_packet_sha256": _sha256(packet_path),
        "checks": {key: None for key in sorted(CHECKS)},
    }
    _write_atomic(review_path, review)
    print(json.dumps({
        "status": "V63_FULL_REVIEW_READY",
        "review_path": str(review_path),
        "review_sha256": _sha256(review_path),
        "packet_path": str(packet_path),
        "publish_allowed": False,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
