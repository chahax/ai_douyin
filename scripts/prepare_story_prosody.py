from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply per-scene Edge-TTS prosody overrides to a story_video/v1 manifest."
    )
    parser.add_argument("manifest")
    parser.add_argument("overrides")
    parser.add_argument("output")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    override_path = Path(args.overrides)
    output_path = Path(args.output)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    overrides = json.loads(override_path.read_text(encoding="utf-8"))
    if manifest.get("template") != "story_video/v1":
        raise ValueError("manifest must use template story_video/v1")
    if not isinstance(overrides, dict):
        raise ValueError("overrides must be an object keyed by scene id")

    seen: set[str] = set()
    for scene in manifest["scenes"]:
        scene_id = scene["id"]
        values = overrides.get(scene_id)
        if values is None:
            continue
        if not isinstance(values, dict):
            raise ValueError(f"override for {scene_id} must be an object")
        for line in scene["lines"]:
            for key in ("rate", "volume", "pitch"):
                if key in values:
                    line[key] = values[key]
        seen.add(scene_id)

    unknown = sorted(set(overrides) - seen)
    if unknown:
        raise ValueError(f"prosody overrides reference unknown scenes: {', '.join(unknown)}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(output_path)


if __name__ == "__main__":
    main()
