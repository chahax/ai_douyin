"""Bind one re-rendered motion unit to the other 18 immutable V6.2 units."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE_PLAN = ROOT / r"data\fanqie_promotion\scene_plans\task1_story_v62_microshot_workflow.json"
REVISION_PLAN = ROOT / r"data\fanqie_promotion\scene_plans\task1_story_v62_microshot_workflow_exaggerated_motion_v1.json"
BASE_PROGRESS = ROOT / r"data\qa\task1_story_v62_microshot_20260821\ltx\original_recomposed\progress.json"
REVISION_DIR = ROOT / r"data\qa\task1_story_v62_microshot_20260821\ltx_exaggerated_motion_v1\original_recomposed"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, timeout=30,
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
    parser.add_argument("--revision-dir", type=Path, default=REVISION_DIR)
    args = parser.parse_args()
    revision_dir = args.revision_dir.resolve()
    base = json.loads(BASE_PROGRESS.read_text(encoding="utf-8"))
    revision_plan = json.loads(REVISION_PLAN.read_text(encoding="utf-8"))
    revision = revision_plan.get("revision") or {}
    if revision.get("parent_plan_sha256") != _sha256(BASE_PLAN):
        raise ValueError("revision parent plan binding changed")
    if revision.get("changed_scene_ids") != ["b01_boast"]:
        raise ValueError("unexpected motion revision scope")
    partial_path = revision_dir / "progress.json"
    archived = revision_dir / "progress.b01_only.json"
    source_progress_path = archived if archived.exists() else partial_path
    partial = json.loads(source_progress_path.read_text(encoding="utf-8"))
    partial_rows = partial.get("shots") or []
    if len(partial_rows) != 1 or partial_rows[0].get("scene_id") != "b01_boast" or partial_rows[0].get("status") != "rendered":
        raise ValueError("opening motion re-render is incomplete")
    replacement = partial_rows[0]
    replacement_path = Path(str(replacement["output_path"])).resolve()
    source = revision_dir / "b01_boast.pre_delivery_align.mp4"
    if not source.exists():
        if not replacement_path.is_file() or _sha256(replacement_path) != replacement["output_sha256"]:
            raise ValueError("opening motion re-render changed before latency normalization")
        shutil.copy2(replacement_path, source)
    if _sha256(source) != replacement["output_sha256"]:
        raise ValueError("opening motion source no longer matches the provider result")
    source_duration = _duration(source)
    if source_duration < 2.65:
        raise ValueError("opening motion source is unexpectedly short")
    pending = replacement_path.with_suffix(".pending.mp4")
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(source), "-an",
            "-vf", (
                "trim=start=0.950:end=2.700,"
                "setpts=1.6*(PTS-STARTPTS),fps=50,"
                "tpad=stop_mode=clone:stop_duration=0.1,trim=duration=2.8"
            ),
            "-c:v", "libx264", "-preset", "medium", "-crf", "17",
            "-pix_fmt", "yuv420p", str(pending),
        ],
        capture_output=True, text=True,
    )
    if result.returncode:
        raise RuntimeError(result.stderr[-2000:])
    pending.replace(replacement_path)
    replacement["motion_latency_normalization"] = {
        "source_path": str(source),
        "source_sha256": _sha256(source),
        "source_duration_seconds": round(source_duration, 3),
        "trim_start_seconds": 0.95,
        "trim_end_seconds": 2.7,
        "setpts_multiplier": 1.6,
        "output_duration_seconds": round(_duration(replacement_path), 3),
        "reason": "remove LTX first-frame motion latency and preserve visible full-body action",
    }
    replacement["output_sha256"] = _sha256(replacement_path)
    base_rows = {str(row["scene_id"]): row for row in base.get("shots") or []}
    if len(base_rows) != 19:
        raise ValueError("base hybrid progress is incomplete")
    base_rows["b01_boast"] = replacement
    order = [str(row["scene_id"]) for row in revision_plan["variants"]["original_recomposed"]["new_framepack_units"]]
    if not archived.exists():
        shutil.copy2(partial_path, archived)
    progress = {
        **base,
        "plan_path": str(REVISION_PLAN.resolve()),
        "plan_sha256": _sha256(REVISION_PLAN),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "renderer": "hybrid_v62_with_exaggerated_b01_ltx_revision",
        "revision": revision,
        "revision_partial_progress_path": str(archived),
        "revision_partial_progress_sha256": _sha256(archived),
        "shots": [base_rows[scene_id] for scene_id in order],
        "success": True,
        "publish_allowed": False,
        "fanqie_backfill_allowed": False,
        "human_review_required": True,
    }
    _write_atomic(partial_path, progress)
    print(json.dumps({"status": "MOTION_REVISION_PROGRESS_READY", "progress": str(partial_path), "sha256": _sha256(partial_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
