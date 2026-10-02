"""Build a single-person DWPose-format two-step walk for shot 049.

The public-pool source contains many overlapping people, so its raw detector
path lets background skeletons replace the operator.  This reviewed driver
keeps one adult skeleton, two complete alternating steps, a small weight shift,
and a settled end pose.  Pose pixels guide Wan only and never enter the output.
"""

from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/qa/hospital_video/shot049_pose_driver_two_steps_320x576_16fps.mp4"
WIDTH, HEIGHT, FPS, FRAMES = 320, 576, 16, 41
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


def pose(t: float) -> list[tuple[int, int]]:
    # Ease the body along a short pool-edge path. Two sine cycles make exactly
    # two alternating steps; the amplitude fades to zero for a planted finish.
    travel = t * t * (3.0 - 2.0 * t)
    center = 128 + round(62 * travel)
    fade = min(1.0, (1.0 - t) / 0.14) if t > 0.86 else 1.0
    phase = 4.0 * math.pi * t
    swing = math.sin(phase) * fade
    bounce = round(abs(math.sin(phase)) * 4 * fade)
    head_y = 112 + bounce
    neck_y, hip_y = 148 + bounce, 292 + bounce
    r_foot_x = center - 13 + round(32 * swing)
    l_foot_x = center + 13 - round(32 * swing)
    r_knee_x = center - 11 + round(17 * swing)
    l_knee_x = center + 11 - round(17 * swing)
    arm = round(22 * swing)
    return [
        (center, head_y), (center, neck_y),
        (center - 22, neck_y + 8), (center - 28 - arm // 2, 225 + bounce),
        (center - 31 - arm, 302 + bounce),
        (center + 22, neck_y + 8), (center + 28 + arm // 2, 225 + bounce),
        (center + 31 + arm, 302 + bounce),
        (center - 12, hip_y), (r_knee_x, 395 + bounce), (r_foot_x, 516),
        (center + 12, hip_y), (l_knee_x, 395 + bounce), (l_foot_x, 516),
        (center - 6, head_y - 3), (center + 6, head_y - 3),
        (center - 15, head_y - 1), (center + 15, head_y - 1),
    ]


def draw(frame: np.ndarray, points: list[tuple[int, int]]) -> None:
    for color, (a, b) in zip(COLORS, LIMBS):
        cv2.line(frame, points[a], points[b], color, 6, cv2.LINE_AA)
    for index, point in enumerate(points):
        cv2.circle(frame, point, 5, COLORS[index % len(COLORS)], -1, cv2.LINE_AA)


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(OUTPUT), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (WIDTH, HEIGHT)
    )
    if not writer.isOpened():
        raise RuntimeError(f"could not open video writer: {OUTPUT}")
    for index in range(FRAMES):
        frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        draw(frame, pose(index / (FRAMES - 1)))
        writer.write(frame)
    writer.release()
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
