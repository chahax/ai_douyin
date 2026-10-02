#!/usr/bin/env python
"""Generate all voices for the original lawyer sample with one CosyVoice load."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
COSYVOICE_DIR = Path(r"D:\IT\CosyVoice")
MODEL_DIR = COSYVOICE_DIR / "pretrained_models" / "Fun-CosyVoice3-0.5B"
CACHE_DIR = PROJECT_DIR / "data" / "cache"
PROMPT_WAV = COSYVOICE_DIR / "asset" / "zero_shot_prompt.wav"

LINES = [
    ("01_verdict", "审判长", "鉴定结论，被告案发时不具备刑事责任能力。", "冷静、正式、权威的中年女审判长语气，吐字清晰，语速稍慢。", 0.96, 0.35),
    ("02_mother", "被害人母亲", "他杀了我女儿，一句精神病就算了吗？", "五十岁母亲压抑悲痛后突然质问，声音发颤但不要喊破音，语速略快。", 1.05, 0.30),
    ("03_observation", "旁白", "所有人都以为，案子已经结束。", "低沉克制的男性悬疑旁白，后半句稍作停顿，语速偏慢。", 0.95, 0.40),
    ("04_report", "沈墨", "报告没有问题。有问题的是，接受鉴定的人。", "三十四岁男性律师，冷静、笃定、具有压迫感，第二句强调“接受鉴定的人”。", 0.98, 0.45),
    ("05_twin", "旁白", "法庭门打开时，被告第一次慌了。", "低沉克制的男性悬疑旁白，像揭示关键转折，最后三个字压低声音。", 0.96, 0.35),
    ("06_reveal", "沈墨", "你让患病的孪生哥哥，替你完成了精神鉴定。", "三十四岁男性律师，平静但锋利地揭穿真相，停顿自然，不怒吼。", 0.96, 0.70),
]


def configure_runtime() -> None:
    for directory in (CACHE_DIR, CACHE_DIR / "numba", CACHE_DIR / "huggingface"):
        directory.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("NUMBA_CACHE_DIR", str(CACHE_DIR / "numba"))
    os.environ.setdefault("HF_HOME", str(CACHE_DIR / "huggingface"))
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ["TEMP"] = str(CACHE_DIR)
    os.environ["TMP"] = str(CACHE_DIR)
    sys.path.insert(0, str(COSYVOICE_DIR))
    sys.path.insert(0, str(COSYVOICE_DIR / "third_party" / "Matcha-TTS"))


def wav_duration(path: Path) -> float:
    value = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        text=True,
    )
    return float(value.strip())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir", type=Path)
    args = parser.parse_args()
    out_dir = args.project_dir.resolve() / "audio"
    out_dir.mkdir(parents=True, exist_ok=True)
    configure_runtime()

    import torch
    import torchaudio
    from cosyvoice.cli.cosyvoice import AutoModel

    started = time.perf_counter()
    model = AutoModel(model_dir=str(MODEL_DIR), load_trt=False, load_vllm=False, fp16=True)
    print(f"model_load_seconds={time.perf_counter() - started:.2f}", flush=True)

    timeline = []
    cursor = 0.0
    for shot_id, speaker, text, instruct, speed, pause in LINES:
        prompt = f"You are a helpful assistant. {instruct}<|endofprompt|>"
        chunks = []
        with torch.inference_mode():
            for result in model.inference_instruct2(text, prompt, str(PROMPT_WAV), stream=False, speed=speed):
                chunks.append(result["tts_speech"].cpu())
        if not chunks:
            raise RuntimeError(f"CosyVoice returned no audio for {shot_id}")
        speech = torch.cat(chunks, dim=1)
        output = out_dir / f"{shot_id}.wav"
        torchaudio.save(str(output), speech, model.sample_rate, encoding="PCM_S", bits_per_sample=16)
        duration = wav_duration(output)
        timeline.append({
            "id": shot_id,
            "speaker": speaker,
            "text": text,
            "file": str(output),
            "start": round(cursor, 3),
            "end": round(cursor + duration, 3),
            "duration": round(duration, 3),
            "pause": pause,
        })
        cursor += duration + pause
        print(f"generated {shot_id}: {duration:.2f}s", flush=True)

    manifest = {"engine": "CosyVoice3-0.5B-2512 local", "timeline": timeline, "total_duration": round(cursor, 3)}
    (out_dir / "timeline.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
