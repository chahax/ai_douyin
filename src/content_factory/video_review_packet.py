"""Create deterministic visual evidence for manual AI-video acceptance."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont


MANIFEST_TEMPLATE = "video_review_packet/v1"
REPORT_TEMPLATE = "video_review_packet_report/v1"
DECISION_TEMPLATE = "video_review_decision/v1"
DECISION_REPORT_TEMPLATE = "video_review_decision_report/v1"


@dataclass(frozen=True, slots=True)
class VideoReviewPacketManifest:
    packet_id: str
    manifest_path: Path
    video_path: Path
    output_dir: Path
    sample_count: int
    plan_report: Path | None
    shot_id: str | None
    control_report: Path | None
    reference_image: Path | None
    mouth_region: tuple[int, int, int, int] | None

    @classmethod
    def load(cls, manifest_path: str | Path) -> "VideoReviewPacketManifest":
        path = Path(manifest_path).resolve()
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("template") != MANIFEST_TEMPLATE:
            raise ValueError(f"template must be {MANIFEST_TEMPLATE}")
        packet_id = _required_string(data, "id")
        sample_count = _bounded_int(data, "sample_count", 5, 3, 9)
        shot_id = _optional_string(data, "shot_id")
        plan_report = _optional_path(path, data, "plan_report")
        if (plan_report is None) != (shot_id is None):
            raise ValueError("plan_report and shot_id must be provided together")
        return cls(
            packet_id=packet_id,
            manifest_path=path,
            video_path=_required_path(path, data, "video_path"),
            output_dir=_required_path(path, data, "output_dir"),
            sample_count=sample_count,
            plan_report=plan_report,
            shot_id=shot_id,
            control_report=_optional_path(path, data, "control_report"),
            reference_image=_optional_path(path, data, "reference_image"),
            mouth_region=_optional_rect(data, "mouth_region"),
        )


def create_video_review_packet(
    manifest_path: str | Path,
    *,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
) -> dict[str, object]:
    manifest = VideoReviewPacketManifest.load(manifest_path)
    if not manifest.video_path.is_file():
        raise FileNotFoundError(f"video not found: {manifest.video_path}")
    if manifest.reference_image and not manifest.reference_image.is_file():
        raise FileNotFoundError(f"reference image not found: {manifest.reference_image}")

    metadata = _probe_video(manifest.video_path, ffprobe=ffprobe)
    route_context = _load_route_context(manifest.plan_report, manifest.shot_id)
    control_context = _load_control_context(manifest.control_report)
    checks = route_context.get(
        "acceptance_checks",
        [
            "technical_metadata",
            "identity_consistency",
            "lighting_stability",
            "camera_constraint",
            "motion_scope",
        ],
    )
    frame_count = metadata["frame_count"]
    fps = metadata["fps"]
    indices = _sample_indices(frame_count, manifest.sample_count)
    manifest.output_dir.mkdir(parents=True, exist_ok=True)

    samples: list[dict[str, object]] = []
    sample_images: list[tuple[str, Image.Image]] = []
    first_image: Image.Image | None = None
    for index in indices:
        timestamp = index / fps
        frame_path = manifest.output_dir / f"f{index:04d}.png"
        _extract_frame(
            manifest.video_path,
            frame_path,
            timestamp=timestamp,
            ffmpeg=ffmpeg,
        )
        with Image.open(frame_path) as source:
            image = source.convert("RGB")
        if first_image is None:
            first_image = image.copy()
        mean_difference, active_ratio = _difference_metrics(first_image, image)
        label = f"f{index:04d} / {timestamp:.2f}s"
        sample_images.append((label, image))
        samples.append(
            {
                "frame_index": index,
                "timestamp": round(timestamp, 4),
                "path": str(frame_path),
                "mean_difference_from_start": round(mean_difference, 4),
                "active_pixel_ratio_from_start": round(active_ratio, 6),
            }
        )

    if first_image is None:
        raise RuntimeError("no review frames were extracted")

    contact_items = list(sample_images)
    if manifest.reference_image:
        with Image.open(manifest.reference_image) as source:
            reference = source.convert("RGB")
        contact_items.insert(0, ("approved reference", reference))

    contact_sheet = manifest.output_dir / "contact_sheet.png"
    _build_contact_sheet(contact_items, contact_sheet)
    difference_sheet = manifest.output_dir / "difference_sheet.png"
    difference_items = [
        (label, _amplified_difference(first_image, image))
        for label, image in sample_images
    ]
    _build_contact_sheet(difference_items, difference_sheet)

    mouth_metrics = _region_motion_metrics(
        [image for _, image in sample_images],
        manifest.mouth_region,
    )
    automatic_checks = _automatic_checks(metadata, checks, mouth_metrics)
    automatic_checks_passed = all(
        item["status"] != "failed"
        for item in automatic_checks.values()
    )
    report = {
        "template": REPORT_TEMPLATE,
        "id": manifest.packet_id,
        "status": "pending_manual_review",
        "video_path": str(manifest.video_path),
        "output_dir": str(manifest.output_dir),
        "route": route_context,
        "machine_gate": control_context,
        "automatic_checks_passed": automatic_checks_passed,
        "automatic_checks": automatic_checks,
        "metadata": metadata,
        "mouth_motion": mouth_metrics,
        "samples": samples,
        "artifacts": {
            "contact_sheet": str(contact_sheet),
            "difference_sheet": str(difference_sheet),
        },
        "acceptance_checks": checks,
        "manual_review": {
            check: {
                "status": "pending",
                "notes": "",
            }
            for check in checks
        },
    }
    report_path = manifest.output_dir / "review.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    report["report_path"] = str(report_path)
    return report


def finalize_video_review(decision_manifest_path: str | Path) -> dict[str, object]:
    path = Path(decision_manifest_path).resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("template") != DECISION_TEMPLATE:
        raise ValueError(f"template must be {DECISION_TEMPLATE}")
    review_path = _required_path(path, data, "review_report")
    output_path = _required_path(path, data, "output_path")
    reviewer = _required_string(data, "reviewer")
    decisions = data.get("decisions")
    if not isinstance(decisions, dict):
        raise ValueError("decisions must be an object")

    review = json.loads(review_path.read_text(encoding="utf-8"))
    if review.get("template") != REPORT_TEMPLATE:
        raise ValueError(f"review_report must be {REPORT_TEMPLATE}")
    expected_checks = review.get("acceptance_checks")
    if not isinstance(expected_checks, list) or not all(
        isinstance(check, str) and check for check in expected_checks
    ):
        raise ValueError("review_report acceptance_checks must be a string array")

    expected_set = set(expected_checks)
    decision_set = set(decisions)
    missing = sorted(expected_set - decision_set)
    unknown = sorted(decision_set - expected_set)
    if missing:
        raise ValueError(f"missing review decisions: {', '.join(missing)}")
    if unknown:
        raise ValueError(f"unknown review decisions: {', '.join(unknown)}")

    normalized: dict[str, dict[str, str]] = {}
    failed_checks: list[str] = []
    for check in expected_checks:
        raw_decision = decisions[check]
        if not isinstance(raw_decision, dict):
            raise ValueError(f"decisions.{check} must be an object")
        status = _required_string(raw_decision, "status")
        if status not in {"passed", "failed"}:
            raise ValueError(f"decisions.{check}.status must be passed or failed")
        notes = str(raw_decision.get("notes") or "").strip()
        if status == "failed" and not notes:
            raise ValueError(f"decisions.{check}.notes is required when failed")
        if status == "failed":
            failed_checks.append(check)
        normalized[check] = {
            "status": status,
            "notes": notes,
        }

    machine_gate = review.get("machine_gate", {})
    machine_passed = (
        isinstance(machine_gate, dict) and machine_gate.get("passed") is True
    )
    automatic_checks_passed = review.get("automatic_checks_passed") is True
    if not machine_passed:
        failed_checks.insert(0, "machine_gate")
    if not automatic_checks_passed:
        failed_checks.insert(0, "automatic_checks")
    accepted = not failed_checks
    result = {
        "template": DECISION_REPORT_TEMPLATE,
        "id": review.get("id"),
        "status": "accepted" if accepted else "rejected",
        "composition_eligible": accepted,
        "reviewer": reviewer,
        "video_path": review.get("video_path"),
        "review_report": str(review_path),
        "machine_gate_passed": machine_passed,
        "automatic_checks_passed": automatic_checks_passed,
        "failed_checks": failed_checks,
        "decisions": normalized,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    result["output_path"] = str(output_path)
    return result


def _probe_video(path: Path, *, ffprobe: str) -> dict[str, object]:
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,width,height,avg_frame_rate,nb_frames,codec_name,"
            "pix_fmt,duration,sample_rate,channels",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed:\n{result.stderr[-1200:]}")
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    if not streams:
        raise ValueError("ffprobe returned no video stream")
    stream = next(
        (
            item
            for item in streams
            if isinstance(item, dict) and item.get("codec_type") == "video"
        ),
        None,
    )
    if stream is None:
        raise ValueError("ffprobe returned no video stream")
    audio_stream = next(
        (
            item
            for item in streams
            if isinstance(item, dict) and item.get("codec_type") == "audio"
        ),
        None,
    )
    fps = _parse_rate(stream.get("avg_frame_rate"))
    duration = float(data.get("format", {}).get("duration") or 0)
    raw_frame_count = stream.get("nb_frames")
    frame_count = (
        int(raw_frame_count)
        if isinstance(raw_frame_count, str) and raw_frame_count.isdigit()
        else max(1, round(duration * fps))
    )
    if duration <= 0 or fps <= 0 or frame_count <= 0:
        raise ValueError("video metadata must contain positive duration, fps and frames")
    video_duration = float(stream.get("duration") or duration)
    audio_duration = (
        float(audio_stream.get("duration") or duration)
        if audio_stream is not None
        else None
    )
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "fps": round(fps, 6),
        "frame_count": frame_count,
        "duration": round(duration, 6),
        "codec": stream.get("codec_name"),
        "pixel_format": stream.get("pix_fmt"),
        "audio_present": audio_stream is not None,
        "audio_codec": audio_stream.get("codec_name") if audio_stream else None,
        "audio_sample_rate": (
            int(audio_stream["sample_rate"])
            if audio_stream and str(audio_stream.get("sample_rate", "")).isdigit()
            else None
        ),
        "audio_channels": (
            int(audio_stream["channels"])
            if audio_stream and audio_stream.get("channels") is not None
            else None
        ),
        "audio_duration": round(audio_duration, 6) if audio_duration else None,
        "audio_video_duration_delta": (
            round(abs(audio_duration - video_duration), 6)
            if audio_duration is not None
            else None
        ),
    }


def _extract_frame(
    video_path: Path,
    frame_path: Path,
    *,
    timestamp: float,
    ffmpeg: str,
) -> None:
    result = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(video_path),
            "-ss",
            f"{timestamp:.6f}",
            "-frames:v",
            "1",
            "-update",
            "1",
            str(frame_path),
        ],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0 or not frame_path.is_file():
        raise RuntimeError(f"ffmpeg frame extraction failed:\n{result.stderr[-1200:]}")


def _build_contact_sheet(
    items: list[tuple[str, Image.Image]],
    output_path: Path,
) -> None:
    columns = 3
    thumb_width = 320
    thumb_height = 568
    label_height = 42
    rows = (len(items) + columns - 1) // columns
    sheet = Image.new(
        "RGB",
        (columns * thumb_width, rows * (thumb_height + label_height)),
        "black",
    )
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=18)
    for item_index, (label, image) in enumerate(items):
        column = item_index % columns
        row = item_index // columns
        fitted = _fit_image(image, thumb_width, thumb_height)
        x = column * thumb_width
        y = row * (thumb_height + label_height)
        sheet.paste(fitted, (x, y))
        draw.text((x + 10, y + thumb_height + 10), label, fill="white", font=font)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path)


def _fit_image(image: Image.Image, width: int, height: int) -> Image.Image:
    result = Image.new("RGB", (width, height), "#181818")
    thumbnail = image.copy()
    thumbnail.thumbnail((width, height), Image.Resampling.LANCZOS)
    x = (width - thumbnail.width) // 2
    y = (height - thumbnail.height) // 2
    result.paste(thumbnail, (x, y))
    return result


def _amplified_difference(left: Image.Image, right: Image.Image) -> Image.Image:
    right_resized = right.resize(left.size, Image.Resampling.LANCZOS)
    difference = ImageChops.difference(left, right_resized)
    return difference.point(lambda value: min(255, value * 4))


def _difference_metrics(left: Image.Image, right: Image.Image) -> tuple[float, float]:
    right_resized = right.resize(left.size, Image.Resampling.LANCZOS)
    difference = ImageChops.difference(left, right_resized).convert("RGB")
    pixels = list(difference.getdata())
    if not pixels:
        return 0.0, 0.0
    mean = sum(sum(pixel) for pixel in pixels) / (len(pixels) * 3)
    active = sum(max(pixel) >= 36 for pixel in pixels) / len(pixels)
    return mean, active


def _region_motion_metrics(
    images: list[Image.Image],
    rect: tuple[int, int, int, int] | None,
) -> dict[str, object]:
    if rect is None:
        return {
            "status": "not_configured",
            "rect": None,
        }
    if not images:
        raise ValueError("mouth motion requires at least one image")
    x, y, width, height = rect
    image_width, image_height = images[0].size
    if x < 0 or y < 0 or x + width > image_width or y + height > image_height:
        raise ValueError("mouth_region must fit inside the video frame")
    crops = [
        image.crop((x, y, x + width, y + height))
        for image in images
    ]
    differences = [
        _difference_metrics(crops[index - 1], crops[index])
        for index in range(1, len(crops))
    ]
    max_mean = max((item[0] for item in differences), default=0.0)
    max_active = max((item[1] for item in differences), default=0.0)
    return {
        "status": "measured",
        "rect": list(rect),
        "max_mean_frame_difference": round(max_mean, 4),
        "max_active_pixel_ratio": round(max_active, 6),
    }


def _automatic_checks(
    metadata: dict[str, object],
    acceptance_checks: object,
    mouth_metrics: dict[str, object],
) -> dict[str, dict[str, object]]:
    checks = (
        set(acceptance_checks)
        if isinstance(acceptance_checks, list)
        else set()
    )
    audio_required = "audio_track_presence" in checks
    audio_present = metadata.get("audio_present") is True
    duration_delta = metadata.get("audio_video_duration_delta")
    duration_match = (
        isinstance(duration_delta, int | float) and duration_delta <= 0.2
    )
    mouth_required = "mouth_motion_presence" in checks
    mouth_measured = mouth_metrics.get("status") == "measured"
    mouth_motion = (
        mouth_measured
        and float(mouth_metrics.get("max_mean_frame_difference") or 0) >= 0.5
        and float(mouth_metrics.get("max_active_pixel_ratio") or 0) >= 0.0005
    )
    return {
        "technical_metadata": {
            "status": "passed",
            "details": "ffprobe returned positive video metadata",
        },
        "audio_track_presence": {
            "status": (
                "passed"
                if audio_required and audio_present
                else "failed"
                if audio_required
                else "not_required"
            ),
            "details": f"audio_present={audio_present}",
        },
        "audio_duration_match": {
            "status": (
                "passed"
                if audio_required and audio_present and duration_match
                else "failed"
                if audio_required
                else "not_required"
            ),
            "details": f"duration_delta={duration_delta}",
        },
        "mouth_motion_presence": {
            "status": (
                "passed"
                if mouth_required and mouth_motion
                else "failed"
                if mouth_required
                else "not_required"
            ),
            "details": mouth_metrics,
        },
    }


def _sample_indices(frame_count: int, sample_count: int) -> list[int]:
    if frame_count <= 0:
        raise ValueError("frame_count must be positive")
    if sample_count <= 1:
        raise ValueError("sample_count must be greater than one")
    last = frame_count - 1
    return sorted(
        {
            round(last * index / (sample_count - 1))
            for index in range(sample_count)
        }
    )


def _load_route_context(
    plan_report_path: Path | None,
    shot_id: str | None,
) -> dict[str, object]:
    if plan_report_path is None or shot_id is None:
        return {}
    data = json.loads(plan_report_path.read_text(encoding="utf-8"))
    if data.get("template") != "video_control_plan_report/v1":
        raise ValueError("plan_report must be video_control_plan_report/v1")
    routes = data.get("routes", [])
    route = next(
        (
            item
            for item in routes
            if isinstance(item, dict) and item.get("id") == shot_id
        ),
        None,
    )
    if route is None:
        raise ValueError(f"shot_id not found in plan report: {shot_id}")
    return route


def _load_control_context(control_report_path: Path | None) -> dict[str, object]:
    if control_report_path is None:
        return {
            "status": "not_provided",
            "passed": None,
        }
    data = json.loads(control_report_path.read_text(encoding="utf-8"))
    return {
        "status": "passed" if data.get("passed") is True else "failed",
        "passed": data.get("passed"),
        "report_path": str(control_report_path),
        "issues": data.get("issues", []),
    }


def _parse_rate(value: object) -> float:
    if not isinstance(value, str) or "/" not in value:
        raise ValueError("invalid ffprobe frame rate")
    numerator, denominator = value.split("/", 1)
    denominator_value = float(denominator)
    if denominator_value == 0:
        raise ValueError("invalid zero frame-rate denominator")
    return float(numerator) / denominator_value


def _required_string(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _optional_string(data: dict[str, object], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _resolve_path(manifest_path: Path, raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else (manifest_path.parent / path).resolve()


def _required_path(
    manifest_path: Path,
    data: dict[str, object],
    key: str,
) -> Path:
    return _resolve_path(manifest_path, _required_string(data, key))


def _optional_path(
    manifest_path: Path,
    data: dict[str, object],
    key: str,
) -> Path | None:
    raw = _optional_string(data, key)
    return _resolve_path(manifest_path, raw) if raw is not None else None


def _bounded_int(
    data: dict[str, object],
    key: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    value = data.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{key} must be an integer")
    if value < minimum or value > maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}")
    return value


def _optional_rect(
    data: dict[str, object],
    key: str,
) -> tuple[int, int, int, int] | None:
    raw = data.get(key)
    if raw is None:
        return None
    if not isinstance(raw, list) or len(raw) != 4:
        raise ValueError(f"{key} must contain [x, y, width, height]")
    values = tuple(int(value) for value in raw)
    if values[2] <= 0 or values[3] <= 0:
        raise ValueError(f"{key} width and height must be positive")
    return values
