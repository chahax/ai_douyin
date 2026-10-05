"""Deterministic top / middle / bottom video composition from a JSON manifest."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from src.content_factory.video_quality import VideoQualityProfile, resolve_quality_profile
from src.content_factory.video_quality_gate import VideoQualityGate
from src.shared.logger import logger


PanelMotion = Literal["static", "generated"]
PANEL_NAMES = ("top", "middle", "bottom")
STATIC_IMAGE_EXTENSIONS = {".bmp", ".jpeg", ".jpg", ".png", ".webp"}


@dataclass(frozen=True, slots=True)
class PanelSpec:
    source: str | None
    motion: PanelMotion

    @classmethod
    def from_dict(cls, value: object, panel_name: str) -> "PanelSpec":
        if not isinstance(value, dict):
            raise ValueError(f"panels.{panel_name} must be an object")
        source = value.get("source")
        if source is not None and not isinstance(source, str):
            raise ValueError(f"panels.{panel_name}.source must be a string or null")
        motion = value.get("motion")
        if motion not in {"static", "generated"}:
            raise ValueError(f"panels.{panel_name}.motion must be static or generated")
        return cls(source=source, motion=motion)


@dataclass(frozen=True, slots=True)
class TriplePanelManifest:
    """Portable source-of-truth for a three-slot video composition."""

    duration_seconds: float
    top: PanelSpec
    middle: PanelSpec
    bottom: PanelSpec
    audio_path: str | None = None
    quality_profile: str = "publish"
    template: str = "triple_panel/v1"

    @classmethod
    def load(cls, manifest_path: str | Path) -> "TriplePanelManifest":
        path = Path(manifest_path)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Unable to read triple panel manifest: {path}: {exc}") from exc
        manifest = cls.from_dict(value)
        return manifest.resolve_paths(path.parent)

    @classmethod
    def from_dict(cls, value: object) -> "TriplePanelManifest":
        if not isinstance(value, dict):
            raise ValueError("Triple panel manifest must be an object")
        if value.get("template") != "triple_panel/v1":
            raise ValueError("template must be triple_panel/v1")

        duration = value.get("duration_seconds")
        try:
            duration_seconds = float(duration)
        except (TypeError, ValueError) as exc:
            raise ValueError("duration_seconds must be a positive number") from exc
        if duration_seconds <= 0:
            raise ValueError("duration_seconds must be a positive number")

        panels = value.get("panels")
        if not isinstance(panels, dict):
            raise ValueError("panels must be an object")
        top = PanelSpec.from_dict(panels.get("top"), "top")
        middle = PanelSpec.from_dict(panels.get("middle"), "middle")
        bottom = PanelSpec.from_dict(panels.get("bottom"), "bottom")
        if middle.motion != "generated" or not middle.source:
            raise ValueError("panels.middle must declare a generated source video")
        if top.motion != "static" or bottom.motion != "static":
            raise ValueError("top and bottom panels must use static motion")
        if bool(top.source) != bool(bottom.source):
            raise ValueError("top and bottom sources must either both be provided or both be omitted")

        audio_path = value.get("audio_path")
        if audio_path is not None and not isinstance(audio_path, str):
            raise ValueError("audio_path must be a string or null")
        quality_profile = value.get("quality_profile", "publish")
        if not isinstance(quality_profile, str):
            raise ValueError("quality_profile must be a string")
        resolve_quality_profile(quality_profile)
        return cls(
            duration_seconds=duration_seconds,
            top=top,
            middle=middle,
            bottom=bottom,
            audio_path=audio_path,
            quality_profile=quality_profile,
        )

    def resolve_paths(self, parent: Path) -> "TriplePanelManifest":
        def resolve(source: str | None) -> str | None:
            if not source:
                return source
            candidate = Path(source)
            return str(candidate if candidate.is_absolute() else parent / candidate)

        return TriplePanelManifest(
            duration_seconds=self.duration_seconds,
            top=PanelSpec(resolve(self.top.source), self.top.motion),
            middle=PanelSpec(resolve(self.middle.source), self.middle.motion),
            bottom=PanelSpec(resolve(self.bottom.source), self.bottom.motion),
            audio_path=resolve(self.audio_path),
            quality_profile=self.quality_profile,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "template": self.template,
            "duration_seconds": self.duration_seconds,
            "quality_profile": self.quality_profile,
            "audio_path": self.audio_path,
            "panels": {
                "top": asdict(self.top),
                "middle": asdict(self.middle),
                "bottom": asdict(self.bottom),
            },
        }


def triple_panel_regions(profile: str | VideoQualityProfile) -> dict[str, tuple[int, int, int, int]]:
    """Return x, y, width, height for the three output slots."""
    resolved = resolve_quality_profile(profile)
    gap = max(2, round(resolved.width / 45))
    panel_height = (resolved.height - 2 * gap) // 3
    remaining_height = resolved.height - panel_height * 3 - gap * 2
    return {
        "top": (0, 0, resolved.width, panel_height),
        "middle": (0, panel_height + gap, resolved.width, panel_height + remaining_height),
        "bottom": (0, 2 * (panel_height + gap) + remaining_height, resolved.width, panel_height),
    }


def _layout_for_manifest(
    manifest: TriplePanelManifest,
    profile: VideoQualityProfile,
) -> tuple[str, dict[str, tuple[int, int, int, int]]]:
    if not manifest.top.source and not manifest.bottom.source:
        return "single_scene", {"middle": (0, 0, profile.width, profile.height)}
    return "triple_panel", triple_panel_regions(profile)


def compose_triple_panel_video(
    manifest_path: str | Path,
    output_path: str | Path,
) -> str:
    """Compose a manifest into an H.264 video and write manifest/quality artifacts."""
    manifest = TriplePanelManifest.load(manifest_path)
    profile = resolve_quality_profile(manifest.quality_profile)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    pending_output = output.with_name(f"{output.stem}.pending{output.suffix}")
    pending_output.unlink(missing_ok=True)
    _validate_sources(manifest)

    layout_mode, regions = _layout_for_manifest(manifest, profile)
    command = ["ffmpeg", "-y"]
    if layout_mode == "single_scene":
        command.extend(["-stream_loop", "-1", "-i", manifest.middle.source])
        audio_input_index = 1
        filters = [
            (
                f"[0:v]scale={profile.width}:{profile.height}:force_original_aspect_ratio=increase:flags=lanczos,"
                f"crop={profile.width}:{profile.height},fps={profile.fps},setsar=1,setpts=PTS-STARTPTS,format=yuv420p[outv]"
            )
        ]
        panel_motion_policy = {"middle": "dynamic"}
    else:
        for name, spec in zip(PANEL_NAMES, (manifest.top, manifest.middle, manifest.bottom)):
            if name == "middle":
                command.extend(["-stream_loop", "-1", "-i", spec.source])
            else:
                command.extend(["-loop", "1", "-framerate", str(profile.fps), "-i", spec.source])
        audio_input_index = 3
        filters = [
            (
                f"[0:v]scale={regions['top'][2]}:{regions['top'][3]}:force_original_aspect_ratio=increase:flags=lanczos,"
                f"crop={regions['top'][2]}:{regions['top'][3]},fps={profile.fps},setsar=1,setpts=PTS-STARTPTS[top]"
            ),
            (
                f"[1:v]scale={regions['middle'][2]}:{regions['middle'][3]}:force_original_aspect_ratio=increase:flags=lanczos,"
                f"crop={regions['middle'][2]}:{regions['middle'][3]},fps={profile.fps},setsar=1,setpts=PTS-STARTPTS[middle]"
            ),
            (
                f"[2:v]scale={regions['bottom'][2]}:{regions['bottom'][3]}:force_original_aspect_ratio=increase:flags=lanczos,"
                f"crop={regions['bottom'][2]}:{regions['bottom'][3]},fps={profile.fps},setsar=1,setpts=PTS-STARTPTS[bottom]"
            ),
            f"color=c=#0b0b0b:s={profile.width}x{profile.height}:r={profile.fps}:d={manifest.duration_seconds}[canvas]",
            "[canvas][top]overlay=0:0[with_top]",
            f"[with_top][middle]overlay=0:{regions['middle'][1]}[with_middle]",
            f"[with_middle][bottom]overlay=0:{regions['bottom'][1]},format=yuv420p[outv]",
        ]
        panel_motion_policy = {"top": "static", "middle": "dynamic", "bottom": "static"}

    if manifest.audio_path:
        command.extend(["-i", manifest.audio_path])
    else:
        command.extend(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"])
    audio_filter = f"apad=pad_dur={manifest.duration_seconds},atrim=duration={manifest.duration_seconds},asetpts=PTS-STARTPTS"
    command.extend([
        "-filter_complex", ";".join(filters),
        "-map", "[outv]",
        "-map", f"{audio_input_index}:a",
        "-af", audio_filter,
        "-t", str(manifest.duration_seconds),
        *profile.video_encoding_args(),
        *profile.audio_encoding_args(),
        *profile.muxing_args(),
        str(pending_output),
    ])

    try:
        _run_ffmpeg(command)
        report = VideoQualityGate(sample_count=5).inspect(
            pending_output,
            profile,
            expected_duration=manifest.duration_seconds,
            panel_motion_policy=panel_motion_policy,
            panel_regions=regions,
        )
        report.metadata["layout_mode"] = layout_mode
        report.path = str(output)
        report.write_json(output.with_suffix(".quality.json"))
        if not report.passed:
            details = "; ".join(f"{issue.code}: {issue.message}" for issue in report.issues)
            raise RuntimeError(f"Triple panel quality gate failed: {details}")
        pending_output.replace(output)
        _write_manifest_artifact(manifest, output)
        return str(output)
    finally:
        pending_output.unlink(missing_ok=True)


def _validate_sources(manifest: TriplePanelManifest) -> None:
    for name, spec in zip(PANEL_NAMES, (manifest.top, manifest.middle, manifest.bottom)):
        if not spec.source:
            continue
        source = Path(spec.source)
        if not source.is_file():
            raise ValueError(f"panels.{name}.source does not exist: {source}")
        if name == "middle" and source.suffix.lower() in STATIC_IMAGE_EXTENSIONS:
            raise ValueError("panels.middle.source must be a video, not a static image")
        if name != "middle" and source.suffix.lower() not in STATIC_IMAGE_EXTENSIONS:
            raise ValueError(f"panels.{name}.source must be a static image")
    if manifest.audio_path and not Path(manifest.audio_path).is_file():
        raise ValueError(f"audio_path does not exist: {manifest.audio_path}")


def _write_manifest_artifact(manifest: TriplePanelManifest, output: Path) -> None:
    output.with_suffix(".manifest.json").write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _run_ffmpeg(command: list[str]) -> None:
    result = subprocess.run(
        command,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
    )
    if result.returncode == 0:
        return
    logger.error("[TriplePanel] FFmpeg failed: %s", result.stderr[-2000:])
    raise RuntimeError("Triple panel FFmpeg composition failed")
