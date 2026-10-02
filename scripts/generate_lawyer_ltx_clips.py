from __future__ import annotations

import argparse
import json
import shutil
import time
import urllib.request
import uuid
from pathlib import Path


MOTIONS = {
    "01_verdict": "The visible lawyer listens to the judge off screen. He remains upright and nearly still, completes one slow natural blink, moves only his eyes toward the bench, tightens his jaw slightly, and takes one restrained breath. No visible speaking.",
    "02_mother": "The grieving woman speaks one emotional sentence toward the judge with small natural mouth movements. Her eyebrows tense, her fingers tighten around the wooden rail, and her shoulders rise slightly with one breath. She never waves her arms or turns away.",
    "03_observation": "The lawyer silently studies the defendant. His gaze shifts slightly across frame, his eyes narrow by a small amount, he completes one slow blink, and then holds completely still. His lips remain closed.",
    "04_report": "The lawyer speaks calmly and decisively with restrained natural mouth movement. He lifts the case file only two centimeters, gives one small nod, and keeps both hands, file and body stable.",
    "05_twin": "The escorted twin and bailiff take one slow controlled step forward through the doorway. The foreground defendant turns his head slightly in shock. Clothing, faces and doorway remain stable.",
    "06_reveal": "The lawyer delivers a decisive accusation with restrained natural mouth movement. His head stays nearly still; his lower jaw and lips move subtly, he completes one slow blink, and ends with firm eye contact and closed lips.",
}


NEGATIVE = (
    "identity change, different face, face morphing, stretched neck, long neck, rubber face, warped mouth, "
    "extra teeth, open mouth frozen, exaggerated lip movement, hairstyle change, clothing change, extra person, "
    "extra limbs, malformed hands, large motion, fast motion, head spinning, camera movement, zoom, pan, tilt, "
    "camera shake, refocus, background change, flicker, exposure pumping, scene cut, text, watermark"
)


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


def graph(image_name: str, prompt: str, seed: int, length: int, prefix: str) -> dict:
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": r"LTX2\ltx-2.3-22b-distilled-1.1_transformer_only_fp8_scaled.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "ModelSamplingLTXV", "inputs": {"model": ["1", 0], "max_shift": 2.05, "base_shift": 0.95, "latent": ["9", 2]}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": r"LTX-Kijai\LTX23_video_vae_bf16.safetensors"}},
        "4": {"class_type": "LTXAVTextEncoderLoader", "inputs": {"text_encoder": "gemma_3_12B_it.safetensors", "ckpt_name": "ltx-2.3-text-proj-only.safetensors", "device": "default"}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 0], "text": "High-end semi-realistic Chinese 3D animated legal suspense drama. Preserve the exact input character identity, face, hair, clothing, courtroom composition, lighting and color. Locked camera. " + prompt}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 0], "text": NEGATIVE}},
        "7": {"class_type": "LTXVConditioning", "inputs": {"positive": ["5", 0], "negative": ["6", 0], "frame_rate": 25.0}},
        "8": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "9": {"class_type": "LTXVImgToVideo", "inputs": {"positive": ["7", 0], "negative": ["7", 1], "vae": ["3", 0], "image": ["8", 0], "width": 704, "height": 1248, "length": length, "batch_size": 1, "strength": 0.92}},
        "10": {"class_type": "KSampler", "inputs": {"model": ["2", 0], "positive": ["9", 0], "negative": ["9", 1], "latent_image": ["9", 2], "seed": seed, "steps": 8, "cfg": 1.0, "sampler_name": "euler_ancestral_cfg_pp", "scheduler": "simple", "denoise": 1.0}},
        "11": {"class_type": "LTXVTiledVAEDecode", "inputs": {"vae": ["3", 0], "latents": ["10", 0], "horizontal_tiles": 1, "vertical_tiles": 2, "overlap": 2, "last_frame_fix": False, "working_device": "auto", "working_dtype": "auto"}},
        "12": {"class_type": "CreateVideo", "inputs": {"images": ["11", 0], "fps": 25.0}},
        "13": {"class_type": "SaveVideo", "inputs": {"video": ["12", 0], "filename_prefix": prefix, "format": "mp4", "codec": "h264"}},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    parser.add_argument("--only", action="append")
    parser.add_argument("--base-url", default="http://127.0.0.1:8190")
    parser.add_argument("--comfy-input", default=r"D:\IT\AI_vido\ComfyUI\input")
    parser.add_argument("--comfy-output", default=r"D:\IT\AI_vido\ComfyUI\output")
    parser.add_argument("--timeout", type=int, default=7200)
    parser.add_argument("--length", type=int, default=65)
    args = parser.parse_args()

    project_path = Path(args.project).resolve()
    project = json.loads(project_path.read_text(encoding="utf-8"))
    root = project_path.parent
    clean_dir = root / "keyframes_clean"
    clips_dir = root / "clips_ltx"
    workflows_dir = root / "ltx_workflows"
    clips_dir.mkdir(exist_ok=True)
    workflows_dir.mkdir(exist_ok=True)
    input_root = Path(args.comfy_input)
    output_root = Path(args.comfy_output)
    report_path = root / "ltx_run_report.json"
    report: list[dict] = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else []

    for index, shot in enumerate(project["shots"]):
        shot_id = shot["id"]
        if args.only and shot_id not in args.only:
            continue
        source = clean_dir / f"{shot_id}.png"
        if not source.exists():
            raise FileNotFoundError(source)
        image_name = f"lawyer_ltx_{shot_id}.png"
        shutil.copy2(source, input_root / image_name)
        prefix = f"lawyer_reference_style_v1_ltx/{shot_id}"
        workflow = graph(image_name, MOTIONS[shot_id], 819000 + index, args.length, prefix)
        (workflows_dir / f"{shot_id}.api.json").write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8")
        output_dir = output_root / "lawyer_reference_style_v1_ltx"
        before = {p.resolve() for p in output_dir.glob(f"{shot_id}*.mp4")} if output_dir.exists() else set()
        response = request_json(f"{args.base_url}/prompt", {"prompt": workflow, "client_id": str(uuid.uuid4())})
        prompt_id = response["prompt_id"]
        print(f"queued {shot_id}: {prompt_id}", flush=True)
        wait_history(args.base_url, prompt_id, args.timeout)
        candidates = [p for p in output_dir.glob(f"{shot_id}*.mp4") if p.resolve() not in before]
        if not candidates:
            candidates = list(output_dir.glob(f"{shot_id}*.mp4"))
        if not candidates:
            raise FileNotFoundError(f"ComfyUI did not save {shot_id} mp4")
        generated = max(candidates, key=lambda p: p.stat().st_mtime)
        destination = clips_dir / f"{shot_id}.mp4"
        shutil.copy2(generated, destination)
        report.append({"id": shot_id, "prompt_id": prompt_id, "source": str(generated), "output": str(destination), "length": args.length})
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"generated {shot_id}: {destination}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
