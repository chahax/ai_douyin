from __future__ import annotations

import argparse
import json
import shutil
import time
import urllib.request
import uuid
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_DIR = PROJECT_ROOT / "data" / "qa" / "wenshu_lawyer_brand_v1"

SHOTS = [
    {
        "id": "01", "character": "zhouning", "length": 129,
        "motion": "She starts seated upright with both hands fully visible on the desk. She looks down at one plain paper transfer record, raises it slowly to mid-chest with her right hand while her left hand remains flat on the desk, then looks directly into the camera and ends holding the paper steadily. Medium motion, normal speed.",
    },
    {
        "id": "02", "character": "zhouning", "length": 97,
        "motion": "She starts facing the camera with both hands resting apart on the desk. She leans forward by only three centimeters, raises her right hand to chest height and makes one restrained pinch gesture to emphasize a legal distinction, then lowers the hand and ends with calm direct eye contact. Small motion, normal speed.",
    },
    {
        "id": "03", "character": "xuan", "length": 97,
        "motion": "She starts seated at the desk, left hand holding a plain folder and right hand beside the keyboard. She presses two keys with the right index finger, slides the folder ten centimeters toward herself, writes one short note with a pen, and ends reviewing the note. Medium motion, normal speed. The monitor content is not visible to camera.",
    },
    {
        "id": "04", "character": "gucheng", "length": 97,
        "motion": "He starts holding a plain case folder at lower chest height with both hands fully visible. He opens it once, traces one short line on the page with his right index finger, gives one restrained nod, closes the folder halfway, and ends looking at the camera. Small motion, normal speed.",
    },
    {
        "id": "05", "character": "zhouning", "length": 129,
        "motion": "She starts seated upright with a plain transfer slip flat on the desk. She lifts the slip with her left hand, points once to the lower half with her right index finger, turns the slip slightly toward herself rather than toward the camera, places it back on the desk, and ends with both hands visible. Medium motion, normal speed. No readable document text.",
    },
    {
        "id": "06", "character": "xuan", "length": 97,
        "motion": "She starts with four plain evidence cards spread on the desk and both hands visible. Using her right hand, she slides the cards into one neat row from left to right, taps the row once with the pen, folds both hands lightly beside the cards, and ends looking up. Medium motion, normal speed. No readable text.",
    },
    {
        "id": "07", "character": "gucheng", "length": 97,
        "motion": "He starts with a closed case folder resting on the desk. He opens the folder, taps three different blank tabs in sequence with his right index finger, turns his gaze from the folder to the camera, and ends with one calm nod. Small motion, normal speed.",
    },
    {
        "id": "08", "character": "zhouning", "length": 129,
        "motion": "She starts with a notebook open on the desk and a pen in her right hand. She draws one short line, moves the pen first to the left option and then to the right option, opens her left palm in a restrained explanatory gesture, sets the pen down, and ends with both hands visible. Medium motion, normal speed.",
    },
    {
        "id": "09", "character": "zhouning", "length": 97,
        "motion": "She starts with both hands lightly clasped on the desk. She separates them slowly with both palms angled inward to show balanced risks, holds for one second, brings them back to rest, and ends with a firm professional gaze. Small motion, normal speed.",
    },
    {
        "id": "10", "character": "zhouning", "length": 97,
        "motion": "She starts seated upright with both hands resting on either side of a closed plain folder. She gives one small nod, gently closes the folder with her right hand, places that hand back on the desk, and ends completely still with direct eye contact. Small motion, normal speed.",
    },
]

