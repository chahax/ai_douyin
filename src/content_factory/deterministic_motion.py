"""Deterministic single-image animation with bounded lighting and particles."""

from __future__ import annotations

import json
import math
import random
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from src.content_factory.video_control_gate import VideoControlGate


TEMPLATE = "deterministic_motion/v1"
REPORT_TEMPLATE = "deterministic_motion_report/v1"


@dataclass(frozen=True, slots=True)
class LightPulse:
    name: str
    rect: tuple[float, float, float, float]
    color: tuple[int, int, int]
    opacity: float
    blur: float
    start: float
    peak: float
    end: float


@dataclass(frozen=True, slots=True)
class ParticleLayer:
    name: str
    rect: tuple[float, float, float, float]
    count: int
    color: tuple[int, int, int]
    opacity: float
    radius: float
    drift: tuple[float, float]
    twinkle: float
    seed: int


@dataclass(frozen=True, slots=True)
class DeterministicMotionManifest:
    manifest_path: Path
    source_image: Path
    output_path: Path
    width: int
    height: int
    fps: float
    duration: float
    crf: int
    preset: str
    minimum_activity_ratio: float
    light_pulses: tuple[LightPulse, ...]
    particle_layers: tuple[ParticleLayer, ...]

    @classmethod
    def load(cls, manifest_path: str | Path) -> "DeterministicMotionManifest":
        path = Path(manifest_path).resolve()
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("template") != TEMPLATE:
            raise ValueError(f"template must be {TEMPLATE}")

        source_image = _resolve_path(path, _required_string(data, "source_image"))
        output_path = _resolve_path(path, _required_string(data, "output_path"))
        width = _positive_even_int(data, "width")
        height = _positive_even_int(data, "height")
        fps = _positive_float(data, "fps")
        duration = _positive_float(data, "duration_seconds")
        crf = _bounded_int(data, "crf", default=18, minimum=0, maximum=51)
        preset = str(data.get("preset", "slow")).strip() or "slow"

        raw_safety = data.get("safety", {})
        if not isinstance(raw_safety, dict):
            raise ValueError("safety must be an object")
        minimum_activity_ratio = _bounded_float(
            raw_safety,
            "minimum_activity_ratio",
            default=0.001,
            minimum=0.0,
            maximum=0.02,
        )
        maximum_effect_area_ratio = _bounded_float(
            raw_safety,
            "maximum_effect_area_ratio",
            default=0.04,
            minimum=0.0,
            maximum=0.08,
        )

        raw_effects = data.get("effects", {})
        if not isinstance(raw_effects, dict):
            raise ValueError("effects must be an object")
        light_pulses = tuple(
            _parse_light_pulse(item, index, duration)
            for index, item in enumerate(_object_list(raw_effects, "light_pulses"))
        )
        particle_layers = tuple(
            _parse_particle_layer(item, index)
            for index, item in enumerate(_object_list(raw_effects, "particles"))
        )
        if not light_pulses and not particle_layers:
            raise ValueError("at least one deterministic effect is required")

        declared_area = sum(_rect_area(item.rect) for item in light_pulses)
        declared_area += sum(_rect_area(item.rect) for item in particle_layers)
        if declared_area - maximum_effect_area_ratio > 1e-9:
            raise ValueError(
                "declared effect area "
                f"{declared_area:.4f} exceeds safety.maximum_effect_area_ratio "
                f"{maximum_effect_area_ratio:.4f}"
            )

        return cls(
            manifest_path=path,
            source_image=source_image,
            output_path=output_path,
            width=width,
            height=height,
            fps=fps,
            duration=duration,
            crf=crf,
            preset=preset,
            minimum_activity_ratio=minimum_activity_ratio,
            light_pulses=light_pulses,
            particle_layers=particle_layers,
        )

    @property
    def frame_count(self) -> int:
        return max(2, round(self.duration * self.fps))

    def validate_assets(self) -> None:
        if not self.source_image.is_file():
            raise FileNotFoundError(f"source image does not exist: {self.source_image}")

    def plan(self) -> dict[str, object]:
        return {
            "template": "deterministic_motion_plan/v1",
            "source_image": str(self.source_image),
            "output_path": str(self.output_path),
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "duration_seconds": self.duration,
            "frame_count": self.frame_count,
            "effects": {
                "light_pulses": len(self.light_pulses),
                "particles": len(self.particle_layers),
                "declared_area_ratio": round(
                    sum(_rect_area(item.rect) for item in self.light_pulses)
                    + sum(_rect_area(item.rect) for item in self.particle_layers),
                    4,
                ),
            },
            "control_mode": "pixel_locked",
        }


