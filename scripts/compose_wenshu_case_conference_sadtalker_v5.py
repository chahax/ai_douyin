from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEBATE = ROOT / "data" / "qa" / "wenshu_lawyer_brand_v1" / "v2_debate"
PROJECT = DEBATE / "v4_case_conference"
LIPSYNC = PROJECT / "sadtalker_fullframe"
REACTIONS = DEBATE / "reactions_ltx"
GROUP = DEBATE / "characters" / "group_master.png"
SEGMENTS = PROJECT / "segments25_sadtalker"
W, H = 704, 1248

ORDER = [
    ("still", "intro", 1.10, "group"),
    ("talk", "01", None, None),
    ("talk", "02", None, None),
    ("talk", "03", None, None),
    ("reaction", "xu_considers", 0.90, "r_xu_counter.mp4"),
    ("talk", "04", None, None),
    ("talk", "05", None, None),
    ("talk", "06", None, None),
    ("reaction", "zhou_listens", 0.85, "r_zhou_listen.mp4"),
    ("talk", "07", None, None),
    ("talk", "08", None, None),
    ("talk", "09", None, None),
    ("talk", "10", None, None),
    ("reaction", "gu_prepares", 0.75, "r_gu_gesture.mp4"),
    ("talk", "11", None, None),
    ("talk", "12", None, None),
    ("talk", "13", None, None),
    ("talk", "14", None, None),
    ("talk", "15", None, None),
    ("still", "close", 0.80, "group"),
]


def run(args: list[str]) -> None:
    print(subprocess.list2cmdline(args), flush=True)
    subprocess.run(args, check=True)


def probe(path: Path, selector: str | None = None) -> float:
    args = ["ffprobe", "-v", "error"]
    if selector:
        args.extend(["-select_streams", selector])
    args.extend(
        [
            "-show_entries",
            "stream=duration" if selector else "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ]
    )
    return float(subprocess.check_output(args, text=True).strip().splitlines()[0])


def ass_time(value: float) -> str:
    centiseconds = max(0, round(value * 100))
    hour, remainder = divmod(centiseconds, 360000)
    minute, remainder = divmod(remainder, 6000)
    second, centisecond = divmod(remainder, 100)
    return f"{hour}:{minute:02d}:{second:02d}.{centisecond:02d}"


def wrap_cn(text: str, width: int = 17) -> str:
    return r"\N".join(text[i : i + width] for i in range(0, len(text), width))


def make_ass(events: list[dict[str, object]], total: float) -> Path:
    path = PROJECT / "subtitles_v5_sadtalker.ass"
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {W}",
        f"PlayResY: {H}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Dialogue,Microsoft YaHei,36,&H00FFFFFF,&H000000FF,&H00100D0B,&H72000000,-1,0,0,0,100,100,0,0,1,3,0.5,2,44,44,84,1",
        "Style: Name,Microsoft YaHei,23,&H00EBD6AA,&H000000FF,&H00100D0B,&H68000000,-1,0,0,0,100,100,0,0,1,2,0,1,36,36,220,1",
        "Style: Source,Microsoft YaHei,18,&H00D6D6D6,&H000000FF,&H00111111,&H48000000,0,0,0,0,100,100,0,0,1,1.5,0,9,18,18,18,1",
        "Style: Title,Microsoft YaHei,40,&H00FFFFFF,&H000000FF,&H00100D0B,&H5A000000,-1,0,0,0,100,100,1,0,1,3,0.5,8,34,34,62,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        f"Dialogue: 0,{ass_time(0)},{ass_time(total)},Source,,0,0,0,,案件讨论｜（2021）湘01民初548号",
        f"Dialogue: 1,{ass_time(0.12)},{ass_time(1.05)},Title,,0,0,0,,同一笔钱，两场官司",
    ]
    role_labels = {
        "周宁": "主持讨论",
        "顾承": "付款方视角",
        "许安": "收款方视角",
    }
    for event in events:
        if event["kind"] != "talk":
            continue
        start = float(event["start"])
        end = float(event["end"])
        speaker = str(event["speaker"])
        text = str(event["text"])
        lines.append(
            f"Dialogue: 2,{ass_time(start + 0.08)},{ass_time(min(end - 0.12, start + 1.80))},Name,,0,0,0,,{speaker}｜{role_labels[speaker]}"
        )
        lines.append(
            f"Dialogue: 3,{ass_time(start + 0.05)},{ass_time(end - 0.10)},Dialogue,,0,0,0,,{wrap_cn(text)}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return path


def talk_segment(item: dict[str, object], destination: Path) -> float:
    source = LIPSYNC / f"{item['id']}.mp4"
    audio_duration = probe(source, "a:0")
    # The video and the playback audio are already generated from the same final
    # CosyVoice WAV. Preserve timing exactly: no speed change, tmix or interpolation.
    run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-vf",
            "scale=704:1248:flags=lanczos,tpad=stop_mode=clone:stop_duration=0.04,fps=25,format=yuv420p",
            "-af",
            "aresample=48000",
            "-t",
            f"{audio_duration:.6f}",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "17",
            "-r",
            "25",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ac",
            "2",
            "-ar",
            "48000",
            "-movflags",
            "+faststart",
            str(destination),
        ]
    )
    return probe(destination)


