from __future__ import annotations

import argparse
import json
import shutil
import time
import urllib.request
import uuid
from pathlib import Path


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}


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
                raise RuntimeError(json.dumps(result["status"], ensure_ascii=False))
            return result
        time.sleep(2)
    raise TimeoutError(f"ComfyUI prompt timed out: {prompt_id}")


def saved_video(history: dict, output_root: Path) -> Path:
    for output in history.get("outputs", {}).values():
        for collection in ("gifs", "videos", "images"):
            for item in output.get(collection, []):
                filename = item.get("filename", "")
                if item.get("type") == "output" and Path(filename).suffix.lower() in VIDEO_EXTENSIONS:
                    return output_root / item.get("subfolder", "") / filename
    raise RuntimeError("ComfyUI history did not contain a saved video")


def workflow(
    *,
    input_video: str,
    source_fps: int,
    multiplier: int,
    model_name: str,
    filename_prefix: str,
    crf: int,
) -> dict:
    return {
        "1": {
            "class_type": "VHS_LoadVideo",
            "inputs": {
                "video": input_video,
                "force_rate": source_fps,
                "custom_width": 0,
                "custom_height": 0,
                "frame_load_cap": 0,
                "skip_first_frames": 0,
                "select_every_nth": 1,
                "force_size": "Disabled",
            },
        },
        "2": {
            "class_type": "FrameInterpolationModelLoader",
            "inputs": {"model_name": model_name},
        },
        "3": {
            "class_type": "FrameInterpolate",
            "inputs": {
                "interp_model": ["2", 0],
                "images": ["1", 0],
                "multiplier": multiplier,
            },
        },
        "4": {
            "class_type": "VHS_VideoCombine",
            "inputs": {
                "images": ["3", 0],
                "frame_rate": float(source_fps * multiplier),
                "loop_count": 0,
                "filename_prefix": filename_prefix,
                "format": "video/h264-mp4",
                "pingpong": False,
                "save_output": True,
                "pix_fmt": "yuv420p",
                "crf": crf,
                "save_metadata": True,
                "trim_to_audio": False,
            },
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Interpolate a named batch of ComfyUI input videos with RIFE."
    )
    parser.add_argument(
        "source_map",
        help=(
            "JSON object mapping output ids to ComfyUI input-relative video paths, "
            "for example {'shot01': 'project/shot01.mp4'}."
        ),
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8190")
    parser.add_argument("--comfy-output", default=r"D:\IT\AI_vido\ComfyUI\output")
    parser.add_argument("--source-fps", type=int, default=25)
    parser.add_argument("--multiplier", type=int, default=4)
    parser.add_argument("--model-name", default="rife_v4.26.safetensors")
    parser.add_argument("--crf", type=int, default=18)
    parser.add_argument("--filename-prefix", default="perfect_lover_v4_rife")
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    parser.add_argument("--only", action="append")
    parser.add_argument("--skip-existing", action="store_true")
    args = parser.parse_args()

    if args.source_fps <= 0:
        raise ValueError("--source-fps must be positive")
    if not 2 <= args.multiplier <= 16:
        raise ValueError("--multiplier must be between 2 and 16")
    if not 0 <= args.crf <= 51:
        raise ValueError("--crf must be between 0 and 51")

    source_map_path = Path(args.source_map).resolve()
    source_map = json.loads(source_map_path.read_text(encoding="utf-8"))
    if not isinstance(source_map, dict) or not source_map:
        raise ValueError("source map must be a non-empty JSON object")
    selected = set(args.only or source_map)
    unknown = selected.difference(source_map)
    if unknown:
        raise ValueError(f"unknown selected ids: {', '.join(sorted(unknown))}")

    output_dir = Path(args.output_dir).resolve()
    clip_dir = output_dir / "clips"
    workflow_dir = output_dir / "workflows"
    clip_dir.mkdir(parents=True, exist_ok=True)
    workflow_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "run_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else []
    client_id = str(uuid.uuid4())

    for item_id, input_video in source_map.items():
        if item_id not in selected:
            continue
        destination = clip_dir / f"{item_id}.mp4"
        if args.skip_existing and destination.is_file():
            print(f"skipped {item_id}", flush=True)
            continue
        graph = workflow(
            input_video=input_video,
            source_fps=args.source_fps,
            multiplier=args.multiplier,
            model_name=args.model_name,
            filename_prefix=f"{args.filename_prefix}/{item_id}",
            crf=args.crf,
        )
        workflow_path = workflow_dir / f"{item_id}.api.json"
        workflow_path.write_text(
            json.dumps(graph, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        started_at = time.time()
        response = request_json(
            f"{args.base_url}/prompt",
            {"prompt": graph, "client_id": client_id},
        )
        prompt_id = response["prompt_id"]
        print(f"queued {item_id}: {prompt_id}", flush=True)
        history = wait_history(args.base_url, prompt_id, args.timeout_seconds)
        source = saved_video(history, Path(args.comfy_output))
        if not source.is_file():
            raise FileNotFoundError(source)
        shutil.copy2(source, destination)
        entry = {
            "id": item_id,
            "status": "generated",
            "prompt_id": prompt_id,
            "input_video": input_video,
            "source": str(source),
            "output": str(destination),
            "source_fps": args.source_fps,
            "multiplier": args.multiplier,
            "output_fps": args.source_fps * args.multiplier,
            "elapsed_seconds": round(time.time() - started_at, 3),
        }
        report = [item for item in report if item.get("id") != item_id]
        report.append(entry)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"generated {item_id}: {destination}", flush=True)


if __name__ == "__main__":
    main()
