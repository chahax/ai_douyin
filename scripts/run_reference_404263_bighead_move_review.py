"""Render the 404263 style-locked consecutive-action review packet.

One uninterrupted Wan2.2 Animate Move take is generated, then divided into
three adjacent review shots without resetting the character or scene.  The take
uses the exact approved bighead-3D male character master.  The original 404263
video is used only to derive DWPose body motion; its audio, identity, face video,
and pixels are not copied into generated clips.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

from run_reference_404263_native_move_benchmark import graph


ROOT = Path(__file__).resolve().parents[1]
SOURCE_VIDEO = ROOT / "40426344181-1-192.mp4"
STYLE_ROOT = (
    ROOT
    / "data/qa/reference_404263_detailed_two_style_full_20260826/bighead3d"
)
CHARACTER_MASTER = (
    STYLE_ROOT / "character_masters_selected/keyframes/male_operator.png"
)
# For this audit, use the approved character master itself as the reference image.
# This prevents an independently generated scene anchor from changing his identity.
SCENE_ANCHOR = CHARACTER_MASTER
DEFAULT_OUTPUT = ROOT / "data/qa/reference_404263_bighead_move_review_20260827_v3"
DEFAULT_COMFY_ROOT = Path(r"D:\IT\AI_vido\ComfyUI")


NEGATIVE = (
    "photorealistic, live action, real human, realistic skin pores, documentary, "
    "controlled v4 visual style, child, toddler, mascot, plush toy, doll texture, "
    "identity drift, face replacement, hairstyle change, clothing change, extra person, "
    "duplicate person, female person, extra arm, extra hand, extra leg, giant hand, "
    "foreshortened hand, extra fingers, fused fingers, malformed hand, broken wrist, "
    "floating limb, body teleport, instant pose change, frozen body, background jump, "
    "bed deformation, camera shake, zoom, pan, scene cut inside shot, loop, flicker, "
    "exposure pumping, readable text, subtitle, logo, watermark"
)


SHOTS = (
    {
        "id": "take01_operator_read_confirm_grin",
        "source_start": 46.80,
        "source_end": 49.80,
        "length": 49,
        "crop": "crop=600:1080:60:0",
        "seed": 827921,
        "action": (
            "In one uninterrupted three-second take, the same seated adult man first "
            "leans slightly toward the desk to read the phone result; he then lifts his "
            "head a little as he confirms it; finally a restrained closed-mouth smile "
            "builds while he leans a fraction closer. His shoulders, neck and head move "
            "along one continuous natural path. His mouth stays closed, the smile stays "
            "subtle, and both hands remain low near the desk and out of emphasis."
        ),
    },
)


REVIEW_SEGMENTS = (
    {
        "id": "k01_operator_leans_in",
        "start_frame": 0,
        "frame_count": 16,
        "source_motion_range_seconds": [46.80, 47.80],
        "action": "leans toward the desk and reads the result",
    },
    {
        "id": "k02_operator_confirms_result",
        "start_frame": 16,
        "frame_count": 16,
        "source_motion_range_seconds": [47.80, 48.80],
        "action": "lifts his head slightly to confirm the result",
    },
    {
        "id": "k03_operator_closed_smile_builds",
        "start_frame": 32,
        "frame_count": 17,
        "source_motion_range_seconds": [48.80, 49.80],
        "action": "a restrained closed-mouth satisfied smile builds",
    },
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def request_json(url: str, payload: dict[str, object] | None = None) -> dict:
    body = None
    headers: dict[str, str] = {}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ComfyUI HTTP {exc.code}: {detail}") from exc


def wait_history(base_url: str, prompt_id: str, timeout_seconds: int) -> dict:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        history = request_json(f"{base_url}/history/{prompt_id}")
        if prompt_id in history:
            item = history[prompt_id]
            status = item.get("status", {})
            if status.get("status_str") == "error" or status.get("completed") is False:
                raise RuntimeError(
                    "ComfyUI execution failed: "
                    + json.dumps(status.get("messages", []), ensure_ascii=False)
                )
            return item
        time.sleep(3)
    raise TimeoutError(f"ComfyUI prompt timed out: {prompt_id}")


def run(command: list[str], *, timeout: int = 900) -> None:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.returncode:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n"
            + completed.stderr[-5000:]
        )


def prepare_driver(source: Path, shot: dict[str, object], destination: Path) -> None:
    duration = float(shot["source_end"]) - float(shot["source_start"])
    video_filter = (
        f"{shot['crop']},"
        "scale=320:576:force_original_aspect_ratio=decrease,"
        "pad=320:576:(ow-iw)/2:(oh-ih)/2:black,fps=16,setsar=1"
    )
    run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            f"{float(shot['source_start']):.3f}",
            "-t",
            f"{duration:.3f}",
            "-i",
            str(source),
            "-vf",
            video_filter,
            "-frames:v",
            str(int(shot["length"])),
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "16",
            str(destination),
        ]
    )


def output_images(history: dict, node_id: str, comfy_output: Path) -> list[Path]:
    paths: list[Path] = []
    for image in history.get("outputs", {}).get(node_id, {}).get("images", []):
        source = comfy_output / str(image.get("subfolder") or "") / str(image["filename"])
        if source.is_file():
            paths.append(source)
    return sorted(paths, key=lambda path: path.name)


def copy_sequence(sources: list[Path], destination: Path, prefix: str) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for index, source in enumerate(sources):
        shutil.copy2(source, destination / f"{prefix}_{index:04d}.png")


def encode_sequence(
    frames_dir: Path,
    pattern: str,
    destination: Path,
    *,
    even_dimensions: bool = False,
) -> None:
    dimension_filter = (
        ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2"]
        if even_dimensions
        else []
    )
    run(
        [
            "ffmpeg",
            "-y",
            "-framerate",
            "16",
            "-i",
            str(frames_dir / pattern),
            *dimension_filter,
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "18",
            "-movflags",
            "+faststart",
            str(destination),
        ]
    )


def encode_segment(
    frames_dir: Path,
    destination: Path,
    *,
    start_frame: int,
    frame_count: int,
) -> None:
    run(
        [
            "ffmpeg",
            "-y",
            "-framerate",
            "16",
            "-start_number",
            str(start_frame),
            "-i",
            str(frames_dir / "frame_%04d.png"),
            "-frames:v",
            str(frame_count),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "18",
            "-movflags",
            "+faststart",
            str(destination),
        ]
    )


def build_prompt(action: str) -> str:
    return (
        "Vertical 9:16 premium cinematic stylized 3D adult animation in the exact "
        "approved 404263 bighead-adult style, never photorealistic. The exact same "
        "approved adult Chinese male phone operator age 27 appears in a cold cyan scam "
        "workroom: long narrow angular mature face, pronounced brow ridge, slightly "
        "hollow cheeks, dyed blond top hair with dark sides and dark roots, black crew-"
        "neck T-shirt. Preserve his exact face, mature age, hair silhouette, clothing, "
        "stylized skin material, seated scale and cold-cyan workroom lighting from first "
        "frame to last. One man only. A desk edge may remain low in frame; no readable "
        "phone screen and no hand close-up. "
        + action
        + " Locked camera, natural adult weight, continuous pose-driven movement, "
        "restrained acting, no internal cut and no newly invented gesture."
    )


def compose_review(output_dir: Path, clips: list[Path]) -> tuple[Path, Path]:
    concat_file = output_dir / "review_concat.txt"
    concat_file.write_text(
        "".join(f"file '{path.as_posix()}'\n" for path in clips),
        encoding="utf-8",
    )
    raw = output_dir / "reference_404263_bighead_move_review_raw_16fps.mp4"
    run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c",
            "copy",
            str(raw),
        ]
    )
    preview = output_dir / "reference_404263_bighead_move_review_preview_720x1280.mp4"
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(raw),
            "-vf",
            "scale=720:1280:flags=lanczos,fps=30",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "18",
            "-movflags",
            "+faststart",
            str(preview),
        ]
    )
    return raw, preview


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8190")
    parser.add_argument("--comfy-root", type=Path, default=DEFAULT_COMFY_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--only", action="append", choices=[item["id"] for item in SHOTS])
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument(
        "--recover-existing-frames",
        action="store_true",
        help="encode a completed frame sequence after a post-render packaging failure",
    )
    parser.add_argument("--steps", type=int, default=6)
    parser.add_argument("--timeout", type=int, default=7200)
    args = parser.parse_args()

    output_dir = args.output_dir.resolve()
    comfy_root = args.comfy_root.resolve()
    comfy_input = comfy_root / "input"
    comfy_output = comfy_root / "output"
    selected = [item for item in SHOTS if not args.only or item["id"] in args.only]
    for path in (SOURCE_VIDEO, CHARACTER_MASTER, SCENE_ANCHOR):
        if not path.is_file():
            raise FileNotFoundError(path)
    if not comfy_input.is_dir() or not comfy_output.is_dir():
        raise FileNotFoundError("ComfyUI input/output directory is unavailable")
    output_dir.mkdir(parents=True, exist_ok=True)

    object_info = request_json(f"{args.base_url}/object_info")
    required = {
        "WanAnimateToVideo",
        "DWPreprocessor",
        "LoadVideo",
        "GetVideoComponents",
        "UNETLoader",
        "KSampler",
        "SaveImage",
    }
    missing = sorted(required - set(object_info))
    if missing:
        raise RuntimeError(f"ComfyUI is missing required nodes: {missing}")

    input_prefix = comfy_input / "reference_404263_bighead_move_review_20260827_v3"
    input_prefix.mkdir(parents=True, exist_ok=True)
    anchor_input = input_prefix / "approved_bighead_male_operator.png"
    shutil.copy2(SCENE_ANCHOR, anchor_input)
    copied_master = input_prefix / "approved_bighead_male_operator_master.png"
    shutil.copy2(CHARACTER_MASTER, copied_master)

    render_rows: list[dict[str, object]] = []
    clips: list[Path] = []
    for shot in selected:
        shot_id = str(shot["id"])
        shot_dir = output_dir / "shots" / shot_id
        driver_dir = output_dir / "drivers"
        driver_dir.mkdir(parents=True, exist_ok=True)
        driver = driver_dir / f"{shot_id}_dwpose_source_16fps.mp4"
        clip = shot_dir / f"{shot_id}_wan22_animate_move.mp4"
        report_path = shot_dir / "render.report.json"
        workflow_path = shot_dir / "workflow.api.json"
        generated_dir = shot_dir / "generated_frames"
        pose_dir = shot_dir / "dwpose_frames"
        recovered_generated = sorted(generated_dir.glob("frame_*.png"))
        recovered_poses = sorted(pose_dir.glob("pose_*.png"))
        if (
            args.recover_existing_frames
            and len(recovered_generated) == int(shot["length"])
            and driver.is_file()
            and workflow_path.is_file()
        ):
            encode_sequence(generated_dir, "frame_%04d.png", clip)
            pose_clip = shot_dir / f"{shot_id}_dwpose_preview.mp4"
            if recovered_poses:
                encode_sequence(
                    pose_dir,
                    "pose_%04d.png",
                    pose_clip,
                    even_dimensions=True,
                )
            row = {
                "id": shot_id,
                "status": "generated_pending_manual_review",
                "source_motion_range_seconds": [shot["source_start"], shot["source_end"]],
                "source_video_pixels_used_for_dwpose_only": True,
                "source_video_pixels_directly_included": False,
                "source_video_face_video_used": False,
                "source_video_audio_used": False,
                "approved_style": "cinematic_3d_bighead_adult",
                "approved_character_master": str(CHARACTER_MASTER),
                "approved_character_master_sha256": sha256(CHARACTER_MASTER),
                "shared_scene_anchor": str(SCENE_ANCHOR),
                "shared_scene_anchor_sha256": sha256(SCENE_ANCHOR),
                "renderer": "Wan2.2 Animate Move 14B + DWPose",
                "prompt_id": "recovered_completed_frames_after_postencode_failure",
                "seed": shot["seed"],
                "steps": args.steps,
                "width": 320,
                "height": 576,
                "fps": 16,
                "frame_count": len(recovered_generated),
                "driver": str(driver),
                "driver_sha256": sha256(driver),
                "workflow": str(workflow_path),
                "workflow_sha256": sha256(workflow_path),
                "video": str(clip),
                "video_sha256": sha256(clip),
                "dwpose_preview": str(pose_clip) if recovered_poses else None,
                "action_contract": shot["action"],
                "recovered_without_rerender": True,
            }
            report_path.write_text(
                json.dumps(row, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            clips.append(clip)
            render_rows.append(row)
            print(
                json.dumps({"event": "recovered", "shot": shot_id, "video": str(clip)}),
                flush=True,
            )
            continue
        if args.skip_existing and clip.is_file() and report_path.is_file():
            clips.append(clip)
            render_rows.append(json.loads(report_path.read_text(encoding="utf-8")))
            print(json.dumps({"event": "skipped", "shot": shot_id}), flush=True)
            continue
        shot_dir.mkdir(parents=True, exist_ok=True)
        prepare_driver(SOURCE_VIDEO, shot, driver)
        driver_input = input_prefix / f"{shot_id}_driver.mp4"
        shutil.copy2(driver, driver_input)

        workflow = graph(
            image_name=f"reference_404263_bighead_move_review_20260827_v3/{anchor_input.name}",
            driver_name=f"reference_404263_bighead_move_review_20260827_v3/{driver_input.name}",
            prefix=f"reference_404263_bighead_move_review_20260827_v3/{shot_id}/generated",
            seed=int(shot["seed"]),
            width=320,
            height=576,
            length=int(shot["length"]),
            steps=args.steps,
            positive=build_prompt(str(shot["action"])),
            negative=NEGATIVE,
            include_face_video=False,
        )
        # Use DWPose for whole-body continuity, but suppress face and hand points.
        # The source's foreground hands caused anatomy failures, while its late open-
        # mouth face points overrode the required restrained closed-mouth reaction.
        workflow["14"]["inputs"]["detect_hand"] = "disable"
        workflow["14"]["inputs"]["detect_face"] = "disable"
        workflow["21"] = {
            "class_type": "SaveImage",
            "inputs": {
                "images": ["14", 0],
                "filename_prefix": (
                    f"reference_404263_bighead_move_review_20260827_v3/{shot_id}/pose"
                ),
            },
        }
        workflow_path.write_text(
            json.dumps(workflow, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        response = request_json(
            f"{args.base_url}/prompt",
            {"prompt": workflow, "client_id": str(uuid.uuid4())},
        )
        prompt_id = str(response["prompt_id"])
        print(
            json.dumps({"event": "queued", "shot": shot_id, "prompt_id": prompt_id}),
            flush=True,
        )
        history = wait_history(args.base_url, prompt_id, args.timeout)
        generated = output_images(history, "20", comfy_output)
        poses = output_images(history, "21", comfy_output)
        if len(generated) != int(shot["length"]):
            raise RuntimeError(
                f"{shot_id}: expected {shot['length']} frames, got {len(generated)}"
            )
        copy_sequence(generated, generated_dir, "frame")
        copy_sequence(poses, pose_dir, "pose")
        encode_sequence(generated_dir, "frame_%04d.png", clip)
        pose_clip = shot_dir / f"{shot_id}_dwpose_preview.mp4"
        if poses:
            encode_sequence(
                pose_dir,
                "pose_%04d.png",
                pose_clip,
                even_dimensions=True,
            )
        row = {
            "id": shot_id,
            "status": "generated_pending_manual_review",
            "source_motion_range_seconds": [shot["source_start"], shot["source_end"]],
            "source_video_pixels_used_for_dwpose_only": True,
            "source_video_pixels_directly_included": False,
            "source_video_face_video_used": False,
            "source_video_audio_used": False,
            "approved_style": "cinematic_3d_bighead_adult",
            "approved_character_master": str(CHARACTER_MASTER),
            "approved_character_master_sha256": sha256(CHARACTER_MASTER),
            "shared_scene_anchor": str(SCENE_ANCHOR),
            "shared_scene_anchor_sha256": sha256(SCENE_ANCHOR),
            "renderer": "Wan2.2 Animate Move 14B + DWPose",
            "prompt_id": prompt_id,
            "seed": shot["seed"],
            "steps": args.steps,
            "width": 320,
            "height": 576,
            "fps": 16,
            "frame_count": len(generated),
            "driver": str(driver),
            "driver_sha256": sha256(driver),
            "workflow": str(workflow_path),
            "workflow_sha256": sha256(workflow_path),
            "video": str(clip),
            "video_sha256": sha256(clip),
            "dwpose_preview": str(pose_clip) if poses else None,
            "action_contract": shot["action"],
        }
        report_path.write_text(
            json.dumps(row, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        clips.append(clip)
        render_rows.append(row)
        print(json.dumps({"event": "generated", "shot": shot_id, "video": str(clip)}), flush=True)

    if len(render_rows) != 1:
        raise RuntimeError("The v3 review must contain exactly one uninterrupted take")
    continuous_take = clips[0]
    continuous_take_frames = continuous_take.parent / "generated_frames"
    segment_dir = output_dir / "review_shots"
    segment_dir.mkdir(parents=True, exist_ok=True)
    segment_clips: list[Path] = []
    segment_rows: list[dict[str, object]] = []
    for segment in REVIEW_SEGMENTS:
        segment_clip = segment_dir / f"{segment['id']}.mp4"
        encode_segment(
            continuous_take_frames,
            segment_clip,
            start_frame=int(segment["start_frame"]),
            frame_count=int(segment["frame_count"]),
        )
        segment_clips.append(segment_clip)
        segment_rows.append(
            {
                **segment,
                "status": "generated_pending_user_review",
                "derived_from_one_uninterrupted_take": True,
                "character_or_scene_reset_before_segment": False,
                "approved_character_master_sha256": sha256(CHARACTER_MASTER),
                "video": str(segment_clip),
                "video_sha256": sha256(segment_clip),
                "fps": 16,
            }
        )

    raw, preview = compose_review(output_dir, segment_clips)
    packet = {
        "schema": "reference_404263_bighead_move_review/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "generated_pending_user_review",
        "scope": "three_adjacent_segments_from_one_uninterrupted_phone_operator_take",
        "approved_style": "cinematic_3d_bighead_adult",
        "forbidden_style": "controlled_v4_photorealistic",
        "same_character_asset_required": True,
        "same_character_asset_verified_by_sha256": True,
        "one_uninterrupted_generation_take": True,
        "character_or_scene_reset_between_review_shots": False,
        "source_policy": {
            "old_69_shot_candidate_used_as_video": False,
            "old_69_shot_candidate_used_as_script_or_composition_reference_only": True,
            "reference_video_used_for_dwpose_motion_only": True,
            "reference_identity_or_face_video_used": False,
            "reference_audio_used": False,
        },
        "publish_allowed": False,
        "full_104_second_generation_allowed": False,
        "raw_review_video": str(raw),
        "raw_review_video_sha256": sha256(raw),
        "preview_video": str(preview),
        "preview_video_sha256": sha256(preview),
        "continuous_take": render_rows[0],
        "shots": segment_rows,
        "review_gate": [
            "same_bighead_3d_style_in_all_shots",
            "same_male_operator_identity_hair_and_clothes_in_all_shots",
            "pose_path_matches_adjacent_dwpose_windows",
            "no_pose_reset_or_body_teleport_inside_shot",
            "hands_stay_low_without_giant_hand_or_foreground_distortion",
            "seated_weight_and_neck_shoulder_motion_are_anatomically_coherent",
            "cold_cyan_workroom_and_lighting_do_not_rebuild_between_frames",
        ],
    }
    packet_path = output_dir / "review.packet.json"
    packet_path.write_text(
        json.dumps(packet, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "event": "complete",
                "raw": str(raw),
                "preview": str(preview),
                "packet": str(packet_path),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
