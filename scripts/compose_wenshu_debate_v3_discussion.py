from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "data" / "qa" / "wenshu_lawyer_brand_v1" / "v2_debate"
LIPSYNC = PROJECT / "musetalk_results" / "v15"
REACTIONS = PROJECT / "reactions_ltx"
OUT = PROJECT / "v3_discussion"
W, H = 704, 1248
VIDEO_SPEED = 1.10
TOTAL_AUDIO_SPEED = 1.18 * VIDEO_SPEED
PAUSE = 0.10


ORDER = [
    ("still", "intro", 1.6, "group_master.png"),
    ("talk", "02", None, None),
    ("talk", "04", None, None),
    ("talk", "05", None, None),
    ("reaction", "rxu", 1.2, "r_xu_counter.mp4"),
    ("talk", "07", None, None),
    ("talk", "08", None, None),
    ("talk", "10", None, None),
    ("talk", "11", None, None),
    ("reaction", "rzhou", 1.2, "r_zhou_listen.mp4"),
    ("talk", "13", None, None),
    ("talk", "14", None, None),
    ("talk", "16", None, None),
    ("talk", "17", None, None),
    ("still", "group_mid", 1.0, "group_master.png"),
    ("talk", "19", None, None),
    ("talk", "20", None, None),
    ("reaction", "rgu", 0.9, "r_gu_gesture.mp4"),
    ("talk", "22", None, None),
    ("talk", "23", None, None),
    ("still", "outro", 2.6, "group_master.png"),
]


def run(args: list[str]) -> None:
    print(subprocess.list2cmdline(args), flush=True)
    subprocess.run(args, check=True)


def probe(path: Path) -> float:
    return float(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(path)
    ], text=True).strip())


def ass_time(value: float) -> str:
    cs = max(0, round(value * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def wrap_cn(text: str, width: int = 17) -> str:
    return r"\N".join(text[i:i + width] for i in range(0, len(text), width))


def make_ass(events: list[dict], total: float) -> Path:
    path = OUT / "subtitles.ass"
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Dialogue,Microsoft YaHei,36,&H00FFFFFF,&H000000FF,&H00100D0B,&H72000000,-1,0,0,0,100,100,0,0,1,3,0.5,2,44,44,86,1",
        "Style: Name,Microsoft YaHei,24,&H00E9D5A7,&H000000FF,&H00100D0B,&H76000000,-1,0,0,0,100,100,1,0,1,2,0,1,38,38,225,1",
        "Style: Title,Microsoft YaHei,43,&H00FFFFFF,&H000000FF,&H00100D0B,&H66000000,-1,0,0,0,100,100,1,0,1,3,0.6,8,34,34,66,1",
        "Style: Notice,Microsoft YaHei,18,&H00D8D8D8,&H000000FF,&H00111111,&H48000000,0,0,0,0,100,100,0,0,1,1.5,0,9,18,18,18,1", "",
        "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        f"Dialogue: 0,{ass_time(0)},{ass_time(total)},Notice,,0,0,0,,基于公开裁判文书的一般法律问题分析，不构成个案法律意见",
        f"Dialogue: 1,{ass_time(0.15)},{ass_time(2.8)},Title,,0,0,0,,同一笔钱，为什么会有两种法律结论？",
    ]
    roles = {"周宁": "主持律师", "顾承": "付款方代理视角", "许安": "收款方代理视角"}
    for event in events:
        if event["kind"] != "talk":
            continue
        lines.append(f"Dialogue: 2,{ass_time(event['start'] + 0.08)},{ass_time(min(event['end'], event['start'] + 1.8))},Name,,0,0,0,,{event['speaker']}｜{roles[event['speaker']]}")
        lines.append(f"Dialogue: 3,{ass_time(event['start'])},{ass_time(event['end'] - PAUSE)},Dialogue,,0,0,0,,{wrap_cn(event['text'])}")
    lines.append(f"Dialogue: 1,{ass_time(total - 2.35)},{ass_time(total - 0.35)},Title,,0,0,0,,法律关系｜举证责任｜诉讼路径")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return path


def talk_segment(item: dict, dst: Path) -> float:
    # Reuse the already accepted 50 fps face-only interpolation from v2. This
    # avoids running a second motion interpolation pass over the mouth.
    source_video = PROJECT / "segments50" / f"{item['id']}.mp4"
    source_audio = Path(item["file"])
    vf = f"setpts=PTS/{VIDEO_SPEED:.6f},fps=50,format=yuv420p"
    af = (
        "silenceremove=start_periods=1:start_duration=0.02:start_threshold=-42dB,"
        "areverse,silenceremove=start_periods=1:start_duration=0.08:start_threshold=-42dB,areverse,"
        f"atempo={TOTAL_AUDIO_SPEED:.6f},highpass=f=70,lowpass=f=10800,"
        "acompressor=threshold=0.16:ratio=1.8:attack=12:release=160:makeup=1.05,"
        "afade=t=in:st=0:d=0.02,"
        f"apad=pad_dur={PAUSE:.3f},alimiter=limit=0.95,aresample=48000"
    )
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(source_video), "-i", str(source_audio),
         "-map", "0:v:0", "-map", "1:a:0", "-vf", vf, "-af", af,
         "-c:v", "libx264", "-preset", "fast", "-crf", "17", "-r", "50",
         "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-ar", "48000", "-shortest", "-movflags", "+faststart", str(dst)])
    return probe(dst)


