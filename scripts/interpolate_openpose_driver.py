"""Build a deterministic OpenPose/DWPose-style motion driver from two endpoint JSON files."""

from __future__ import annotations

import argparse
import colorsys
import json
import math
from pathlib import Path

import cv2
import numpy as np


BODY_LIMBS = [
    (2, 3),
    (2, 6),
    (3, 4),
    (4, 5),
    (6, 7),
    (7, 8),
    (2, 9),
    (9, 10),
    (10, 11),
    (2, 12),
    (12, 13),
    (13, 14),
    (2, 1),
    (1, 15),
    (15, 17),
    (1, 16),
    (16, 18),
]

BODY_COLORS_RGB = [
    (255, 0, 0),
    (255, 85, 0),
    (255, 170, 0),
    (255, 255, 0),
    (170, 255, 0),
    (85, 255, 0),
    (0, 255, 0),
    (0, 255, 85),
    (0, 255, 170),
    (0, 255, 255),
    (0, 170, 255),
    (0, 85, 255),
    (0, 0, 255),
    (85, 0, 255),
    (170, 0, 255),
    (255, 0, 255),
    (255, 0, 170),
    (255, 0, 85),
]

HAND_EDGES = [
    (0, 1),
    (1, 2),
    (2, 3),
    (3, 4),
    (0, 5),
    (5, 6),
    (6, 7),
    (7, 8),
    (0, 9),
    (9, 10),
    (10, 11),
    (11, 12),
    (0, 13),
    (13, 14),
    (14, 15),
    (15, 16),
    (0, 17),
    (17, 18),
    (18, 19),
    (19, 20),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("start_json", type=Path)
    parser.add_argument("end_json", type=Path)
    parser.add_argument("output_video", type=Path)
    parser.add_argument("--frames", type=int, default=49)
    parser.add_argument("--fps", type=float, default=16.0)
    parser.add_argument("--moving-person", type=int, default=0)
    parser.add_argument("--start-hold", type=int, default=5)
    parser.add_argument("--end-hold", type=int, default=8)
    parser.add_argument(
        "--kneel-reference-retarget",
        action="store_true",
        help="Retarget the moving person's endpoint to a floor-level kneel for the hospital reference.",
    )
    return parser.parse_args()


def load_pose(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or len(payload) != 1:
        raise ValueError(f"Expected one pose frame in {path}")
    return payload[0]


def triplets(values: list[float] | None) -> np.ndarray | None:
    if values is None:
        return None
    array = np.asarray(values, dtype=np.float32)
    if array.size % 3:
        raise ValueError("Keypoint list length must be divisible by three")
    return array.reshape((-1, 3))


def smoothstep(value: float) -> float:
    value = min(1.0, max(0.0, value))
    return value * value * (3.0 - 2.0 * value)


def retarget_hospital_kneel(person: dict) -> None:
    """Place the adult skeleton at floor level while leaning toward the child."""
    body = triplets(person["pose_keypoints_2d"])
    if body is None or body.shape[0] != 18:
        raise ValueError("Hospital kneel retarget expects an 18-point body pose")

    target_xy = np.asarray(
        [
            (210, 310),
            (180, 360),
            (140, 360),
            (175, 445),
            (240, 530),
            (220, 360),
            (230, 450),
            (245, 535),
            (150, 500),
            (150, 620),
            (70, 620),
            (200, 500),
            (245, 540),
            (225, 665),
            (200, 298),
            (218, 300),
            (185, 300),
            (228, 305),
        ],
        dtype=np.float32,
    )
    body[:, :2] = target_xy
    body[:, 2] = 1.0
    person["pose_keypoints_2d"] = body.reshape(-1).tolist()

    for field, wrist_target in (
        ("hand_right_keypoints_2d", target_xy[4]),
        ("hand_left_keypoints_2d", target_xy[7]),
    ):
        hand = triplets(person[field])
        if hand is None:
            continue
        offset = wrist_target - hand[0, :2]
        hand[:, :2] += offset
        hand[:, 2] = np.maximum(hand[:, 2], 1.0)
        person[field] = hand.reshape(-1).tolist()


def interpolate_points(
    start: list[float] | None, end: list[float] | None, amount: float
) -> np.ndarray | None:
    start_points = triplets(start)
    end_points = triplets(end)
    if start_points is None:
        return end_points
    if end_points is None:
        return start_points
    if start_points.shape != end_points.shape:
        raise ValueError(
            f"Endpoint keypoint shapes differ: {start_points.shape} vs {end_points.shape}"
        )
    result = start_points.copy()
    both_visible = (start_points[:, 2] > 0) & (end_points[:, 2] > 0)
    result[both_visible, :2] = (
        start_points[both_visible, :2] * (1.0 - amount)
        + end_points[both_visible, :2] * amount
    )
    result[both_visible, 2] = np.minimum(
        start_points[both_visible, 2], end_points[both_visible, 2]
    )
    only_end = (start_points[:, 2] <= 0) & (end_points[:, 2] > 0)
    result[only_end] = end_points[only_end]
    return result


def rgb_to_bgr(color: tuple[int, int, int], scale: float = 1.0) -> tuple[int, int, int]:
    return tuple(int(channel * scale) for channel in reversed(color))


def draw_body(canvas: np.ndarray, points: np.ndarray | None) -> None:
    if points is None:
        return
    for (first, second), color in zip(BODY_LIMBS, BODY_COLORS_RGB):
        p1 = points[first - 1]
        p2 = points[second - 1]
        if p1[2] <= 0 or p2[2] <= 0:
            continue
        x1, y1 = float(p1[0]), float(p1[1])
        x2, y2 = float(p2[0]), float(p2[1])
        center = (int(round((x1 + x2) / 2)), int(round((y1 + y2) / 2)))
        length = math.hypot(x1 - x2, y1 - y2)
        angle = math.degrees(math.atan2(y1 - y2, x1 - x2))
        polygon = cv2.ellipse2Poly(
            center, (max(1, int(length / 2)), 4), int(angle), 0, 360, 1
        )
        cv2.fillConvexPoly(canvas, polygon, rgb_to_bgr(color, 0.6))
    for point, color in zip(points, BODY_COLORS_RGB):
        if point[2] > 0:
            cv2.circle(
                canvas,
                (int(round(point[0])), int(round(point[1]))),
                4,
                rgb_to_bgr(color),
                thickness=-1,
                lineType=cv2.LINE_AA,
            )


def draw_hand(canvas: np.ndarray, points: np.ndarray | None) -> None:
    if points is None:
        return
    for index, (first, second) in enumerate(HAND_EDGES):
        p1 = points[first]
        p2 = points[second]
        if p1[2] <= 0 or p2[2] <= 0:
            continue
        rgb_float = colorsys.hsv_to_rgb(index / len(HAND_EDGES), 1.0, 1.0)
        color = rgb_to_bgr(tuple(int(channel * 255) for channel in rgb_float))
        cv2.line(
            canvas,
            (int(round(p1[0])), int(round(p1[1]))),
            (int(round(p2[0])), int(round(p2[1]))),
            color,
            thickness=2,
            lineType=cv2.LINE_AA,
        )
    for point in points:
        if point[2] > 0:
            cv2.circle(
                canvas,
                (int(round(point[0])), int(round(point[1]))),
                4,
                (255, 0, 0),
                thickness=-1,
                lineType=cv2.LINE_AA,
            )


def main() -> None:
    args = parse_args()
    start_pose = load_pose(args.start_json)
    end_pose = load_pose(args.end_json)
    width = int(start_pose["canvas_width"])
    height = int(start_pose["canvas_height"])
    if (width, height) != (
        int(end_pose["canvas_width"]),
        int(end_pose["canvas_height"]),
    ):
        raise ValueError("Pose endpoint canvases differ")
    if len(start_pose["people"]) != len(end_pose["people"]):
        raise ValueError("Pose endpoints contain a different number of people")
    if args.kneel_reference_retarget:
        retarget_hospital_kneel(end_pose["people"][args.moving_person])

    args.output_video.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(args.output_video),
        cv2.VideoWriter_fourcc(*"mp4v"),
        args.fps,
        (width, height),
    )
    if not writer.isOpened():
        raise RuntimeError(f"Could not open video writer for {args.output_video}")

    move_count = args.frames - args.start_hold - args.end_hold
    if move_count < 2:
        raise ValueError("Not enough frames remain for the motion transition")

    try:
        for frame_index in range(args.frames):
            if frame_index < args.start_hold:
                amount = 0.0
            elif frame_index >= args.frames - args.end_hold:
                amount = 1.0
            else:
                linear = (frame_index - args.start_hold) / float(move_count - 1)
                amount = smoothstep(linear)

            canvas = np.zeros((height, width, 3), dtype=np.uint8)
            for person_index, start_person in enumerate(start_pose["people"]):
                if person_index == args.moving_person:
                    end_person = end_pose["people"][person_index]
                    body = interpolate_points(
                        start_person["pose_keypoints_2d"],
                        end_person["pose_keypoints_2d"],
                        amount,
                    )
                    left_hand = interpolate_points(
                        start_person["hand_left_keypoints_2d"],
                        end_person["hand_left_keypoints_2d"],
                        amount,
                    )
                    right_hand = interpolate_points(
                        start_person["hand_right_keypoints_2d"],
                        end_person["hand_right_keypoints_2d"],
                        amount,
                    )
                else:
                    body = triplets(start_person["pose_keypoints_2d"])
                    left_hand = triplets(start_person["hand_left_keypoints_2d"])
                    right_hand = triplets(start_person["hand_right_keypoints_2d"])
                draw_body(canvas, body)
                draw_hand(canvas, left_hand)
                draw_hand(canvas, right_hand)
            writer.write(canvas)
    finally:
        writer.release()

    print(
        json.dumps(
            {
                "output": str(args.output_video),
                "width": width,
                "height": height,
                "frames": args.frames,
                "fps": args.fps,
                "moving_person": args.moving_person,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
