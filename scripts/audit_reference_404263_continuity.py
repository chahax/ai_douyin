"""Audit every v3 cut boundary and prepare an honest full-playback review packet."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / (
    "data/qa/reference_404263_full_workflows_20260825/candidates/controlled/"
    "candidate.v3.manifest.json"
)
FPS = 30.0


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def read_frame(capture: cv2.VideoCapture, seconds: float) -> np.ndarray:
    capture.set(cv2.CAP_PROP_POS_MSEC, max(0.0, seconds) * 1000.0)
    ok, frame = capture.read()
    if not ok or frame is None:
        raise RuntimeError(f"cannot read frame at {seconds:.3f}s")
    return frame


def compare_frames(before: np.ndarray, after: np.ndarray) -> dict[str, float]:
    before_small = cv2.resize(before, (270, 480), interpolation=cv2.INTER_AREA)
    after_small = cv2.resize(after, (270, 480), interpolation=cv2.INTER_AREA)
    mae = float(np.mean(cv2.absdiff(before_small, after_small)) / 255.0)
    before_hsv = cv2.cvtColor(before_small, cv2.COLOR_BGR2HSV)
    after_hsv = cv2.cvtColor(after_small, cv2.COLOR_BGR2HSV)
    hist_before = cv2.calcHist([before_hsv], [0, 1], None, [30, 32], [0, 180, 0, 256])
    hist_after = cv2.calcHist([after_hsv], [0, 1], None, [30, 32], [0, 180, 0, 256])
    cv2.normalize(hist_before, hist_before)
    cv2.normalize(hist_after, hist_after)
    hist_correlation = float(cv2.compareHist(hist_before, hist_after, cv2.HISTCMP_CORREL))
    return {
        "normalized_mean_absolute_difference": round(mae, 6),
        "hsv_histogram_correlation": round(hist_correlation, 6),
    }


def contact_pair(before: np.ndarray, after: np.ndarray, label: str, output: Path) -> None:
    target_height = 640
    scale = target_height / before.shape[0]
    before_view = cv2.resize(before, (int(before.shape[1] * scale), target_height))
    after_view = cv2.resize(after, (int(after.shape[1] * scale), target_height))
    pair = np.hstack([before_view, after_view])
    cv2.rectangle(pair, (0, 0), (pair.shape[1], 48), (0, 0, 0), -1)
    cv2.putText(pair, label, (14, 33), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.imwrite(str(output), pair)


def make_boundary_pages(pair_paths: list[Path], output_root: Path) -> list[Path]:
    pages: list[Path] = []
    per_page = 6
    cell_width, cell_height = 720, 408
    for page_index in range(0, len(pair_paths), per_page):
        canvas = np.zeros((cell_height * 3, cell_width * 2, 3), dtype=np.uint8)
        for local_index, path in enumerate(pair_paths[page_index:page_index + per_page]):
            image = cv2.imread(str(path))
            if image is None:
                raise RuntimeError(f"cannot read boundary pair {path}")
            image = cv2.resize(image, (cell_width, cell_height), interpolation=cv2.INTER_AREA)
            row, column = divmod(local_index, 2)
            y, x = row * cell_height, column * cell_width
            canvas[y:y + cell_height, x:x + cell_width] = image
        page = output_root / f"boundary_page_{page_index // per_page + 1}.jpg"
        cv2.imwrite(str(page), canvas)
        pages.append(page)
    return pages


def make_full_contact_pages(video: Path, output_root: Path, duration_seconds: float) -> list[Path]:
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise RuntimeError(f"cannot open {video}")
    frames: list[tuple[int, np.ndarray]] = []
    for second in range(0, int(duration_seconds) + 1):
        frames.append((second, read_frame(capture, float(second))))
    capture.release()

    pages: list[Path] = []
    per_page = 20
    cell_width, cell_height = 216, 414
    for page_index in range(0, len(frames), per_page):
        canvas = np.zeros((cell_height * 4, cell_width * 5, 3), dtype=np.uint8)
        for local_index, (second, frame) in enumerate(frames[page_index:page_index + per_page]):
            view = cv2.resize(frame, (cell_width, 384), interpolation=cv2.INTER_AREA)
            cell = np.zeros((cell_height, cell_width, 3), dtype=np.uint8)
            cell[:384] = view
            cv2.putText(cell, f"{second:03d}s", (8, 406), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
            row, column = divmod(local_index, 5)
            y, x = row * cell_height, column * cell_width
            canvas[y:y + cell_height, x:x + cell_width] = cell
        page = output_root / f"full_contact_1fps_page_{page_index // per_page + 1}.jpg"
        cv2.imwrite(str(page), canvas)
        pages.append(page)
    return pages


def flatten_cuts(manifest: dict[str, object]) -> list[dict[str, object]]:
    cuts: list[dict[str, object]] = []
    for beat in manifest["beats"]:
        cuts.extend(dict(cut) for cut in beat["cuts"])
    return cuts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()

    manifest_path = args.manifest.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "reference_404263_full_candidate/v3":
        raise ValueError("continuity audit requires a v3 manifest")
    video = Path(str(manifest["video_path"])).resolve()
    if not video.is_file() or sha256(video) != manifest["video_sha256"]:
        raise ValueError("manifest video is missing or its hash changed")

    output_root = manifest_path.parent / "continuity_review_v3"
    pairs_root = output_root / "boundary_pairs"
    pairs_root.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise RuntimeError(f"cannot open {video}")

    cuts = flatten_cuts(manifest)
    rows: list[dict[str, object]] = []
    pair_paths: list[Path] = []
    machine_failures: list[str] = []
    for index, (left, right) in enumerate(zip(cuts, cuts[1:]), start=1):
        boundary = float(left["timeline_start_seconds"]) + float(left["duration_seconds"])
        before = read_frame(capture, boundary - 2 / FPS)
        after = read_frame(capture, boundary + 2 / FPS)
        metrics = compare_frames(before, after)
        transition = str(left.get("transition_out") or "scene_cut")
        pair_path = pairs_root / f"{index:02d}_{left['beat_id']}_to_{right['beat_id']}.jpg"
        contact_pair(before, after, f"{boundary:07.3f}s  {transition}", pair_path)
        pair_paths.append(pair_path)

        machine_status = "not_gated_story_cut"
        if transition in {"continuous_source", "continuous_hold"}:
            machine_status = "pass"
            if (
                float(metrics["normalized_mean_absolute_difference"]) > 0.14
                or float(metrics["hsv_histogram_correlation"]) < 0.70
            ):
                machine_status = "fail"
                machine_failures.append(f"{left['cut_index']}->{right['cut_index']}")
        elif transition == "continuous_story":
            machine_status = "human_review_required"
        elif transition == "motivated_insert":
            machine_status = "human_review_required"

        rows.append({
            "boundary_index": index,
            "timestamp_seconds": round(boundary, 6),
            "from_cut_index": left["cut_index"],
            "from_beat": left["beat_id"],
            "to_cut_index": right["cut_index"],
            "to_beat": right["beat_id"],
            "transition_contract": transition,
            "machine_status": machine_status,
            "metrics": metrics,
            "pair_path": str(pair_path),
            "pair_sha256": sha256(pair_path),
            "human_status": "pending",
            "human_notes": ""
        })
    capture.release()

    boundary_pages = make_boundary_pages(pair_paths, output_root)
    full_contact_pages = make_full_contact_pages(
        video,
        output_root,
        float(manifest["actual_duration_seconds"]),
    )

    machine_status = "fail" if machine_failures else "pass_structural_edges_only"
    report = {
        "schema": "reference_404263_continuity_audit/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "candidate_manifest_path": str(manifest_path),
        "candidate_manifest_sha256": sha256(manifest_path),
        "video_path": str(video),
        "video_sha256": sha256(video),
        "machine_continuity_status": machine_status,
        "machine_failures": machine_failures,
        "human_transition_review_status": "pending",
        "full_playback_status": "pending",
        "boundary_contact_pages": [
            {"path": str(path), "sha256": sha256(path)} for path in boundary_pages
        ],
        "full_contact_pages": [
            {"path": str(path), "sha256": sha256(path)} for path in full_contact_pages
        ],
        "disclaimer": (
            "Pixel metrics only gate exact sequential-source and end-hold edges. "
            "They do not prove action naturalness, story continuity, or viewing quality."
        ),
        "boundaries": rows,
    }
    report_path = output_root / "continuity_audit.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    review = {
        "schema": "reference_404263_full_playback_review/v1",
        "candidate_manifest_path": str(manifest_path),
        "candidate_video_path": str(video),
        "reviewer": "",
        "review_started_at": "",
        "review_completed_at": "",
        "playback_speed": 1.0,
        "audio_enabled": True,
        "subtitles_enabled": True,
        "uninterrupted_full_playback": False,
        "reviewed_seconds": 0.0,
        "hard_rejects": [],
        "timestamped_issues": [],
        "scores": {
            "full_viewing_experience_35": None,
            "action_and_transition_continuity_25": None,
            "identity_costume_prop_15": None,
            "composition_style_readability_15": None,
            "audio_subtitle_delivery_10": None,
            "total_100": None
        },
        "decision_rule": "total >= 80 and hard_rejects is empty",
        "decision": "pending_human_full_playback",
        "publish_allowed": False
    }
    review_path = output_root / "full_playback_review.template.json"
    review_path.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_path), "review_template": str(review_path), "machine_status": machine_status}, ensure_ascii=False))
    return 0 if not machine_failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
