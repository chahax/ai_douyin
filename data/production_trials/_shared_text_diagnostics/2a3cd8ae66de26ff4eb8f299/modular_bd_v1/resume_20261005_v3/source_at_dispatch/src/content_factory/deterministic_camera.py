"""Deterministic full-frame camera motion for approved still images."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image, ImageOps

from src.content_factory.video_control_gate import VideoControlGate


MANIFEST_TEMPLATE = "deterministic_camera/v1"
REPORT_TEMPLATE = "deterministic_camera_report/v1"
EASING_MODES = {"linear", "smooth"}


@dataclass(frozen=True, slots=True)
class CameraMotion:
    start_zoom: float
    end_zoom: float
    start_center: tuple[float, float]
    end_center: tuple[float, float]
    easing: str


@dataclass(frozen=True, slots=True)
class CameraSafety:
    maximum_zoom: float
    maximum_zoom_delta: float
    maximum_pan_distance: float
    minimum_activity_ratio: float
    maximum_luma_range: float


@dataclass(frozen=True, slots=True)
class DeterministicCameraManifest:
    manifest_path: Path
    source_image: Path
    output_path: Path
    width: int
    height: int
    fps: float
    duration: float
    crf: int
    preset: str
    motion: CameraMotion
    safety: CameraSafety

    @classmethod
    def load(
        cls,
        manifest_path: str | Path,
    ) -> "DeterministicCameraManifest":
        path = Path(manifest_path).resolve()
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("template") != MANIFEST_TEMPLATE:
            raise ValueError(f"template must be {MANIFEST_TEMPLATE}")

        raw_motion = data.get("motion", {})
        if not isinstance(raw_motion, dict):
            raise ValueError("motion must be an object")
        easing = str(raw_motion.get("easing", "smooth")).strip()
        if easing not in EASING_MODES:
            choices = ", ".join(sorted(EASING_MODES))
            raise ValueError(f"motion.easing must be one of: {choices}")
        motion = CameraMotion(
            start_zoom=_bounded_float(
                raw_motion,
                "start_zoom",
                default=1.0,
                minimum=1.0,
                maximum=1.2,
            ),
            end_zoom=_bounded_float(
                raw_motion,
                "end_zoom",
                default=1.05,
                minimum=1.0,
                maximum=1.2,
            ),
            start_center=_point(
                raw_motion.get("start_center", [0.5, 0.5]),
                "motion.start_center",
            ),
            end_center=_point(
                raw_motion.get("end_center", [0.5, 0.5]),
                "motion.end_center",
            ),
            easing=easing,
        )

        raw_safety = data.get("safety", {})
        if not isinstance(raw_safety, dict):
            raise ValueError("safety must be an object")
        safety = CameraSafety(
            maximum_zoom=_bounded_float(
                raw_safety,
                "maximum_zoom",
                default=1.08,
                minimum=1.0,
                maximum=1.2,
            ),
            maximum_zoom_delta=_bounded_float(
                raw_safety,
                "maximum_zoom_delta",
                default=0.08,
                minimum=0.0,
                maximum=0.2,
            ),
            maximum_pan_distance=_bounded_float(
                raw_safety,
                "maximum_pan_distance",
                default=0.04,
                minimum=0.0,
                maximum=0.15,
            ),
            minimum_activity_ratio=_bounded_float(
                raw_safety,
                "minimum_activity_ratio",
                default=0.03,
                minimum=0.0,
                maximum=0.5,
            ),
            maximum_luma_range=_bounded_float(
                raw_safety,
                "maximum_luma_range",
                default=6.0,
                minimum=0.0,
                maximum=20.0,
            ),
        )
        _validate_motion(motion, safety)

        raw_encoding = data.get("encoding", {})
        if not isinstance(raw_encoding, dict):
            raise ValueError("encoding must be an object")
        return cls(
            manifest_path=path,
            source_image=_required_path(path, data, "source_image"),
            output_path=_required_path(path, data, "output_path"),
            width=_positive_even_int(data, "width"),
            height=_positive_even_int(data, "height"),
            fps=_positive_float(data, "fps"),
            duration=_positive_float(data, "duration_seconds"),
            crf=_bounded_int(
                raw_encoding,
                "crf",
                default=18,
                minimum=0,
                maximum=51,
            ),
            preset=str(raw_encoding.get("preset", "slow")).strip() or "slow",
            motion=motion,
            safety=safety,
        )

    @property
    def frame_count(self) -> int:
        return max(2, round(self.duration * self.fps))

    def validate_assets(self) -> None:
        if not self.source_image.is_file():
            raise FileNotFoundError(
                f"source image does not exist: {self.source_image}"
            )

    def plan(self) -> dict[str, object]:
        return {
            "template": "deterministic_camera_plan/v1",
            "source_image": str(self.source_image),
            "output_path": str(self.output_path),
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "duration_seconds": self.duration,
            "frame_count": self.frame_count,
            "motion": asdict(self.motion),
            "safety": asdict(self.safety),
            "control_mode": "deterministic_full_frame",
        }


def run_deterministic_camera(
    manifest_path: str | Path,
    *,
    report_path: str | Path | None = None,
    qa_dir: str | Path | None = None,
    dry_run: bool = False,
    ffmpeg: str = "ffmpeg",
) -> dict[str, object]:
    manifest = DeterministicCameraManifest.load(manifest_path)
    manifest.validate_assets()
    if dry_run:
        return manifest.plan()

    output = manifest.output_path
    output.parent.mkdir(parents=True, exist_ok=True)
    qa_root = Path(qa_dir).resolve() if qa_dir is not None else output.parent
    qa_root.mkdir(parents=True, exist_ok=True)
    pending = output.with_name(f"{output.stem}.pending{output.suffix}")
    pending.unlink(missing_ok=True)
    _render_video(manifest, pending, ffmpeg=ffmpeg)

    control_manifest = qa_root / f"{output.stem}.control.manifest.json"
    control_report = qa_root / f"{output.stem}.control.report.json"
    control_manifest.write_text(
        json.dumps(
            {
                "template": "video_control/v1",
                "video_path": str(pending),
                "reference_image": str(manifest.source_image),
                "mode": "free",
                "regions": {},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    gate_report = VideoControlGate().inspect_manifest(
        control_manifest,
        control_report,
    )
    temporal = gate_report.metadata.get("temporal", {})
    metrics = temporal if isinstance(temporal, dict) else {}
    activity_ratio = float(metrics.get("max_active_pixel_ratio", 0.0))
    luma_range = float(metrics.get("luma_range", 0.0))
    issues = [
        {
            "code": issue.code,
            "message": issue.message,
            "severity": issue.severity,
        }
        for issue in gate_report.issues
    ]
    if activity_ratio < manifest.safety.minimum_activity_ratio:
        issues.append(
            _issue(
                "camera_motion_too_subtle",
                f"activity ratio {activity_ratio:.4f} is below "
                f"{manifest.safety.minimum_activity_ratio:.4f}",
            )
        )
    if luma_range > manifest.safety.maximum_luma_range:
        issues.append(
            _issue(
                "camera_motion_luma_shift",
                f"luma range {luma_range:.3f} exceeds "
                f"{manifest.safety.maximum_luma_range:.3f}",
            )
        )
    accepted = gate_report.passed and not any(
        issue["severity"] == "error" for issue in issues
    )
    if accepted:
        pending.replace(output)
        control_data = json.loads(
            control_manifest.read_text(encoding="utf-8")
        )
        control_data["video_path"] = str(output)
        control_manifest.write_text(
            json.dumps(control_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        gate_report.path = str(output)
        gate_report.write_json(control_report)

    result = {
        "template": REPORT_TEMPLATE,
        "status": "accepted" if accepted else "rejected",
        "output": str(output) if accepted else None,
        "pending_output": None if accepted else str(pending),
        "control_manifest": str(control_manifest),
        "control_report": str(control_report),
        "activity_ratio": round(activity_ratio, 6),
        "luma_range": round(luma_range, 4),
        "issues": issues,
        "plan": manifest.plan(),
    }
    destination = (
        Path(report_path)
        if report_path is not None
        else qa_root / f"{output.stem}.camera.report.json"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def render_camera_frame(
    manifest: DeterministicCameraManifest,
    source: Image.Image,
    frame_index: int,
) -> Image.Image:
    progress = frame_index / max(1, manifest.frame_count - 1)
    eased = _ease(progress, manifest.motion.easing)
    zoom = _lerp(
        manifest.motion.start_zoom,
        manifest.motion.end_zoom,
        eased,
    )
    center_x = _lerp(
        manifest.motion.start_center[0],
        manifest.motion.end_center[0],
        eased,
    )
    center_y = _lerp(
        manifest.motion.start_center[1],
        manifest.motion.end_center[1],
        eased,
    )
    crop_width = manifest.width / zoom
    crop_height = manifest.height / zoom
    left = center_x * manifest.width - crop_width / 2
    top = center_y * manifest.height - crop_height / 2
    box = (left, top, left + crop_width, top + crop_height)
    return source.transform(
        (manifest.width, manifest.height),
        Image.Transform.EXTENT,
        box,
        resample=Image.Resampling.BICUBIC,
    )


def _render_video(
    manifest: DeterministicCameraManifest,
    output_path: Path,
    *,
    ffmpeg: str,
) -> None:
    with Image.open(manifest.source_image) as raw_source:
        source = ImageOps.fit(
            ImageOps.exif_transpose(raw_source).convert("RGB"),
            (manifest.width, manifest.height),
            method=Image.Resampling.LANCZOS,
        )

    executable = shutil.which(ffmpeg) or ffmpeg
    process = subprocess.Popen(
        [
            executable,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{manifest.width}x{manifest.height}",
            "-r",
            f"{manifest.fps:.8f}",
            "-i",
            "pipe:0",
            "-an",
            "-c:v",
            "libx264",
            "-crf",
            str(manifest.crf),
            "-preset",
            manifest.preset,
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output_path),
        ],
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if process.stdin is None or process.stderr is None:
        process.kill()
        raise RuntimeError("unable to open FFmpeg camera-motion pipes")
    try:
        for frame_index in range(manifest.frame_count):
            frame = render_camera_frame(manifest, source, frame_index)
            process.stdin.write(frame.tobytes())
        process.stdin.close()
        stderr = process.stderr.read().decode("utf-8", errors="replace")
        return_code = process.wait()
    except BaseException:
        process.kill()
        process.wait()
        raise
    if return_code != 0:
        raise RuntimeError(
            f"FFmpeg deterministic camera render failed: {stderr[-2000:]}"
        )


def _validate_motion(
    motion: CameraMotion,
    safety: CameraSafety,
) -> None:
    maximum_zoom = max(motion.start_zoom, motion.end_zoom)
    if maximum_zoom - safety.maximum_zoom > 1e-9:
        raise ValueError(
            f"motion zoom {maximum_zoom:.4f} exceeds "
            f"safety.maximum_zoom {safety.maximum_zoom:.4f}"
        )
    zoom_delta = abs(motion.end_zoom - motion.start_zoom)
    if zoom_delta - safety.maximum_zoom_delta > 1e-9:
        raise ValueError(
            f"motion zoom delta {zoom_delta:.4f} exceeds "
            f"safety.maximum_zoom_delta {safety.maximum_zoom_delta:.4f}"
        )
    pan_distance = math.dist(motion.start_center, motion.end_center)
    if pan_distance - safety.maximum_pan_distance > 1e-9:
        raise ValueError(
            f"motion pan distance {pan_distance:.4f} exceeds "
            f"safety.maximum_pan_distance {safety.maximum_pan_distance:.4f}"
        )
    if zoom_delta < 0.005 and pan_distance < 0.002:
        raise ValueError("camera motion must contain visible zoom or pan")
    for label, zoom, center in (
        ("start", motion.start_zoom, motion.start_center),
        ("end", motion.end_zoom, motion.end_center),
    ):
        minimum = 0.5 / zoom
        maximum = 1.0 - minimum
        if not (
            minimum <= center[0] <= maximum
            and minimum <= center[1] <= maximum
        ):
            raise ValueError(
                f"motion.{label}_center exposes image border at zoom {zoom:.4f}"
            )


def _ease(progress: float, mode: str) -> float:
    bounded = max(0.0, min(1.0, progress))
    if mode == "linear":
        return bounded
    return 0.5 - 0.5 * math.cos(math.pi * bounded)


def _lerp(start: float, end: float, progress: float) -> float:
    return start + (end - start) * progress


def _issue(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message, "severity": "error"}


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


def _positive_even_int(data: dict[str, object], key: str) -> int:
    raw = data.get(key)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(f"{key} must be an integer")
    if raw <= 0 or raw % 2:
        raise ValueError(f"{key} must be a positive even integer")
    return raw


def _positive_float(data: dict[str, object], key: str) -> float:
    raw = data.get(key)
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise ValueError(f"{key} must be a number")
    value = float(raw)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{key} must be positive")
    return value


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


def _point(value: object, key: str) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{key} must contain [x, y]")
    coordinates: list[float] = []
    for coordinate in value:
        if isinstance(coordinate, bool) or not isinstance(
            coordinate,
            int | float,
        ):
            raise ValueError(f"{key} coordinates must be numbers")
        number = float(coordinate)
        if not 0.0 <= number <= 1.0:
            raise ValueError(f"{key} coordinates must be between 0 and 1")
        coordinates.append(number)
    return coordinates[0], coordinates[1]
