"""Controlled FFmpeg deflicker and interpolation with before/after gates."""

from __future__ import annotations

import json
import shutil
import subprocess
import statistics
from dataclasses import dataclass
from pathlib import Path

from src.content_factory.video_control_gate import (
    ControlRegion,
    VideoControlGate,
    VideoControlManifest,
)


MANIFEST_TEMPLATE = "video_temporal_repair/v1"
REPORT_TEMPLATE = "video_temporal_repair_report/v1"
DEFLICKER_MODES = {"am", "gm", "hm", "qm", "cm", "pm", "median"}
DEFLICKER_ALGORITHMS = {"ffmpeg", "luma_gain"}
LUMA_TARGETS = {"reference", "median", "first"}
INTERPOLATION_MODES = {"none", "minterpolate"}
REPAIRABLE_FLICKER_ISSUES = {
    "lighting_flicker",
    "color_flicker",
    "motion_too_large",
    "anchor_drift",
    "active_area_too_large",
}
STRUCTURAL_ISSUES = {
    "static_region_changed",
    "reference_lock_failed",
    "region_motion_too_large",
    "region_anchor_drift",
    "region_active_area_too_large",
    "hand_anatomy",
    "hand_position",
    "phone_position",
    "hand_object_contact",
    "identity_consistency",
    "camera_constraint",
    "motion_scope",
}


