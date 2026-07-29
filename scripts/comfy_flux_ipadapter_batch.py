from __future__ import annotations

import argparse
import json
import shutil
import time
import urllib.request
import uuid
from pathlib import Path


IP_SCALES = {
    "01_unknown_call": 0.55,
    "02_accusation": 0.70,
    "03_foreign_number": 0.25,
    "04_pacing": 0.60,
    "05_transfer": 0.55,
    "06_police_call": 0.68,
    "07_real_officer": 0.42,
    "08_relief_warning": 0.70,
}

SHOT_SUFFIXES = {
    "01_unknown_call": (
        "Both forearms lie on the desktop. Her left hand rests beside the laptop and her right hand rests "
        "beside the phone; all ten relaxed fingers touch or nearly touch the wooden desk."
    ),
    "02_accusation": "Exactly one visible hand holds the phone at her right ear; the other hand stays out of frame.",
    "03_foreign_number": "Show exactly two natural adult hands and one phone. The phone screen is solid dark navy and blank.",
    "04_pacing": (
        "Both feet are planted naturally, parallel and shoulder-width apart; she wears closed dark office shoes "
        "and dark charcoal straight-leg office trousers."
    ),
    "05_transfer": (
        "The phone screen is a uniform blank pale-gray surface with no generated letters, symbols, or fake words. "
        "The index finger hovers without touching."
    ),
    "06_police_call": "The frame contains exactly one woman and one phone against a clean uncluttered study background.",
    "07_real_officer": (
        "Exactly two people total, separated by a sharp vertical video-call divider: one seated woman only on the left "
        "and one male police officer only on the right. The clean background contains empty space and the total cast is two."
    ),
    "08_relief_warning": "Exactly one woman. Both hands are lowering naturally from her face toward the desk.",
}

PROMPT_OVERRIDES = {
    "01_unknown_call": (
        "Vertical cinematic medium shot inside a modern Chinese apartment study at evening. "
        "The same adult Chinese woman age 28 sits at a wooden desk beside an open laptop. "
        "A smartphone lies flat on the desk near her right forearm and appears to vibrate. "
        "She looks down toward the phone with slightly furrowed eyebrows. Both forearms rest on the desktop; "
        "both hands are low and relaxed beside the laptop, palms down. Premium handcrafted 3D plush doll, "
        "soft flocked fabric, fine textile fibers, rounded adult chibi proportions, cold white practical light "
        "with a small warm desk lamp, clean 9:16 composition."
    ),
    "02_accusation": (
        "Vertical tight head-and-shoulders portrait of the same adult Chinese woman age 28. "
        "A single black smartphone is pressed flat against her right ear by her right hand. "
        "The crop ends at her upper chest and includes only that hand. Her eyes tighten with restrained fear "
        "and her lower lip presses inward. Her light blue shirt collar, charcoal blazer and thin silver necklace "
        "remain visible. Premium handcrafted 3D plush doll, fine textile fibers, cool apartment light, 85mm lens."
    ),
    "05_transfer": (
        "Vertical over-shoulder close shot of the same adult Chinese woman at the wooden desk. "
        "She holds one portrait-oriented smartphone upright in her left hand. Its tall screen is a uniform blank "
        "pale-gray rectangle. Her right index finger hovers one centimeter above the lower third of the screen. "
        "Her worried face is visible behind the phone in three-quarter profile. Premium handcrafted 3D plush doll, "
        "light blue shirt, charcoal blazer, visible thin silver necklace, cool tense light, physically natural hands."
    ),
    "06_police_call": (
        "Vertical medium close shot of the same adult Chinese woman seated at the wooden desk. "
        "She holds one portrait-oriented smartphone upright at chest height and looks at its uniform blank dark-blue "
        "screen with a small surprised expression. Her other hand has pulled back and rests on the desk. "
        "Her light blue button-up shirt, charcoal blazer and thin silver necklace are clearly visible. "
        "Premium handcrafted 3D plush doll, cool blue light beginning to warm, clean uncluttered study background."
    ),
    "07_real_officer": (
        "Vertical clean two-way video-call split composition with exactly two adult plush characters. "
        "Left half: the same Chinese woman age 28, light blue shirt, charcoal blazer and thin silver necklace, "
        "holds one phone at chest height and looks relieved. Right half: one Chinese male police officer age 35, "
        "square face and short black hair fully visible, wears a plain solid navy duty uniform with an empty breast area. "
        "He holds his right open hand at chest height in a calm stop gesture while his left arm rests beside his body. "
        "Both backgrounds are simple and empty. Premium handcrafted 3D plush stop-motion film, clear vertical divider."
    ),
}


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


def saved_image(history: dict, output_root: Path) -> Path:
    for output in history.get("outputs", {}).values():
        for image in output.get("images", []):
            if image.get("type") == "output" and image.get("filename", "").lower().endswith(".png"):
                return output_root / image.get("subfolder", "") / image["filename"]
    raise RuntimeError("ComfyUI history did not contain a saved PNG")


