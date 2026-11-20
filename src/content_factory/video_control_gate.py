"""AI video motion, lighting, and reference-lock acceptance gate."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from io import BytesIO
from pathlib import Path

from PIL import Image

from src.content_factory.video_control_policy import (
    VideoControlRecommendation,
    VideoShotIntent,
    recommend_video_control,
)


@dataclass(frozen=True, slots=True)
class VideoControlProfile:
    name: str
    sample_count: int
    max_luma_range: float
    max_chroma_range: float
    max_frame_distance: float | None = None
    max_anchor_distance: float | None = None
    max_active_pixel_ratio: float | None = None
    min_active_pixel_ratio: float | None = None
    require_regions: bool = False
    require_reference: bool = False


VIDEO_CONTROL_PROFILES: dict[str, VideoControlProfile] = {
    "free": VideoControlProfile(
        name="free",
        sample_count=9,
        max_luma_range=30.0,
        max_chroma_range=30.0,
    ),
    "micro_motion": VideoControlProfile(
        name="micro_motion",
        sample_count=9,
        max_luma_range=10.0,
        max_chroma_range=12.0,
        max_frame_distance=12.0,
        max_anchor_distance=22.0,
        max_active_pixel_ratio=0.35,
        min_active_pixel_ratio=0.001,
    ),
    "subject_only": VideoControlProfile(
        name="subject_only",
        sample_count=9,
        max_luma_range=8.0,
        max_chroma_range=10.0,
        min_active_pixel_ratio=0.001,
        require_regions=True,
    ),
    "pixel_locked": VideoControlProfile(
        name="pixel_locked",
        sample_count=9,
        max_luma_range=4.0,
        max_chroma_range=6.0,
        max_frame_distance=1.2,
        max_anchor_distance=1.5,
        max_active_pixel_ratio=0.02,
    ),
    "replacement_relight": VideoControlProfile(
        name="replacement_relight",
        sample_count=9,
        max_luma_range=8.0,
        max_chroma_range=10.0,
        min_active_pixel_ratio=0.001,
        require_regions=True,
        require_reference=True,
    ),
}


@dataclass(frozen=True, slots=True)
class ControlRegion:
    name: str
    rect: tuple[int, int, int, int]
    motion: str
    reference_lock: bool = False
    max_frame_distance: float | None = None
    max_anchor_distance: float | None = None
    max_active_pixel_ratio: float | None = None
    min_active_pixel_ratio: float | None = None

    @classmethod
    def from_dict(cls, name: str, data: dict[str, object]) -> "ControlRegion":
        rect = data.get("rect")
        if not isinstance(rect, list) or len(rect) != 4:
            raise ValueError(f"{name}.rect must contain [x, y, width, height]")
        values = tuple(int(value) for value in rect)
        if values[2] <= 0 or values[3] <= 0:
            raise ValueError(f"{name}.rect width and height must be positive")
        motion = str(data.get("motion") or "").strip().lower()
        if motion not in {"static", "dynamic"}:
            raise ValueError(f"{name}.motion must be static or dynamic")
        return cls(
            name=name,
            rect=values,
            motion=motion,
            reference_lock=bool(data.get("reference_lock", False)),
            max_frame_distance=_optional_non_negative(
                data,
                "max_frame_distance",
                name,
            ),
            max_anchor_distance=_optional_non_negative(
                data,
                "max_anchor_distance",
                name,
            ),
            max_active_pixel_ratio=_optional_non_negative(
                data,
                "max_active_pixel_ratio",
                name,
            ),
            min_active_pixel_ratio=_optional_non_negative(
                data,
                "min_active_pixel_ratio",
                name,
            ),
        )


@dataclass(frozen=True, slots=True)
class VideoControlIssue:
    code: str
    message: str
    severity: str = "error"


@dataclass(slots=True)
class VideoControlReport:
    path: str
    mode: str
    metadata: dict[str, object] = field(default_factory=dict)
    issues: list[VideoControlIssue] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def add_issue(self, code: str, message: str, severity: str = "error") -> None:
        self.issues.append(VideoControlIssue(code=code, message=message, severity=severity))

    def write_json(self, output_path: str | Path) -> None:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                {
                    "path": self.path,
                    "mode": self.mode,
                    "passed": self.passed,
                    "metadata": self.metadata,
                    "issues": [asdict(issue) for issue in self.issues],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


@dataclass(frozen=True, slots=True)
class VideoControlManifest:
    video_path: Path
    mode: str
    reference_image: Path | None
    regions: tuple[ControlRegion, ...]
    intent: VideoShotIntent | None = None
    recommendation: VideoControlRecommendation | None = None

    @classmethod
    def load(cls, manifest_path: str | Path) -> "VideoControlManifest":
        path = Path(manifest_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("template") != "video_control/v1":
            raise ValueError("template must be video_control/v1")
        raw_intent = data.get("intent")
        intent = VideoShotIntent.from_dict(raw_intent) if raw_intent is not None else None
        recommendation = recommend_video_control(intent) if intent is not None else None
        mode = str(data.get("mode") or (recommendation.mode if recommendation else "")).strip().lower()
        resolve_control_profile(mode)
        if recommendation is not None and mode != recommendation.mode:
            raise ValueError(
                f"mode {mode} conflicts with intent recommendation {recommendation.mode}"
            )
        raw_video_path = data.get("video_path")
        if not isinstance(raw_video_path, str) or not raw_video_path.strip():
            raise ValueError("video_path is required")
        video_path = _resolve_manifest_path(path, raw_video_path)
        raw_reference = data.get("reference_image")
        reference_image = (
            _resolve_manifest_path(path, raw_reference)
            if isinstance(raw_reference, str) and raw_reference.strip()
            else None
        )
        raw_regions = data.get("regions") or {}
        if not isinstance(raw_regions, dict):
            raise ValueError("regions must be an object")
        regions = tuple(
            ControlRegion.from_dict(name, region)
            for name, region in raw_regions.items()
            if isinstance(region, dict)
        )
        if len(regions) != len(raw_regions):
            raise ValueError("each region must be an object")
        return cls(
            video_path=video_path,
            mode=mode,
            reference_image=reference_image,
            regions=regions,
            intent=intent,
            recommendation=recommendation,
        )


def available_control_profiles() -> tuple[str, ...]:
    return tuple(VIDEO_CONTROL_PROFILES)


def resolve_control_profile(profile: str | VideoControlProfile) -> VideoControlProfile:
    if isinstance(profile, VideoControlProfile):
        return profile
    profile_name = profile.strip().lower()
    try:
        return VIDEO_CONTROL_PROFILES[profile_name]
    except KeyError as exc:
        choices = ", ".join(available_control_profiles())
        raise ValueError(f"unknown video control mode: {profile_name}; choose from {choices}") from exc


class VideoControlGate:
    def inspect(
        self,
        video_path: str | Path,
        mode: str | VideoControlProfile,
        *,
        regions: tuple[ControlRegion, ...] = (),
        reference_image: str | Path | None = None,
    ) -> VideoControlReport:
        path = Path(video_path)
        profile = resolve_control_profile(mode)
        report = VideoControlReport(path=str(path), mode=profile.name)
        if not path.is_file():
            report.add_issue("file_missing", f"video file does not exist: {path}")
            return report
        if profile.require_regions and not regions:
            report.add_issue("regions_required", f"{profile.name} requires declared static/dynamic regions")
        if profile.require_reference and reference_image is None:
            report.add_issue("reference_required", f"{profile.name} requires a reference image")

        try:
            probe = self._probe(path)
            duration = _probe_duration(probe)
            samples = self._sample_frames(path, duration, profile.sample_count)
        except (OSError, ValueError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            report.add_issue("scan_failed", f"unable to scan video: {exc}")
            return report

        report.metadata.update(
            {
                "duration": round(duration, 3),
                "sample_count": len(samples),
                "width": samples[0][1].width,
                "height": samples[0][1].height,
                **_video_stream_metadata(probe),
            }
        )
        reference = self._load_reference(reference_image, samples[0][1].size, report)
        self.evaluate_samples(report, profile, samples, regions=regions, reference=reference)
        return report

    def inspect_manifest(
        self,
        manifest_path: str | Path,
        output_path: str | Path | None = None,
    ) -> VideoControlReport:
        manifest = VideoControlManifest.load(manifest_path)
        report = self.inspect(
            manifest.video_path,
            manifest.mode,
            regions=manifest.regions,
            reference_image=manifest.reference_image,
        )
        if manifest.intent is not None and manifest.recommendation is not None:
            report.metadata["intent"] = manifest.intent.to_dict()
            report.metadata["recommendation"] = manifest.recommendation.to_dict()
        report.write_json(output_path or manifest.video_path.with_suffix(".control.json"))
        return report

    @staticmethod
    def evaluate_samples(
        report: VideoControlReport,
        profile: VideoControlProfile,
        samples: list[tuple[float, Image.Image]],
        *,
        regions: tuple[ControlRegion, ...] = (),
        reference: Image.Image | None = None,
    ) -> None:
        if len(samples) < 2:
            report.add_issue("samples_insufficient", "at least two frames are required")
            return

        frames = [image.convert("RGB") for _, image in samples]
        luma_values = [_mean_luma(image) for image in frames]
        chroma_values = [_mean_chroma(image) for image in frames]
        consecutive = [_frame_difference(frames[index - 1], frames[index]) for index in range(1, len(frames))]
        anchor = [_frame_difference(frames[0], image) for image in frames[1:]]
        metrics = {
            "luma_min": round(min(luma_values), 3),
            "luma_max": round(max(luma_values), 3),
            "luma_range": round(max(luma_values) - min(luma_values), 3),
            "chroma_range": round(max(chroma_values) - min(chroma_values), 3),
            "max_frame_distance": round(max((value[0] for value in consecutive), default=0.0), 3),
            "max_anchor_distance": round(max((value[0] for value in anchor), default=0.0), 3),
            "max_active_pixel_ratio": round(max((value[1] for value in consecutive), default=0.0), 4),
        }
        report.metadata["temporal"] = metrics

        if metrics["luma_range"] > profile.max_luma_range:
            report.add_issue(
                "lighting_flicker",
                f"luma range {metrics['luma_range']:.3f} exceeds {profile.max_luma_range:.3f}",
            )
        if metrics["chroma_range"] > profile.max_chroma_range:
            report.add_issue(
                "color_flicker",
                f"chroma range {metrics['chroma_range']:.3f} exceeds {profile.max_chroma_range:.3f}",
            )
        if profile.max_frame_distance is not None and metrics["max_frame_distance"] > profile.max_frame_distance:
            report.add_issue(
                "motion_too_large",
                f"frame distance {metrics['max_frame_distance']:.3f} exceeds {profile.max_frame_distance:.3f}",
            )
        if profile.max_anchor_distance is not None and metrics["max_anchor_distance"] > profile.max_anchor_distance:
            report.add_issue(
                "anchor_drift",
                f"anchor distance {metrics['max_anchor_distance']:.3f} exceeds {profile.max_anchor_distance:.3f}",
            )
        if (
            profile.max_active_pixel_ratio is not None
            and metrics["max_active_pixel_ratio"] > profile.max_active_pixel_ratio
        ):
            report.add_issue(
                "active_area_too_large",
                f"active pixel ratio {metrics['max_active_pixel_ratio']:.4f} exceeds "
                f"{profile.max_active_pixel_ratio:.4f}",
            )
        if (
            profile.min_active_pixel_ratio is not None
            and metrics["max_active_pixel_ratio"] < profile.min_active_pixel_ratio
        ):
            report.add_issue(
                "motion_missing",
                f"active pixel ratio {metrics['max_active_pixel_ratio']:.4f} is below "
                f"{profile.min_active_pixel_ratio:.4f}",
            )

        region_metrics: dict[str, object] = {}
        for region in regions:
            region_report = _evaluate_region(frames, region, reference)
            region_metrics[region.name] = region_report
            if region.motion == "static":
                if (
                    region_report["max_frame_distance"] > 1.5
                    or region_report["max_anchor_distance"] > 1.8
                    or region_report["max_active_pixel_ratio"] > 0.03
                ):
                    report.add_issue(
                        "static_region_changed",
                        f"{region.name} changed: frame={region_report['max_frame_distance']:.3f}, "
                        f"anchor={region_report['max_anchor_distance']:.3f}, "
                        f"active={region_report['max_active_pixel_ratio']:.4f}",
                    )
            elif (
                region_report["max_frame_distance"] < 1.2
                and region_report["max_active_pixel_ratio"]
                < (
                    region.min_active_pixel_ratio
                    if region.min_active_pixel_ratio is not None
                    else 0.002
                )
            ):
                report.add_issue(
                    "dynamic_region_static",
                    f"{region.name} has no visible motion",
                )
            if (
                region.motion == "dynamic"
                and region.max_frame_distance is not None
                and region_report["max_frame_distance"] > region.max_frame_distance
            ):
                report.add_issue(
                    "region_motion_too_large",
                    f"{region.name} frame distance "
                    f"{region_report['max_frame_distance']:.3f} exceeds "
                    f"{region.max_frame_distance:.3f}",
                )
            if (
                region.motion == "dynamic"
                and region.max_anchor_distance is not None
                and region_report["max_anchor_distance"] > region.max_anchor_distance
            ):
                report.add_issue(
                    "region_anchor_drift",
                    f"{region.name} anchor distance "
                    f"{region_report['max_anchor_distance']:.3f} exceeds "
                    f"{region.max_anchor_distance:.3f}",
                )
            if (
                region.motion == "dynamic"
                and region.max_active_pixel_ratio is not None
                and region_report["max_active_pixel_ratio"] > region.max_active_pixel_ratio
            ):
                report.add_issue(
                    "region_active_area_too_large",
                    f"{region.name} active pixel ratio "
                    f"{region_report['max_active_pixel_ratio']:.4f} exceeds "
                    f"{region.max_active_pixel_ratio:.4f}",
                )
            if region.reference_lock:
                if reference is None:
                    report.add_issue("reference_missing", f"{region.name} requires a reference image")
                elif region_report["max_reference_distance"] > 4.0:
                    report.add_issue(
                        "reference_lock_failed",
                        f"{region.name} reference distance "
                        f"{region_report['max_reference_distance']:.3f} exceeds 4.000",
                    )
        report.metadata["regions"] = region_metrics

    @staticmethod
    def _probe(path: Path) -> dict[str, object]:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            timeout=20,
        )
        return json.loads(result.stdout)

    @staticmethod
    def _sample_frames(
        path: Path,
        duration: float,
        sample_count: int,
    ) -> list[tuple[float, Image.Image]]:
        if duration <= 0:
            raise ValueError("video duration must be positive")
        start_margin = min(0.03, duration / 10)
        end_margin = min(max(0.1, duration * 0.02), duration / 3)
        usable_duration = max(0.0, duration - start_margin - end_margin)
        timestamps = [
            start_margin + usable_duration * index / max(1, sample_count - 1)
            for index in range(sample_count)
        ]
        samples: list[tuple[float, Image.Image]] = []
        for timestamp in timestamps:
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-ss",
                    f"{timestamp:.4f}",
                    "-i",
                    str(path),
                    "-frames:v",
                    "1",
                    "-f",
                    "image2pipe",
                    "-vcodec",
                    "png",
                    "-",
                ],
                capture_output=True,
                check=True,
                timeout=30,
            )
            if not result.stdout:
                raise ValueError(f"unable to extract frame at {timestamp:.4f}s")
            with Image.open(BytesIO(result.stdout)) as image:
                samples.append((timestamp, image.convert("RGB").copy()))
        return samples

    @staticmethod
    def _load_reference(
        reference_image: str | Path | None,
        size: tuple[int, int],
        report: VideoControlReport,
    ) -> Image.Image | None:
        if reference_image is None:
            return None
        path = Path(reference_image)
        if not path.is_file():
            report.add_issue("reference_missing", f"reference image does not exist: {path}")
            return None
        with Image.open(path) as image:
            return image.convert("RGB").resize(size, Image.Resampling.LANCZOS)


def _resolve_manifest_path(manifest_path: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else manifest_path.parent / path


def _optional_non_negative(
    data: dict[str, object],
    key: str,
    region_name: str,
) -> float | None:
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{region_name}.{key} must be a non-negative number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{region_name}.{key} must be a non-negative number"
        ) from exc
    if number < 0:
        raise ValueError(f"{region_name}.{key} must be a non-negative number")
    return number


def _probe_duration(probe: dict[str, object]) -> float:
    format_info = probe.get("format")
    if isinstance(format_info, dict):
        try:
            duration = float(str(format_info.get("duration") or 0))
        except (TypeError, ValueError):
            duration = 0.0
        if duration > 0:
            return duration
    raise ValueError("ffprobe did not return a positive duration")


def _video_stream_metadata(probe: dict[str, object]) -> dict[str, object]:
    raw_streams = probe.get("streams")
    streams = raw_streams if isinstance(raw_streams, list) else []
    stream = next(
        (
            item
            for item in streams
            if isinstance(item, dict) and item.get("codec_type") == "video"
        ),
        None,
    )
    if stream is None:
        return {}
    metadata: dict[str, object] = {}
    fps = _parse_frame_rate(stream.get("avg_frame_rate"))
    if fps is not None:
        metadata["fps"] = round(fps, 3)
    frame_count = stream.get("nb_frames")
    if isinstance(frame_count, str) and frame_count.isdigit():
        metadata["frame_count"] = int(frame_count)
    codec = stream.get("codec_name")
    if isinstance(codec, str) and codec:
        metadata["codec"] = codec
    pixel_format = stream.get("pix_fmt")
    if isinstance(pixel_format, str) and pixel_format:
        metadata["pixel_format"] = pixel_format
    return metadata


def _parse_frame_rate(value: object) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    numerator_text, separator, denominator_text = value.partition("/")
    try:
        numerator = float(numerator_text)
        denominator = float(denominator_text) if separator else 1.0
    except ValueError:
        return None
    if denominator <= 0:
        return None
    return numerator / denominator


def _mean_luma(image: Image.Image) -> float:
    pixels = list(image.resize((96, 96)).convert("RGB").getdata())
    return sum(0.2126 * red + 0.7152 * green + 0.0722 * blue for red, green, blue in pixels) / len(pixels)


def _mean_chroma(image: Image.Image) -> float:
    pixels = list(image.resize((96, 96)).convert("RGB").getdata())
    return sum(max(pixel) - min(pixel) for pixel in pixels) / len(pixels)


def _frame_difference(left: Image.Image, right: Image.Image) -> tuple[float, float]:
    left_pixels = list(left.resize((96, 96)).convert("RGB").getdata())
    right_pixels = list(right.resize((96, 96)).convert("RGB").getdata())
    differences = [
        abs(left_red - right_red) + abs(left_green - right_green) + abs(left_blue - right_blue)
        for (left_red, left_green, left_blue), (right_red, right_green, right_blue) in zip(
            left_pixels,
            right_pixels,
        )
    ]
    mean_distance = sum(differences) / (len(differences) * 3) if differences else 0.0
    active_ratio = sum(difference >= 36 for difference in differences) / len(differences) if differences else 0.0
    return mean_distance, active_ratio


def _evaluate_region(
    frames: list[Image.Image],
    region: ControlRegion,
    reference: Image.Image | None,
) -> dict[str, float]:
    x, y, width, height = region.rect
    crops = [frame.crop((x, y, x + width, y + height)) for frame in frames]
    consecutive = [_frame_difference(crops[index - 1], crops[index]) for index in range(1, len(crops))]
    anchor = [_frame_difference(crops[0], crop) for crop in crops[1:]]
    reference_distances = (
        [_frame_difference(reference.crop((x, y, x + width, y + height)), crop)[0] for crop in crops]
        if reference is not None
        else []
    )
    return {
        "max_frame_distance": round(max((value[0] for value in consecutive), default=0.0), 3),
        "max_anchor_distance": round(max((value[0] for value in anchor), default=0.0), 3),
        "max_active_pixel_ratio": round(max((value[1] for value in consecutive), default=0.0), 4),
        "max_reference_distance": round(max(reference_distances, default=0.0), 3),
    }
