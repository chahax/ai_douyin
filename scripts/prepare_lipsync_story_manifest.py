from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bind rendered line audio and matching lip-sync clips to a story manifest."
    )
    parser.add_argument("manifest")
    parser.add_argument("audio_timeline")
    parser.add_argument("clip_dir")
    parser.add_argument("output")
    args = parser.parse_args()

    manifest_path = Path(args.manifest).resolve()
    timeline = json.loads(Path(args.audio_timeline).read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    clip_dir = Path(args.clip_dir).resolve()
    output_path = Path(args.output).resolve()
    audio_by_scene: dict[str, list[str]] = {}
    for line in timeline["lines"]:
        audio_by_scene.setdefault(line["scene_id"], []).append(line["audio_path"])

    for scene in manifest["scenes"]:
        scene_id = scene["id"]
        clip = clip_dir / f"{scene_id}.mp4"
        if not clip.is_file():
            raise FileNotFoundError(f"lip-sync clip is missing: {clip}")
        paths = audio_by_scene.get(scene_id, [])
        if len(paths) != len(scene["lines"]):
            raise ValueError(
                f"{scene_id} has {len(scene['lines'])} lines but {len(paths)} audio files"
            )
        scene["video_path"] = str(clip)
        for line, audio_path in zip(scene["lines"], paths, strict=True):
            line["audio_path"] = str(Path(audio_path).resolve())

    manifest["video_fit_mode"] = "hold_last"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(output_path)


if __name__ == "__main__":
    main()