def workflow(
    *,
    checkpoint: str,
    prompt: str,
    negative_prompt: str,
    seed: int,
    width: int,
    height: int,
    steps: int,
    cfg: float,
    sampler: str,
    scheduler: str,
    reference_image: str,
    ip_adapter: str,
    clip_vision: str,
    ip_scale: float,
    filename_prefix: str,
) -> dict:
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
        "2": {"class_type": "LoadImage", "inputs": {"image": reference_image}},
        "3": {
            "class_type": "LoadFluxIPAdapter",
            "inputs": {"ipadatper": ip_adapter, "clip_vision": clip_vision, "provider": "CPU"},
        },
        "4": {
            "class_type": "ApplyFluxIPAdapter",
            "inputs": {
                "model": ["1", 0],
                "ip_adapter_flux": ["3", 0],
                "image": ["2", 0],
                "ip_scale": ip_scale,
            },
        },
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 1]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": negative_prompt, "clip": ["1", 1]}},
        "7": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "8": {
            "class_type": "XlabsSampler",
            "inputs": {
                "model": ["4", 0],
                "conditioning": ["5", 0],
                "neg_conditioning": ["6", 0],
                "noise_seed": seed,
                "steps": steps,
                "timestep_to_start_cfg": steps,
                "true_gs": cfg,
                "image_to_image_strength": 0.0,
                "denoise_strength": 1.0,
                "latent_image": ["7", 0],
            },
        },
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["1", 2]}},
        "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0], "filename_prefix": filename_prefix}},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate identity-locked anti-fraud keyframes with Flux IP-Adapter.")
    parser.add_argument("project")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8190")
    parser.add_argument("--comfy-output", default=r"D:\IT\AI_vido\ComfyUI\output")
    parser.add_argument("--reference-image", default="anti_fraud_police_chibi_v1/new/liting_anchor_v2.png")
    parser.add_argument("--ip-adapter", default="ip_adapter.safetensors")
    parser.add_argument("--clip-vision", default=r"openai_clip_vit_l14\model.safetensors")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--only", action="append", help="Generate only a selected shot id; repeat as needed.")
    parser.add_argument("--overrides", help="Optional JSON mapping shot ids to prompt overrides.")
    parser.add_argument("--seed-offset", type=int, default=2000)
    parser.add_argument("--filename-prefix", default="anti_fraud_police_chibi/new")
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    args = parser.parse_args()

    project = json.loads(Path(args.project).read_text(encoding="utf-8"))
    settings = project["keyframe_generation"]
    output_dir = Path(args.output_dir).resolve()
    image_dir = output_dir / "keyframes"
    workflow_dir = output_dir / "workflows"
    image_dir.mkdir(parents=True, exist_ok=True)
    workflow_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "run_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else []
    overrides = (
        json.loads(Path(args.overrides).read_text(encoding="utf-8"))
        if args.overrides else {}
    )
    client_id = str(uuid.uuid4())

    for shot in project["shots"]:
        if args.only and shot["id"] not in args.only:
            continue
        destination = image_dir / f"{shot['id']}.png"
        if args.skip_existing and destination.is_file():
            print(f"skipped {shot['id']}", flush=True)
            continue
        shot_options = overrides.get(shot["id"], {})
        override_prompt = shot_options.get("prompt")
        base_prompt = override_prompt or PROMPT_OVERRIDES.get(shot["id"], shot["prompt"])
        suffix = shot_options.get("suffix", SHOT_SUFFIXES.get(shot["id"], ""))
        identity_lock = shot_options.get("identity_lock", shot.get("identity_lock"))
        if not identity_lock:
            character_id = shot.get("character_id")
            character = project.get("character_bible", {}).get(character_id, {})
            identity_lock = character.get("invariants") or character.get("identity_prompt", "")
        prompt = base_prompt
        if identity_lock:
            prompt += (
                " The character identity must exactly match the supplied character master reference: "
                + identity_lock + ". Preserve the same adult identity in every frame."
            )
        if suffix:
            prompt += " " + suffix
        ip_scale = shot_options.get(
            "ip_scale",
            shot.get("ip_scale", IP_SCALES.get(shot["id"], 0.65)),
        )
        graph = workflow(
            checkpoint=settings["checkpoint"],
            prompt=prompt,
            negative_prompt=shot_options.get("negative_prompt", ""),
            seed=shot["seed"] + args.seed_offset,
            width=settings["width"],
            height=settings["height"],
            steps=settings["steps"],
            cfg=settings["cfg"],
            sampler=settings["sampler"],
            scheduler=settings["scheduler"],
            reference_image=args.reference_image,
            ip_adapter=args.ip_adapter,
            clip_vision=args.clip_vision,
            ip_scale=ip_scale,
            filename_prefix=f"{args.filename_prefix}/{shot['id']}",
        )
        workflow_path = workflow_dir / f"{shot['id']}.api.json"
        workflow_path.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
        response = request_json(f"{args.base_url}/prompt", {"prompt": graph, "client_id": client_id})
        prompt_id = response["prompt_id"]
        print(f"queued {shot['id']}: {prompt_id}", flush=True)
        history = wait_history(args.base_url, prompt_id, args.timeout_seconds)
        source = saved_image(history, Path(args.comfy_output))
        shutil.copy2(source, destination)
        report.append({
            "id": shot["id"],
            "status": "generated",
            "prompt_id": prompt_id,
            "source": str(source),
            "output": str(destination),
            "seed": shot["seed"] + args.seed_offset,
            "ip_scale": ip_scale,
        })
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"generated {shot['id']}: {destination}", flush=True)


if __name__ == "__main__":
    main()
