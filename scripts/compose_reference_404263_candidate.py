"""Compose the reviewed 404263-inspired microshots into a local review candidate.

The compositor never reads pixels or audio from the reference video.  It uses
only generated clips listed by the original scene plan, creates narration with
the local Windows Chinese SAPI voice, burns review subtitles, and writes an
auditable non-publishable manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = ROOT / r"data\fanqie_promotion\scene_plans\reference_404263_original_multiflow_v1.json"
DEFAULT_QA_ROOT = ROOT / r"data\qa\reference_404263_multiflow_20260825"
DEFAULT_VOICE_REPORT = (
    DEFAULT_QA_ROOT / "candidates" / "audio_cosyvoice_raw" / "voice_render_report.json"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def probe(path: Path) -> dict[str, object]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration:stream=index,codec_type,codec_name,width,height,avg_frame_rate,channels,sample_rate",
            "-of", "json", str(path),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def duration(path: Path) -> float:
    return float(probe(path)["format"]["duration"])


def srt_time(seconds: float) -> str:
    milliseconds = int(round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def wrap_caption(text: str, width: int = 16) -> str:
    return "\n".join(text[index:index + width] for index in range(0, len(text), width))


def write_concat(path: Path, files: list[Path]) -> None:
    lines = [f"file '{item.as_posix().replace(chr(39), chr(39) * 2)}'" for item in files]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def choose_clip(scene_id: str, workflow: str, qa_root: Path, prefer_ltx: set[str]) -> tuple[str, Path]:
    if workflow == "hybrid" and scene_id in prefer_ltx:
        candidate = qa_root / "renders" / "ltx" / "clips_raw" / f"{scene_id}.mp4"
        if candidate.is_file():
            return "ltx", candidate
    selected = workflow if workflow in {"ltx", "stability"} else "wan"
    candidate = qa_root / "renders" / selected / "clips_raw" / f"{scene_id}.mp4"
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return selected, candidate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow", choices=("wan", "ltx", "hybrid", "stability"), default="wan")
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--qa-root", type=Path, default=DEFAULT_QA_ROOT)
    parser.add_argument(
        "--voice-report",
        type=Path,
        default=DEFAULT_VOICE_REPORT,
        help="Offline CosyVoice voice_render_report.json produced before composition.",
    )
    parser.add_argument(
        "--prefer-ltx",
        default="s04_escalation,s06a_luxury,s08a_raid",
        help="Comma-separated scene IDs used by hybrid mode when an LTX clip exists.",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    plan_path = args.plan.resolve()
    qa_root = args.qa_root.resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("schema_version") != "reference_404263_original_multiflow/v1":
        raise ValueError("unexpected plan schema")
    if plan["delivery"].get("publish_allowed") is not False:
        raise ValueError("candidate plan must remain non-publishable")

    prefer_ltx = {value.strip() for value in args.prefer_ltx.split(",") if value.strip()}
    voice_report_path = args.voice_report.resolve()
    if not voice_report_path.is_file():
        raise FileNotFoundError(
            f"offline CosyVoice report is required before composition: {voice_report_path}"
        )
    voice_report = json.loads(voice_report_path.read_text(encoding="utf-8-sig"))
    voice_by_scene = {
        str(row["scene_id"]): Path(str(row["audio_path"])).resolve()
        for row in voice_report.get("lines", [])
    }
    output_root = qa_root / "candidates" / args.workflow
    visuals = output_root / "visual_segments"
    audio = output_root / "audio_segments"
    work = output_root / "work"
    for directory in (visuals, audio, work):
        directory.mkdir(parents=True, exist_ok=True)

    selected_rows: list[dict[str, object]] = []
    visual_files: list[Path] = []
    audio_files: list[Path] = []
    subtitles: list[str] = []
    cursor = 0.0
    caption_index = 0

    for index, scene in enumerate(plan["scenes"], start=1):
        scene_id = str(scene["id"])
        scene_duration = float(scene["duration_seconds"])
        selected_workflow, source = choose_clip(scene_id, args.workflow, qa_root, prefer_ltx)
        normalized = visuals / f"{index:02d}_{scene_id}.mp4"
        if args.force or not normalized.is_file():
            run([
                "ffmpeg", "-y", "-i", str(source), "-vf",
                (
                    "scale=1080:1920:force_original_aspect_ratio=increase,"
                    "crop=1080:1920,fps=30,"
                    f"tpad=stop_mode=clone:stop_duration=3,trim=duration={scene_duration:.3f},"
                    "setpts=PTS-STARTPTS,format=yuv420p"
                ),
                "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "17",
                "-g", "60", "-video_track_timescale", "90000", str(normalized),
            ])

        narration = str(scene.get("narration") or "").strip()
        fitted_wav = audio / f"{index:02d}_{scene_id}.wav"
        if args.force or not fitted_wav.is_file():
            if narration:
                raw_wav = voice_by_scene.get(scene_id)
                if raw_wav is None or not raw_wav.is_file():
                    raise FileNotFoundError(f"CosyVoice audio missing for {scene_id}: {raw_wav}")
                raw_duration = duration(raw_wav)
                speech_target = max(0.5, scene_duration - 0.18)
                tempo = max(1.0, raw_duration / speech_target)
                run([
                    "ffmpeg", "-y", "-i", str(raw_wav), "-af",
                    f"aresample=48000,atempo={tempo:.8f},apad,atrim=duration={scene_duration:.3f}",
                    "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(fitted_wav),
                ])
            else:
                run([
                    "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                    "-t", f"{scene_duration:.3f}", "-c:a", "pcm_s16le", str(fitted_wav),
                ])

        if narration:
            caption_index += 1
            subtitles.extend([
                str(caption_index),
                f"{srt_time(cursor)} --> {srt_time(cursor + scene_duration - 0.05)}",
                wrap_caption(narration),
                "",
            ])
        visual_files.append(normalized)
        audio_files.append(fitted_wav)
        selected_rows.append({
            "scene_id": scene_id,
            "duration_seconds": scene_duration,
            "selected_workflow": selected_workflow,
            "source_path": str(source),
            "source_sha256": sha256(source),
            "normalized_path": str(normalized),
            "normalized_sha256": sha256(normalized),
            "audio_path": str(fitted_wav),
            "audio_sha256": sha256(fitted_wav),
            "narration": narration,
        })
        cursor += scene_duration
        print(json.dumps({"event": "prepared", "scene_id": scene_id, "workflow": selected_workflow}, ensure_ascii=False), flush=True)

    visual_list = work / "visual_concat.txt"
    audio_list = work / "audio_concat.txt"
    write_concat(visual_list, visual_files)
    write_concat(audio_list, audio_files)
    visual_concat = work / "visual_concat.mp4"
    narration_concat = work / "narration.wav"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(visual_list), "-c", "copy", str(visual_concat)])
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(audio_list), "-c", "copy", str(narration_concat)])

    subtitle_path = output_root / "candidate.zh-CN.srt"
    subtitle_path.write_text("\n".join(subtitles) + "\n", encoding="utf-8-sig")
    subtitle_filter_path = subtitle_path.relative_to(ROOT).as_posix().replace(":", "\\:")
    final_path = output_root / f"reference_404263_original_{args.workflow}_candidate.mp4"
    run([
        "ffmpeg", "-y", "-i", str(visual_concat), "-i", str(narration_concat),
        "-vf",
        (
            f"subtitles='{subtitle_filter_path}':"
            "force_style='FontName=Microsoft YaHei,FontSize=15,PrimaryColour=&H00FFFFFF,"
            "OutlineColour=&H00101010,BorderStyle=3,BackColour=&H70000000,Outline=1,"
            "Shadow=0,MarginV=28,Alignment=2'"
        ),
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", "medium",
        "-crf", "17", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart", "-t", f"{cursor:.3f}", str(final_path),
    ])

    manifest = {
        "schema": "reference_404263_original_candidate/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "title": plan["title"],
        "candidate_mode": args.workflow,
        "plan_path": str(plan_path),
        "plan_sha256": sha256(plan_path),
        "reference_video_pixels_used": False,
        "reference_video_audio_used": False,
        "publish_allowed": False,
        "douyin_upload_allowed": False,
        "fanqie_backfill_allowed": False,
        "voice_engine": "CosyVoice3-0.5B-2512 local offline",
        "voice_report_path": str(voice_report_path),
        "voice_report_sha256": sha256(voice_report_path),
        "duration_seconds": cursor,
        "scenes": selected_rows,
        "subtitle_path": str(subtitle_path),
        "subtitle_sha256": sha256(subtitle_path),
        "video_path": str(final_path),
        "video_sha256": sha256(final_path),
        "probe": probe(final_path),
    }
    manifest_path = output_root / "candidate.manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"event": "complete", "video": str(final_path), "manifest": str(manifest_path)}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
