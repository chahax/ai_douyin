"""Build a versioned continuity-first full candidate.

This compositor intentionally does not honour the legacy 72-cut quota.  A
story beat normally uses one forward source window, with a fixed crop and no
automatic still-image tail.  Only motivated UI inserts and a <=0.8 second
exact end-frame settle are accepted by the recipe validator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = ROOT / "data/fanqie_promotion/scene_plans/reference_404263_full_workflows_v2.json"
DEFAULT_QA = ROOT / "data/qa/reference_404263_full_workflows_20260825"
DEFAULT_RECIPE = DEFAULT_QA / "full_candidate_edit_recipes_v2_continuity.json"
DEFAULT_VOICE_REPORT = DEFAULT_QA / "audio_cosyvoice_raw/voice_render_report.json"
FPS = 30


def run(command: list[str], *, timeout: int = 2400) -> None:
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
            "format=duration:stream=index,codec_type,codec_name,width,height,avg_frame_rate,channels,sample_rate",
            "-of", "json", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return json.loads(result.stdout)


def resolve_path(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def source_path(qa_root: Path, spec: dict[str, object], beat_id: str) -> Path:
    family = str(spec["family"])
    scene_id = str(spec.get("scene_id") or beat_id)
    return qa_root / "renders" / family / "clips_raw" / f"{scene_id}.mp4"


def crop_filter() -> str:
    # One transform for every continuity-first source window.  The old
    # compositor varied scale/crop by local cut index, causing visible jumps.
    return (
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920:(iw-1080)/2:(ih-1920)/2"
    )


def render_video_cut(
    source: Path,
    output: Path,
    *,
    start: float,
    source_seconds: float,
    output_seconds: float,
) -> None:
    stretch = output_seconds / source_seconds
    vf = (
        f"{crop_filter()},trim=duration={source_seconds:.6f},"
        f"setpts={stretch:.9f}*(PTS-STARTPTS),fps={FPS},format=yuv420p"
    )
    run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.6f}",
            "-i", str(source), "-vf", vf, "-an", "-c:v", "libx264",
            "-preset", "medium", "-crf", "17", "-g", "60",
            "-video_track_timescale", "90000", "-t", f"{output_seconds:.6f}",
            str(output),
        ]
    )


def render_still(source: Path, output: Path, *, seconds: float) -> None:
    frames = max(1, int(round(seconds * FPS)))
    vf = (
        f"{crop_filter()},loop=loop={frames - 1}:size=1:start=0,"
        f"trim=duration={seconds:.6f},setpts=PTS-STARTPTS,fps={FPS},format=yuv420p"
    )
    run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(source),
            "-t", f"{seconds:.6f}", "-vf", vf, "-an", "-c:v", "libx264",
            "-preset", "medium", "-crf", "17", "-g", "60",
            "-video_track_timescale", "90000", str(output),
        ]
    )


def extract_source_frame(source: Path, output: Path, *, at: float) -> None:
    run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-ss", f"{at:.6f}",
            "-i", str(source), "-frames:v", "1", "-vf", f"{crop_filter()},format=rgb24",
            str(output),
        ],
        timeout=120,
    )


def extract_candidate_frame(source: Path, output: Path, *, at: float) -> None:
    run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-ss", f"{max(0.0, at):.6f}",
            "-i", str(source), "-frames:v", "1", str(output),
        ],
        timeout=120,
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
    if "\n" in text:
        return "\n".join(line.strip() for line in text.splitlines() if line.strip())
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
    chain: list[str] = ["aresample=48000"]
    while speed > 2.0:
        chain.append("atempo=2.0")
        speed /= 2.0
    chain.append(f"atempo={speed:.8f}")
    chain.extend(["apad", f"atrim=duration={target_seconds:.6f}"])
    return ",".join(chain)


def validate_recipe(
    plan: dict[str, object],
    recipe: dict[str, object],
    workflow: str,
) -> list[dict[str, object]]:
    if recipe.get("schema") != "reference_404263_full_candidate_edit_recipes/v2":
        raise ValueError("unexpected continuity recipe schema")
    if recipe.get("publish_allowed") is not False:
        raise ValueError("continuity candidate must remain non-publishable")
    beats = list(plan["beats"])
    mode = dict(dict(recipe.get("modes") or {}).get(workflow) or {})
    if set(mode) != {str(beat["id"]) for beat in beats}:
        missing = {str(beat["id"]) for beat in beats} - set(mode)
        extra = set(mode) - {str(beat["id"]) for beat in beats}
        raise ValueError(f"continuity recipe must cover every beat; missing={missing}, extra={extra}")

    used_ranges: set[tuple[str, str, float, float]] = set()
    for beat in beats:
        beat_id = str(beat["id"])
        cuts = list(dict(mode[beat_id]).get("cuts") or [])
        if not cuts:
            raise ValueError(f"empty continuity recipe: {beat_id}")
        total = sum(float(cut["seconds"]) for cut in cuts)
        if abs(total - float(beat["duration"])) > 0.002:
            raise ValueError(f"duration mismatch for {beat_id}: {total}")
        video_families: set[str] = set()
        for cut in cuts:
            cut_type = str(cut["type"])
            seconds = float(cut["seconds"])
            if cut_type == "video":
                source_seconds = float(cut["source_seconds"])
                if source_seconds <= 0 or seconds / source_seconds > 1.60:
                    raise ValueError(f"excessive slowdown for {beat_id}: {seconds / source_seconds:.3f}x")
                family = str(cut["family"])
                scene_id = str(cut.get("scene_id") or beat_id)
                start = round(float(cut.get("start") or 0.0), 6)
                end = round(start + source_seconds, 6)
                key = (family, scene_id, start, end)
                if key in used_ranges:
                    raise ValueError(f"reused source range: {key}")
                used_ranges.add(key)
                video_families.add(family)
            elif cut_type == "end_hold":
                if seconds > 0.8001:
                    raise ValueError(f"end hold exceeds 0.8s: {beat_id}")
            elif cut_type == "ui_insert":
                if str(beat.get("kind")) != "deterministic_ui" and seconds > 1.2001:
                    raise ValueError(f"motivated UI insert exceeds 1.2s: {beat_id}")
            else:
                raise ValueError(f"unsupported continuity cut type: {cut_type}")
        if len(video_families) > 1:
            raise ValueError(f"cross-engine action splice is forbidden: {beat_id}")
    return beats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", choices=("controlled",), default="controlled")
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--qa-root", type=Path, default=DEFAULT_QA)
    parser.add_argument("--edit-recipes", type=Path, default=DEFAULT_RECIPE)
    parser.add_argument("--voice-report", type=Path, default=DEFAULT_VOICE_REPORT)
    parser.add_argument(
        "--candidate-version",
        choices=("v3", "v4"),
        default="v3",
        help="Artifact namespace; v4 is reserved for the motion re-audit repair.",
    )
    parser.add_argument("--visual-only", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    version_tag = args.candidate_version

    plan_path = args.plan.resolve()
    recipe_path = args.edit_recipes.resolve()
    qa_root = args.qa_root.resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    if plan.get("schema_version") != "reference_404263_full_workflows/v2":
        raise ValueError("unexpected plan schema")
    if dict(plan["delivery"]).get("publish_allowed") is not False:
        raise ValueError("plan must remain non-publishable")
    beats = validate_recipe(plan, recipe, args.workflow)
    mode = dict(dict(recipe["modes"])[args.workflow])

    voice_by_scene: dict[str, Path] = {}
    if not args.visual_only:
        voice_payload = json.loads(args.voice_report.resolve().read_text(encoding="utf-8-sig"))
        voice_by_scene = {
            str(row["scene_id"]): Path(str(row["audio_path"])).resolve()
            for row in voice_payload.get("lines", [])
        }

    output_root = qa_root / "candidates" / args.workflow
    cuts_root = output_root / f"cuts_{version_tag}"
    audio_root = output_root / f"audio_segments_{version_tag}"
    work_root = output_root / f"work_{version_tag}"
    evidence_root = output_root / f"continuity_evidence_{version_tag}"
    for directory in (cuts_root, audio_root, work_root, evidence_root):
        directory.mkdir(parents=True, exist_ok=True)

    cut_files: list[Path] = []
    audio_files: list[Path] = []
    manifest_beats: list[dict[str, object]] = []
    subtitles: list[str] = []
    cut_index = 0
    subtitle_index = 0
    cursor = 0.0

    for beat in beats:
        beat_id = str(beat["id"])
        beat_seconds = float(beat["duration"])
        beat_recipe = dict(mode[beat_id])
        beat_cuts: list[dict[str, object]] = []
        for local_index, spec_value in enumerate(beat_recipe["cuts"], start=1):
            spec = dict(spec_value)
            cut_index += 1
            seconds = float(spec["seconds"])
            cut_path = cuts_root / f"{cut_index:03d}_{beat_id}_{local_index:02d}.mp4"
            cut_type = str(spec["type"])
            row: dict[str, object] = {
                "cut_index": cut_index,
                "local_index": local_index,
                "beat_id": beat_id,
                "timeline_start_seconds": round(cursor + sum(float(item["duration_seconds"]) for item in beat_cuts), 6),
                "duration_seconds": round(seconds, 6),
                "kind": cut_type,
                "transition_out": str(spec.get("transition_out") or "scene_cut"),
                "reason": str(spec.get("reason") or "continuity_first_forward_window"),
                "crop_contract": "fixed_center_crop_v1",
                "path": str(cut_path),
            }
            if cut_type == "video":
                source = source_path(qa_root, spec, beat_id)
                if not source.is_file():
                    raise FileNotFoundError(source)
                start = float(spec.get("start") or 0.0)
                source_seconds = float(spec["source_seconds"])
                if start + source_seconds > duration(source) + 0.04:
                    raise ValueError(f"source window exceeds clip: {beat_id}")
                if args.force or not cut_path.is_file():
                    render_video_cut(
                        source,
                        cut_path,
                        start=start,
                        source_seconds=source_seconds,
                        output_seconds=seconds,
                    )
                row.update({
                    "family": str(spec["family"]),
                    "source_scene_id": str(spec.get("scene_id") or beat_id),
                    "source_path": str(source),
                    "source_sha256": sha256(source),
                    "source_start_seconds": round(start, 6),
                    "source_duration_seconds": round(source_seconds, 6),
                    "playback_stretch": round(seconds / source_seconds, 6),
                })
            elif cut_type == "ui_insert":
                source = resolve_path(str(spec.get("path") or beat["anchor"]))
                if not source.is_file():
                    raise FileNotFoundError(source)
                if args.force or not cut_path.is_file():
                    render_still(source, cut_path, seconds=seconds)
                row.update({
                    "family": "deterministic_ui",
                    "source_path": str(source),
                    "source_sha256": sha256(source),
                    "source_start_seconds": None,
                    "source_duration_seconds": None,
                    "playback_stretch": None,
                })
            else:
                source = source_path(qa_root, spec, beat_id)
                if not source.is_file():
                    raise FileNotFoundError(source)
                at = float(spec["at"])
                frame_path = evidence_root / f"{cut_index:03d}_{beat_id}_exact_end_frame.png"
                if args.force or not frame_path.is_file():
                    extract_source_frame(source, frame_path, at=at)
                if args.force or not cut_path.is_file():
                    render_still(frame_path, cut_path, seconds=seconds)
                row.update({
                    "family": str(spec["family"]),
                    "source_scene_id": str(spec.get("scene_id") or beat_id),
                    "source_path": str(source),
                    "source_sha256": sha256(source),
                    "source_frame_at_seconds": round(at, 6),
                    "source_frame_path": str(frame_path),
                    "source_frame_sha256": sha256(frame_path),
                    "playback_stretch": None,
                })
            row["sha256"] = sha256(cut_path)
            beat_cuts.append(row)
            cut_files.append(cut_path)

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
            "timeline_start_seconds": round(cursor, 6),
            "duration_seconds": beat_seconds,
            "nominal_legacy_cut_count": int(beat["cut_count"]),
            "continuity_cut_count": len(beat_cuts),
            "action": str(beat_recipe.get("action_contract") or beat.get("action") or ""),
            "end_pose_contract": str(beat_recipe.get("end_pose_contract") or beat.get("end_pose") or ""),
            "cuts": beat_cuts,
            "audio_path": str(audio_path),
            "audio_sha256": sha256(audio_path),
            "narration": narration,
        })
        cursor += beat_seconds
        print(json.dumps({"event": "prepared", "beat": beat_id, "cuts": len(beat_cuts)}, ensure_ascii=False), flush=True)

    visual_list = work_root / "visual_concat.txt"
    audio_list = work_root / "audio_concat.txt"
    write_concat(visual_list, cut_files)
    write_concat(audio_list, audio_files)
    visual_concat = work_root / "visual_concat.mp4"
    audio_concat = work_root / "narration.wav"
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(visual_list), "-c", "copy", str(visual_concat)])
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(audio_list), "-c", "copy", str(audio_concat)])

    subtitle_path = output_root / f"candidate_{version_tag}.zh-CN.srt"
    subtitle_path.write_text("\n".join(subtitles) + "\n", encoding="utf-8-sig")
    subtitle_filter_path = subtitle_path.relative_to(ROOT).as_posix().replace(":", "\\:")
    final_path = output_root / f"reference_404263_{args.workflow}_full_candidate_{version_tag}.mp4"
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
    ])

    actual_duration = duration(final_path)
    if abs(actual_duration - float(dict(plan["delivery"])["duration_seconds"])) > 0.12:
        raise RuntimeError(f"candidate duration mismatch: {actual_duration:.3f}s")

    # End-frame evidence is generated only after final assembly, so it records
    # what the reviewer actually sees rather than only the input asset.
    for beat_row in manifest_beats:
        beat_end = float(beat_row["timeline_start_seconds"]) + float(beat_row["duration_seconds"])
        frame_path = evidence_root / f"{beat_row['beat_id']}_visible_end.png"
        extract_candidate_frame(final_path, frame_path, at=beat_end - 1 / FPS)
        beat_row["visible_end_frame_path"] = str(frame_path)
        beat_row["visible_end_frame_sha256"] = sha256(frame_path)

    manifest = {
        "schema": f"reference_404263_full_candidate/{version_tag}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "candidate_mode": args.workflow,
        "artifact_status": "technical_pass",
        "shot_review_status": "pending",
        "transition_review_status": "pending",
        "full_playback_status": "pending",
        "workflow_evidence_status": "single_run_evaluated",
        "release_status": "not_authorized",
        "status": (
            "technical_pass_motion_reaudit_pending"
            if version_tag == "v4"
            else "technical_pass_continuity_review_pending"
        ),
        "plan_path": str(plan_path),
        "plan_sha256": sha256(plan_path),
        "edit_recipe_path": str(recipe_path),
        "edit_recipe_sha256": sha256(recipe_path),
        "continuity_policy": {
            "legacy_cut_quota_enforced": False,
            "automatic_anchor_tail_allowed": False,
            "fixed_crop_per_source_window": True,
            "max_end_hold_seconds": 0.8,
            "max_motivated_ui_insert_seconds": 1.2,
            "max_playback_stretch": 1.6,
            "full_playback_review_required": True
        },
        "reference_video_pixels_used": False,
        "reference_video_audio_used": False,
        "publish_allowed": False,
        "douyin_upload_allowed": False,
        "fanqie_backfill_allowed": False,
        "target_duration_seconds": float(dict(plan["delivery"])["duration_seconds"]),
        "actual_duration_seconds": actual_duration,
        "beat_count": len(beats),
        "nominal_legacy_cut_count": sum(int(beat["cut_count"]) for beat in beats),
        "effective_cut_count": len(cut_files),
        "visual_only": args.visual_only,
        "beats": manifest_beats,
        "subtitle_path": str(subtitle_path),
        "subtitle_sha256": sha256(subtitle_path),
        "video_path": str(final_path),
        "video_sha256": sha256(final_path),
        "probe": probe(final_path),
    }
    manifest_path = output_root / f"candidate.{version_tag}.manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"event": "complete", "video": str(final_path), "manifest": str(manifest_path)}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
