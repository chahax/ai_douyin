from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE_PLAN = ROOT / r"data\fanqie_promotion\scene_plans\task1_story_v62_microshot_workflow.json"
BASE_PROGRESS = ROOT / r"data\qa\task1_story_v62_microshot_20260821\ltx\original_recomposed\progress.json"
REVISION_PLAN = ROOT / r"data\fanqie_promotion\scene_plans\task1_story_v62_microshot_workflow_framepack_b01_reference_composition_v1.json"
WORK_ROOT = ROOT / r"data\qa\task1_story_v62_reference_motion_rebuild_20260822"
FRAMEPACK_REPORT = WORK_ROOT / r"framepack_b01_v1\render_report.json"
FRAMEPACK_SOURCE = WORK_ROOT / r"framepack_b01_v1\b01_boast_framepack_reference_composition.mp4"
ORIGINAL_START = WORK_ROOT / r"original_keyframes\b01_wan_start_original.png"
ORIGINAL_END = WORK_ROOT / r"original_keyframes\b01_wan_end_original.png"
REFERENCE_VIDEO = ROOT / "40426344181-1-192.mp4"
REFERENCE_START = WORK_ROOT / "reference_walk_start_0p10.png"
REFERENCE_END = WORK_ROOT / "reference_walk_end_1p10.png"
REJECTED_WAN_REPORT = WORK_ROOT / r"wan_first_last_v1\render_report.json"
OUTPUT_DIR = WORK_ROOT / r"integrated_framepack_b01_v1\original_recomposed"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def write_atomic(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + ".pending")
    pending.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pending.replace(path)


def probe(path: Path) -> dict[str, object]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,r_frame_rate,nb_frames:format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode:
        raise RuntimeError(result.stderr[-2000:])
    payload = json.loads(result.stdout)
    stream = payload["streams"][0]
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "fps": str(stream["r_frame_rate"]),
        "frames": int(stream.get("nb_frames") or 0),
        "duration_seconds": round(float(payload["format"]["duration"]), 3),
    }


