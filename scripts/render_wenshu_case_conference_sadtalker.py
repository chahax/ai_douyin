from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = (
    ROOT
    / "data"
    / "qa"
    / "wenshu_lawyer_brand_v1"
    / "v2_debate"
    / "v4_case_conference"
)
SADTALKER = Path(r"D:\IT\SadTalker")
PYTHON = Path(sys.executable)


def newest_video(directory: Path, started_at: float) -> Path:
    candidates = [
        path
        for path in directory.glob("*.mp4")
        if path.stat().st_mtime >= started_at - 2.0
    ]
    if not candidates:
        raise RuntimeError(f"SadTalker produced no video in {directory}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def main() -> int:
    timeline = json.loads(
        (PROJECT / "production_timeline.json").read_text(encoding="utf-8")
    )["timeline"]
    square_dir = PROJECT / "sadtalker_square"
    full_dir = PROJECT / "sadtalker_fullframe"
    runs_dir = PROJECT / "sadtalker_runs"
    cache_dir = ROOT / "data" / "cache" / "sadtalker_v4"
    for directory in (square_dir, full_dir, runs_dir, cache_dir):
        directory.mkdir(parents=True, exist_ok=True)

    environment = os.environ.copy()
    environment["TEMP"] = str(cache_dir)
    environment["TMP"] = str(cache_dir)
    report: list[dict[str, object]] = []

    for index, item in enumerate(timeline, start=1):
        shot_id = str(item["id"])
        source_image = PROJECT / "musetalk_plates" / f"{shot_id}.png"
        audio = PROJECT / "audio_final_16k" / f"{shot_id}.wav"
        square = square_dir / f"{shot_id}.mp4"
        run_dir = runs_dir / shot_id
        run_dir.mkdir(parents=True, exist_ok=True)
        if not square.is_file():
            started_at = time.time()
            subprocess.run(
                [
                    str(PYTHON),
                    str(SADTALKER / "inference.py"),
                    "--driven_audio",
                    str(audio),
                    "--source_image",
                    str(source_image),
                    "--checkpoint_dir",
                    str(SADTALKER / "checkpoints"),
                    "--result_dir",
                    str(run_dir),
                    "--size",
                    "256",
                    "--preprocess",
                    "crop",
                    "--still",
                    "--expression_scale",
                    "0.65",
                    "--pose_style",
                    "0",
                    "--batch_size",
                    "2",
                ],
                cwd=SADTALKER,
                env=environment,
                check=True,
            )
            shutil.copy2(newest_video(run_dir, started_at), square)
        print(f"square {index}/{len(timeline)} {shot_id}", flush=True)

    sys.path.insert(0, str(SADTALKER))
    import cv2
    from src.utils.croper import Preprocesser
    from src.utils.paste_pic import paste_pic

    preprocessor = Preprocesser("cuda")
    for index, item in enumerate(timeline, start=1):
        shot_id = str(item["id"])
        source_image = PROJECT / "musetalk_plates" / f"{shot_id}.png"
        audio = PROJECT / "audio_final_16k" / f"{shot_id}.wav"
        square = square_dir / f"{shot_id}.mp4"
        full = full_dir / f"{shot_id}.mp4"

        frame = cv2.imread(str(source_image))
        if frame is None:
            raise FileNotFoundError(source_image)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        _, crop, quad = preprocessor.crop([rgb], still=False, xsize=512)
        clx, cly, _, _ = crop
        lx, ly, rx, ry = (int(value) for value in quad)
        ox1, ox2 = clx + lx, clx + rx
        oy1, oy2 = cly + ly, cly + ry
        crop_info = ((ox2 - ox1, oy2 - oy1), crop, quad)

        paste_pic(
            str(square),
            str(source_image),
            crop_info,
            str(audio),
            str(full),
            extended_crop=False,
        )
        report.append(
            {
                "id": shot_id,
                "speaker": item["speaker"],
                "text": item["text"],
                "source_image": str(source_image.resolve()),
                "audio": str(audio.resolve()),
                "square": str(square.resolve()),
                "fullframe": str(full.resolve()),
                "paste_rect": [ox1, oy1, ox2, oy2],
            }
        )
        print(f"fullframe {index}/{len(timeline)} {shot_id}", flush=True)

    (PROJECT / "sadtalker_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
