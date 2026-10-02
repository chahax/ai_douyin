from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = (
    ROOT
    / "data"
    / "qa"
    / "wenshu_lawyer_brand_v1"
    / "v2_debate"
    / "v4_case_conference"
)
MODEL_DIR = ROOT / "data" / "models" / "kokoro" / "Kokoro-82M-v1.1-zh"
REPO_ID = "hexgrad/Kokoro-82M-v1.1-zh"
SAMPLE_RATE = 24_000
CAST = {
    "周宁": ("zf_048", 1.16),
    "顾承": ("zm_052", 1.14),
    "许安": ("zf_001", 1.18),
}


def probe(path: Path) -> float:
    return float(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                str(path),
            ],
            text=True,
        ).strip()
    )


def atempo_chain(value: float) -> str:
    stages: list[float] = []
    while value > 2.0:
        stages.append(2.0)
        value /= 2.0
    while value < 0.5:
        stages.append(0.5)
        value /= 0.5
    stages.append(value)
    return ",".join(f"atempo={stage:.8f}" for stage in stages)


def main() -> int:
    import numpy as np
    import soundfile as sf
    from kokoro import KModel, KPipeline

    os.environ.setdefault("HF_HOME", str(ROOT / "data" / "cache" / "huggingface"))
    raw_dir = PROJECT / "lip_guides_raw"
    final_dir = PROJECT / "lip_guides_16k"
    raw_dir.mkdir(parents=True, exist_ok=True)
    final_dir.mkdir(parents=True, exist_ok=True)

    timeline = json.loads(
        (PROJECT / "production_timeline.json").read_text(encoding="utf-8")
    )["timeline"]
    model = KModel(
        repo_id=REPO_ID,
        config=str(MODEL_DIR / "config.json"),
        model=str(MODEL_DIR / "kokoro-v1_1-zh.pth"),
    ).to("cpu").eval()
    pipeline = KPipeline(
        lang_code="z", repo_id=REPO_ID, model=model, device="cpu"
    )

    report: list[dict[str, object]] = []
    yaml_lines: list[str] = []
    for item in timeline:
        shot_id = str(item["id"])
        speaker = str(item["speaker"])
        voice, speed = CAST[speaker]
        chunks = []
        for result in pipeline(
            str(item["text"]),
            voice=str(MODEL_DIR / "voices" / f"{voice}.pt"),
            speed=speed,
        ):
            if result.audio is not None:
                chunks.append(
                    result.audio.detach().cpu().numpy().astype(np.float32)
                )
        if not chunks:
            raise RuntimeError(f"No Kokoro lip guide for {shot_id}")

        raw = raw_dir / f"{shot_id}.wav"
        sf.write(raw, np.concatenate(chunks), SAMPLE_RATE, subtype="PCM_16")
        raw_duration = probe(raw)

        # Match only the spoken portion. The final CosyVoice files contain an
        # 80 ms lead-in and a 250 ms closed-mouth tail.
        final_audio_duration = float(item["duration_seconds"])
        speech_target = max(0.25, final_audio_duration - 0.33)
        tempo = raw_duration / speech_target
        guide = final_dir / f"{shot_id}.wav"
        audio_filter = (
            f"{atempo_chain(tempo)},highpass=f=65,lowpass=f=7600,"
            "alimiter=limit=0.94,adelay=80,apad=pad_dur=0.25,aresample=16000"
        )
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(raw),
                "-af",
                audio_filter,
                "-ar",
                "16000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                "-t",
                f"{final_audio_duration:.3f}",
                str(guide),
            ],
            check=True,
        )
        aligned_duration = probe(guide)
        plate = PROJECT / "musetalk_plates" / f"{shot_id}.png"
        yaml_lines.extend(
            [
                f"task_{shot_id}:",
                f'  video_path: "{plate.as_posix()}"',
                f'  audio_path: "{guide.as_posix()}"',
                f'  result_name: "{shot_id}_lipsync.mp4"',
            ]
        )
        report.append(
            {
                "id": shot_id,
                "speaker": speaker,
                "voice": voice,
                "text": item["text"],
                "raw_duration": round(raw_duration, 3),
                "target_duration": round(final_audio_duration, 3),
                "aligned_duration": round(aligned_duration, 3),
                "atempo": round(tempo, 6),
                "guide": str(guide.resolve()),
            }
        )
        print(
            f"{shot_id} {speaker}: raw={raw_duration:.3f}s "
            f"target={final_audio_duration:.3f}s tempo={tempo:.4f}",
            flush=True,
        )

    (PROJECT / "musetalk_lip_guides.yaml").write_text(
        "\n".join(yaml_lines) + "\n", encoding="utf-8"
    )
    (PROJECT / "lip_guides_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
