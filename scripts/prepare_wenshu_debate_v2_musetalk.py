from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "data" / "qa" / "wenshu_lawyer_brand_v1"
OUT = PROJECT / "v2_debate"
CHARACTERS = OUT / "characters"
SPEED = 1.18


PLATES = {
    "02": PROJECT / "characters" / "zhouning_master.png",
    "04": PROJECT / "characters" / "gucheng_master.png",
    "05": CHARACTERS / "gucheng_side.png",
    "07": PROJECT / "characters" / "xuan_master.png",
    "08": CHARACTERS / "zhouning_side.png",
    "10": PROJECT / "characters" / "gucheng_master.png",
    "11": CHARACTERS / "xuan_side.png",
    "13": PROJECT / "characters" / "zhouning_master.png",
    "14": CHARACTERS / "gucheng_side.png",
    "16": PROJECT / "characters" / "xuan_master.png",
    "17": PROJECT / "characters" / "gucheng_master.png",
    "19": CHARACTERS / "xuan_side.png",
    "20": CHARACTERS / "zhouning_side.png",
    "22": CHARACTERS / "gucheng_side.png",
    "23": PROJECT / "characters" / "zhouning_master.png",
}


def run(args: list[str]) -> None:
    print(subprocess.list2cmdline(args), flush=True)
    subprocess.run(args, check=True)


def probe(path: Path) -> float:
    return float(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(path)
    ], text=True).strip())


def main() -> int:
    source = json.loads((OUT / "audio" / "timeline.json").read_text(encoding="utf-8"))
    fast_audio = OUT / "audio_fast"
    base_video = OUT / "base_video"
    plate_dir = OUT / "musetalk_plates"
    fast_audio.mkdir(parents=True, exist_ok=True)
    base_video.mkdir(parents=True, exist_ok=True)
    plate_dir.mkdir(parents=True, exist_ok=True)
    yaml_lines: list[str] = []
    timeline = []

    for index, item in enumerate(source["timeline"]):
        shot_id = item["id"]
        wav = fast_audio / f"{shot_id}.wav"
        run([
            "ffmpeg", "-y", "-loglevel", "error", "-i", item["file"],
            "-af", f"atempo={SPEED},highpass=f=65,lowpass=f=11000,alimiter=limit=0.96",
            # MuseTalk's Whisper frontend consumes 16 kHz. Pre-converting here avoids
            # a Windows librosa/soxr resampling stall on 48 kHz PCM inputs.
            "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(wav)
        ])
        duration = probe(wav)
        plate = PLATES[shot_id]
        video = base_video / f"{shot_id}.mp4"
        plate_out = plate_dir / f"{shot_id}.png"
        # Front plates are enlarged so the original tabletop/hands remain outside frame.
        front = plate.parent.name == "characters" and plate.parent == PROJECT / "characters"
        vf = (
            "scale=830:1476:flags=lanczos,crop=704:1248:(in_w-out_w)/2:24,format=yuv420p"
            if front else
            "scale=704:1248:force_original_aspect_ratio=increase:flags=lanczos,crop=704:1248,format=yuv420p"
        )
        run([
            "ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", "25", "-i", str(plate),
            "-t", f"{duration:.3f}", "-vf", vf, "-an", "-c:v", "libx264", "-preset", "fast",
            "-crf", "16", "-r", "25", "-movflags", "+faststart", str(video)
        ])
        run([
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(plate),
            "-vf", vf, "-frames:v", "1", str(plate_out)
        ])
        yaml_lines += [
            f"task_{shot_id}:",
            f'  video_path: "{plate_out.as_posix()}"',
            f'  audio_path: "{wav.as_posix()}"',
            f'  result_name: "{shot_id}_lipsync.mp4"',
        ]
        timeline.append({**item, "file": str(wav), "duration": round(duration, 3), "plate": str(plate), "camera": "front" if front else "side"})
        print(f"prepared {shot_id}: {duration:.3f}s", flush=True)

    (OUT / "musetalk_v2.yaml").write_text("\n".join(yaml_lines) + "\n", encoding="utf-8")
    (OUT / "production_timeline.json").write_text(json.dumps({"timeline": timeline}, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
