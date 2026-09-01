"""Transcribe a local WAV file with the downloaded FunASR model bundle."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL_ROOT = PROJECT_ROOT / ".local_models" / "video_analysis"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model-root", type=Path, default=DEFAULT_MODEL_ROOT)
    parser.add_argument(
        "--hotword",
        default="法律 律师 法院 诉讼 合同 劳动仲裁 婚姻 债务 赔偿",
    )
    parser.add_argument(
        "--without-punctuation",
        action="store_true",
        help="Skip CT-Punc when its output encoding is incompatible with the source audio.",
    )
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    audio = args.audio.resolve()
    output = args.output.resolve()
    model_root = args.model_root.resolve()
    os.environ.setdefault("NUMBA_CACHE_DIR", str(PROJECT_ROOT / "data" / ".numba_cache"))

    from funasr import AutoModel

    model_options = {
        "model": str(model_root / "paraformer-zh"),
        "vad_model": str(model_root / "fsmn-vad"),
        "device": "cpu",
        "disable_update": True,
    }
    if not args.without_punctuation:
        model_options["punc_model"] = str(model_root / "ct-punc")
    model = AutoModel(
        **model_options,
    )
    result = model.generate(input=str(audio), batch_size_s=60, hotword=args.hotword)
    payload = {
        "schema": "local_video_transcript/v1",
        "audio": str(audio),
        "models": {
            "asr": "paraformer-zh",
            "vad": "fsmn-vad",
            "punctuation": None if args.without_punctuation else "ct-punc",
        },
        "result": result,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"Wrote UTF-8 transcript: {output}")


if __name__ == "__main__":
    main()
