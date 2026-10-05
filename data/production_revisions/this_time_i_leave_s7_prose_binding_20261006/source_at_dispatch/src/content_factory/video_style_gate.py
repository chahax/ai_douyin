"""Cross-shot visual-style consistency gate for images and accepted videos."""

from __future__ import annotations

import json
import math
import re
import shutil
import statistics
import subprocess
from dataclasses import asdict, dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps


MANIFEST_TEMPLATE = "video_style_gate/v1"
REPORT_TEMPLATE = "video_style_gate_report/v1"
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True, slots=True)
class StyleFingerprint:
    hue_histogram: tuple[float, ...]
    saturation_histogram: tuple[float, ...]
    value_histogram: tuple[float, ...]
    luma_mean: float
    luma_std: float
    saturation_mean: float
    edge_density: float
    edge_strength: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class StyleMedia:
    media_id: str
    path: Path
    region: tuple[float, float, float, float]
    control_report: Path | None


@dataclass(frozen=True, slots=True)
class StyleAcceptance:
    maximum_style_distance: float
    maximum_palette_distance: float
    maximum_edge_density_delta: float
    maximum_edge_strength_delta: float
    maximum_temporal_drift: float


@dataclass(frozen=True, slots=True)
class VideoStyleGateManifest:
    manifest_path: Path
    gate_id: str
    reference: StyleMedia
    candidates: tuple[StyleMedia, ...]
    sample_count: int
    fingerprint_size: int
    acceptance: StyleAcceptance

    @classmethod
    def load(cls, manifest_path: str | Path) -> "VideoStyleGateManifest":
        path = Path(manifest_path).resolve()
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("template") != MANIFEST_TEMPLATE:
            raise ValueError(f"template must be {MANIFEST_TEMPLATE}")
        gate_id = _safe_id(data, "id")
        reference = _media(
            path,
            _required_object(data, "reference"),
            "reference",
            require_control=False,
        )
        raw_candidates = data.get("candidates")
        if not isinstance(raw_candidates, list) or not raw_candidates:
            raise ValueError("candidates must be a non-empty array")
        candidates = tuple(
            _media(
                path,
                item,
                f"candidates[{index}]",
                require_control=True,
            )
            for index, item in enumerate(raw_candidates)
            if isinstance(item, dict)
        )
        if len(candidates) != len(raw_candidates):
            raise ValueError("each candidate must be an object")
        candidate_ids = [item.media_id for item in candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("candidate ids must be unique")

        raw_sampling = data.get("sampling", {})
        if not isinstance(raw_sampling, dict):
            raise ValueError("sampling must be an object")
        sample_count = _bounded_int(
            raw_sampling,
            "sample_count",
            default=5,
            minimum=1,
            maximum=9,
        )
        fingerprint_size = _bounded_int(
            raw_sampling,
            "fingerprint_size",
            default=128,
            minimum=64,
            maximum=256,
        )

        raw_acceptance = data.get("acceptance", {})
        if not isinstance(raw_acceptance, dict):
            raise ValueError("acceptance must be an object")
        acceptance = StyleAcceptance(
            maximum_style_distance=_bounded_float(
                raw_acceptance,
                "maximum_style_distance",
                default=0.2,
                minimum=0.01,
                maximum=1.0,
            ),
            maximum_palette_distance=_bounded_float(
                raw_acceptance,
                "maximum_palette_distance",
                default=0.28,
                minimum=0.01,
                maximum=1.0,
            ),
            maximum_edge_density_delta=_bounded_float(
                raw_acceptance,
                "maximum_edge_density_delta",
                default=0.12,
                minimum=0.01,
                maximum=1.0,
            ),
            maximum_edge_strength_delta=_bounded_float(
                raw_acceptance,
                "maximum_edge_strength_delta",
                default=0.035,
                minimum=0.005,
                maximum=1.0,
            ),
            maximum_temporal_drift=_bounded_float(
                raw_acceptance,
                "maximum_temporal_drift",
                default=0.1,
                minimum=0.0,
                maximum=1.0,
            ),
        )
        return cls(
            manifest_path=path,
            gate_id=gate_id,
            reference=reference,
            candidates=candidates,
            sample_count=sample_count,
            fingerprint_size=fingerprint_size,
            acceptance=acceptance,
        )

    def validate_assets(self) -> None:
        media = (self.reference, *self.candidates)
        missing = [item.path for item in media if not item.path.is_file()]
        missing.extend(
            item.control_report
            for item in self.candidates
            if item.control_report is not None
            and not item.control_report.is_file()
        )
        if missing:
            names = ", ".join(str(path) for path in missing)
            raise FileNotFoundError(f"style gate assets missing: {names}")


def run_video_style_gate(
    manifest_path: str | Path,
    *,
    report_path: str | Path | None = None,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
) -> dict[str, object]:
    manifest = VideoStyleGateManifest.load(manifest_path)
    manifest.validate_assets()
    reference_frames = _sample_media(
        manifest.reference,
        sample_count=manifest.sample_count,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
    )
    reference_fingerprints = [
        fingerprint_image(
            _crop_region(frame, manifest.reference.region),
            size=manifest.fingerprint_size,
        )
        for frame in reference_frames
    ]
    reference = aggregate_fingerprints(reference_fingerprints)

    results: list[dict[str, object]] = []
    failed_checks: set[str] = set()
    for candidate in manifest.candidates:
        control_issues = _control_blockers(candidate)
        if control_issues:
            failed_checks.update(control_issues)
            results.append(
                {
                    "id": candidate.media_id,
                    "path": str(candidate.path),
                    "status": "blocked",
                    "style_eligible": False,
                    "control_issues": control_issues,
                    "issues": [
                        _issue(
                            code,
                            "candidate video must pass its structural control "
                            "report before style comparison",
                        )
                        for code in control_issues
                    ],
                }
            )
            continue

        frames = _sample_media(
            candidate,
            sample_count=manifest.sample_count,
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
        )
        fingerprints = [
            fingerprint_image(
                _crop_region(frame, candidate.region),
                size=manifest.fingerprint_size,
            )
            for frame in frames
        ]
        aggregate = aggregate_fingerprints(fingerprints)
        reference_metrics = [
            compare_fingerprints(reference, fingerprint)
            for fingerprint in fingerprints
        ]
        aggregate_metrics = compare_fingerprints(reference, aggregate)
        temporal_metrics = [
            compare_fingerprints(aggregate, fingerprint)
            for fingerprint in fingerprints
        ]
        metrics = {
            "style_distance": round(
                statistics.median(
                    item["style_distance"] for item in reference_metrics
                ),
                6,
            ),
            "maximum_style_distance": round(
                max(item["style_distance"] for item in reference_metrics),
                6,
            ),
            "palette_distance": round(
                aggregate_metrics["palette_distance"],
                6,
            ),
            "edge_density_delta": round(
                aggregate_metrics["edge_density_delta"],
                6,
            ),
            "edge_strength_delta": round(
                aggregate_metrics["edge_strength_delta"],
                6,
            ),
            "temporal_style_drift": round(
                max(item["style_distance"] for item in temporal_metrics),
                6,
            ),
        }
        issues = _style_issues(metrics, manifest.acceptance)
        failed_checks.update(issue["code"] for issue in issues)
        results.append(
            {
                "id": candidate.media_id,
                "path": str(candidate.path),
                "status": "accepted" if not issues else "rejected",
                "style_eligible": not issues,
                "sample_count": len(frames),
                "region": list(candidate.region),
                "metrics": metrics,
                "aggregate_fingerprint": aggregate.to_dict(),
                "issues": issues,
            }
        )

    blocked = any(result["status"] == "blocked" for result in results)
    rejected = any(result["status"] == "rejected" for result in results)
    status = "blocked" if blocked else "rejected" if rejected else "accepted"
    report = {
        "template": REPORT_TEMPLATE,
        "id": manifest.gate_id,
        "status": status,
        "style_eligible": status == "accepted",
        "reference": {
            "path": str(manifest.reference.path),
            "region": list(manifest.reference.region),
            "sample_count": len(reference_frames),
            "aggregate_fingerprint": reference.to_dict(),
        },
        "acceptance": asdict(manifest.acceptance),
        "accepted_candidates": [
            result["id"]
            for result in results
            if result["status"] == "accepted"
        ],
        "rejected_candidates": [
            result["id"]
            for result in results
            if result["status"] != "accepted"
        ],
        "failed_checks": sorted(failed_checks),
        "candidates": results,
    }
    destination = (
        Path(report_path)
        if report_path is not None
        else manifest.manifest_path.with_suffix(".report.json")
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    report["report_path"] = str(destination)
    return report


def fingerprint_image(
    image: Image.Image,
    *,
    size: int = 128,
) -> StyleFingerprint:
    normalized = ImageOps.fit(
        image.convert("RGB"),
        (size, size),
        method=Image.Resampling.LANCZOS,
    )
    hsv = normalized.convert("HSV")
    hue, saturation, value = hsv.split()
    hue_pixels = list(hue.getdata())
    saturation_pixels = list(saturation.getdata())
    value_pixels = list(value.getdata())
    hue_histogram = [0.0] * 16
    for hue_value, saturation_value in zip(
        hue_pixels,
        saturation_pixels,
        strict=True,
    ):
        hue_histogram[min(15, hue_value * 16 // 256)] += (
            saturation_value / 255.0
        )
    saturation_histogram = _histogram(saturation_pixels, 8)
    value_histogram = _histogram(value_pixels, 8)
    grayscale = normalized.convert("L")
    grayscale_pixels = list(grayscale.getdata())
    edge_image = grayscale.filter(ImageFilter.FIND_EDGES)
    if size > 8:
        edge_image = edge_image.crop((2, 2, size - 2, size - 2))
    edge_pixels = list(edge_image.getdata())
    return StyleFingerprint(
        hue_histogram=tuple(_normalize(hue_histogram)),
        saturation_histogram=tuple(_normalize(saturation_histogram)),
        value_histogram=tuple(_normalize(value_histogram)),
        luma_mean=statistics.fmean(grayscale_pixels),
        luma_std=statistics.pstdev(grayscale_pixels),
        saturation_mean=statistics.fmean(saturation_pixels),
        edge_density=sum(value >= 32 for value in edge_pixels)
        / len(edge_pixels),
        edge_strength=statistics.fmean(edge_pixels) / 255.0,
    )


def aggregate_fingerprints(
    fingerprints: list[StyleFingerprint],
) -> StyleFingerprint:
    if not fingerprints:
        raise ValueError("at least one style fingerprint is required")
    return StyleFingerprint(
        hue_histogram=tuple(
            statistics.median(
                item.hue_histogram[index] for item in fingerprints
            )
            for index in range(16)
        ),
        saturation_histogram=tuple(
            statistics.median(
                item.saturation_histogram[index] for item in fingerprints
            )
            for index in range(8)
        ),
        value_histogram=tuple(
            statistics.median(
                item.value_histogram[index] for item in fingerprints
            )
            for index in range(8)
        ),
        luma_mean=statistics.median(
            item.luma_mean for item in fingerprints
        ),
        luma_std=statistics.median(item.luma_std for item in fingerprints),
        saturation_mean=statistics.median(
            item.saturation_mean for item in fingerprints
        ),
        edge_density=statistics.median(
            item.edge_density for item in fingerprints
        ),
        edge_strength=statistics.median(
            item.edge_strength for item in fingerprints
        ),
    )


def compare_fingerprints(
    reference: StyleFingerprint,
    candidate: StyleFingerprint,
) -> dict[str, float]:
    palette_distance = statistics.fmean(
        (
            _distribution_distance(
                reference.hue_histogram,
                candidate.hue_histogram,
            ),
            _distribution_distance(
                reference.saturation_histogram,
                candidate.saturation_histogram,
            ),
            _distribution_distance(
                reference.value_histogram,
                candidate.value_histogram,
            ),
        )
    )
    edge_density_delta = abs(
        reference.edge_density - candidate.edge_density
    )
    edge_strength_delta = abs(
        reference.edge_strength - candidate.edge_strength
    )
    luma_delta = abs(reference.luma_mean - candidate.luma_mean) / 255.0
    contrast_delta = abs(reference.luma_std - candidate.luma_std) / 128.0
    saturation_delta = abs(
        reference.saturation_mean - candidate.saturation_mean
    ) / 255.0
    style_distance = (
        palette_distance * 0.5
        + min(1.0, edge_density_delta / 0.25) * 0.15
        + min(1.0, edge_strength_delta / 0.25) * 0.1
        + luma_delta * 0.1
        + min(1.0, contrast_delta) * 0.1
        + saturation_delta * 0.05
    )
    return {
        "style_distance": style_distance,
        "palette_distance": palette_distance,
        "edge_density_delta": edge_density_delta,
        "edge_strength_delta": edge_strength_delta,
        "luma_delta": luma_delta,
        "contrast_delta": contrast_delta,
        "saturation_delta": saturation_delta,
    }


def _style_issues(
    metrics: dict[str, float],
    acceptance: StyleAcceptance,
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if metrics["maximum_style_distance"] > (
        acceptance.maximum_style_distance
    ):
        issues.append(
            _issue(
                "render_style_mismatch",
                f"maximum style distance "
                f"{metrics['maximum_style_distance']:.4f} exceeds "
                f"{acceptance.maximum_style_distance:.4f}",
            )
        )
    if metrics["palette_distance"] > (
        acceptance.maximum_palette_distance
    ):
        issues.append(
            _issue(
                "style_palette_mismatch",
                f"palette distance {metrics['palette_distance']:.4f} exceeds "
                f"{acceptance.maximum_palette_distance:.4f}",
            )
        )
    if (
        metrics["edge_density_delta"]
        > acceptance.maximum_edge_density_delta
        or metrics["edge_strength_delta"]
        > acceptance.maximum_edge_strength_delta
    ):
        issues.append(
            _issue(
                "style_lineart_mismatch",
                "edge signature differs: "
                f"density={metrics['edge_density_delta']:.4f}/"
                f"{acceptance.maximum_edge_density_delta:.4f}, "
                f"strength={metrics['edge_strength_delta']:.4f}/"
                f"{acceptance.maximum_edge_strength_delta:.4f}",
            )
        )
    if metrics["temporal_style_drift"] > (
        acceptance.maximum_temporal_drift
    ):
        issues.append(
            _issue(
                "temporal_style_drift",
                f"temporal style drift "
                f"{metrics['temporal_style_drift']:.4f} exceeds "
                f"{acceptance.maximum_temporal_drift:.4f}",
            )
        )
    return issues


def _sample_media(
    media: StyleMedia,
    *,
    sample_count: int,
    ffmpeg: str,
    ffprobe: str,
) -> list[Image.Image]:
    suffix = media.path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        with Image.open(media.path) as image:
            return [ImageOps.exif_transpose(image).convert("RGB").copy()]
    if suffix not in VIDEO_SUFFIXES:
        raise ValueError(f"unsupported style media: {media.path}")
    duration = _probe_duration(media.path, ffprobe=ffprobe)
    count = max(1, sample_count)
    times = (
        [duration / 2]
        if count == 1
        else [
            min(duration * 0.98, duration * index / (count - 1))
            for index in range(count)
        ]
    )
    executable = shutil.which(ffmpeg) or ffmpeg
    frames: list[Image.Image] = []
    for timestamp in times:
        completed = subprocess.run(
            [
                executable,
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{timestamp:.6f}",
                "-i",
                str(media.path),
                "-frames:v",
                "1",
                "-f",
                "image2pipe",
                "-vcodec",
                "png",
                "pipe:1",
            ],
            check=True,
            capture_output=True,
        )
        with Image.open(BytesIO(completed.stdout)) as image:
            frames.append(image.convert("RGB").copy())
    return frames


def _probe_duration(path: Path, *, ffprobe: str) -> float:
    executable = shutil.which(ffprobe) or ffprobe
    completed = subprocess.run(
        [
            executable,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    duration = float(completed.stdout.strip())
    if duration <= 0:
        raise ValueError(f"invalid video duration: {path}")
    return duration


def _control_blockers(media: StyleMedia) -> list[str]:
    if media.path.suffix.lower() not in VIDEO_SUFFIXES:
        return []
    if media.control_report is None:
        return ["style_control_report_missing"]
    data = json.loads(media.control_report.read_text(encoding="utf-8-sig"))
    blockers: list[str] = []
    raw_path = data.get("path")
    if not isinstance(raw_path, str) or (
        Path(raw_path).resolve() != media.path.resolve()
    ):
        blockers.append("style_control_report_video_mismatch")
    if data.get("passed") is not True:
        blockers.append("style_control_report_failed")
    return blockers


def _media(
    manifest_path: Path,
    value: dict[str, object],
    key: str,
    *,
    require_control: bool,
) -> StyleMedia:
    media_id = str(value.get("id", key)).strip()
    if not SAFE_ID.fullmatch(media_id):
        raise ValueError(f"{key}.id must use letters, numbers, underscores, or hyphens")
    path = _resolve_path(
        manifest_path,
        _required_string(value, "path", prefix=key),
    )
    suffix = path.suffix.lower()
    if suffix not in VIDEO_SUFFIXES | IMAGE_SUFFIXES:
        raise ValueError(f"{key}.path has unsupported media type: {suffix}")
    raw_control = value.get("control_report")
    control_report = (
        _resolve_path(manifest_path, raw_control)
        if isinstance(raw_control, str) and raw_control.strip()
        else None
    )
    if require_control and suffix in VIDEO_SUFFIXES and control_report is None:
        raise ValueError(f"{key}.control_report is required for video candidates")
    return StyleMedia(
        media_id=media_id,
        path=path,
        region=_region(value.get("region", [0.0, 0.0, 1.0, 1.0]), key),
        control_report=control_report,
    )


def _crop_region(
    image: Image.Image,
    region: tuple[float, float, float, float],
) -> Image.Image:
    left, top, width, height = region
    pixel_box = (
        round(left * image.width),
        round(top * image.height),
        round((left + width) * image.width),
        round((top + height) * image.height),
    )
    return image.crop(pixel_box)


def _histogram(values: list[int], bins: int) -> list[float]:
    histogram = [0.0] * bins
    for value in values:
        histogram[min(bins - 1, value * bins // 256)] += 1.0
    return _normalize(histogram)


def _normalize(values: list[float]) -> list[float]:
    total = sum(values)
    return (
        [value / total for value in values]
        if total > 0
        else [0.0 for _ in values]
    )


def _distribution_distance(
    first: tuple[float, ...],
    second: tuple[float, ...],
) -> float:
    return sum(
        abs(left - right)
        for left, right in zip(first, second, strict=True)
    ) / 2.0


def _region(
    value: object,
    key: str,
) -> tuple[float, float, float, float]:
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError(f"{key}.region must contain [x, y, width, height]")
    numbers: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int | float):
            raise ValueError(f"{key}.region values must be numbers")
        numbers.append(float(item))
    left, top, width, height = numbers
    if left < 0 or top < 0 or width <= 0 or height <= 0:
        raise ValueError(f"{key}.region must be positive and inside the image")
    if left + width > 1.0 or top + height > 1.0:
        raise ValueError(f"{key}.region must stay inside normalized image bounds")
    if width * height < 0.02:
        raise ValueError(f"{key}.region is too small for style analysis")
    return left, top, width, height


def _issue(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message, "severity": "error"}


def _safe_id(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise ValueError(f"{key} must use letters, numbers, underscores, or hyphens")
    return value


def _required_object(
    data: dict[str, object],
    key: str,
) -> dict[str, object]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object")
    return value


def _required_string(
    data: dict[str, object],
    key: str,
    *,
    prefix: str,
) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{prefix}.{key} is required")
    return value


def _resolve_path(manifest_path: Path, value: str) -> Path:
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
