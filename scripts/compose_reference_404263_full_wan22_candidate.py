"""Assemble the strict 404263 Wan/DWPose full review candidate.

Only clips produced by ``run_reference_404263_full_wan22_production.py`` are
accepted as visual inputs.  Missing clips are a hard error; there is no still
image, old-candidate, or generic push-in fallback.  Previously rendered local
CosyVoice dialogue/silence segments may be reused because they contain no old
visual pixels or source-video audio.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = (
    ROOT
    / "data/qa/reference_404263_detailed_two_style_full_20260826/bighead3d"
    / "story_project.json"
)
PRODUCTION = ROOT / "data/qa/reference_404263_full_wan22_production_20260827"
AUDIO_SEGMENTS = (
    ROOT
    / "data/qa/reference_404263_detailed_two_style_full_20260826/candidates"
    / "bighead3d/audio_segments"
)
DEFAULT_OUTPUT = ROOT / "data/qa/reference_404263_full_wan22_candidate_20260827"


def run(command: list[str], timeout: int = 3600) -> None:
    completed = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, timeout=timeout,
    )
    if completed.returncode:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n"
            + completed.stderr[-5000:]
        )


def ffprobe(path: Path) -> dict:
    completed = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration:stream=index,codec_type,codec_name,width,height,avg_frame_rate,channels,sample_rate",
            "-of", "json", str(path),
        ],
        cwd=ROOT, check=True, capture_output=True, text=True, timeout=60,
    )
    return json.loads(completed.stdout)


def duration(path: Path) -> float:
    return float(ffprobe(path)["format"]["duration"])


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def concat_file(path: Path, files: list[Path]) -> None:
    path.write_text(
        "\n".join(f"file '{item.as_posix().replace(chr(39), chr(39) * 2)}'" for item in files) + "\n",
        encoding="utf-8",
    )


def srt_time(seconds: float) -> str:
    value = int(round(seconds * 1000))
    hours, value = divmod(value, 3_600_000)
    minutes, value = divmod(value, 60_000)
    secs, millis = divmod(value, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def wrap_zh(text: str, width: int = 15) -> str:
    return "\n".join(text[index:index + width] for index in range(0, len(text), width))


def normalize_visual(source: Path, output: Path, seconds: float) -> dict[str, float]:
    raw = duration(source)
    speed_ratio = seconds / raw
    vf = (
        "scale=720:1280:force_original_aspect_ratio=increase:flags=lanczos,"
        "crop=720:1280,setsar=1,"
        f"setpts={speed_ratio:.10f}*PTS,fps=30,"
        f"trim=duration={seconds:.6f},setpts=PTS-STARTPTS,format=yuv420p"
    )
    run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(source), "-vf", vf,
        "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-g",
        "60", "-video_track_timescale", "90000", "-movflags", "+faststart",
        str(output),
    ])
    return {"raw_duration_seconds": raw, "timeline_speed_ratio": speed_ratio}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=PROJECT)
    parser.add_argument("--production-dir", type=Path, default=PRODUCTION)
    parser.add_argument("--audio-dir", type=Path, default=AUDIO_SEGMENTS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    project_path = args.project.resolve()
    production_dir = args.production_dir.resolve()
    audio_dir = args.audio_dir.resolve()
    output_dir = args.output_dir.resolve()
    project = json.loads(project_path.read_text(encoding="utf-8"))
    shots = list(project["shots"])
    expected_duration = float(project["duration_seconds"])
    if len(shots) != 69 or abs(expected_duration - 104.3) > 0.001:
        raise ValueError("assembly requires the locked 69-segment / 104.3-second project")

    visual_dir = output_dir / "visual_segments"
    work_dir = output_dir / "work"
    visual_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    audio_files = sorted(audio_dir.glob("*.wav"))
    if len(audio_files) != 69:
        raise ValueError(f"expected 69 local audio segments, got {len(audio_files)}")
    expected_audio_names = [f"{index:03d}_{shot['id']}.wav" for index, shot in enumerate(shots, 1)]
    if [path.name for path in audio_files] != expected_audio_names:
        raise ValueError("audio segment names do not match the locked timeline")

    rows: list[dict[str, object]] = []
    visual_files: list[Path] = []
    subtitles: list[str] = []
    subtitle_index = 0
    cursor = 0.0
    for index, shot in enumerate(shots, start=1):
        shot_id = str(shot["id"])
        source = production_dir / "clips" / shot_id / f"{shot_id}.mp4"
        report_path = production_dir / "clips" / shot_id / "render.report.json"
        if not source.is_file() or not report_path.is_file():
            raise FileNotFoundError(f"strict production clip missing: {shot_id}")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if bool(report.get("old_candidate_visual_used", False)):
            raise ValueError(f"forbidden old visual provenance on shot {shot_id}")
        seconds = float(shot["duration"])
        visual = visual_dir / f"{index:03d}_{shot_id}.mp4"
        if args.force or not visual.is_file():
            timing = normalize_visual(source, visual, seconds)
        else:
            timing = {
                "raw_duration_seconds": duration(source),
                "timeline_speed_ratio": seconds / duration(source),
            }
        visual_files.append(visual)
        caption = str(shot.get("caption") or "").strip()
        if caption:
            subtitle_index += 1
            subtitles.extend([
                str(subtitle_index),
                f"{srt_time(cursor)} --> {srt_time(cursor + max(0.12, seconds - 0.04))}",
                wrap_zh(caption),
                "",
            ])
        rows.append({
            "id": shot_id,
            "timeline_start_seconds": cursor,
            "timeline_end_seconds": cursor + seconds,
            "duration_seconds": seconds,
            "renderer": report.get("renderer"),
            "production_clip": str(source),
            "production_clip_sha256": sha256(source),
            "normalized_visual": str(visual),
            "audio_segment": str(audio_files[index - 1]),
            "audio_segment_sha256": sha256(audio_files[index - 1]),
            "caption": caption,
            **timing,
        })
        cursor += seconds
        print(json.dumps({"event": "normalized", "shot": shot_id}), flush=True)

    subtitle_path = output_dir / "reference_404263_full.zh-CN.srt"
    subtitle_path.write_text("\n".join(subtitles) + "\n", encoding="utf-8-sig")
    visual_list = work_dir / "visual_concat.txt"
    audio_list = work_dir / "audio_concat.txt"
    concat_file(visual_list, visual_files)
    concat_file(audio_list, audio_files)
    visual_master = work_dir / "visual_master_720x1280_30fps.mp4"
    audio_master = work_dir / "dialogue_master_48k.wav"
    run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
        "-i", str(visual_list), "-c", "copy", str(visual_master),
    ])
    run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
        "-i", str(audio_list), "-c", "copy", str(audio_master),
    ])

    subtitle_ref = subtitle_path.relative_to(ROOT).as_posix().replace(":", "\\:")
    final = output_dir / "reference_404263_full_wan22_review_candidate_720x1280.mp4"
    run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(visual_master), "-i",
        str(audio_master), "-vf",
        (
            f"subtitles='{subtitle_ref}':force_style='FontName=Microsoft YaHei,FontSize=15,"
            "PrimaryColour=&H00FFFFFF,OutlineColour=&H00101010,BorderStyle=3,"
            "BackColour=&H70000000,Outline=1,Shadow=0,MarginV=38,Alignment=2'"
        ),
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", "fast",
        "-crf", "18", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:a", "aac",
        "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", "-t",
        f"{expected_duration:.6f}", str(final),
    ])
    actual = duration(final)
    if abs(actual - expected_duration) > 0.12:
        raise RuntimeError(f"candidate duration mismatch: {actual:.3f} != {expected_duration:.3f}")
    manifest = {
        "schema": "reference_404263_full_wan22_candidate/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending_full_playback_qa",
        "approved_style": "cinematic_3d_bighead_adult",
        "forbidden_style": "controlled_v4_photorealistic",
        "segment_count": len(shots),
        "duration_seconds": actual,
        "old_69_candidate_video_used": False,
        "old_69_candidate_visual_segments_used": False,
        "generic_first_frame_push_used": False,
        "source_video_used_for_dwpose_only": True,
        "source_video_rgb_directly_included": False,
        "source_video_audio_used": False,
        "audio_provenance": "local_CosyVoice_dialogue_and_timeline_silence_from_locked_script",
        "video": str(final),
        "video_sha256": sha256(final),
        "probe": ffprobe(final),
        "subtitles": str(subtitle_path),
        "segments": rows,
    }
    manifest_path = output_dir / "candidate.manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"event": "complete", "video": str(final), "manifest": str(manifest_path)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
