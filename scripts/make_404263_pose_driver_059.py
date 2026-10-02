"""Build the reviewed two-person DWPose-format arrest-reaction path for 059."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/qa/hospital_video/shot059_pose_driver_reaction_two_person_320x576_16fps.mp4"
WIDTH, HEIGHT, FPS, FRAMES = 320, 576, 16, 29
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
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def lerp(a: tuple[int, int], b: tuple[int, int], t: float) -> tuple[int, int]:
    return (round(a[0] + (b[0] - a[0]) * t), round(a[1] + (b[1] - a[1]) * t))


def face(center: tuple[int, int]) -> list[tuple[int, int]]:
    x, y = center
    return [(x, y), (x, y + 25), (x - 18, y + 30), (x - 30, y + 95),
            (x - 10, y + 155), (x + 18, y + 30), (x + 30, y + 95),
            (x + 10, y + 155), (x - 10, y + 185), (x - 12, y + 275),
            (x - 18, y + 380), (x + 10, y + 185), (x + 12, y + 275),
            (x + 18, y + 380), (x - 6, y - 3), (x + 6, y - 3),
            (x - 15, y - 1), (x + 15, y - 1)]


def operator_pose(t: float) -> list[tuple[int, int]]:
    start = face((88, 118))
    end = face((76, 110))
    # Torso leans back, open hands release the phone, and the near foot slides
    # one short step back.  No officer contact occurs yet.
    start[4], start[7] = (72, 278), (104, 278)
    end[4], end[7] = (38, 260), (116, 254)
    start[8:14] = [(98, 303), (91, 402), (92, 520), (116, 303), (122, 402), (124, 520)]
    end[8:14] = [(111, 320), (96, 414), (73, 520), (128, 320), (135, 414), (142, 520)]
    return [lerp(a, b, t) for a, b in zip(start, end)]


def lead_pose(t: float) -> list[tuple[int, int]]:
    start = face((224, 142))
    end = face((224, 108))
    start[4], start[7] = (210, 300), (238, 300)
    end[4], end[7] = (190, 258), (258, 258)
    start[8:14] = [(214, 337), (205, 418), (204, 520), (234, 337), (243, 418), (244, 520)]
    end[8:14] = [(214, 306), (205, 405), (204, 520), (234, 306), (243, 405), (244, 520)]
    return [lerp(a, b, t) for a, b in zip(start, end)]


def draw(frame: np.ndarray, points: list[tuple[int, int]], thickness: int) -> None:
    for color, (a, b) in zip(COLORS, LIMBS):
        cv2.line(frame, points[a], points[b], color, thickness, cv2.LINE_AA)
    for index, point in enumerate(points):
        cv2.circle(frame, point, max(3, thickness - 1), COLORS[index % len(COLORS)], -1, cv2.LINE_AA)


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(OUTPUT), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (WIDTH, HEIGHT))
    if not writer.isOpened():
        raise RuntimeError(f"could not open video writer: {OUTPUT}")
    for index in range(FRAMES):
        t = smoothstep(index / (FRAMES - 1))
        frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        draw(frame, operator_pose(t), 6)
        draw(frame, lead_pose(t), 5)
        writer.write(frame)
    writer.release()
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
