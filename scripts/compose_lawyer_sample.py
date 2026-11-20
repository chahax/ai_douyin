#!/usr/bin/env python
"""Edit the newly generated lawyer clips, local voices, ambience and subtitles."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


TRIM_END = {
    "01_verdict": 2.60,
    "02_mother": 1.05,
    "03_observation": 2.60,
    "04_report": 0.52,
    "05_twin": 2.60,
    "06_reveal": 2.60,
}


def run(command: list[str]) -> None:
    print("RUN", subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, check=True)


def ass_time(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, remain = divmod(centiseconds, 360000)
    minutes, remain = divmod(remain, 6000)
    secs, cs = divmod(remain, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def wrap_cn(text: str, width: int = 13) -> str:
    if len(text) <= width:
        return text
    cut = width
    for punctuation in "，。！？；":
        pos = text.rfind(punctuation, 0, width + 3)
        if pos >= width - 4:
            cut = pos + 1
            break
    return text[:cut] + r"\N" + text[cut:]


def write_ass(path: Path, timeline: list[dict], total: float) -> None:
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 704",
        "PlayResY: 1248",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Default,Microsoft YaHei,43,&H00FFFFFF,&H000000FF,&H00111116,&H9A000000,-1,0,0,0,100,100,0,0,1,3.2,0.7,2,46,46,132,1",
        "Style: Title,Microsoft YaHei,64,&H00E6F2FF,&H000000FF,&H00100C0B,&H70000000,-1,0,0,0,100,100,2,0,1,3.5,1.2,8,30,30,86,1",
        "Style: Notice,Microsoft YaHei,23,&H00D8D8D8,&H000000FF,&H00111111,&H60000000,0,0,0,0,100,100,0,0,1,2,0,9,20,22,26,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        f"Dialogue: 0,{ass_time(0)},{ass_time(min(total, 2.5))},Title,,0,0,0,,《第七码》",
        f"Dialogue: 0,{ass_time(0)},{ass_time(total)},Notice,,0,0,0,,AI生成剧情 · 虚构演绎",
    ]
    for item in timeline:
        subtitle = wrap_cn(f"{item['speaker']}：{item['text']}")
        lines.append(
            f"Dialogue: 0,{ass_time(item['start'])},{ass_time(item['end'])},Default,,0,0,0,,{subtitle}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir", type=Path)
    args = parser.parse_args()
    root = args.project_dir.resolve()
    timeline_path = root / "audio" / "timeline.json"
    payload = json.loads(timeline_path.read_text(encoding="utf-8"))
    timeline = payload["timeline"]
    total = float(payload["total_duration"])

    edit_dir = root / "edit"
    edit_dir.mkdir(parents=True, exist_ok=True)
    processed: list[Path] = []
    for item in timeline:
        shot_id = item["id"]
        source = root / "clips_ltx" / f"{shot_id}.mp4"
        pattern = edit_dir / f"{shot_id}_pingpong.mp4"
        output = edit_dir / f"{shot_id}_edit.mp4"
        trim_end = TRIM_END[shot_id]
        run([
            "ffmpeg", "-y", "-i", str(source),
            "-filter_complex",
            f"[0:v]trim=start=0:end={trim_end},setpts=PTS-STARTPTS,split=2[f][r];[r]reverse[rr];[f][rr]concat=n=2:v=1:a=0,fps=25,format=yuv420p[v]",
            "-map", "[v]", "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "18", str(pattern),
        ])
        segment_duration = float(item["duration"]) + float(item["pause"])
        run([
            "ffmpeg", "-y", "-stream_loop", "-1", "-i", str(pattern), "-t", f"{segment_duration:.3f}",
            "-vf", "eq=contrast=1.045:saturation=0.92:brightness=-0.018,fps=25,format=yuv420p",
            "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-movflags", "+faststart", str(output),
        ])
        processed.append(output)

    concat_file = edit_dir / "video_concat.txt"
    concat_file.write_text("\n".join(f"file '{p.as_posix()}'" for p in processed) + "\n", encoding="utf-8")
    silent_video = edit_dir / "silent_concat.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(silent_video)])

    audio_mix = edit_dir / "dialogue_mix.wav"
    audio_inputs: list[str] = []
    filters: list[str] = []
    labels: list[str] = []
    for index, item in enumerate(timeline):
        audio_inputs.extend(["-i", item["file"]])
        delay = round(float(item["start"]) * 1000)
        label = f"a{index}"
        filters.append(f"[{index}:a]aresample=48000,adelay={delay}:all=1,volume=1.04[{label}]")
        labels.append(f"[{label}]")
    filters.append(f"anoisesrc=color=brown:sample_rate=48000:duration={total:.3f},lowpass=f=240,volume=0.011[amb]")
    twin_start = next(float(x["start"]) for x in timeline if x["id"] == "05_twin")
    filters.append(f"sine=frequency=52:sample_rate=48000:duration=0.55,afade=t=out:st=0.05:d=0.50,adelay={round(twin_start * 1000)}:all=1,volume=0.11[hit]")
    labels.extend(["[amb]", "[hit]"])
    filters.append("".join(labels) + f"amix=inputs={len(labels)}:duration=longest:normalize=0,alimiter=limit=0.93[outa]")
    run(["ffmpeg", "-y", *audio_inputs, "-filter_complex", ";".join(filters), "-map", "[outa]", "-t", f"{total:.3f}", "-c:a", "pcm_s16le", str(audio_mix)])

    subtitles = edit_dir / "subtitles.ass"
    write_ass(subtitles, timeline, total)
    escaped_ass = subtitles.as_posix().replace(":", r"\:").replace("'", r"\'")
    final_path = root / "lawyer_seven_code_sample_v1.mp4"
    run([
        "ffmpeg", "-y", "-i", str(silent_video), "-i", str(audio_mix),
        "-vf", f"subtitles=filename='{escaped_ass}'",
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(final_path),
    ])

    manifest = {
        "title": "第七码",
        "final": str(final_path),
        "duration": total,
        "visual_model": "LTX-Video 2.3 22B distilled FP8 (local)",
        "keyframe_model": "FLUX.1 Schnell FP8 (local)",
        "voice_model": payload.get("engine", "CosyVoice3 local"),
        "source_policy": "All visuals, dialogue, voices and edit assets were newly generated for this sample; no earlier project video was reused.",
        "shots": [str(p) for p in processed],
    }
    (root / "provenance.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
