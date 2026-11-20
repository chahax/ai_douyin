"""Add one subtle face-tracked tear to a video without changing the source pixels elsewhere."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_video", type=Path)
    parser.add_argument("output_video", type=Path)
    parser.add_argument("--appear", type=int, default=34)
    parser.add_argument("--fall-start", type=int, default=42)
    parser.add_argument("--fall-end", type=int, default=63)
    parser.add_argument("--fade-end", type=int, default=73)
    parser.add_argument("--opacity-scale", type=float, default=1.0)
    return parser.parse_args()


def detect_largest_face(
    gray: np.ndarray, detector: cv2.CascadeClassifier
) -> tuple[float, float, float, float] | None:
    faces = detector.detectMultiScale(
        gray, scaleFactor=1.08, minNeighbors=5, minSize=(100, 100)
    )
    if len(faces) == 0:
        return None
    x, y, width, height = max(faces, key=lambda item: int(item[2]) * int(item[3]))
    return float(x), float(y), float(width), float(height)


def smooth_box(
    previous: tuple[float, float, float, float] | None,
    current: tuple[float, float, float, float] | None,
    amount: float = 0.22,
) -> tuple[float, float, float, float] | None:
    if current is None:
        return previous
    if previous is None:
        return current
    return tuple(
        old * (1.0 - amount) + new * amount for old, new in zip(previous, current)
    )


def tear_progress(frame_index: int, args: argparse.Namespace) -> tuple[float, float]:
    """Return fall progress and opacity."""
    if frame_index < args.appear or frame_index >= args.fade_end:
        return 0.0, 0.0
    if frame_index < args.fall_start:
        emerge = (frame_index - args.appear) / max(1, args.fall_start - args.appear)
        return 0.0, 0.15 + 0.75 * emerge
    if frame_index <= args.fall_end:
        fall = (frame_index - args.fall_start) / max(
            1, args.fall_end - args.fall_start
        )
        eased = fall * fall * (3.0 - 2.0 * fall)
        return eased, 0.9
    fade = (frame_index - args.fall_end) / max(
        1, args.fade_end - args.fall_end
    )
    return 1.0, 0.9 * (1.0 - fade)


def add_tear(
    frame: np.ndarray,
    face: tuple[float, float, float, float],
    fall: float,
    opacity: float,
    opacity_scale: float,
) -> np.ndarray:
    x, y, width, height = face
    eye_x = x + width * 0.325
    eye_y = y + height * 0.39
    start = np.asarray((eye_x, eye_y + height * 0.035), dtype=np.float32)
    end = start + np.asarray((width * 0.018, height * 0.19), dtype=np.float32)
    droplet = start * (1.0 - fall) + end * fall

    layer = np.zeros_like(frame)
    mask = np.zeros(frame.shape[:2], dtype=np.uint8)
    start_point = tuple(np.rint(start).astype(int))
    drop_point = tuple(np.rint(droplet).astype(int))

    if fall > 0.04:
        cv2.line(
            layer,
            start_point,
            drop_point,
            (205, 220, 232),
            thickness=1,
            lineType=cv2.LINE_AA,
        )
        cv2.line(
            mask,
            start_point,
            drop_point,
            95,
            thickness=2,
            lineType=cv2.LINE_AA,
        )

    droplet_height = max(2, int(round(height * (0.008 + fall * 0.003))))
    droplet_width = max(1, int(round(width * 0.005)))
    cv2.ellipse(
        layer,
        drop_point,
        (droplet_width, droplet_height),
        0,
        0,
        360,
        (224, 239, 250),
        thickness=-1,
        lineType=cv2.LINE_AA,
    )
    cv2.ellipse(
        mask,
        drop_point,
        (droplet_width + 1, droplet_height + 1),
        0,
        0,
        360,
        165,
        thickness=-1,
        lineType=cv2.LINE_AA,
    )
    highlight = (drop_point[0] - 1, drop_point[1] - max(1, droplet_height // 2))
    cv2.circle(
        layer,
        highlight,
        max(1, droplet_width // 2),
        (252, 252, 252),
        thickness=-1,
        lineType=cv2.LINE_AA,
    )

    layer = cv2.GaussianBlur(layer, (0, 0), sigmaX=0.7, sigmaY=0.7)
    mask = cv2.GaussianBlur(mask, (0, 0), sigmaX=1.0, sigmaY=1.0)
    alpha = (mask.astype(np.float32) / 255.0 * opacity * opacity_scale)[..., None]
    result = frame.astype(np.float32) * (1.0 - alpha) + layer.astype(
        np.float32
    ) * alpha
    return np.clip(result, 0, 255).astype(np.uint8)


def main() -> None:
    args = parse_args()
    capture = cv2.VideoCapture(str(args.input_video))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open {args.input_video}")
    fps = capture.get(cv2.CAP_PROP_FPS)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))

    args.output_video.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(args.output_video),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )
    if not writer.isOpened():
        raise RuntimeError(f"Could not create {args.output_video}")

    detector = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    tracked_face = None
    written = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            tracked_face = smooth_box(
                tracked_face, detect_largest_face(gray, detector)
            )
            fall, opacity = tear_progress(written, args)
            if tracked_face is not None and opacity > 0:
                frame = add_tear(
                    frame, tracked_face, fall, opacity, args.opacity_scale
                )
            writer.write(frame)
            written += 1
    finally:
        capture.release()
        writer.release()

    print(
        json.dumps(
            {
                "input": str(args.input_video),
                "output": str(args.output_video),
                "width": width,
                "height": height,
                "fps": fps,
                "frames_expected": frame_count,
                "frames_written": written,
                "tear_window": [args.appear, args.fade_end],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