def run_deterministic_motion(
    manifest_path: str | Path,
    *,
    report_path: str | Path | None = None,
    qa_dir: str | Path | None = None,
    dry_run: bool = False,
    ffmpeg: str = "ffmpeg",
) -> dict[str, object]:
    manifest = DeterministicMotionManifest.load(manifest_path)
    manifest.validate_assets()
    if dry_run:
        return manifest.plan()

    output = manifest.output_path
    output.parent.mkdir(parents=True, exist_ok=True)
    qa_root = Path(qa_dir).resolve() if qa_dir is not None else output.parent
    qa_root.mkdir(parents=True, exist_ok=True)
    pending = output.with_name(f"{output.stem}.pending{output.suffix}")
    pending.unlink(missing_ok=True)
    try:
        _render_video(manifest, pending, ffmpeg=ffmpeg)
        control_manifest_path = (
            qa_root / f"{output.stem}.control.manifest.json"
        )
        control_report_path = qa_root / f"{output.stem}.control.report.json"
        control_manifest_path.write_text(
            json.dumps(_control_manifest(manifest, pending), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        control_report = VideoControlGate().inspect_manifest(
            control_manifest_path,
            control_report_path,
        )
        activity_ratio = float(
            control_report.metadata.get("temporal", {}).get(
                "max_active_pixel_ratio",
                0.0,
            )
        )
        if activity_ratio < manifest.minimum_activity_ratio:
            control_report.add_issue(
                "motion_too_subtle",
                f"active pixel ratio {activity_ratio:.4f} is below "
                f"{manifest.minimum_activity_ratio:.4f}",
            )
            control_report.write_json(control_report_path)

        status = "accepted" if control_report.passed else "rejected"
        if control_report.passed:
            pending.replace(output)
            control_data = json.loads(control_manifest_path.read_text(encoding="utf-8"))
            control_data["video_path"] = str(output)
            control_manifest_path.write_text(
                json.dumps(control_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            control_report.path = str(output)
            control_report.write_json(control_report_path)
            control_report.path = str(output)
            control_report.write_json(control_report_path)

        result = {
            "template": REPORT_TEMPLATE,
            "status": status,
            "output": str(output) if control_report.passed else None,
            "pending_output": None if control_report.passed else str(pending),
            "control_manifest": str(control_manifest_path),
            "control_report": str(control_report_path),
            "plan": manifest.plan(),
            "activity_ratio": activity_ratio,
            "issues": [
                {
                    "code": issue.code,
                    "message": issue.message,
                    "severity": issue.severity,
                }
                for issue in control_report.issues
            ],
        }
        destination = (
            Path(report_path)
            if report_path is not None
            else qa_root / f"{output.stem}.motion.report.json"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return result
    finally:
        if pending.is_file() and output.is_file():
            pending.unlink(missing_ok=True)


def render_frame(
    manifest: DeterministicMotionManifest,
    base_image: Image.Image,
    frame_index: int,
) -> Image.Image:
    progress = frame_index / max(1, manifest.frame_count - 1)
    frame = base_image.copy().convert("RGBA")
    for pulse in manifest.light_pulses:
        strength = _pulse_strength(progress * manifest.duration, pulse)
        if strength > 0:
            frame = _apply_light_pulse(frame, pulse, strength)
    if manifest.particle_layers:
        layer = Image.new("RGBA", frame.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        for particles in manifest.particle_layers:
            _draw_particles(draw, particles, progress, frame.size)
        frame = Image.alpha_composite(frame, layer)
    return frame.convert("RGB")


def _render_video(
    manifest: DeterministicMotionManifest,
    output_path: Path,
    *,
    ffmpeg: str,
) -> None:
    with Image.open(manifest.source_image) as source:
        base = ImageOps.fit(
            source.convert("RGB"),
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
        raise RuntimeError("unable to open FFmpeg pipes")
    try:
        for frame_index in range(manifest.frame_count):
            frame = render_frame(manifest, base, frame_index)
            process.stdin.write(frame.tobytes())
        process.stdin.close()
        stderr = process.stderr.read().decode("utf-8", errors="replace")
        return_code = process.wait()
    except BaseException:
        process.kill()
        process.wait()
        raise
    if return_code != 0:
        raise RuntimeError(f"FFmpeg deterministic motion render failed: {stderr[-2000:]}")


def _control_manifest(
    manifest: DeterministicMotionManifest,
    video_path: Path,
) -> dict[str, object]:
    regions: dict[str, object] = {}
    for effect in (*manifest.light_pulses, *manifest.particle_layers):
        regions[effect.name] = {
            "rect": _pixel_rect(effect.rect, manifest.width, manifest.height),
            "motion": "dynamic",
            "max_frame_distance": 12.0,
            "max_anchor_distance": 24.0,
            "max_active_pixel_ratio": 0.8,
            "min_active_pixel_ratio": manifest.minimum_activity_ratio,
        }
    return {
        "template": "video_control/v1",
        "video_path": str(video_path),
        "reference_image": str(manifest.source_image),
        "mode": "pixel_locked",
        "regions": regions,
    }


def _apply_light_pulse(
    frame: Image.Image,
    pulse: LightPulse,
    strength: float,
) -> Image.Image:
    width, height = frame.size
    left, top, region_width, region_height = _pixel_rect(pulse.rect, width, height)
    mask = Image.new("L", (region_width, region_height), 0)
    draw = ImageDraw.Draw(mask)
    inset_x = max(1, round(region_width * 0.12))
    inset_y = max(1, round(region_height * 0.12))
    alpha = round(255 * pulse.opacity * strength)
    draw.ellipse(
        (
            inset_x,
            inset_y,
            region_width - inset_x,
            region_height - inset_y,
        ),
        fill=alpha,
    )
    if pulse.blur > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(pulse.blur))
    color = Image.new("RGBA", (region_width, region_height), (*pulse.color, 255))
    overlay = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    overlay.paste(color, (left, top), mask)
    return Image.alpha_composite(frame, overlay)


def _draw_particles(
    draw: ImageDraw.ImageDraw,
    particles: ParticleLayer,
    progress: float,
    size: tuple[int, int],
) -> None:
    left, top, width, height = _pixel_rect(particles.rect, *size)
    randomizer = random.Random(particles.seed)
    for index in range(particles.count):
        origin_x = randomizer.random()
        origin_y = randomizer.random()
        phase = randomizer.random() * math.tau
        position_x = (origin_x + particles.drift[0] * progress) % 1.0
        position_y = (origin_y + particles.drift[1] * progress) % 1.0
        twinkle = 1.0 - particles.twinkle
        twinkle += particles.twinkle * (0.5 + 0.5 * math.sin(math.tau * progress + phase))
        alpha = round(255 * particles.opacity * twinkle)
        radius = max(1.0, particles.radius * (0.8 + 0.4 * (index % 3) / 2))
        center_x = left + position_x * width
        center_y = top + position_y * height
        draw.ellipse(
            (
                center_x - radius,
                center_y - radius,
                center_x + radius,
                center_y + radius,
            ),
            fill=(*particles.color, alpha),
        )


def _pulse_strength(time_seconds: float, pulse: LightPulse) -> float:
    if time_seconds <= pulse.start or time_seconds >= pulse.end:
        return 0.0
    if time_seconds <= pulse.peak:
        phase = (time_seconds - pulse.start) / (pulse.peak - pulse.start)
    else:
        phase = (pulse.end - time_seconds) / (pulse.end - pulse.peak)
    return 0.5 - 0.5 * math.cos(math.pi * max(0.0, min(1.0, phase)))


def _parse_light_pulse(
    value: dict[str, object],
    index: int,
    duration: float,
) -> LightPulse:
    prefix = f"effects.light_pulses[{index}]"
    start = _bounded_float(value, "start", default=0.0, minimum=0.0, maximum=duration)
    peak = _bounded_float(value, "peak", default=duration / 2, minimum=0.0, maximum=duration)
    end = _bounded_float(value, "end", default=duration, minimum=0.0, maximum=duration)
    if not start < peak < end:
        raise ValueError(f"{prefix} requires start < peak < end")
    return LightPulse(
        name=_effect_name(value, index, "light"),
        rect=_normalized_rect(value, "rect", prefix),
        color=_color(value, "color", prefix, default=(90, 150, 255)),
        opacity=_bounded_float(value, "opacity", default=0.18, minimum=0.0, maximum=0.5),
        blur=_bounded_float(value, "blur", default=12.0, minimum=0.0, maximum=80.0),
        start=start,
        peak=peak,
        end=end,
    )


def _parse_particle_layer(
    value: dict[str, object],
    index: int,
) -> ParticleLayer:
    prefix = f"effects.particles[{index}]"
    raw_drift = value.get("drift", [0.02, -0.03])
    if (
        not isinstance(raw_drift, list)
        or len(raw_drift) != 2
        or not all(isinstance(item, (int, float)) for item in raw_drift)
    ):
        raise ValueError(f"{prefix}.drift must contain two numbers")
    return ParticleLayer(
        name=_effect_name(value, index, "particles"),
        rect=_normalized_rect(value, "rect", prefix),
        count=_bounded_int(value, "count", default=3, minimum=1, maximum=24),
        color=_color(value, "color", prefix, default=(220, 235, 255)),
        opacity=_bounded_float(value, "opacity", default=0.12, minimum=0.0, maximum=0.35),
        radius=_bounded_float(value, "radius", default=2.0, minimum=0.5, maximum=8.0),
        drift=(float(raw_drift[0]), float(raw_drift[1])),
        twinkle=_bounded_float(value, "twinkle", default=0.4, minimum=0.0, maximum=1.0),
        seed=_bounded_int(value, "seed", default=42, minimum=0, maximum=2**31 - 1),
    )


def _effect_name(value: dict[str, object], index: int, kind: str) -> str:
    raw = value.get("name", f"{kind}_{index + 1}")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"effect name for {kind}[{index}] must be a non-empty string")
    return raw.strip()


def _normalized_rect(
    value: dict[str, object],
    key: str,
    prefix: str,
) -> tuple[float, float, float, float]:
    raw = value.get(key)
    if (
        not isinstance(raw, list)
        or len(raw) != 4
        or not all(isinstance(item, (int, float)) for item in raw)
    ):
        raise ValueError(f"{prefix}.{key} must contain four numbers")
    rect = tuple(float(item) for item in raw)
    if (
        rect[0] < 0
        or rect[1] < 0
        or rect[2] <= 0
        or rect[3] <= 0
        or rect[0] + rect[2] > 1
        or rect[1] + rect[3] > 1
    ):
        raise ValueError(f"{prefix}.{key} must fit within normalized bounds")
    return rect


def _pixel_rect(
    rect: tuple[float, float, float, float],
    width: int,
    height: int,
) -> list[int]:
    left = min(width - 1, round(rect[0] * width))
    top = min(height - 1, round(rect[1] * height))
    right = min(width, max(left + 1, round((rect[0] + rect[2]) * width)))
    bottom = min(height, max(top + 1, round((rect[1] + rect[3]) * height)))
    return [left, top, right - left, bottom - top]


def _rect_area(rect: tuple[float, float, float, float]) -> float:
    return rect[2] * rect[3]


def _color(
    value: dict[str, object],
    key: str,
    prefix: str,
    *,
    default: tuple[int, int, int],
) -> tuple[int, int, int]:
    raw = value.get(key, list(default))
    if (
        not isinstance(raw, list)
        or len(raw) != 3
        or not all(isinstance(item, int) and 0 <= item <= 255 for item in raw)
    ):
        raise ValueError(f"{prefix}.{key} must contain three integers from 0 to 255")
    return tuple(raw)


def _object_list(value: dict[str, object], key: str) -> list[dict[str, object]]:
    raw = value.get(key, [])
    if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
        raise ValueError(f"effects.{key} must be an array of objects")
    return raw


def _required_string(value: dict[str, object], key: str) -> str:
    raw = value.get(key)
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return raw.strip()


def _resolve_path(manifest_path: Path, raw: str) -> Path:
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = manifest_path.parent / candidate
    return candidate.resolve()


def _positive_even_int(value: dict[str, object], key: str) -> int:
    result = _bounded_int(value, key, default=0, minimum=2, maximum=16384)
    if result % 2:
        raise ValueError(f"{key} must be even")
    return result


def _positive_float(value: dict[str, object], key: str) -> float:
    raw = value.get(key)
    if not isinstance(raw, (int, float)) or float(raw) <= 0:
        raise ValueError(f"{key} must be a positive number")
    return float(raw)


def _bounded_float(
    value: dict[str, object],
    key: str,
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    raw = value.get(key, default)
    if not isinstance(raw, (int, float)):
        raise ValueError(f"{key} must be a number")
    result = float(raw)
    if result < minimum or result > maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}")
    return result


def _bounded_int(
    value: dict[str, object],
    key: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = value.get(key, default)
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise ValueError(f"{key} must be an integer")
    if raw < minimum or raw > maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}")
    return raw
