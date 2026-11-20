"""Reference-based lighting consistency gate for images and accepted videos."""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps, ImageStat

from src.content_factory.video_style_gate import (
    StyleMedia,
    VIDEO_SUFFIXES,
    _bounded_float,
    _bounded_int,
    _crop_region,
    _issue,
    _media,
    _required_object,
    _safe_id,
    _sample_media,
)


MANIFEST_TEMPLATE = "video_lighting_gate/v1"
REPORT_TEMPLATE = "video_lighting_gate_report/v1"


@dataclass(frozen=True, slots=True)
class LightingFingerprint:
    luma_mean: float
    luma_std: float
    warm_cool_index: float
    green_magenta_index: float
    highlight_ratio: float
    shadow_ratio: float
    horizontal_gradient: float
    vertical_gradient: float
    gradient_strength: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class LightingAcceptance:
    maximum_exposure_ev_delta: float
    maximum_temperature_delta: float
    maximum_tint_delta: float
    maximum_contrast_delta: float
    maximum_highlight_ratio_delta: float
    maximum_shadow_ratio_delta: float
    maximum_direction_angle_degrees: float
    maximum_direction_strength_delta: float
    minimum_reference_direction_strength: float
    maximum_temporal_exposure_range_ev: float
    maximum_temporal_color_range: float
    maximum_temporal_direction_range_degrees: float


