from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from gradio_client import Client, handle_file


POSITIVE = (
    "Photorealistic glossy Chinese live-action campus micro-drama at night after rain. "
    "Preserve the exact adult Chinese man's face, hairstyle, pale blue open overshirt, white T-shirt, "
    "dark jeans, phone, wet neon street background, camera height, framing and color grade from the input image. "
    "He takes one calm natural step toward the camera with clear but realistic lower-body weight transfer. "
    "During the step he lowers the phone in his right hand from lower chest toward his right hip, then turns his "
    "head and upper torso slightly toward screen-right as if he has just noticed someone approaching. His free left "
    "forearm moves slightly toward the empty screen-right space. One continuous action, natural arm counter-swing, "
    "subtle shoulder motion, stable camera, stable identity, stable anatomy, premium live-action short-drama look."
)

NEGATIVE = (
    "face morphing, identity change, hairstyle change, clothing change, scene change, background change, "
    "phone switching hands, phone duplication, disappearing phone, extra fingers, fused fingers, deformed hands, "
    "extra limbs, missing limbs, duplicated person, another person entering, frozen body, frozen legs, foot sliding, "
    "moonwalk, dancing, jumping, running, exaggerated pose, fast motion, camera shake, pan, tilt, zoom, scene cut, "
    "flicker, exposure pumping, anime, cartoon, presenter, text, subtitles, watermark, logo"
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
    parser = argparse.ArgumentParser(description="Generate the revised V6.2 b01 with local FramePack.")
    parser.add_argument("--input-image", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:7861")
    parser.add_argument("--seed", type=int, default=6220823)
    parser.add_argument("--duration", type=float, default=3.0)
    args = parser.parse_args()

    image_path = Path(args.input_image).resolve()
    if not image_path.is_file():
        raise FileNotFoundError(image_path)
    output_root = Path(args.output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    client = Client(args.base_url)
    job = client.submit(
        input_image=handle_file(str(image_path)),
        prompt=POSITIVE,
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
    destination = output_root / "b01_boast_framepack_reference_composition.mp4"
    pending = destination.with_suffix(".pending.mp4")
    shutil.copy2(generated, pending)
    pending.replace(destination)

    report = {
        "schema": "task1_story_v62_framepack_b01_revision/v1",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "publish_allowed": False,
        "fanqie_backfill_allowed": False,
        "scene_id": "b01_boast",
        "renderer": "local_framepack_i2v",
        "seed": args.seed,
        "duration_seconds_requested": args.duration,
        "input_image": {"path": str(image_path), "sha256": sha256(image_path)},
        "prompt": POSITIVE,
        "negative_prompt": NEGATIVE,
        "video": {"path": str(destination), "sha256": sha256(destination)},
        "framepack_source": str(generated),
    }
    report_path = output_root / "render_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
