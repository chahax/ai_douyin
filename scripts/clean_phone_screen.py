from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np


def parse_points(value: str) -> np.ndarray:
    points = []
    for pair in value.split(";"):
        x, y = pair.split(",")
        points.append((float(x), float(y)))
    if len(points) != 4:
        raise argparse.ArgumentTypeError("Expected four x,y pairs separated by semicolons.")
    return np.asarray(points, dtype=np.float32)


def main() -> None:
    parser = argparse.ArgumentParser(description="Remove generated gibberish from a tracked bright phone screen.")
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument(
        "--corners",
        type=parse_points,
        required=True,
        help="First-frame screen corners: top-left;top-right;bottom-right;bottom-left",
    )
    parser.add_argument("--debug-output")
    args = parser.parse_args()

    source = Path(args.input)
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(source))
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    writer = cv2.VideoWriter(
        str(destination),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )
    if not writer.isOpened():
        raise RuntimeError(f"Unable to open output video: {destination}")

    rect_width, rect_height = 320, 520
    rectangle = np.asarray(
        [(0, 0), (rect_width - 1, 0), (rect_width - 1, rect_height - 1), (0, rect_height - 1)],
        dtype=np.float32,
    )
    tracked = args.corners.reshape(-1, 1, 2)
    previous_gray = None
    debug_frame = None
    frame_index = 0

    while True:
        ok, frame = capture.read()
        if not ok:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if previous_gray is not None:
            next_points, status, _ = cv2.calcOpticalFlowPyrLK(
                previous_gray,
                gray,
                tracked,
                None,
                winSize=(41, 41),
                maxLevel=4,
                criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 40, 0.001),
            )
            if next_points is not None and status is not None and int(status.sum()) == 4:
                tracked = next_points

        corners = tracked.reshape(4, 2)
        to_rectangle = cv2.getPerspectiveTransform(corners, rectangle)
        to_frame = cv2.getPerspectiveTransform(rectangle, corners)
        screen = cv2.warpPerspective(frame, to_rectangle, (rect_width, rect_height))
        screen_gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(screen, cv2.COLOR_BGR2HSV)
        ycrcb = cv2.cvtColor(screen, cv2.COLOR_BGR2YCrCb)

        roi = np.zeros((rect_height, rect_width), dtype=np.uint8)
        roi[int(rect_height * 0.42):int(rect_height * 0.76), int(rect_width * 0.08):int(rect_width * 0.92)] = 255
        low_saturation_dark = (screen_gray < 210) & (hsv[:, :, 1] < 120)
        skin = (
            (ycrcb[:, :, 1] >= 133) & (ycrcb[:, :, 1] <= 180) &
            (ycrcb[:, :, 2] >= 70) & (ycrcb[:, :, 2] <= 135) &
            (screen_gray > 45)
        )
        mask = np.where((roi > 0) & low_saturation_dark & ~skin, 255, 0).astype(np.uint8)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        filtered = np.zeros_like(mask)
        for label in range(1, count):
            area = int(stats[label, cv2.CC_STAT_AREA])
            component_width = int(stats[label, cv2.CC_STAT_WIDTH])
            component_height = int(stats[label, cv2.CC_STAT_HEIGHT])
            if 2 <= area <= 1600 and component_width <= 120 and component_height <= 60:
                filtered[labels == label] = 255
        filtered = cv2.dilate(filtered, np.ones((5, 5), np.uint8), iterations=1)
        cleaned_screen = cv2.inpaint(screen, filtered, 5, cv2.INPAINT_TELEA)
        changed = cv2.warpPerspective(cleaned_screen, to_frame, (width, height))
        changed_mask = cv2.warpPerspective(filtered, to_frame, (width, height))
        frame[changed_mask > 0] = changed[changed_mask > 0]
        writer.write(frame)

        if frame_index == 0:
            debug_frame = frame.copy()
            cv2.polylines(debug_frame, [corners.astype(np.int32)], True, (0, 255, 0), 2)
        previous_gray = gray
        frame_index += 1

    capture.release()
    writer.release()
    if args.debug_output and debug_frame is not None:
        cv2.imwrite(str(Path(args.debug_output)), debug_frame)
    print(f"cleaned {frame_index} frames: {destination}")


if __name__ == "__main__":
    main()
