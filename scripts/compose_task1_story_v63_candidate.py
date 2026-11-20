"""Compose the complete non-publishable V6.3 visual-retention candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.compose_task1_story_v62_candidate import (
    _escape_subtitle_filter,
    _probe_duration,
    _run,
    _video_filter,
)


DEFAULT_PLAN = ROOT / r"data\fanqie_promotion\scene_plans\task1_story_v63_visual_retention_workflow_v1.json"
DEFAULT_RENDER_ROOT = ROOT / r"data\qa\task1_story_v63_full_render_20260822_visual_retention_v1"
DEFAULT_OUTPUT = ROOT / r"data\qa\task1_story_v63_full_candidate_20260822_visual_retention_v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--render-root", type=Path, default=DEFAULT_RENDER_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    plan_path = args.plan.resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("schema_version") != "fanqie_v63_visual_retention_workflow/v1":
        raise ValueError("unexpected V6.3 workflow schema")
    branch = plan["variants"]["visual_retention_v1"]
    if branch.get("publish_allowed") is not False or branch.get("fanqie_backfill_allowed") is not False:
        raise ValueError("V6.3 candidate branch lost its non-publication gate")
    if branch.get("reference_video_pixels_allowed") is not False:
        raise ValueError("reference pixels cannot enter the V6.3 candidate")

    render_dir = args.render_root.resolve()
    progress_path = render_dir / "progress.json"
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    if progress.get("schema_version") != "fanqie_v63_render_progress/v1":
        raise ValueError("unexpected V6.3 render progress schema")
    if progress.get("plan_sha256") != _sha256(plan_path):
        raise ValueError("render progress is not bound to this V6.3 plan")
    if progress.get("success") is not True:
        raise ValueError("V6.3 render progress is incomplete")
    rendered = {
        str(row["scene_id"]): row
        for row in progress.get("shots", [])
        if isinstance(row, dict) and row.get("status") == "rendered"
    }
    required_units = {str(unit["scene_id"]) for unit in branch["new_framepack_units"]}
    if set(rendered) != required_units or len(rendered) != 19:
        raise ValueError("rendered scene set does not match the 19 V6.3 units")
    if set(progress["renderer_partition"].get("local_framepack_i2v", [])) != set(branch["action_scene_ids"]):
        raise ValueError("V6.3 action renderer partition mismatch")
    if set(progress["renderer_partition"].get("deterministic_camera_motion_candidate_only", [])) != set(branch["stable_insert_scene_ids"]):
        raise ValueError("V6.3 stable renderer partition mismatch")

    output_dir = args.output_dir.resolve()
    candidate = output_dir / "candidate.mp4"
    if candidate.exists() and not args.force:
        raise FileExistsError(f"candidate already exists: {candidate}")
    output_dir.mkdir(parents=True, exist_ok=True)
    microshot_dir = output_dir / "microshots"
    microshot_dir.mkdir(parents=True, exist_ok=True)

    microshot_rows: list[dict[str, object]] = []
    concat_lines: list[str] = []
    for index, shot in enumerate(branch["microshots"], start=1):
        source_unit = str(shot["source_unit"])
        source_row = rendered[source_unit]
        source = Path(str(source_row["output_path"])).resolve()
        if not source.is_file() or _sha256(source) != source_row["output_sha256"]:
            raise ValueError(f"render changed after progress binding: {source_unit}")
        destination = microshot_dir / f"{index:03d}_{shot['shot_id']}.mp4"
        _run(
            [
                "ffmpeg", "-y", "-ss", f"{float(shot['source_start_seconds']):.3f}",
                "-i", str(source), "-t", f"{float(shot['duration_seconds']):.3f}", "-an",
                "-vf", _video_filter(str(shot["crop"])), "-c:v", "libx264",
                "-preset", "medium", "-crf", "17", "-movflags", "+faststart", str(destination),
            ]
        )
        actual_duration = _probe_duration(destination)
        expected_duration = float(shot["duration_seconds"])
        if abs(actual_duration - expected_duration) > 0.07:
            raise RuntimeError(
                f"micro-shot duration mismatch for {shot['shot_id']}: "
                f"{actual_duration:.3f}s vs {expected_duration:.3f}s"
            )
        microshot_rows.append(
            {
                **shot,
                "renderer": source_row["renderer"],
                "source_path": str(source),
                "source_sha256": source_row["output_sha256"],
                "output_path": str(destination),
                "output_sha256": _sha256(destination),
                "actual_duration_seconds": actual_duration,
            }
        )
        concat_lines.append(f"file '{str(destination).replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'")

    concat_path = output_dir / "concat.txt"
    concat_path.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")
    silent = output_dir / "candidate_silent.mp4"
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_path), "-c", "copy", str(silent)])

    audio_source = Path(str(plan["audio_source"])).resolve()
    subtitle_source = Path(str(plan["subtitle_source"])).resolve()
    if not audio_source.is_file() or not subtitle_source.is_file():
        raise FileNotFoundError("V6.1 audio/subtitle source is missing")
    subtitle_filter = (
        "subtitles=filename='" + _escape_subtitle_filter(subtitle_source)
        + "':force_style='FontName=Microsoft YaHei,FontSize=18,"
        "PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,BorderStyle=1,"
        "Outline=2,Shadow=0,Alignment=2,MarginV=90'"
    )
    pending = output_dir / "candidate.pending.mp4"
    _run(
        [
            "ffmpeg", "-y", "-i", str(silent), "-i", str(audio_source), "-map", "0:v:0", "-map", "1:a:0",
            "-t", "40.8", "-vf", subtitle_filter, "-c:v", "libx264", "-preset", "medium", "-crf", "17",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(pending),
        ]
    )
    pending.replace(candidate)
    shutil.copy2(subtitle_source, output_dir / "candidate.srt")

    duration = _probe_duration(candidate)
    if abs(duration - 40.8) > 0.08:
        raise RuntimeError(f"candidate duration is {duration:.3f}s, expected 40.8s")
    audit = {
        "schema_version": "fanqie_v63_visual_retention_candidate/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "variant": "visual_retention_v1",
        "role": branch["role"],
        "style_variant": branch["style_variant"],
        "visual_phases": branch["visual_phases"],
        "plan_path": str(plan_path),
        "plan_sha256": _sha256(plan_path),
        "render_progress_path": str(progress_path),
        "render_progress_sha256": _sha256(progress_path),
        "renderer_partition": progress["renderer_partition"],
        "audio_source_path": str(audio_source),
        "audio_source_sha256": _sha256(audio_source),
        "subtitle_source_path": str(subtitle_source),
        "subtitle_source_sha256": _sha256(subtitle_source),
        "microshots": microshot_rows,
        "candidate_path": str(candidate),
        "candidate_sha256": _sha256(candidate),
        "duration_seconds": duration,
        "reference_video_pixels_used": False,
        "reference_people_used": False,
        "reference_watermark_used": False,
        "publish_allowed": False,
        "fanqie_backfill_allowed": False,
        "human_review_required": True,
    }
    audit_path = output_dir / "compose_audit.json"
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(candidate)
    print(audit["candidate_sha256"])
    print(audit_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
