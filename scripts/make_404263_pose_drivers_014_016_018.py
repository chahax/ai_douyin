"""Create reviewed DWPose-format micro-action paths for shots 014/016/018."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data/qa/hospital_video"
WIDTH, HEIGHT, FPS = 320, 576, 16
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


def smoothstep(t: float) -> float:
    return t * t * (3.0 - 2.0 * t)


def mix(a: tuple[int, int], b: tuple[int, int], t: float) -> tuple[int, int]:
    return (round(a[0] + (b[0] - a[0]) * t), round(a[1] + (b[1] - a[1]) * t))


def body(cx: int, head_y: int = 105) -> list[tuple[int, int]]:
    return [
        (cx, head_y), (cx, head_y + 34),
        (cx - 20, head_y + 42), (cx - 30, head_y + 115), (cx - 35, head_y + 195),
        (cx + 20, head_y + 42), (cx + 30, head_y + 115), (cx + 35, head_y + 195),
        (cx - 11, head_y + 210), (cx - 13, head_y + 315), (cx - 15, head_y + 430),
        (cx + 11, head_y + 210), (cx + 13, head_y + 315), (cx + 15, head_y + 430),
        (cx - 6, head_y - 3), (cx + 6, head_y - 3),
        (cx - 15, head_y - 1), (cx + 15, head_y - 1),
    ]


def draw(frame: np.ndarray, points: list[tuple[int, int]], thickness: int = 5) -> None:
    for color, (a, b) in zip(COLORS, LIMBS):
        cv2.line(frame, points[a], points[b], color, thickness, cv2.LINE_AA)
    for index, point in enumerate(points):
        cv2.circle(frame, point, max(3, thickness - 1), COLORS[index % len(COLORS)], -1, cv2.LINE_AA)


def write(name: str, frames: int, pose_fn) -> Path:
    path = OUT_DIR / name
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (WIDTH, HEIGHT))
    if not writer.isOpened():
        raise RuntimeError(path)
    for index in range(frames):
        frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        for points, thickness in pose_fn(smoothstep(index / (frames - 1))):
            draw(frame, points, thickness)
        writer.write(frame)
    writer.release()
    return path


def pose_014(t: float):
    woman_a, woman_b = body(100), body(100)
    # Her camera-right arm extends once toward the phone desk and stops at
    # chest/desk height.  The operator remains motionless and watches.
    woman_a[5:8] = [(120, 150), (127, 222), (125, 280)]
    woman_b[5:8] = [(120, 150), (140, 220), (165, 274)]
    woman = [mix(a, b, t) for a, b in zip(woman_a, woman_b)]
    man = body(222)
    return [(woman, 5), (man, 6)]


def pose_016(t: float):
    # Stable close-up conditioning: a centered upper-body skeleton lowers the
    # head by only two pixels. Facial action remains text/reference driven, so
    # no synthetic tear or hand path can be introduced.
    person_a = body(160, 92)
    person_b = [(x, y + (2 if index < 14 else 0)) for index, (x, y) in enumerate(person_a)]
    person = [mix(a, b, t) for a, b in zip(person_a, person_b)]
    return [(person, 6)]


def pose_018(t: float):
    woman_a, woman_b = body(92), body(92, 119)
    # Keep the woman upright; only head/shoulders bow slightly.
    for index in range(8, 14):
        woman_b[index] = woman_a[index]
    woman = [mix(a, b, t) for a, b in zip(woman_a, woman_b)]
    man_a, man_b = body(220), body(220)
    # Operator opens the palm and extends it toward the first phone on the
    # camera-left side; no second gesture is added.
    man_a[2:5] = [(200, 150), (190, 220), (184, 286)]
    man_b[2:5] = [(200, 150), (178, 224), (145, 286)]
    man = [mix(a, b, t) for a, b in zip(man_a, man_b)]
    return [(woman, 5), (man, 6)]


def main() -> int:
    outputs = [
        write("shot014_pose_driver_point_two_person_320x576_16fps.mp4", 25, pose_014),
        write("shot016_pose_driver_eye_closeup_320x576_16fps.mp4", 29, pose_016),
        write("shot018_pose_driver_bow_point_two_person_320x576_16fps.mp4", 49, pose_018),
    ]
    print("\n".join(map(str, outputs)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
