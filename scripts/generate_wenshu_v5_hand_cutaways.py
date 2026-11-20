from __future__ import annotations

import json
import shutil
import time
import urllib.request
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEBATE = ROOT / "data" / "qa" / "wenshu_lawyer_brand_v1" / "v2_debate"
PROJECT = DEBATE / "v4_case_conference"
CHARACTERS = ROOT / "data" / "qa" / "wenshu_lawyer_brand_v1" / "characters"
COMFY_INPUT = Path(r"D:\IT\AI_vido\ComfyUI\input")
COMFY_OUTPUT = Path(r"D:\IT\AI_vido\ComfyUI\output")
BASE = "http://127.0.0.1:8190"


SHOTS = [
    {
        "id": "h_zhou_align_note",
        "image": CHARACTERS / "zhouning_master.png",
        "motion": (
            "She listens with her mouth gently closed. Both natural hands remain fully visible on the desk. "
            "Her left hand stays relaxed and completely still. With only her right hand, she slides one plain "
            "blank note four centimeters toward the center, taps its upper edge once with her right index finger, "
            "then returns the right hand beside the note. Small controlled motion, normal speed."
        ),
    },
    {
        "id": "h_gu_open_folder",
        "image": CHARACTERS / "gucheng_master.png",
        "motion": (
            "He listens with his mouth closed. A single plain closed case folder lies centered on the desk and "
            "both natural hands are fully visible. His left hand holds the lower left corner still. His right hand "
            "lifts only the top cover, opens it halfway, pauses briefly, then lowers the cover and returns to rest. "
            "Small controlled motion, normal speed."
        ),
    },
    {
        "id": "h_xu_align_cards",
        "image": CHARACTERS / "xuan_master.png",
        "motion": (
            "She listens with her mouth gently closed. Exactly three plain blank evidence cards lie on the desk and "
            "both natural hands are fully visible. Her left hand stays flat and still. Her right hand slides only the "
            "nearest card three centimeters into line with the other two, releases it, then returns to its original "
            "resting place. Small controlled motion, normal speed."
        ),
    },
    {
        "id": "h_gu_balanced_palms",
        "image": CHARACTERS / "gucheng_master.png",
        "motion": (
            "He listens with his mouth closed and both natural hands resting separately on the desk. He raises both "
            "hands by only five centimeters, palms angled inward and fingers naturally together, makes one restrained "
            "balanced comparison gesture, then lowers both hands back to exactly their original resting positions. "
            "Small symmetrical motion, normal speed."
        ),
    },
]


NEGATIVE = (
    "identity change, face morphing, different person, hairstyle change, clothing change, extra person, "
    "duplicate body, third hand, extra hand, extra arm, missing hand, missing fingers, extra fingers, fused fingers, "
    "malformed hands, deformed wrists, crossed arms, floating object, duplicate object, readable document text, "
    "phone, computer screen, talking, open mouth, teeth, exaggerated expression, large head turn, repeated motion, "
    "fast hand motion, camera movement, camera shake, zoom, scene cut, flicker, exposure change, overexposure, "
    "watermark, subtitle"
)


def request_json(url: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read())


def wait(prompt_id: str, timeout: int = 3600) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        history = request_json(f"{BASE}/history/{prompt_id}")
        if prompt_id in history:
            status = history[prompt_id].get("status", {})
            if status.get("status_str") == "error":
                raise RuntimeError(json.dumps(status, ensure_ascii=False))
            return history[prompt_id]
        time.sleep(3)
    raise TimeoutError(prompt_id)


def graph(image_name: str, motion: str, seed: int, prefix: str) -> dict:
    positive = (
        "Photorealistic internal Chinese law firm case conference. Preserve the exact input identity, facial "
        "structure, age, hairstyle, suit, shirt, accessories, body proportions, desk, office and lighting. "
        "Locked eye-level camera, locked head position and stable exposure. Exactly one person and exactly two hands. "
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
        "9": {"class_type": "LTXVImgToVideo", "inputs": {"positive": ["7", 0], "negative": ["7", 1], "vae": ["3", 0], "image": ["8", 0], "width": 704, "height": 1248, "length": 65, "batch_size": 1, "strength": 0.90}},
        "10": {"class_type": "KSampler", "inputs": {"model": ["2", 0], "positive": ["9", 0], "negative": ["9", 1], "latent_image": ["9", 2], "seed": seed, "steps": 8, "cfg": 1.0, "sampler_name": "euler_ancestral_cfg_pp", "scheduler": "simple", "denoise": 1.0}},
        "11": {"class_type": "LTXVTiledVAEDecode", "inputs": {"vae": ["3", 0], "latents": ["10", 0], "horizontal_tiles": 1, "vertical_tiles": 2, "overlap": 2, "last_frame_fix": False, "working_device": "auto", "working_dtype": "auto"}},
        "12": {"class_type": "CreateVideo", "inputs": {"images": ["11", 0], "fps": 25.0}},
        "13": {"class_type": "SaveVideo", "inputs": {"video": ["12", 0], "filename_prefix": prefix, "format": "mp4", "codec": "h264"}},
    }


def main() -> int:
    output = PROJECT / "hand_cutaways_ltx"
    workflows = PROJECT / "workflows_hand_cutaways_ltx"
    output.mkdir(parents=True, exist_ok=True)
    workflows.mkdir(parents=True, exist_ok=True)
    report: list[dict[str, str]] = []
    for index, shot in enumerate(SHOTS):
        destination = output / f"{shot['id']}.mp4"
        if destination.is_file():
            print(f"SKIP {shot['id']} -> {destination}", flush=True)
            continue
        completed_candidates = list(
            (COMFY_OUTPUT / "wenshu_case_conference_v5").glob(f"{shot['id']}*.mp4")
        )
        if completed_candidates:
            source = max(completed_candidates, key=lambda path: path.stat().st_mtime)
            shutil.copy2(source, destination)
            print(f"RECOVER {shot['id']} -> {destination}", flush=True)
            continue
        input_name = f"wenshu_v5_{shot['id']}.png"
        shutil.copy2(shot["image"], COMFY_INPUT / input_name)
        prefix = f"wenshu_case_conference_v5/{shot['id']}"
        workflow = graph(input_name, shot["motion"], 843100 + index * 149, prefix)
        (workflows / f"{shot['id']}.api.json").write_text(
            json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        response = request_json(
            f"{BASE}/prompt", {"prompt": workflow, "client_id": str(uuid.uuid4())}
        )
        prompt_id = response["prompt_id"]
        print(f"QUEUED {shot['id']} {prompt_id}", flush=True)
        wait(prompt_id)
        candidates = list(
            (COMFY_OUTPUT / "wenshu_case_conference_v5").glob(f"{shot['id']}*.mp4")
        )
        if not candidates:
            raise FileNotFoundError(shot["id"])
        source = max(candidates, key=lambda path: path.stat().st_mtime)
        shutil.copy2(source, destination)
        report.append(
            {
                "id": shot["id"],
                "prompt_id": prompt_id,
                "source": str(source),
                "output": str(destination),
            }
        )
        (PROJECT / "hand_cutaways_ltx_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"DONE {shot['id']} -> {destination}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
