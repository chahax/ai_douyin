"""Compose a non-publishable V6.2 candidate from rendered motion units."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = ROOT / (
    r"data\fanqie_promotion\scene_plans\task1_story_v62_microshot_workflow.json"
)
DEFAULT_RENDER_ROOT = ROOT / r"data\qa\task1_story_v62_microshot_20260821\ltx"
DEFAULT_OUTPUT = ROOT / (
    r"data\qa\task1_story_v62_full_candidate_20260822_original_ltx"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _run(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            f"{result.stderr[-4000:]}"
        )


def _probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode:
        raise RuntimeError(f"ffprobe failed: {result.stderr[-1000:]}")
    return float(result.stdout.strip())


def _video_filter(crop: str) -> str:
    base = "scale=1080:1920:flags=lanczos"
    variants = {
        "full": "",
        "background_detail": ",crop=972:1728:54:96,scale=1080:1920:flags=lanczos",
        "upper_close": ",crop=864:1536:108:24,scale=1080:1920:flags=lanczos",
        "eye_close": ",crop=756:1344:162:0,scale=1080:1920:flags=lanczos",
        "lower_detail": ",crop=864:1536:108:360,scale=1080:1920:flags=lanczos",
        "hand_close": ",crop=864:1536:108:220,scale=1080:1920:flags=lanczos",
    }
    if crop not in variants:
        raise ValueError(f"unsupported micro-shot crop: {crop}")
    return f"{base}{variants[crop]},fps=30,format=yuv420p"


def _escape_subtitle_filter(path: Path) -> str:
    value = str(path.resolve()).replace("\\", "/")
    value = value.replace(":", r"\:").replace("'", r"\'")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", default="original_recomposed")
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--render-root", type=Path, default=DEFAULT_RENDER_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    plan_path = args.plan.resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("schema_version") != "fanqie_v62_microshot_workflow/v2":
        raise ValueError("unexpected V6.2 workflow schema")
    branch = plan["variants"][args.variant]
    if branch.get("publish_allowed") is not False:
        raise ValueError("candidate branch must remain non-publishable")
    if args.variant == "direct_reference_i2v" and not branch.get(
        "frontend_approval_cannot_authorize_publication"
    ):
        raise ValueError("direct-reference branch lost its publication guard")

    render_dir = args.render_root.resolve() / args.variant
    progress_path = render_dir / "progress.json"
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    if progress.get("schema_version") != "fanqie_v62_ltx_progress/v1":
        raise ValueError("unexpected LTX progress schema")
    if progress.get("plan_sha256") != _sha256(plan_path):
        raise ValueError("LTX progress is not bound to this plan")
    if progress.get("success") is not True:
        raise ValueError("LTX batch is incomplete")
    rendered = {
        str(row["scene_id"]): row
        for row in progress.get("shots", [])
        if isinstance(row, dict) and row.get("status") == "rendered"
    }
    required_units = {
        str(unit["scene_id"]) for unit in branch["new_framepack_units"]
    }
    if set(rendered) != required_units:
        raise ValueError("rendered scene set does not match the branch units")

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
        source = Path(str(rendered[source_unit]["output_path"]))
        if not source.is_file() or _sha256(source) != rendered[source_unit]["output_sha256"]:
            raise ValueError(f"render changed after progress binding: {source_unit}")
        destination = microshot_dir / f"{index:03d}_{shot['shot_id']}.mp4"
        _run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                f"{float(shot['source_start_seconds']):.3f}",
                "-i",
                str(source),
                "-t",
                f"{float(shot['duration_seconds']):.3f}",
                "-an",
                "-vf",
                _video_filter(str(shot["crop"])),
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "17",
                "-movflags",
                "+faststart",
                str(destination),
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
                "source_path": str(source),
                "source_sha256": rendered[source_unit]["output_sha256"],
                "output_path": str(destination),
                "output_sha256": _sha256(destination),
                "actual_duration_seconds": actual_duration,
            }
        )
        escaped = str(destination).replace("'", "'\\''")
        concat_lines.append(f"file '{escaped}'")

    concat_path = output_dir / "concat.txt"
    concat_path.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")
    silent = output_dir / "candidate_silent.mp4"
    _run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_path),
            "-c",
            "copy",
            str(silent),
        ]
    )

    audio_source = Path(str(plan["audio_source"]))
    subtitle_source = Path(str(plan["subtitle_source"]))
    if not audio_source.is_file() or not subtitle_source.is_file():
        raise FileNotFoundError("approved V6.1 audio/subtitle source is missing")
    subtitle_filter = (
        "subtitles=filename='"
        + _escape_subtitle_filter(subtitle_source)
        + "':force_style='FontName=Microsoft YaHei,FontSize=18,"
        "PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,BorderStyle=1,"
        "Outline=2,Shadow=0,Alignment=2,MarginV=90'"
    )
    pending = output_dir / "candidate.pending.mp4"
    _run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(silent),
            "-i",
            str(audio_source),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-t",
            "40.8",
            "-vf",
            subtitle_filter,
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "17",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(pending),
        ]
    )
    pending.replace(candidate)
    shutil.copy2(subtitle_source, output_dir / "candidate.srt")

    duration = _probe_duration(candidate)
    if abs(duration - 40.8) > 0.08:
        raise RuntimeError(f"candidate duration is {duration:.3f}s, expected 40.8s")
    audit = {
        "schema_version": "fanqie_v62_microshot_candidate/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "variant": args.variant,
        "role": branch.get("role"),
        "plan_path": str(plan_path),
        "plan_sha256": _sha256(plan_path),
        "render_progress_path": str(progress_path),
        "render_progress_sha256": _sha256(progress_path),
        "audio_source_path": str(audio_source),
        "audio_source_sha256": _sha256(audio_source),
        "subtitle_source_path": str(subtitle_source),
        "subtitle_source_sha256": _sha256(subtitle_source),
        "microshots": microshot_rows,
        "candidate_path": str(candidate),
        "candidate_sha256": _sha256(candidate),
        "duration_seconds": duration,
        "publish_allowed": False,
        "fanqie_backfill_allowed": False,
        "human_review_required": True,
        "frontend_approval_cannot_authorize_publication": bool(
            branch.get("frontend_approval_cannot_authorize_publication", False)
        ),
    }
    audit_path = output_dir / "compose_audit.json"
    audit_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(candidate)
    print(audit["candidate_sha256"])
    print(audit_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
