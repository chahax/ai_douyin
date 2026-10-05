"""Deterministic, mask-bounded directional relighting for approved keyframes."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps


MANIFEST_TEMPLATE = "keyframe_relight/v1"
REPORT_TEMPLATE = "keyframe_relight_report/v1"
_DIRECTIONS = {
    "left": (1.0, 0.0),
    "right": (-1.0, 0.0),
    "top": (0.0, 1.0),
    "bottom": (0.0, -1.0),
    "top_left": (1.0, 1.0),
    "top_right": (-1.0, 1.0),
    "bottom_left": (1.0, -1.0),
    "bottom_right": (-1.0, -1.0),
}


@dataclass(frozen=True, slots=True)
class DirectionalLight:
    direction: str
    highlight_ev: float
    shadow_ev: float
    color: tuple[int, int, int]
    color_strength: float
    curve: float


@dataclass(frozen=True, slots=True)
class RelightSafety:
    maximum_mask_area_ratio: float
    maximum_mean_pixel_change: float
    minimum_mean_pixel_change: float
    minimum_directional_luma_shift: float


@dataclass(frozen=True, slots=True)
class KeyframeRelightManifest:
    manifest_path: Path
    source_image: Path
    mask_image: Path
    output_image: Path
    mask_blur: float
    light: DirectionalLight
    safety: RelightSafety

    @classmethod
    def load(cls, manifest_path: str | Path) -> "KeyframeRelightManifest":
        path = Path(manifest_path).resolve()
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("template") != MANIFEST_TEMPLATE:
            raise ValueError(f"template must be {MANIFEST_TEMPLATE}")

        source_image = _resolve_path(path, _required_string(data, "source_image"))
        mask_image = _resolve_path(path, _required_string(data, "mask_image"))
        output_image = _resolve_path(path, _required_string(data, "output_image"))
        if output_image.suffix.lower() != ".png":
            raise ValueError("output_image must use lossless PNG")

        raw_light = _required_object(data, "light")
        direction = str(raw_light.get("direction", "")).strip().lower()
        if direction not in _DIRECTIONS:
            choices = ", ".join(sorted(_DIRECTIONS))
            raise ValueError(f"light.direction must be one of: {choices}")
        light = DirectionalLight(
            direction=direction,
            highlight_ev=_bounded_float(
                raw_light,
                "highlight_ev",
                default=0.35,
                minimum=-1.0,
                maximum=1.0,
            ),
            shadow_ev=_bounded_float(
                raw_light,
                "shadow_ev",
                default=-0.05,
                minimum=-1.0,
                maximum=1.0,
            ),
            color=_color(raw_light.get("color", [255, 220, 180])),
            color_strength=_bounded_float(
                raw_light,
                "color_strength",
                default=0.08,
                minimum=0.0,
                maximum=0.35,
            ),
            curve=_bounded_float(
                raw_light,
                "curve",
                default=1.0,
                minimum=0.25,
                maximum=4.0,
            ),
        )
        if abs(light.highlight_ev - light.shadow_ev) < 0.05:
            raise ValueError(
                "light.highlight_ev and light.shadow_ev must differ by at least 0.05"
            )

        raw_safety = data.get("safety", {})
        if not isinstance(raw_safety, dict):
            raise ValueError("safety must be an object")
        safety = RelightSafety(
            maximum_mask_area_ratio=_bounded_float(
                raw_safety,
                "maximum_mask_area_ratio",
                default=0.65,
                minimum=0.01,
                maximum=0.85,
            ),
            maximum_mean_pixel_change=_bounded_float(
                raw_safety,
                "maximum_mean_pixel_change",
                default=28.0,
                minimum=1.0,
                maximum=64.0,
            ),
            minimum_mean_pixel_change=_bounded_float(
                raw_safety,
                "minimum_mean_pixel_change",
                default=0.8,
                minimum=0.0,
                maximum=12.0,
            ),
            minimum_directional_luma_shift=_bounded_float(
                raw_safety,
                "minimum_directional_luma_shift",
                default=1.5,
                minimum=0.0,
                maximum=20.0,
            ),
        )
        if (
            safety.minimum_mean_pixel_change
            >= safety.maximum_mean_pixel_change
        ):
            raise ValueError(
                "safety.minimum_mean_pixel_change must be below "
                "maximum_mean_pixel_change"
            )

        mask_blur = _bounded_float(
            data,
            "mask_blur",
            default=4.0,
            minimum=0.0,
            maximum=64.0,
        )
        return cls(
            manifest_path=path,
            source_image=source_image,
            mask_image=mask_image,
            output_image=output_image,
            mask_blur=mask_blur,
            light=light,
            safety=safety,
        )

    def validate_assets(self) -> None:
        for path in (self.source_image, self.mask_image):
            if not path.is_file():
                raise FileNotFoundError(f"input asset does not exist: {path}")
        with (
            Image.open(self.source_image) as source,
            Image.open(self.mask_image) as mask,
        ):
            if source.size != mask.size:
                raise ValueError(
                    "source_image and mask_image must have identical dimensions"
                )

    def plan(self) -> dict[str, object]:
        return {
            "template": "keyframe_relight_plan/v1",
            "source_image": str(self.source_image),
            "mask_image": str(self.mask_image),
            "output_image": str(self.output_image),
            "mask_blur": self.mask_blur,
            "light": asdict(self.light),
            "safety": asdict(self.safety),
            "control_mode": "masked_pixel_preserve",
        }


def run_keyframe_relight(
    manifest_path: str | Path,
    *,
    report_path: str | Path | None = None,
    dry_run: bool = False,
) -> dict[str, object]:
    manifest = KeyframeRelightManifest.load(manifest_path)
    manifest.validate_assets()
    if dry_run:
        return manifest.plan()

    with (
        Image.open(manifest.source_image) as raw_source,
        Image.open(manifest.mask_image) as raw_mask,
    ):
        source = ImageOps.exif_transpose(raw_source).convert("RGB")
        mask = ImageOps.exif_transpose(raw_mask).convert("L")
    if manifest.mask_blur:
        mask = mask.filter(ImageFilter.GaussianBlur(manifest.mask_blur))

    output, field = render_keyframe_relight(source, mask, manifest.light)
    metrics = measure_keyframe_relight(source, output, mask, field)
    issues = _validate_metrics(metrics, manifest.safety)
    status = "accepted" if not issues else "rejected"

    output_path = manifest.output_image
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pending_path = output_path.with_name(f"{output_path.stem}.pending.png")
    pending_path.unlink(missing_ok=True)
    output.save(pending_path, format="PNG", optimize=True)
    if status == "accepted":
        pending_path.replace(output_path)

    report = {
        "template": REPORT_TEMPLATE,
        "status": status,
        "output": str(output_path) if status == "accepted" else None,
        "pending_output": str(pending_path) if status == "rejected" else None,
        "source_image": str(manifest.source_image),
        "mask_image": str(manifest.mask_image),
        "plan": manifest.plan(),
        "metrics": metrics,
        "issues": issues,
    }
    destination = (
        Path(report_path)
        if report_path is not None
        else output_path.with_suffix(".relight.report.json")
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def render_keyframe_relight(
    source: Image.Image,
    mask: Image.Image,
    light: DirectionalLight,
) -> tuple[Image.Image, Image.Image]:
    source_rgb = source.convert("RGB")
    mask_l = mask.convert("L")
    if source_rgb.size != mask_l.size:
        raise ValueError("source and mask must have identical dimensions")
    bbox = mask_l.getbbox()
    if bbox is None:
        raise ValueError("mask_image contains no active pixels")

    field = _directional_field(source_rgb.size, bbox, light.direction, light.curve)
    source_pixels = list(source_rgb.getdata())
    mask_pixels = list(mask_l.getdata())
    field_pixels = list(field.getdata())
    output_pixels: list[tuple[int, int, int]] = []
    tint = light.color
    for pixel, mask_value, field_value in zip(
        source_pixels,
        mask_pixels,
        field_pixels,
        strict=True,
    ):
        if mask_value == 0:
            output_pixels.append(pixel)
            continue
        coverage = mask_value / 255.0
        directional = field_value / 255.0
        exposure = light.shadow_ev + (
            light.highlight_ev - light.shadow_ev
        ) * directional
        gain = 2.0**exposure
        tint_mix = light.color_strength * directional
        adjusted: list[int] = []
        for channel, tint_channel in zip(pixel, tint, strict=True):
            exposed = max(0.0, min(255.0, channel * gain))
            colored = exposed * (1.0 - tint_mix) + tint_channel * tint_mix
            blended = channel * (1.0 - coverage) + colored * coverage
            adjusted.append(round(max(0.0, min(255.0, blended))))
        output_pixels.append(tuple(adjusted))

    output = Image.new("RGB", source_rgb.size)
    output.putdata(output_pixels)
    return output, field


def measure_keyframe_relight(
    source: Image.Image,
    output: Image.Image,
    mask: Image.Image,
    field: Image.Image,
) -> dict[str, object]:
    source_pixels = list(source.convert("RGB").getdata())
    output_pixels = list(output.convert("RGB").getdata())
    mask_pixels = list(mask.convert("L").getdata())
    field_pixels = list(field.convert("L").getdata())
    total_pixels = len(source_pixels)

    weighted_mask = sum(mask_pixels) / 255.0
    inside_changes: list[float] = []
    outside_changes: list[float] = []
    source_light: list[float] = []
    source_shadow: list[float] = []
    output_light: list[float] = []
    output_shadow: list[float] = []
    for before, after, mask_value, field_value in zip(
        source_pixels,
        output_pixels,
        mask_pixels,
        field_pixels,
        strict=True,
    ):
        change = sum(abs(a - b) for a, b in zip(before, after, strict=True)) / 3.0
        if mask_value:
            inside_changes.append(change)
            luma_before = _luma(before)
            luma_after = _luma(after)
            if field_value >= 170:
                source_light.append(luma_before)
                output_light.append(luma_after)
            elif field_value <= 85:
                source_shadow.append(luma_before)
                output_shadow.append(luma_after)
        else:
            outside_changes.append(change)

    before_contrast = _mean(source_light) - _mean(source_shadow)
    after_contrast = _mean(output_light) - _mean(output_shadow)
    return {
        "width": source.width,
        "height": source.height,
        "effective_mask_area_ratio": round(weighted_mask / total_pixels, 6),
        "inside_mean_pixel_change": round(_mean(inside_changes), 4),
        "inside_max_pixel_change": round(max(inside_changes, default=0.0), 4),
        "outside_mean_pixel_change": round(_mean(outside_changes), 6),
        "outside_changed_pixels": sum(value > 0.0 for value in outside_changes),
        "directional_luma_shift": round(after_contrast - before_contrast, 4),
        "light_side_luma_change": round(
            _mean(output_light) - _mean(source_light),
            4,
        ),
        "shadow_side_luma_change": round(
            _mean(output_shadow) - _mean(source_shadow),
            4,
        ),
    }


def _validate_metrics(
    metrics: dict[str, object],
    safety: RelightSafety,
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    mask_ratio = float(metrics["effective_mask_area_ratio"])
    mean_change = float(metrics["inside_mean_pixel_change"])
    directional_shift = float(metrics["directional_luma_shift"])
    outside_changed = int(metrics["outside_changed_pixels"])
    if mask_ratio > safety.maximum_mask_area_ratio:
        issues.append(
            {
                "code": "relight_mask_too_large",
                "message": (
                    f"effective mask area {mask_ratio:.4f} exceeds "
                    f"{safety.maximum_mask_area_ratio:.4f}"
                ),
            }
        )
    if mean_change > safety.maximum_mean_pixel_change:
        issues.append(
            {
                "code": "relight_change_too_large",
                "message": (
                    f"mean masked change {mean_change:.3f} exceeds "
                    f"{safety.maximum_mean_pixel_change:.3f}"
                ),
            }
        )
    if mean_change < safety.minimum_mean_pixel_change:
        issues.append(
            {
                "code": "relight_change_too_subtle",
                "message": (
                    f"mean masked change {mean_change:.3f} is below "
                    f"{safety.minimum_mean_pixel_change:.3f}"
                ),
            }
        )
    if directional_shift < safety.minimum_directional_luma_shift:
        issues.append(
            {
                "code": "relight_direction_missing",
                "message": (
                    f"directional luma shift {directional_shift:.3f} is below "
                    f"{safety.minimum_directional_luma_shift:.3f}"
                ),
            }
        )
    if outside_changed:
        issues.append(
            {
                "code": "relight_outside_mask_changed",
                "message": f"{outside_changed} unmasked pixels changed",
            }
        )
    return issues


def _directional_field(
    size: tuple[int, int],
    bbox: tuple[int, int, int, int],
    direction: str,
    curve: float,
) -> Image.Image:
    width, height = size
    left, top, right, bottom = bbox
    box_width = max(1, right - left - 1)
    box_height = max(1, bottom - top - 1)
    vector_x, vector_y = _DIRECTIONS[direction]
    normalization = abs(vector_x) + abs(vector_y)
    values: list[int] = []
    for y_position in range(height):
        normalized_y = max(0.0, min(1.0, (y_position - top) / box_height))
        for x_position in range(width):
            normalized_x = max(0.0, min(1.0, (x_position - left) / box_width))
            horizontal = (
                1.0 - normalized_x if vector_x > 0 else normalized_x
            )
            vertical = 1.0 - normalized_y if vector_y > 0 else normalized_y
            if vector_x == 0:
                raw = vertical
            elif vector_y == 0:
                raw = horizontal
            else:
                raw = (
                    abs(vector_x) * horizontal + abs(vector_y) * vertical
                ) / normalization
            values.append(round(255 * max(0.0, min(1.0, raw)) ** curve))
    field = Image.new("L", size)
    field.putdata(values)
    return field


def _luma(pixel: tuple[int, int, int]) -> float:
    red, green, blue = pixel
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _resolve_path(manifest_path: Path, value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = manifest_path.parent / path
    return path.resolve()


def _required_string(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required")
    return value


def _required_object(data: dict[str, object], key: str) -> dict[str, object]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object")
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


def _color(value: object) -> tuple[int, int, int]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError("light.color must contain [red, green, blue]")
    channels: list[int] = []
    for channel in value:
        if isinstance(channel, bool) or not isinstance(channel, int):
            raise ValueError("light.color channels must be integers")
        if not 0 <= channel <= 255:
            raise ValueError("light.color channels must be between 0 and 255")
        channels.append(channel)
    return tuple(channels)
