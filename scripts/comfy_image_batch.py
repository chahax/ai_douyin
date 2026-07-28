from __future__ import annotations

import argparse
import json
import shutil
import time
import urllib.request
import uuid
from pathlib import Path


def _request_json(url: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())


def _workflow(*, checkpoint: str, prompt: str, seed: int, width: int, height: int,
              steps: int, cfg: float, sampler: str, scheduler: str,
              filename_prefix: str) -> dict:
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["1", 1]}},
        "4": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0], "seed": seed, "steps": steps, "cfg": cfg,
                "sampler_name": sampler, "scheduler": scheduler,
                "positive": ["2", 0], "negative": ["3", 0],
                "latent_image": ["4", 0], "denoise": 1.0,
            },
        },
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"images": ["6", 0], "filename_prefix": filename_prefix}},
    }


def _wait_history(base_url: str, prompt_id: str, timeout_seconds: int) -> dict:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        history = _request_json(f"{base_url}/history/{prompt_id}")
        if prompt_id in history:
            return history[prompt_id]
        time.sleep(2)
    raise TimeoutError(f"ComfyUI prompt timed out: {prompt_id}")


def _saved_image(history: dict, output_root: Path) -> Path:
    for output in history.get("outputs", {}).values():
        for image in output.get("images", []):
            if image.get("type") != "output":
                continue
            return output_root / image.get("subfolder", "") / image["filename"]
    raise RuntimeError("ComfyUI history did not contain a saved output image")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a batch of project keyframes through ComfyUI API.")
    parser.add_argument("project")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8190")
    parser.add_argument("--comfy-output", default=r"D:\IT\AI_vido\ComfyUI\output")
    parser.add_argument("--anchor-only", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--only", action="append", help="Generate only a selected item id; repeat as needed.")
    parser.add_argument("--overrides", help="Optional JSON mapping item ids to prompt overrides.")
    parser.add_argument("--seed-offset", type=int, default=0)
    parser.add_argument("--filename-prefix", default="anti_fraud_police_chibi/old")
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    args = parser.parse_args()

    project_path = Path(args.project).resolve()
    project = json.loads(project_path.read_text(encoding="utf-8"))
    settings = project["keyframe_generation"]
    output_dir = Path(args.output_dir).resolve()
    workflow_dir = output_dir / "workflows"
    image_dir = output_dir / "keyframes"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    image_dir.mkdir(parents=True, exist_ok=True)

    overrides = (
        json.loads(Path(args.overrides).read_text(encoding="utf-8"))
        if args.overrides else {}
    )
    items = [project["anchor"]]
    if not args.anchor_only:
        items.extend(project["shots"])
    if args.only:
        selected = set(args.only)
        items = [item for item in items if item["id"] in selected]

    report = []
    client_id = str(uuid.uuid4())
    for item in items:
        output_path = image_dir / f"{item['id']}.png"
        if args.skip_existing and output_path.is_file():
            report.append({"id": item["id"], "status": "skipped", "output": str(output_path)})
            continue
        workflow = _workflow(
            checkpoint=settings["checkpoint"],
            prompt=overrides.get(item["id"], {}).get("prompt", item["prompt"]),
            seed=item["seed"] + args.seed_offset,
            width=item.get("width", settings["width"]), height=item.get("height", settings["height"]),
            steps=settings["steps"], cfg=settings["cfg"], sampler=settings["sampler"],
            scheduler=settings["scheduler"], filename_prefix=f"{args.filename_prefix}/{item['id']}",
        )
        (workflow_dir / f"{item['id']}.api.json").write_text(
            json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        response = _request_json(f"{args.base_url}/prompt", {"prompt": workflow, "client_id": client_id})
        prompt_id = response["prompt_id"]
        history = _wait_history(args.base_url, prompt_id, args.timeout_seconds)
        source = _saved_image(history, Path(args.comfy_output))
        if not source.is_file():
            raise FileNotFoundError(source)
        shutil.copy2(source, output_path)
        report.append({
            "id": item["id"], "status": "generated", "prompt_id": prompt_id,
            "source": str(source), "output": str(output_path), "seed": item["seed"] + args.seed_offset,
        })
        (output_dir / "run_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"generated {item['id']}: {output_path}", flush=True)


if __name__ == "__main__":
    main()
