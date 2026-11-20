"""Generate scene keyframes with a per-character Flux IP-Adapter reference.

Shots without a primary character use plain Flux text-to-image. Selected
character masters are copied into a dedicated ComfyUI input prefix. The runner
is resumable and records every workflow and output incrementally.
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
import urllib.request
import uuid
from pathlib import Path

if __package__:
    from scripts.comfy_flux_ipadapter_batch import workflow as ip_workflow
    from scripts.comfy_image_batch import _workflow as text_workflow
else:
    from comfy_flux_ipadapter_batch import workflow as ip_workflow
    from comfy_image_batch import _workflow as text_workflow


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
    raise TimeoutError(f"ComfyUI prompt timed out: {prompt_id}")


def saved_image(history: dict, output_root: Path) -> Path:
    for output in history.get("outputs", {}).values():
        for image in output.get("images", []):
            if image.get("type") == "output" and image.get("filename", "").lower().endswith(".png"):
                return output_root / image.get("subfolder", "") / image["filename"]
    raise RuntimeError("ComfyUI history did not contain a saved PNG")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--master-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8190")
    parser.add_argument("--comfy-input", type=Path, default=Path(r"D:\IT\AI_vido\ComfyUI\input"))
    parser.add_argument("--comfy-output", type=Path, default=Path(r"D:\IT\AI_vido\ComfyUI\output"))
    parser.add_argument("--input-prefix", required=True)
    parser.add_argument("--filename-prefix", required=True)
    parser.add_argument("--ip-adapter", default="ip_adapter.safetensors")
    parser.add_argument("--clip-vision", default=r"openai_clip_vit_l14\model.safetensors")
    parser.add_argument("--only", action="append")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--seed-offset", type=int, default=0)
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    args = parser.parse_args()

    project_path = args.project.resolve()
    project = json.loads(project_path.read_text(encoding="utf-8"))
    if project.get("publish_allowed") is not False:
        raise ValueError("project must remain non-publishable")
    settings = project["keyframe_generation"]
    master_dir = args.master_dir.resolve()
    output_dir = args.output_dir.resolve()
    image_dir = output_dir / "keyframes"
    workflow_dir = output_dir / "workflows"
    image_dir.mkdir(parents=True, exist_ok=True)
    workflow_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "run_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else []
    completed = {str(item["id"]) for item in report if item.get("status") in {"generated", "skipped"}}

    selected_ids = set(args.only or [])
    shots = [shot for shot in project["shots"] if not selected_ids or shot["id"] in selected_ids]
    if selected_ids and {shot["id"] for shot in shots} != selected_ids:
        missing = sorted(selected_ids - {shot["id"] for shot in shots})
        raise ValueError(f"unknown shot ids: {missing}")

    comfy_master_dir = args.comfy_input.resolve() / Path(args.input_prefix.replace("/", "\\")) / "masters"
    comfy_master_dir.mkdir(parents=True, exist_ok=True)
    copied_masters: dict[str, str] = {}
    for master in master_dir.glob("*.png"):
        destination = comfy_master_dir / master.name
        shutil.copy2(master, destination)
        copied_masters[master.stem] = f"{args.input_prefix}/masters/{master.name}"

    client_id = str(uuid.uuid4())
    for shot in shots:
        shot_id = str(shot["id"])
        destination = image_dir / f"{shot_id}.png"
        if args.skip_existing and (destination.is_file() or shot_id in completed):
            print(f"skipped {shot_id}", flush=True)
            continue
        seed = int(shot["seed"]) + args.seed_offset
        primary = shot.get("primary_character")
        if primary:
            reference = copied_masters.get(str(primary))
            if not reference:
                raise FileNotFoundError(f"master missing for {shot_id}: {primary}")
            graph = ip_workflow(
                checkpoint=settings["checkpoint"], prompt=str(shot["prompt"]),
                negative_prompt=str(project["video_generation"]["negative_prompt"]), seed=seed,
                width=int(settings["width"]), height=int(settings["height"]), steps=int(settings["steps"]),
                cfg=float(settings["cfg"]), sampler=str(settings["sampler"]), scheduler=str(settings["scheduler"]),
                reference_image=reference, ip_adapter=args.ip_adapter, clip_vision=args.clip_vision,
                ip_scale=float(shot.get("ip_scale", 0.6)),
                filename_prefix=f"{args.filename_prefix}/{shot_id}",
            )
            mode = "flux_ipadapter_primary_character"
        else:
            # Do not alternate a patched x-flux graph with core KSampler in
            # one Comfy process.  The plugin leaves a patched Flux processor
            # in the model cache and core KSampler then fails while restoring
            # it.  A zero-scale adapter is semantically text-only and keeps a
            # single stable graph family for the whole batch.
            if not copied_masters:
                raise FileNotFoundError("at least one master is required for the zero-scale fallback")
            fallback_reference = copied_masters[sorted(copied_masters)[0]]
            graph = ip_workflow(
                checkpoint=settings["checkpoint"], prompt=str(shot["prompt"]),
                negative_prompt=str(project["video_generation"]["negative_prompt"]), seed=seed,
                width=int(settings["width"]), height=int(settings["height"]), steps=int(settings["steps"]),
                cfg=float(settings["cfg"]), sampler=str(settings["sampler"]), scheduler=str(settings["scheduler"]),
                reference_image=fallback_reference, ip_adapter=args.ip_adapter, clip_vision=args.clip_vision,
                ip_scale=0.0, filename_prefix=f"{args.filename_prefix}/{shot_id}",
            )
            mode = "flux_ipadapter_zero_scale_text_insert"

        workflow_path = workflow_dir / f"{shot_id}.api.json"
        workflow_path.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
        response = request_json(f"{args.base_url}/prompt", {"prompt": graph, "client_id": client_id})
        prompt_id = response["prompt_id"]
        print(f"queued {shot_id}: {prompt_id}", flush=True)
        history = wait_history(args.base_url, prompt_id, args.timeout_seconds)
        source = saved_image(history, args.comfy_output.resolve())
        if not source.is_file():
            raise FileNotFoundError(source)
        shutil.copy2(source, destination)
        report.append({
            "id": shot_id, "status": "generated", "mode": mode, "primary_character": primary,
            "prompt_id": prompt_id, "source": str(source), "output": str(destination), "seed": seed,
            "ip_scale": float(shot.get("ip_scale", 0.0)) if primary else None,
        })
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"generated {shot_id}: {destination}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
