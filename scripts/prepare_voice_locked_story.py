#!/usr/bin/env python
"""Create a story manifest and scene timing file from a batch voice report."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_manifest", type=Path)
    parser.add_argument("voice_report", type=Path)
    parser.add_argument("video_dir", type=Path)
    parser.add_argument("output_manifest", type=Path)
    parser.add_argument("audio_timeline", type=Path)
    parser.add_argument("--between-line-pause", type=float, default=0.25)
    args = parser.parse_args()

    base = json.loads(args.base_manifest.read_text(encoding="utf-8-sig"))
    report = json.loads(args.voice_report.read_text(encoding="utf-8-sig"))
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for line in report["lines"]:
        grouped[str(line["scene_id"])].append(line)

    cast = {
        role_id: {
            "name": role["name"],
            "voice": role["voice_id"],
            # Existing audio paths are always used; "edge" only satisfies the
            # story manifest's provider enum and never triggers synthesis.
            "tts_provider": "edge",
        }
        for role_id, role in report["cast"].items()
    }
    scenes: list[dict[str, object]] = []
    timeline_scenes: list[dict[str, object]] = []
    global_lines: list[dict[str, object]] = []
    global_cursor = 0.0
    for scene in base["scenes"]:
        scene_id = scene["id"]
        source_lines = grouped.get(scene_id)
        if not source_lines:
            raise ValueError(f"No generated voice lines for scene {scene_id}")
        story_lines = []
        local_cursor = 0.0
        for index, line in enumerate(source_lines):
            pause = args.between_line_pause if index + 1 < len(source_lines) else 0.0
            duration = float(line["duration_seconds"])
            story_lines.append(
                {
                    "speaker": line["speaker"],
                    "text": line["text"],
                    "audio_path": line["audio_path"],
                    "pause_after_seconds": pause,
                    "rate": "+0%",
                    "volume": "+0%",
                    "pitch": "+0Hz",
                }
            )
            global_lines.append(
                {
                    "speaker": line["speaker"],
                    "speaker_name": cast[line["speaker"]]["name"],
                    "text": line["text"],
                    "audio_path": line["audio_path"],
                    "start": round(global_cursor + local_cursor, 3),
                    "end": round(global_cursor + local_cursor + duration, 3),
                    "scene_id": scene_id,
                }
            )
            local_cursor += duration + pause
        video_path = (args.video_dir.resolve() / f"{scene_id}.mp4").resolve()
        scenes.append(
            {
                "id": scene_id,
                "video_path": str(video_path),
                "lines": story_lines,
            }
        )
        timeline_scenes.append(
            {
                "id": scene_id,
                "audio_path": story_lines[0]["audio_path"],
                "duration_seconds": round(local_cursor, 3),
            }
        )
        global_cursor += local_cursor

    manifest = {
        "template": "story_video/v1",
        "title": "杀猪盘反诈短剧《完美恋人》—固定音色完整版",
        "quality_profile": "publish",
        "output_fps": 50,
        "video_fit_mode": "hold_last",
        "cast": cast,
        "scenes": scenes,
    }
    audio_timeline = {
        "title": manifest["title"],
        "duration_seconds": round(global_cursor, 3),
        "scenes": timeline_scenes,
        "lines": global_lines,
    }
    args.output_manifest.parent.mkdir(parents=True, exist_ok=True)
    args.audio_timeline.parent.mkdir(parents=True, exist_ok=True)
    args.output_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.audio_timeline.write_text(
        json.dumps(audio_timeline, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(args.output_manifest.resolve())
    print(args.audio_timeline.resolve())
    print(f"duration_seconds={global_cursor:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
