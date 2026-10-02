#!/usr/bin/env python
"""Prepare exact CosyVoice WAVs and fixed character plates for the ten-episode series."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "data/qa/wenshu_lawyer_brand_v1"
PROJECT = BASE / "series_v2"
MASTER = BASE / "characters"
SIDE = BASE / "v2_debate/characters"

PLATES = {
    ("周宁", "front"): MASTER / "zhouning_master.png",
    ("周宁", "side"): SIDE / "zhouning_side.png",
    ("顾承", "front"): MASTER / "gucheng_master.png",
    ("顾承", "side"): SIDE / "gucheng_side.png",
    ("许安", "front"): MASTER / "xuan_master.png",
    ("许安", "side"): SIDE / "xuan_side.png",
}


def run(args: list[str]) -> None:
    subprocess.run(args, check=True)


def probe(path: Path) -> float:
    return float(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(path),
    ], text=True).strip())


def main() -> int:
    report_path = PROJECT / "audio_cosyvoice/voice_render_report.json"
    if not report_path.is_file():
        raise FileNotFoundError(f"Run CosyVoice first: {report_path}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    catalog = json.loads((PROJECT / "series_catalog.json").read_text(encoding="utf-8"))
    camera = {
        line["id"]: ("side" if "侧面" in line["camera"] else "front")
        for episode in catalog["episodes"] for line in episode["lines"]
    }
    audio_dir = PROJECT / "audio_final_16k"
    plate_dir = PROJECT / "plates"
    audio_dir.mkdir(parents=True, exist_ok=True)
    plate_dir.mkdir(parents=True, exist_ok=True)
    timeline = []
    for item in report["lines"]:
        line_id = item["id"]
        role = item["speaker"]
        view = camera[line_id]
        output_audio = audio_dir / f"{line_id}.wav"
        if not output_audio.is_file():
            run([
                "ffmpeg", "-y", "-loglevel", "error", "-i", item["audio_path"],
                "-af", "adelay=70,apad=pad_dur=0.22,aresample=16000",
                "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(output_audio),
            ])
        plate = plate_dir / f"{line_id}.png"
        source = PLATES[(role, view)]
        if not plate.is_file():
            vf = (
                "scale=830:1476:flags=lanczos,crop=704:1248:(in_w-out_w)/2:24"
                if view == "front" else
                "scale=704:1248:force_original_aspect_ratio=increase:flags=lanczos,crop=704:1248"
            )
            run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(source), "-vf", vf, "-frames:v", "1", str(plate)])
        timeline.append({
            **item,
            "audio_path": str(output_audio.resolve()),
            "duration_seconds": round(probe(output_audio), 3),
            "plate": str(plate.resolve()),
            "source_plate": str(source.resolve()),
            "camera": view,
        })
    (PROJECT / "production_timeline.json").write_text(json.dumps({"timeline": timeline}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"prepared={len(timeline)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
