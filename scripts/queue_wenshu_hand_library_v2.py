#!/usr/bin/env python
"""Queue two contact-safe LTX hand-object clips without blocking for completion."""

from __future__ import annotations

import json
import shutil
import urllib.request
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "data/qa/wenshu_lawyer_brand_v1/series_v2"
INPUTS = PROJECT / "hand_library_inputs"
COMFY_INPUT = Path(r"D:\IT\AI_vido\ComfyUI\input")
BASE = "http://127.0.0.1:8190"

SHOTS = [
    {
        "id": "lib_gu_card_tap",
        "image": INPUTS / "gu_cards_start.png",
        "motion": (
            "The right index finger is already touching one rigid blank evidence card. All four cards remain flat, "
            "fixed and perfectly unchanged. His other hand remains completely still. He presses the same card once "
            "with a tiny downward motion, pauses, then lifts the index finger only one centimeter and rests it beside "
            "the same card. One contact event, slow controlled speed. Head fixed, mouth closed."
        ),
    },
    {
        "id": "lib_zhou_folder_slide",
        "image": INPUTS / "zhou_folder_start.png",
        "motion": (
            "Her left hand stays flat and completely still on the desk. Her right palm is already resting on one "
            "rigid closed white folder. Using only the right hand, she slides the entire folder three centimeters "
            "toward the desk center without rotating or bending it, stops, releases it, then rests her right hand "
            "beside the folder. One contact event, slow controlled speed. Head fixed, mouth closed."
        ),
    },
]

NEGATIVE = (
    "identity change, face morphing, extra person, third hand, extra hand, extra arm, missing hand, missing fingers, "
    "extra fingers, fused fingers, malformed fingers, deformed wrist, crossed arms, occluded hand, hand-object fusion, "
    "floating object, duplicate object, moving cards, bending folder, thin paper, paper flutter, object shape change, "
    "motion blur, fast hand motion, repeated action, talking, open mouth, head movement, camera movement, scene cut, "
    "flicker, exposure change, watermark, subtitle"
)


def post(payload: dict) -> dict:
    request = urllib.request.Request(
        f"{BASE}/prompt", data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read())


def graph(image_name: str, motion: str, seed: int, prefix: str) -> dict:
    positive = (
        "Photorealistic internal Chinese law firm case conference. Preserve the exact input identity, face, hair, "
        "clothes, body proportions, desk, objects and lighting. Locked eye-level camera and stable exposure. "
        "Exactly one person, exactly two natural human hands, anatomically correct five fingers on each hand. " + motion
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
        "9": {"class_type": "LTXVImgToVideo", "inputs": {"positive": ["7", 0], "negative": ["7", 1], "vae": ["3", 0], "image": ["8", 0], "width": 704, "height": 1248, "length": 65, "batch_size": 1, "strength": 0.91}},
        "10": {"class_type": "KSampler", "inputs": {"model": ["2", 0], "positive": ["9", 0], "negative": ["9", 1], "latent_image": ["9", 2], "seed": seed, "steps": 8, "cfg": 1.0, "sampler_name": "euler_ancestral_cfg_pp", "scheduler": "simple", "denoise": 1.0}},
        "11": {"class_type": "LTXVTiledVAEDecode", "inputs": {"vae": ["3", 0], "latents": ["10", 0], "horizontal_tiles": 1, "vertical_tiles": 2, "overlap": 2, "last_frame_fix": False, "working_device": "auto", "working_dtype": "auto"}},
        "12": {"class_type": "CreateVideo", "inputs": {"images": ["11", 0], "fps": 25.0}},
        "13": {"class_type": "SaveVideo", "inputs": {"video": ["12", 0], "filename_prefix": prefix, "format": "mp4", "codec": "h264"}},
    }


def main() -> int:
    workflows = PROJECT / "workflows_hand_library"
    workflows.mkdir(parents=True, exist_ok=True)
    queued = []
    for index, shot in enumerate(SHOTS):
        if not shot["image"].is_file():
            raise FileNotFoundError(shot["image"])
        input_name = f"wenshu_series_v2_{shot['id']}.png"
        shutil.copy2(shot["image"], COMFY_INPUT / input_name)
        workflow = graph(input_name, shot["motion"], 917300 + index * 211, f"wenshu_series_v2/hand_library/{shot['id']}")
        (workflows / f"{shot['id']}.api.json").write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8")
        response = post({"prompt": workflow, "client_id": str(uuid.uuid4())})
        queued.append({"id": shot["id"], "prompt_id": response["prompt_id"]})
        print(f"QUEUED {shot['id']} {response['prompt_id']}", flush=True)
    (PROJECT / "hand_library_queue.json").write_text(json.dumps(queued, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
