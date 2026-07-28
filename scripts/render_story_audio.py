from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.content_factory.story_video import (
    StoryVideoManifest,
    _duration,
    _render_scene_audio,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render scene-level dialogue audio without composing video."
    )
    parser.add_argument("manifest")
    parser.add_argument("output_dir")
    args = parser.parse_args()

    manifest = StoryVideoManifest.load(args.manifest)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    timeline: list[dict[str, object]] = []
    scenes: list[dict[str, object]] = []
    cursor = 0.0
    for index, scene in enumerate(manifest.scenes):
        audio_path, scene_timeline = _render_scene_audio(
            scene=scene,
            cast=manifest.cast,
            audio_dir=output_dir,
            scene_index=index,
        )
        duration = _duration(audio_path)
        for entry in scene_timeline:
            local_start = float(entry["start"])
            local_end = float(entry["end"])
            entry["start"] = round(cursor + local_start, 3)
            entry["end"] = round(cursor + local_end, 3)
            entry["scene_id"] = scene.scene_id
            timeline.append(entry)
        scenes.append(
            {
                "index": index,
                "id": scene.scene_id,
                "speaker": scene.lines[0].speaker,
                "audio_path": str(audio_path),
                "duration_seconds": round(duration, 3),
            }
        )
        cursor += duration

    result = {
        "title": manifest.title,
        "duration_seconds": round(cursor, 3),
        "scenes": scenes,
        "lines": timeline,
    }
    output_path = output_dir / "story_audio.timeline.json"
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(output_path)


if __name__ == "__main__":
    main()
