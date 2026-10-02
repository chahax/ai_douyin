from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_DIR = PROJECT_ROOT / "data" / "qa" / "wenshu_lawyer_brand_v1"
COMFY_INPUT = Path(r"D:\IT\AI_vido\ComfyUI\input")
PAUSE = 0.28


def run(command: list[str]) -> None:
    print("RUN", subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, check=True)


def ass_time(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, remain = divmod(centiseconds, 360000)
    minutes, remain = divmod(remain, 6000)
    secs, cs = divmod(remain, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def wrap_cn(text: str, width: int = 17) -> str:
    if len(text) <= width:
        return text
    rows: list[str] = []
    remain = text
    while len(remain) > width:
        cut = width
        for punctuation in "，；：。！？":
            position = remain.rfind(punctuation, max(0, width - 5), width + 1)
            if position >= 0:
                cut = position + 1
                break
        rows.append(remain[:cut])
        remain = remain[cut:]
    if remain:
        rows.append(remain)
    return r"\N".join(rows)


def write_ass(path: Path, timeline: dict) -> None:
    total = float(timeline["total_duration"])
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
        "Style: Dialogue,Microsoft YaHei,39,&H00FFFFFF,&H000000FF,&H00110D0B,&H76000000,-1,0,0,0,100,100,0,0,1,3,0.8,2,44,44,108,1",
        "Style: Kicker,Microsoft YaHei,27,&H00D8E7F2,&H000000FF,&H00201612,&H65000000,-1,0,0,0,100,100,1,0,1,2.3,0.5,8,36,36,58,1",
        "Style: Headline,Microsoft YaHei,48,&H00FFFFFF,&H000000FF,&H00201612,&H65000000,-1,0,0,0,100,100,1.5,0,1,3.2,0.8,8,34,34,78,1",
        "Style: Notice,Microsoft YaHei,20,&H00D8D8D8,&H000000FF,&H00111111,&H52000000,0,0,0,0,100,100,0,0,1,1.8,0,9,18,20,22,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        f"Dialogue: 0,{ass_time(0)},{ass_time(total)},Notice,,0,0,0,,一般法律信息分享，不构成个案法律意见",
        f"Dialogue: 1,{ass_time(0.2)},{ass_time(3.6)},Kicker,,0,0,0,,律师类案研究",
        f"Dialogue: 1,{ass_time(0.5)},{ass_time(4.8)},Headline,,0,0,0,,一张转账记录，为什么不一定能赢？",
        f"Dialogue: 1,{ass_time(15.41)},{ass_time(21.91)},Kicker,,0,0,0,,中国裁判文书网｜类案检索",
        f"Dialogue: 1,{ass_time(29.395)},{ass_time(35.2)},Kicker,,0,0,0,,转账事实 ≠ 必然成立借贷关系",
        f"Dialogue: 1,{ass_time(40.925)},{ass_time(46.85)},Kicker,,0,0,0,,借贷合意 + 款项交付 + 催收经过",
        f"Dialogue: 1,{ass_time(72.295)},{ass_time(78.995)},Kicker,,0,0,0,,专业，不是承诺结果，是提前识别风险",
    ]
    for item in timeline["timeline"]:
        text = wrap_cn(item["text"])
        lines.append(
            f"Dialogue: 2,{ass_time(float(item['start']))},{ass_time(float(item['end']))},Dialogue,{item['speaker']},0,0,0,,{text}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")


def prepare() -> None:
    timeline = json.loads((PROJECT_DIR / "audio" / "timeline.json").read_text(encoding="utf-8"))
    source_dir = PROJECT_DIR / "musetalk_full" / "results" / "v15"
    rife_input_dir = PROJECT_DIR / "rife_inputs"
    comfy_rife_dir = COMFY_INPUT / "wenshu_lawyer_brand_v1_rife"
    rife_input_dir.mkdir(parents=True, exist_ok=True)
    comfy_rife_dir.mkdir(parents=True, exist_ok=True)
    source_map: dict[str, str] = {}

    for item in timeline["timeline"]:
        shot_id = item["id"]
        source = source_dir / f"{shot_id}_lipsync.mp4"
        duration = float(item["duration"]) + PAUSE
        output = rife_input_dir / f"{shot_id}.mp4"
        run(
            [
                "ffmpeg", "-y", "-loglevel", "error", "-i", str(source), "-t", f"{duration:.3f}",
                "-vf", f"tpad=stop_mode=clone:stop_duration={PAUSE:.3f},fps=25,format=yuv420p",
                "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-movflags", "+faststart", str(output),
            ]
        )
        comfy_destination = comfy_rife_dir / f"{shot_id}.mp4"
        shutil.copy2(output, comfy_destination)
        source_map[shot_id] = f"wenshu_lawyer_brand_v1_rife/{shot_id}.mp4"

    (PROJECT_DIR / "rife_source_map.json").write_text(json.dumps(source_map, ensure_ascii=False, indent=2), encoding="utf-8")

    audio_mix = PROJECT_DIR / "dialogue_mix.wav"
    audio_inputs: list[str] = []
    filters: list[str] = []
    labels: list[str] = []
    for index, item in enumerate(timeline["timeline"]):
        audio_inputs.extend(["-i", item["file"]])
        delay_ms = round(float(item["start"]) * 1000)
        label = f"a{index}"
        filters.append(
            f"[{index}:a]aresample=48000,highpass=f=70,lowpass=f=10500,"
            f"acompressor=threshold=0.18:ratio=2:attack=8:release=110,adelay={delay_ms}:all=1[{label}]"
        )
        labels.append(f"[{label}]")
    total = float(timeline["total_duration"])
    filters.append(f"anoisesrc=color=pink:sample_rate=48000:duration={total:.3f},lowpass=f=800,volume=0.0025[room]")
    labels.append("[room]")
    filters.append("".join(labels) + f"amix=inputs={len(labels)}:duration=longest:normalize=0,alimiter=limit=0.95[outa]")
    run(
        [
            "ffmpeg", "-y", "-loglevel", "error", *audio_inputs, "-filter_complex", ";".join(filters),
            "-map", "[outa]", "-t", f"{total:.3f}", "-c:a", "pcm_s16le", str(audio_mix),
        ]
    )
    write_ass(PROJECT_DIR / "subtitles.ass", timeline)


def compose() -> None:
    timeline = json.loads((PROJECT_DIR / "audio" / "timeline.json").read_text(encoding="utf-8"))
    rife_dir = PROJECT_DIR / "rife50" / "clips"
    concat_path = PROJECT_DIR / "rife50_concat.txt"
    concat_lines = []
    for item in timeline["timeline"]:
        clip_path = rife_dir / f"{item['id']}.mp4"
        concat_lines.append(f"file '{clip_path.as_posix()}'")
    concat_path.write_text(
        "\n".join(concat_lines) + "\n",
        encoding="utf-8",
    )
    silent_video = PROJECT_DIR / "wenshu_lawyer_brand_v1_50fps_silent.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat_path), "-c", "copy", str(silent_video)])

    subtitles = PROJECT_DIR / "subtitles.ass"
    escaped_ass = subtitles.as_posix().replace(":", r"\:").replace("'", r"\'")
    final = PROJECT_DIR / "wenshu_lawyer_brand_v1_50fps.mp4"
    run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(silent_video), "-i", str(PROJECT_DIR / "dialogue_mix.wav"),
            "-vf", f"subtitles=filename='{escaped_ass}',format=yuv420p", "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "aac", "-b:a", "192k",
            "-af", "loudnorm=I=-16:LRA=7:TP=-1.5",
            "-ar", "48000",
            "-t", f"{float(timeline['total_duration']):.3f}", "-movflags", "+faststart", str(final),
        ]
    )
    print(final, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["prepare", "compose"])
    args = parser.parse_args()
    if args.phase == "prepare":
        prepare()
    else:
        compose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
