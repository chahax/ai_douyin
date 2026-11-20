"""Compose the 24-shot character-first big-head 3D candidate.

The source LTX clips are generated slightly longer than each source beat so the
whole action can be retimed into the exact 103.63-second narration timeline.
The candidate remains review-only and cannot be published or backfilled.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QA = ROOT / "data/qa/reference_404263_bighead3d_full_20260826"
DEFAULT_PROJECT = DEFAULT_QA / "story_project.json"
DEFAULT_VIDEO_RUN = DEFAULT_QA / "video_run"
DEFAULT_VOICE_REPORT = (
    ROOT
    / "data/qa/reference_404263_full_workflows_20260825/audio_cosyvoice_raw/voice_render_report.json"
)
FPS = 30


def run(command: list[str], *, timeout: int = 3600) -> None:
    subprocess.run(command, cwd=ROOT, check=True, timeout=timeout)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return float(result.stdout.strip())


def probe(path: Path) -> dict[str, object]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration,size,bit_rate:stream=index,codec_type,codec_name,width,height,avg_frame_rate,channels,sample_rate",
            "-of", "json", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return json.loads(result.stdout)


def crop_filter() -> str:
    return (
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920:(iw-1080)/2:(ih-1920)/2"
    )


def write_concat(path: Path, files: list[Path]) -> None:
    lines = [f"file '{item.as_posix().replace(chr(39), chr(39) * 2)}'" for item in files]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def srt_time(seconds: float) -> str:
    milliseconds = int(round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def wrap_caption(text: str, width: int = 16) -> str:
    if len(text) <= width:
        return text
    line_count = (len(text) + width - 1) // width
    base, extra = divmod(len(text), line_count)
    sizes = [base + (1 if index < extra else 0) for index in range(line_count)]
    lines: list[str] = []
    cursor = 0
    for size in sizes:
        lines.append(text[cursor:cursor + size])
        cursor += size
    punctuation = set("，。！？；：、,.!?;:")
    for index in range(1, len(lines)):
        while lines[index] and lines[index][0] in punctuation:
            lines[index - 1] += lines[index][0]
            lines[index] = lines[index][1:]
    return "\n".join(line for line in lines if line)


def audio_filter(raw_seconds: float, target_seconds: float) -> str:
    usable = max(0.45, target_seconds - 0.12)
    speed = max(1.0, raw_seconds / usable)
    chain = ["aresample=48000"]
    while speed > 2.0:
        chain.append("atempo=2.0")
        speed /= 2.0
    chain.extend([f"atempo={speed:.8f}", "apad", f"atrim=duration={target_seconds:.6f}"])
    return ",".join(chain)


def render_cut(source: Path, destination: Path, seconds: float) -> dict[str, float]:
    source_seconds = duration(source)
    if source_seconds < seconds - 0.08:
        raise ValueError(f"source clip shorter than beat: {source} ({source_seconds:.3f} < {seconds:.3f})")
    stretch = seconds / source_seconds
    run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(source),
            "-vf",
            f"{crop_filter()},setpts={stretch:.9f}*(PTS-STARTPTS),fps={FPS},format=yuv420p",
            "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-g", "60",
            "-video_track_timescale", "90000", "-t", f"{seconds:.6f}", str(destination),
        ]
    )
    return {"source_duration_seconds": source_seconds, "playback_stretch": stretch}


def extract_review_frame(video: Path, output: Path, at: float) -> None:
    run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-ss", f"{max(0.0, at):.6f}",
            "-i", str(video), "-frames:v", "1", "-vf",
            "scale=270:480:force_original_aspect_ratio=increase,crop=270:480", str(output),
        ],
        timeout=180,
    )


def build_contact_sheet(items: list[tuple[str, Path]], output: Path) -> None:
    columns = 4
    cell_width, cell_height = 270, 510
    rows = (len(items) + columns - 1) // columns
    canvas = Image.new("RGB", (columns * cell_width, rows * cell_height), "black")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    for index, (shot_id, path) in enumerate(items):
        image = Image.open(path).convert("RGB")
        image = image.resize((cell_width, 480), Image.Resampling.LANCZOS)
        x = (index % columns) * cell_width
        y = (index // columns) * cell_height
        canvas.paste(image, (x, y))
        draw.text((x + 8, y + 487), shot_id, fill="white", font=font)
    canvas.save(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=DEFAULT_PROJECT)
    parser.add_argument("--video-run", type=Path, default=DEFAULT_VIDEO_RUN)
    parser.add_argument("--voice-report", type=Path, default=DEFAULT_VOICE_REPORT)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    project_path = args.project.resolve()
    video_run = args.video_run.resolve()
    project = json.loads(project_path.read_text(encoding="utf-8"))
    if project.get("publish_allowed") is not False:
        raise ValueError("project must remain non-publishable")
    shots = list(project["shots"])
    voice_payload = json.loads(args.voice_report.resolve().read_text(encoding="utf-8-sig"))
    voices = {str(item["scene_id"]): Path(str(item["audio_path"])).resolve() for item in voice_payload["lines"]}

    candidate_root = DEFAULT_QA / "candidate"
    cuts_root = candidate_root / "cuts"
    audio_root = candidate_root / "audio_segments"
    review_root = candidate_root / "review_frames"
    work_root = candidate_root / "work"
    for directory in (candidate_root, cuts_root, audio_root, review_root, work_root):
        directory.mkdir(parents=True, exist_ok=True)

    cut_files: list[Path] = []
    audio_files: list[Path] = []
    manifest_shots: list[dict[str, object]] = []
    subtitles: list[str] = []
    contact_items: list[tuple[str, Path]] = []
    cursor = 0.0

    for index, shot in enumerate(shots, start=1):
        shot_id = str(shot["id"])
        seconds = float(shot["duration"])
        source = video_run / "clips" / f"{shot_id}.mp4"
        if not source.is_file():
            raise FileNotFoundError(source)
        cut = cuts_root / f"{index:02d}_{shot_id}.mp4"
        timing = render_cut(source, cut, seconds) if args.force or not cut.is_file() else {
            "source_duration_seconds": duration(source),
            "playback_stretch": seconds / duration(source),
        }
        cut_files.append(cut)

        audio = audio_root / f"{index:02d}_{shot_id}.wav"
        raw = voices.get(shot_id)
        if raw is None or not raw.is_file():
            raise FileNotFoundError(f"voice missing for {shot_id}: {raw}")
        if args.force or not audio.is_file():
            run(
                [
                    "ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-af",
                    audio_filter(duration(raw), seconds), "-ar", "48000", "-ac", "2",
                    "-c:a", "pcm_s16le", str(audio),
                ]
            )
        audio_files.append(audio)

        narration = str(shot.get("narration") or "").strip()
        subtitles.extend(
            [
                str(index),
                f"{srt_time(cursor)} --> {srt_time(cursor + seconds - 0.05)}",
                wrap_caption(narration),
                "",
            ]
        )
        mid_frame = review_root / f"{index:02d}_{shot_id}_mid.png"
        if args.force or not mid_frame.is_file():
            extract_review_frame(cut, mid_frame, seconds / 2)
        contact_items.append((shot_id, mid_frame))
        manifest_shots.append(
            {
                "index": index,
                "id": shot_id,
                "timeline_start_seconds": round(cursor, 6),
                "duration_seconds": seconds,
                "source_path": str(source),
                "source_sha256": sha256(source),
                "cut_path": str(cut),
                "cut_sha256": sha256(cut),
                "audio_path": str(audio),
                "audio_sha256": sha256(audio),
                "narration": narration,
                "continuity_from": shot.get("continuity_from"),
                **timing,
            }
        )
        cursor += seconds
        print(json.dumps({"event": "prepared", "shot": shot_id, "index": index}, ensure_ascii=False), flush=True)

    video_list = work_root / "video_concat.txt"
    audio_list = work_root / "audio_concat.txt"
    write_concat(video_list, cut_files)
    write_concat(audio_list, audio_files)
    visual = work_root / "visual.mp4"
    narration_audio = work_root / "narration.wav"
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(video_list), "-c", "copy", str(visual)])
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(audio_list), "-c", "copy", str(narration_audio)])

    subtitle = candidate_root / "reference_404263_bighead3d_full_v1.zh-CN.srt"
    subtitle.write_text("\n".join(subtitles) + "\n", encoding="utf-8-sig")
    subtitle_rel = subtitle.relative_to(ROOT).as_posix().replace(":", "\\:")
    final = candidate_root / "reference_404263_bighead3d_full_candidate_v1.mp4"
    run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(visual), "-i", str(narration_audio),
            "-vf",
            (
                f"subtitles='{subtitle_rel}':"
                "force_style='FontName=Microsoft YaHei,FontSize=15,PrimaryColour=&H00FFFFFF,"
                "OutlineColour=&H00101010,BorderStyle=3,BackColour=&H70000000,Outline=1,"
                "Shadow=0,MarginV=28,Alignment=2'"
            ),
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", "medium",
            "-crf", "17", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:a", "aac",
            "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", "-t", f"{cursor:.6f}", str(final),
        ]
    )
    actual_duration = duration(final)
    if abs(actual_duration - cursor) > 0.12:
        raise RuntimeError(f"candidate duration mismatch: {actual_duration:.3f} vs {cursor:.3f}")

    contact = candidate_root / "reference_404263_bighead3d_full_candidate_v1_contact.png"
    build_contact_sheet(contact_items, contact)
    manifest = {
        "schema": "reference_404263_bighead3d_full_candidate/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "technical_generation_complete_review_pending",
        "release_status": "not_authorized",
        "publish_allowed": False,
        "douyin_upload_allowed": False,
        "fanqie_backfill_allowed": False,
        "reference_video_pixels_used": False,
        "reference_video_audio_used": False,
        "project_path": str(project_path),
        "project_sha256": sha256(project_path),
        "target_duration_seconds": cursor,
        "actual_duration_seconds": actual_duration,
        "shot_count": len(shots),
        "effective_cut_count": len(shots),
        "continuity_chain_count": sum(1 for shot in shots if shot.get("continuity_from")),
        "shots": manifest_shots,
        "subtitle_path": str(subtitle),
        "subtitle_sha256": sha256(subtitle),
        "contact_sheet_path": str(contact),
        "contact_sheet_sha256": sha256(contact),
        "video_path": str(final),
        "video_sha256": sha256(final),
        "probe": probe(final),
    }
    manifest_path = candidate_root / "candidate_v1.manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"event": "complete", "video": str(final), "manifest": str(manifest_path)}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
