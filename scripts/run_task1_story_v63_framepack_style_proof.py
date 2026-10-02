from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from gradio_client import Client, handle_file


PROMPTS = {
    "male_walk": (
        "Glossy high-saturation Chinese AI live-action micro-drama on a wet neon city street at night. "
        "Preserve the exact adult Chinese male identity, short black hair, pale-blue open shirt, white T-shirt, "
        "dark jeans, white sneakers, smartphone, low 24mm camera angle, vivid cyan-magenta-red lighting and framing. "
        "He completes one bold confident stride directly toward camera: the lifted front foot plants close to lens, "
        "the rear leg pushes off visibly, hips and shoulders transfer weight, free arm counter-swings, shirt hem reacts, "
        "and he glances from the phone toward camera with a smug micro-smile. Strong readable lower-body movement, one "
        "continuous action, fashion-ad energy, punchy Douyin short-drama visual impact, stable camera and identity."
    ),
    "female_block": (
        "Glossy high-saturation Chinese AI live-action micro-drama on the same wet neon city street at night. "
        "Preserve the exact adult Chinese female identity, high ponytail, ivory blazer, light-blue blouse, charcoal "
        "trousers, beige heels, low 24mm Dutch-angle camera, vivid cyan-magenta-red lighting and framing. She lunges "
        "decisively into the path of someone off-screen-left: front heel plants firmly, rear leg drives forward, torso "
        "leans in, reaching arm extends another short distance toward screen-left while the other arm counterbalances, "
        "blazer hem and ponytail follow through, eyes widen and lips part with urgent determination. Strong readable "
        "full-body movement, one continuous action, fashion-ad energy, punchy Douyin short-drama impact, stable camera."
    ),
}

NEGATIVE = (
    "identity change, face morphing, hairstyle change, clothing change, scene change, background change, muted grade, "
    "frozen pose, frozen legs, foot sliding, moonwalk, tiny motion, slow idle, duplicated person, extra limbs, missing "
    "limbs, extra fingers, fused fingers, deformed hands, phone duplication, disappearing phone, rubber body, dancing, "
    "jumping, running away, camera shake, pan, tilt, zoom, scene cut, flicker, exposure pumping, anime, cartoon, "
    "documentary, corporate portrait, presenter, text, subtitles, watermark, logo"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def video_candidates(value: object) -> list[Path]:
    candidates: list[Path] = []
    if isinstance(value, (str, Path)):
        path = Path(str(value))
        if path.suffix.lower() in {".mp4", ".mov", ".webm", ".mkv"}:
            candidates.append(path)
        return candidates
    if isinstance(value, dict):
        for nested in value.values():
            candidates.extend(video_candidates(nested))
        return candidates
    if isinstance(value, (tuple, list)):
        for nested in value:
            candidates.extend(video_candidates(nested))
        return candidates
    path = getattr(value, "path", None)
    if path:
        candidates.extend(video_candidates(path))
    return candidates


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a V6.3 visual-style proof shot with local FramePack.")
    parser.add_argument("--shot", required=True, choices=sorted(PROMPTS))
    parser.add_argument("--input-image", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:7861")
    parser.add_argument("--seed", type=int, default=6320822)
    parser.add_argument("--duration", type=float, default=2.5)
    args = parser.parse_args()

    image_path = Path(args.input_image).resolve()
    if not image_path.is_file():
        raise FileNotFoundError(image_path)
    output_root = Path(args.output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    client = Client(args.base_url)
    job = client.submit(
        input_image=handle_file(str(image_path)),
        prompt=PROMPTS[args.shot],
        n_prompt=NEGATIVE,
        seed=float(args.seed),
        total_second_length=float(args.duration),
        latent_window_size=9,
        steps=25,
        cfg=1.0,
        gs=10.0,
        rs=0.0,
        gpu_memory_preservation=6.0,
        use_teacache=True,
        api_name="/process",
    )
    result = job.result()
    candidates = video_candidates(job.outputs()) + video_candidates(result)
    existing = [path for path in candidates if path.is_file() and path.stat().st_size > 0]
    if not existing:
        raise RuntimeError(f"FramePack returned no usable video: {[str(path) for path in candidates]}")
    generated = existing[-1]
    destination = output_root / f"{args.shot}_framepack.mp4"
    pending = destination.with_suffix(".pending.mp4")
    shutil.copy2(generated, pending)
    pending.replace(destination)

    report = {
        "schema": "task1_story_v63_framepack_style_proof/v1",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "publish_allowed": False,
        "fanqie_backfill_allowed": False,
        "shot": args.shot,
        "renderer": "local_framepack_i2v",
        "seed": args.seed,
        "duration_seconds_requested": args.duration,
        "input_image": {"path": str(image_path), "sha256": sha256(image_path)},
        "prompt": PROMPTS[args.shot],
        "negative_prompt": NEGATIVE,
        "video": {"path": str(destination), "sha256": sha256(destination)},
        "framepack_source": str(generated),
    }
    report_path = output_root / f"{args.shot}_render_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
