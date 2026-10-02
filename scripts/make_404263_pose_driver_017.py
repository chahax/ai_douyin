"""Build the reviewed two-person DWPose-format driver for shot 017.

The original reference edit does not contain an uncut chair-push-to-sit action.
This produces a single continuous, physically constrained pose path in the same
colored COCO/DWPose representation consumed by WanAnimateToVideo: the operator
pushes the chair first, then the lead bends and settles while both feet remain
planted.  It contains pose pixels only and is never composited into the result.
"""

from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = (
    ROOT
    / "data/qa/hospital_video/shot017_pose_driver_chair_sit_reviewed_320x576_16fps.mp4"
)
WIDTH, HEIGHT, FPS, FRAMES = 320, 576, 16, 37


def smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def mix(a: tuple[float, float], b: tuple[float, float], t: float) -> tuple[int, int]:
    return (round(a[0] + (b[0] - a[0]) * t), round(a[1] + (b[1] - a[1]) * t))


# DWPose/OpenPose body limb order and rainbow palette.  Keypoint labels are:
# nose, neck, right shoulder/elbow/wrist, left shoulder/elbow/wrist,
# right hip/knee/ankle, left hip/knee/ankle, right eye, left eye, right ear, left ear.
LIMBS = [
    (1, 2), (2, 3), (3, 4), (1, 5), (5, 6), (6, 7),
    (1, 8), (8, 9), (9, 10), (1, 11), (11, 12), (12, 13),
    (1, 0), (0, 14), (14, 16), (0, 15), (15, 17),
]
COLORS = [
    (0, 85, 255), (0, 170, 255), (0, 255, 255), (0, 255, 170),
    (0, 255, 85), (0, 255, 0), (85, 255, 0), (170, 255, 0),
    (255, 255, 0), (255, 170, 0), (255, 85, 0), (255, 0, 0),
    (255, 0, 85), (255, 0, 170), (255, 0, 255), (170, 0, 255),
    (85, 0, 255),
]


def face_points(nose: tuple[int, int]) -> list[tuple[int, int]]:
    x, y = nose
    return [(x, y), (x, y + 20), (x - 16, y + 22), (x - 26, y + 58),
            (x - 32, y + 104), (x + 16, y + 22), (x + 26, y + 58),
            (x + 32, y + 104), (x - 11, y + 125), (x - 13, y + 210),
            (x - 15, y + 305), (x + 11, y + 125), (x + 13, y + 210),
            (x + 15, y + 305), (x - 6, y - 3), (x + 6, y - 3),
            (x - 15, y - 1), (x + 15, y - 1)]


def woman_pose(t: float) -> list[tuple[int, int]]:
    # Chair push occupies the first quarter.  Only then does the sit begin.
    sit = smoothstep((t - 0.25) / 0.67)
    settle = smoothstep((t - 0.92) / 0.08)
    start = face_points((122, 120))
    end = [
        (122, 190), (122, 210), (105, 214), (98, 270), (108, 326),
        (139, 214), (146, 270), (136, 326), (110, 350), (78, 365),
        (78, 505), (134, 350), (166, 365), (166, 505),
        (116, 187), (128, 187), (107, 189), (137, 189),
    ]
    points = [mix(a, b, sit) for a, b in zip(start, end)]
    if settle > 0:
        points = [(x, y + round(2 * settle)) for x, y in points]
    return points


def man_pose(t: float) -> list[tuple[int, int]]:
    push = smoothstep(t / 0.25)
    base = face_points((220, 118))
    # Adult male remains upright.  Both wrists slide the chair back forward a
    # short distance and stop before the woman begins lowering.
    base[2], base[3], base[4] = (204, 160), (195, 222), mix((176, 278), (164, 278), push)
    base[5], base[6], base[7] = (236, 160), (245, 222), mix((198, 278), (186, 278), push)
    base[8], base[9], base[10] = (209, 306), (208, 405), (207, 515)
    base[11], base[12], base[13] = (231, 306), (233, 405), (236, 515)
    if t < 0.25:
        lean = round(3 * push)
        base = [(x - lean if index < 14 else x, y) for index, (x, y) in enumerate(base)]
    return [(int(x), int(y)) for x, y in base]


def draw_pose(frame: np.ndarray, points: list[tuple[int, int]], thickness: int) -> None:
    for color, (a, b) in zip(COLORS, LIMBS):
        cv2.line(frame, points[a], points[b], color, thickness, cv2.LINE_AA)
    radius = max(3, thickness)
    for index, point in enumerate(points):
        cv2.circle(frame, point, radius, COLORS[index % len(COLORS)], -1, cv2.LINE_AA)


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(OUTPUT), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (WIDTH, HEIGHT)
    )
    if not writer.isOpened():
        raise RuntimeError(f"could not open video writer: {OUTPUT}")
    for index in range(FRAMES):
        t = index / (FRAMES - 1)
        frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        draw_pose(frame, woman_pose(t), 6)
        draw_pose(frame, man_pose(t), 5)
        writer.write(frame)
    writer.release()
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
