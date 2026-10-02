from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PARENT_PLAN = ROOT / r"data\fanqie_promotion\scene_plans\task1_story_v62_microshot_workflow_framepack_b01_reference_composition_v1.json"
PARENT_PROGRESS = ROOT / r"data\qa\task1_story_v62_reference_motion_rebuild_20260822\integrated_framepack_b01_v1\original_recomposed\progress.json"
REVISION_PLAN = ROOT / r"data\fanqie_promotion\scene_plans\task1_story_v62_microshot_workflow_framepack_b01_wrist_bridge_v2.json"
WORK_ROOT = ROOT / r"data\qa\task1_story_v62_reference_motion_rebuild_20260822\bridge_b01_b02_v1"
RIFE_REPORT = WORK_ROOT / r"rife_v1\render_report.json"
RIFE_BRIDGE = WORK_ROOT / r"rife_v1\wrist_grab_bridge_rife.mp4"
REJECTED_WAN_REPORT = WORK_ROOT / r"wan_first_last_v1\render_report.json"
ORIGINAL_B02 = ROOT / r"data\qa\task1_story_v62_microshot_20260821\ltx\original_recomposed\b02_grab_reaction.mp4"
OUTPUT_DIR = WORK_ROOT / r"integrated_wrist_bridge_v2\original_recomposed"
COMPOSITE_RENDERER = "local_composite_rife_bridge_and_ltx"


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
            "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
            "stream=width,height,r_frame_rate,nb_frames:format=duration", "-of", "json", str(path),
        ],
        capture_output=True, text=True, timeout=30,
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
    for required in (PARENT_PLAN, PARENT_PROGRESS, RIFE_REPORT, RIFE_BRIDGE, ORIGINAL_B02):
        if not required.is_file():
            raise FileNotFoundError(required)

    plan = load(PARENT_PLAN)
    if plan.get("schema_version") != "fanqie_v62_microshot_workflow/v2":
        raise ValueError("unexpected V6.2 plan schema")
    branch = plan["variants"]["original_recomposed"]
    unit = next(row for row in branch["new_framepack_units"] if row["scene_id"] == "b02_grab_reaction")
    unit["renderer"] = COMPOSITE_RENDERER
    unit["target_duration_seconds"] = 1.4
    unit["transition_bridge"] = {
        "method": "four original keyframes plus local RIFE optical-flow interpolation",
        "render_report_path": str(RIFE_REPORT.resolve()),
        "render_report_sha256": sha256(RIFE_REPORT),
        "bridge_video_path": str(RIFE_BRIDGE.resolve()),
        "bridge_video_sha256": sha256(RIFE_BRIDGE),
        "duration_seconds": 0.6,
        "followed_by_original_ltx_reaction_seconds": 0.8,
        "reference_video_pixels_used": False,
    }
    microshot_changes = {
        "m04": {"source_start_seconds": 0.0, "duration_seconds": 0.6, "crop": "full", "cut": "insert_on_contact"},
        "m05": {"source_start_seconds": 0.6, "duration_seconds": 0.8, "crop": "full", "cut": "cut_on_completed_grab"},
    }
    for shot in branch["microshots"]:
        change = microshot_changes.get(str(shot["shot_id"]))
        if change:
            shot.update(change)
    parent_plan_sha = sha256(PARENT_PLAN)
    plan["revision"] = {
        "schema_version": "fanqie_v62_wrist_bridge_revision/v2",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "parent_plan_path": str(PARENT_PLAN.resolve()),
        "parent_plan_sha256": parent_plan_sha,
        "changed_scene_ids": ["b02_grab_reaction"],
        "changed_microshot_ids": ["m04", "m05"],
        "transition_strategy": "close hand insert: approach, first contact, completed grab, then wide reaction",
        "total_duration_seconds_unchanged": True,
        "story_audio_subtitles_and_other_eighteen_units_unchanged": True,
        "publish_allowed": False,
        "fanqie_backfill_allowed": False,
    }
    write_atomic(REVISION_PLAN, plan)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    composite = OUTPUT_DIR / "b02_grab_reaction.mp4"
    pending = composite.with_suffix(".pending.mp4")
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(RIFE_BRIDGE), "-i", str(ORIGINAL_B02),
            "-filter_complex",
            (
                "[0:v]scale=704:1248:force_original_aspect_ratio=increase:flags=lanczos,"
                "crop=704:1248,setpts=0.9375*(PTS-STARTPTS),fps=50,"
                "tpad=stop_mode=clone:stop_duration=0.08,trim=duration=0.6,setpts=PTS-STARTPTS[bridge];"
                "[1:v]scale=704:1248:force_original_aspect_ratio=increase:flags=lanczos,"
                "crop=704:1248,fps=50,trim=start=0:duration=0.8,setpts=PTS-STARTPTS[reaction];"
                "[bridge][reaction]concat=n=2:v=1:a=0,trim=duration=1.4,format=yuv420p[v]"
            ),
            "-map", "[v]", "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "17",
            "-movflags", "+faststart", str(pending),
        ],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode:
        raise RuntimeError(result.stderr[-4000:])
    pending.replace(composite)
    composite_probe = probe(composite)
    if (
        composite_probe["width"], composite_probe["height"], composite_probe["fps"]
    ) != (704, 1248, "50/1") or abs(float(composite_probe["duration_seconds"]) - 1.4) > 0.04:
        raise ValueError(f"composite b02 has unexpected delivery shape: {composite_probe}")

    progress = load(PARENT_PROGRESS)
    rows = {str(row["scene_id"]): row for row in progress.get("shots", [])}
    if len(rows) != 19 or "b02_grab_reaction" not in rows:
        raise ValueError("parent progress is incomplete")
    old_b02 = rows["b02_grab_reaction"]
    rife_report = load(RIFE_REPORT)
    rows["b02_grab_reaction"] = {
        **old_b02,
        "output_path": str(composite.resolve()),
        "output_sha256": sha256(composite),
        "probe": {
            "width": composite_probe["width"], "height": composite_probe["height"],
            "fps": composite_probe["fps"], "duration_seconds": composite_probe["duration_seconds"],
        },
        "provider_metadata": {
            "renderer": COMPOSITE_RENDERER,
            "true_i2v": True,
            "composition": [
                {
                    "renderer": "local_rife_interpolation_bridge",
                    "duration_seconds": 0.6,
                    "source_path": str(RIFE_BRIDGE.resolve()),
                    "source_sha256": sha256(RIFE_BRIDGE),
                    "render_report_path": str(RIFE_REPORT.resolve()),
                    "render_report_sha256": sha256(RIFE_REPORT),
                    "keyframe_sha256s": [row["sha256"] for row in rife_report["keyframes"]],
                },
                {
                    "renderer": "local_comfyui_ltx_i2v",
                    "duration_seconds": 0.8,
                    "source_path": str(ORIGINAL_B02.resolve()),
                    "source_sha256": sha256(ORIGINAL_B02),
                    "parent_provider_metadata": old_b02.get("provider_metadata"),
                },
            ],
            "reference_video_pixels_used": False,
            "human_review_required": True,
            "publish_allowed": False,
        },
    }
    partition = progress.get("renderer_partition") or {}
    ltx_scenes = [scene for scene in partition.get("local_comfyui_ltx_i2v", []) if scene != "b02_grab_reaction"]
    order = [str(row["scene_id"]) for row in branch["new_framepack_units"]]
    revised_progress = {
        **progress,
        "plan_path": str(REVISION_PLAN.resolve()),
        "plan_sha256": sha256(REVISION_PLAN),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "renderer": "hybrid_v62_with_framepack_b01_and_rife_wrist_bridge_b02",
        "renderer_partition": {
            "local_framepack_i2v": list(partition.get("local_framepack_i2v", [])),
            "local_comfyui_ltx_i2v": ltx_scenes,
            COMPOSITE_RENDERER: ["b02_grab_reaction"],
            "deterministic_camera_motion_candidate_only": list(partition.get("deterministic_camera_motion_candidate_only", [])),
        },
        "revision": plan["revision"],
        "shots": [rows[scene_id] for scene_id in order],
        "success": True,
        "publish_allowed": False,
        "fanqie_backfill_allowed": False,
        "human_review_required": True,
    }
    progress_path = OUTPUT_DIR / "progress.json"
    write_atomic(progress_path, revised_progress)

    report = {
        "schema_version": "fanqie_v62_wrist_bridge_integration/v2",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "revision_plan_path": str(REVISION_PLAN.resolve()),
        "revision_plan_sha256": sha256(REVISION_PLAN),
        "progress_path": str(progress_path.resolve()),
        "progress_sha256": sha256(progress_path),
        "changed_scene_ids": ["b02_grab_reaction"],
        "unchanged_scene_count": 18,
        "composite_b02_path": str(composite.resolve()),
        "composite_b02_sha256": sha256(composite),
        "rife_bridge_sha256": sha256(RIFE_BRIDGE),
        "rejected_experiment": {
            "renderer": "local_comfyui_wan_first_last_bridge",
            "report_path": str(REJECTED_WAN_REPORT.resolve()),
            "report_sha256": sha256(REJECTED_WAN_REPORT) if REJECTED_WAN_REPORT.is_file() else None,
            "reason": "intermediate frames contained severe spatial rearrangement and texture breakup",
        },
        "publish_allowed": False,
        "fanqie_backfill_allowed": False,
        "human_review_required": True,
    }
    write_atomic(OUTPUT_DIR.parent / "integration_report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
