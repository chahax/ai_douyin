from __future__ import annotations

import json
import shutil
import time
import urllib.request
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "data" / "qa" / "wenshu_lawyer_brand_v1"
OUT = PROJECT / "v2_debate"
COMFY_INPUT = Path(r"D:\IT\AI_vido\ComfyUI\input")
COMFY_OUTPUT = Path(r"D:\IT\AI_vido\ComfyUI\output")
BASE = "http://127.0.0.1:8190"


SHOTS = [
    {
        "id": "r_zhou_listen",
        "image": OUT / "characters" / "zhouning_side.png",
        "motion": "She begins listening toward screen left with her mouth closed. She shifts her gaze toward the other lawyer, turns her head by only six degrees, gives one restrained nod, then returns to a composed listening pose. Hands remain completely outside frame. Small motion, normal speed.",
    },
    {
        "id": "r_gu_gesture",
        "image": PROJECT / "characters" / "gucheng_master.png",
        "motion": "He begins seated upright with both hands resting separately and fully visible on the desk. His left hand stays completely still. He lifts only his right hand eight centimeters with fingers naturally together, makes one short downward emphasis without touching any object, then returns the right hand to its original resting position. Medium-small motion, brisk normal speed.",
    },
    {
        "id": "r_xu_counter",
        "image": OUT / "characters" / "xuan_side.png",
        "motion": "She begins listening with mouth closed. She leans forward by three centimeters, slightly raises her eyebrows, turns her gaze toward screen right, gives one small skeptical nod, and ends ready to respond. Hands remain completely outside frame. Small motion, normal speed.",
    },
]


NEGATIVE = (
    "identity change, face morphing, different person, hairstyle change, clothing change, extra person, "
    "duplicate body, third hand, extra arm, missing fingers, fused fingers, malformed hands, moving left hand, "
    "holding object, pen, paper, phone, laptop interaction, readable text, talking, open mouth, exaggerated expression, "
    "large head turn, repeated action, fast hand motion, camera shake, scene cut, flicker, exposure change, watermark, subtitle"
)


def request_json(url: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=120) as response:
        return json.loads(response.read())


def wait(prompt_id: str, timeout: int = 3600) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        history = request_json(f"{BASE}/history/{prompt_id}")
        if prompt_id in history:
            status = history[prompt_id].get("status", {})
            if status.get("status_str") == "error":
                raise RuntimeError(json.dumps(status, ensure_ascii=False))
            return
        time.sleep(3)
    raise TimeoutError(prompt_id)


def graph(image_name: str, motion: str, seed: int, prefix: str) -> dict:
    positive = (
        "Premium cinematic Chinese law firm roundtable, photorealistic. Preserve the exact input identity, face, age, hairstyle, suit, shirt, accessories, body proportions, office and lighting. Stable eye-level camera and exposure. "
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
        "9": {"class_type": "LTXVImgToVideo", "inputs": {"positive": ["7", 0], "negative": ["7", 1], "vae": ["3", 0], "image": ["8", 0], "width": 704, "height": 1248, "length": 65, "batch_size": 1, "strength": 0.92}},
        "10": {"class_type": "KSampler", "inputs": {"model": ["2", 0], "positive": ["9", 0], "negative": ["9", 1], "latent_image": ["9", 2], "seed": seed, "steps": 8, "cfg": 1.0, "sampler_name": "euler_ancestral_cfg_pp", "scheduler": "simple", "denoise": 1.0}},
        "11": {"class_type": "LTXVTiledVAEDecode", "inputs": {"vae": ["3", 0], "latents": ["10", 0], "horizontal_tiles": 1, "vertical_tiles": 2, "overlap": 2, "last_frame_fix": False, "working_device": "auto", "working_dtype": "auto"}},
        "12": {"class_type": "CreateVideo", "inputs": {"images": ["11", 0], "fps": 25.0}},
        "13": {"class_type": "SaveVideo", "inputs": {"video": ["12", 0], "filename_prefix": prefix, "format": "mp4", "codec": "h264"}},
    }


def main() -> int:
    output = OUT / "reactions_ltx"
    workflows = OUT / "workflows_reactions_ltx"
    output.mkdir(parents=True, exist_ok=True)
    workflows.mkdir(parents=True, exist_ok=True)
    report = []
    for i, shot in enumerate(SHOTS):
        input_name = f"wenshu_v2_{shot['id']}.png"
        shutil.copy2(shot["image"], COMFY_INPUT / input_name)
        prefix = f"wenshu_lawyer_debate_v2/{shot['id']}"
        workflow = graph(input_name, shot["motion"], 931700 + i * 137, prefix)
        (workflows / f"{shot['id']}.api.json").write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8")
        response = request_json(f"{BASE}/prompt", {"prompt": workflow, "client_id": str(uuid.uuid4())})
        prompt_id = response["prompt_id"]
        print(f"QUEUED {shot['id']} {prompt_id}", flush=True)
        wait(prompt_id)
        candidates = list((COMFY_OUTPUT / "wenshu_lawyer_debate_v2").glob(f"{shot['id']}*.mp4"))
        if not candidates:
            raise FileNotFoundError(shot["id"])
        source = max(candidates, key=lambda p: p.stat().st_mtime)
        destination = output / f"{shot['id']}.mp4"
        shutil.copy2(source, destination)
        report.append({"id": shot["id"], "prompt_id": prompt_id, "source": str(source), "output": str(destination)})
        (OUT / "reactions_ltx_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"DONE {shot['id']} -> {destination}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
