"""Compose a complete detailed-script review candidate from approved assets.

Generated I2V clips are preferred when present.  Missing clips deliberately
fall back to deterministic movement on the matching approved keyframe so the
candidate is always timeline-complete and never loops an unrelated shot.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], timeout: int = 2400) -> None:
    subprocess.run(command, cwd=ROOT, check=True, timeout=timeout)


def ffprobe(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration:stream=index,codec_type,codec_name,width,height,avg_frame_rate,channels,sample_rate",
            "-of", "json", str(path),
        ],
        check=True, capture_output=True, text=True, timeout=60,
    )
    return json.loads(result.stdout)


def duration(path: Path) -> float:
    return float(ffprobe(path)["format"]["duration"])


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def srt_time(seconds: float) -> str:
    value = int(round(seconds * 1000))
    hours, value = divmod(value, 3_600_000)
    minutes, value = divmod(value, 60_000)
    secs, millis = divmod(value, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def wrap_zh(text: str, width: int = 15) -> str:
    return "\n".join(text[index:index + width] for index in range(0, len(text), width))


def concat_file(path: Path, files: list[Path]) -> None:
    path.write_text(
        "\n".join(f"file '{item.as_posix().replace(chr(39), chr(39) * 2)}'" for item in files) + "\n",
        encoding="utf-8",
    )


def atempo_filter(raw_seconds: float, target_seconds: float) -> str:
    usable = max(0.35, target_seconds - 0.10)
    speed = max(1.0, raw_seconds / usable)
    pieces = ["aresample=48000"]
    while speed > 2.0:
        pieces.append("atempo=2.0")
        speed /= 2.0
    pieces.extend([f"atempo={speed:.8f}", "apad", f"atrim=duration={target_seconds:.6f}"])
    return ",".join(pieces)


def render_keyframe(image: Path, output: Path, seconds: float, index: int) -> None:
    frames = max(1, round(seconds * 30))
    zoom_step = 0.00045 if index % 2 == 0 else 0.00032
    horizontal = "iw/2-(iw/zoom/2)" if index % 3 else "iw/2-(iw/zoom/2)+4*sin(on/18)"
    vf = (
        "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        f"zoompan=z='min(zoom+{zoom_step:.5f},1.032)':x='{horizontal}':"
        f"y='ih/2-(ih/zoom/2)':d={frames}:s=1080x1920:fps=30,"
        f"trim=duration={seconds:.6f},setpts=PTS-STARTPTS,format=yuv420p"
    )
    run([
        "ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(image),
        "-t", f"{seconds:.6f}", "-vf", vf, "-an", "-c:v", "libx264", "-preset", "fast",
        "-crf", "18", "-g", "60", "-video_track_timescale", "90000", str(output),
    ])


def render_generated_clip(source: Path, output: Path, seconds: float) -> None:
    raw = duration(source)
    if raw + 0.03 < seconds:
        timing = f"tpad=stop_mode=clone:stop_duration={seconds - raw + 0.04:.6f},trim=duration={seconds:.6f}"
    else:
        timing = f"trim=duration={seconds:.6f}"
    vf = (
        "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        f"{timing},fps=30,setpts=PTS-STARTPTS,format=yuv420p"
    )
    run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(source), "-vf", vf, "-an",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-g", "60",
        "-video_track_timescale", "90000", str(output),
    ])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--keyframe-dir", type=Path, required=True)
    parser.add_argument("--clip-dir", type=Path, required=True)
    parser.add_argument("--voice-report", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    project_path = args.project.resolve()
    project = json.loads(project_path.read_text(encoding="utf-8"))
    if project.get("publish_allowed") is not False:
        raise ValueError("review candidate project must remain non-publishable")
    shots = list(project["shots"])
    expected_duration = float(project["duration_seconds"])
    if len(shots) != 69 or abs(sum(float(row["duration"]) for row in shots) - expected_duration) > 0.002:
        raise ValueError("detailed project must contain the complete 69-segment timeline")

    keyframe_dir = args.keyframe_dir.resolve()
    clip_dir = args.clip_dir.resolve()
    output_dir = args.output_dir.resolve()
    visual_dir = output_dir / "visual_segments"
    audio_dir = output_dir / "audio_segments"
    work_dir = output_dir / "work"
    for directory in (visual_dir, audio_dir, work_dir):
        directory.mkdir(parents=True, exist_ok=True)

    voice_by_scene: dict[str, Path] = {}
    if args.voice_report and args.voice_report.resolve().is_file():
        voice_payload = json.loads(args.voice_report.resolve().read_text(encoding="utf-8-sig"))
        voice_by_scene = {str(row["scene_id"]): Path(row["audio_path"]).resolve() for row in voice_payload["lines"]}

    visual_files: list[Path] = []
    audio_files: list[Path] = []
    manifest_rows: list[dict] = []
    subtitles: list[str] = []
    cursor = 0.0
    subtitle_index = 0
    for index, shot in enumerate(shots, start=1):
        shot_id = str(shot["id"])
        seconds = float(shot["duration"])
        keyframe = keyframe_dir / f"{shot_id}.png"
        clip = clip_dir / f"{shot_id}.mp4"
        visual = visual_dir / f"{index:03d}_{shot_id}.mp4"
        if clip.is_file():
            source_kind = "generated_i2v"
            source = clip
            if args.force or not visual.is_file():
                render_generated_clip(clip, visual, seconds)
        else:
            source_kind = "deterministic_keyframe_motion"
            source = keyframe
            if not keyframe.is_file():
                raise FileNotFoundError(keyframe)
            if args.force or not visual.is_file():
                render_keyframe(keyframe, visual, seconds, index)
        visual_files.append(visual)

        audio = audio_dir / f"{index:03d}_{shot_id}.wav"
        voice = voice_by_scene.get(shot_id)
        if args.force or not audio.is_file():
            if voice and voice.is_file():
                run([
                    "ffmpeg", "-y", "-loglevel", "error", "-i", str(voice),
                    "-af", atempo_filter(duration(voice), seconds), "-ar", "48000", "-ac", "2",
                    "-c:a", "pcm_s16le", str(audio),
                ])
            else:
                run([
                    "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "anullsrc=r=48000:cl=stereo", "-t", f"{seconds:.6f}",
                    "-c:a", "pcm_s16le", str(audio),
                ])
        audio_files.append(audio)

        caption = str(shot.get("caption") or "").strip()
        if caption:
            subtitle_index += 1
            subtitles.extend([
                str(subtitle_index),
                f"{srt_time(cursor)} --> {srt_time(cursor + max(0.12, seconds - 0.04))}",
                wrap_zh(caption), "",
            ])
        manifest_rows.append({
            "id": shot_id, "duration_seconds": seconds, "render_mode": shot.get("render_mode"),
            "source_kind": source_kind, "source": str(source), "visual_segment": str(visual),
            "audio_source": str(voice) if voice else None, "caption": caption,
        })
        cursor += seconds
        print(json.dumps({"event": "prepared", "id": shot_id, "source": source_kind}, ensure_ascii=False), flush=True)

    visual_list = work_dir / "visual_concat.txt"
    audio_list = work_dir / "audio_concat.txt"
    concat_file(visual_list, visual_files)
    concat_file(audio_list, audio_files)
    visual_master = work_dir / "visual_master.mp4"
    audio_master = work_dir / "audio_master.wav"
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(visual_list), "-c", "copy", str(visual_master)])
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(audio_list), "-c", "copy", str(audio_master)])

    subtitle_path = output_dir / "candidate.zh-CN.srt"
    subtitle_path.write_text("\n".join(subtitles) + "\n", encoding="utf-8-sig")
    subtitle_ref = subtitle_path.relative_to(ROOT).as_posix().replace(":", "\\:")
    final = output_dir / f"reference_404263_{project['style']}_detailed_full_candidate_v1.mp4"
    run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(visual_master), "-i", str(audio_master),
        "-vf", (
            f"subtitles='{subtitle_ref}':force_style='FontName=Microsoft YaHei,FontSize=15,"
            "PrimaryColour=&H00FFFFFF,OutlineColour=&H00101010,BorderStyle=3,BackColour=&H70000000,"
            "Outline=1,Shadow=0,MarginV=30,Alignment=2'"
        ),
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart", "-t", f"{expected_duration:.6f}", str(final),
    ])
    actual = duration(final)
    if abs(actual - expected_duration) > 0.12:
        raise RuntimeError(f"candidate duration mismatch: {actual:.3f} != {expected_duration:.3f}")
    manifest = {
        "schema": "reference_404263_detailed_full_candidate/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending_user_review",
        "style": project["style"],
        "project": str(project_path),
        "reference_video_pixels_used": bool(project.get("reference_video_pixels_used", False)),
        "reference_video_pixels_used_for_pose_guidance": bool(
            project.get("reference_video_pixels_used_for_pose_guidance", False)
        ),
        "reference_video_pixels_directly_included": bool(
            project.get("reference_video_pixels_directly_included", False)
        ),
        "reference_video_audio_used": bool(project.get("reference_video_audio_used", False)),
        "publish_allowed": False,
        "duration_seconds": actual,
        "segment_count": len(shots),
        "generated_i2v_count": sum(row["source_kind"] == "generated_i2v" for row in manifest_rows),
        "deterministic_count": sum(row["source_kind"] == "deterministic_keyframe_motion" for row in manifest_rows),
        "video": str(final),
        "sha256": sha256(final),
        "probe": ffprobe(final),
        "segments": manifest_rows,
    }
    manifest_path = output_dir / "candidate.manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"event": "complete", "video": str(final), "manifest": str(manifest_path)}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
