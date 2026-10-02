from __future__ import annotations

import argparse
import json
import shutil
import time
import urllib.request
import uuid
from pathlib import Path


MOTIONS = {
    "01_verdict": "The lawyer remains standing in the courtroom and listens to an off-screen judge. He completes one slow blink, turns his eyes slightly toward the judge, and tightens his jaw. Very small controlled motion, locked camera, no speech from the visible man.",
    "02_mother": "The grieving woman speaks one emotional sentence toward the judge. Her lips move naturally, eyebrows tense, and the hand gripping the rail tightens slightly. Her head and shoulders move only a little. Locked camera, restrained courtroom acting.",
    "03_observation": "The lawyer silently studies the defendant. He shifts his gaze from left to right, narrows his eyes slightly, then becomes still. Subtle breathing and one natural blink, locked camera, no speech.",
    "04_report": "The lawyer speaks calmly while holding the case file at his chest. His lips move naturally, he raises the file by only a few centimeters and gives one small decisive nod. Hands and file remain stable, locked camera.",
    "05_twin": "The bailiff and escorted twin take one slow step into the courtroom while the defendant foreground silhouette turns his head in shock. Small believable movement, stable faces and uniforms, bright doorway light remains constant, locked camera.",
    "06_reveal": "The lawyer delivers one decisive accusation with restrained natural lip movement. His head remains nearly still; only his mouth, eyes and jaw move. He completes one slow blink and ends with firm eye contact. Locked camera, no scene change.",
}


NEGATIVE = (
    "face morphing, identity change, hairstyle change, clothing change, rubber face, warped mouth, "
    "exaggerated lip movement, extra teeth, deformed eyes, extra fingers, extra limbs, duplicated people, "
    "fast motion, large head turn, dancing, camera shake, pan, tilt, zoom, scene cut, flicker, exposure pumping, "
    "text, subtitles, watermark, logo"
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


def graph(image_name: str, prompt: str, seed: int, prefix: str) -> dict:
    return {
        "1": {"class_type": "CLIPLoader", "inputs": {"clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "type": "wan", "device": "default"}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 0], "text": "High-end semi-realistic Chinese 3D animated legal suspense drama. Preserve the exact input frame, character identity, face, hair, clothing, courtroom architecture, composition and lighting. " + prompt}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 0], "text": NEGATIVE}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": "wan2.2_vae.safetensors"}},
        "5": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "6": {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": "clip_vision_h.safetensors"}},
        "7": {"class_type": "CLIPVisionEncode", "inputs": {"clip_vision": ["6", 0], "image": ["5", 0], "crop": "none"}},
        "8": {"class_type": "WanFirstLastFrameToVideo", "inputs": {"positive": ["2", 0], "negative": ["3", 0], "vae": ["4", 0], "width": 416, "height": 736, "length": 49, "batch_size": 1, "clip_vision_start_image": ["7", 0], "clip_vision_end_image": ["7", 0], "start_image": ["5", 0], "end_image": ["5", 0]}},
        "9": {"class_type": "UNETLoader", "inputs": {"unet_name": "wan2.2_ti2v_5B_fp16.safetensors", "weight_dtype": "default"}},
        "10": {"class_type": "KSamplerAdvanced", "inputs": {"model": ["9", 0], "positive": ["8", 0], "negative": ["8", 1], "latent_image": ["8", 2], "add_noise": "enable", "noise_seed": seed, "steps": 4, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "start_at_step": 0, "end_at_step": 2, "return_with_leftover_noise": "enable"}},
        "11": {"class_type": "KSamplerAdvanced", "inputs": {"model": ["9", 0], "positive": ["8", 0], "negative": ["8", 1], "latent_image": ["10", 0], "add_noise": "disable", "noise_seed": seed, "steps": 4, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "start_at_step": 2, "end_at_step": 4, "return_with_leftover_noise": "disable"}},
        "12": {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["4", 0]}},
        "13": {"class_type": "CreateVideo", "inputs": {"images": ["12", 0], "fps": 16.0}},
        "14": {"class_type": "SaveVideo", "inputs": {"video": ["13", 0], "filename_prefix": prefix, "format": "mp4", "codec": "h264"}},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project")
    parser.add_argument("--only", action="append")
    parser.add_argument("--base-url", default="http://127.0.0.1:8190")
    parser.add_argument("--comfy-input", default=r"D:\IT\AI_vido\ComfyUI\input")
    parser.add_argument("--comfy-output", default=r"D:\IT\AI_vido\ComfyUI\output")
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args()

    project_path = Path(args.project).resolve()
    project = json.loads(project_path.read_text(encoding="utf-8"))
    root = project_path.parent
    clean_dir = root / "keyframes_clean"
    clips_dir = root / "clips_raw"
    workflows_dir = root / "video_workflows"
    clips_dir.mkdir(exist_ok=True)
    workflows_dir.mkdir(exist_ok=True)
    input_root = Path(args.comfy_input)
    output_root = Path(args.comfy_output)
    report: list[dict] = []

    for index, shot in enumerate(project["shots"]):
        shot_id = shot["id"]
        if args.only and shot_id not in args.only:
            continue
        source = clean_dir / f"{shot_id}.png"
        if not source.is_file():
            raise FileNotFoundError(source)
        image_name = f"lawyer_reference_style_v1_{shot_id}.png"
        shutil.copy2(source, input_root / image_name)
        prefix = f"lawyer_reference_style_v1_video/{shot_id}"
        workflow = graph(image_name, MOTIONS[shot_id], 818000 + index, prefix)
        (workflows_dir / f"{shot_id}.api.json").write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8")
        before = {p.resolve() for p in (output_root / "lawyer_reference_style_v1_video").glob(f"{shot_id}*.mp4")} if (output_root / "lawyer_reference_style_v1_video").exists() else set()
        response = request_json(f"{args.base_url}/prompt", {"prompt": workflow, "client_id": str(uuid.uuid4())})
        prompt_id = response["prompt_id"]
        print(f"queued {shot_id}: {prompt_id}", flush=True)
        wait_history(args.base_url, prompt_id, args.timeout)
        candidates = [p for p in (output_root / "lawyer_reference_style_v1_video").glob(f"{shot_id}*.mp4") if p.resolve() not in before]
        if not candidates:
            candidates = list((output_root / "lawyer_reference_style_v1_video").glob(f"{shot_id}*.mp4"))
        if not candidates:
            raise FileNotFoundError(f"ComfyUI did not save {shot_id} mp4")
        generated = max(candidates, key=lambda p: p.stat().st_mtime)
        destination = clips_dir / f"{shot_id}.mp4"
        shutil.copy2(generated, destination)
        report.append({"id": shot_id, "prompt_id": prompt_id, "source": str(generated), "output": str(destination)})
        (root / "video_run_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"generated {shot_id}: {destination}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
