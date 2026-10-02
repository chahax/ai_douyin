from __future__ import annotations

import time
from pathlib import Path

import torch
from transformers import WhisperModel


def mark(label: str, start: float) -> float:
    now = time.perf_counter()
    print(f"{label}: {now - start:.3f}s", flush=True)
    return now


def main() -> int:
    from musetalk.utils.audio_processor import AudioProcessor

    root = Path(r"D:\IT\MuseTalk")
    wav = Path(r"D:\IT\ai_douyin\data\qa\wenshu_lawyer_brand_v1\v2_debate\audio_fast\02.wav")
    t = time.perf_counter()
    processor = AudioProcessor(str(root / "models" / "whisper"))
    t = mark("feature extractor init", t)
    whisper = WhisperModel.from_pretrained(str(root / "models" / "whisper"))
    t = mark("whisper load", t)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    whisper = whisper.to(device=device, dtype=torch.float16).eval()
    t = mark("whisper to device", t)
    features, length = processor.get_audio_feature(str(wav), weight_dtype=torch.float16)
    t = mark(f"audio feature length={length}", t)
    prompts = processor.get_whisper_chunk(features, device, torch.float16, whisper, length, fps=25)
    mark(f"whisper prompts={tuple(prompts.shape)}", t)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
