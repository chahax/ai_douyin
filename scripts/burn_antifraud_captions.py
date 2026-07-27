from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


CALLOUTS = {
    "03_foreign_number": "境外来电  00 开头号码",
    "05_transfer": "资金核查  ·  确认转账",
    "06_police_call": "110 来电",
    "08_relief_warning": "真警察不会通过电话办案\\N更不会让你转账！",
}


def ass_time(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    whole_seconds, cs = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{cs:02d}"


def ass_escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}").replace("\n", r"\N")


def scene_ranges(timeline: dict) -> dict[str, tuple[float, float]]:
    ranges: dict[str, tuple[float, float]] = {}
    for line in timeline["lines"]:
        scene_id = line["scene_id"]
        start = float(line["start"])
        end = float(line["end"])
        if scene_id not in ranges:
            ranges[scene_id] = (start, end)
        else:
            ranges[scene_id] = (min(ranges[scene_id][0], start), max(ranges[scene_id][1], end))
    return ranges


def write_ass(timeline_path: Path, output_path: Path) -> None:
    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    events: list[str] = []
    for line in timeline["lines"]:
        text = ass_escape(line["text"])
        events.append(
            f"Dialogue: 0,{ass_time(float(line['start']))},{ass_time(float(line['end']))},"
            f"Subtitle,,0,0,0,,{text}"
        )

    ranges = scene_ranges(timeline)
    for scene_id, text in CALLOUTS.items():
        if scene_id not in ranges:
            continue
        start, end = ranges[scene_id]
        style = "Slogan" if scene_id == "08_relief_warning" else "Callout"
        events.append(
            f"Dialogue: 1,{ass_time(start)},{ass_time(end)},{style},,0,0,0,,{text}"
        )

    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 704
PlayResY: 1248
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Subtitle,Microsoft YaHei,42,&H00FFFFFF,&H000000FF,&H00121212,&H76000000,-1,0,0,0,100,100,0,0,1,3,1,2,44,44,86,1
Style: Callout,Microsoft YaHei,43,&H0000E7FF,&H000000FF,&H00101010,&H88000000,-1,0,0,0,100,100,1,0,1,3,1,8,38,38,92,1
Style: Slogan,Microsoft YaHei,45,&H0029F3FF,&H000000FF,&H00101010,&HCC101010,-1,0,0,0,100,100,1,0,3,18,0,8,36,36,95,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    output_path.write_text(header + "\n".join(events) + "\n", encoding="utf-8-sig")


def ffmpeg_ass_path(path: Path) -> str:
    value = path.resolve().as_posix()
    return value.replace(":", r"\:")


def main() -> None:
    parser = argparse.ArgumentParser(description="Burn deterministic Chinese captions and anti-fraud UI callouts.")
    parser.add_argument("video")
    parser.add_argument("timeline")
    parser.add_argument("output")
    parser.add_argument("--ass-output")
    args = parser.parse_args()

    video = Path(args.video)
    timeline = Path(args.timeline)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    ass_output = Path(args.ass_output) if args.ass_output else output.with_suffix(".ass")
    write_ass(timeline, ass_output)
    filter_value = f"ass='{ffmpeg_ass_path(ass_output)}'"
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(video), "-vf", filter_value,
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(output),
        ],
        check=True,
    )
    print(output)


if __name__ == "__main__":
    main()
