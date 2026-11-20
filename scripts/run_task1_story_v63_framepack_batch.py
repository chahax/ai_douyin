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

from gradio_client import Client, handle_file
from src.content_factory.video_smoothness import analyze_video_smoothness


DEFAULT_PLAN = ROOT / r"data\fanqie_promotion\scene_plans\task1_story_v63_visual_retention_workflow_v1.json"
DEFAULT_OUTPUT = ROOT / r"data\qa\task1_story_v63_full_render_20260822_visual_retention_v1"
STYLE_PROOF_ROOT = ROOT / r"data\qa\task1_story_v63_reference_style_rebuild_20260822\framepack_style_proof_v1"
STYLE_PROOF = {
    "b01_boast": STYLE_PROOF_ROOT / "male_walk_framepack.mp4",
    "b02_grab_reaction": STYLE_PROOF_ROOT / "female_block_framepack.mp4",
}


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


def _probe_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def _video_candidates(value: object) -> list[Path]:
    candidates: list[Path] = []
    if isinstance(value, (str, Path)):
        path = Path(str(value))
        if path.suffix.lower() in {".mp4", ".mov", ".webm", ".mkv"}:
            candidates.append(path)
    elif isinstance(value, dict):
        for nested in value.values():
            candidates.extend(_video_candidates(nested))
    elif isinstance(value, (tuple, list)):
        for nested in value:
            candidates.extend(_video_candidates(nested))
    else:
        path = getattr(value, "path", None)
        if path:
            candidates.extend(_video_candidates(path))
    return candidates


def _normalize_video(source: Path, destination: Path, target_duration: float, *, reverse: bool = False) -> dict[str, object]:
    source_duration = _probe_duration(source)
    if source_duration <= 0:
        raise ValueError(f"invalid source duration: {source}")
    if reverse:
        vf = "reverse,setpts=PTS-STARTPTS,fps=30,format=yuv420p"
    else:
        ratio = target_duration / source_duration
        vf = f"setpts={ratio:.10f}*PTS,fps=30,format=yuv420p"
    pending = destination.with_suffix(".pending.mp4")
    _run(
        [
            "ffmpeg", "-y", "-i", str(source), "-t", f"{target_duration:.3f}", "-an",
            "-vf", vf, "-c:v", "libx264", "-preset", "medium", "-crf", "16",
            "-movflags", "+faststart", str(pending),
        ]
    )
    pending.replace(destination)
    output_duration = _probe_duration(destination)
    if abs(output_duration - target_duration) > 0.08:
        raise RuntimeError(f"normalized duration mismatch: {output_duration:.3f}s vs {target_duration:.3f}s")
    return {
        "source_duration_seconds": source_duration,
        "output_duration_seconds": output_duration,
        "playback_reversed": reverse,
        "tempo_ratio": round(target_duration / source_duration, 8) if not reverse else None,
    }


def _metrics(path: Path) -> dict[str, object]:
    return analyze_video_smoothness(
        path,
        analysis_fps=15.0,
        analysis_width=160,
        duplicate_threshold=0.12,
    )


def _assert_motion(metrics: dict[str, object], scene_id: str) -> None:
    if float(metrics["duplicate_ratio"]) > 0.12:
        raise ValueError(f"{scene_id} duplicate ratio failed: {metrics['duplicate_ratio']}")
    if float(metrics["mean_frame_distance"]) < 0.5:
        raise ValueError(f"{scene_id} motion distance failed: {metrics['mean_frame_distance']}")
    if float(metrics["smoothness_score"]) < 65.0:
        raise ValueError(f"{scene_id} smoothness failed: {metrics['smoothness_score']}")


