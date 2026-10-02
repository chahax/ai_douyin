from __future__ import annotations

import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "data" / "qa" / "wenshu_lawyer_brand_v1" / "v2_debate"
LIPSYNC = PROJECT / "musetalk_results" / "v15"
W, H = 704, 1248
PAUSE = 0.18


SEQUENCE = [
    ("still", "01", 2.4, "group_master.png"),
    ("talk", "02", None, None),
    ("card", "03", 2.8, "case"),
    ("talk", "04", None, None), ("talk", "05", None, None),
    ("card", "06", 2.8, "views"),
    ("talk", "07", None, None), ("talk", "08", None, None),
    ("still", "09", 2.0, "group_master.png"),
    ("talk", "10", None, None), ("talk", "11", None, None),
    ("card", "12", 3.0, "evidence"),
    ("talk", "13", None, None), ("talk", "14", None, None),
    ("card", "15", 3.0, "burden"),
    ("talk", "16", None, None), ("talk", "17", None, None),
    ("still", "18", 2.0, "group_master.png"),
    ("talk", "19", None, None), ("talk", "20", None, None),
    ("card", "21", 3.0, "strategy"),
    ("talk", "22", None, None), ("talk", "23", None, None),
    ("still", "24", 3.8, "group_master.png"),
]


CARD_CONTENT = {
    "case": ("公开裁判文书", "（2021）粤01民初548号", ["争议：款项性质与约定用途", "同一组转账，不等于同一法律问题"]),
    "views": ("两种代理视角", "付款方  VS  收款方", ["约定用途是否偏离？", "汇款备注能否被其他事实解释？"]),
    "evidence": ("证据必须相互印证", "不能只看一个标签", ["合同｜发票｜付款对象", "项目进度｜资金流向｜双方确认"]),
    "burden": ("举证责任如何移动", "先证明约定，再解释流向", ["付款方：转账 + 约定用途", "收款方：实际履行 + 第三方凭证"]),
    "strategy": ("律师的双向验证", "先攻击自己的薄弱处", ["预判对方最强解释", "逐笔拆分金额、时间与交易背景"]),
}


def run(args: list[str]) -> None:
    print(subprocess.list2cmdline(args), flush=True)
    subprocess.run(args, check=True)