def silent_motion_segment(source: Path, duration: float, dst: Path, is_still: bool) -> None:
    if is_still:
        run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", "50", "-i", str(source),
             "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{duration:.3f}",
             "-vf", "scale=720:1277:flags=lanczos,crop=704:1248:x='8+3*sin(t*0.3)':y=14,format=yuv420p",
             "-c:v", "libx264", "-preset", "fast", "-crf", "17", "-r", "50", "-c:a", "aac", "-b:a", "128k",
             "-shortest", "-movflags", "+faststart", str(dst)])
    else:
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(source),
             "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{duration:.3f}",
             "-vf", "scale=704:1248:force_original_aspect_ratio=increase:flags=lanczos,crop=704:1248,minterpolate=fps=50:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1,format=yuv420p",
             "-c:v", "libx264", "-preset", "fast", "-crf", "17", "-r", "50", "-c:a", "aac", "-b:a", "128k",
             "-shortest", "-movflags", "+faststart", str(dst)])


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    segments_dir = OUT / "segments"
    segments_dir.mkdir(parents=True, exist_ok=True)
    timeline = {i["id"]: i for i in json.loads((PROJECT / "audio" / "timeline.json").read_text(encoding="utf-8"))["timeline"]}
    segments = []
    events = []
    cursor = 0.0
    for index, (kind, sid, fixed, payload) in enumerate(ORDER):
        dst = segments_dir / f"{index:02d}_{sid}.mp4"
        if kind == "talk":
            duration = talk_segment(timeline[sid], dst)
            events.append({"kind": "talk", "id": sid, "speaker": timeline[sid]["speaker"], "text": timeline[sid]["text"], "start": cursor, "end": cursor + duration})
        elif kind == "reaction":
            duration = float(fixed)
            silent_motion_segment(REACTIONS / payload, duration, dst, False)
            events.append({"kind": kind, "id": sid, "start": cursor, "end": cursor + duration})
        else:
            duration = float(fixed)
            silent_motion_segment(PROJECT / "characters" / payload, duration, dst, True)
            events.append({"kind": kind, "id": sid, "start": cursor, "end": cursor + duration})
        segments.append(dst)
        cursor += duration

    concat = OUT / "concat.txt"
    concat.write_text("\n".join(f"file '{p.as_posix()}'" for p in segments) + "\n", encoding="utf-8")
    joined = OUT / "discussion_v3_joined.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(joined)])
    ass = make_ass(events, cursor)
    escaped = ass.as_posix().replace(":", r"\:").replace("'", r"\'")
    final = OUT / "wenshu_lawyer_discussion_v3_50fps.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(joined),
         "-f", "lavfi", "-i", f"anoisesrc=color=pink:sample_rate=48000:duration={cursor:.3f}",
         "-filter_complex", "[0:a]loudnorm=I=-16:LRA=6:TP=-1.5[a0];[1:a]lowpass=f=650,volume=0.0015[room];[a0][room]amix=inputs=2:duration=first[a]",
         "-vf", f"subtitles=filename='{escaped}',format=yuv420p", "-map", "0:v:0", "-map", "[a]",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-r", "50", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
         "-t", f"{cursor:.3f}", "-movflags", "+faststart", str(final)])
    (OUT / "timeline.json").write_text(json.dumps({"duration": cursor, "events": events, "output": str(final)}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(final)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