NEGATIVE = (
    "identity change, different face, face morphing, hairstyle change, clothing change, jewelry change, "
    "extra person, duplicate body, third hand, extra arm, missing fingers, fused fingers, malformed hands, "
    "hands leaving the frame, floating paper, readable generated text, fake website UI, phone screen, laptop screen facing camera, "
    "exaggerated mouth movement, frozen open mouth, teeth distortion, large head turn, fast movement, repeated motion, "
    "camera shake, zoom jump, scene cut, flicker, exposure pumping, overexposure, watermark, subtitle"
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
        history = request_json(f"{base_url}/history/{prompt_id}")
        if prompt_id in history:
            item = history[prompt_id]
            if item.get("status", {}).get("status_str") == "error":
                raise RuntimeError(json.dumps(item.get("status"), ensure_ascii=False))
            return item
        time.sleep(3)
    raise TimeoutError(prompt_id)


def workflow(image_name: str, motion: str, seed: int, length: int, prefix: str) -> dict:
    positive = (
        "Premium cinematic Chinese law firm advertisement, photorealistic professional office. "
        "Preserve the exact input person's identity, facial structure, age, hairstyle, suit, shirt, jewelry, body proportions, "
        "desk, office lighting and vertical composition. Locked camera, stable exposure. Exactly one person and exactly two hands. "
        + motion
    )
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": r"LTX2\ltx-2.3-22b-distilled-1.1_transformer_only_fp8_scaled.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "ModelSamplingLTXV", "inputs": {"model": ["1", 0], "max_shift": 2.05, "base_shift": 0.95, "latent": ["9", 2]}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": r"LTX-Kijai\LTX23_video_vae_bf16.safetensors"}},
        "4": {"class_type": "LTXAVTextEncoderLoader", "inputs": {"text_encoder": "gemma_3_12B_it.safetensors", "ckpt_name": "ltx-2.3-text-proj-only.safetensors", "device": "default"}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 0], "text": positive}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 0], "text": NEGATIVE}},
        "7": {"class_type": "LTXVConditioning", "inputs": {"positive": ["5", 0], "negative": ["6", 0], "frame_rate": 25.0}},
        "8": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "9": {"class_type": "LTXVImgToVideo", "inputs": {"positive": ["7", 0], "negative": ["7", 1], "vae": ["3", 0], "image": ["8", 0], "width": 704, "height": 1248, "length": length, "batch_size": 1, "strength": 0.94}},
        "10": {"class_type": "KSampler", "inputs": {"model": ["2", 0], "positive": ["9", 0], "negative": ["9", 1], "latent_image": ["9", 2], "seed": seed, "steps": 8, "cfg": 1.0, "sampler_name": "euler_ancestral_cfg_pp", "scheduler": "simple", "denoise": 1.0}},
        "11": {"class_type": "LTXVTiledVAEDecode", "inputs": {"vae": ["3", 0], "latents": ["10", 0], "horizontal_tiles": 1, "vertical_tiles": 2, "overlap": 2, "last_frame_fix": False, "working_device": "auto", "working_dtype": "auto"}},
        "12": {"class_type": "CreateVideo", "inputs": {"images": ["11", 0], "fps": 25.0}},
        "13": {"class_type": "SaveVideo", "inputs": {"video": ["12", 0], "filename_prefix": prefix, "format": "mp4", "codec": "h264"}},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8190")
    parser.add_argument("--comfy-input", type=Path, default=Path(r"D:\IT\AI_vido\ComfyUI\input"))
    parser.add_argument("--comfy-output", type=Path, default=Path(r"D:\IT\AI_vido\ComfyUI\output"))
    parser.add_argument("--only", action="append")
    parser.add_argument("--timeout", type=int, default=7200)
    args = parser.parse_args()

    clips_dir = PROJECT_DIR / "clips_ltx"
    workflows_dir = PROJECT_DIR / "workflows_ltx"
    clips_dir.mkdir(parents=True, exist_ok=True)
    workflows_dir.mkdir(parents=True, exist_ok=True)
    report_path = PROJECT_DIR / "ltx_run_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else []

    for index, shot in enumerate(SHOTS):
        if args.only and shot["id"] not in args.only:
            continue
        source = PROJECT_DIR / "characters" / f"{shot['character']}_master.png"
        input_name = f"wenshu_{shot['character']}_{shot['id']}.png"
        shutil.copy2(source, args.comfy_input / input_name)
        prefix = f"wenshu_lawyer_brand_v1/{shot['id']}"
        graph = workflow(input_name, shot["motion"], 826200 + index * 37, shot["length"], prefix)
        (workflows_dir / f"{shot['id']}.api.json").write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
        output_dir = args.comfy_output / "wenshu_lawyer_brand_v1"
        before = {path.resolve() for path in output_dir.glob(f"{shot['id']}*.mp4")} if output_dir.exists() else set()
        response = request_json(f"{args.base_url}/prompt", {"prompt": graph, "client_id": str(uuid.uuid4())})
        prompt_id = response["prompt_id"]
        print(f"QUEUED {shot['id']} {shot['character']} length={shot['length']} prompt_id={prompt_id}", flush=True)
        wait_history(args.base_url, prompt_id, args.timeout)
        candidates = [path for path in output_dir.glob(f"{shot['id']}*.mp4") if path.resolve() not in before]
        if not candidates:
            candidates = list(output_dir.glob(f"{shot['id']}*.mp4"))
        if not candidates:
            raise FileNotFoundError(f"No ComfyUI output found for shot {shot['id']}")
        generated = max(candidates, key=lambda path: path.stat().st_mtime)
        destination = clips_dir / f"{shot['id']}.mp4"
        shutil.copy2(generated, destination)
        report.append({"id": shot["id"], "character": shot["character"], "length": shot["length"], "prompt_id": prompt_id, "source": str(generated), "output": str(destination)})
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"DONE {shot['id']} -> {destination}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
