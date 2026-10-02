from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
from pathlib import Path

import edge_tts


LINES = [
    {
        "id": "01_verdict",
        "speaker": "审判长",
        "text": "鉴定结论，被告案发时不具备刑事责任能力。",
        "voice": "zh-CN-XiaoxiaoNeural",
        "rate": "-12%",
        "pitch": "-5Hz",
        "pause": 0.35,
    },
    {
        "id": "02_mother",
        "speaker": "被害人母亲",
        "text": "他杀了我女儿，一句精神病就算了吗？",
        "voice": "zh-CN-XiaoxiaoNeural",
        "rate": "+4%",
        "pitch": "-18Hz",
        "pause": 0.30,
    },
    {
        "id": "03_observation",
        "speaker": "旁白",
        "text": "所有人都以为，案子已经结束。",
        "voice": "zh-CN-YunjianNeural",
        "rate": "-10%",
        "pitch": "-8Hz",
        "pause": 0.40,
    },
    {
        "id": "04_report",
        "speaker": "沈墨",
        "text": "报告没有问题。有问题的是，接受鉴定的人。",
        "voice": "zh-CN-YunxiNeural",
        "rate": "-7%",
        "pitch": "-10Hz",
        "pause": 0.45,
    },
    {
        "id": "05_twin",
        "speaker": "旁白",
        "text": "法庭门打开时，被告第一次慌了。",
        "voice": "zh-CN-YunjianNeural",
        "rate": "-8%",
        "pitch": "-8Hz",
        "pause": 0.35,
    },
    {
        "id": "06_reveal",
        "speaker": "沈墨",
        "text": "你让患病的孪生哥哥，替你完成了精神鉴定。",
        "voice": "zh-CN-YunxiNeural",
        "rate": "-8%",
        "pitch": "-10Hz",
        "pause": 0.70,
    },
]


def duration(path: Path) -> float:
    output = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        text=True,
    )
    return float(output.strip())


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir", type=Path)
    args = parser.parse_args()
    out_dir = args.project_dir.resolve() / "audio"
    out_dir.mkdir(parents=True, exist_ok=True)

    timeline = []
    cursor = 0.0
    for line in LINES:
        out_path = out_dir / f"{line['id']}.mp3"
        communicate = edge_tts.Communicate(
            line["text"],
            line["voice"],
            rate=line["rate"],
            pitch=line["pitch"],
            volume="+0%",
        )
        await communicate.save(str(out_path))
        clip_duration = duration(out_path)
        entry = {
            **line,
            "file": str(out_path),
            "start": round(cursor, 3),
            "end": round(cursor + clip_duration, 3),
            "duration": round(clip_duration, 3),
        }
        timeline.append(entry)
        cursor += clip_duration + float(line["pause"])

    manifest = {
        "timeline": timeline,
        "total_duration": round(cursor, 3),
    }
    (out_dir / "timeline.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
