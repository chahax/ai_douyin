from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


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


def ass_filter(path: Path) -> str:
    value = path.resolve().as_posix().replace(":", r"\:")
    value = value.replace("'", r"\'")
    return f"ass='{value}'"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build a direction-locked story without visual loops. Each accepted raw shot "
            "is used once, stretched continuously to its dialogue duration, then interpolated."
        )
    )
    parser.add_argument("timeline")
    parser.add_argument("clip_dir")
    parser.add_argument("safe_ranges")
    parser.add_argument("audio_source")
    parser.add_argument("subtitles")
    parser.add_argument("output_dir")
    parser.add_argument("--fps", type=int, default=50)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--preset", default="medium")
    parser.add_argument("--crf", type=int, default=18)
    parser.add_argument(
        "--interpolation-guard-seconds",
        type=float,
        default=0.35,
        help=(
            "Extra pre-interpolation timeline used to absorb minterpolate's edge-frame loss. "
            "The result is still trimmed to the exact target duration."
        ),
    )
    args = parser.parse_args()

    timeline_path = Path(args.timeline).resolve()
    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    safe_ranges = json.loads(Path(args.safe_ranges).read_text(encoding="utf-8"))
    clip_dir = Path(args.clip_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    processed_dir = output_dir / "clips_50fps"
    processed_dir.mkdir(parents=True, exist_ok=True)

    report: list[dict[str, object]] = []
    outputs: list[Path] = []
    for index, scene in enumerate(timeline["scenes"], start=1):
        scene_id = scene["id"]
        source = clip_dir / f"{scene_id}.mp4"
        if not source.is_file():
            raise FileNotFoundError(source)

        source_duration = probe_duration(source, args.ffprobe)
        selected = safe_ranges.get(scene_id, {})
        start = float(selected.get("start_seconds", 0.0))
        end = float(selected.get("end_seconds", source_duration))
        if not (0 <= start < end <= source_duration + 0.05):
            raise ValueError(f"invalid safe range for {scene_id}: {start}..{end}")

        usable_duration = end - start
        target_duration = float(scene["duration_seconds"])
        guarded_duration = target_duration + args.interpolation_guard_seconds
        stretch = guarded_duration / usable_duration
        output = processed_dir / f"{index:02d}_{scene_id}.mp4"
        vf = (
            f"trim=start={start:.6f}:end={end:.6f},setpts=PTS-STARTPTS,"
            f"setpts={stretch:.9f}*PTS,"
            f"minterpolate=fps={args.fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1,"
            f"trim=duration={target_duration:.6f},setpts=PTS-STARTPTS,setsar=1,format=yuv420p"
        )
        run(
            [
                args.ffmpeg,
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(source),
                "-an",
                "-vf",
                vf,
                "-r",
                str(args.fps),
                "-c:v",
                "libx264",
                "-preset",
                args.preset,
                "-crf",
                str(args.crf),
                "-color_primaries",
                "bt709",
                "-color_trc",
                "bt709",
                "-colorspace",
                "bt709",
                "-movflags",
                "+faststart",
                str(output),
            ]
        )
        outputs.append(output)
        report.append(
            {
                "id": scene_id,
                "source": str(source),
                "source_duration_seconds": source_duration,
                "safe_start_seconds": start,
                "safe_end_seconds": end,
                "target_duration_seconds": target_duration,
                "interpolation_guard_seconds": args.interpolation_guard_seconds,
                "stretch_factor": stretch,
                "output": str(output),
                "fps": args.fps,
                "loop_count": 0,
            }
        )
        print(f"built {index:02d}/{len(timeline['scenes'])}: {scene_id}", flush=True)

    concat_list = output_dir / "concat.txt"
    concat_list.write_text(
        "".join(f"file '{item.as_posix()}'\n" for item in outputs), encoding="utf-8"
    )
    silent_video = output_dir / "perfect_lover_direction_locked_silent.mp4"
    run(
        [
            args.ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(silent_video),
        ]
    )

    audio_source = Path(args.audio_source).resolve()
    subtitles = Path(args.subtitles).resolve()
    final_video = output_dir / "perfect_lover_direction_locked_v1_50fps.mp4"
    run(
        [
            args.ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(silent_video),
            "-i",
            str(audio_source),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-vf",
            ass_filter(subtitles),
            "-c:v",
            "libx264",
            "-preset",
            args.preset,
            "-crf",
            str(args.crf),
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(final_video),
        ]
    )

    report_path = output_dir / "build_report.json"
    report_path.write_text(
        json.dumps(
            {
                "timeline": str(timeline_path),
                "duration_seconds": timeline["duration_seconds"],
                "fps": args.fps,
                "audio_source": str(audio_source),
                "subtitles": str(subtitles),
                "silent_video": str(silent_video),
                "final_video": str(final_video),
                "shots": report,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(final_video)


if __name__ == "__main__":
    main()
