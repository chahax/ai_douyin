"""Render deformation-safe V6.2 closeups with deterministic camera motion."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / r"data\fanqie_promotion\scene_plans\task1_story_v62_microshot_workflow.json"
OUTPUT = ROOT / r"data\qa\task1_story_v62_microshot_20260821\ltx\original_recomposed"
SCENE_IDS = {
    "b08_offer_one",
    "b09_offer_two",
    "b10_offer_three",
    "b13_registry_reveal",
    "b14_certificate",
    "b15_terms",
    "b17a_kiss_reaction",
    "b17b_hunt_order",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _probe(path: Path) -> dict[str, object]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,avg_frame_rate:format=duration",
            "-of", "json", str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode:
        raise RuntimeError(result.stderr[-1000:])
    value = json.loads(result.stdout)
    stream = value["streams"][0]
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "fps": stream["avg_frame_rate"],
        "duration_seconds": float(value["format"]["duration"]),
    }


def _filter(scene_id: str, frames: int) -> str:
    # Keep the movement deliberately modest: these inserts contain exact hand
    # counts or small props, where generative motion is more likely to deform
    # the evidence than improve it.
    # Travel roughly ten percent over the exact clip length; never hit a cap
    # early and turn the tail into duplicate frames.
    zoom_step = f"{0.10 / max(frames, 1):.8f}"
    x = "iw/2-(iw/zoom/2)+sin(on/14)*8*(zoom-1)/0.1"
    y = "ih/2-(ih/zoom/2)+cos(on/18)*6*(zoom-1)/0.1"
    if scene_id == "b13_registry_reveal":
        y = "max(0,ih/2-(ih/zoom/2)-on*0.08)"
    elif scene_id in {"b14_certificate", "b15_terms"}:
        y = "min(ih-ih/zoom,ih/2-(ih/zoom/2)+on*0.05)"
    return (
        "scale=768:1366:force_original_aspect_ratio=increase,"
        "crop=768:1366,"
        f"zoompan=z='min(zoom+{zoom_step},1.12)':x='{x}':y='{y}':"
        f"d={frames}:s=704x1248:fps=50,format=yuv420p"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=PLAN)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    plan_path = args.plan.resolve()
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "fanqie_v62_microshot_workflow/v2":
        raise ValueError("unexpected V6.2 workflow schema")
    branch = payload["variants"]["original_recomposed"]
    units = {
        str(unit["scene_id"]): unit
        for unit in branch["new_framepack_units"]
        if unit["scene_id"] in SCENE_IDS
    }
    if set(units) != SCENE_IDS:
        raise ValueError("stable-closeup scene contract changed")

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for scene_id in sorted(SCENE_IDS):
        unit = units[scene_id]
        anchor = Path(str(unit["anchor_path"]))
        if not anchor.is_file() or _sha256(anchor) != unit["anchor_sha256"]:
            raise ValueError(f"anchor missing or changed: {scene_id}")
        destination = output_dir / f"{scene_id}.mp4"
        if not destination.exists() or args.force:
            frames = round(float(unit["target_duration_seconds"]) * 50)
            command = [
                "ffmpeg", "-y", "-loop", "1", "-framerate", "50",
                "-i", str(anchor), "-frames:v", str(frames), "-an",
                "-vf", _filter(scene_id, frames), "-c:v", "libx264", "-preset", "medium",
                "-crf", "17", "-movflags", "+faststart", str(destination),
            ]
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(f"{scene_id}: {result.stderr[-3000:]}")
        probe = _probe(destination)
        expected = float(unit["target_duration_seconds"])
        if abs(probe["duration_seconds"] - expected) > 0.04:
            raise RuntimeError(f"duration mismatch for {scene_id}: {probe}")
        rows.append(
            {
                "scene_id": scene_id,
                "renderer": "deterministic_camera_motion_candidate_only",
                "anchor_path": str(anchor.resolve()),
                "anchor_sha256": unit["anchor_sha256"],
                "output_path": str(destination),
                "output_sha256": _sha256(destination),
                "probe": probe,
                "deformation_sensitive_insert": True,
                "human_review_required": True,
                "publish_allowed": False,
            }
        )
        print(json.dumps({"event": "stable_closeup_rendered", "scene_id": scene_id}), flush=True)

    audit = {
        "schema_version": "fanqie_v62_stable_closeup_progress/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "plan_path": str(plan_path),
        "plan_sha256": _sha256(plan_path),
        "shots": rows,
        "success": len(rows) == len(SCENE_IDS),
        "publish_allowed": False,
        "fanqie_backfill_allowed": False,
    }
    audit_path = output_dir / "stable_closeup_progress.json"
    audit_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(audit_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
