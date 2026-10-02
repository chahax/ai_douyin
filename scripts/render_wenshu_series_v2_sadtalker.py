#!/usr/bin/env python
"""Render audio-driven fixed-character talking shots and paste faces into full plates."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "data/qa/wenshu_lawyer_brand_v1/series_v2"
SADTALKER = Path(r"D:\IT\SadTalker")


def newest_video(directory: Path, started: float) -> Path:
    candidates = [p for p in directory.glob("*.mp4") if p.stat().st_mtime >= started - 2]
    if not candidates:
        raise RuntimeError(f"SadTalker produced no output in {directory}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", action="append", help="Optional ep01 style filter")
    args = parser.parse_args()
    timeline = json.loads((PROJECT / "production_timeline.json").read_text(encoding="utf-8"))["timeline"]
    selected = set(args.episode or [])
    if selected:
        timeline = [item for item in timeline if item["scene_id"] in selected]
    square_dir = PROJECT / "sadtalker_square"
    full_dir = PROJECT / "sadtalker_fullframe"
    runs_dir = PROJECT / "sadtalker_runs"
    cache_dir = ROOT / "data/cache/sadtalker_series_v2"
    for directory in (square_dir, full_dir, runs_dir, cache_dir):
        directory.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["TEMP"] = str(cache_dir)
    env["TMP"] = str(cache_dir)
    report = []
    # Phase 1: render all audio-driven crop videos. Keeping this phase separate
    # avoids repeatedly constructing the face cropper and its detector models.
    for index, item in enumerate(timeline, 1):
        line_id = item["id"]
        plate = Path(item["plate"])
        audio = Path(item["audio_path"])
        square = square_dir / f"{line_id}.mp4"
        run_dir = runs_dir / line_id
        run_dir.mkdir(parents=True, exist_ok=True)
        if not square.is_file():
            started = time.time()
            subprocess.run([
                sys.executable, str(SADTALKER / "inference.py"),
                "--driven_audio", str(audio), "--source_image", str(plate),
                "--checkpoint_dir", str(SADTALKER / "checkpoints"), "--result_dir", str(run_dir),
                "--size", "256", "--preprocess", "crop", "--still",
                "--expression_scale", "0.58", "--pose_style", "0", "--batch_size", "2",
            ], cwd=SADTALKER, env=env, check=True)
            shutil.copy2(newest_video(run_dir, started), square)
        print(f"square {index}/{len(timeline)} {line_id}", flush=True)

    # Phase 2: load the cropper once and paste each animated face back into its
    # exact vertical full-body plate so hands and composition remain available.
    sys.path.insert(0, str(SADTALKER))
    import cv2
    from src.utils.croper import Preprocesser
    from src.utils.paste_pic import paste_pic
    preprocessor = Preprocesser("cuda")
    for index, item in enumerate(timeline, 1):
        line_id = item["id"]
        plate = Path(item["plate"])
        audio = Path(item["audio_path"])
        square = square_dir / f"{line_id}.mp4"
        full = full_dir / f"{line_id}.mp4"
        if not full.is_file():
            frame = cv2.imread(str(plate))
            if frame is None:
                raise FileNotFoundError(plate)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            _, crop, quad = preprocessor.crop([rgb], still=False, xsize=512)
            lx, ly, rx, ry = (int(v) for v in quad)
            crop_info = ((rx - lx, ry - ly), crop, quad)
            paste_pic(str(square), str(plate), crop_info, str(audio), str(full), extended_crop=False)
        report.append({"id": line_id, "speaker": item["speaker"], "fullframe": str(full.resolve())})
        (PROJECT / "sadtalker_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"fullframe {index}/{len(timeline)} {line_id}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
