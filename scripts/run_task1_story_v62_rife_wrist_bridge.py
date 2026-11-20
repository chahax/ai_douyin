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
        time.sleep(1)
    raise TimeoutError(prompt_id)


def graph(names: list[str], prefix: str) -> dict:
    workflow: dict[str, object] = {}
    scaled_nodes: list[str] = []
    for index, name in enumerate(names, start=1):
        load_id = str(index)
        scale_id = str(index + 10)
        workflow[load_id] = {"class_type": "LoadImage", "inputs": {"image": name}}
        workflow[scale_id] = {
            "class_type": "ImageScale",
            "inputs": {
                "image": [load_id, 0], "upscale_method": "lanczos",
                "width": 704, "height": 1248, "crop": "center",
            },
        }
        scaled_nodes.append(scale_id)

    workflow["20"] = {"class_type": "ImageBatch", "inputs": {"image1": [scaled_nodes[0], 0], "image2": [scaled_nodes[1], 0]}}
    workflow["21"] = {"class_type": "ImageBatch", "inputs": {"image1": ["20", 0], "image2": [scaled_nodes[2], 0]}}
    workflow["22"] = {"class_type": "ImageBatch", "inputs": {"image1": ["21", 0], "image2": [scaled_nodes[3], 0]}}
    workflow["23"] = {"class_type": "FrameInterpolationModelLoader", "inputs": {"model_name": "rife_v4.26.safetensors"}}
    workflow["24"] = {"class_type": "FrameInterpolate", "inputs": {"interp_model": ["23", 0], "images": ["22", 0], "multiplier": 5}}
    workflow["25"] = {"class_type": "CreateVideo", "inputs": {"images": ["24", 0], "fps": 25.0}}
    workflow["26"] = {"class_type": "SaveVideo", "inputs": {"video": ["25", 0], "filename_prefix": prefix, "format": "mp4", "codec": "h264"}}
    return workflow


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the V6.2 four-keyframe RIFE wrist-contact bridge.")
    parser.add_argument("--start", required=True)
    parser.add_argument("--approach", required=True)
    parser.add_argument("--contact", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8190")
    parser.add_argument("--comfy-input", default=r"D:\IT\AI_vido\ComfyUI\input")
    parser.add_argument("--comfy-output", default=r"D:\IT\AI_vido\ComfyUI\output")
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()

    keyframes = [Path(value).resolve() for value in (args.start, args.approach, args.contact, args.end)]
    output_root = Path(args.output_root).resolve()
    comfy_input = Path(args.comfy_input).resolve()
    comfy_output = Path(args.comfy_output).resolve()
    for required in (*keyframes, comfy_input, comfy_output):
        if not required.exists():
            raise FileNotFoundError(required)

    output_root.mkdir(parents=True, exist_ok=True)
    input_prefix = f"task1_story_v62_rife_bridge_{uuid.uuid4().hex[:10]}"
    names: list[str] = []
    for index, source in enumerate(keyframes):
        name = f"{input_prefix}_{index:02d}.png"
        shutil.copy2(source, comfy_input / name)
        names.append(name)

    save_prefix = f"task1_story_v62_rife_bridge/{input_prefix}"
    workflow = graph(names, save_prefix)
    workflow_path = output_root / "rife_wrist_bridge.api.json"
    workflow_path.write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8")

    output_dir = comfy_output / "task1_story_v62_rife_bridge"
    before = {path.resolve() for path in output_dir.glob(f"{input_prefix}*.mp4")} if output_dir.exists() else set()
    response = request_json(f"{args.base_url}/prompt", {"prompt": workflow, "client_id": str(uuid.uuid4())})
    prompt_id = response["prompt_id"]
    print(f"queued RIFE wrist bridge: {prompt_id}", flush=True)
    wait_history(args.base_url, prompt_id, args.timeout)

    candidates = [path for path in output_dir.glob(f"{input_prefix}*.mp4") if path.resolve() not in before]
    if not candidates:
        candidates = list(output_dir.glob(f"{input_prefix}*.mp4"))
    if not candidates:
        raise FileNotFoundError("ComfyUI completed without saving the RIFE wrist bridge MP4")
    generated = max(candidates, key=lambda path: path.stat().st_mtime)
    destination = output_root / "wrist_grab_bridge_rife.mp4"
    shutil.copy2(generated, destination)

    report = {
        "schema": "task1_story_v62_rife_wrist_bridge/v1",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "publish_allowed": False,
        "scene_id": "b02_grab_reaction",
        "renderer": "local_rife_interpolation_bridge",
        "model": "rife_v4.26.safetensors",
        "prompt_id": prompt_id,
        "keyframes": [{"path": str(path), "sha256": sha256(path)} for path in keyframes],
        "workflow": {"path": str(workflow_path), "sha256": sha256(workflow_path)},
        "video": {"path": str(destination), "sha256": sha256(destination)},
        "comfy_output_source": str(generated),
        "expected_frames": 16,
        "fps": 25,
        "expected_duration_seconds": 0.64,
    }
    report_path = output_root / "render_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
