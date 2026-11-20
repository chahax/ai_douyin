"""Run the B2 fake-illness benchmark with local LTX 2.3 I2V.

The reference frame contains source-video pixels and identity, so every output
is internal-only and non-publishable.  This benchmark measures whether LTX is a
useful light-action / facial-close-up tool, not whether it can copy motion.
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
DEFAULT_FRAME = (
    ROOT
    / r"data\qa\reference_404263_performance_benchmarks_20260825"
    / r"b2_fake_illness\internal_reference\frame_52_000.png"
)
DEFAULT_OUTPUT = (
    ROOT
    / r"data\qa\reference_404263_performance_benchmarks_20260825"
    / r"b2_fake_illness\ltx23_i2v"
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
    prefix: str,
    seed: int,
    width: int,
    height: int,
    length: int,
    steps: int,
) -> dict[str, object]:
    positive = (
        "Photorealistic vertical Chinese crime microdrama. Preserve the exact input woman, "
        "face, hair, clothes, bed, lighting and composition. She lies naturally on her side, "
        "slowly opens her eyes, raises one relaxed hand toward her forehead as if performing "
        "weakness for an off-camera phone, holds the pose, then looks toward that phone. "
        "Restrained gradual facial change, natural breathing and weight, one coherent light "
        "action, stable hands, stable room geometry, locked camera."
    )
    negative = (
        "identity change, face morphing, stretched neck, rubber face, extra person, extra legs, "
        "feet near camera, extra arms, extra fingers, fused hands, malformed hand, floating prop, "
        "phone disappearance, missing screen, half squat, frozen legs, bed deformation, background "
        "jump, camera shake, zoom, scene cut, flicker, exposure pumping, readable text, subtitle, "
        "watermark, logo, anime, cartoon, presenter"
    )
    return {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": "LTX2\\ltx-2.3-22b-distilled-1.1_transformer_only_fp8_scaled.safetensors",
                "weight_dtype": "default",
            },
        },
        "2": {
            "class_type": "ModelSamplingLTXV",
            "inputs": {"model": ["1", 0], "max_shift": 2.05, "base_shift": 0.95, "latent": ["9", 2]},
        },
        "3": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": "LTX-Kijai\\LTX23_video_vae_bf16.safetensors"},
        },
        "4": {
            "class_type": "LTXAVTextEncoderLoader",
            "inputs": {
                "text_encoder": "gemma_3_12B_it.safetensors",
                "ckpt_name": "ltx-2.3-text-proj-only.safetensors",
                "device": "default",
            },
        },
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 0], "text": positive}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 0], "text": negative}},
        "7": {
            "class_type": "LTXVConditioning",
            "inputs": {"positive": ["5", 0], "negative": ["6", 0], "frame_rate": 25.0},
        },
        "8": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "9": {
            "class_type": "LTXVImgToVideo",
            "inputs": {
                "positive": ["7", 0],
                "negative": ["7", 1],
                "vae": ["3", 0],
                "image": ["8", 0],
                "width": width,
                "height": height,
                "length": length,
                "batch_size": 1,
                "strength": 0.92,
            },
        },
        "10": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["2", 0],
                "positive": ["9", 0],
                "negative": ["9", 1],
                "latent_image": ["9", 2],
                "seed": seed,
                "steps": steps,
                "cfg": 1.0,
                "sampler_name": "euler_ancestral_cfg_pp",
                "scheduler": "simple",
                "denoise": 1.0,
            },
        },
        "11": {
            "class_type": "LTXVTiledVAEDecode",
            "inputs": {
                "vae": ["3", 0],
                "latents": ["10", 0],
                "horizontal_tiles": 1,
                "vertical_tiles": 2,
                "overlap": 2,
                "last_frame_fix": False,
                "working_device": "auto",
                "working_dtype": "auto",
            },
        },
        "12": {"class_type": "SaveImage", "inputs": {"images": ["11", 0], "filename_prefix": prefix}},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8190")
    parser.add_argument("--comfy-root", type=Path, default=DEFAULT_COMFY_ROOT)
    parser.add_argument("--reference-frame", type=Path, default=DEFAULT_FRAME)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=825522)
    parser.add_argument("--width", type=int, default=320)
    parser.add_argument("--height", type=int, default=576)
    parser.add_argument("--length", type=int, default=57)
    parser.add_argument("--steps", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=7200)
    args = parser.parse_args()

    reference_frame = args.reference_frame.resolve()
    output_dir = args.output_dir.resolve()
    comfy_root = args.comfy_root.resolve()
    comfy_input = comfy_root / "input"
    comfy_output = comfy_root / "output"
    if not reference_frame.is_file():
        raise FileNotFoundError(reference_frame)
    if (args.length - 1) % 8 != 0:
        raise ValueError("LTX frame length must be 8n+1")
    if args.width % 32 or args.height % 32:
        raise ValueError("LTX width and height must be multiples of 32")
    output_dir.mkdir(parents=True, exist_ok=True)

    object_info = request_json(f"{args.base_url}/object_info")
    required = {"LTXVImgToVideo", "LTXVTiledVAEDecode", "LTXAVTextEncoderLoader", "SaveImage"}
    missing = sorted(required - set(object_info))
    if missing:
        raise RuntimeError(f"ComfyUI is missing LTX nodes: {missing}")

    token = uuid.uuid4().hex[:8]
    image_name = f"reference_404263_b2_ltx_{token}.png"
    shutil.copy2(reference_frame, comfy_input / image_name)
    prefix = f"reference_404263_performance_bench/b2_ltx23_{token}"
    workflow = graph(
        image_name=image_name,
        prefix=prefix,
        seed=args.seed,
        width=args.width,
        height=args.height,
        length=args.length,
        steps=args.steps,
    )
    workflow_path = output_dir / "workflow.api.json"
    workflow_path.write_text(json.dumps(workflow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

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
            source = comfy_output / str(image.get("subfolder") or "") / str(image.get("filename") or "")
            if source.is_file():
                saved.append(source)
    if not saved:
        raise FileNotFoundError("ComfyUI saved no LTX benchmark frames")
    saved.sort(key=lambda path: path.name)
    frames_dir = output_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    for index, source in enumerate(saved):
        shutil.copy2(source, frames_dir / f"frame_{index:04d}.png")

    video = output_dir / "b2_fake_illness_ltx23_i2v.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-framerate", "25", "-i", str(frames_dir / "frame_%04d.png"),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", str(video),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=600,
    )

    report = {
        "schema": "reference_404263_ltx23_benchmark/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending_manual_review",
        "benchmark_id": "b2_fake_illness_staging",
        "reference_range_seconds": [52.0, 54.3],
        "reference_pixels_used": True,
        "reference_identity_used": True,
        "usage": "internal_light_action_and_expression_benchmark_only",
        "publish_allowed": False,
        "douyin_upload_allowed": False,
        "fanqie_backfill_allowed": False,
        "renderer": "local_ltx23_i2v",
        "model": "ltx-2.3-22b-distilled-1.1_transformer_only_fp8_scaled.safetensors",
        "reference_frame": str(reference_frame),
        "reference_frame_sha256": sha256(reference_frame),
        "workflow": str(workflow_path),
        "workflow_sha256": sha256(workflow_path),
        "prompt_id": prompt_id,
        "seed": args.seed,
        "steps": args.steps,
        "width": args.width,
        "height": args.height,
        "length": args.length,
        "fps": 25.0,
        "saved_frame_count": len(saved),
        "video": str(video),
        "video_sha256": sha256(video),
    }
    report_path = output_dir / "benchmark.report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"event": "complete", "video": str(video), "report": str(report_path)}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
