from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = PROJECT_ROOT / "data" / "models" / "kokoro" / "Kokoro-82M-v1.1-zh"
REPO_ID = "hexgrad/Kokoro-82M-v1.1-zh"
SAMPLE_RATE = 24_000


LINES = [
    ("01", "周宁", "zf_048", 1.30, "客户拿着一张转账记录问我：钱明明转了，为什么官司还不一定赢？"),
    ("02", "周宁", "zf_048", 1.28, "因为法庭要确认的不只是钱动过，还要确认它为什么转，双方到底怎样约定。"),
    ("03", "许安", "zf_001", 1.34, "接到案件，我们先在中国裁判文书网做类案检索。案由、法院、裁判年份、法律依据，一项项收窄。"),
    ("04", "顾承", "zm_052", 1.26, "我们看的不是相似标题，而是争议焦点、举证责任，以及法院完整的论证路径。"),
    ("05", "周宁", "zf_048", 1.30, "以民间借贷为例，只有转账凭证；对方如果举证说这是还款或其他往来，原告仍可能需要继续证明借贷关系成立。"),
    ("06", "许安", "zf_001", 1.34, "所以，聊天记录、借条、催款经过、资金来源和交付方式，必须相互印证，形成证据闭环。"),
    ("07", "顾承", "zm_052", 1.28, "类案不是标准答案，它是一张风险地图：哪些事实会被追问，哪些证据可能不够。"),
    ("08", "周宁", "zf_048", 1.30, "律师的工作，是把判例语言翻译成行动：先补证据，还是先谈判；立即起诉，还是控制成本。"),
    ("09", "周宁", "zf_048", 1.28, "我们不会先承诺结果，而会先把胜诉空间、时间成本和执行风险讲清楚。"),
    ("10", "周宁", "zf_048", 1.25, "专业，不是把话说满；是让你在走进法庭之前，看清每一条路。"),
]


def ffprobe_duration(path: Path) -> float:
    value = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        text=True,
    )
    return float(value.strip())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "qa" / "wenshu_lawyer_brand_v1",
    )
    args = parser.parse_args()
    output_dir = args.project_dir.resolve() / "audio"
    output_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(PROJECT_ROOT / "data" / "cache" / "huggingface"))

    import numpy as np
    import soundfile as sf
    from kokoro import KModel, KPipeline

    model = KModel(
        repo_id=REPO_ID,
        config=str(MODEL_DIR / "config.json"),
        model=str(MODEL_DIR / "kokoro-v1_1-zh.pth"),
    ).to("cpu").eval()
    pipeline = KPipeline(lang_code="z", repo_id=REPO_ID, model=model, device="cpu")

    timeline: list[dict] = []
    cursor = 0.0
    for shot_id, speaker, voice, speed, spoken_text in LINES:
        chunks: list[np.ndarray] = []
        for result in pipeline(
            spoken_text,
            voice=str(MODEL_DIR / "voices" / f"{voice}.pt"),
            speed=speed,
        ):
            if result.audio is not None:
                chunks.append(result.audio.detach().cpu().numpy().astype(np.float32))
        if not chunks:
            raise RuntimeError(f"No audio generated for shot {shot_id}")
        waveform = np.concatenate(chunks)
        output_path = output_dir / f"{shot_id}_{voice}.wav"
        sf.write(output_path, waveform, SAMPLE_RATE, subtype="PCM_16")
        clip_duration = ffprobe_duration(output_path)
        timeline.append(
            {
                "id": shot_id,
                "speaker": speaker,
                "voice": voice,
                "speed": speed,
                "text": spoken_text,
                "file": str(output_path),
                "start": round(cursor, 3),
                "duration": round(clip_duration, 3),
                "end": round(cursor + clip_duration, 3),
            }
        )
        cursor += clip_duration + 0.28
        print(f"{shot_id} {speaker}: {clip_duration:.2f}s -> {output_path}", flush=True)

    manifest = {
        "engine": "Kokoro-82M-v1.1-zh local",
        "policy": "All lines use normal-to-brisk speaking rates; no slow-speed rendering.",
        "timeline": timeline,
        "total_duration": round(cursor, 3),
    }
    (output_dir / "timeline.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
