"""Build the strict two-person DWPose-format control action for shot 060."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/qa/hospital_video/shot060_pose_driver_control_two_person_320x576_16fps.mp4"
WIDTH, HEIGHT, FPS, FRAMES = 320, 576, 16, 21
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


def operator(t: float) -> list[tuple[int, int]]:
    start = [
        (120, 148), (126, 188), (98, 198), (75, 300), (64, 462),
        (154, 200), (174, 310), (190, 462), (116, 326), (103, 422),
        (96, 548), (144, 328), (154, 425), (166, 548),
        (114, 145), (126, 145), (105, 147), (135, 147),
    ]
    end = [
        (112, 165), (120, 205), (92, 215), (73, 316), (64, 462),
        (149, 217), (172, 325), (190, 462), (112, 342), (101, 430),
        (96, 548), (140, 344), (153, 433), (166, 548),
        (106, 162), (118, 162), (97, 164), (127, 164),
    ]
    return [mix(a, b, t) for a, b in zip(start, end)]


def officer(t: float) -> list[tuple[int, int]]:
    # The front officer remains behind the operator. His camera-left hand closes
    # on the upper arm, then the shoulder/torso transfer weight downward once.
    start = [
        (226, 108), (226, 145), (204, 155), (180, 225), (153, 250),
        (248, 155), (258, 240), (246, 310), (216, 300), (214, 402),
        (212, 540), (238, 300), (242, 405), (246, 540),
        (220, 105), (232, 105), (211, 107), (241, 107),
    ]
    end = [
        (222, 116), (222, 154), (200, 165), (174, 235), (148, 266),
        (244, 165), (254, 247), (242, 315), (212, 306), (210, 404),
        (208, 540), (234, 306), (238, 407), (242, 540),
        (216, 113), (228, 113), (207, 115), (237, 115),
    ]
    return [mix(a, b, t) for a, b in zip(start, end)]


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
        draw(frame, operator(t), 6)
        draw(frame, officer(t), 5)
        writer.write(frame)
    writer.release()
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