@dataclass(frozen=True, slots=True)
class TemporalRepairManifest:
    manifest_path: Path
    input_video: Path
    input_control_manifest: Path
    input_control_report: Path
    output_video: Path
    deflicker_enabled: bool
    deflicker_algorithm: str
    deflicker_size: int
    deflicker_mode: str
    luma_target: str
    luma_strength: float
    maximum_gain_delta: float
    interpolation: str
    target_fps: float | None
    minimum_luma_improvement: float
    crf: int
    preset: str

    @classmethod
    def load(cls, manifest_path: str | Path) -> "TemporalRepairManifest":
        path = Path(manifest_path).resolve()
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("template") != MANIFEST_TEMPLATE:
            raise ValueError(f"template must be {MANIFEST_TEMPLATE}")

        raw_repair = data.get("repair", {})
        if not isinstance(raw_repair, dict):
            raise ValueError("repair must be an object")
        raw_deflicker = raw_repair.get("deflicker", {})
        if not isinstance(raw_deflicker, dict):
            raise ValueError("repair.deflicker must be an object")
        deflicker_enabled = _boolean(raw_deflicker, "enabled", True)
        deflicker_algorithm = str(
            raw_deflicker.get("algorithm", "ffmpeg")
        ).strip()
        if deflicker_algorithm not in DEFLICKER_ALGORITHMS:
            choices = ", ".join(sorted(DEFLICKER_ALGORITHMS))
            raise ValueError(
                f"repair.deflicker.algorithm must be one of: {choices}"
            )
        deflicker_size = _bounded_int(
            raw_deflicker,
            "size",
            default=5,
            minimum=2,
            maximum=129,
        )
        deflicker_mode = str(raw_deflicker.get("mode", "am")).strip()
        if deflicker_mode not in DEFLICKER_MODES:
            choices = ", ".join(sorted(DEFLICKER_MODES))
            raise ValueError(f"repair.deflicker.mode must be one of: {choices}")
        luma_target = str(raw_deflicker.get("target", "reference")).strip()
        if luma_target not in LUMA_TARGETS:
            choices = ", ".join(sorted(LUMA_TARGETS))
            raise ValueError(f"repair.deflicker.target must be one of: {choices}")
        luma_strength = _bounded_float(
            raw_deflicker,
            "strength",
            default=1.0,
            minimum=0.0,
            maximum=1.0,
        )
        maximum_gain_delta = _bounded_float(
            raw_deflicker,
            "maximum_gain_delta",
            default=0.35,
            minimum=0.01,
            maximum=1.0,
        )

        interpolation = str(raw_repair.get("interpolation", "none")).strip()
        if interpolation not in INTERPOLATION_MODES:
            choices = ", ".join(sorted(INTERPOLATION_MODES))
            raise ValueError(f"repair.interpolation must be one of: {choices}")
        raw_target_fps = raw_repair.get("target_fps")
        target_fps = (
            _positive_float(raw_repair, "target_fps")
            if raw_target_fps is not None
            else None
        )
        if interpolation == "minterpolate" and target_fps is None:
            raise ValueError(
                "repair.target_fps is required when interpolation=minterpolate"
            )
        if not deflicker_enabled and interpolation == "none":
            raise ValueError("repair must enable deflicker or interpolation")

        raw_acceptance = data.get("acceptance", {})
        if not isinstance(raw_acceptance, dict):
            raise ValueError("acceptance must be an object")
        minimum_luma_improvement = _bounded_float(
            raw_acceptance,
            "minimum_luma_improvement",
            default=0.15,
            minimum=0.0,
            maximum=1.0,
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
            deflicker_enabled=deflicker_enabled,
            deflicker_algorithm=deflicker_algorithm,
            deflicker_size=deflicker_size,
            deflicker_mode=deflicker_mode,
            luma_target=luma_target,
            luma_strength=luma_strength,
            maximum_gain_delta=maximum_gain_delta,
            interpolation=interpolation,
            target_fps=target_fps,
            minimum_luma_improvement=minimum_luma_improvement,
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
            raise FileNotFoundError(f"temporal repair assets missing: {names}")

    def filter_chain(self) -> str:
        filters: list[str] = []
        if self.deflicker_enabled:
            if self.deflicker_algorithm == "ffmpeg":
                filters.append(
                    f"deflicker=size={self.deflicker_size}:"
                    f"mode={self.deflicker_mode}"
                )
            else:
                filters.append(
                    "luma_gain="
                    f"target={self.luma_target}:"
                    f"strength={self.luma_strength:.3f}:"
                    f"max_delta={self.maximum_gain_delta:.3f}"
                )
        if self.interpolation == "minterpolate":
            assert self.target_fps is not None
            filters.append(
                "minterpolate="
                f"fps={self.target_fps:.8f}:mi_mode=mci:"
                "mc_mode=aobmc:me_mode=bidir:vsbmc=1"
            )
        return ",".join(filters)


def run_video_temporal_repair(
    manifest_path: str | Path,
    *,
    report_path: str | Path | None = None,
    dry_run: bool = False,
    ffmpeg: str = "ffmpeg",
) -> dict[str, object]:
    manifest = TemporalRepairManifest.load(manifest_path)
    manifest.validate_assets()
    input_control = VideoControlManifest.load(manifest.input_control_manifest)
    input_report = _read_json(manifest.input_control_report)
    _validate_report_matches_video(input_report, manifest.input_video)
    issue_codes = _error_issue_codes(input_report)
    blocked_issues = sorted(
        issue_codes & STRUCTURAL_ISSUES
        or issue_codes - REPAIRABLE_FLICKER_ISSUES
    )
    plan = {
        "template": "video_temporal_repair_plan/v1",
        "input_video": str(manifest.input_video),
        "output_video": str(manifest.output_video),
        "control_mode": input_control.mode,
        "filter_chain": manifest.filter_chain(),
        "input_issue_codes": sorted(issue_codes),
        "blocked_issue_codes": blocked_issues,
    }
    if dry_run:
        return plan
    if blocked_issues:
        return _write_result(
            manifest,
            {
                "template": REPORT_TEMPLATE,
                "status": "blocked",
                "output": None,
                "reason": "structural_or_unmapped_input_failure",
                "blocked_issue_codes": blocked_issues,
                "plan": plan,
            },
            report_path,
        )

    output = manifest.output_video
    output.parent.mkdir(parents=True, exist_ok=True)
    pending = output.with_name(f"{output.stem}.pending{output.suffix}")
    pending.unlink(missing_ok=True)
    _render_repair(manifest, pending, ffmpeg=ffmpeg)

    output_control_manifest = output.with_suffix(".control.manifest.json")
    output_control_report = output.with_suffix(".control.report.json")
    output_control_manifest.write_text(
        json.dumps(
            _output_control_manifest(input_control, pending),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    gate_report = VideoControlGate().inspect_manifest(
        output_control_manifest,
        output_control_report,
    )
    input_luma = _temporal_metric(input_report, "luma_range")
    output_luma = _temporal_metric(
        {"metadata": gate_report.metadata},
        "luma_range",
    )
    luma_improvement = (
        (input_luma - output_luma) / input_luma
        if input_luma > 0
        else 0.0
    )
    improvement_required = bool(
        {"lighting_flicker", "color_flicker"} & issue_codes
        and manifest.deflicker_enabled
    )
    issues: list[dict[str, str]] = [
        {
            "code": issue.code,
            "message": issue.message,
            "severity": issue.severity,
        }
        for issue in gate_report.issues
    ]
    if (
        improvement_required
        and luma_improvement < manifest.minimum_luma_improvement
    ):
        issues.append(
            {
                "code": "deflicker_improvement_insufficient",
                "message": (
                    f"luma improvement {luma_improvement:.4f} is below "
                    f"{manifest.minimum_luma_improvement:.4f}"
                ),
                "severity": "error",
            }
        )
    accepted = gate_report.passed and not any(
        issue["severity"] == "error" for issue in issues
    )
    if accepted:
        pending.replace(output)
        control_data = json.loads(
            output_control_manifest.read_text(encoding="utf-8")
        )
        control_data["video_path"] = str(output)
        output_control_manifest.write_text(
            json.dumps(control_data, ensure_ascii=False, indent=2),
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
        "input_luma_range": round(input_luma, 4),
        "output_luma_range": round(output_luma, 4),
        "luma_improvement": round(luma_improvement, 4),
        "issues": issues,
        "plan": plan,
    }
    return _write_result(manifest, result, report_path)


def _render_repair(
    manifest: TemporalRepairManifest,
    output_path: Path,
    *,
    ffmpeg: str,
) -> None:
    if (
        manifest.deflicker_enabled
        and manifest.deflicker_algorithm == "luma_gain"
    ):
        _render_luma_gain(manifest, output_path, ffmpeg=ffmpeg)
        return
    executable = shutil.which(ffmpeg) or ffmpeg
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
            manifest.filter_chain(),
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
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
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg temporal repair failed: {result.stderr[-2000:]}")


def _render_luma_gain(
    manifest: TemporalRepairManifest,
    output_path: Path,
    *,
    ffmpeg: str,
) -> None:
    executable = shutil.which(ffmpeg) or ffmpeg
    metadata = _probe_video(manifest.input_video, ffmpeg=executable)
    width = int(metadata["width"])
    height = int(metadata["height"])
    fps = float(metadata["fps"])
    luma_values = _decode_luma_values(
        manifest.input_video,
        width,
        height,
        ffmpeg=executable,
    )
    if not luma_values:
        raise RuntimeError("no frames decoded for luma stabilization")
    target_luma = _target_luma(
        manifest,
        luma_values,
        (width, height),
        ffmpeg=executable,
    )
    gains = [
        _brightness_gain(
            value,
            target_luma,
            strength=manifest.luma_strength,
            maximum_delta=manifest.maximum_gain_delta,
        )
        for value in luma_values
    ]

    decoder = subprocess.Popen(
        [
            executable,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(manifest.input_video),
            "-map",
            "0:v:0",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "yuv444p",
            "pipe:1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    encoder_command = [
        executable,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "yuv444p",
        "-s",
        f"{width}x{height}",
        "-r",
        f"{fps:.8f}",
        "-i",
        "pipe:0",
        "-i",
        str(manifest.input_video),
    ]
    if manifest.interpolation == "minterpolate":
        assert manifest.target_fps is not None
        encoder_command.extend(
            [
                "-vf",
                "minterpolate="
                f"fps={manifest.target_fps:.8f}:mi_mode=mci:"
                "mc_mode=aobmc:me_mode=bidir:vsbmc=1",
            ]
        )
    encoder_command.extend(
        [
            "-map",
            "0:v:0",
            "-map",
            "1:a?",
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
            "-shortest",
            str(output_path),
        ]
    )
    encoder = subprocess.Popen(
        encoder_command,
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if (
        decoder.stdout is None
        or decoder.stderr is None
        or encoder.stdin is None
        or encoder.stderr is None
    ):
        decoder.kill()
        encoder.kill()
        raise RuntimeError("unable to open temporal repair pipes")

    plane_size = width * height
    frame_size = plane_size * 3
    frame_index = 0
    try:
        while frame_index < len(gains):
            raw = _read_exact(decoder.stdout, frame_size)
            if raw is None:
                break
            gain = gains[frame_index]
            lookup = bytes(
                min(255, max(0, round(value * gain)))
                for value in range(256)
            )
            adjusted_y = raw[:plane_size].translate(lookup)
            encoder.stdin.write(adjusted_y + raw[plane_size:])
            frame_index += 1
        encoder.stdin.close()
        decoder_stderr = decoder.stderr.read().decode("utf-8", errors="replace")
        encoder_stderr = encoder.stderr.read().decode("utf-8", errors="replace")
        decoder_code = decoder.wait()
        encoder_code = encoder.wait()
    except BaseException:
        decoder.kill()
        encoder.kill()
        decoder.wait()
        encoder.wait()
        raise
    if decoder_code != 0:
        raise RuntimeError(f"FFmpeg frame decode failed: {decoder_stderr[-2000:]}")
    if encoder_code != 0:
        raise RuntimeError(f"FFmpeg luma encode failed: {encoder_stderr[-2000:]}")
    if frame_index != len(gains):
        raise RuntimeError(
            f"decoded frame count changed: expected {len(gains)}, got {frame_index}"
        )


def _decode_luma_values(
    video_path: Path,
    width: int,
    height: int,
    *,
    ffmpeg: str,
) -> list[float]:
    process = subprocess.Popen(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video_path),
            "-map",
            "0:v:0",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "yuv444p",
            "pipe:1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if process.stdout is None or process.stderr is None:
        process.kill()
        raise RuntimeError("unable to open FFmpeg decoder pipe")
    plane_size = width * height
    frame_size = plane_size * 3
    values: list[float] = []
    while True:
        raw = _read_exact(process.stdout, frame_size)
        if raw is None:
            break
        values.append(sum(raw[:plane_size]) / plane_size)
    stderr = process.stderr.read().decode("utf-8", errors="replace")
    code = process.wait()
    if code != 0:
        raise RuntimeError(f"FFmpeg luma scan failed: {stderr[-2000:]}")
    return values


def _target_luma(
    manifest: TemporalRepairManifest,
    values: list[float],
    size: tuple[int, int],
    *,
    ffmpeg: str,
) -> float:
    if manifest.luma_target == "first":
        return values[0]
    if manifest.luma_target == "median":
        return float(statistics.median(values))
    source = VideoControlManifest.load(manifest.input_control_manifest)
    if source.reference_image is None or not source.reference_image.is_file():
        raise ValueError(
            "repair.deflicker.target=reference requires a valid reference_image"
        )
    width, height = size
    result = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source.reference_image),
            "-vf",
            f"scale={width}:{height}:flags=lanczos",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "yuv444p",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
    )
    plane_size = width * height
    if len(result.stdout) < plane_size:
        raise RuntimeError("unable to decode reference luma plane")
    return sum(result.stdout[:plane_size]) / plane_size


def _brightness_gain(
    current_luma: float,
    target_luma: float,
    *,
    strength: float,
    maximum_delta: float,
) -> float:
    if current_luma <= 0:
        return 1.0
    raw_gain = target_luma / current_luma
    corrected = 1.0 + (raw_gain - 1.0) * strength
    return min(1.0 + maximum_delta, max(1.0 - maximum_delta, corrected))


def _probe_video(path: Path, *, ffmpeg: str) -> dict[str, float | int]:
    ffprobe = str(Path(ffmpeg).with_name("ffprobe.exe"))
    if not Path(ffprobe).is_file():
        ffprobe = shutil.which("ffprobe") or "ffprobe"
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,r_frame_rate",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    if not streams:
        raise ValueError("video stream not found")
    stream = streams[0]
    numerator, denominator = str(stream["r_frame_rate"]).split("/", maxsplit=1)
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "fps": float(numerator) / float(denominator),
    }


def _read_exact(stream: object, size: int) -> bytes | None:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            if not chunks:
                return None
            raise RuntimeError("truncated raw video frame")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _output_control_manifest(
    source: VideoControlManifest,
    video_path: Path,
) -> dict[str, object]:
    data: dict[str, object] = {
        "template": "video_control/v1",
        "video_path": str(video_path),
        "mode": source.mode,
        "regions": {
            region.name: _region_dict(region)
            for region in source.regions
        },
    }
    if source.reference_image is not None:
        data["reference_image"] = str(source.reference_image)
    if source.intent is not None:
        data["intent"] = source.intent.to_dict()
    return data


def _region_dict(region: ControlRegion) -> dict[str, object]:
    data: dict[str, object] = {
        "rect": list(region.rect),
        "motion": region.motion,
        "reference_lock": region.reference_lock,
    }
    for key in (
        "max_frame_distance",
        "max_anchor_distance",
        "max_active_pixel_ratio",
        "min_active_pixel_ratio",
    ):
        value = getattr(region, key)
        if value is not None:
            data[key] = value
    return data


def _validate_report_matches_video(
    report: dict[str, object],
    video_path: Path,
) -> None:
    raw = report.get("path")
    if not isinstance(raw, str) or Path(raw).resolve() != video_path.resolve():
        raise ValueError("input_control_report path does not match input_video")


def _error_issue_codes(report: dict[str, object]) -> set[str]:
    issues = report.get("issues", [])
    if not isinstance(issues, list):
        raise ValueError("input_control_report issues must be an array")
    return {
        str(issue["code"])
        for issue in issues
        if isinstance(issue, dict)
        and issue.get("severity", "error") == "error"
        and isinstance(issue.get("code"), str)
    }


def _temporal_metric(report: dict[str, object], key: str) -> float:
    metadata = report.get("metadata", {})
    temporal = metadata.get("temporal", {}) if isinstance(metadata, dict) else {}
    raw = temporal.get(key, 0.0) if isinstance(temporal, dict) else 0.0
    return float(raw) if isinstance(raw, (int, float)) else 0.0


def _write_result(
    manifest: TemporalRepairManifest,
    result: dict[str, object],
    report_path: str | Path | None,
) -> dict[str, object]:
    destination = (
        Path(report_path)
        if report_path is not None
        else manifest.output_video.with_suffix(".temporal.report.json")
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    result["report_path"] = str(destination)
    return result


def _required_path(
    manifest_path: Path,
    data: dict[str, object],
    key: str,
) -> Path:
    raw = data.get(key)
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{key} must be a non-empty string")
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = manifest_path.parent / candidate
    return candidate.resolve()


def _boolean(data: dict[str, object], key: str, default: bool) -> bool:
    raw = data.get(key, default)
    if not isinstance(raw, bool):
        raise ValueError(f"{key} must be a boolean")
    return raw


def _positive_float(data: dict[str, object], key: str) -> float:
    raw = data.get(key)
    if not isinstance(raw, (int, float)) or float(raw) <= 0:
        raise ValueError(f"{key} must be a positive number")
    return float(raw)


def _bounded_float(
    data: dict[str, object],
    key: str,
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    raw = data.get(key, default)
    if not isinstance(raw, (int, float)):
        raise ValueError(f"{key} must be a number")
    result = float(raw)
    if result < minimum or result > maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}")
    return result


def _bounded_int(
    data: dict[str, object],
    key: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = data.get(key, default)
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise ValueError(f"{key} must be an integer")
    if raw < minimum or raw > maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}")
    return raw


def _read_json(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"report must be a JSON object: {path}")
    return data
