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
    "Photorealistic live-action Chinese micro-drama, tight insert shot of hands and wrists only, "
    "wet campus walkway at blue hour, stable teal-blue and amber bokeh, locked camera. Preserve the "
    "supplied first and last frames exactly. In one continuous natural motion, the adult woman's right "
    "hand in an ivory blazer sleeve reaches the remaining few centimeters from screen-right, makes contact, "
    "then closes firmly but nonviolently around the adult man's right wrist in a pale-blue rolled sleeve. "
    "Natural finger articulation, anatomically correct contact, smooth acceleration and deceleration, stable "
    "forearms, stable lighting and background. End exactly on the supplied completed-grab frame."
)

NEGATIVE = (
    "scene cut, camera movement, background change, sleeve change, hand teleporting, sudden contact, jitter, "
    "stutter, frozen motion, hand morphing, extra hand, extra arm, extra fingers, fused fingers, missing fingers, "
    "rubber wrist, duplicated wrist, face, person body, phone, text, subtitles, logo, watermark, anime, cartoon"
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
        "1": {"class_type": "CLIPLoader", "inputs": {"clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "type": "wan", "device": "default"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 0], "text": POSITIVE}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 0], "text": NEGATIVE}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": "wan2.2_vae.safetensors"}},
        "5": {"class_type": "LoadImage", "inputs": {"image": start_name}},
        "6": {"class_type": "LoadImage", "inputs": {"image": end_name}},
        "7": {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": "clip_vision_h.safetensors"}},
        "8": {"class_type": "CLIPVisionEncode", "inputs": {"clip_vision": ["7", 0], "image": ["5", 0], "crop": "none"}},
        "9": {"class_type": "CLIPVisionEncode", "inputs": {"clip_vision": ["7", 0], "image": ["6", 0], "crop": "none"}},
        "10": {
            "class_type": "WanFirstLastFrameToVideo",
            "inputs": {
                "positive": ["2", 0], "negative": ["3", 0], "vae": ["4", 0],
                "width": 416, "height": 736, "length": 17, "batch_size": 1,
                "clip_vision_start_image": ["8", 0], "clip_vision_end_image": ["9", 0],
                "start_image": ["5", 0], "end_image": ["6", 0],
            },
        },
        "11": {"class_type": "UNETLoader", "inputs": {"unet_name": "wan2.2_ti2v_5B_fp16.safetensors", "weight_dtype": "default"}},
        "12": {
            "class_type": "KSamplerAdvanced",
            "inputs": {
                "model": ["11", 0], "positive": ["10", 0], "negative": ["10", 1], "latent_image": ["10", 2],
                "add_noise": "enable", "noise_seed": seed, "steps": 6, "cfg": 1.0,
                "sampler_name": "euler", "scheduler": "simple", "start_at_step": 0, "end_at_step": 3,
                "return_with_leftover_noise": "enable",
            },
        },
        "13": {
            "class_type": "KSamplerAdvanced",
            "inputs": {
                "model": ["11", 0], "positive": ["10", 0], "negative": ["10", 1], "latent_image": ["12", 0],
                "add_noise": "disable", "noise_seed": seed, "steps": 6, "cfg": 1.0,
                "sampler_name": "euler", "scheduler": "simple", "start_at_step": 3, "end_at_step": 6,
                "return_with_leftover_noise": "disable",
            },
        },
        "14": {"class_type": "VAEDecode", "inputs": {"samples": ["13", 0], "vae": ["4", 0]}},
        "15": {"class_type": "CreateVideo", "inputs": {"images": ["14", 0], "fps": 16.0}},
        "16": {"class_type": "SaveVideo", "inputs": {"video": ["15", 0], "filename_prefix": prefix, "format": "mp4", "codec": "h264"}},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the V6.2 b01-to-b02 wrist-contact bridge with Wan first/last conditioning.")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--seed", type=int, default=6220824)
    parser.add_argument("--base-url", default="http://127.0.0.1:8190")
    parser.add_argument("--comfy-input", default=r"D:\IT\AI_vido\ComfyUI\input")
    parser.add_argument("--comfy-output", default=r"D:\IT\AI_vido\ComfyUI\output")
    parser.add_argument("--timeout", type=int, default=3600)
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
    input_prefix = f"task1_story_v62_wrist_bridge_{uuid.uuid4().hex[:10]}"
    start_name = f"{input_prefix}_start.png"
    end_name = f"{input_prefix}_end.png"
    shutil.copy2(start_path, comfy_input / start_name)
    shutil.copy2(end_path, comfy_input / end_name)

    save_prefix = f"task1_story_v62_wrist_bridge/{input_prefix}"
    workflow = graph(start_name, end_name, args.seed, save_prefix)
    workflow_path = output_root / "wrist_bridge.api.json"
    workflow_path.write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8")

    output_dir = comfy_output / "task1_story_v62_wrist_bridge"
    before = {path.resolve() for path in output_dir.glob(f"{input_prefix}*.mp4")} if output_dir.exists() else set()
    response = request_json(f"{args.base_url}/prompt", {"prompt": workflow, "client_id": str(uuid.uuid4())})
    prompt_id = response["prompt_id"]
    print(f"queued Wan wrist bridge: {prompt_id}", flush=True)
    wait_history(args.base_url, prompt_id, args.timeout)

    candidates = [path for path in output_dir.glob(f"{input_prefix}*.mp4") if path.resolve() not in before]
    if not candidates:
        candidates = list(output_dir.glob(f"{input_prefix}*.mp4"))
    if not candidates:
        raise FileNotFoundError("ComfyUI completed without saving the wrist bridge MP4")
    generated = max(candidates, key=lambda path: path.stat().st_mtime)
    destination = output_root / "wrist_grab_bridge_wan_first_last.mp4"
    shutil.copy2(generated, destination)

    report = {
        "schema": "task1_story_v62_wrist_bridge_render/v1",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "publish_allowed": False,
        "scene_id": "b02_grab_reaction",
        "renderer": "local_comfyui_wan_first_last_bridge",
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
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
