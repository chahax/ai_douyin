#!/usr/bin/env python
"""Compose ten subtitled 50 fps episodes with contact-safe hand-action cutaways."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "data/qa/wenshu_lawyer_brand_v1"
PROJECT = BASE / "series_v2"
FULL = PROJECT / "sadtalker_fullframe"
GROUP = BASE / "v2_debate/characters/group_master.png"
W, H = 704, 1248


def run(args: list[str]) -> None:
    print(subprocess.list2cmdline(args), flush=True)
    subprocess.run(args, check=True)


def probe(path: Path, audio: bool = False) -> float:
    args = ["ffprobe", "-v", "error"]
    if audio:
        args += ["-select_streams", "a:0", "-show_entries", "stream=duration"]
    else:
        args += ["-show_entries", "format=duration"]
    args += ["-of", "default=nw=1:nk=1", str(path)]
    return float(subprocess.check_output(args, text=True).strip().splitlines()[0])


def ass_time(value: float) -> str:
    cs = max(0, round(value * 100))
    hour, rem = divmod(cs, 360000)
    minute, rem = divmod(rem, 6000)
    second, centi = divmod(rem, 100)
    return f"{hour}:{minute:02d}:{second:02d}.{centi:02d}"


def wrap_cn(text: str, width: int = 17) -> str:
    return r"\N".join(text[i:i + width] for i in range(0, len(text), width))


def make_ass(ep: dict, events: list[dict], total: float, destination: Path) -> None:
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Dialogue,Microsoft YaHei,35,&H00FFFFFF,&H000000FF,&H00100D0B,&H72000000,-1,0,0,0,100,100,0,0,1,3,0.4,2,42,42,82,1",
        "Style: Name,Microsoft YaHei,23,&H00EBD6AA,&H000000FF,&H00100D0B,&H68000000,-1,0,0,0,100,100,0,0,1,2,0,1,34,34,218,1",
        "Style: Title,Microsoft YaHei,38,&H00FFFFFF,&H000000FF,&H00100D0B,&H5A000000,-1,0,0,0,100,100,1,0,1,3,0.4,8,30,30,60,1",
        "Style: Note,Microsoft YaHei,18,&H00D4D4D4,&H000000FF,&H00111111,&H40000000,0,0,0,0,100,100,0,0,1,1.5,0,9,16,16,16,1", "",
        "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        f"Dialogue: 0,{ass_time(0)},{ass_time(total)},Note,,0,0,0,,案件研讨｜非个案法律意见",
        f"Dialogue: 1,{ass_time(0.10)},{ass_time(0.85)},Title,,0,0,0,,{ep['title']}",
    ]
    for event in events:
        lines.append(f"Dialogue: 2,{ass_time(event['start'] + 0.05)},{ass_time(min(event['end'] - 0.10, event['start'] + 1.60))},Name,,0,0,0,,{event['speaker']}｜案件讨论")
        lines.append(f"Dialogue: 3,{ass_time(event['start'] + 0.04)},{ass_time(event['end'] - 0.08)},Dialogue,,0,0,0,,{wrap_cn(event['text'])}")
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")


def choose_hands() -> dict[str, tuple[Path, float, float]]:
    old = BASE / "v2_debate/v4_case_conference/hand_cutaways_ltx"
    generated = Path(r"D:\IT\AI_vido\ComfyUI\output\wenshu_series_v2\hand_library")
    candidates = {
        "许安": (old / "h_xu_align_cards.mp4", 0.35, 0.82),
        "顾承": (old / "h_gu_open_folder.mp4", 0.75, 0.82),
    }
    approval_path = PROJECT / "hand_library_approved.json"
    approved = json.loads(approval_path.read_text(encoding="utf-8")) if approval_path.is_file() else {}
    new_map = {"周宁": "lib_zhou_folder_slide", "顾承新": "lib_gu_card_tap"}
    for role, stem in new_map.items():
        decision = approved.get(stem, {})
        if not decision.get("approved", False):
            continue
        files = sorted(generated.glob(f"{stem}*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
        if files:
            candidates[role] = (
                files[0],
                float(decision["safe_offset_seconds"]),
                float(decision["safe_duration_seconds"]),
            )
    return candidates


def render_talk(source: Path, destination: Path, hand: tuple[Path, float, float] | None) -> float:
    duration = probe(source, audio=True)
    if hand and duration > 2.3:
        hand_path, hand_offset, hand_max_duration = hand
        overlay_start = min(0.82, max(0.45, duration * 0.20))
        overlay_duration = min(0.82, hand_max_duration, duration - overlay_start - 0.40)
        overlay_end = overlay_start + overlay_duration
        run([
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(source), "-ss", f"{hand_offset:.3f}", "-i", str(hand_path),
            "-filter_complex",
            f"[0:v]scale=704:1248:flags=lanczos,fps=25[base];[1:v]scale=704:1248:force_original_aspect_ratio=increase:flags=lanczos,crop=704:1248,fps=25,setpts=PTS-STARTPTS+{overlay_start}/TB[hand];[base][hand]overlay=0:0:enable='between(t,{overlay_start},{overlay_end})':eof_action=pass[v]",
            "-map", "[v]", "-map", "0:a:0", "-t", f"{duration:.6f}", "-c:v", "libx264", "-preset", "fast", "-crf", "17", "-r", "25",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(destination),
        ])
    else:
        run([
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(source), "-map", "0:v:0", "-map", "0:a:0",
            "-vf", "scale=704:1248:flags=lanczos,fps=25,format=yuv420p", "-t", f"{duration:.6f}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "17", "-r", "25", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(destination),
        ])
    return probe(destination)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", action="append")
    args = parser.parse_args()
    catalog = json.loads((PROJECT / "series_catalog.json").read_text(encoding="utf-8"))
    selected = set(args.episode or [])
    hand = choose_hands()
    final_dir = PROJECT / "final"
    work = PROJECT / "compose_work"
    final_dir.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    report = []
    for ep in catalog["episodes"]:
        if selected and ep["episode_id"] not in selected:
            continue
        ep_id = ep["episode_id"]
        ep_dir = work / ep_id
        ep_dir.mkdir(parents=True, exist_ok=True)
        segments, events, cursor = [], [], 0.0
        for index, line in enumerate(ep["lines"], 1):
            source = FULL / f"{line['id']}.mp4"
            if not source.is_file():
                raise FileNotFoundError(source)
            selected_hand = None
            if index == 3:
                selected_hand = hand.get("许安")
            elif index == 4:
                selected_hand = hand.get("周宁")
            elif index == 5:
                selected_hand = hand.get("顾承新") or hand.get("顾承")
            segment = ep_dir / f"{index:02d}.mp4"
            duration = render_talk(source, segment, selected_hand)
            segments.append(segment)
            events.append({"speaker": line["speaker"], "text": line["text"], "start": cursor, "end": cursor + duration})
            cursor += duration
        concat = ep_dir / "concat.txt"
        concat.write_text("\n".join(f"file '{p.as_posix()}'" for p in segments) + "\n", encoding="utf-8")
        joined = ep_dir / "joined25.mp4"
        run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(joined)])
        subtitles = ep_dir / "subtitles.ass"
        make_ass(ep, events, cursor, subtitles)
        escaped = subtitles.as_posix().replace(":", r"\:").replace("'", r"\'")
        output = final_dir / f"{ep_id}_{ep['title']}_50fps.mp4"
        run([
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(joined),
            "-vf", f"subtitles=filename='{escaped}',fps=50,format=yuv420p", "-map", "0:v:0", "-map", "0:a:0",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-r", "50", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(output),
        ])
        report.append({"episode_id": ep_id, "title": ep["title"], "duration_seconds": round(cursor, 3), "output": str(output.resolve())})
        (PROJECT / "final_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"DONE {ep_id} -> {output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