def probe(path: Path) -> float:
    return float(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(path)
    ], text=True).strip())


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = Path(r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc")
    return ImageFont.truetype(str(path), size)


def centered(draw: ImageDraw.ImageDraw, text: str, y: int, f: ImageFont.FreeTypeFont, color: tuple[int, int, int]) -> None:
    box = draw.textbbox((0, 0), text, font=f)
    draw.text(((W - (box[2] - box[0])) / 2, y), text, font=f, fill=color)


def make_cards() -> None:
    out = PROJECT / "cards"
    out.mkdir(parents=True, exist_ok=True)
    for key, (kicker, title, rows) in CARD_CONTENT.items():
        im = Image.new("RGB", (W, H), (17, 26, 38))
        d = ImageDraw.Draw(im)
        d.rectangle((0, 0, W, 15), fill=(175, 139, 72))
        d.rounded_rectangle((54, 220, W - 54, 1000), radius=32, fill=(29, 41, 56), outline=(85, 107, 130), width=2)
        centered(d, kicker, 280, font(30, True), (188, 207, 225))
        centered(d, title, 370, font(44, True), (255, 255, 255))
        d.line((116, 476, W - 116, 476), fill=(175, 139, 72), width=3)
        for i, row in enumerate(rows):
            y = 565 + i * 142
            d.rounded_rectangle((94, y - 25, W - 94, y + 72), radius=18, fill=(37, 53, 71))
            centered(d, row, y, font(29, False), (235, 239, 243))
        centered(d, "裁判文书研究｜律师圆桌", 1082, font(23), (135, 153, 173))
        im.save(out / f"{key}.png", quality=95)


def ass_time(value: float) -> str:
    cs = max(0, round(value * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def wrap_cn(text: str, width: int = 16) -> str:
    return r"\N".join(text[i:i + width] for i in range(0, len(text), width))


def write_ass(events: list[dict], total: float) -> Path:
    path = PROJECT / "subtitles_v2.ass"
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Dialogue,Microsoft YaHei,37,&H00FFFFFF,&H000000FF,&H00100D0B,&H73000000,-1,0,0,0,100,100,0,0,1,3,0.5,2,42,42,92,1",
        "Style: Name,Microsoft YaHei,25,&H00E8D8B0,&H000000FF,&H00100D0B,&H78000000,-1,0,0,0,100,100,1,0,1,2,0,1,42,42,230,1",
        "Style: Title,Microsoft YaHei,44,&H00FFFFFF,&H000000FF,&H00100D0B,&H66000000,-1,0,0,0,100,100,1,0,1,3,0.6,8,34,34,70,1",
        "Style: Notice,Microsoft YaHei,19,&H00DDDDDD,&H000000FF,&H00111111,&H4A000000,0,0,0,0,100,100,0,0,1,1.5,0,9,18,18,18,1", "",
        "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        f"Dialogue: 0,{ass_time(0)},{ass_time(total)},Notice,,0,0,0,,基于公开裁判文书的一般法律问题分析，不构成个案法律意见",
        f"Dialogue: 1,{ass_time(0.3)},{ass_time(3.0)},Title,,0,0,0,,同一笔钱，为什么会有两种法律结论？",
    ]
    for e in events:
        if e["kind"] != "talk":
            continue
        name = e["speaker"] + "｜" + {"周宁": "主持律师", "顾承": "付款方代理视角", "许安": "收款方代理视角"}[e["speaker"]]
        lines.append(f"Dialogue: 2,{ass_time(e['start'] + 0.15)},{ass_time(min(e['end'], e['start'] + 2.4))},Name,,0,0,0,,{name}")
        lines.append(f"Dialogue: 3,{ass_time(e['start'])},{ass_time(e['end'] - PAUSE)},Dialogue,,0,0,0,,{wrap_cn(e['text'])}")
    lines += [
        f"Dialogue: 1,{ass_time(total - 4.6)},{ass_time(total - 0.5)},Title,,0,0,0,,先定法律关系｜再定举证责任｜最后定诉讼路径"
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return path


def make_segments() -> tuple[list[Path], list[dict], float]:
    timeline = {i["id"]: i for i in json.loads((PROJECT / "production_timeline.json").read_text(encoding="utf-8"))["timeline"]}
    out = PROJECT / "segments50"
    out.mkdir(parents=True, exist_ok=True)
    segments: list[Path] = []
    events: list[dict] = []
    cursor = 0.0
    for kind, sid, fixed_duration, payload in SEQUENCE:
        dst = out / f"{sid}.mp4"
        if kind == "talk":
            item = timeline[sid]
            src = LIPSYNC / f"{sid}_lipsync.mp4"
            duration = float(item["duration"]) + PAUSE
            vf = (
                "scale=720:1277:flags=lanczos,"
                "crop=704:1248:x='8+5*sin(t*0.33)':y='14+2*cos(t*0.27)',"
                "minterpolate=fps=50:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1,format=yuv420p"
            )
            if not dst.is_file() or abs(probe(dst) - duration) > 0.08:
                run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vf", vf,
                     "-af", f"apad=pad_dur={PAUSE:.3f},alimiter=limit=0.96", "-t", f"{duration:.3f}",
                     "-c:v", "libx264", "-preset", "fast", "-crf", "17", "-r", "50",
                     "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(dst)])
            events.append({"kind": kind, "id": sid, "speaker": item["speaker"], "text": item["text"], "start": cursor, "end": cursor + duration})
        else:
            duration = float(fixed_duration)
            src = PROJECT / "characters" / payload if kind == "still" else PROJECT / "cards" / f"{payload}.png"
            vf = (
                "scale=720:1277:flags=lanczos,crop=704:1248:x='8+3*sin(t*0.22)':y=14,format=yuv420p"
                if kind == "still" else "scale=704:1248:flags=lanczos,format=yuv420p"
            )
            run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", "50", "-i", str(src),
                 "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{duration:.3f}", "-vf", vf,
                 "-c:v", "libx264", "-preset", "fast", "-crf", "17", "-r", "50", "-c:a", "aac", "-b:a", "128k",
                 "-shortest", "-movflags", "+faststart", str(dst)])
            events.append({"kind": kind, "id": sid, "start": cursor, "end": cursor + duration})
        segments.append(dst)
        cursor += duration
    return segments, events, cursor


def main() -> int:
    make_cards()
    segments, events, total = make_segments()
    concat = PROJECT / "concat_v2.txt"
    concat.write_text("\n".join(f"file '{p.as_posix()}'" for p in segments) + "\n", encoding="utf-8")
    joined = PROJECT / "wenshu_lawyer_debate_v2_50fps_silenttitles.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(joined)])
    ass = write_ass(events, total)
    escaped = ass.as_posix().replace(":", r"\:").replace("'", r"\'")
    final = PROJECT / "wenshu_lawyer_debate_v2_50fps.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(joined),
         "-f", "lavfi", "-i", f"anoisesrc=color=pink:sample_rate=48000:duration={total:.3f}",
         "-filter_complex", f"[0:a]loudnorm=I=-16:LRA=7:TP=-1.5[a0];[1:a]lowpass=f=700,volume=0.0018[room];[a0][room]amix=inputs=2:duration=first[a]",
         "-vf", f"subtitles=filename='{escaped}',format=yuv420p", "-map", "0:v:0", "-map", "[a]",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-r", "50", "-c:a", "aac", "-b:a", "192k",
         "-ar", "48000", "-t", f"{total:.3f}", "-movflags", "+faststart", str(final)])
    (PROJECT / "final_timeline.json").write_text(json.dumps({"duration": total, "events": events, "output": str(final)}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(final)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
