from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AKI_COMFY = ROOT / r"data\tools\aki_v2_runtime\ComfyUI-aki-v2\ComfyUI"
DEFAULT_ANCHOR = (
    ROOT
    / r"data\qa\reference_404263_multiflow_20260825\anchors\s04_escalation.png"
)
DEFAULT_OUTPUT = ROOT / r"data\qa\reference_404263_aki_v2_20260825\smoke"


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
        with urllib.request.urlopen(request, timeout=60) as response:
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
                messages = status.get("messages", [])
                raise RuntimeError(f"ComfyUI execution failed: {messages}")
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
    profile: str,
) -> dict:
    if profile == "b2_fake_illness":
        positive = (
            "Photorealistic vertical Chinese crime microdrama. A young adult woman lies "
            "naturally on her side on a messy bed, slowly opens her eyes, raises one hand "
            "toward her forehead to perform restrained weakness for an off-camera phone, then "
            "looks toward that phone. One coherent action, natural breathing and weight, "
            "stable face, stable hands, stable bed and props, locked camera."
        )
        negative = (
            "extra person, extra legs, feet near camera, identity drift, instant expression "
            "flip, phone disappearance, missing screen, extra phone, extra arms, fused hands, "
            "malformed fingers, floating prop, crouching, half squat, frozen legs, bed "
            "deformation, camera shake, zoom, scene cut, flicker, morphing, readable text, "
            "subtitle, logo, watermark, cartoon, anime"
        )
    else:
        positive = (
            "Photorealistic Chinese crime microdrama, fixed vertical medium two-shot in a "
            "cramped cyan-lit office. A Chinese woman in a black blazer naturally passes one "
            "plain unbranded smartphone into a Chinese man's open hand at lower chest height. "
            "Both remain standing upright; the receiver closes his fingers around the phone, "
            "then the giver releases it. One simple slow handoff, restrained body motion, stable "
            "faces, stable room geometry, locked camera, realistic hands and eyelines."
        )
        negative = (
            "phone near face, phone disappearing, extra phone, extra arms, fused hands, malformed "
            "fingers, crouching, half squat, bent knees, looking at watch, dramatic gesture, camera "
            "shake, zoom, scene cut, flicker, morphing, readable text, logo, watermark, cartoon, anime"
        )
    return {
        "1": {
            "class_type": "CLIPLoader",
            "inputs": {
                "clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
                "type": "wan",
                "device": "default",
            },
        },
        "2": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 0], "text": positive}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 0], "text": negative}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": "wan2.2_vae.safetensors"}},
        "5": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "8": {
            "class_type": "Wan22ImageToVideoLatent",
            "inputs": {
                "vae": ["4", 0],
                "width": width,
                "height": height,
                "length": length,
                "batch_size": 1,
                "start_image": ["5", 0],
            },
        },
        "9": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": "wan2.2_ti2v_5B_fp16.safetensors",
                "weight_dtype": "default",
            },
        },
        "15": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["9", 0], "shift": 8.0}},
        "10": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["15", 0],
                "seed": seed,
                "steps": steps,
                "cfg": 5.0,
                "sampler_name": "uni_pc",
                "scheduler": "simple",
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["8", 0],
                "denoise": 1.0,
            },
        },
        "12": {"class_type": "VAEDecode", "inputs": {"samples": ["10", 0], "vae": ["4", 0]}},
        "13": {"class_type": "CreateVideo", "inputs": {"images": ["12", 0], "fps": 16.0}},
        "14": {
            "class_type": "SaveVideo",
            "inputs": {
                "video": ["13", 0],
                "filename_prefix": prefix,
                "format": "mp4",
                "codec": "h264",
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8191")
    parser.add_argument("--anchor", type=Path, default=DEFAULT_ANCHOR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=825401)
    parser.add_argument("--width", type=int, default=320)
    parser.add_argument("--height", type=int, default=576)
    parser.add_argument("--length", type=int, default=49)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument(
        "--profile",
        choices=("s04_handoff", "b2_fake_illness"),
        default="s04_handoff",
    )
    parser.add_argument("--timeout", type=int, default=7200)
    args = parser.parse_args()

    anchor = args.anchor.resolve()
    output_dir = args.output_dir.resolve()
    if not anchor.is_file():
        raise FileNotFoundError(anchor)
    if args.length < 17 or (args.length - 1) % 4 != 0:
        raise ValueError("Wan frame length must be 4n+1 and at least 17")

    aki_input = AKI_COMFY / "input"
    aki_output = AKI_COMFY / "output"
    if not aki_input.is_dir() or not aki_output.is_dir():
        raise FileNotFoundError("Aki ComfyUI input/output directories are unavailable")
    output_dir.mkdir(parents=True, exist_ok=True)

    token = uuid.uuid4().hex[:8]
    image_name = f"aki_v2_s04_{token}.png"
    shutil.copy2(anchor, aki_input / image_name)
    prefix = f"aki_v2_smoke/{args.profile}_{token}"
    workflow = graph(
        image_name=image_name,
        prefix=prefix,
        seed=args.seed,
        width=args.width,
        height=args.height,
        length=args.length,
        steps=args.steps,
        profile=args.profile,
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

    candidates: list[Path] = []
    for node_output in history.get("outputs", {}).values():
        for video in node_output.get("videos", []):
            filename = str(video.get("filename") or "")
            subfolder = str(video.get("subfolder") or "")
            path = aki_output / subfolder / filename
            if path.is_file():
                candidates.append(path)
    if not candidates:
        candidates = list((aki_output / "aki_v2_smoke").glob(f"{args.profile}_{token}*.mp4"))
    if not candidates:
        raise FileNotFoundError("Aki ComfyUI saved no video")
    source = max(candidates, key=lambda path: path.stat().st_mtime)
    output_name = (
        "aki_v2_b2_fake_illness_smoke.mp4"
        if args.profile == "b2_fake_illness"
        else "aki_v2_s04_escalation_smoke.mp4"
    )
    destination = output_dir / output_name
    shutil.copy2(source, destination)

    system_stats = request_json(f"{args.base_url}/system_stats")
    report = {
        "schema": "aki_v2_video_smoke/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending_manual_review",
        "runtime": "ComfyUI-aki-v2 independent extracted runtime",
        "runtime_source_archive": r"C:\Users\c\Downloads\ComfyUI-aki-v2.7z",
        "runtime_comfyui_version": system_stats.get("system", {}).get("comfyui_version"),
        "runtime_python_version": system_stats.get("system", {}).get("python_version"),
        "runtime_pytorch_version": system_stats.get("system", {}).get("pytorch_version"),
        "workflow_kind": "native Wan2.2 5B I2V run inside Aki runtime",
        "prompt_profile": args.profile,
        "aki_specific_move_or_mix_workflow_used": False,
        "aki_user_workflow_available": False,
        "model": "wan2.2_ti2v_5B_fp16.safetensors",
        "anchor_path": str(anchor),
        "anchor_sha256": sha256(anchor),
        "workflow_path": str(workflow_path),
        "workflow_sha256": sha256(workflow_path),
        "prompt_id": prompt_id,
        "seed": args.seed,
        "steps": args.steps,
        "width": args.width,
        "height": args.height,
        "length": args.length,
        "fps": 16.0,
        "video_path": str(destination),
        "video_sha256": sha256(destination),
        "comfy_output_source": str(source),
        "publish_allowed": False,
        "douyin_upload_allowed": False,
        "fanqie_backfill_allowed": False,
    }
    report_path = output_dir / "smoke.report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"event": "complete", "video": str(destination), "report": str(report_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
