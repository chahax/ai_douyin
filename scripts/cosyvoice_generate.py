#!/usr/bin/env python
"""Generate one CosyVoice3 WAV with stable Windows cache locations."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
COSYVOICE_DIR = Path(r"D:\IT\CosyVoice")
MODEL_DIR = COSYVOICE_DIR / "pretrained_models" / "Fun-CosyVoice3-0.5B"
CACHE_DIR = PROJECT_DIR / "data" / "cache"
DEFAULT_PROMPT_WAV = COSYVOICE_DIR / "asset" / "zero_shot_prompt.wav"


def configure_runtime() -> None:
    """Configure caches before importing libraries that initialize Numba."""
    numba_cache = CACHE_DIR / "numba"
    huggingface_cache = CACHE_DIR / "huggingface"
    numba_cache.mkdir(parents=True, exist_ok=True)
    huggingface_cache.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("NUMBA_CACHE_DIR", str(numba_cache))
    os.environ.setdefault("HF_HOME", str(huggingface_cache))
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ["TEMP"] = str(CACHE_DIR)
    os.environ["TMP"] = str(CACHE_DIR)

    sys.path.insert(0, str(COSYVOICE_DIR))
    sys.path.insert(0, str(COSYVOICE_DIR / "third_party" / "Matcha-TTS"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", required=True, help="Text to synthesize.")
    parser.add_argument(
        "--instruct",
        default="请用自然、真诚、略带担忧的语气说这句话。",
        help="Natural-language delivery instruction.",
    )
    parser.add_argument("--prompt-wav", type=Path, default=DEFAULT_PROMPT_WAV)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_DIR / "data" / "audio" / "cosyvoice" / "sample.wav",
    )
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--fp16", action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    configure_runtime()

    import torch
    import torchaudio
    from cosyvoice.cli.cosyvoice import AutoModel

    if not MODEL_DIR.joinpath("cosyvoice3.yaml").is_file():
        raise FileNotFoundError(f"CosyVoice3 model is incomplete: {MODEL_DIR}")
    if not args.prompt_wav.is_file():
        raise FileNotFoundError(f"Prompt WAV does not exist: {args.prompt_wav}")

    started = time.perf_counter()
    model = AutoModel(
        model_dir=str(MODEL_DIR),
        load_trt=False,
        load_vllm=False,
        fp16=args.fp16,
    )
    load_seconds = time.perf_counter() - started

    instruction = (
        f"You are a helpful assistant. {args.instruct.strip()}<|endofprompt|>"
    )
    chunks = []
    with torch.inference_mode():
        for result in model.inference_instruct2(
            args.text,
            instruction,
            str(args.prompt_wav),
            stream=False,
            speed=args.speed,
        ):
            chunks.append(result["tts_speech"].cpu())

    if not chunks:
        raise RuntimeError("CosyVoice returned no audio chunks.")

    speech = torch.cat(chunks, dim=1)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    torchaudio.save(
        str(args.output),
        speech,
        model.sample_rate,
        encoding="PCM_S",
        bits_per_sample=16,
    )
    duration = speech.shape[1] / model.sample_rate

    print(f"output={args.output.resolve()}")
    print(f"sample_rate={model.sample_rate}")
    print(f"duration_seconds={duration:.2f}")
    print(f"model_load_seconds={load_seconds:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
