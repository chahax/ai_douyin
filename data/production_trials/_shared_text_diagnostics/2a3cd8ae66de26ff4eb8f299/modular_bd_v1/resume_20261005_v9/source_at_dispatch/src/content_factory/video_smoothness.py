"""Gated frame interpolation with cadence and motion-retention evidence."""

from __future__ import annotations

import json
import math
import shutil
import statistics
import subprocess
from dataclasses import dataclass
from pathlib import Path

from src.content_factory.video_control_gate import (
    VideoControlGate,
    VideoControlManifest,
)


MANIFEST_TEMPLATE = "video_smoothness/v1"
REPORT_TEMPLATE = "video_smoothness_report/v1"
ALGORITHMS = {"minterpolate"}


@dataclass(frozen=True, slots=True)
class SmoothnessAcceptance:
    minimum_score_gain: float
    maximum_duplicate_ratio: float
    minimum_motion_retention: float
    maximum_motion_retention: float
    maximum_duration_delta: float
    minimum_motion_distance: float
    duplicate_threshold: float


@dataclass(frozen=True, slots=True)
class VideoSmoothnessManifest:
    manifest_path: Path
    input_video: Path
    input_control_manifest: Path
    input_control_report: Path
    output_video: Path
    algorithm: str
    target_fps: float
    analysis_width: int
    acceptance: SmoothnessAcceptance
    crf: int
    preset: str

    @classmethod
    def load(cls, manifest_path: str | Path) -> "VideoSmoothnessManifest":
        path = Path(manifest_path).resolve()
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("template") != MANIFEST_TEMPLATE:
            raise ValueError(f"template must be {MANIFEST_TEMPLATE}")

        raw_smoothing = data.get("smoothing", {})
        if not isinstance(raw_smoothing, dict):
            raise ValueError("smoothing must be an object")
        algorithm = str(
            raw_smoothing.get("algorithm", "minterpolate")
        ).strip()
        if algorithm not in ALGORITHMS:
            choices = ", ".join(sorted(ALGORITHMS))
            raise ValueError(f"smoothing.algorithm must be one of: {choices}")
        target_fps = _bounded_float(
            raw_smoothing,
            "target_fps",
            default=30.0,
            minimum=20.0,
            maximum=60.0,
        )
        analysis_width = _bounded_int(
            raw_smoothing,
            "analysis_width",
            default=160,
            minimum=64,
            maximum=320,
        )

        raw_acceptance = data.get("acceptance", {})
        if not isinstance(raw_acceptance, dict):
            raise ValueError("acceptance must be an object")
        acceptance = SmoothnessAcceptance(
            minimum_score_gain=_bounded_float(
                raw_acceptance,
                "minimum_score_gain",
                default=5.0,
                minimum=0.0,
                maximum=50.0,
            ),
            maximum_duplicate_ratio=_bounded_float(
                raw_acceptance,
                "maximum_duplicate_ratio",
                default=0.12,
                minimum=0.0,
                maximum=0.5,
            ),
            minimum_motion_retention=_bounded_float(
                raw_acceptance,
                "minimum_motion_retention",
                default=0.7,
                minimum=0.1,
                maximum=1.0,
            ),
            maximum_motion_retention=_bounded_float(
                raw_acceptance,
                "maximum_motion_retention",
                default=1.4,
                minimum=1.0,
                maximum=3.0,
            ),
            maximum_duration_delta=_bounded_float(
                raw_acceptance,
                "maximum_duration_delta",
                default=0.08,
                minimum=0.0,
                maximum=0.5,
            ),
            minimum_motion_distance=_bounded_float(
                raw_acceptance,
                "minimum_motion_distance",
                default=0.12,
                minimum=0.0,
                maximum=3.0,
            ),
            duplicate_threshold=_bounded_float(
                raw_acceptance,
                "duplicate_threshold",
                default=0.12,
                minimum=0.0,
                maximum=2.0,
            ),
        )
        if (
            acceptance.minimum_motion_retention
            >= acceptance.maximum_motion_retention
        ):
            raise ValueError(
                "acceptance.minimum_motion_retention must be below "
                "maximum_motion_retention"
            )

        raw_encoding = data.get("encoding", {})
        if not isinstance(raw_encoding, dict):
            raise ValueError("encoding must be an object")
        return cls(
            manifest_path=path,
            input_video=_required_path(path, data, "input_video"),
            input_control_manifest=_required_path(
                path,
                data,
                "input_control_manifest",
            ),
            input_control_report=_required_path(
                path,
                data,
                "input_control_report",
            ),
            output_video=_required_path(path, data, "output_video"),
            algorithm=algorithm,
            target_fps=target_fps,
            analysis_width=analysis_width,
            acceptance=acceptance,
            crf=_bounded_int(
                raw_encoding,
                "crf",
                default=18,
                minimum=0,
                maximum=51,
            ),
            preset=str(raw_encoding.get("preset", "slow")).strip() or "slow",
        )

    def validate_assets(self) -> None:
        missing = [
            path
            for path in (
                self.input_video,
                self.input_control_manifest,
                self.input_control_report,
            )
            if not path.is_file()
        ]
        if missing:
            names = ", ".join(str(path) for path in missing)
            raise FileNotFoundError(f"smoothness assets missing: {names}")

    def plan(self) -> dict[str, object]:
        return {
            "template": "video_smoothness_plan/v1",
            "input_video": str(self.input_video),
            "output_video": str(self.output_video),
            "algorithm": self.algorithm,
            "target_fps": self.target_fps,
            "analysis_width": self.analysis_width,
            "control_mode": "post_gate_interpolation",
        }


