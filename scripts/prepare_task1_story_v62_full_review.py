"""Prepare the immutable V6.2 complete-candidate frontend review packet."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CANDIDATE_DIR = ROOT / r"data\qa\task1_story_v62_full_candidate_20260822_original_ltx"
DEFAULT_REVIEW = ROOT / r"data\qa\task1_story_v62_full_review_20260822_original_ltx.json"
CHECKS = {
    "complete_video_watched_from_start_to_finish",
    "all_19_beats_and_32_microshots_present_in_order",
    "reference_style_is_glossy_ai_live_action_blue_hour_neon",
    "no_natural_daylight_stock_or_documentary_style_drift",
    "character_identity_hair_and_wardrobe_are_consistent",
    "actions_are_continuous_without_stutter_or_unwanted_chaining",
    "hands_fingers_phone_booklet_and_car_geometry_are_plausible",
    "facial_expressions_and_emotional_turns_are_readable",
    "cuts_audio_and_subtitles_are_synchronized",
    "dialogue_music_and_silence_gaps_sound_natural",
    "subtitle_text_is_correct_readable_and_safe",
    "no_black_frame_long_freeze_logo_watermark_or_visual_artifact",
    "hybrid_renderer_disclosure_is_understood",
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
        timeout=120,
    )
    output = result.stderr
    if result.returncode:
        raise RuntimeError(output[-2000:])
    silences = [float(value) for value in re.findall(r"silence_duration:\s*([0-9.]+)", output)]
    return {
        "freeze_event_count": len(re.findall(r"freeze_start:", output)),
        "black_event_count": len(re.findall(r"black_start:", output)),
        "silence_gap_count_over_1s": len(silences),
        "longest_silence_gap_seconds": round(max(silences, default=0.0), 3),
        "silence_gaps_require_human_audio_review": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-dir", type=Path, default=DEFAULT_CANDIDATE_DIR)
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    candidate_dir = args.candidate_dir.resolve()
    candidate = candidate_dir / "candidate.mp4"
    audit_path = candidate_dir / "compose_audit.json"
    contact = candidate_dir / "contact_sheet.png"
    for required in (candidate, audit_path, contact):
        if not required.is_file() or required.stat().st_size <= 0:
            raise FileNotFoundError(required)
    audit = _load(audit_path)
    if audit.get("schema_version") != "fanqie_v62_microshot_candidate/v1":
        raise ValueError("unexpected V6.2 candidate audit schema")
    if str(audit.get("candidate_sha256") or "").upper() != _sha256(candidate):
        raise ValueError("candidate changed after composition audit")
    if len(audit.get("microshots") or []) != 32:
        raise ValueError("candidate audit does not contain 32 micro-shots")
    progress_path = Path(str(audit["render_progress_path"])).resolve()
    progress = _load(progress_path)
    if progress.get("schema_version") != "fanqie_v62_ltx_progress/v1" or progress.get("success") is not True:
        raise ValueError("hybrid render progress is incomplete")
    if len(progress.get("shots") or []) != 19:
        raise ValueError("hybrid render progress does not contain 19 units")
    renderer_partition = progress.get("renderer_partition")
    allowed_renderers = {
        "local_framepack_i2v",
        "local_comfyui_ltx_i2v",
        "local_composite_rife_bridge_and_ltx",
        "deterministic_camera_motion_candidate_only",
    }
    if not isinstance(renderer_partition, dict) or set(renderer_partition) - allowed_renderers:
        raise ValueError("hybrid renderer partition contains an unknown renderer")
    disclosed_scenes: dict[str, str] = {}
    renderer_counts: dict[str, int] = {}
    for renderer in sorted(allowed_renderers):
        scene_ids = renderer_partition.get(renderer) or []
        if not isinstance(scene_ids, list) or len(scene_ids) != len(set(scene_ids)):
            raise ValueError(f"invalid renderer partition for {renderer}")
        renderer_counts[renderer] = len(scene_ids)
        for scene_id in scene_ids:
            if scene_id in disclosed_scenes:
                raise ValueError(f"scene is disclosed by multiple renderers: {scene_id}")
            disclosed_scenes[str(scene_id)] = renderer
    progress_rows = {str(row.get("scene_id")): row for row in progress.get("shots") or []}
    if set(disclosed_scenes) != set(progress_rows):
        raise ValueError("renderer partition does not cover the 19 progress scenes exactly")
    for scene_id, renderer in disclosed_scenes.items():
        metadata = progress_rows[scene_id].get("provider_metadata") or {}
        if metadata.get("renderer") != renderer:
            raise ValueError(f"renderer partition conflicts with scene audit: {scene_id}")
    plan_path = Path(str(audit["plan_path"])).resolve()
    plan_sha = _sha256(plan_path)
    if str(audit.get("plan_sha256") or "").upper() != plan_sha:
        raise ValueError("candidate audit plan binding changed")

    probe = _probe(candidate)
    if (probe["width"], probe["height"], probe["fps"]) != (1080, 1920, "30/1"):
        raise ValueError(f"candidate video format is invalid: {probe}")
    if abs(float(probe["duration_seconds"]) - 40.8) > 0.08:
        raise ValueError("candidate duration is outside the V6.2 boundary")
    scan = _technical_scan(candidate)
    if scan["freeze_event_count"] or scan["black_event_count"]:
        raise ValueError(f"candidate technical scan failed: {scan}")

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

    packet = {
        "schema_version": "fanqie_v62_full_machine_review_packet/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "task_id": 1,
        "scope": "v62_full_microshot_candidate",
        "variant": "original_recomposed",
        "plan_path": str(plan_path),
        "plan_sha256": plan_sha,
        "candidate_path": str(candidate),
        "candidate_sha256": _sha256(candidate),
        "candidate_audit_path": str(audit_path),
        "candidate_audit_sha256": _sha256(audit_path),
        "render_progress_path": str(progress_path),
        "render_progress_sha256": _sha256(progress_path),
        "contact_sheet_path": str(contact),
        "contact_sheet_sha256": _sha256(contact),
        "probe": probe,
        "technical_scan": scan,
        "frames": frames,
        "render_disclosure": {
            "renderer_units": renderer_counts,
            "microshot_count": 32,
            "all_media_generated_locally": True,
        },
        "machine_gate_passed": True,
        "visual_style_and_motion_require_human_confirmation": True,
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
        "schema_version": "fanqie_v62_full_human_review/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "task_id": 1,
        "target_promotion_task_id": None,
        "scope": "v62_full_microshot_candidate",
        "variant": "original_recomposed",
        "plan_path": str(plan_path),
        "plan_sha256": plan_sha,
        "review_status": "pending_review",
        "decision": None,
        "reviewer": "",
        "reviewed_at": None,
        "notes": "",
        "candidate_path": str(candidate),
        "candidate_sha256": _sha256(candidate),
        "contact_sheet_path": str(contact),
        "contact_sheet_sha256": _sha256(contact),
        "machine_review_packet_path": str(packet_path),
        "machine_review_packet_sha256": _sha256(packet_path),
        "checks": {key: None for key in sorted(CHECKS)},
    }
    _write_atomic(review_path, review)
    print(json.dumps({"status": "V62_FULL_REVIEW_READY", "review_path": str(review_path), "review_sha256": _sha256(review_path), "packet_path": str(packet_path), "publish_allowed": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
