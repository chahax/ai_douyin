#!/usr/bin/env python
"""Generate a batch of Kokoro Chinese voice auditions with one model load."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
MODEL_DIR = (
    PROJECT_DIR
    / "data"
    / "models"
    / "kokoro"
    / "Kokoro-82M-v1.1-zh"
)
REPO_ID = "hexgrad/Kokoro-82M-v1.1-zh"
SAMPLE_RATE = 24_000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", required=True)
    parser.add_argument("--voices", nargs="+", required=True)
    parser.add_argument("--speed", type=float, default=1.05)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_DIR / "data" / "audio" / "kokoro" / "auditions",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    os.environ.setdefault(
        "HF_HOME",
        str(PROJECT_DIR / "data" / "cache" / "huggingface"),
    )

    import numpy as np
    import soundfile as sf
    import torch
    from kokoro import KModel, KPipeline

    config_path = MODEL_DIR / "config.json"
    weights_path = MODEL_DIR / "kokoro-v1_1-zh.pth"
    if not config_path.is_file() or not weights_path.is_file():
        raise FileNotFoundError(f"Kokoro model is incomplete: {MODEL_DIR}")

    model = KModel(
        repo_id=REPO_ID,
        config=str(config_path),
        model=str(weights_path),
    ).to("cpu").eval()
    pipeline = KPipeline(
        lang_code="z",
        repo_id=REPO_ID,
        model=model,
        device="cpu",
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    silence = np.zeros(int(SAMPLE_RATE * 0.12), dtype=np.float32)

    for voice_id in args.voices:
        voice_path = MODEL_DIR / "voices" / f"{voice_id}.pt"
        if not voice_path.is_file():
            raise FileNotFoundError(f"Unknown Kokoro voice: {voice_id}")

        chunks: list[np.ndarray] = []
        for result in pipeline(
            args.text,
            voice=str(voice_path),
            speed=args.speed,
        ):
            if result.audio is None:
                continue
            audio = result.audio.detach().cpu().numpy().astype(np.float32)
            if chunks:
                chunks.append(silence)
            chunks.append(audio)

        if not chunks:
            raise RuntimeError(f"Kokoro returned no audio for {voice_id}")

        waveform = np.concatenate(chunks)
        output_path = args.output_dir / f"{voice_id}.wav"
        sf.write(output_path, waveform, SAMPLE_RATE, subtype="PCM_16")
        print(
            f"{voice_id}: {output_path.resolve()} "
            f"({waveform.size / SAMPLE_RATE:.2f}s)"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
