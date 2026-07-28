from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.content_factory.story_video import StoryVideoManifest


def run(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    subprocess.run(command, cwd=cwd, env=env, check=True)


def newest_result(result_dir: Path, started_at: float) -> Path:
    candidates = [
        path
        for path in result_dir.glob("*.mp4")
        if path.stat().st_mtime >= started_at - 2
    ]
    if not candidates:
        raise RuntimeError(f"SadTalker did not create a top-level result in {result_dir}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def verticalize(
    *,
    ffmpeg: str,
    square_video: Path,
    background: Path,
    output: Path,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    filter_value = (
        "[0:v]scale=704:1248:force_original_aspect_ratio=increase:flags=lanczos,"
        "crop=704:1248,gblur=sigma=30,eq=brightness=-0.12:saturation=0.65,"
        "drawbox=x=20:y=254:w=664:h=664:color=black@0.38:t=fill[bg];"
        "[1:v]scale=640:640:flags=lanczos,setsar=1[face];"
        "[bg][face]overlay=32:266:shortest=1,fps=25,format=yuv420p[outv]"
    )
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-loop",
            "1",
            "-i",
            str(background),
            "-i",
            str(square_video),
            "-filter_complex",
            filter_value,
            "-map",
            "[outv]",
            "-map",
            "1:a",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            "-shortest",
            str(output),
        ],
        check=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate identity-locked, audio-driven story clips with SadTalker."
    )
    parser.add_argument("manifest")
    parser.add_argument("audio_timeline")
    parser.add_argument("anchor_map")
    parser.add_argument("background_dir")
    parser.add_argument("output_dir")
    parser.add_argument("--sadtalker-home", required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--expression-scale", type=float, default=0.65)
    parser.add_argument("--only", action="append")
    args = parser.parse_args()

    manifest = StoryVideoManifest.load(args.manifest)
    timeline = json.loads(Path(args.audio_timeline).read_text(encoding="utf-8"))
    anchors = json.loads(Path(args.anchor_map).read_text(encoding="utf-8"))
    audio_by_scene = {
        item["id"]: Path(item["audio_path"]).resolve() for item in timeline["scenes"]
    }
    root = Path(args.output_dir).resolve()
    square_dir = root / "square"
    vertical_dir = root / "vertical"
    wav_dir = root / "wav"
    temp_dir = root / "temp"
    result_root = root / "runs"
    for path in (square_dir, vertical_dir, wav_dir, temp_dir, result_root):
        path.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["TEMP"] = str(temp_dir)
    env["TMP"] = str(temp_dir)
    selected = set(args.only or [])
    report: list[dict[str, object]] = []
    for index, scene in enumerate(manifest.scenes):
        if selected and scene.scene_id not in selected:
            continue
        speaker = scene.lines[0].speaker
        anchor = Path(anchors[speaker])
        audio = audio_by_scene[scene.scene_id]
        wav_audio = wav_dir / f"{scene.scene_id}.wav"
        if not wav_audio.is_file():
            subprocess.run(
                [
                    args.ffmpeg,
                    "-y",
                    "-i",
                    str(audio),
                    "-ar",
                    "16000",
                    "-ac",
                    "1",
                    "-c:a",
                    "pcm_s16le",
                    str(wav_audio),
                ],
                check=True,
            )
        background = Path(args.background_dir).resolve() / f"{scene.scene_id}.png"
        square = square_dir / f"{scene.scene_id}.mp4"
        vertical = vertical_dir / f"{scene.scene_id}.mp4"
        if not square.is_file():
            scene_results = result_root / scene.scene_id
            scene_results.mkdir(parents=True, exist_ok=True)
            started_at = time.time()
            run(
                [
                    args.python,
                    "inference.py",
                    "--driven_audio",
                    str(wav_audio),
                    "--source_image",
                    str(anchor),
                    "--checkpoint_dir",
                    str(Path(args.sadtalker_home) / "checkpoints"),
                    "--result_dir",
                    str(scene_results),
                    "--size",
                    "256",
                    "--preprocess",
                    "crop",
                    "--still",
                    "--expression_scale",
                    str(args.expression_scale),
                    "--pose_style",
                    "0",
                    "--batch_size",
                    "2",
                ],
                cwd=Path(args.sadtalker_home),
                env=env,
            )
            shutil.copy2(newest_result(scene_results, started_at), square)
        verticalize(
            ffmpeg=args.ffmpeg,
            square_video=square,
            background=background,
            output=vertical,
        )
        report.append(
            {
                "index": index,
                "id": scene.scene_id,
                "speaker": speaker,
                "anchor": str(anchor),
                "audio": str(audio),
                "square": str(square),
                "vertical": str(vertical),
            }
        )
        print(f"generated {scene.scene_id}", flush=True)

    report_path = root / "run_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(report_path)


if __name__ == "__main__":
    main()
