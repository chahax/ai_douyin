"""Generate styled keyframes while preserving only pose from guide frames."""

from __future__ import annotations

import argparse
import json
import shutil
import time
import urllib.request
import uuid
from pathlib import Path


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
        payload = request_json(f"{base_url}/history/{prompt_id}")
        if prompt_id in payload:
            result = payload[prompt_id]
            if result.get("status", {}).get("status_str") == "error":
                raise RuntimeError(json.dumps(result["status"], ensure_ascii=False))
            return result
        time.sleep(2)
    raise TimeoutError(prompt_id)


def saved_image(history: dict, output_root: Path) -> Path:
    for output in history.get("outputs", {}).values():
        for item in output.get("images", []):
            if item.get("type") == "output" and str(item.get("filename", "")).lower().endswith(".png"):
                return output_root / item.get("subfolder", "") / item["filename"]
    raise RuntimeError("ComfyUI history did not contain a saved PNG")


def workflow(*, settings: dict, prompt: str, negative: str, guide: str, seed: int,
             strength: float, filename_prefix: str, controlnet: str) -> dict:
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": settings["checkpoint"]}},
        "2": {"class_type": "LoadImage", "inputs": {"image": guide}},
        "3": {
            "class_type": "DWPreprocessor",
            "inputs": {
                "image": ["2", 0], "detect_hand": "enable", "detect_body": "enable",
                "detect_face": "disable", "resolution": 768, "bbox_detector": "yolox_l.onnx",
                "pose_estimator": "dw-ll_ucoco_384_bs5.torchscript.pt", "scale_stick_for_xinsr_cn": "disable",
            },
        },
        "4": {"class_type": "ControlNetLoader", "inputs": {"control_net_name": controlnet}},
        "5": {"class_type": "SetUnionControlNetType", "inputs": {"control_net": ["4", 0], "type": "openpose"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["1", 1]}},
        "8": {
            "class_type": "ControlNetApplyAdvanced",
            "inputs": {
                "positive": ["6", 0], "negative": ["7", 0], "control_net": ["5", 0],
                "image": ["3", 0], "strength": strength, "start_percent": 0.0,
                "end_percent": 0.72, "vae": ["1", 2],
            },
        },
        "9": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": settings["width"], "height": settings["height"], "batch_size": 1},
        },
        "10": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0], "seed": seed, "steps": settings["steps"], "cfg": settings["cfg"],
                "sampler_name": settings["sampler"], "scheduler": settings["scheduler"],
                "positive": ["8", 0], "negative": ["8", 1], "latent_image": ["9", 0], "denoise": 1.0,
            },
        },
        "11": {"class_type": "VAEDecode", "inputs": {"samples": ["10", 0], "vae": ["1", 2]}},
        "12": {"class_type": "SaveImage", "inputs": {"images": ["11", 0], "filename_prefix": filename_prefix}},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--guide-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--input-prefix", required=True)
    parser.add_argument("--filename-prefix", required=True)
    parser.add_argument("--only", action="append")
    parser.add_argument("--strength", type=float, default=0.72)
    parser.add_argument("--seed-offset", type=int, default=5000)
    parser.add_argument("--controlnet", default=r"InstantX_FLUX1_dev_Controlnet_Union\diffusion_pytorch_model.safetensors")
    parser.add_argument("--base-url", default="http://127.0.0.1:8190")
    parser.add_argument("--comfy-input", type=Path, default=Path(r"D:\IT\AI_vido\ComfyUI\input"))
    parser.add_argument("--comfy-output", type=Path, default=Path(r"D:\IT\AI_vido\ComfyUI\output"))
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    args = parser.parse_args()

    project = json.loads(args.project.resolve().read_text(encoding="utf-8"))
    if project.get("publish_allowed") is not False:
        raise ValueError("project must remain non-publishable")
    settings = project["keyframe_generation"]
    selected = set(args.only or [])
    shots = [shot for shot in project["shots"] if not selected or str(shot["id"]) in selected]
    guide_dir = args.guide_dir.resolve()
    output_dir = args.output_dir.resolve()
    keyframe_dir = output_dir / "keyframes"
    workflow_dir = output_dir / "workflows"
    keyframe_dir.mkdir(parents=True, exist_ok=True)
    workflow_dir.mkdir(parents=True, exist_ok=True)
    comfy_dir = args.comfy_input.resolve() / Path(args.input_prefix.replace("/", "\\"))
    comfy_dir.mkdir(parents=True, exist_ok=True)
    report: list[dict] = []
    client_id = str(uuid.uuid4())
    for shot in shots:
        shot_id = str(shot["id"])
        guide_source = guide_dir / f"{shot_id}.png"
        if not guide_source.is_file():
            raise FileNotFoundError(guide_source)
        guide_target = comfy_dir / f"{shot_id}.png"
        shutil.copy2(guide_source, guide_target)
        guide_ref = f"{args.input_prefix}/{shot_id}.png"
        graph = workflow(
            settings=settings, prompt=str(shot["prompt"]),
            negative=str(project["video_generation"]["negative_prompt"]), guide=guide_ref,
            seed=int(shot["seed"]) + args.seed_offset, strength=args.strength,
            filename_prefix=f"{args.filename_prefix}/{shot_id}", controlnet=args.controlnet,
        )
        (workflow_dir / f"{shot_id}.api.json").write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
        prompt_id = request_json(f"{args.base_url}/prompt", {"prompt": graph, "client_id": client_id})["prompt_id"]
        print(f"queued {shot_id}: {prompt_id}", flush=True)
        history = wait_history(args.base_url, prompt_id, args.timeout_seconds)
        source = saved_image(history, args.comfy_output.resolve())
        destination = keyframe_dir / f"{shot_id}.png"
        shutil.copy2(source, destination)
        report.append({
            "id": shot_id, "status": "generated", "prompt_id": prompt_id,
            "guide": str(guide_source), "guide_pixels_used_for_pose_only": True,
            "preprocessor": "DWPreprocessor", "controlnet": args.controlnet,
            "strength": args.strength, "output": str(destination),
        })
        (output_dir / "run_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"generated {shot_id}: {destination}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
