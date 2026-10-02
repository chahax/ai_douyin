"""Render the script-aligned 404263 ending-performance review (064b-064f).

The four character-action shots use Wan2.2 Animate Move + DWPose.  The first
shot starts from the approved victim_chen master; every later shot starts from
the preceding generated shot's final frame.  Shot 064c is a deterministic
phone insert assembled after 064b passes visual review.
"""

from __future__ import annotations

import argparse
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from run_reference_404263_bighead_move_review import (
    copy_sequence,
    encode_sequence,
    graph,
    output_images,
    prepare_driver,
    request_json,
    sha256,
    wait_history,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE_VIDEO = ROOT / "40426344181-1-192.mp4"
CHARACTER_MASTER = (
    ROOT
    / "data/qa/reference_404263_detailed_two_style_full_20260826/bighead3d"
    / "character_masters_selected/keyframes/victim_chen.png"
)
DEFAULT_OUTPUT = (
    ROOT / "data/qa/reference_404263_bighead_move_review_20260827_v5_script_064"
)
DEFAULT_COMFY_ROOT = Path(r"D:\IT\AI_vido\ComfyUI")
INPUT_NAMESPACE = "reference_404263_bighead_move_review_20260827_v4_script_064"


NEGATIVE = (
    "photorealistic, live action, real actor, realistic skin pores, controlled v4 "
    "visual style, child, young man, glasses, black hair, blond hair, identity drift, "
    "face replacement, hairstyle change, clothing change, extra person, duplicate "
    "person, extra arm, extra hand, giant hand, foreshortened hand, extra fingers, "
    "fused fingers, malformed hand, broken wrist, floating limb, phone fused to hand, "
    "phone changing shape, duplicate phone, readable text, subtitle, logo, watermark, "
    "camera push in, zoom, pan, scene rebuild, background jump, body teleport, frozen "
    "body, exaggerated grin, cheerful smile, comedy, crying scream, open mouth"
)


SHOTS = (
    {
        "id": "064b_chen_confused",
        "script_time": [91.10, 93.13],
        "source_start": 93.50,
        "source_end": 94.25,
        "length": 33,
        "crop": "crop=600:1080:60:100,setpts=2.666667*PTS",
        "seed": 827961,
        "detect_hand": "disable",
        "action": (
            "Chen sits in the same armchair and watches offscreen television news. "
            "His breathing pauses, his brows draw together, and his gaze shifts slowly "
            "from the television toward the cracked black smartphone lying on the glass "
            "coffee table at lower right. Keep the phone visible and stationary."
        ),
        "contract": (
            "陈叔听到新闻后呼吸停顿，眉头收紧，视线从电视缓慢移向玻璃茶几右下方的裂屏手机。"
        ),
    },
    {
        "id": "064d_chen_reaches_phone",
        "script_time": [94.40, 97.33],
        "source_start": 12.25,
        "source_end": 13.50,
        "length": 21,
        "crop": "crop=600:1080:60:100",
        "seed": 827962,
        "detect_hand": "enable",
        "action": (
            "Continuing from the exact previous final frame, Chen leans forward a little. "
            "His right shoulder, elbow and hand move together as he reaches down toward "
            "the same cracked black smartphone, closes his fingers around it once, and "
            "lifts it just clear of the glass tabletop."
        ),
        "contract": (
            "承接上一镜末帧，陈叔身体前倾，右肩、肘和手沿同一路径伸向手机，握住一次并刚好拿离桌面。"
        ),
    },
    {
        "id": "064e_chen_phone_to_ear",
        "script_time": [97.33, 99.50],
        "source_start": 99.50,
        "source_end": 100.75,
        "length": 21,
        "crop": "crop=600:1080:60:100",
        "seed": 827953,
        "detect_hand": "enable",
        "action": (
            "Continuing from the exact previous final frame, Chen raises the same phone "
            "from chest height to his right ear. His elbow bends smoothly, the wrist "
            "stays aligned, and the phone touches the ear only once. His worried gaze "
            "stays forward; he does not smile."
        ),
        "contract": (
            "承接上一镜末帧，陈叔将同一手机从胸前平滑举到右耳，手腕不折、手机不变形，只贴耳一次。"
        ),
    },
    {
        "id": "064f_chen_waits_shoulders_sink",
        "script_time": [99.50, 104.30],
        "source_start": 100.75,
        "source_end": 104.25,
        "length": 57,
        "crop": "crop=600:1080:60:100",
        "seed": 827954,
        "detect_hand": "enable",
        "action": (
            "Continuing from the exact previous final frame, Chen holds the same phone "
            "steadily to his right ear and listens. After a still beat, his torso leans "
            "forward slightly, his gaze lowers, and both shoulders sink slowly with one "
            "quiet exhale. He remains restrained and worried, never smiling."
        ),
        "contract": (
            "承接上一镜末帧，陈叔贴耳等待；停顿后身体微前倾、视线下落、双肩随一次呼气缓慢塌下。"
        ),
    },
)


def positive_prompt(action: str) -> str:
    return (
        "Vertical 9:16 premium cinematic stylized 3D adult animation in the exact "
        "approved 404263 bighead-adult style, never photorealistic. The exact same "
        "approved Chinese retired worker Chen, age 66: broad square mature face, short "
        "silver-grey hair with the same swept forelock, thick grey brows, deep forehead "
        "lines, large warm brown stylized eyes, no glasses, brown knitted cardigan over "
        "a beige ribbed turtleneck. He sits alone in the same modest low-light living "
        "room at night, with a cool blue window rim light, a warm dim practical lamp, "
        "the same armchair and the same glass coffee table. A single simple black "
        "smartphone has a cracked dark screen and no readable text. Preserve Chen's "
        "face, age, hair silhouette, cardigan, room layout, chair, table, phone shape, "
        "lighting and camera axis from first frame to last. "
        + action
        + " Natural elderly weight and inertia, restrained tragic acting, one clear "
        "action path, locked camera, no internal cut, no invented gesture."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8190")
    parser.add_argument("--comfy-root", type=Path, default=DEFAULT_COMFY_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--through",
        choices=[shot["id"] for shot in SHOTS],
        default=SHOTS[-1]["id"],
    )
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument(
        "--force-shot",
        action="append",
        choices=[shot["id"] for shot in SHOTS],
        help="rerender only the named shot while other completed shots are skipped",
    )
    parser.add_argument("--steps", type=int, default=6)
    parser.add_argument("--timeout", type=int, default=7200)
    args = parser.parse_args()

    output_dir = args.output_dir.resolve()
    comfy_root = args.comfy_root.resolve()
    comfy_input = comfy_root / "input"
    comfy_output = comfy_root / "output"
    input_dir = comfy_input / INPUT_NAMESPACE
    for path in (SOURCE_VIDEO, CHARACTER_MASTER):
        if not path.is_file():
            raise FileNotFoundError(path)
    if not comfy_input.is_dir() or not comfy_output.is_dir():
        raise FileNotFoundError("ComfyUI input/output directory is unavailable")
    output_dir.mkdir(parents=True, exist_ok=True)
    input_dir.mkdir(parents=True, exist_ok=True)

    object_info = request_json(f"{args.base_url}/object_info")
    required = {"WanAnimateToVideo", "DWPreprocessor", "LoadVideo", "SaveImage"}
    missing = sorted(required - set(object_info))
    if missing:
        raise RuntimeError(f"ComfyUI is missing required nodes: {missing}")

    selected: list[dict[str, object]] = []
    for shot in SHOTS:
        selected.append(shot)
        if shot["id"] == args.through:
            break

    rows: list[dict[str, object]] = []
    reference_source = CHARACTER_MASTER
    reference_origin = "approved_character_master"
    for shot in selected:
        shot_id = str(shot["id"])
        shot_dir = output_dir / "shots" / shot_id
        shot_dir.mkdir(parents=True, exist_ok=True)
        driver_dir = output_dir / "drivers"
        driver_dir.mkdir(parents=True, exist_ok=True)
        driver = driver_dir / f"{shot_id}_dwpose_source_16fps.mp4"
        clip = shot_dir / f"{shot_id}_wan22_animate_move.mp4"
        workflow_path = shot_dir / "workflow.api.json"
        report_path = shot_dir / "render.report.json"
        generated_dir = shot_dir / "generated_frames"
        last_frame = generated_dir / f"frame_{int(shot['length']) - 1:04d}.png"
        approved_cleaned_frame = (
            shot_dir / "cleaned_frames" / f"frame_{int(shot['length']) - 1:04d}.png"
        )
        approved_clip = shot_dir / f"{shot_id}_approved.mp4"

        forced = bool(args.force_shot and shot_id in args.force_shot)
        if (
            args.skip_existing
            and not forced
            and clip.is_file()
            and report_path.is_file()
            and last_frame.is_file()
        ):
            row = json.loads(report_path.read_text(encoding="utf-8"))
            if approved_cleaned_frame.is_file() and approved_clip.is_file():
                row["status"] = "internal_visual_qa_passed"
                row["approved_video"] = str(approved_clip)
                row["approved_video_sha256"] = sha256(approved_clip)
                row["approved_final_frame"] = str(approved_cleaned_frame)
                row["approved_final_frame_sha256"] = sha256(approved_cleaned_frame)
                row["deterministic_phone_cleanup_used"] = True
                report_path.write_text(
                    json.dumps(row, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
            rows.append(row)
            reference_source = (
                approved_cleaned_frame
                if approved_cleaned_frame.is_file()
                else last_frame
            )
            reference_origin = (
                f"previous_shot_approved_final_frame:{shot_id}"
                if approved_cleaned_frame.is_file()
                else f"previous_shot_final_frame:{shot_id}"
            )
            print(json.dumps({"event": "skipped", "shot": shot_id}), flush=True)
            continue

        prepare_driver(SOURCE_VIDEO, shot, driver)
        transition_reference = (
            output_dir / "transition_refs/064d_reference_from_064b_clean_table.png"
        )
        if shot_id == "064d_chen_reaches_phone" and transition_reference.is_file():
            reference_source = transition_reference
            reference_origin = (
                "previous_shot_final_frame_with_deterministic_table_cleanup:064b_chen_confused"
            )
        reference_input = input_dir / f"{shot_id}_reference.png"
        driver_input = input_dir / f"{shot_id}_driver.mp4"
        shutil.copy2(reference_source, reference_input)
        shutil.copy2(driver, driver_input)

        workflow = graph(
            image_name=f"{INPUT_NAMESPACE}/{reference_input.name}",
            driver_name=f"{INPUT_NAMESPACE}/{driver_input.name}",
            prefix=f"{INPUT_NAMESPACE}/{shot_id}/generated",
            seed=int(shot["seed"]),
            width=320,
            height=576,
            length=int(shot["length"]),
            steps=args.steps,
            positive=positive_prompt(str(shot["action"])),
            negative=NEGATIVE,
            include_face_video=False,
        )
        workflow["14"]["inputs"]["detect_hand"] = str(shot["detect_hand"])
        workflow["14"]["inputs"]["detect_face"] = "disable"
        workflow["21"] = {
            "class_type": "SaveImage",
            "inputs": {
                "images": ["14", 0],
                "filename_prefix": f"{INPUT_NAMESPACE}/{shot_id}/pose",
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
        pose_dir = shot_dir / "dwpose_frames"
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
            "script_unit": shot_id.split("_")[0],
            "script_time_seconds": shot["script_time"],
            "action_contract_zh": shot["contract"],
            "source_motion_range_seconds": [shot["source_start"], shot["source_end"]],
            "renderer": "Wan2.2 Animate Move 14B + DWPose",
            "approved_style": "cinematic_3d_bighead_adult",
            "forbidden_style": "controlled_v4_photorealistic",
            "approved_character_master": str(CHARACTER_MASTER),
            "approved_character_master_sha256": sha256(CHARACTER_MASTER),
            "reference_origin": reference_origin,
            "reference_image": str(reference_source),
            "reference_image_sha256": sha256(reference_source),
            "previous_final_frame_chained": reference_origin.startswith("previous_shot"),
            "deterministic_transition_cleanup_used": "deterministic_table_cleanup" in reference_origin,
            "source_video_used_for_dwpose_only": True,
            "source_video_pixels_directly_included": False,
            "source_face_video_used": False,
            "source_audio_used": False,
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
            "final_frame": str(last_frame),
            "final_frame_sha256": sha256(last_frame),
            "dwpose_preview": str(pose_clip) if poses else None,
        }
        report_path.write_text(
            json.dumps(row, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        rows.append(row)
        reference_source = last_frame
        reference_origin = f"previous_shot_final_frame:{shot_id}"
        print(json.dumps({"event": "generated", "shot": shot_id, "video": str(clip)}), flush=True)

    packet = {
        "schema": "reference_404263_script_aligned_064_review/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "partial_generated_pending_manual_review",
        "scope": "script_units_064b_through_064f",
        "approved_style": "cinematic_3d_bighead_adult",
        "forbidden_style": "controlled_v4_photorealistic",
        "approved_character_master": str(CHARACTER_MASTER),
        "approved_character_master_sha256": sha256(CHARACTER_MASTER),
        "old_69_used_as_video_or_first_frame": False,
        "old_69_used_for_script_and_composition_reference_only": True,
        "full_104_second_generation_allowed": False,
        "publish_allowed": False,
        "shots": rows,
        "pending_deterministic_insert": "064c_cracked_phone_insert",
    }
    packet_path = output_dir / "review.packet.json"
    packet_path.write_text(
        json.dumps(packet, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps({"event": "partial_complete", "packet": str(packet_path)}),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