@dataclass(frozen=True, slots=True)
class VideoLightingGateManifest:
    manifest_path: Path
    gate_id: str
    reference: StyleMedia
    candidates: tuple[StyleMedia, ...]
    sample_count: int
    fingerprint_size: int
    acceptance: LightingAcceptance

    @classmethod
    def load(cls, manifest_path: str | Path) -> "VideoLightingGateManifest":
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
            default=7,
            minimum=1,
            maximum=13,
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
        acceptance = LightingAcceptance(
            maximum_exposure_ev_delta=_bounded_float(
                raw_acceptance,
                "maximum_exposure_ev_delta",
                default=0.35,
                minimum=0.01,
                maximum=4.0,
            ),
            maximum_temperature_delta=_bounded_float(
                raw_acceptance,
                "maximum_temperature_delta",
                default=0.08,
                minimum=0.005,
                maximum=1.0,
            ),
            maximum_tint_delta=_bounded_float(
                raw_acceptance,
                "maximum_tint_delta",
                default=0.06,
                minimum=0.005,
                maximum=1.0,
            ),
            maximum_contrast_delta=_bounded_float(
                raw_acceptance,
                "maximum_contrast_delta",
                default=0.15,
                minimum=0.005,
                maximum=1.0,
            ),
            maximum_highlight_ratio_delta=_bounded_float(
                raw_acceptance,
                "maximum_highlight_ratio_delta",
                default=0.12,
                minimum=0.005,
                maximum=1.0,
            ),
            maximum_shadow_ratio_delta=_bounded_float(
                raw_acceptance,
                "maximum_shadow_ratio_delta",
                default=0.12,
                minimum=0.005,
                maximum=1.0,
            ),
            maximum_direction_angle_degrees=_bounded_float(
                raw_acceptance,
                "maximum_direction_angle_degrees",
                default=45.0,
                minimum=1.0,
                maximum=180.0,
            ),
            maximum_direction_strength_delta=_bounded_float(
                raw_acceptance,
                "maximum_direction_strength_delta",
                default=0.06,
                minimum=0.005,
                maximum=1.0,
            ),
            minimum_reference_direction_strength=_bounded_float(
                raw_acceptance,
                "minimum_reference_direction_strength",
                default=0.015,
                minimum=0.0,
                maximum=1.0,
            ),
            maximum_temporal_exposure_range_ev=_bounded_float(
                raw_acceptance,
                "maximum_temporal_exposure_range_ev",
                default=0.25,
                minimum=0.0,
                maximum=4.0,
            ),
            maximum_temporal_color_range=_bounded_float(
                raw_acceptance,
                "maximum_temporal_color_range",
                default=0.06,
                minimum=0.0,
                maximum=1.0,
            ),
            maximum_temporal_direction_range_degrees=_bounded_float(
                raw_acceptance,
                "maximum_temporal_direction_range_degrees",
                default=45.0,
                minimum=0.0,
                maximum=180.0,
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
            raise FileNotFoundError(f"lighting gate assets missing: {names}")


def run_video_lighting_gate(
    manifest_path: str | Path,
    *,
    report_path: str | Path | None = None,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
) -> dict[str, object]:
    manifest = VideoLightingGateManifest.load(manifest_path)
    manifest.validate_assets()
    reference_frames = _sample_media(
        manifest.reference,
        sample_count=manifest.sample_count,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
    )
    reference_fingerprints = [
        fingerprint_lighting(
            _crop_region(frame, manifest.reference.region),
            size=manifest.fingerprint_size,
        )
        for frame in reference_frames
    ]
    reference = aggregate_lighting_fingerprints(reference_fingerprints)

    results: list[dict[str, object]] = []
    failed_checks: set[str] = set()
    for candidate in manifest.candidates:
        control_issues = _lighting_control_blockers(candidate)
        if control_issues:
            failed_checks.update(control_issues)
            results.append(
                {
                    "id": candidate.media_id,
                    "path": str(candidate.path),
                    "status": "blocked",
                    "lighting_eligible": False,
                    "control_issues": control_issues,
                    "issues": [
                        _issue(
                            code,
                            "candidate video must pass its structural control "
                            "report before lighting comparison",
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
            fingerprint_lighting(
                _crop_region(frame, candidate.region),
                size=manifest.fingerprint_size,
            )
            for frame in frames
        ]
        aggregate = aggregate_lighting_fingerprints(fingerprints)
        metrics = summarize_lighting_metrics(
            reference,
            aggregate,
            fingerprints,
        )
        issues = lighting_issues(metrics, manifest.acceptance)
        failed_checks.update(issue["code"] for issue in issues)
        results.append(
            {
                "id": candidate.media_id,
                "path": str(candidate.path),
                "status": "accepted" if not issues else "rejected",
                "lighting_eligible": not issues,
                "sample_count": len(frames),
                "region": list(candidate.region),
                "metrics": {
                    key: round(value, 6)
                    for key, value in metrics.items()
                },
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
        "lighting_eligible": status == "accepted",
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


def fingerprint_lighting(
    image: Image.Image,
    *,
    size: int = 128,
) -> LightingFingerprint:
    normalized = ImageOps.fit(
        image.convert("RGB"),
        (size, size),
        method=Image.Resampling.LANCZOS,
    )
    rgb_pixels = list(normalized.getdata())
    grayscale = normalized.convert("L")
    luma_pixels = list(grayscale.getdata())
    smooth = grayscale.filter(ImageFilter.GaussianBlur(radius=max(2, size / 16)))
    strip = max(1, round(size * 0.4))
    far_start = size - strip
    left_luma = ImageStat.Stat(smooth.crop((0, 0, strip, size))).mean[0]
    right_luma = ImageStat.Stat(
        smooth.crop((far_start, 0, size, size))
    ).mean[0]
    top_luma = ImageStat.Stat(smooth.crop((0, 0, size, strip))).mean[0]
    bottom_luma = ImageStat.Stat(
        smooth.crop((0, far_start, size, size))
    ).mean[0]
    horizontal_gradient = (right_luma - left_luma) / 255.0
    vertical_gradient = (bottom_luma - top_luma) / 255.0
    return LightingFingerprint(
        luma_mean=statistics.fmean(luma_pixels),
        luma_std=statistics.pstdev(luma_pixels),
        warm_cool_index=statistics.fmean(
            (red - blue) / 255.0 for red, _, blue in rgb_pixels
        ),
        green_magenta_index=statistics.fmean(
            (2 * green - red - blue) / 510.0
            for red, green, blue in rgb_pixels
        ),
        highlight_ratio=sum(value >= 217 for value in luma_pixels)
        / len(luma_pixels),
        shadow_ratio=sum(value <= 38 for value in luma_pixels)
        / len(luma_pixels),
        horizontal_gradient=horizontal_gradient,
        vertical_gradient=vertical_gradient,
        gradient_strength=math.hypot(
            horizontal_gradient,
            vertical_gradient,
        ),
    )


def aggregate_lighting_fingerprints(
    fingerprints: list[LightingFingerprint],
) -> LightingFingerprint:
    if not fingerprints:
        raise ValueError("at least one lighting fingerprint is required")
    return LightingFingerprint(
        **{
            field: statistics.median(
                getattr(fingerprint, field) for fingerprint in fingerprints
            )
            for field in LightingFingerprint.__dataclass_fields__
        }
    )


def compare_lighting(
    reference: LightingFingerprint,
    candidate: LightingFingerprint,
) -> dict[str, float]:
    return {
        "exposure_ev_delta": abs(
            _exposure_ev(candidate.luma_mean)
            - _exposure_ev(reference.luma_mean)
        ),
        "temperature_delta": abs(
            candidate.warm_cool_index - reference.warm_cool_index
        ),
        "tint_delta": abs(
            candidate.green_magenta_index
            - reference.green_magenta_index
        ),
        "contrast_delta": abs(
            candidate.luma_std - reference.luma_std
        )
        / 128.0,
        "highlight_ratio_delta": abs(
            candidate.highlight_ratio - reference.highlight_ratio
        ),
        "shadow_ratio_delta": abs(
            candidate.shadow_ratio - reference.shadow_ratio
        ),
        "direction_angle_degrees": _direction_angle(
            reference,
            candidate,
        ),
        "direction_strength_delta": abs(
            candidate.gradient_strength - reference.gradient_strength
        ),
    }


def summarize_lighting_metrics(
    reference: LightingFingerprint,
    aggregate: LightingFingerprint,
    fingerprints: list[LightingFingerprint],
) -> dict[str, float]:
    comparisons = [
        compare_lighting(reference, fingerprint)
        for fingerprint in fingerprints
    ]
    aggregate_comparison = compare_lighting(reference, aggregate)
    exposure_values = [
        _exposure_ev(fingerprint.luma_mean)
        for fingerprint in fingerprints
    ]
    temperature_values = [
        fingerprint.warm_cool_index for fingerprint in fingerprints
    ]
    tint_values = [
        fingerprint.green_magenta_index for fingerprint in fingerprints
    ]
    direction_angles = [
        _direction_angle(aggregate, fingerprint)
        for fingerprint in fingerprints
    ]
    return {
        "exposure_ev_delta": statistics.median(
            item["exposure_ev_delta"] for item in comparisons
        ),
        "maximum_exposure_ev_delta": max(
            item["exposure_ev_delta"] for item in comparisons
        ),
        "temperature_delta": aggregate_comparison["temperature_delta"],
        "maximum_temperature_delta": max(
            item["temperature_delta"] for item in comparisons
        ),
        "tint_delta": aggregate_comparison["tint_delta"],
        "maximum_tint_delta": max(
            item["tint_delta"] for item in comparisons
        ),
        "contrast_delta": aggregate_comparison["contrast_delta"],
        "highlight_ratio_delta": aggregate_comparison[
            "highlight_ratio_delta"
        ],
        "shadow_ratio_delta": aggregate_comparison["shadow_ratio_delta"],
        "direction_angle_degrees": aggregate_comparison[
            "direction_angle_degrees"
        ],
        "maximum_direction_angle_degrees": max(
            item["direction_angle_degrees"] for item in comparisons
        ),
        "direction_strength_delta": aggregate_comparison[
            "direction_strength_delta"
        ],
        "temporal_exposure_range_ev": _range(exposure_values),
        "temporal_temperature_range": _range(temperature_values),
        "temporal_tint_range": _range(tint_values),
        "temporal_direction_range_degrees": max(direction_angles),
        "reference_direction_strength": reference.gradient_strength,
        "candidate_direction_strength": aggregate.gradient_strength,
    }


def lighting_issues(
    metrics: dict[str, float],
    acceptance: LightingAcceptance,
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if (
        metrics["maximum_exposure_ev_delta"]
        > acceptance.maximum_exposure_ev_delta
    ):
        issues.append(
            _issue(
                "lighting_exposure_mismatch",
                "maximum exposure delta "
                f"{metrics['maximum_exposure_ev_delta']:.3f} EV exceeds "
                f"{acceptance.maximum_exposure_ev_delta:.3f} EV",
            )
        )
    if (
        metrics["maximum_temperature_delta"]
        > acceptance.maximum_temperature_delta
        or metrics["maximum_tint_delta"] > acceptance.maximum_tint_delta
    ):
        issues.append(
            _issue(
                "lighting_color_cast_mismatch",
                "lighting color differs: "
                f"temperature={metrics['maximum_temperature_delta']:.4f}/"
                f"{acceptance.maximum_temperature_delta:.4f}, "
                f"tint={metrics['maximum_tint_delta']:.4f}/"
                f"{acceptance.maximum_tint_delta:.4f}",
            )
        )
    if (
        metrics["contrast_delta"] > acceptance.maximum_contrast_delta
        or metrics["highlight_ratio_delta"]
        > acceptance.maximum_highlight_ratio_delta
        or metrics["shadow_ratio_delta"]
        > acceptance.maximum_shadow_ratio_delta
    ):
        issues.append(
            _issue(
                "lighting_contrast_mismatch",
                "contrast envelope differs: "
                f"contrast={metrics['contrast_delta']:.4f}/"
                f"{acceptance.maximum_contrast_delta:.4f}, "
                f"highlight={metrics['highlight_ratio_delta']:.4f}/"
                f"{acceptance.maximum_highlight_ratio_delta:.4f}, "
                f"shadow={metrics['shadow_ratio_delta']:.4f}/"
                f"{acceptance.maximum_shadow_ratio_delta:.4f}",
            )
        )
    direction_is_defined = (
        metrics["reference_direction_strength"]
        >= acceptance.minimum_reference_direction_strength
    )
    if direction_is_defined and (
        metrics["maximum_direction_angle_degrees"]
        > acceptance.maximum_direction_angle_degrees
        or metrics["direction_strength_delta"]
        > acceptance.maximum_direction_strength_delta
    ):
        issues.append(
            _issue(
                "light_direction_mismatch",
                "low-frequency light direction differs: "
                f"angle={metrics['maximum_direction_angle_degrees']:.2f}/"
                f"{acceptance.maximum_direction_angle_degrees:.2f} degrees, "
                f"strength={metrics['direction_strength_delta']:.4f}/"
                f"{acceptance.maximum_direction_strength_delta:.4f}",
            )
        )
    if (
        metrics["temporal_exposure_range_ev"]
        > acceptance.maximum_temporal_exposure_range_ev
        or max(
            metrics["temporal_temperature_range"],
            metrics["temporal_tint_range"],
        )
        > acceptance.maximum_temporal_color_range
        or metrics["temporal_direction_range_degrees"]
        > acceptance.maximum_temporal_direction_range_degrees
    ):
        issues.append(
            _issue(
                "lighting_temporal_drift",
                "lighting changes across sampled frames: "
                f"exposure={metrics['temporal_exposure_range_ev']:.3f}/"
                f"{acceptance.maximum_temporal_exposure_range_ev:.3f} EV, "
                f"color={max(metrics['temporal_temperature_range'], metrics['temporal_tint_range']):.4f}/"
                f"{acceptance.maximum_temporal_color_range:.4f}, "
                f"direction={metrics['temporal_direction_range_degrees']:.2f}/"
                f"{acceptance.maximum_temporal_direction_range_degrees:.2f}",
            )
        )
    return issues


def _direction_angle(
    reference: LightingFingerprint,
    candidate: LightingFingerprint,
) -> float:
    if reference.gradient_strength < 1e-8 or candidate.gradient_strength < 1e-8:
        return 0.0
    cosine = (
        reference.horizontal_gradient * candidate.horizontal_gradient
        + reference.vertical_gradient * candidate.vertical_gradient
    ) / (reference.gradient_strength * candidate.gradient_strength)
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def _exposure_ev(luma_mean: float) -> float:
    return math.log2((luma_mean + 1.0) / 256.0)


def _range(values: list[float]) -> float:
    return max(values) - min(values) if values else 0.0


def _lighting_control_blockers(media: StyleMedia) -> list[str]:
    if media.path.suffix.lower() not in VIDEO_SUFFIXES:
        return []
    if media.control_report is None:
        return ["lighting_control_report_missing"]
    data = json.loads(
        media.control_report.read_text(encoding="utf-8-sig")
    )
    blockers: list[str] = []
    raw_path = data.get("path")
    if not isinstance(raw_path, str) or (
        Path(raw_path).resolve() != media.path.resolve()
    ):
        blockers.append("lighting_control_report_video_mismatch")
    if data.get("passed") is not True:
        blockers.append("lighting_control_report_failed")
    return blockers
