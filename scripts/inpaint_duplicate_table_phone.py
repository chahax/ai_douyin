"""Remove a duplicate tabletop phone from a short locked-camera review clip.

This is a deterministic cleanup pass: it never touches the held phone, actor,
or source/reference identities.  A fixed polygon covers only the duplicate
tabletop object after the pickup is complete.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np


POLYGON = np.array(
    [[0, 345], [175, 345], [202, 485], [0, 525]],
    dtype=np.int32,
)
SCREEN_POLYGON = np.array(
    [[27, 456], [136, 434], [158, 470], [45, 497]],
    dtype=np.int32,
)


def darken_table_phone_screen(frame: np.ndarray) -> np.ndarray:
    mask = np.zeros(frame.shape[:2], dtype=np.uint8)
    cv2.fillPoly(mask, [SCREEN_POLYGON], 255)
    feather = cv2.GaussianBlur(mask, (7, 7), 0).astype(np.float32) / 255.0
    feather = feather[:, :, None] * 0.88
    dark = frame.astype(np.float32) * 0.12 + np.array(
        [12.0, 13.0, 15.0], dtype=np.float32
    )
    result = np.clip(
        frame.astype(np.float32) * (1.0 - feather) + dark * feather,
        0,
        255,
    ).astype(np.uint8)
    # Stable non-text crack motif. It is deliberately subtle and remains inside
    # the screen polygon so no hand or table pixel is redrawn.
    crack_color = (82, 86, 90)
    for end in ((61, 463), (79, 447), (112, 444), (142, 459), (130, 482), (91, 490)):
        cv2.line(result, (96, 464), end, crack_color, 1, cv2.LINE_AA)
    return result


def clean_frame(frame: np.ndarray, plate: np.ndarray | None = None) -> np.ndarray:
    mask = np.zeros(frame.shape[:2], dtype=np.uint8)
    cv2.fillPoly(mask, [POLYGON], 255)
    if plate is not None:
        if plate.shape[:2] != frame.shape[:2]:
            plate = cv2.resize(plate, (frame.shape[1], frame.shape[0]))
        # Match the generated clean plate to an untouched glass-table region on
        # the right of the frame before blending.  This keeps the replacement
        # from appearing as a differently graded rectangle.
        frame_anchor = frame[414:520, 220:315].astype(np.float32)
        plate_anchor = plate[414:520, 220:315].astype(np.float32)
        frame_mean = frame_anchor.reshape(-1, 3).mean(axis=0)
        plate_mean = plate_anchor.reshape(-1, 3).mean(axis=0)
        frame_std = frame_anchor.reshape(-1, 3).std(axis=0) + 1.0
        plate_std = plate_anchor.reshape(-1, 3).std(axis=0) + 1.0
        matched = (
            (plate.astype(np.float32) - plate_mean)
            * (frame_std / plate_std)
            + frame_mean
        )
        matched = np.clip(matched, 0, 255)
        feather = cv2.GaussianBlur(mask, (41, 41), 0).astype(np.float32) / 255.0
        feather = feather[:, :, None]
        return np.clip(
            frame.astype(np.float32) * (1.0 - feather)
            + matched * feather,
            0,
            255,
        ).astype(np.uint8)
    # Fallback for diagnostics when a generated clean plate is unavailable.
    mask = cv2.dilate(mask, np.ones((5, 5), np.uint8), iterations=1)
    return cv2.inpaint(frame, mask, 7, cv2.INPAINT_TELEA)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--start-frame", type=int, default=8)
    parser.add_argument("--frames-dir", type=Path)
    parser.add_argument("--plate", type=Path)
    args = parser.parse_args()

    plate = cv2.imread(str(args.plate)) if args.plate else None
    if args.plate and plate is None:
        raise RuntimeError(f"cannot open clean plate {args.plate}")
    if args.input.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
        frame = cv2.imread(str(args.input))
        if frame is None:
            raise RuntimeError(f"cannot open {args.input}")
        cleaned = clean_frame(frame, plate)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(args.output), cleaned):
            raise RuntimeError(f"cannot create {args.output}")
        print(f"image=1 output={args.output}")
        return 0

    capture = cv2.VideoCapture(str(args.input))
    if not capture.isOpened():
        raise RuntimeError(f"cannot open {args.input}")
    fps = capture.get(cv2.CAP_PROP_FPS)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(args.output),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )
    if not writer.isOpened():
        raise RuntimeError(f"cannot create {args.output}")
    if args.frames_dir:
        args.frames_dir.mkdir(parents=True, exist_ok=True)

    index = 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        if index < args.start_frame:
            cleaned = darken_table_phone_screen(frame)
        else:
            cleaned = clean_frame(frame, plate)
        writer.write(cleaned)
        if args.frames_dir:
            cv2.imwrite(str(args.frames_dir / f"frame_{index:04d}.png"), cleaned)
        index += 1
    capture.release()
    writer.release()
    print(f"frames={index} fps={fps:g} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
