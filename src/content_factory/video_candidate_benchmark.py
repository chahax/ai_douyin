"""Compare controlled-video candidates with one shared acceptance policy."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from src.content_factory.video_control_gate import (
    ControlRegion,
    VideoControlGate,
    VideoControlManifest,
    VideoControlReport,
)


@dataclass(frozen=True, slots=True)
class VideoCandidate:
    candidate_id: str
    tool: str
    control_manifest_path: Path
    control: VideoControlManifest


@dataclass(frozen=True, slots=True)
class VideoCandidateBenchmark:
    benchmark_id: str
    manifest_path: Path
    candidates: tuple[VideoCandidate, ...]
    target_fps: float
    target_duration: float | None

    @classmethod
    def load(cls, manifest_path: str | Path) -> "VideoCandidateBenchmark":
        path = Path(manifest_path).resolve()
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("template") != "video_candidate_benchmark/v1":
            raise ValueError("template must be video_candidate_benchmark/v1")
        benchmark_id = _required_string(data, "id")
        raw_candidates = data.get("candidates")
        if not isinstance(raw_candidates, list) or len(raw_candidates) < 2:
            raise ValueError("candidates must contain at least two items")

        candidates: list[VideoCandidate] = []
        for index, raw_candidate in enumerate(raw_candidates):
            if not isinstance(raw_candidate, dict):
                raise ValueError(f"candidates[{index}] must be an object")
            candidate_id = _required_string(raw_candidate, "id")
            tool = _required_string(raw_candidate, "tool")
            control_path = _resolve_path(
                path,
                _required_string(raw_candidate, "control_manifest"),
            )
            if not control_path.is_file():
                raise FileNotFoundError(
                    f"candidate control manifest missing: {control_path}"
                )
            candidates.append(
                VideoCandidate(
                    candidate_id=candidate_id,
                    tool=tool,
                    control_manifest_path=control_path,
                    control=VideoControlManifest.load(control_path),
                )
            )

        ids = [candidate.candidate_id for candidate in candidates]
        if len(set(ids)) != len(ids):
            raise ValueError("candidate ids must be unique")
        modes = {candidate.control.mode for candidate in candidates}
        if len(modes) != 1:
            raise ValueError("all candidates must use the same control mode")
        references = {
            candidate.control.reference_image.resolve()
            if candidate.control.reference_image is not None
            else None
            for candidate in candidates
        }
        if len(references) != 1:
            raise ValueError("all candidates must use the same reference image")

        raw_ranking = data.get("ranking", {})
        if not isinstance(raw_ranking, dict):
            raise ValueError("ranking must be an object")
        target_fps = _positive_float(raw_ranking, "target_fps", 30.0)
        target_duration = _optional_positive_float(
            raw_ranking,
            "target_duration",
        )
        return cls(
            benchmark_id=benchmark_id,
            manifest_path=path,
            candidates=tuple(candidates),
            target_fps=target_fps,
            target_duration=target_duration,
        )


def run_video_candidate_benchmark(
    manifest_path: str | Path,
    *,
    output_dir: str | Path,
    report_path: str | Path | None = None,
) -> dict[str, object]:
    benchmark = VideoCandidateBenchmark.load(manifest_path)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    gate = VideoControlGate()
    for candidate in benchmark.candidates:
        control_report_path = destination / f"{candidate.candidate_id}.control.json"
        report = gate.inspect_manifest(
            candidate.control_manifest_path,
            control_report_path,
        )
        score = score_control_report(
            report,
            candidate.control.regions,
            target_fps=benchmark.target_fps,
            target_duration=benchmark.target_duration,
        )
        results.append(
            {
                "id": candidate.candidate_id,
                "tool": candidate.tool,
                "video_path": str(candidate.control.video_path),
                "control_manifest": str(candidate.control_manifest_path),
                "control_report": str(control_report_path),
                "mode": candidate.control.mode,
                "passed": report.passed,
                "score": score if report.passed else None,
                "metadata": report.metadata,
                "issues": [asdict(issue) for issue in report.issues],
            }
        )

    results.sort(
        key=lambda result: (
            not bool(result["passed"]),
            -(float(result["score"]) if result["score"] is not None else 0.0),
            str(result["id"]),
        )
    )
    accepted = [result for result in results if result["passed"]]
    winner = accepted[0] if accepted else None
    output = {
        "template": "video_candidate_benchmark_report/v1",
        "id": benchmark.benchmark_id,
        "status": "accepted" if winner is not None else "rejected",
        "winner": winner["id"] if winner is not None else None,
        "winner_video": winner["video_path"] if winner is not None else None,
        "ranking": {
            "target_fps": benchmark.target_fps,
            "target_duration": benchmark.target_duration,
        },
        "candidates": results,
    }
    report_destination = (
        Path(report_path)
        if report_path is not None
        else destination / f"{benchmark.benchmark_id}.benchmark.json"
    )
    report_destination.parent.mkdir(parents=True, exist_ok=True)
    report_destination.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output


def score_control_report(
    report: VideoControlReport,
    regions: tuple[ControlRegion, ...],
    *,
    target_fps: float = 30.0,
    target_duration: float | None = None,
) -> float:
    if not report.passed:
        return 0.0
    temporal = _metrics(report.metadata.get("temporal"))
    score = 100.0
    score -= temporal["luma_range"] * 1.5
    score -= temporal["chroma_range"] * 1.5
    score -= temporal["max_frame_distance"] * 0.4
    score -= temporal["max_anchor_distance"] * 0.5
    score -= temporal["max_active_pixel_ratio"] * 15.0

    fps = _number(report.metadata.get("fps"))
    if fps is not None:
        score -= abs(fps - target_fps) * 0.35
    duration = _number(report.metadata.get("duration"))
    if duration is not None and target_duration is not None:
        score -= abs(duration - target_duration)

    raw_region_metrics = report.metadata.get("regions")
    region_metrics = (
        raw_region_metrics if isinstance(raw_region_metrics, dict) else {}
    )
    for region in regions:
        values = _metrics(region_metrics.get(region.name))
        if region.motion == "static":
            score -= values["max_frame_distance"] * 1.2
            score -= values["max_anchor_distance"] * 1.2
            score -= values["max_active_pixel_ratio"] * 25.0
            if region.reference_lock:
                score -= values["max_reference_distance"] * 0.2
        else:
            score -= max(0.0, values["max_frame_distance"] - 3.0) * 0.1
            score -= max(0.0, values["max_anchor_distance"] - 5.0) * 0.1
    return round(max(0.0, score), 3)


def _metrics(value: object) -> dict[str, float]:
    data = value if isinstance(value, dict) else {}
    names = (
        "luma_range",
        "chroma_range",
        "max_frame_distance",
        "max_anchor_distance",
        "max_active_pixel_ratio",
        "max_reference_distance",
    )
    return {
        name: _number(data.get(name)) or 0.0
        for name in names
    }


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _required_string(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required")
    return value.strip()


def _resolve_path(manifest_path: Path, value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (manifest_path.parent / path).resolve()


def _positive_float(
    data: dict[str, object],
    key: str,
    default: float,
) -> float:
    value = _number(data.get(key, default))
    if value is None or value <= 0:
        raise ValueError(f"{key} must be a positive number")
    return value


def _optional_positive_float(
    data: dict[str, object],
    key: str,
) -> float | None:
    if data.get(key) is None:
        return None
    value = _number(data.get(key))
    if value is None or value <= 0:
        raise ValueError(f"{key} must be a positive number")
    return value
