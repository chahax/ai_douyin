from __future__ import annotations

"""Prepare immutable machine evidence and a pending frontend whole-video review."""

import argparse
import hashlib
import json
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(r"D:\IT\ai_douyin")
AUDIT_SCHEMA = "fanqie_v61_full_candidate_audit/v2"
PACKET_SCHEMA = "fanqie_v61_full_machine_review_packet/v1"
REVIEW_SCHEMA = "fanqie_v61_full_human_review/v1"
EXPECTED_PLAN_SHA256 = "D2C15C86B0AC57BE8CD26EF687C65C049D64B2069568707C8B699AE6D5828CB4"
EXPECTED_DURATION = 40.8
SAMPLE_FRACTIONS = tuple(index / 12 for index in range(1, 12))
GLOBAL_CHECKS = (
    "complete_video_watched_from_start_to_finish",
    "all_19_beats_present_in_reviewed_order",
    "photorealistic_live_action_only",
    "no_anime_cartoon_chibi_or_digital_presenter",
    "no_explanatory_narration",
    "character_identity_and_wardrobe_consistent",
    "actions_and_emotion_changes_are_readable",
    "lip_sync_is_acceptable_for_all_spoken_closeups",
    "voices_are_fixed_clear_and_emotionally_natural",
    "pace_is_tight_without_slow_motion_or_long_holds",
    "cuts_audio_and_subtitles_are_synchronized",
    "subtitle_text_is_correct_readable_and_safe",
    "no_unapproved_text_logo_watermark_or_visual_artifact",
    "approved_as_douyin_upload_candidate",
)
DEFAULT_CANDIDATE_ROOT = PROJECT_ROOT / "data/qa/task1_story_v61_full_candidate"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "data/qa/task1_story_v61_full_review_packet"
DEFAULT_REVIEW = PROJECT_ROOT / "data/qa/task1_story_v61_full_review.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"JSON file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid JSON {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return data


def _write_new(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise ValueError(f"Refusing to overwrite evidence: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _probe(path: Path) -> dict[str, Any]:
    result = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries",
        "stream=codec_type,avg_frame_rate,width,height,sample_rate,channels",
        "-show_entries", "format=duration", "-of", "json", str(path),
    ], capture_output=True, text=True, check=False, timeout=60)
    if result.returncode != 0:
        raise ValueError(f"ffprobe rejected candidate: {result.stderr[-800:]}")
    try:
        data = json.loads(result.stdout)
        video = next(item for item in data["streams"] if item.get("codec_type") == "video")
        audio = next((item for item in data["streams"] if item.get("codec_type") == "audio"), None)
        n, d = str(video["avg_frame_rate"]).split("/", 1)
        return {
            "duration_seconds": float(data["format"]["duration"]),
            "fps": float(n) / float(d), "width": int(video["width"]),
            "height": int(video["height"]), "audio_present": audio is not None,
            "audio_sample_rate": int(audio["sample_rate"]) if audio else None,
            "audio_channels": int(audio["channels"]) if audio else None,
        }
    except (KeyError, StopIteration, TypeError, ValueError, ZeroDivisionError) as exc:
        raise ValueError("ffprobe returned invalid candidate metadata") from exc


def _extract(video: Path, output: Path, timestamp: float) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{timestamp:.6f}", "-i", str(video), "-frames:v", "1",
        "-update", "1", str(output),
    ], capture_output=True, text=True, check=False, timeout=60)
    if result.returncode != 0 or not output.is_file():
        raise ValueError(f"frame extraction failed: {result.stderr[-800:]}")


