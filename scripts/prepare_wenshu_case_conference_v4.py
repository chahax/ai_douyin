from __future__ import annotations

import json
import pickle
import subprocess
from pathlib import Path

import cv2


ROOT = Path(__file__).resolve().parents[1]
DEBATE = ROOT / "data" / "qa" / "wenshu_lawyer_brand_v1" / "v2_debate"
PROJECT = DEBATE / "v4_case_conference"
MASTER = ROOT / "data" / "qa" / "wenshu_lawyer_brand_v1" / "characters"
SIDE = DEBATE / "characters"

PLATES = {
    "01": MASTER / "zhouning_master.png",
    "02": MASTER / "gucheng_master.png",
    "03": MASTER / "xuan_master.png",
    "04": SIDE / "zhouning_side.png",
    "05": SIDE / "gucheng_side.png",
    "06": SIDE / "xuan_side.png",
    "07": MASTER / "gucheng_master.png",
    "08": MASTER / "xuan_master.png",
    "09": MASTER / "zhouning_master.png",
    "10": SIDE / "gucheng_side.png",
    "11": SIDE / "xuan_side.png",
    "12": SIDE / "zhouning_side.png",
    "13": MASTER / "gucheng_master.png",
    "14": MASTER / "xuan_master.png",
    "15": MASTER / "zhouning_master.png",
}


def run(args: list[str]) -> None:
    print(subprocess.list2cmdline(args), flush=True)
    subprocess.run(args, check=True)


def probe(path: Path) -> float:
    return float(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                str(path),
            ],
            text=True,
        ).strip()
    )


def face_coord(image_path: Path) -> tuple[tuple[int, int, int, int], str]:
    frame = cv2.imread(str(image_path))
    if frame is None:
        raise FileNotFoundError(image_path)
    detector = cv2.CascadeClassifier(
        str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml")
    )
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = detector.detectMultiScale(
        gray, scaleFactor=1.08, minNeighbors=5, minSize=(120, 120)
    )
    if len(faces):
        x, y, w, h = max(faces, key=lambda item: item[2] * item[3])
        pad_x = int(w * 0.08)
        coord = (
            max(0, int(x - pad_x)),
            max(0, int(y + h * 0.15)),
            min(frame.shape[1], int(x + w + pad_x)),
            min(frame.shape[0], int(y + h * 1.10)),
        )
        return coord, "haar"
    return (185, 205, 525, 630), "fallback"


def main() -> int:
    report_path = PROJECT / "audio_cosyvoice" / "voice_render_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    lines = report["lines"]

    audio_dir = PROJECT / "audio_final_16k"
    plate_dir = PROJECT / "musetalk_plates"
    result_dir = PROJECT / "musetalk_results"
    for directory in (audio_dir, plate_dir, result_dir):
        directory.mkdir(parents=True, exist_ok=True)

    yaml_lines: list[str] = []
    timeline: list[dict[str, object]] = []
    coord_report: list[dict[str, object]] = []

    for item in lines:
        shot_id = item["id"]
        source_audio = Path(item["audio_path"])
        final_audio = audio_dir / f"{shot_id}.wav"
        # Preserve the complete CosyVoice waveform. Add a short lead-in and tail so
        # neither the first phoneme nor the closed-mouth ending touches a hard cut.
        run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(source_audio),
                "-af",
                "adelay=80,apad=pad_dur=0.25,aresample=16000",
                "-ar",
                "16000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(final_audio),
            ]
        )

        source_plate = PLATES[shot_id]
        plate = plate_dir / f"{shot_id}.png"
        front = source_plate.parent == MASTER
        vf = (
            "scale=830:1476:flags=lanczos,crop=704:1248:(in_w-out_w)/2:24"
            if front
            else "scale=704:1248:force_original_aspect_ratio=increase:flags=lanczos,crop=704:1248"
        )
        run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(source_plate),
                "-vf",
                vf,
                "-frames:v",
                "1",
                str(plate),
            ]
        )

        coord, method = face_coord(plate)
        with (PROJECT / f"{shot_id}.pkl").open("wb") as handle:
            pickle.dump([coord], handle)
        coord_report.append({"id": shot_id, "coord": coord, "method": method})

        yaml_lines.extend(
            [
                f"task_{shot_id}:",
                f'  video_path: "{plate.as_posix()}"',
                f'  audio_path: "{final_audio.as_posix()}"',
                f'  result_name: "{shot_id}_lipsync.mp4"',
            ]
        )
        timeline.append(
            {
                **item,
                "audio_path": str(final_audio.resolve()),
                "duration_seconds": round(probe(final_audio), 3),
                "plate": str(source_plate.resolve()),
                "camera": "front" if front else "side",
            }
        )

    (PROJECT / "musetalk_v4.yaml").write_text(
        "\n".join(yaml_lines) + "\n", encoding="utf-8"
    )
    (PROJECT / "production_timeline.json").write_text(
        json.dumps({"timeline": timeline}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (PROJECT / "face_coords_report.json").write_text(
        json.dumps(coord_report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"prepared={len(timeline)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
