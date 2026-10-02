"""Rank per-shot camera shake and local temporal instability with optical flow.

The report is diagnostic only. It does not modify source media and deliberately
keeps scene-cut analysis outside this tool by consuming a candidate manifest.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import cv2
import numpy as np


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    return float(np.percentile(np.asarray(values, dtype=np.float64), percentile))


def inspect_clip(path: Path) -> dict[str, object]:
    capture = cv2.VideoCapture(str(path))
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    ok, previous = capture.read()
    if not ok:
        raise RuntimeError(f"unable to decode first frame: {path}")
    height, width = previous.shape[:2]
    scale = min(1.0, 640.0 / max(width, height))

    def gray(frame: np.ndarray) -> np.ndarray:
        if scale < 1.0:
            frame = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    previous_gray = gray(previous)
    translations: list[float] = []
    rotations: list[float] = []
    residuals: list[float] = []
    valid_pairs = 0

    while True:
        ok, current = capture.read()
        if not ok:
            break
        current_gray = gray(current)
        points = cv2.goodFeaturesToTrack(
            previous_gray,
            maxCorners=500,
            qualityLevel=0.01,
            minDistance=8,
            blockSize=7,
        )
        if points is not None and len(points) >= 12:
            next_points, status, _ = cv2.calcOpticalFlowPyrLK(
                previous_gray,
                current_gray,
                points,
                None,
                winSize=(31, 31),
                maxLevel=4,
                criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
            )
            if next_points is not None and status is not None:
                mask = status.reshape(-1).astype(bool)
                source = points.reshape(-1, 2)[mask]
                target = next_points.reshape(-1, 2)[mask]
                if len(source) >= 10:
                    matrix, inliers = cv2.estimateAffinePartial2D(
                        source,
                        target,
                        method=cv2.RANSAC,
                        ransacReprojThreshold=2.5,
                        maxIters=2000,
                        confidence=0.99,
                    )
                    if matrix is not None:
                        dx = float(matrix[0, 2]) / scale
                        dy = float(matrix[1, 2]) / scale
                        angle = math.degrees(math.atan2(float(matrix[1, 0]), float(matrix[0, 0])))
                        translations.append(math.hypot(dx, dy))
                        rotations.append(abs(angle))
                        predicted = cv2.transform(source.reshape(1, -1, 2), matrix).reshape(-1, 2)
                        point_residual = np.linalg.norm(predicted - target, axis=1) / scale
                        if inliers is not None:
                            point_residual = point_residual[inliers.reshape(-1).astype(bool)]
                        if len(point_residual):
                            residuals.append(float(np.median(point_residual)))
                        valid_pairs += 1
        previous_gray = current_gray

    capture.release()
    translation_steps = np.asarray(translations, dtype=np.float64)
    rotation_steps = np.asarray(rotations, dtype=np.float64)
    translation_jerk = np.abs(np.diff(translation_steps)).tolist() if len(translation_steps) > 1 else []
    rotation_jerk = np.abs(np.diff(rotation_steps)).tolist() if len(rotation_steps) > 1 else []
    diagonal = math.hypot(width, height)
    global_jitter = _percentile(translation_jerk, 95.0)
    local_instability = _percentile(residuals, 95.0)
    score = 100.0 * (global_jitter + local_instability) / max(diagonal, 1.0)
    return {
        "path": str(path),
        "width": width,
        "height": height,
        "fps": round(fps, 4),
        "frame_count": frame_count,
        "valid_flow_pairs": valid_pairs,
        "global_translation_px_median": round(_percentile(translations, 50.0), 4),
        "global_translation_px_p95": round(_percentile(translations, 95.0), 4),
        "global_translation_jerk_px_p95": round(global_jitter, 4),
        "global_rotation_deg_p95": round(_percentile(rotations, 95.0), 5),
        "global_rotation_jerk_deg_p95": round(_percentile(rotation_jerk, 95.0), 5),
        "local_flow_residual_px_p95": round(local_instability, 4),
        "instability_score": round(score, 5),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.resolve().read_text(encoding="utf-8"))
    rows: list[dict[str, object]] = []
    entries: list[dict[str, object]] = []
    for scene in manifest.get("scenes", []):
        entries.append({
            "path": scene["source_path"],
            "scene_id": scene["scene_id"],
            "workflow": scene["selected_workflow"],
        })
    if not entries:
        for beat in manifest.get("beats", []):
            for cut in beat.get("cuts", []):
                entries.append({
                    "path": cut["path"],
                    "scene_id": f"{beat['beat_id']}/cut_{int(cut['local_index']):02d}",
                    "workflow": cut["family"],
                })
    if not entries:
        raise ValueError("manifest contains neither scenes nor beat cuts")
    for entry in entries:
        path = Path(str(entry["path"]))
        result = inspect_clip(path)
        result["scene_id"] = entry["scene_id"]
        result["workflow"] = entry["workflow"]
        rows.append(result)
    rows.sort(key=lambda item: float(item["instability_score"]), reverse=True)
    report = {
        "template": "video_jitter_diagnostic/v1",
        "candidate_manifest": str(args.manifest.resolve()),
        "scenes": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