def main() -> int:
    required = (
        BASE_PLAN,
        BASE_PROGRESS,
        FRAMEPACK_REPORT,
        FRAMEPACK_SOURCE,
        ORIGINAL_START,
        ORIGINAL_END,
        REFERENCE_VIDEO,
        REFERENCE_START,
        REFERENCE_END,
    )
    for path in required:
        if not path.is_file():
            raise FileNotFoundError(path)

    base_plan = load(BASE_PLAN)
    if base_plan.get("schema_version") != "fanqie_v62_microshot_workflow/v2":
        raise ValueError("unexpected base V6.2 plan schema")
    base_plan_sha = sha256(BASE_PLAN)
    branch = base_plan["variants"]["original_recomposed"]
    unit = next(row for row in branch["new_framepack_units"] if row["scene_id"] == "b01_boast")
    unit.update(
        {
            "anchor_path": str(ORIGINAL_START.resolve()),
            "anchor_sha256": sha256(ORIGINAL_START),
            "target_duration_seconds": 2.8,
            "seed": 6220823,
            "renderer": "local_framepack_i2v",
            "prompt": load(FRAMEPACK_REPORT)["prompt"],
            "negative_prompt": load(FRAMEPACK_REPORT)["negative_prompt"],
            "motion_reference_contract": {
                "reference_video_path": str(REFERENCE_VIDEO.resolve()),
                "reference_video_sha256": sha256(REFERENCE_VIDEO),
                "reference_frames_internal_only": [
                    {"path": str(REFERENCE_START.resolve()), "sha256": sha256(REFERENCE_START)},
                    {"path": str(REFERENCE_END.resolve()), "sha256": sha256(REFERENCE_END)},
                ],
                "reference_material_used_for_publication": False,
                "original_generated_start_frame": {
                    "path": str(ORIGINAL_START.resolve()),
                    "sha256": sha256(ORIGINAL_START),
                },
                "original_generated_end_frame": {
                    "path": str(ORIGINAL_END.resolve()),
                    "sha256": sha256(ORIGINAL_END),
                },
                "method": "reference composition and edit rhythm; original generated publication frame",
            },
        }
    )
    opening_microshots = {
        "m01": (0.0, 0.8, "full"),
        "m02": (0.8, 1.0, "lower_detail"),
        "m03": (1.8, 1.0, "upper_close"),
    }
    for shot in branch["microshots"]:
        values = opening_microshots.get(str(shot["shot_id"]))
        if values is None:
            continue
        start, duration, crop = values
        shot["source_start_seconds"] = start
        shot["duration_seconds"] = duration
        shot["crop"] = crop
    base_plan["revision"] = {
        "schema_version": "fanqie_v62_reference_composition_revision/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "parent_plan_path": str(BASE_PLAN.resolve()),
        "parent_plan_sha256": base_plan_sha,
        "changed_scene_ids": ["b01_boast"],
        "changed_microshot_ids": ["m01", "m02", "m03"],
        "transition_strategy": "existing b02 lower-detail action insert hides the location cut",
        "story_audio_subtitles_and_other_eighteen_units_unchanged": True,
        "publish_allowed": False,
        "fanqie_backfill_allowed": False,
    }
    write_atomic(REVISION_PLAN, base_plan)

    source_probe = probe(FRAMEPACK_SOURCE)
    if source_probe["duration_seconds"] < 2.3:
        raise ValueError(f"FramePack b01 is unexpectedly short: {source_probe}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    aligned = OUTPUT_DIR / "b01_boast.mp4"
    stretch = 2.8 / float(source_probe["duration_seconds"])
    pending = aligned.with_suffix(".pending.mp4")
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(FRAMEPACK_SOURCE),
            "-an",
            "-vf",
            (
                "scale=704:1248:force_original_aspect_ratio=increase:flags=lanczos,"
                f"crop=704:1248,setpts={stretch:.9f}*(PTS-STARTPTS),fps=50,"
                "tpad=stop_mode=clone:stop_duration=0.08,trim=duration=2.8,format=yuv420p"
            ),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "17",
            "-movflags",
            "+faststart",
            str(pending),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode:
        raise RuntimeError(result.stderr[-4000:])
    pending.replace(aligned)
    aligned_probe = probe(aligned)
    if (
        aligned_probe["width"],
        aligned_probe["height"],
        aligned_probe["fps"],
    ) != (704, 1248, "50/1") or abs(float(aligned_probe["duration_seconds"]) - 2.8) > 0.04:
        raise ValueError(f"aligned FramePack b01 has unexpected delivery shape: {aligned_probe}")

    base_progress = load(BASE_PROGRESS)
    base_rows = {str(row["scene_id"]): row for row in base_progress.get("shots", [])}
    if len(base_rows) != 19 or "b01_boast" not in base_rows:
        raise ValueError("base progress is incomplete")
    framepack_report = load(FRAMEPACK_REPORT)
    replacement = {
        **base_rows["b01_boast"],
        "status": "rendered",
        "output_path": str(aligned.resolve()),
        "output_sha256": sha256(aligned),
        "probe": {
            "width": aligned_probe["width"],
            "height": aligned_probe["height"],
            "fps": aligned_probe["fps"],
            "duration_seconds": aligned_probe["duration_seconds"],
        },
        "anchor_path": str(ORIGINAL_START.resolve()),
        "anchor_sha256": sha256(ORIGINAL_START),
        "provider_metadata": {
            "renderer": "local_framepack_i2v",
            "true_i2v": True,
            "source_render_report_path": str(FRAMEPACK_REPORT.resolve()),
            "source_render_report_sha256": sha256(FRAMEPACK_REPORT),
            "source_video_path": str(FRAMEPACK_SOURCE.resolve()),
            "source_video_sha256": sha256(FRAMEPACK_SOURCE),
            "source_probe": source_probe,
            "delivery_alignment": {
                "setpts_multiplier": round(stretch, 9),
                "output_probe": aligned_probe,
            },
            "reference_video_sha256": sha256(REFERENCE_VIDEO),
            "reference_frames_internal_only": True,
            "reference_material_used_for_publication": False,
            "original_generated_start_frame_sha256": sha256(ORIGINAL_START),
            "human_review_required": True,
            "publish_allowed": False,
        },
    }
    base_rows["b01_boast"] = replacement
    order = [str(row["scene_id"]) for row in branch["new_framepack_units"]]
    base_partition = base_progress.get("renderer_partition") or {}
    ltx_scenes = [scene for scene in base_partition.get("local_comfyui_ltx_i2v", []) if scene != "b01_boast"]
    stable_scenes = list(base_partition.get("deterministic_camera_motion_candidate_only", []))
    progress = {
        **base_progress,
        "plan_path": str(REVISION_PLAN.resolve()),
        "plan_sha256": sha256(REVISION_PLAN),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "renderer": "hybrid_v62_with_framepack_reference_composition_b01",
        "renderer_partition": {
            "local_framepack_i2v": ["b01_boast"],
            "local_comfyui_ltx_i2v": ltx_scenes,
            "deterministic_camera_motion_candidate_only": stable_scenes,
        },
        "revision": base_plan["revision"],
        "shots": [base_rows[scene_id] for scene_id in order],
        "success": True,
        "publish_allowed": False,
        "fanqie_backfill_allowed": False,
        "human_review_required": True,
    }
    progress_path = OUTPUT_DIR / "progress.json"
    write_atomic(progress_path, progress)

    report = {
        "schema_version": "fanqie_v62_reference_framepack_integration/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "revision_plan_path": str(REVISION_PLAN.resolve()),
        "revision_plan_sha256": sha256(REVISION_PLAN),
        "progress_path": str(progress_path.resolve()),
        "progress_sha256": sha256(progress_path),
        "changed_scene_ids": ["b01_boast"],
        "unchanged_scene_count": 18,
        "framepack_source_sha256": framepack_report["video"]["sha256"],
        "aligned_b01_sha256": sha256(aligned),
        "rejected_experiments": [
            {
                "renderer": "local_comfyui_wan_first_last",
                "report_path": str(REJECTED_WAN_REPORT.resolve()),
                "report_sha256": sha256(REJECTED_WAN_REPORT) if REJECTED_WAN_REPORT.is_file() else None,
                "reason": "identity, background and phone continuity failed visual review",
            }
        ],
        "publish_allowed": False,
        "fanqie_backfill_allowed": False,
        "human_review_required": True,
    }
    report_path = OUTPUT_DIR.parent / "integration_report.json"
    write_atomic(report_path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