def _initial_progress(plan_path: Path, plan: dict[str, object], output_root: Path) -> dict[str, object]:
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the resumable V6.3 FramePack action partition.")
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--base-url", default="http://127.0.0.1:7861")
    parser.add_argument("--scene", action="append", default=[])
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    plan_path = args.plan.resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("schema_version") != "fanqie_v63_visual_retention_workflow/v1":
        raise ValueError("unexpected V6.3 plan schema")
    branch = plan["variants"]["visual_retention_v1"]
    action_ids = set(branch["action_scene_ids"])
    requested = set(args.scene) if args.scene else action_ids
    if not requested <= action_ids:
        raise ValueError(f"unknown or non-action scenes: {sorted(requested - action_ids)}")

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
        progress = _initial_progress(plan_path, plan, output_root)

    units = {str(unit["scene_id"]): unit for unit in branch["new_framepack_units"]}
    rows = {str(row["scene_id"]): row for row in progress["shots"] if isinstance(row, dict)}
    client: Client | None = None
    for scene_id in branch["action_scene_ids"]:
        if scene_id not in requested:
            continue
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

        print(f"START {scene_id} ({float(unit['target_duration_seconds']):.1f}s)", flush=True)
        source: Path
        provenance: dict[str, object]
        style_proof_anchor_names = {
            "b01_boast": "b01_boast_original.png",
            "b02_grab_reaction": "b02_path_block_original.png",
        }
        if scene_id in STYLE_PROOF and anchor.name == style_proof_anchor_names[scene_id]:
            source = STYLE_PROOF[scene_id]
            if not source.is_file():
                raise FileNotFoundError(source)
            provenance = {
                "mode": "bound_framepack_style_proof_reuse",
                "source_path": str(source),
                "source_sha256": _sha256(source),
                **_normalize_video(
                    source,
                    destination,
                    float(unit["target_duration_seconds"]),
                    reverse=scene_id == "b02_grab_reaction",
                ),
            }
        else:
            if client is None:
                client = Client(args.base_url)
            job = client.submit(
                input_image=handle_file(str(anchor)),
                prompt=str(unit["prompt"]),
                n_prompt=str(unit["negative_prompt"]),
                seed=float(unit["seed"]),
                total_second_length=float(unit["target_duration_seconds"]),
                latent_window_size=9,
                steps=25,
                cfg=1.0,
                gs=10.0,
                rs=0.0,
                gpu_memory_preservation=6.0,
                use_teacache=True,
                api_name="/process",
            )
            result = job.result()
            candidates = _video_candidates(job.outputs()) + _video_candidates(result)
            usable = [path for path in candidates if path.is_file() and path.stat().st_size > 0]
            if not usable:
                raise RuntimeError(f"FramePack returned no video for {scene_id}: {[str(p) for p in candidates]}")
            source = usable[-1]
            provenance = {
                "mode": "fresh_local_framepack_i2v",
                "framepack_source_path": str(source),
                "framepack_source_sha256": _sha256(source),
                **_normalize_video(source, destination, float(unit["target_duration_seconds"])),
            }

        metrics = _metrics(destination)
        try:
            _assert_motion(metrics, scene_id)
            status = "rendered"
            error = None
        except Exception as exc:
            status = "failed_motion_gate"
            error = str(exc)
        rows[scene_id] = {
            "scene_id": scene_id,
            "status": status,
            "renderer": "local_framepack_i2v",
            "seed": unit["seed"],
            "target_duration_seconds": unit["target_duration_seconds"],
            "anchor_path": str(anchor),
            "anchor_sha256": unit["anchor_sha256"],
            "prompt": unit["prompt"],
            "negative_prompt": unit["negative_prompt"],
            "output_path": str(destination),
            "output_sha256": _sha256(destination),
            "motion_metrics": metrics,
            "provenance": provenance,
            "error": error,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        progress["shots"] = [rows[key] for key in sorted(rows)]
        progress["renderer_partition"]["local_framepack_i2v"] = sorted(
            key for key, row in rows.items() if row.get("renderer") == "local_framepack_i2v" and row.get("status") == "rendered"
        )
        progress["updated_at"] = datetime.now(timezone.utc).isoformat()
        progress["action_complete"] = set(progress["renderer_partition"]["local_framepack_i2v"]) == action_ids
        progress["success"] = bool(progress["action_complete"] and progress.get("stable_inserts_complete"))
        _write_json(progress_path, progress)
        print(f"DONE {scene_id}: {status} {metrics}", flush=True)
        if error:
            raise ValueError(error)

    progress["action_complete"] = set(progress["renderer_partition"]["local_framepack_i2v"]) == action_ids
    progress["success"] = bool(progress["action_complete"] and progress.get("stable_inserts_complete"))
    progress["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write_json(progress_path, progress)
    print(json.dumps({"progress": str(progress_path), "action_complete": progress["action_complete"]}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
