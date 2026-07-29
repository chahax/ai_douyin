from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def probe_duration(path: Path, ffprobe: str) -> float:
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build full-frame story clips by stretching each accepted I2V shot once "
            "across its dialogue duration. No loops, portrait inserts, crops, or blurred fills."
        )
    )
    parser.add_argument("manifest")
    parser.add_argument("audio_timeline")
    parser.add_argument("base_clip_dir")
    parser.add_argument("replacement_map")
    parser.add_argument("output_dir")
    parser.add_argument("output_manifest")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--fps", type=int, default=25)
    parser.add_argument(
        "--interpolation",
        choices=("minterpolate", "fps"),
        default="minterpolate",
        help=(
            "Frame synthesis used after time stretching. Use fps for inputs that "
            "were already densely interpolated by RIFE."
        ),
    )
    parser.add_argument("--only", action="append")
    parser.add_argument("--exclude", action="append")
    parser.add_argument("--attach-audio", action="store_true")
    args = parser.parse_args()
    if args.fps <= 0:
        raise ValueError("--fps must be positive")

    manifest_path = Path(args.manifest).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    timeline = json.loads(Path(args.audio_timeline).read_text(encoding="utf-8"))
    replacements = json.loads(Path(args.replacement_map).read_text(encoding="utf-8"))
    target_by_id = {
        item["id"]: float(item["duration_seconds"]) for item in timeline["scenes"]
    }
    base_clip_dir = Path(args.base_clip_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    selected = set(args.only or [])
    excluded = set(args.exclude or [])

    report: list[dict[str, object]] = []
    for scene in manifest["scenes"]:
        scene_id = scene["id"]
        if scene_id in excluded or (selected and scene_id not in selected):
            existing = output_dir / f"{scene_id}.mp4"
            if existing.is_file():
                scene["video_path"] = str(existing)
            continue
        source = Path(replacements.get(scene_id, base_clip_dir / f"{scene_id}.mp4")).resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        target_duration = target_by_id[scene_id]
        source_duration = probe_duration(source, args.ffprobe)
        speed_factor = target_duration / source_duration
        output = output_dir / f"{scene_id}.mp4"
        interpolation_filter = (
            f"minterpolate=fps={args.fps}:mi_mode=mci:mc_mode=aobmc:"
            "me_mode=bidir:vsbmc=1"
            if args.interpolation == "minterpolate"
            else f"fps={args.fps}"
        )
        video_filter = (
            f"setpts={speed_factor:.9f}*PTS,"
            f"{interpolation_filter},"
            f"trim=duration={target_duration:.6f},"
            "setpts=PTS-STARTPTS,setsar=1,format=yuv420p"
        )
        subprocess.run(
            [
                args.ffmpeg,
                "-y",
                "-i",
                str(source),
                "-an",
                "-vf",
                video_filter,
                "-r",
                str(args.fps),
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "18",
                "-color_primaries",
                "bt709",
                "-color_trc",
                "bt709",
                "-colorspace",
                "bt709",
                "-movflags",
                "+faststart",
                str(output),
            ],
            check=True,
        )
        scene["video_path"] = str(output)
        report.append(
            {
                "id": scene_id,
                "source": str(source),
                "source_duration_seconds": source_duration,
                "target_duration_seconds": target_duration,
                "speed_factor": speed_factor,
                "output": str(output),
                "composition": "full_frame_original",
                "fps": args.fps,
                "interpolation": args.interpolation,
            }
        )
        print(f"built {scene_id}", flush=True)

    if args.attach_audio:
        audio_by_id = {item["id"]: item["audio_path"] for item in timeline["scenes"]}
        for scene in manifest["scenes"]:
            if len(scene["lines"]) != 1:
                raise ValueError(
                    f"{scene['id']} must contain exactly one line when --attach-audio is used"
                )
            scene["lines"][0]["audio_path"] = audio_by_id[scene["id"]]
            scene["lines"][0]["pause_after_seconds"] = 0.0

    output_manifest = Path(args.output_manifest).resolve()
    output_manifest.parent.mkdir(parents=True, exist_ok=True)
    output_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report_path = output_dir.parent / "fullframe_clip_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(output_manifest)


if __name__ == "__main__":
    main()
