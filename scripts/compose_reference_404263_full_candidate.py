"""Compose one complete 103.63s candidate from a single audited workflow family.

Each candidate uses the same 24-beat/72-cut performance contract. Generated
motion plays forward once at native speed; long beats are completed with
deterministic insert/keyframe cuts instead of loops or excessive slow motion.
Reference-video pixels and audio are never read by this compositor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = ROOT / r"data\fanqie_promotion\scene_plans\reference_404263_full_workflows_v2.json"
DEFAULT_QA = ROOT / r"data\qa\reference_404263_full_workflows_20260825"
DEFAULT_EDIT_RECIPES = DEFAULT_QA / "full_candidate_edit_recipes_v1.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def run(command: list[str], *, timeout: int = 1200) -> None:
    subprocess.run(command, cwd=ROOT, check=True, timeout=timeout)


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
            "format=duration:stream=index,codec_type,codec_name,width,height,avg_frame_rate,channels,sample_rate",
            "-of", "json", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return json.loads(result.stdout)


def resolve_project_path(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def srt_time(seconds: float) -> str:
    milliseconds = int(round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def wrap_caption(text: str, width: int = 16) -> str:
    if "\n" in text:
        return "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if len(text) <= width:
        return text

    # Balance short Chinese captions across lines instead of leaving a one- or
    # two-character tail.  In particular, punctuation must never start a line.
    line_count = (len(text) + width - 1) // width
    base, extra = divmod(len(text), line_count)
    sizes = [base + (1 if index < extra else 0) for index in range(line_count)]
    lines: list[str] = []
    cursor = 0
    for size in sizes:
        lines.append(text[cursor:cursor + size])
        cursor += size

    forbidden_line_starts = set("，。！？；：、,.!?;:")
    for index in range(1, len(lines)):
        while lines[index] and lines[index][0] in forbidden_line_starts:
            lines[index - 1] += lines[index][0]
            lines[index] = lines[index][1:]
    return "\n".join(line for line in lines if line)


def write_concat(path: Path, files: list[Path]) -> None:
    lines = [f"file '{item.as_posix().replace(chr(39), chr(39) * 2)}'" for item in files]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def crop_filter(variant: int, profile: str = "default") -> str:
    if profile == "face":
        return (
            "scale=1380:2454:force_original_aspect_ratio=increase,"
            "crop=1080:1920:(iw-1080)/2:0,"
            "fps=30,setpts=PTS-STARTPTS,format=yuv420p"
        )
    if profile != "default":
        raise ValueError(f"unsupported crop profile: {profile}")
    filters = [
        "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
        "scale=1210:2152:force_original_aspect_ratio=increase,crop=1080:1920:(iw-1080)/2:0",
        "scale=1280:2276:force_original_aspect_ratio=increase,crop=1080:1920:(iw-1080)/2:(ih-1920)*0.62",
        "scale=1160:2062:force_original_aspect_ratio=increase,crop=1080:1920:(iw-1080)/2:(ih-1920)/2",
    ]
    return filters[variant % len(filters)] + ",fps=30,setpts=PTS-STARTPTS,format=yuv420p"


def render_video_cut(
    source: Path,
    output: Path,
    *,
    start: float,
    seconds: float,
    variant: int,
    profile: str = "default",
) -> None:
    run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.6f}",
            "-i", str(source), "-t", f"{seconds:.6f}", "-vf", crop_filter(variant, profile),
            "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "17",
            "-g", "60", "-video_track_timescale", "90000", str(output),
        ]
    )


def render_anchor_cut(anchor: Path, output: Path, *, seconds: float, variant: int) -> None:
    frames = max(1, int(round(seconds * 30)))
    direction = -1 if variant % 2 else 1
    x_expr = "iw/2-(iw/zoom/2)" if direction > 0 else "iw/2-(iw/zoom/2)+6*sin(on/20)"
    zoom = "min(zoom+0.00030,1.025)"
    vf = (
        f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        f"zoompan=z='{zoom}':x='{x_expr}':y='ih/2-(ih/zoom/2)':"
        f"d={frames}:s=1080x1920:fps=30,trim=duration={seconds:.6f},"
        "setpts=PTS-STARTPTS,format=yuv420p"
    )
    run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(anchor),
            "-t", f"{seconds:.6f}", "-vf", vf, "-an", "-c:v", "libx264",
            "-preset", "medium", "-crf", "17", "-g", "60",
            "-video_track_timescale", "90000", str(output),
        ]
    )


def selected_family(beat_id: str, mode: str) -> str:
    if mode in {"ltx", "wan"}:
        return mode
    move_body_beats = {
        "p04_enter_phone_room", "p11_batch_money_celebration",
        "p15_male_luxury", "p23_denial",
    }
    if beat_id in move_body_beats:
        return "wan_animate"
    wan_body_beats = {
        "p01_nightlife_hook", "p07_learn_pipeline", "p16_female_spending_montage",
        "p17_pool_boast_peak", "p20_police_entry", "p21_control_and_evidence",
    }
    return "wan" if beat_id in wan_body_beats else "ltx"


def audio_filter(raw_seconds: float, target_seconds: float) -> str:
    usable = max(0.45, target_seconds - 0.12)
    speed = max(1.0, raw_seconds / usable)
    chain: list[str] = ["aresample=48000"]
    while speed > 2.0:
        chain.append("atempo=2.0")
        speed /= 2.0
    chain.append(f"atempo={speed:.8f}")
    chain.extend(["apad", f"atrim=duration={target_seconds:.6f}"])
    return ",".join(chain)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", choices=("ltx", "wan", "controlled"), required=True)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--qa-root", type=Path, default=DEFAULT_QA)
    parser.add_argument("--voice-report", type=Path, default=None)
    parser.add_argument("--edit-recipes", type=Path, default=DEFAULT_EDIT_RECIPES)
    parser.add_argument("--visual-only", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    plan_path = args.plan.resolve()
    qa_root = args.qa_root.resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("schema_version") != "reference_404263_full_workflows/v2":
        raise ValueError("unexpected plan schema")
    if plan["delivery"].get("publish_allowed") is not False:
        raise ValueError("candidate must remain non-publishable before user review")
    beats = list(plan["beats"])
    if len(beats) != 24 or sum(int(beat["cut_count"]) for beat in beats) != 72:
        raise ValueError("v2 contract requires exactly 24 beats and 72 cuts")
    recipe_path = args.edit_recipes.resolve()
    recipe_payload = json.loads(recipe_path.read_text(encoding="utf-8"))
    if recipe_payload.get("schema") != "reference_404263_full_candidate_edit_recipes/v1":
        raise ValueError("unexpected edit recipe schema")
    mode_recipes = dict(recipe_payload.get("modes", {}).get(args.workflow) or {})

    voice_by_scene: dict[str, Path] = {}
    if not args.visual_only:
        if args.voice_report is None or not args.voice_report.resolve().is_file():
            raise FileNotFoundError("--voice-report is required unless --visual-only is used")
        voice_payload = json.loads(args.voice_report.resolve().read_text(encoding="utf-8-sig"))
        voice_by_scene = {
            str(row["scene_id"]): Path(str(row["audio_path"])).resolve()
            for row in voice_payload.get("lines", [])
        }

    output_root = qa_root / "candidates" / args.workflow
    cuts_root = output_root / "cuts"
    audio_root = output_root / "audio_segments"
    work_root = output_root / "work"
    for directory in (cuts_root, audio_root, work_root):
        directory.mkdir(parents=True, exist_ok=True)

    cut_files: list[Path] = []
    audio_files: list[Path] = []
    manifest_beats: list[dict[str, object]] = []
    subtitles: list[str] = []
    cursor = 0.0
    subtitle_index = 0
    cut_index = 0

    for beat in beats:
        beat_id = str(beat["id"])
        beat_seconds = float(beat["duration"])
        cut_count = int(beat["cut_count"])
        anchor = resolve_project_path(str(beat["anchor"]))
        if not anchor.is_file():
            raise FileNotFoundError(anchor)
        source: Path | None = None
        family = "deterministic"
        source_scene_id: str | None = None
        source_seconds = 0.0
        generated_cut_count = 0
        beat_cut_rows: list[dict[str, object]] = []
        recipe = dict(mode_recipes.get(beat_id) or {})
        if recipe:
            cut_specs = list(recipe.get("cuts") or [])
            if len(cut_specs) != cut_count:
                raise ValueError(f"edit recipe cut count mismatch for {beat_id}")
            recipe_total = sum(float(spec["seconds"]) for spec in cut_specs)
            if abs(recipe_total - beat_seconds) > 0.002:
                raise ValueError(f"edit recipe duration mismatch for {beat_id}: {recipe_total}")
            family = "reviewed_recipe"
            generated_budget = 0.0
            for local_index, spec in enumerate(cut_specs):
                cut_index += 1
                seconds = float(spec["seconds"])
                source_type = str(spec["type"])
                cut_path = cuts_root / f"{cut_index:03d}_{beat_id}_{local_index + 1:02d}.mp4"
                if source_type == "video":
                    cut_family = str(spec["family"])
                    cut_scene_id = str(spec.get("scene_id") or beat_id)
                    cut_source = qa_root / "renders" / cut_family / "clips_raw" / f"{cut_scene_id}.mp4"
                    cut_start = float(spec.get("start") or 0.0)
                    crop_profile = str(spec.get("crop_profile") or "default")
                    if not cut_source.is_file():
                        raise FileNotFoundError(cut_source)
                    if cut_start + seconds > duration(cut_source) + 0.08:
                        raise ValueError(f"reviewed window exceeds source for {beat_id} cut {local_index + 1}")
                    if args.force or not cut_path.is_file():
                        render_video_cut(
                            cut_source,
                            cut_path,
                            start=cut_start,
                            seconds=seconds,
                            variant=local_index,
                            profile=crop_profile,
                        )
                    generated_budget += seconds
                    row_kind = "reviewed_video_window"
                    row_family = cut_family
                    row_source = cut_source
                    row_start: float | None = cut_start
                elif source_type == "anchor":
                    value = str(spec.get("path") or beat["anchor"])
                    cut_source = resolve_project_path(value)
                    if not cut_source.is_file():
                        raise FileNotFoundError(cut_source)
                    if args.force or not cut_path.is_file():
                        render_anchor_cut(cut_source, cut_path, seconds=seconds, variant=local_index)
                    row_kind = "reviewed_deterministic_anchor"
                    row_family = "deterministic"
                    row_source = cut_source
                    row_start = None
                else:
                    raise ValueError(f"unsupported edit recipe source type for {beat_id}: {source_type}")
                row = {
                    "cut_index": cut_index,
                    "local_index": local_index + 1,
                    "duration_seconds": round(seconds, 6),
                    "kind": row_kind,
                    "family": row_family,
                    "source_path": str(row_source),
                    "source_start_seconds": round(row_start, 6) if row_start is not None else None,
                    "recipe_reason": str(spec.get("reason") or recipe.get("reason") or "reviewed_override"),
                    "path": str(cut_path),
                    "sha256": sha256(cut_path),
                }
                beat_cut_rows.append(row)
                cut_files.append(cut_path)
        else:
            if str(beat.get("kind")) in {"generated", "derived_generated"}:
                family = selected_family(beat_id, args.workflow)
                source_scene_id = str(beat.get("source_scene_id") or beat_id)
                source = qa_root / "renders" / family / "clips_raw" / f"{source_scene_id}.mp4"
                if not source.is_file():
                    raise FileNotFoundError(source)
                source_seconds = max(0.0, duration(source) - 0.06)
                generated_cut_count = max(1, cut_count - 1)
            generated_budget = (
                min(source_seconds, beat_seconds * generated_cut_count / cut_count)
                if source is not None
                else 0.0
            )
            generated_each = generated_budget / generated_cut_count if generated_cut_count else 0.0
            source_cursor = 0.0
            for local_index in range(cut_count):
                cut_index += 1
                is_generated = source is not None and local_index < generated_cut_count
                seconds = generated_each if is_generated else (beat_seconds - generated_budget) / (cut_count - generated_cut_count)
                if seconds <= 0:
                    raise ValueError(f"invalid cut duration for {beat_id}")
                cut_path = cuts_root / f"{cut_index:03d}_{beat_id}_{local_index + 1:02d}.mp4"
                if args.force or not cut_path.is_file():
                    if is_generated:
                        render_video_cut(
                            source,
                            cut_path,
                            start=source_cursor,
                            seconds=seconds,
                            variant=local_index,
                        )
                    else:
                        render_anchor_cut(anchor, cut_path, seconds=seconds, variant=local_index)
                row = {
                    "cut_index": cut_index,
                    "local_index": local_index + 1,
                    "duration_seconds": round(seconds, 6),
                    "kind": "generated_forward" if is_generated else "deterministic_anchor",
                    "family": family if is_generated else "deterministic",
                    "source_path": str(source) if is_generated else str(anchor),
                    "source_start_seconds": round(source_cursor, 6) if is_generated else None,
                    "path": str(cut_path),
                    "sha256": sha256(cut_path),
                }
                beat_cut_rows.append(row)
                cut_files.append(cut_path)
                if is_generated:
                    source_cursor += seconds

        narration = str(beat.get("narration") or "").strip()
        caption = str(beat.get("caption") or narration).strip()
        audio_path = audio_root / f"{beat_id}.wav"
        if args.force or not audio_path.is_file():
            if args.visual_only or not narration:
                run([
                    "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "anullsrc=r=48000:cl=stereo", "-t", f"{beat_seconds:.6f}",
                    "-c:a", "pcm_s16le", str(audio_path),
                ])
            else:
                raw = voice_by_scene.get(beat_id)
                if raw is None or not raw.is_file():
                    raise FileNotFoundError(f"voice missing for {beat_id}: {raw}")
                run([
                    "ffmpeg", "-y", "-loglevel", "error", "-i", str(raw),
                    "-af", audio_filter(duration(raw), beat_seconds), "-ar", "48000",
                    "-ac", "2", "-c:a", "pcm_s16le", str(audio_path),
                ])
        audio_files.append(audio_path)
        if narration:
            subtitle_index += 1
            subtitles.extend([
                str(subtitle_index),
                f"{srt_time(cursor)} --> {srt_time(cursor + beat_seconds - 0.05)}",
                wrap_caption(caption),
                "",
            ])
        manifest_beats.append({
            "beat_id": beat_id,
            "duration_seconds": beat_seconds,
            "cut_count": cut_count,
            "selected_family": family,
            "source_scene_id": source_scene_id,
            "generated_source_path": str(source) if source else None,
            "generated_source_sha256": sha256(source) if source else None,
            "generated_budget_seconds": round(generated_budget, 6),
            "anchor_path": str(anchor),
            "anchor_sha256": sha256(anchor),
            "cuts": beat_cut_rows,
            "audio_path": str(audio_path),
            "audio_sha256": sha256(audio_path),
            "narration": narration,
        })
        cursor += beat_seconds
        print(json.dumps({"event": "prepared", "beat": beat_id, "cuts": cut_count, "family": family}, ensure_ascii=False), flush=True)

    visual_list = work_root / "visual_concat.txt"
    audio_list = work_root / "audio_concat.txt"
    write_concat(visual_list, cut_files)
    write_concat(audio_list, audio_files)
    visual_concat = work_root / "visual_concat.mp4"
    audio_concat = work_root / "narration.wav"
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(visual_list), "-c", "copy", str(visual_concat)])
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(audio_list), "-c", "copy", str(audio_concat)])

    subtitle_path = output_root / "candidate.zh-CN.srt"
    subtitle_path.write_text("\n".join(subtitles) + "\n", encoding="utf-8-sig")
    subtitle_filter_path = subtitle_path.relative_to(ROOT).as_posix().replace(":", "\\:")
    final_path = output_root / f"reference_404263_{args.workflow}_full_candidate_v2.mp4"
    run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(visual_concat), "-i", str(audio_concat),
        "-vf", (
            f"subtitles='{subtitle_filter_path}':"
            "force_style='FontName=Microsoft YaHei,FontSize=15,PrimaryColour=&H00FFFFFF,"
            "OutlineColour=&H00101010,BorderStyle=3,BackColour=&H70000000,Outline=1,"
            "Shadow=0,MarginV=28,Alignment=2'"
        ),
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", "medium",
        "-crf", "17", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:a", "aac",
        "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", "-t",
        f"{cursor:.6f}", str(final_path),
    ], timeout=2400)

    actual_duration = duration(final_path)
    manifest = {
        "schema": "reference_404263_full_candidate/v2",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "candidate_mode": args.workflow,
        "status": "pending_full_visual_review",
        "plan_path": str(plan_path),
        "plan_sha256": sha256(plan_path),
        "edit_recipe_path": str(recipe_path),
        "edit_recipe_sha256": sha256(recipe_path),
        "reference_video_pixels_used": False,
        "reference_video_audio_used": False,
        "publish_allowed": False,
        "douyin_upload_allowed": False,
        "fanqie_backfill_allowed": False,
        "target_duration_seconds": float(plan["delivery"]["duration_seconds"]),
        "actual_duration_seconds": actual_duration,
        "beat_count": len(beats),
        "effective_cut_count": len(cut_files),
        "visual_only": args.visual_only,
        "beats": manifest_beats,
        "subtitle_path": str(subtitle_path),
        "subtitle_sha256": sha256(subtitle_path),
        "video_path": str(final_path),
        "video_sha256": sha256(final_path),
        "probe": probe(final_path),
    }
    if abs(actual_duration - float(plan["delivery"]["duration_seconds"])) > 0.12:
        raise RuntimeError(f"candidate duration mismatch: {actual_duration:.3f}s")
    if len(cut_files) != int(plan["delivery"]["effective_cut_count"]):
        raise RuntimeError("candidate cut count mismatch")
    manifest_path = output_root / "candidate.manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"event": "complete", "video": str(final_path), "manifest": str(manifest_path)}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