def silent_segment(source: Path, duration: float, destination: Path, still: bool) -> None:
    if still:
        input_args = ["-loop", "1", "-framerate", "25", "-i", str(source)]
        video_filter = (
            "scale=720:1277:flags=lanczos,"
            "crop=704:1248:x='8+2*sin(t*0.35)':y=14,format=yuv420p"
        )
    else:
        input_args = ["-i", str(source)]
        video_filter = (
            "scale=704:1248:force_original_aspect_ratio=increase:flags=lanczos,"
            "crop=704:1248,fps=25,format=yuv420p"
        )
    run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            *input_args,
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=stereo",
            "-t",
            f"{duration:.6f}",
            "-vf",
            video_filter,
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "17",
            "-r",
            "25",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(destination),
        ]
    )


def main() -> int:
    SEGMENTS.mkdir(parents=True, exist_ok=True)
    timeline = {
        item["id"]: item
        for item in json.loads(
            (PROJECT / "production_timeline.json").read_text(encoding="utf-8")
        )["timeline"]
    }
    segments: list[Path] = []
    events: list[dict[str, object]] = []
    cursor = 0.0
    for index, (kind, segment_id, fixed_duration, payload) in enumerate(ORDER):
        destination = SEGMENTS / f"{index:02d}_{segment_id}.mp4"
        if kind == "talk":
            item = timeline[segment_id]
            duration = talk_segment(item, destination)
            events.append(
                {
                    "kind": "talk",
                    "id": segment_id,
                    "speaker": item["speaker"],
                    "text": item["text"],
                    "start": cursor,
                    "end": cursor + duration,
                }
            )
        elif kind == "reaction":
            duration = float(fixed_duration)
            silent_segment(REACTIONS / str(payload), duration, destination, False)
            events.append(
                {"kind": kind, "id": segment_id, "start": cursor, "end": cursor + duration}
            )
        else:
            duration = float(fixed_duration)
            silent_segment(GROUP, duration, destination, True)
            events.append(
                {"kind": kind, "id": segment_id, "start": cursor, "end": cursor + duration}
            )
        segments.append(destination)
        cursor += duration

    concat = PROJECT / "concat_sadtalker.txt"
    concat.write_text(
        "\n".join(f"file '{path.as_posix()}'" for path in segments) + "\n",
        encoding="utf-8",
    )
    joined = PROJECT / "case_conference_v5_sadtalker_joined.mp4"
    run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat),
            "-c",
            "copy",
            str(joined),
        ]
    )

    subtitles = make_ass(events, cursor)
    escaped = subtitles.as_posix().replace(":", r"\:").replace("'", r"\'")
    native = PROJECT / "wenshu_case_conference_v5_sadtalker_native25.mp4"
    run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(joined),
            "-vf",
            f"subtitles=filename='{escaped}',format=yuv420p",
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-r",
            "25",
            "-c:a",
            "copy",
            "-t",
            f"{cursor:.6f}",
            "-movflags",
            "+faststart",
            str(native),
        ]
    )

    safe50 = PROJECT / "wenshu_case_conference_v5_sadtalker_safe50.mp4"
    run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(native),
            "-vf",
            "fps=50,format=yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-r",
            "50",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            str(safe50),
        ]
    )

    manifest = {
        "duration_seconds": round(cursor, 3),
        "events": events,
        "native_25fps": str(native.resolve()),
        "safe_50fps": str(safe50.resolve()),
        "lip_sync_policy": (
            "The exact final CosyVoice playback audio drives SadTalker crop-mode lips; "
            "the animated face is pasted into the original full-frame plate. No hidden "
            "guide audio, speed change, tmix, or optical-flow mouth interpolation."
        ),
    }
    (PROJECT / "timeline_v5_sadtalker.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(native)
    print(safe50)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