def run_video_smoothness(
    manifest_path: str | Path,
    *,
    report_path: str | Path | None = None,
    dry_run: bool = False,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
) -> dict[str, object]:
    manifest = VideoSmoothnessManifest.load(manifest_path)
    manifest.validate_assets()
    input_control = VideoControlManifest.load(manifest.input_control_manifest)
    input_report = _read_json(manifest.input_control_report)
    plan = manifest.plan()
    blocked_issues = _input_gate_blockers(
        manifest,
        input_control,
        input_report,
    )
    plan["blocked_issue_codes"] = blocked_issues
    if dry_run:
        return plan
    if blocked_issues:
        return _write_result(
            manifest,
            {
                "template": REPORT_TEMPLATE,
                "status": "blocked",
                "output": None,
                "reason": "input_control_gate_not_accepted",
                "blocked_issue_codes": blocked_issues,
                "plan": plan,
            },
            report_path,
        )

    input_probe = _probe_video(manifest.input_video, ffprobe=ffprobe)
    if input_probe["fps"] >= manifest.target_fps - 0.01:
        return _write_result(
            manifest,
            {
                "template": REPORT_TEMPLATE,
                "status": "no_action",
                "output": None,
                "reason": "input_fps_already_meets_target",
                "input_metadata": input_probe,
                "plan": plan,
            },
            report_path,
        )
    input_metrics = analyze_video_smoothness(
        manifest.input_video,
        analysis_fps=manifest.target_fps,
        analysis_width=manifest.analysis_width,
        duplicate_threshold=manifest.acceptance.duplicate_threshold,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
    )
    if (
        float(input_metrics["mean_frame_distance"])
        < manifest.acceptance.minimum_motion_distance
    ):
        return _write_result(
            manifest,
            {
                "template": REPORT_TEMPLATE,
                "status": "no_action",
                "output": None,
                "reason": "motion_too_low_for_interpolation",
                "input_metadata": input_probe,
                "input_smoothness": input_metrics,
                "plan": plan,
            },
            report_path,
        )

    output = manifest.output_video
    output.parent.mkdir(parents=True, exist_ok=True)
    pending = output.with_name(f"{output.stem}.pending{output.suffix}")
    pending.unlink(missing_ok=True)
    _render_minterpolate(
        manifest,
        pending,
        input_probe=input_probe,
        ffmpeg=ffmpeg,
    )

    output_control_manifest = output.with_suffix(
        ".control.manifest.json"
    )
    output_control_report = output.with_suffix(".control.report.json")
    raw_control = _read_json(manifest.input_control_manifest)
    raw_control["video_path"] = str(pending)
    output_control_manifest.write_text(
        json.dumps(raw_control, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    gate_report = VideoControlGate().inspect_manifest(
        output_control_manifest,
        output_control_report,
    )
    output_probe = _probe_video(pending, ffprobe=ffprobe)
    output_metrics = analyze_video_smoothness(
        pending,
        analysis_fps=manifest.target_fps,
        analysis_width=manifest.analysis_width,
        duplicate_threshold=manifest.acceptance.duplicate_threshold,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
    )
    comparison = compare_smoothness(
        input_metrics,
        output_metrics,
        input_duration=float(input_probe["duration"]),
        output_duration=float(output_probe["duration"]),
        output_fps=float(output_probe["fps"]),
        target_fps=manifest.target_fps,
        acceptance=manifest.acceptance,
    )
    issues = [
        {
            "code": issue.code,
            "message": issue.message,
            "severity": issue.severity,
        }
        for issue in gate_report.issues
    ]
    issues.extend(comparison["issues"])
    accepted = gate_report.passed and not any(
        issue["severity"] == "error" for issue in issues
    )
    if accepted:
        pending.replace(output)
        raw_control["video_path"] = str(output)
        output_control_manifest.write_text(
            json.dumps(raw_control, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        gate_report.path = str(output)
        gate_report.write_json(output_control_report)

    result = {
        "template": REPORT_TEMPLATE,
        "status": "accepted" if accepted else "rejected",
        "output": str(output) if accepted else None,
        "pending_output": None if accepted else str(pending),
        "control_manifest": str(output_control_manifest),
        "control_report": str(output_control_report),
        "input_metadata": input_probe,
        "output_metadata": output_probe,
        "input_smoothness": input_metrics,
        "output_smoothness": output_metrics,
        "comparison": {
            key: value
            for key, value in comparison.items()
            if key != "issues"
        },
        "issues": issues,
        "plan": plan,
    }
    return _write_result(manifest, result, report_path)


def analyze_video_smoothness(
    video_path: str | Path,
    *,
    analysis_fps: float,
    analysis_width: int = 160,
    duplicate_threshold: float = 0.12,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
) -> dict[str, object]:
    path = Path(video_path)
    probe = _probe_video(path, ffprobe=ffprobe)
    source_width = int(probe["width"])
    source_height = int(probe["height"])
    analysis_height = max(
        2,
        round(source_height * analysis_width / source_width / 2) * 2,
    )
    executable = shutil.which(ffmpeg) or ffmpeg
    completed = subprocess.run(
        [
            executable,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-vf",
            (
                f"fps={analysis_fps:.8f},"
                f"scale={analysis_width}:{analysis_height}:flags=area,"
                "format=gray"
            ),
            "-an",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "pipe:1",
        ],
        check=True,
        capture_output=True,
    )
    frame_size = analysis_width * analysis_height
    frame_count = len(completed.stdout) // frame_size
    if frame_count < 3:
        raise ValueError(f"at least three analysis frames are required: {path}")
    frames = [
        completed.stdout[index * frame_size : (index + 1) * frame_size]
        for index in range(frame_count)
    ]
    distances = [
        _frame_distance(frames[index - 1], frames[index])
        for index in range(1, frame_count)
    ]
    metrics = summarize_frame_distances(
        distances,
        duplicate_threshold=duplicate_threshold,
    )
    return {
        "analysis_fps": analysis_fps,
        "analysis_width": analysis_width,
        "analysis_height": analysis_height,
        "analysis_frame_count": frame_count,
        **metrics,
    }


def summarize_frame_distances(
    distances: list[float],
    *,
    duplicate_threshold: float,
) -> dict[str, float]:
    if len(distances) < 2:
        raise ValueError("at least two frame distances are required")
    mean_distance = statistics.fmean(distances)
    median_distance = statistics.median(distances)
    duplicate_ratio = sum(
        value <= duplicate_threshold for value in distances
    ) / len(distances)
    jerk_values = [
        abs(distances[index] - distances[index - 1])
        for index in range(1, len(distances))
    ]
    normalized_jerk = statistics.fmean(jerk_values) / max(
        mean_distance,
        duplicate_threshold,
        1e-6,
    )
    moving = [value for value in distances if value > duplicate_threshold]
    moving_median = statistics.median(moving) if moving else 0.0
    low = max(duplicate_threshold, moving_median * 0.25)
    high = moving_median * 2.5 if moving_median else duplicate_threshold
    cadence_outlier_ratio = sum(
        value <= low or value >= high for value in distances
    ) / len(distances)
    score = 100.0
    score -= duplicate_ratio * 45.0
    score -= min(normalized_jerk, 4.0) * 12.0
    score -= cadence_outlier_ratio * 20.0
    return {
        "mean_frame_distance": round(mean_distance, 6),
        "median_frame_distance": round(median_distance, 6),
        "motion_path": round(sum(distances), 6),
        "duplicate_ratio": round(duplicate_ratio, 6),
        "normalized_jerk": round(normalized_jerk, 6),
        "cadence_outlier_ratio": round(cadence_outlier_ratio, 6),
        "smoothness_score": round(max(0.0, score), 4),
    }


def compare_smoothness(
    input_metrics: dict[str, object],
    output_metrics: dict[str, object],
    *,
    input_duration: float,
    output_duration: float,
    output_fps: float,
    target_fps: float,
    acceptance: SmoothnessAcceptance,
) -> dict[str, object]:
    input_score = float(input_metrics["smoothness_score"])
    output_score = float(output_metrics["smoothness_score"])
    input_path = float(input_metrics["motion_path"])
    output_path = float(output_metrics["motion_path"])
    score_gain = output_score - input_score
    motion_retention = output_path / input_path if input_path > 0 else 1.0
    duplicate_ratio = float(output_metrics["duplicate_ratio"])
    duration_delta = abs(output_duration - input_duration)
    issues: list[dict[str, str]] = []
    if abs(output_fps - target_fps) > 0.02:
        issues.append(
            _issue(
                "smoothness_target_fps_mismatch",
                f"output fps {output_fps:.4f} does not match {target_fps:.4f}",
            )
        )
    if score_gain < acceptance.minimum_score_gain:
        issues.append(
            _issue(
                "smoothness_gain_insufficient",
                f"smoothness gain {score_gain:.3f} is below "
                f"{acceptance.minimum_score_gain:.3f}",
            )
        )
    if duplicate_ratio > acceptance.maximum_duplicate_ratio:
        issues.append(
            _issue(
                "duplicate_frames_excessive",
                f"duplicate ratio {duplicate_ratio:.4f} exceeds "
                f"{acceptance.maximum_duplicate_ratio:.4f}",
            )
        )
    if not (
        acceptance.minimum_motion_retention
        <= motion_retention
        <= acceptance.maximum_motion_retention
    ):
        issues.append(
            _issue(
                "motion_retention_out_of_range",
                f"motion retention {motion_retention:.4f} is outside "
                f"{acceptance.minimum_motion_retention:.4f}-"
                f"{acceptance.maximum_motion_retention:.4f}",
            )
        )
    if duration_delta > acceptance.maximum_duration_delta:
        issues.append(
            _issue(
                "smoothness_duration_changed",
                f"duration delta {duration_delta:.4f}s exceeds "
                f"{acceptance.maximum_duration_delta:.4f}s",
            )
        )
    return {
        "score_gain": round(score_gain, 4),
        "motion_retention": round(motion_retention, 4),
        "duration_delta": round(duration_delta, 4),
        "issues": issues,
    }


def _render_minterpolate(
    manifest: VideoSmoothnessManifest,
    output_path: Path,
    *,
    input_probe: dict[str, object],
    ffmpeg: str,
) -> None:
    executable = shutil.which(ffmpeg) or ffmpeg
    duration = float(input_probe["duration"])
    target_frames = max(2, round(duration * manifest.target_fps))
    filter_chain = (
        f"minterpolate=fps={manifest.target_fps:.8f}:mi_mode=mci:"
        "mc_mode=aobmc:me_mode=bidir:vsbmc=1,"
        "tpad=stop_mode=clone:stop_duration=1,"
        f"trim=end_frame={target_frames},"
        f"setpts=N/({manifest.target_fps:.8f}*TB)"
    )
    result = subprocess.run(
        [
            executable,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(manifest.input_video),
            "-vf",
            filter_chain,
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-r",
            f"{manifest.target_fps:.8f}",
            "-fps_mode",
            "cfr",
            "-c:v",
            "libx264",
            "-crf",
            str(manifest.crf),
            "-preset",
            manifest.preset,
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"FFmpeg minterpolate failed: {result.stderr[-2000:]}"
        )


def _input_gate_blockers(
    manifest: VideoSmoothnessManifest,
    control: VideoControlManifest,
    report: dict[str, object],
) -> list[str]:
    blockers: list[str] = []
    if control.video_path.resolve() != manifest.input_video.resolve():
        blockers.append("control_manifest_video_mismatch")
    raw_report_path = report.get("path")
    if not isinstance(raw_report_path, str) or (
        Path(raw_report_path).resolve() != manifest.input_video.resolve()
    ):
        blockers.append("control_report_video_mismatch")
    if report.get("passed") is not True:
        raw_issues = report.get("issues", [])
        if isinstance(raw_issues, list):
            blockers.extend(
                str(issue.get("code"))
                for issue in raw_issues
                if isinstance(issue, dict) and issue.get("code")
            )
        if len(blockers) == 0:
            blockers.append("input_control_gate_failed")
    return sorted(set(blockers))


def _probe_video(path: Path, *, ffprobe: str) -> dict[str, object]:
    executable = shutil.which(ffprobe) or ffprobe
    result = subprocess.run(
        [
            executable,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,avg_frame_rate,nb_frames,duration",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    if not streams:
        raise ValueError(f"video stream missing: {path}")
    stream = streams[0]
    numerator, denominator = str(stream["avg_frame_rate"]).split("/", 1)
    fps = float(numerator) / float(denominator)
    duration = float(stream.get("duration") or data["format"]["duration"])
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "fps": round(fps, 6),
        "frame_count": int(stream.get("nb_frames") or round(duration * fps)),
        "duration": round(duration, 6),
    }


def _frame_distance(before: bytes, after: bytes) -> float:
    return sum(
        abs(first - second)
        for first, second in zip(before, after, strict=True)
    ) / len(before)


def _issue(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message, "severity": "error"}


def _write_result(
    manifest: VideoSmoothnessManifest,
    result: dict[str, object],
    report_path: str | Path | None,
) -> dict[str, object]:
    destination = (
        Path(report_path)
        if report_path is not None
        else manifest.output_video.with_suffix(".smoothness.report.json")
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def _read_json(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return data


def _required_path(
    manifest_path: Path,
    data: dict[str, object],
    key: str,
) -> Path:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required")
    path = Path(value)
    if not path.is_absolute():
        path = manifest_path.parent / path
    return path.resolve()


def _bounded_float(
    data: dict[str, object],
    key: str,
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    raw = data.get(key, default)
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise ValueError(f"{key} must be a number")
    value = float(raw)
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}")
    return value


def _bounded_int(
    data: dict[str, object],
    key: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = data.get(key, default)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(f"{key} must be an integer")
    if not minimum <= raw <= maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}")
    return raw
