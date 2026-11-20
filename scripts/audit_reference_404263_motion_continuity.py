"""Audit real motion and same-action cut continuity for reference 404263 candidates.

The report is deliberately diagnostic. Numerical motion is not treated as a
human approval of anatomy, acting, gaze, prop persistence, or story meaning.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


MOVE_WORDS = (
    "walk", "step", "turn", "raise", "lower", "reach", "pull", "enter",
    "rise", "stand", "bring", "lift", "move", "stride", "gesture", "look",
    "拿", "走", "抬", "转", "拉", "进入", "起身", "站", "伸手", "移动",
)


def _resize_gray(frame: np.ndarray, max_side: int = 320) -> np.ndarray:
    height, width = frame.shape[:2]
    scale = min(1.0, max_side / max(height, width))
    if scale < 1.0:
        frame = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def _read_edge_frame(path: Path, *, last: bool) -> np.ndarray:
    capture = cv2.VideoCapture(str(path))
    count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if last and count:
        capture.set(cv2.CAP_PROP_POS_FRAMES, max(0, count - 1))
    ok, frame = capture.read()
    capture.release()
    if not ok:
        raise RuntimeError(f"unable to read {'last' if last else 'first'} frame: {path}")
    return frame


def _boundary_metrics(left: Path, right: Path) -> dict[str, float]:
    before = cv2.resize(_read_edge_frame(left, last=True), (180, 320), interpolation=cv2.INTER_AREA)
    after = cv2.resize(_read_edge_frame(right, last=False), (180, 320), interpolation=cv2.INTER_AREA)
    gray_before = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY)
    gray_after = cv2.cvtColor(after, cv2.COLOR_BGR2GRAY)
    mae = float(np.mean(cv2.absdiff(gray_before, gray_after)))
    hist_before = cv2.calcHist([before], [0, 1], None, [24, 24], [0, 256, 0, 256])
    hist_after = cv2.calcHist([after], [0, 1], None, [24, 24], [0, 256, 0, 256])
    cv2.normalize(hist_before, hist_before)
    cv2.normalize(hist_after, hist_after)
    histogram_distance = float(cv2.compareHist(hist_before, hist_after, cv2.HISTCMP_BHATTACHARYYA))
    return {
        "gray_mae": round(mae, 4),
        "histogram_distance": round(histogram_distance, 5),
    }


def _motion_metrics(path: Path) -> dict[str, float | int]:
    capture = cv2.VideoCapture(str(path))
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    stride = max(1, round(fps / 10.0))
    previous: np.ndarray | None = None
    distances: list[float] = []
    flows: list[float] = []
    sampled = 0
    index = 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        if index % stride:
            index += 1
            continue
        current = _resize_gray(frame)
        if previous is not None:
            distances.append(float(np.mean(cv2.absdiff(previous, current))))
            flow = cv2.calcOpticalFlowFarneback(
                previous, current, None, 0.5, 3, 17, 3, 5, 1.1, 0,
            )
            magnitude = cv2.magnitude(flow[..., 0], flow[..., 1])
            flows.append(float(np.median(magnitude)))
        previous = current
        sampled += 1
        index += 1
    capture.release()
    duplicate_ratio = (
        sum(value < 0.85 for value in distances) / len(distances) if distances else 1.0
    )
    return {
        "fps": round(fps, 4),
        "frame_count": frame_count,
        "sampled_frames": sampled,
        "mean_frame_distance": round(float(np.mean(distances)) if distances else 0.0, 4),
        "median_flow": round(float(np.median(flows)) if flows else 0.0, 5),
        "flow_p90": round(float(np.percentile(flows, 90)) if flows else 0.0, 5),
        "duplicate_ratio": round(duplicate_ratio, 5),
    }


def _sample_frame(capture: cv2.VideoCapture, seconds: float) -> np.ndarray:
    capture.set(cv2.CAP_PROP_POS_MSEC, max(0.0, seconds) * 1000.0)
    ok, frame = capture.read()
    if not ok:
        raise RuntimeError(f"unable to sample candidate at {seconds:.3f}s")
    return frame


def _write_contact_sheets(video: Path, beats: list[dict], output_dir: Path) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(video))
    paths: list[str] = []
    thumb_width, thumb_height = 216, 384
    for page, offset in enumerate(range(0, len(beats), 6), start=1):
        page_beats = beats[offset:offset + 6]
        canvas = np.zeros((len(page_beats) * thumb_height, 5 * thumb_width, 3), dtype=np.uint8)
        for row, beat in enumerate(page_beats):
            start = float(beat["timeline_start_seconds"])
            duration = float(beat["duration_seconds"])
            for column, fraction in enumerate((0.04, 0.27, 0.50, 0.73, 0.96)):
                frame = _sample_frame(capture, start + duration * fraction)
                frame = cv2.resize(frame, (thumb_width, thumb_height), interpolation=cv2.INTER_AREA)
                label = f"{beat['beat_id']} {fraction:.2f}"
                cv2.rectangle(frame, (0, 0), (thumb_width, 28), (0, 0, 0), -1)
                cv2.putText(frame, label, (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1, cv2.LINE_AA)
                y0 = row * thumb_height
                x0 = column * thumb_width
                canvas[y0:y0 + thumb_height, x0:x0 + thumb_width] = frame
        target = output_dir / f"motion_contact_page_{page}.jpg"
        cv2.imwrite(str(target), canvas, [cv2.IMWRITE_JPEG_QUALITY, 92])
        paths.append(str(target.resolve()))
    capture.release()
    return paths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--contact-dir", type=Path, required=True)
    args = parser.parse_args()

    manifest_path = args.manifest.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    video = Path(manifest["video_path"]).resolve()
    beats = list(manifest["beats"])
    cut_rows: list[dict] = []
    boundaries: list[dict] = []
    flags: list[dict] = []
    expected_static_cuts: list[dict] = []

    for beat in beats:
        action = str(beat.get("action") or "")
        expects_motion = any(word in action.lower() for word in MOVE_WORDS)
        cuts = list(beat.get("cuts") or [])
        for cut in cuts:
            path = Path(cut["path"]).resolve()
            metrics = _motion_metrics(path)
            cut_kind = str(cut.get("kind") or "video")
            family = str(cut.get("family") or "")
            expected_static = cut_kind in {"ui_insert", "end_hold"} or family == "deterministic_ui"
            expects_cut_motion = expects_motion and not expected_static
            row = {
                "beat_id": beat["beat_id"],
                "cut_index": cut.get("cut_index"),
                "kind": cut_kind,
                "family": family,
                "reason": cut.get("reason"),
                "duration_seconds": cut.get("duration_seconds"),
                "path": str(path),
                "expects_visible_motion": expects_cut_motion,
                "expected_static": expected_static,
                **metrics,
            }
            cut_rows.append(row)
            if expected_static:
                expected_static_cuts.append({
                    "beat_id": beat["beat_id"],
                    "path": str(path),
                    "reason": cut.get("reason"),
                })
            elif expects_cut_motion and float(metrics["duplicate_ratio"]) > 0.60:
                flags.append({"code": "likely_static_or_repeated_frames", "beat_id": beat["beat_id"], "path": str(path)})
            if (
                expects_cut_motion
                and float(metrics["mean_frame_distance"]) < 0.8
                and float(metrics["flow_p90"]) < 0.08
            ):
                flags.append({"code": "declared_action_has_low_motion", "beat_id": beat["beat_id"], "path": str(path)})
        for left, right in zip(cuts, cuts[1:]):
            result = _boundary_metrics(Path(left["path"]), Path(right["path"]))
            boundary = {
                "beat_id": beat["beat_id"],
                "left": left["path"],
                "right": right["path"],
                **result,
            }
            boundaries.append(boundary)
            if result["gray_mae"] > 34.0 and result["histogram_distance"] > 0.42:
                flags.append({"code": "same_action_cut_discontinuity", **boundary})

    contacts = _write_contact_sheets(video, beats, args.contact_dir.resolve())
    report = {
        "schema": "reference_404263_motion_continuity_audit/v1",
        "status": "requires_human_action_review",
        "manifest": str(manifest_path),
        "video": str(video),
        "publish_allowed": False,
        "automated_scope": [
            "motion amount", "duplicate-frame suspicion", "same-action cut boundary distance", "dense contact evidence"
        ],
        "not_proven_by_machine": [
            "anatomy", "natural acting", "gaze correctness", "phone persistence", "identity continuity", "story meaning"
        ],
        "automated_flags": flags,
        "expected_static_cuts": expected_static_cuts,
        "same_action_boundaries": boundaries,
        "cuts": cut_rows,
        "contact_sheets": contacts,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "flags": len(flags), "contacts": contacts}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
