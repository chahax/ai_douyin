"""Manifest-driven post-processing and acceptance for controlled AI video."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from src.content_factory.video_appearance_lock import lock_video_appearance
from src.content_factory.video_control_gate import VideoControlGate
from src.content_factory.video_control_policy import (
    VideoControlRecommendation,
    VideoShotIntent,
    recommend_video_control,
)


INTERPOLATION_MODES = {"none", "minterpolate"}


@dataclass(frozen=True, slots=True)
class VideoRecipeOutput:
    path: Path
    width: int
    height: int
    fps: float
    crf: int = 18
    preset: str = "slow"


@dataclass(frozen=True, slots=True)
class VideoRecipe:
    recipe_id: str
    manifest_path: Path
    generated_video: Path
    reference_image: Path
    subject_mask: Path | None
    intent: VideoShotIntent
    recommendation: VideoControlRecommendation
    output: VideoRecipeOutput
    appearance_lock: bool
    motion_gain: float
    interpolation: str
    gate_mode: str
    gate_regions: dict[str, dict[str, object]]

    @classmethod
    def load(cls, manifest_path: str | Path) -> "VideoRecipe":
        path = Path(manifest_path).resolve()
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("template") != "video_recipe/v1":
            raise ValueError("template must be video_recipe/v1")

        recipe_id = _required_string(data, "id")
        intent = VideoShotIntent.from_dict(data.get("intent"))
        recommendation = recommend_video_control(intent)

        raw_inputs = _required_object(data, "inputs")
        generated_video = _resolve_path(
            path,
            _required_string(raw_inputs, "generated_video"),
        )
        reference_image = _resolve_path(
            path,
            _required_string(raw_inputs, "reference_image"),
        )
        raw_mask = raw_inputs.get("subject_mask")
        subject_mask = (
            _resolve_path(path, raw_mask)
            if isinstance(raw_mask, str) and raw_mask.strip()
            else None
        )

        raw_output = _required_object(data, "output")
        output = VideoRecipeOutput(
            path=_resolve_path(path, _required_string(raw_output, "path")),
            width=_positive_even_int(raw_output, "width"),
            height=_positive_even_int(raw_output, "height"),
            fps=_positive_float(raw_output, "fps"),
            crf=_bounded_int(raw_output, "crf", default=18, minimum=0, maximum=51),
            preset=str(raw_output.get("preset", "slow")).strip() or "slow",
        )

        raw_appearance = data.get("appearance_lock", {})
        if not isinstance(raw_appearance, dict):
            raise ValueError("appearance_lock must be an object")
        appearance_lock = _boolean(raw_appearance, "enabled", True)
        motion_gain = _non_negative_float(raw_appearance, "motion_gain", 0.55)
        if appearance_lock and subject_mask is None:
            raise ValueError("inputs.subject_mask is required when appearance_lock is enabled")

        raw_smoothing = data.get("smoothing", {})
        if not isinstance(raw_smoothing, dict):
            raise ValueError("smoothing must be an object")
        interpolation = str(raw_smoothing.get("interpolation", "minterpolate")).strip()
        if interpolation not in INTERPOLATION_MODES:
            choices = ", ".join(sorted(INTERPOLATION_MODES))
            raise ValueError(f"smoothing.interpolation must be one of: {choices}")

        raw_gate = _required_object(data, "gate")
        gate_mode = str(raw_gate.get("mode") or recommendation.mode).strip()
        if gate_mode != recommendation.mode:
            raise ValueError(
                f"gate.mode {gate_mode} conflicts with intent recommendation "
                f"{recommendation.mode}"
            )
        raw_regions = raw_gate.get("regions", {})
        if not isinstance(raw_regions, dict):
            raise ValueError("gate.regions must be an object")
        gate_regions = _normalize_regions(raw_regions, output.width, output.height)
        if gate_mode in {"subject_only", "replacement_relight"} and not gate_regions:
            raise ValueError(f"gate.regions is required for {gate_mode}")

        return cls(
            recipe_id=recipe_id,
            manifest_path=path,
            generated_video=generated_video,
            reference_image=reference_image,
            subject_mask=subject_mask,
            intent=intent,
            recommendation=recommendation,
            output=output,
            appearance_lock=appearance_lock,
            motion_gain=motion_gain,
            interpolation=interpolation,
            gate_mode=gate_mode,
            gate_regions=gate_regions,
        )

    def validate_assets(self) -> None:
        required = [self.generated_video, self.reference_image]
        if self.subject_mask is not None:
            required.append(self.subject_mask)
        missing = [path for path in required if not path.is_file()]
        if missing:
            names = ", ".join(str(path) for path in missing)
            raise FileNotFoundError(f"recipe assets missing: {names}")

    def control_manifest(self) -> dict[str, object]:
        return {
            "template": "video_control/v1",
            "video_path": str(self.output.path),
            "reference_image": str(self.reference_image),
            "mode": self.gate_mode,
            "regions": self.gate_regions,
        }

    def plan(self) -> dict[str, object]:
        return {
            "template": "video_recipe_plan/v1",
            "id": self.recipe_id,
            "generated_video": str(self.generated_video),
            "reference_image": str(self.reference_image),
            "subject_mask": str(self.subject_mask) if self.subject_mask else None,
            "output": {
                "path": str(self.output.path),
                "width": self.output.width,
                "height": self.output.height,
                "fps": self.output.fps,
                "crf": self.output.crf,
                "preset": self.output.preset,
            },
            "appearance_lock": {
                "enabled": self.appearance_lock,
                "motion_gain": self.motion_gain,
            },
            "smoothing": {"interpolation": self.interpolation},
            "gate_mode": self.gate_mode,
            "recommendation": self.recommendation.to_dict(),
        }


def run_video_recipe(
    manifest_path: str | Path,
    *,
    report_path: str | Path | None = None,
    dry_run: bool = False,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
) -> dict[str, object]:
    recipe = VideoRecipe.load(manifest_path)
    recipe.validate_assets()
    if dry_run:
        return recipe.plan()

    output_path = recipe.output.path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    steps: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(
        prefix=f"{recipe.recipe_id}_",
        dir=output_path.parent,
    ) as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        current_video = recipe.generated_video
        if recipe.appearance_lock:
            locked_path = temp_dir / "appearance_locked.mp4"
            lock_video_appearance(
                current_video,
                recipe.reference_image,
                recipe.subject_mask,
                locked_path,
                motion_gain=recipe.motion_gain,
                ffmpeg=ffmpeg,
                ffprobe=ffprobe,
            )
            current_video = locked_path
            steps.append(
                {
                    "name": "reference_appearance_lock",
                    "motion_gain": recipe.motion_gain,
                }
            )

        _render_output(current_video, recipe.output, recipe.interpolation, ffmpeg)
        steps.append(
            {
                "name": "encode_output",
                "width": recipe.output.width,
                "height": recipe.output.height,
                "fps": recipe.output.fps,
                "interpolation": recipe.interpolation,
            }
        )

    control_manifest_path = output_path.with_suffix(".control.manifest.json")
    control_report_path = output_path.with_suffix(".control.report.json")
    control_manifest_path.write_text(
        json.dumps(recipe.control_manifest(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    control_report = VideoControlGate().inspect_manifest(
        control_manifest_path,
        control_report_path,
    )
    result = {
        "template": "video_recipe_report/v1",
        "id": recipe.recipe_id,
        "status": "accepted" if control_report.passed else "rejected",
        "output": str(output_path),
        "control_manifest": str(control_manifest_path),
        "control_report": str(control_report_path),
        "recommendation": recipe.recommendation.to_dict(),
        "steps": steps,
        "gate": {
            "passed": control_report.passed,
            "mode": control_report.mode,
            "metadata": control_report.metadata,
            "issues": [asdict(issue) for issue in control_report.issues],
        },
    }
    destination = (
        Path(report_path)
        if report_path is not None
        else output_path.with_suffix(".recipe.report.json")
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def _render_output(
    input_video: Path,
    output: VideoRecipeOutput,
    interpolation: str,
    ffmpeg: str,
) -> None:
    filters: list[str] = []
    if interpolation == "minterpolate":
        filters.append(
            "minterpolate="
            f"fps={output.fps:.8f}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1"
        )
    else:
        filters.append(f"fps={output.fps:.8f}")
    filters.append(f"scale={output.width}:{output.height}:flags=lanczos")
    executable = shutil.which(ffmpeg) or ffmpeg
    subprocess.run(
        [
            executable,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(input_video),
            "-vf",
            ",".join(filters),
            "-map",
            "0:v:0",
            "-c:v",
            "libx264",
            "-crf",
            str(output.crf),
            "-preset",
            output.preset,
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output.path),
        ],
        check=True,
    )


def _normalize_regions(
    raw_regions: dict[str, object],
    width: int,
    height: int,
) -> dict[str, dict[str, object]]:
    normalized: dict[str, dict[str, object]] = {}
    for name, raw_value in raw_regions.items():
        if not isinstance(raw_value, dict):
            raise ValueError(f"gate.regions.{name} must be an object")
        value = dict(raw_value)
        raw_rect = value.pop("rect_normalized", None)
        if raw_rect is not None:
            if "rect" in value:
                raise ValueError(
                    f"gate.regions.{name} cannot define rect and rect_normalized"
                )
            rect = _normalized_rect(name, raw_rect, width, height)
            value["rect"] = rect
        elif "rect" in value:
            value["rect"] = _pixel_rect(name, value["rect"], width, height)
        else:
            raise ValueError(
                f"gate.regions.{name} requires rect or rect_normalized"
            )
        normalized[name] = value
    return normalized


def _normalized_rect(
    name: str,
    raw_rect: object,
    width: int,
    height: int,
) -> list[int]:
    if not isinstance(raw_rect, list) or len(raw_rect) != 4:
        raise ValueError(
            f"gate.regions.{name}.rect_normalized must contain [x, y, width, height]"
        )
    x, y, rect_width, rect_height = (float(value) for value in raw_rect)
    if min(x, y, rect_width, rect_height) < 0:
        raise ValueError(f"gate.regions.{name}.rect_normalized cannot be negative")
    if rect_width <= 0 or rect_height <= 0 or x + rect_width > 1 or y + rect_height > 1:
        raise ValueError(
            f"gate.regions.{name}.rect_normalized must fit inside 0..1"
        )
    left = round(x * width)
    top = round(y * height)
    right = round((x + rect_width) * width)
    bottom = round((y + rect_height) * height)
    return [left, top, max(1, right - left), max(1, bottom - top)]


def _pixel_rect(
    name: str,
    raw_rect: object,
    width: int,
    height: int,
) -> list[int]:
    if not isinstance(raw_rect, list) or len(raw_rect) != 4:
        raise ValueError(
            f"gate.regions.{name}.rect must contain [x, y, width, height]"
        )
    x, y, rect_width, rect_height = (int(value) for value in raw_rect)
    if min(x, y) < 0 or rect_width <= 0 or rect_height <= 0:
        raise ValueError(f"gate.regions.{name}.rect is invalid")
    if x + rect_width > width or y + rect_height > height:
        raise ValueError(f"gate.regions.{name}.rect exceeds output dimensions")
    return [x, y, rect_width, rect_height]


def _resolve_path(manifest_path: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    return path.resolve() if path.is_absolute() else (manifest_path.parent / path).resolve()


def _required_object(data: dict[str, object], key: str) -> dict[str, object]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object")
    return value


def _required_string(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required")
    return value.strip()


def _positive_even_int(data: dict[str, object], key: str) -> int:
    value = int(data.get(key, 0))
    if value <= 0 or value % 2:
        raise ValueError(f"{key} must be a positive even integer")
    return value


def _bounded_int(
    data: dict[str, object],
    key: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    value = int(data.get(key, default))
    if not minimum <= value <= maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}")
    return value


def _positive_float(data: dict[str, object], key: str) -> float:
    value = float(data.get(key, 0))
    if value <= 0:
        raise ValueError(f"{key} must be positive")
    return value


def _non_negative_float(
    data: dict[str, object],
    key: str,
    default: float,
) -> float:
    value = float(data.get(key, default))
    if value < 0:
        raise ValueError(f"{key} cannot be negative")
    return value


def _boolean(data: dict[str, object], key: str, default: bool) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value
