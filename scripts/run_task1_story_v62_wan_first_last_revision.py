from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path


POSITIVE = (
    "High-end glossy photorealistic Chinese live-action campus micro-drama at night after rain. "
    "Preserve the exact adult male identity, face, hairstyle, pale blue open overshirt, white T-shirt, "
    "dark jeans, wet street background, teal-orange neon lighting, camera height, lens and color grade "
    "from the supplied first and last frames. The man completes one calm believable forward step, "
    "smoothly lowers the phone in his right hand, turns his torso and head slightly toward screen-right, "
    "and extends his free left forearm toward the empty screen-right space. Natural weight transfer, "
    "subtle shoulder counter-motion, stable anatomy, stable phone, stable camera. End exactly on the supplied "
    "last frame, ready for the next shot in which an off-screen person reaches for his left wrist."
)

NEGATIVE = (
    "face morphing, identity change, hairstyle change, clothing change, scene change, background change, "
    "phone switching hands, phone duplication, disappearing phone, extra fingers, fused fingers, deformed hands, "
    "extra limbs, missing limbs, duplicated person, woman entering frame, rubber body, frozen body, frozen legs, "
    "foot sliding, moonwalk, dancing, jumping, running, sudden acceleration, exaggerated pose, fast motion, "
    "camera shake, pan, tilt, zoom, scene cut, flicker, exposure pumping, anime, cartoon, presenter, "
    "text, subtitles, watermark, logo"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def request_json(url: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read())


def wait_history(base_url: str, prompt_id: str, timeout_seconds: int) -> dict:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        result = request_json(f"{base_url}/history/{prompt_id}")
        if prompt_id in result:
            item = result[prompt_id]
            if item.get("status", {}).get("status_str") == "error":
                raise RuntimeError(json.dumps(item.get("status"), ensure_ascii=False))
            return item
        time.sleep(3)
    raise TimeoutError(prompt_id)


def graph(start_name: str, end_name: str, seed: int, prefix: str) -> dict:
    return {
        "1": {
            "class_type": "CLIPLoader",
            "inputs": {
                "clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
                "type": "wan",
                "device": "default",
            },
        },
        "2": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 0], "text": POSITIVE}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 0], "text": NEGATIVE}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": "wan2.2_vae.safetensors"}},
        "5": {"class_type": "LoadImage", "inputs": {"image": start_name}},
        "6": {"class_type": "LoadImage", "inputs": {"image": end_name}},
        "7": {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": "clip_vision_h.safetensors"}},
        "8": {
            "class_type": "CLIPVisionEncode",
            "inputs": {"clip_vision": ["7", 0], "image": ["5", 0], "crop": "none"},
        },
        "9": {
            "class_type": "CLIPVisionEncode",
            "inputs": {"clip_vision": ["7", 0], "image": ["6", 0], "crop": "none"},
        },
        "10": {
            "class_type": "WanFirstLastFrameToVideo",
            "inputs": {
                "positive": ["2", 0],
                "negative": ["3", 0],
                "vae": ["4", 0],
                "width": 416,
                "height": 736,
                "length": 49,
                "batch_size": 1,
                "clip_vision_start_image": ["8", 0],
                "clip_vision_end_image": ["9", 0],
                "start_image": ["5", 0],
                "end_image": ["6", 0],
            },
        },
        "11": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": "wan2.2_ti2v_5B_fp16.safetensors", "weight_dtype": "default"},
        },
        "12": {
            "class_type": "KSamplerAdvanced",
            "inputs": {
                "model": ["11", 0],
                "positive": ["10", 0],
                "negative": ["10", 1],
                "latent_image": ["10", 2],
                "add_noise": "enable",
                "noise_seed": seed,
                "steps": 6,
                "cfg": 1.0,
                "sampler_name": "euler",
                "scheduler": "simple",
                "start_at_step": 0,
                "end_at_step": 3,
                "return_with_leftover_noise": "enable",
            },
        },
        "13": {
            "class_type": "KSamplerAdvanced",
            "inputs": {
                "model": ["11", 0],
                "positive": ["10", 0],
                "negative": ["10", 1],
                "latent_image": ["12", 0],
                "add_noise": "disable",
                "noise_seed": seed,
                "steps": 6,
                "cfg": 1.0,
                "sampler_name": "euler",
                "scheduler": "simple",
                "start_at_step": 3,
                "end_at_step": 6,
                "return_with_leftover_noise": "disable",
            },
        },
        "14": {"class_type": "VAEDecode", "inputs": {"samples": ["13", 0], "vae": ["4", 0]}},
        "15": {"class_type": "CreateVideo", "inputs": {"images": ["14", 0], "fps": 16.0}},
        "16": {
            "class_type": "SaveVideo",
            "inputs": {"video": ["15", 0], "filename_prefix": prefix, "format": "mp4", "codec": "h264"},
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Render V6.2 b01 with Wan 2.2 first/last-frame conditioning.")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--seed", type=int, default=6220822)
    parser.add_argument("--base-url", default="http://127.0.0.1:8190")
    parser.add_argument("--comfy-input", default=r"D:\IT\AI_vido\ComfyUI\input")
    parser.add_argument("--comfy-output", default=r"D:\IT\AI_vido\ComfyUI\output")
    parser.add_argument("--timeout", type=int, default=5400)
    args = parser.parse_args()

    start_path = Path(args.start).resolve()
    end_path = Path(args.end).resolve()
    output_root = Path(args.output_root).resolve()
    comfy_input = Path(args.comfy_input).resolve()
    comfy_output = Path(args.comfy_output).resolve()
    for required in (start_path, end_path, comfy_input, comfy_output):
        if not required.exists():
            raise FileNotFoundError(required)

    output_root.mkdir(parents=True, exist_ok=True)
    input_prefix = f"task1_story_v62_wan_{uuid.uuid4().hex[:10]}"
    start_name = f"{input_prefix}_start.png"
    end_name = f"{input_prefix}_end.png"
    shutil.copy2(start_path, comfy_input / start_name)
    shutil.copy2(end_path, comfy_input / end_name)

    save_prefix = f"task1_story_v62_wan_first_last/{input_prefix}_b01"
    workflow = graph(start_name, end_name, args.seed, save_prefix)
    workflow_path = output_root / "b01_wan_first_last.api.json"
    workflow_path.write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8")

    output_dir = comfy_output / "task1_story_v62_wan_first_last"
    before = {path.resolve() for path in output_dir.glob(f"{input_prefix}_b01*.mp4")} if output_dir.exists() else set()
    response = request_json(f"{args.base_url}/prompt", {"prompt": workflow, "client_id": str(uuid.uuid4())})
    prompt_id = response["prompt_id"]
    print(f"queued b01 Wan first/last: {prompt_id}", flush=True)
    wait_history(args.base_url, prompt_id, args.timeout)

    candidates = [path for path in output_dir.glob(f"{input_prefix}_b01*.mp4") if path.resolve() not in before]
    if not candidates:
        candidates = list(output_dir.glob(f"{input_prefix}_b01*.mp4"))
    if not candidates:
        raise FileNotFoundError("ComfyUI completed without saving the Wan b01 MP4")
    generated = max(candidates, key=lambda path: path.stat().st_mtime)
    destination = output_root / "b01_boast_wan_first_last.mp4"
    shutil.copy2(generated, destination)

    report = {
        "schema": "task1_story_v62_wan_first_last_render/v1",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "publish_allowed": False,
        "scene_id": "b01_boast",
        "renderer": "local_comfyui_wan_first_last",
        "model": "wan2.2_ti2v_5B_fp16.safetensors",
        "seed": args.seed,
        "prompt_id": prompt_id,
        "start_frame": {"path": str(start_path), "sha256": sha256(start_path)},
        "end_frame": {"path": str(end_path), "sha256": sha256(end_path)},
        "workflow": {"path": str(workflow_path), "sha256": sha256(workflow_path)},
        "video": {"path": str(destination), "sha256": sha256(destination)},
        "comfy_output_source": str(generated),
    }
    report_path = output_root / "render_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
