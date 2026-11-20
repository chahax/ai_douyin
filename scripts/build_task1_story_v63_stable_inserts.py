from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.content_factory.video_smoothness import analyze_video_smoothness


DEFAULT_PLAN = ROOT / r"data\fanqie_promotion\scene_plans\task1_story_v63_visual_retention_workflow_v1.json"
DEFAULT_OUTPUT = ROOT / r"data\qa\task1_story_v63_full_render_20260822_visual_retention_v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _write_json(path: Path, value: dict[str, object]) -> None:
    pending = path.with_suffix(".pending.json")
    pending.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pending.replace(path)


def _run(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(command)}\n{result.stderr[-4000:]}")


def _initial_progress(plan_path: Path, output_root: Path) -> dict[str, object]:
    return {
        "schema_version": "fanqie_v63_render_progress/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "task_id": 1,
        "variant": "visual_retention_v1",
        "plan_path": str(plan_path),
        "plan_sha256": _sha256(plan_path),
        "output_root": str(output_root),
        "shots": [],
        "renderer_partition": {
            "local_framepack_i2v": [],
            "deterministic_camera_motion_candidate_only": [],
        },
        "action_complete": False,
        "stable_inserts_complete": False,
        "success": False,
        "publish_allowed": False,
        "fanqie_backfill_allowed": False,
    }


def _motion_filter(index: int) -> str:
    motions = [
        "z='1.10':x='(iw-iw/zoom)/2+sin(on/15)*(iw-iw/zoom)/8':y='(ih-ih/zoom)/2+cos(on/19)*(ih-ih/zoom)/12'",
        "z='1.11':x='(iw-iw/zoom)/2-sin(on/17)*(iw-iw/zoom)/8':y='(ih-ih/zoom)/2+cos(on/14)*(ih-ih/zoom)/12'",
        "z='1.09':x='(iw-iw/zoom)/2+sin(on/13)*(iw-iw/zoom)/8':y='(ih-ih/zoom)/2-cos(on/18)*(ih-ih/zoom)/12'",
        "z='1.12':x='(iw-iw/zoom)/2-sin(on/16)*(iw-iw/zoom)/8':y='(ih-ih/zoom)/2+cos(on/13)*(ih-ih/zoom)/12'",
    ]
    return motions[index % len(motions)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the eight V6.3 unique stable information inserts.")
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    plan_path = args.plan.resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("schema_version") != "fanqie_v63_visual_retention_workflow/v1":
        raise ValueError("unexpected V6.3 plan schema")
    branch = plan["variants"]["visual_retention_v1"]
    stable_ids = set(branch["stable_insert_scene_ids"])
    action_ids = set(branch["action_scene_ids"])
    units = {str(unit["scene_id"]): unit for unit in branch["new_framepack_units"]}

    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    progress_path = output_root / "progress.json"
    if progress_path.is_file():
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        if progress.get("schema_version") != "fanqie_v63_render_progress/v1":
            raise ValueError("unexpected existing progress schema")
        if progress.get("plan_sha256") != _sha256(plan_path):
            raise ValueError("existing progress is bound to another plan")
    else:
        progress = _initial_progress(plan_path, output_root)
    rows = {str(row["scene_id"]): row for row in progress["shots"] if isinstance(row, dict)}

    for index, scene_id in enumerate(branch["stable_insert_scene_ids"]):
        unit = units[scene_id]
        anchor = Path(str(unit["anchor_path"])).resolve()
        if not anchor.is_file() or _sha256(anchor) != unit["anchor_sha256"]:
            raise ValueError(f"anchor changed: {scene_id}")
        destination = output_root / f"{scene_id}.mp4"
        existing = rows.get(scene_id)
        if (
            not args.force
            and existing
            and existing.get("status") == "rendered"
            and destination.is_file()
            and existing.get("output_sha256") == _sha256(destination)
        ):
            print(f"SKIP {scene_id}: already rendered", flush=True)
            continue

        duration = float(unit["target_duration_seconds"])
        frames = round(duration * 50)
        vf = (
            "scale=704:1248:force_original_aspect_ratio=increase:flags=lanczos,"
            "crop=704:1248,"
            f"zoompan={_motion_filter(index)}:d=1:s=704x1248:fps=50,"
            "format=yuv420p"
        )
        pending = destination.with_suffix(".pending.mp4")
        _run(
            [
                "ffmpeg", "-y", "-loop", "1", "-i", str(anchor), "-frames:v", str(frames),
                "-an", "-vf", vf, "-c:v", "libx264", "-preset", "medium", "-crf", "16",
                "-movflags", "+faststart", str(pending),
            ]
        )
        pending.replace(destination)
        metrics = analyze_video_smoothness(
            destination,
            analysis_fps=15.0,
            analysis_width=160,
            duplicate_threshold=0.12,
        )
        if float(metrics["duplicate_ratio"]) > 0.28:
            raise ValueError(f"{scene_id} stable insert duplicate ratio failed: {metrics['duplicate_ratio']}")
        if float(metrics["smoothness_score"]) < 65.0:
            raise ValueError(f"{scene_id} stable insert smoothness failed: {metrics['smoothness_score']}")
        rows[scene_id] = {
            "scene_id": scene_id,
            "status": "rendered",
            "renderer": "deterministic_camera_motion_candidate_only",
            "seed": unit["seed"],
            "target_duration_seconds": duration,
            "anchor_path": str(anchor),
            "anchor_sha256": unit["anchor_sha256"],
            "prompt": unit["prompt"],
            "negative_prompt": unit["negative_prompt"],
            "output_path": str(destination),
            "output_sha256": _sha256(destination),
            "motion_metrics": metrics,
            "provenance": {
                "mode": "unique_original_anchor_deterministic_camera_motion",
                "ffmpeg_filter": vf,
                "source_reference_video_pixels": False,
            },
            "error": None,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        progress["shots"] = [rows[key] for key in sorted(rows)]
        progress["renderer_partition"]["deterministic_camera_motion_candidate_only"] = sorted(
            key for key, row in rows.items()
            if row.get("renderer") == "deterministic_camera_motion_candidate_only" and row.get("status") == "rendered"
        )
        progress["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_json(progress_path, progress)
        print(f"DONE {scene_id}: {metrics}", flush=True)

    progress["renderer_partition"]["local_framepack_i2v"] = sorted(
        key for key, row in rows.items() if row.get("renderer") == "local_framepack_i2v" and row.get("status") == "rendered"
    )
    progress["renderer_partition"]["deterministic_camera_motion_candidate_only"] = sorted(
        key for key, row in rows.items()
        if row.get("renderer") == "deterministic_camera_motion_candidate_only" and row.get("status") == "rendered"
    )
    progress["action_complete"] = set(progress["renderer_partition"]["local_framepack_i2v"]) == action_ids
    progress["stable_inserts_complete"] = set(progress["renderer_partition"]["deterministic_camera_motion_candidate_only"]) == stable_ids
    progress["success"] = bool(progress["action_complete"] and progress["stable_inserts_complete"] and len(rows) == 19)
    progress["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write_json(progress_path, progress)
    print(json.dumps({"progress": str(progress_path), "stable_inserts_complete": progress["stable_inserts_complete"], "success": progress["success"]}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
