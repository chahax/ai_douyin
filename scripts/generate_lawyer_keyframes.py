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
        history = request_json(f"{base_url}/history/{prompt_id}")
        if prompt_id in history:
            result = history[prompt_id]
            if result.get("status", {}).get("status_str") == "error":
                raise RuntimeError(json.dumps(result.get("status"), ensure_ascii=False))
            return result
        time.sleep(2)
    raise TimeoutError(prompt_id)


def saved_png(history: dict, output_root: Path) -> Path:
    for output in history.get("outputs", {}).values():
        for image in output.get("images", []):
            if image.get("type") == "output" and image.get("filename", "").endswith(".png"):
                return output_root / image.get("subfolder", "") / image["filename"]
    raise RuntimeError("No saved PNG in ComfyUI history")


def anchor_graph(settings: dict, item: dict, prefix: str) -> dict:
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": settings["checkpoint"]}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 1], "text": item["prompt"]}},
        "3": {"class_type": "FluxGuidance", "inputs": {"conditioning": ["2", 0], "guidance": settings["guidance"]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 1], "text": ""}},
        "5": {"class_type": "EmptySD3LatentImage", "inputs": {"width": settings["width"], "height": settings["height"], "batch_size": 1}},
        "6": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "positive": ["3", 0], "negative": ["4", 0], "latent_image": ["5", 0], "seed": item["seed"], "steps": settings["steps"], "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["1", 2]}},
        "8": {"class_type": "SaveImage", "inputs": {"images": ["7", 0], "filename_prefix": prefix}},
    }


def shot_graph(settings: dict, item: dict, reference_name: str, prefix: str) -> dict:
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": settings["checkpoint"]}},
        "2": {"class_type": "LoadImage", "inputs": {"image": reference_name}},
        "3": {"class_type": "LoadFluxIPAdapter", "inputs": {"ipadatper": "ip_adapter.safetensors", "clip_vision": r"openai_clip_vit_l14\model.safetensors", "provider": "CPU"}},
        "4": {"class_type": "ApplyFluxIPAdapter", "inputs": {"model": ["1", 0], "ip_adapter_flux": ["3", 0], "image": ["2", 0], "ip_scale": item.get("ip_scale", settings["ip_scale"])}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 1], "text": item["prompt"]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 1], "text": "deformed face, duplicate person, extra limbs, bad hands, childlike lawyer, chibi, plush doll, real photograph, text, logo, watermark"}},
        "7": {"class_type": "EmptyLatentImage", "inputs": {"width": settings["width"], "height": settings["height"], "batch_size": 1}},
        "8": {"class_type": "XlabsSampler", "inputs": {"model": ["4", 0], "conditioning": ["5", 0], "neg_conditioning": ["6", 0], "noise_seed": item["seed"], "steps": settings["steps"], "timestep_to_start_cfg": settings["steps"], "true_gs": 1.0, "image_to_image_strength": 0.0, "denoise_strength": 1.0, "latent_image": ["7", 0]}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["1", 2]}},
        "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0], "filename_prefix": prefix}},
    }


def submit(graph: dict, base_url: str, output_root: Path, timeout: int) -> tuple[str, Path]:
    response = request_json(f"{base_url}/prompt", {"prompt": graph, "client_id": str(uuid.uuid4())})
    prompt_id = response["prompt_id"]
    history = wait_history(base_url, prompt_id, timeout)
    return prompt_id, saved_png(history, output_root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    parser.add_argument("--base-url", default="http://127.0.0.1:8190")
    parser.add_argument("--comfy-input", default=r"D:\IT\AI_vido\ComfyUI\input")
    parser.add_argument("--comfy-output", default=r"D:\IT\AI_vido\ComfyUI\output")
    parser.add_argument("--only", action="append")
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args()

    project_path = Path(args.project).resolve()
    project = json.loads(project_path.read_text(encoding="utf-8"))
    root = project_path.parent
    keyframes = root / "keyframes"
    workflows = root / "workflows"
    keyframes.mkdir(exist_ok=True)
    workflows.mkdir(exist_ok=True)
    settings = project["keyframe_generation"]
    output_root = Path(args.comfy_output)
    input_root = Path(args.comfy_input)
    report: list[dict] = []

    anchor = project["anchor"]
    anchor_path = keyframes / f"{anchor['id']}.png"
    if not args.only or anchor["id"] in args.only or not anchor_path.exists():
        graph = anchor_graph(settings, anchor, f"lawyer_reference_style_v1/{anchor['id']}")
        (workflows / f"{anchor['id']}.api.json").write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
        prompt_id, source = submit(graph, args.base_url, output_root, args.timeout)
        shutil.copy2(source, anchor_path)
        report.append({"id": anchor["id"], "prompt_id": prompt_id, "source": str(source), "output": str(anchor_path)})
        print(f"generated {anchor['id']}: {anchor_path}", flush=True)

    reference_name = "lawyer_reference_style_v1_shenmo_anchor.png"
    shutil.copy2(anchor_path, input_root / reference_name)
    for shot in project["shots"]:
        if args.only and shot["id"] not in args.only:
            continue
        graph = shot_graph(settings, shot, reference_name, f"lawyer_reference_style_v1/{shot['id']}")
        (workflows / f"{shot['id']}.api.json").write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
        prompt_id, source = submit(graph, args.base_url, output_root, args.timeout)
        destination = keyframes / f"{shot['id']}.png"
        shutil.copy2(source, destination)
        report.append({"id": shot["id"], "prompt_id": prompt_id, "source": str(source), "output": str(destination), "ip_scale": shot.get("ip_scale", settings["ip_scale"])})
        (root / "keyframe_run_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"generated {shot['id']}: {destination}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
