"""Pad only genuinely short V6.2 delivery clips and record the transformation."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = ROOT / r"data\fanqie_promotion\scene_plans\task1_story_v62_microshot_workflow.json"
DEFAULT_RENDER_DIR = ROOT / r"data\qa\task1_story_v62_microshot_20260821\ltx\original_recomposed"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode:
        raise RuntimeError(result.stderr[-1000:])
    return float(result.stdout.strip())


def _write_atomic(path: Path, value: dict[str, object]) -> None:
    pending = path.with_suffix(path.suffix + ".pending")
    pending.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pending.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--render-dir", type=Path, default=DEFAULT_RENDER_DIR)
    args = parser.parse_args()
    plan_path = args.plan.resolve()
    render_dir = args.render_dir.resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    branch = plan["variants"]["original_recomposed"]
    required: dict[str, float] = {}
    for shot in branch["microshots"]:
        scene_id = str(shot["source_unit"])
        required[scene_id] = max(
            required.get(scene_id, 0.0),
            float(shot["source_start_seconds"]) + float(shot["duration_seconds"]),
        )

    backup_dir = render_dir / "pre_delivery_align"
    backup_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    for scene_id, target in required.items():
        destination = render_dir / f"{scene_id}.mp4"
        if not destination.is_file():
            raise FileNotFoundError(destination)
        actual = _duration(destination)
        if actual + 0.04 >= target:
            continue
        source = backup_dir / destination.name
        if not source.exists():
            shutil.copy2(destination, source)
        source_sha = _sha256(source)
        pending = destination.with_suffix(".delivery_align.pending.mp4")
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(source), "-an",
                "-vf", f"tpad=stop_mode=clone:stop_duration=1,trim=duration={target:.3f},setpts=PTS-STARTPTS,fps=50",
                "-c:v", "libx264", "-preset", "medium", "-crf", "17",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(pending),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise RuntimeError(f"delivery alignment failed for {scene_id}: {result.stderr[-2000:]}")
        pending.replace(destination)
        final_duration = _duration(destination)
        if abs(final_duration - target) > 0.04:
            raise RuntimeError(f"delivery alignment duration mismatch for {scene_id}")
        rows.append(
            {
                "scene_id": scene_id,
                "operation": "tail_frame_clone_to_required_microshot_boundary",
                "source_path": str(source),
                "source_sha256": source_sha,
                "source_duration_seconds": round(actual, 3),
                "output_path": str(destination),
                "output_sha256": _sha256(destination),
                "output_duration_seconds": round(final_duration, 3),
                "target_duration_seconds": target,
                "publish_allowed": False,
            }
        )

    manifest = {
        "schema_version": "fanqie_v62_delivery_duration_alignment/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "plan_path": str(plan_path),
        "plan_sha256": _sha256(plan_path),
        "rows": rows,
        "publish_allowed": False,
        "human_review_required": True,
    }
    manifest_path = render_dir / "delivery_duration_alignment.json"
    _write_atomic(manifest_path, manifest)
    print(json.dumps({"status": "DELIVERY_DURATIONS_READY", "aligned": len(rows), "manifest": str(manifest_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
