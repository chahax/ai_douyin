"""Auditably reverse selected V6.3 scene playback after visual direction QA."""

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


DEFAULT_PROGRESS = ROOT / r"data\qa\task1_story_v63_full_render_20260822_visual_retention_v1\progress.json"
ALLOWED_SCENES = {"b05_age_burst"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _write_atomic(path: Path, value: dict[str, object]) -> None:
    pending = path.with_suffix(".pending.json")
    pending.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pending.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--progress", type=Path, default=DEFAULT_PROGRESS)
    parser.add_argument("--scene", action="append", choices=sorted(ALLOWED_SCENES), default=[])
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    scenes = set(args.scene) or set(ALLOWED_SCENES)

    progress_path = args.progress.resolve()
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    if progress.get("schema_version") != "fanqie_v63_render_progress/v1":
        raise ValueError("unexpected V6.3 progress schema")
    rows = {str(row["scene_id"]): row for row in progress.get("shots", []) if isinstance(row, dict)}
    for scene_id in sorted(scenes):
        row = rows.get(scene_id)
        if not row or row.get("status") != "rendered":
            raise ValueError(f"scene is not rendered: {scene_id}")
        provenance = row.get("provenance") or {}
        if provenance.get("playback_direction_repaired") is True and not args.force:
            print(f"SKIP {scene_id}: already reversed", flush=True)
            continue
        video = Path(str(row["output_path"])).resolve()
        original_sha = _sha256(video)
        if original_sha != row.get("output_sha256"):
            raise ValueError(f"scene changed before direction repair: {scene_id}")
        pending = video.with_suffix(".direction.pending.mp4")
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(video), "-an", "-vf",
                "reverse,setpts=PTS-STARTPTS,fps=30,format=yuv420p",
                "-c:v", "libx264", "-preset", "medium", "-crf", "16",
                "-movflags", "+faststart", str(pending),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise RuntimeError(result.stderr[-2000:])
        pending.replace(video)
        metrics = analyze_video_smoothness(
            video, analysis_fps=15.0, analysis_width=160, duplicate_threshold=0.12
        )
        if float(metrics["duplicate_ratio"]) > 0.12 or float(metrics["mean_frame_distance"]) < 0.5:
            raise ValueError(f"direction-repaired scene failed motion gate: {scene_id}: {metrics}")
        if float(metrics["smoothness_score"]) < 65.0:
            raise ValueError(f"direction-repaired scene failed smoothness gate: {scene_id}: {metrics}")
        row["output_sha256"] = _sha256(video)
        row["motion_metrics"] = metrics
        row["provenance"] = {
            **provenance,
            "playback_direction_repaired": True,
            "direction_repair_reason": "visual QA requires watch glance followed by raised-finger emphasis",
            "pre_repair_output_sha256": original_sha,
            "repair_filter": "reverse,setpts=PTS-STARTPTS,fps=30",
            "repaired_at": datetime.now(timezone.utc).isoformat(),
        }
        print(f"REVERSED {scene_id}: {metrics}", flush=True)

    progress["shots"] = [rows[key] for key in sorted(rows)]
    progress["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write_atomic(progress_path, progress)
    print(progress_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