def _contact(items: list[tuple[str, Path]], output: Path) -> None:
    columns, cell_w, cell_h, label_h = 3, 320, 568, 42
    rows = (len(items) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * cell_w, rows * (cell_h + label_h)), "black")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=17)
    for index, (label, path) in enumerate(items):
        with Image.open(path) as source:
            image = source.convert("RGB")
            image.thumbnail((cell_w, cell_h), Image.Resampling.LANCZOS)
        x = (index % columns) * cell_w
        y = (index // columns) * (cell_h + label_h)
        sheet.paste(image, (x + (cell_w - image.width) // 2, y + (cell_h - image.height) // 2))
        draw.text((x + 8, y + cell_h + 10), label, fill="white", font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)


def prepare_packet(
    *, candidate_root: Path,
    output_root: Path,
    review_path: Path,
    probe_video=_probe,
    extract_frame=_extract,
    build_contact=_contact,
) -> dict[str, Any]:
    if output_root.exists() or review_path.exists():
        raise ValueError("Refusing to overwrite an existing whole-video review artifact")
    audit_path = candidate_root / "candidate_audit.json"
    audit = _load_json(audit_path)
    if audit.get("schema_version") != AUDIT_SCHEMA:
        raise ValueError("candidate audit schema mismatch")
    if audit.get("task_id") != 1 or audit.get("scope") != "full_19_beat_candidate":
        raise ValueError("candidate audit task/scope mismatch")
    if str(audit.get("plan_sha256") or "").upper() != EXPECTED_PLAN_SHA256:
        raise ValueError("candidate audit plan SHA mismatch")
    if audit.get("shot_count") != 19 or audit.get("machine_composition_gate_passed") is not True:
        raise ValueError("candidate audit does not prove 19-shot composition")
    for key in (
        "human_full_video_review_completed", "matching_fanqie_task_confirmed",
        "douyin_upload_allowed", "fanqie_backfill_allowed",
    ):
        if audit.get(key) is not False:
            raise ValueError(f"candidate audit {key} must remain false")
    candidate = Path(str(audit.get("candidate_path") or "")).resolve()
    manifest = Path(str(audit.get("story_manifest_path") or "")).resolve()
    subtitle = Path(str(audit.get("subtitle_path") or "")).resolve()
    for label, path, sha_key in (
        ("candidate", candidate, "candidate_sha256"),
        ("manifest", manifest, "story_manifest_sha256"),
        ("subtitle", subtitle, "subtitle_sha256"),
    ):
        if not path.is_file() or _sha256(path) != str(audit.get(sha_key) or "").upper():
            raise ValueError(f"{label} file missing or SHA mismatch")
    pre_sha = _sha256(candidate)
    probe = probe_video(candidate)
    if _sha256(candidate) != pre_sha:
        raise ValueError("candidate changed during probe")
    if abs(float(probe["duration_seconds"]) - EXPECTED_DURATION) > 0.30:
        raise ValueError("candidate duration outside 40.8s +/-0.30s")
    if abs(float(probe["fps"]) - 50.0) > 0.01:
        raise ValueError("candidate fps must be 50")
    if probe.get("audio_present") is not True:
        raise ValueError("candidate audio stream is missing")

    output_root.parent.mkdir(parents=True, exist_ok=True)
    try:
        output_root.mkdir(exist_ok=False)
    except FileExistsError as exc:
        raise ValueError("Whole-video review output is already reserved") from exc
    staging = output_root / f".{uuid.uuid4().hex}.staging"
    frames: list[dict[str, Any]] = []
    contact_items: list[tuple[str, Path]] = []
    try:
        for position, fraction in enumerate(SAMPLE_FRACTIONS, start=1):
            timestamp = float(probe["duration_seconds"]) * fraction
            relative = Path("frames") / f"full_{position:02d}.png"
            staging_frame = staging / relative
            final_frame = output_root / relative
            extract_frame(candidate, staging_frame, timestamp)
            frame_sha = _sha256(staging_frame)
            frames.append({
                "position": position, "fraction": fraction,
                "timestamp_seconds": round(timestamp, 4),
                "path": str(final_frame.resolve()), "sha256": frame_sha,
            })
            contact_items.append((f"{position:02d} / {timestamp:.2f}s", staging_frame))
        contact_path = output_root / "contact_sheet.png"
        staging_contact = staging / "contact_sheet.png"
        build_contact(contact_items, staging_contact)
        contact_sha = _sha256(staging_contact)
        if _sha256(candidate) != pre_sha:
            raise ValueError("candidate changed during frame extraction")
        packet = {
            "schema_version": PACKET_SCHEMA,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "task_id": 1, "scope": "full_19_beat_candidate",
            "plan_sha256": EXPECTED_PLAN_SHA256,
            "candidate_audit_path": str(audit_path.resolve()),
            "candidate_audit_sha256": _sha256(audit_path),
            "candidate_path": str(candidate), "candidate_sha256": pre_sha,
            "story_manifest_path": str(manifest), "story_manifest_sha256": _sha256(manifest),
            "subtitle_path": str(subtitle), "subtitle_sha256": _sha256(subtitle),
            "probe": probe, "sample_count": len(frames), "frames": frames,
            "contact_sheet_path": str(contact_path.resolve()),
            "contact_sheet_sha256": contact_sha,
            "machine_gate_scope": "whole_video_file_integrity_and_media_structure_only",
            "human_visual_audio_editorial_review_required": True,
            "machine_gate_passed": True,
            "human_full_video_review_completed": False,
            "matching_fanqie_task_confirmed": False,
            "douyin_upload_allowed": False, "fanqie_backfill_allowed": False,
        }
        _write_new(staging / "machine_review_packet.json", packet)
        for artifact in staging.iterdir():
            artifact.replace(output_root / artifact.name)
        staging.rmdir()
        packet_path = output_root / "machine_review_packet.json"
        review = {
            "schema_version": REVIEW_SCHEMA,
            "task_id": 1, "scope": "full_19_beat_candidate",
            "plan_sha256": EXPECTED_PLAN_SHA256,
            "review_status": "pending_review", "reviewer": "", "reviewer_id": "",
            "reviewed_at": None,
            "playback_started_at": None, "playback_finished_at": None,
            "playback_candidate_sha256": pre_sha,
            "machine_review_packet_path": str(packet_path.resolve()),
            "machine_review_packet_sha256": _sha256(packet_path),
            "candidate_path": str(candidate), "candidate_sha256": pre_sha,
            "contact_sheet_path": str(contact_path.resolve()),
            "contact_sheet_sha256": contact_sha,
            "checks": {key: None for key in GLOBAL_CHECKS},
            "decision": "pending", "notes": "",
        }
        _write_new(review_path, review)
        return {
            "packet_path": str(packet_path.resolve()),
            "packet_sha256": _sha256(packet_path),
            "review_draft_path": str(review_path.resolve()),
            "review_draft_sha256": _sha256(review_path),
            "sample_count": len(frames),
            "human_full_video_review_completed": False,
            "douyin_upload_allowed": False, "fanqie_backfill_allowed": False,
        }
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        if output_root.exists() and not any(output_root.iterdir()):
            output_root.rmdir()
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare V6.1 whole-video review packet.")
    parser.add_argument("--candidate-root", type=Path, default=DEFAULT_CANDIDATE_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--review-output", type=Path, default=DEFAULT_REVIEW)
    args = parser.parse_args(argv)
    try:
        result = prepare_packet(
            candidate_root=args.candidate_root.resolve(), output_root=args.output_root.resolve(),
            review_path=args.review_output.resolve(),
        )
    except ValueError as exc:
        print(json.dumps({
            "success": False, "error": str(exc),
            "human_full_video_review_completed": False,
            "douyin_upload_allowed": False, "fanqie_backfill_allowed": False,
        }, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"success": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
