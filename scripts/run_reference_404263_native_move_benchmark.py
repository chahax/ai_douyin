"""Run an internal Wan2.2 Animate Move benchmark for the 404263 reference.

This runner intentionally permits reference pixels only as internal motion and
composition evidence.  Every output is marked non-publishable.  It uses the
native ComfyUI ``WanAnimateToVideo`` node so the benchmark does not depend on
the currently broken Kijai wrapper registration in the production runtime.
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


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REFERENCE_FRAME = (
    ROOT
    / r"data\qa\reference_404263_performance_benchmarks_20260825"
    / r"b2_fake_illness\internal_reference\frame_52_000.png"
)
DEFAULT_DRIVER = (
    ROOT
    / r"data\qa\reference_404263_performance_benchmarks_20260825"
    / r"b2_fake_illness\internal_reference\driver_52_000_54_300_16fps.mp4"
)
DEFAULT_OUTPUT = (
    ROOT
    / r"data\qa\reference_404263_performance_benchmarks_20260825"
    / r"b2_fake_illness\native_wan22_animate_move"
)
DEFAULT_COMFY_ROOT = Path(r"D:\IT\AI_vido\ComfyUI")


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


def graph(
    *,
    image_name: str,
    driver_name: str,
    prefix: str,
    seed: int,
    width: int,
    height: int,
    length: int,
    steps: int,
    positive: str | None = None,
    negative: str | None = None,
    include_face_video: bool = True,
) -> dict[str, object]:
    if positive is None:
        positive = (
            "Photorealistic vertical Chinese crime microdrama. The same young adult woman "
            "lies naturally on her side on a messy bed, hears an off-camera direction, "
            "touches her forehead and performs restrained weakness for a phone camera, then "
            "opens her eyes and checks the phone. Preserve the exact room geometry, bed, body "
            "proportions and prop positions. Natural breathing, coherent weight, stable face, "
            "stable hands, stable phone plane, locked camera, continuous realistic movement."
        )
    if negative is None:
        negative = (
            "identity drift, face replacement, instant expression flip, phone disappearance, "
            "phone screen missing, extra phone, extra arms, extra fingers, fused hand and phone, "
            "malformed fingers, floating prop, half squat, crouch, frozen legs, body teleport, "
            "bed deformation, background jump, camera shake, zoom, scene cut, flicker, morphing, "
            "readable text, subtitle, logo, watermark, cartoon, anime, presenter"
        )
    animate_inputs: dict[str, object] = {
        "positive": ["5", 0],
        "negative": ["6", 0],
        "vae": ["7", 0],
        "width": width,
        "height": height,
        "length": length,
        "batch_size": 1,
        "continue_motion_max_frames": 5,
        "video_frame_offset": 0,
        "clip_vision_output": ["10", 0],
        "reference_image": ["9", 0],
        "pose_video": ["14", 0],
    }
    if include_face_video:
        animate_inputs["face_video"] = ["13", 0]
    return {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": "Wan2_2-Animate-14B_fp8_e4m3fn_scaled_KJ.safetensors",
                "weight_dtype": "default",
            },
        },
        "2": {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {
                "model": ["1", 0],
                "lora_name": "lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors",
                "strength_model": 1.0,
            },
        },
        "3": {
            "class_type": "ModelSamplingSD3",
            "inputs": {"model": ["2", 0], "shift": 8.0},
        },
        "4": {
            "class_type": "CLIPLoader",
            "inputs": {
                "clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
                "type": "wan",
                "device": "default",
            },
        },
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 0], "text": positive}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 0], "text": negative}},
        "7": {"class_type": "VAELoader", "inputs": {"vae_name": "wan_2.1_vae.safetensors"}},
        "8": {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": "clip_vision_h.safetensors"}},
        "9": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "10": {
            "class_type": "CLIPVisionEncode",
            "inputs": {"clip_vision": ["8", 0], "image": ["9", 0], "crop": "none"},
        },
        "11": {"class_type": "LoadVideo", "inputs": {"file": driver_name}},
        "12": {"class_type": "GetVideoComponents", "inputs": {"video": ["11", 0]}},
        "13": {
            "class_type": "ImageScale",
            "inputs": {
                "image": ["12", 0],
                "upscale_method": "lanczos",
                "width": width,
                "height": height,
                "crop": "disabled",
            },
        },
        "14": {
            "class_type": "DWPreprocessor",
            "inputs": {
                "image": ["13", 0],
                "detect_hand": "enable",
                "detect_body": "enable",
                "detect_face": "enable",
                "resolution": max(width, height),
                "bbox_detector": "yolox_l.onnx",
                "pose_estimator": "dw-ll_ucoco_384_bs5.torchscript.pt",
                "scale_stick_for_xinsr_cn": "disable",
            },
        },
        "15": {
            "class_type": "WanAnimateToVideo",
            "inputs": animate_inputs,
        },
        "16": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["3", 0],
                "seed": seed,
                "steps": steps,
                "cfg": 1.0,
                "sampler_name": "euler",
                "scheduler": "simple",
                "positive": ["15", 0],
                "negative": ["15", 1],
                "latent_image": ["15", 2],
                "denoise": 1.0,
            },
        },
        "17": {
            "class_type": "TrimVideoLatent",
            "inputs": {"samples": ["16", 0], "trim_amount": ["15", 3]},
        },
        "18": {"class_type": "VAEDecode", "inputs": {"samples": ["17", 0], "vae": ["7", 0]}},
        "19": {
            "class_type": "ImageFromBatch",
            "inputs": {"image": ["18", 0], "batch_index": ["15", 4], "length": 4096},
        },
        "20": {
            "class_type": "SaveImage",
            "inputs": {"images": ["19", 0], "filename_prefix": prefix},
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8190")
    parser.add_argument("--comfy-root", type=Path, default=DEFAULT_COMFY_ROOT)
    parser.add_argument("--reference-frame", type=Path, default=DEFAULT_REFERENCE_FRAME)
    parser.add_argument("--driver", type=Path, default=DEFAULT_DRIVER)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=825520)
    parser.add_argument("--width", type=int, default=320)
    parser.add_argument("--height", type=int, default=576)
    parser.add_argument("--length", type=int, default=37)
    parser.add_argument("--steps", type=int, default=6)
    parser.add_argument("--timeout", type=int, default=7200)
    args = parser.parse_args()

    reference_frame = args.reference_frame.resolve()
    driver = args.driver.resolve()
    output_dir = args.output_dir.resolve()
    comfy_root = args.comfy_root.resolve()
    comfy_input = comfy_root / "input"
    comfy_output = comfy_root / "output"
    for path in (reference_frame, driver):
        if not path.is_file():
            raise FileNotFoundError(path)
    if args.length < 17 or (args.length - 1) % 4 != 0:
        raise ValueError("Wan frame length must be 4n+1 and at least 17")
    if args.width % 16 or args.height % 16:
        raise ValueError("width and height must be multiples of 16")
    if not comfy_input.is_dir() or not comfy_output.is_dir():
        raise FileNotFoundError("ComfyUI input/output directory is unavailable")
    output_dir.mkdir(parents=True, exist_ok=True)

    object_info = request_json(f"{args.base_url}/object_info")
    required_nodes = {
        "WanAnimateToVideo",
        "DWPreprocessor",
        "LoadVideo",
        "GetVideoComponents",
        "UNETLoader",
        "KSampler",
        "SaveImage",
    }
    missing_nodes = sorted(required_nodes - set(object_info))
    if missing_nodes:
        raise RuntimeError(f"ComfyUI is missing required nodes: {missing_nodes}")

    token = uuid.uuid4().hex[:8]
    image_name = f"reference_404263_b2_frame_{token}.png"
    driver_name = f"reference_404263_b2_driver_{token}.mp4"
    shutil.copy2(reference_frame, comfy_input / image_name)
    shutil.copy2(driver, comfy_input / driver_name)

    prefix = f"reference_404263_performance_bench/b2_native_move_{token}"
    workflow = graph(
        image_name=image_name,
        driver_name=driver_name,
        prefix=prefix,
        seed=args.seed,
        width=args.width,
        height=args.height,
        length=args.length,
        steps=args.steps,
    )
    workflow_path = output_dir / "workflow.api.json"
    workflow_path.write_text(
        json.dumps(workflow, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    response = request_json(
        f"{args.base_url}/prompt",
        {"prompt": workflow, "client_id": str(uuid.uuid4())},
    )
    prompt_id = str(response["prompt_id"])
    print(json.dumps({"event": "queued", "prompt_id": prompt_id}, ensure_ascii=False), flush=True)
    history = wait_history(args.base_url, prompt_id, args.timeout)

    saved: list[Path] = []
    for node_output in history.get("outputs", {}).values():
        for image in node_output.get("images", []):
            filename = str(image.get("filename") or "")
            subfolder = str(image.get("subfolder") or "")
            source = comfy_output / subfolder / filename
            if source.is_file():
                saved.append(source)
    if not saved:
        raise FileNotFoundError("ComfyUI saved no benchmark frames")

    saved.sort(key=lambda path: path.name)
    frames_dir = output_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    for index, source in enumerate(saved):
        shutil.copy2(source, frames_dir / f"frame_{index:04d}.png")
    generated = output_dir / "b2_fake_illness_native_wan22_animate_move.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-framerate",
            "16",
            "-i",
            str(frames_dir / "frame_%04d.png"),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "18",
            str(generated),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=600,
    )

    stats = request_json(f"{args.base_url}/system_stats")
    report = {
        "schema": "reference_404263_native_move_benchmark/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending_manual_review",
        "benchmark_id": "b2_fake_illness_staging",
        "reference_range_seconds": [52.0, 54.3],
        "reference_pixels_used": True,
        "reference_identity_used": True,
        "usage": "internal_workflow_fidelity_benchmark_only",
        "publish_allowed": False,
        "douyin_upload_allowed": False,
        "fanqie_backfill_allowed": False,
        "renderer": "native_comfyui_wan22_animate_move",
        "comfyui_version": stats.get("system", {}).get("comfyui_version"),
        "model": "Wan2_2-Animate-14B_fp8_e4m3fn_scaled_KJ.safetensors",
        "lora": "lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors",
        "reference_frame": str(reference_frame),
        "reference_frame_sha256": sha256(reference_frame),
        "driver": str(driver),
        "driver_sha256": sha256(driver),
        "workflow": str(workflow_path),
        "workflow_sha256": sha256(workflow_path),
        "prompt_id": prompt_id,
        "seed": args.seed,
        "steps": args.steps,
        "width": args.width,
        "height": args.height,
        "length": args.length,
        "saved_frame_count": len(saved),
        "fps": 16.0,
        "video": str(generated),
        "video_sha256": sha256(generated),
        "pose_video": None,
        "pose_history_available": True,
        "manual_review_requirements": [
            "body_action_matches_reference_without_teleport",
            "expression_transition_is_gradual",
            "phone_and_screen_plane_remain_continuous",
            "bed_and_props_do_not_jump",
            "hands_do_not_fuse_with_phone",
        ],
    }
    report_path = output_dir / "benchmark.report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {"event": "complete", "video": str(generated), "report": str(report_path)},
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
