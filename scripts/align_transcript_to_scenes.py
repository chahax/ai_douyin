"""Align FunASR token timestamps to PySceneDetect scene intervals."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("transcript", type=Path)
    parser.add_argument("scenes_csv", type=Path)
    parser.add_argument("output", type=Path)
    return parser.parse_args()


def load_scenes(csv_path: Path) -> list[dict[str, object]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        next(handle)
        rows = list(csv.DictReader(handle))
    return [
        {
            "scene": int(row["Scene Number"]),
            "start": float(row["Start Time (seconds)"]),
            "end": float(row["End Time (seconds)"]),
            "start_timecode": row["Start Timecode"],
            "end_timecode": row["End Timecode"],
            "text_tokens": [],
        }
        for row in rows
    ]


def main() -> None:
    args = parse_args()
    transcript = json.loads(args.transcript.read_text(encoding="utf-8"))["result"][0]
    tokens = transcript["text"].split()
    timestamps = transcript["timestamp"]
    if len(tokens) != len(timestamps):
        raise RuntimeError(f"Token/timestamp mismatch: {len(tokens)} != {len(timestamps)}")

    scenes = load_scenes(args.scenes_csv)
    for token, (start_ms, end_ms) in zip(tokens, timestamps):
        midpoint = (start_ms + end_ms) / 2000.0
        target = next(
            (scene for scene in scenes if scene["start"] <= midpoint < scene["end"]),
            scenes[-1],
        )
        target["text_tokens"].append(token)

    for scene in scenes:
        scene["asr_text"] = "".join(scene.pop("text_tokens"))
    payload = {
        "schema": "scene_transcript_alignment/v1",
        "transcript": str(args.transcript.resolve()),
        "scenes_csv": str(args.scenes_csv.resolve()),
        "scenes": scenes,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for scene in scenes:
        print(
            f"S{scene['scene']:02d} {scene['start']:06.2f}-{scene['end']:06.2f}s "
            f"{scene['asr_text']}"
        )


if __name__ == "__main__":
    main()
