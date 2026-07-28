"""Story-level assembly for narrated and multi-character generated videos."""

from __future__ import annotations

import json
import hashlib
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.content_factory.tts_engine import TTSEngine
from src.content_factory.video_control_gate import (
    VideoControlGate,
    VideoControlIssue,
    VideoControlManifest,
    VideoControlReport,
)
from src.content_factory.video_quality import VideoQualityProfile, resolve_quality_profile
from src.content_factory.video_quality_gate import VideoQualityGate


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}


@dataclass(frozen=True, slots=True)
class StoryCastMember:
    """Voice configuration for a narrator or named character."""

    speaker_id: str
    name: str
    voice: str = ""
    tts_provider: str = "edge"

    @classmethod
    def from_dict(cls, speaker_id: str, value: object) -> "StoryCastMember":
        if not isinstance(value, dict):
            raise ValueError(f"cast.{speaker_id} must be an object")
        name = value.get("name")
        voice = value.get("voice", "")
        provider = value.get("tts_provider", "edge")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"cast.{speaker_id}.name must be a non-empty string")
        if not isinstance(voice, str) or not isinstance(provider, str):
            raise ValueError(f"cast.{speaker_id} voice and tts_provider must be strings")
        if provider not in {"edge", "gpt_sovits"}:
            raise ValueError(f"cast.{speaker_id}.tts_provider must be edge or gpt_sovits")
        return cls(
            speaker_id=speaker_id,
            name=name.strip(),
            voice=voice.strip(),
            tts_provider=provider,
        )


@dataclass(frozen=True, slots=True)
class StoryLine:
    speaker: str
    text: str = ""
    audio_path: str | None = None
    pause_after_seconds: float = 0.0
    rate: str = "+0%"
    volume: str = "+0%"
    pitch: str = "+0Hz"

    @classmethod
    def from_dict(cls, value: object, *, scene_id: str, line_index: int) -> "StoryLine":
        if not isinstance(value, dict):
            raise ValueError(f"scenes.{scene_id}.lines[{line_index}] must be an object")
        speaker = value.get("speaker")
        text = value.get("text", "")
        audio_path = value.get("audio_path")
        pause = value.get("pause_after_seconds", 0.0)
        rate = value.get("rate", "+0%")
        volume = value.get("volume", "+0%")
        pitch = value.get("pitch", "+0Hz")
        if not isinstance(speaker, str) or not speaker.strip():
            raise ValueError(f"scenes.{scene_id}.lines[{line_index}].speaker is required")
        if not isinstance(text, str):
            raise ValueError(f"scenes.{scene_id}.lines[{line_index}].text must be a string")
        if audio_path is not None and not isinstance(audio_path, str):
            raise ValueError(f"scenes.{scene_id}.lines[{line_index}].audio_path must be a string or null")
        if not isinstance(rate, str) or not re.fullmatch(r"[+-]\d+%", rate):
            raise ValueError(f"scenes.{scene_id}.lines[{line_index}].rate must look like +5% or -8%")
        if not isinstance(volume, str) or not re.fullmatch(r"[+-]\d+%", volume):
            raise ValueError(f"scenes.{scene_id}.lines[{line_index}].volume must look like +5% or -8%")
        if not isinstance(pitch, str) or not re.fullmatch(r"[+-]\d+Hz", pitch):
            raise ValueError(f"scenes.{scene_id}.lines[{line_index}].pitch must look like +2Hz or -3Hz")
        try:
            pause_seconds = float(pause)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"scenes.{scene_id}.lines[{line_index}].pause_after_seconds must be a number") from exc
        if pause_seconds < 0:
            raise ValueError(f"scenes.{scene_id}.lines[{line_index}].pause_after_seconds cannot be negative")
        if not text.strip() and not audio_path:
            raise ValueError(f"scenes.{scene_id}.lines[{line_index}] requires text or audio_path")
        return cls(
            speaker=speaker.strip(),
            text=text.strip(),
            audio_path=audio_path.strip() if isinstance(audio_path, str) and audio_path.strip() else None,
            pause_after_seconds=pause_seconds,
            rate=rate,
            volume=volume,
            pitch=pitch,
        )


@dataclass(frozen=True, slots=True)
class StoryScene:
    scene_id: str
    video_path: str
    lines: tuple[StoryLine, ...]
    control_manifest: str | None = None
    control_review: str | None = None

    @classmethod
    def from_dict(cls, value: object, *, scene_index: int) -> "StoryScene":
        if not isinstance(value, dict):
            raise ValueError(f"scenes[{scene_index}] must be an object")
        scene_id = value.get("id")
        video_path = value.get("video_path")
        lines = value.get("lines")
        control_manifest = value.get("control_manifest")
        control_review = value.get("control_review")
        if not isinstance(scene_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", scene_id):
            raise ValueError("scene id must use letters, numbers, underscores, or hyphens")
        if not isinstance(video_path, str) or not video_path.strip():
            raise ValueError(f"scenes.{scene_id}.video_path is required")
        if not isinstance(lines, list) or not lines:
            raise ValueError(f"scenes.{scene_id}.lines must be a non-empty list")
        if control_manifest is not None and not isinstance(control_manifest, str):
            raise ValueError(f"scenes.{scene_id}.control_manifest must be a string or null")
        if control_review is not None and not isinstance(control_review, str):
            raise ValueError(f"scenes.{scene_id}.control_review must be a string or null")
        return cls(
            scene_id=scene_id,
            video_path=video_path.strip(),
            lines=tuple(StoryLine.from_dict(item, scene_id=scene_id, line_index=index) for index, item in enumerate(lines)),
            control_manifest=(
                control_manifest.strip()
                if isinstance(control_manifest, str) and control_manifest.strip()
                else None
            ),
            control_review=(
                control_review.strip()
                if isinstance(control_review, str) and control_review.strip()
                else None
            ),
        )


@dataclass(frozen=True, slots=True)
class StoryVideoManifest:
    title: str
    cast: dict[str, StoryCastMember]
    scenes: tuple[StoryScene, ...]
    quality_profile: str = "publish"
    video_fit_mode: str = "loop"
    template: str = "story_video/v1"
    responsibilities: dict[str, str] = field(default_factory=dict)
    require_scene_control: bool = False
    allow_user_overrides: bool = False

    @classmethod
    def load(cls, manifest_path: str | Path) -> "StoryVideoManifest":
        path = Path(manifest_path)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid story manifest JSON: {exc}") from exc
        return cls.from_dict(value).resolve_paths(path.parent)

    @classmethod
    def from_dict(cls, value: object) -> "StoryVideoManifest":
        if not isinstance(value, dict):
            raise ValueError("story manifest must be an object")
        if value.get("template") != "story_video/v1":
            raise ValueError("template must be story_video/v1")
        title = value.get("title", "")
        cast_value = value.get("cast")
        scenes_value = value.get("scenes")
        quality_profile = value.get("quality_profile", "publish")
        video_fit_mode = value.get("video_fit_mode", "loop")
        responsibilities = value.get("responsibilities", {})
        require_scene_control = value.get("require_scene_control", False)
        allow_user_overrides = value.get("allow_user_overrides", False)
        if not isinstance(title, str):
            raise ValueError("title must be a string")
        if not isinstance(cast_value, dict) or not cast_value:
            raise ValueError("cast must be a non-empty object")
        if not isinstance(scenes_value, list) or not scenes_value:
            raise ValueError("scenes must be a non-empty list")
        if not isinstance(quality_profile, str):
            raise ValueError("quality_profile must be a string")
        if video_fit_mode not in {"loop", "hold_last"}:
            raise ValueError("video_fit_mode must be loop or hold_last")
        if not isinstance(responsibilities, dict) or not all(
            isinstance(key, str) and isinstance(item, str) for key, item in responsibilities.items()
        ):
            raise ValueError("responsibilities must be a string map")
        if not isinstance(require_scene_control, bool):
            raise ValueError("require_scene_control must be a boolean")
        if not isinstance(allow_user_overrides, bool):
            raise ValueError("allow_user_overrides must be a boolean")
        resolve_quality_profile(quality_profile)
        if not all(isinstance(speaker_id, str) and speaker_id.strip() for speaker_id in cast_value):
            raise ValueError("cast keys must be non-empty strings")
        cast = {speaker_id: StoryCastMember.from_dict(speaker_id, item) for speaker_id, item in cast_value.items()}
        scenes = tuple(StoryScene.from_dict(item, scene_index=index) for index, item in enumerate(scenes_value))
        duplicate_ids = {scene.scene_id for scene in scenes if sum(item.scene_id == scene.scene_id for item in scenes) > 1}
        if duplicate_ids:
            raise ValueError(f"scene ids must be unique: {', '.join(sorted(duplicate_ids))}")
        missing_speakers = sorted(
            {line.speaker for scene in scenes for line in scene.lines if line.speaker not in cast}
        )
        if missing_speakers:
            raise ValueError(f"lines reference undeclared cast members: {', '.join(missing_speakers)}")
        if require_scene_control:
            uncontrolled_scenes = [scene.scene_id for scene in scenes if not scene.control_manifest]
            if uncontrolled_scenes:
                raise ValueError(
                    f"scenes require control manifests: {', '.join(uncontrolled_scenes)}"
                )
        return cls(
            title=title.strip(),
            cast=cast,
            scenes=scenes,
            quality_profile=quality_profile,
            video_fit_mode=video_fit_mode,
            responsibilities={key: item.strip() for key, item in responsibilities.items()},
            require_scene_control=require_scene_control,
            allow_user_overrides=allow_user_overrides,
        )

    def resolve_paths(self, parent: Path) -> "StoryVideoManifest":
        def resolve(path_value: str | None) -> str | None:
            if not path_value:
                return None
            path = Path(path_value)
            return str(path if path.is_absolute() else parent / path)

        return StoryVideoManifest(
            title=self.title,
            cast=self.cast,
            scenes=tuple(
                StoryScene(
                    scene_id=scene.scene_id,
                    video_path=resolve(scene.video_path) or "",
                    control_manifest=resolve(scene.control_manifest),
                    control_review=resolve(scene.control_review),
                    lines=tuple(
                        StoryLine(
                            speaker=line.speaker,
                            text=line.text,
                            audio_path=resolve(line.audio_path),
                            pause_after_seconds=line.pause_after_seconds,
                            rate=line.rate,
                            volume=line.volume,
                            pitch=line.pitch,
                        )
                        for line in scene.lines
                    ),
                )
                for scene in self.scenes
            ),
            quality_profile=self.quality_profile,
            video_fit_mode=self.video_fit_mode,
            responsibilities=self.responsibilities,
            require_scene_control=self.require_scene_control,
            allow_user_overrides=self.allow_user_overrides,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "template": self.template,
            "title": self.title,
            "quality_profile": self.quality_profile,
            "video_fit_mode": self.video_fit_mode,
            "responsibilities": self.responsibilities,
            "require_scene_control": self.require_scene_control,
            "allow_user_overrides": self.allow_user_overrides,
            "cast": {
                speaker_id: {
                    "name": member.name,
                    "voice": member.voice,
                    "tts_provider": member.tts_provider,
                }
                for speaker_id, member in self.cast.items()
            },
            "scenes": [
                {
                    "id": scene.scene_id,
                    "video_path": scene.video_path,
                    "control_manifest": scene.control_manifest,
                    "control_review": scene.control_review,
                    "lines": [
                        {
                            "speaker": line.speaker,
                            "text": line.text,
                            "audio_path": line.audio_path,
                            "pause_after_seconds": line.pause_after_seconds,
                            "rate": line.rate,
                            "volume": line.volume,
                            "pitch": line.pitch,
                        }
                        for line in scene.lines
                    ],
                }
                for scene in self.scenes
            ],
        }


def compose_story_video(manifest_path: str | Path, output_path: str | Path) -> str:
    """Synthesize missing line audio, compose scene videos, then accept one story video."""
    manifest = StoryVideoManifest.load(manifest_path)
    profile = resolve_quality_profile(manifest.quality_profile)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    _validate_scene_assets(manifest)

    work_dir = output.parent / f"{output.stem}.story"
    audio_dir = work_dir / "audio"
    scene_dir = work_dir / "scenes"
    control_dir = work_dir / "controls"
    audio_dir.mkdir(parents=True, exist_ok=True)
    scene_dir.mkdir(parents=True, exist_ok=True)
    control_dir.mkdir(parents=True, exist_ok=True)
    _validate_scene_controls(manifest, control_dir)

    timeline: list[dict[str, object]] = []
    scene_outputs: list[Path] = []
    cursor = 0.0
    for scene_index, scene in enumerate(manifest.scenes):
        scene_audio, scene_timeline = _render_scene_audio(
            scene=scene,
            cast=manifest.cast,
            audio_dir=audio_dir,
            scene_index=scene_index,
        )
        scene_duration = _duration(scene_audio)
        if scene_duration <= 0:
            raise RuntimeError(f"scene {scene.scene_id} has invalid synthesized audio duration")
        for entry in scene_timeline:
            entry["start"] = round(cursor + float(entry["start"]), 3)
            entry["end"] = round(cursor + float(entry["end"]), 3)
            entry["scene_id"] = scene.scene_id
            timeline.append(entry)
        scene_output = scene_dir / f"{scene_index:03d}_{scene.scene_id}.mp4"
        _compose_scene(
            scene.video_path,
            scene_audio,
            scene_output,
            scene_duration,
            profile,
            manifest.video_fit_mode,
        )
        scene_outputs.append(scene_output)
        cursor += scene_duration

    pending = output.with_name(f"{output.stem}.pending{output.suffix}")
    if pending.exists():
        pending.unlink()
    _concatenate_scenes(scene_outputs, pending, profile)
    report = VideoQualityGate(sample_count=5).inspect(
        pending,
        profile,
        expected_duration=cursor,
    )
    _write_json(
        output.with_suffix(".timeline.json"),
        {
            "title": manifest.title,
            "duration_seconds": round(cursor, 3),
            "lines": timeline,
        },
    )
    _write_json(output.with_suffix(".manifest.json"), manifest.to_dict())
    if not report.passed:
        report.write_json(output.with_suffix(".quality.json"))
        pending.unlink(missing_ok=True)
        details = "; ".join(f"{issue.code}: {issue.message}" for issue in report.issues)
        raise RuntimeError(f"story video quality gate rejected output: {details}")
    pending.replace(output)
    report.path = str(output)
    report.write_json(output.with_suffix(".quality.json"))
    return str(output)


def _validate_scene_assets(manifest: StoryVideoManifest) -> None:
    for scene in manifest.scenes:
        video_path = Path(scene.video_path)
        if not video_path.is_file():
            raise FileNotFoundError(f"scene {scene.scene_id} video is missing: {video_path}")
        if video_path.suffix.lower() not in VIDEO_EXTENSIONS:
            raise ValueError(f"scene {scene.scene_id} video must be a video file: {video_path}")
        for line_index, line in enumerate(scene.lines):
            if line.audio_path and not Path(line.audio_path).is_file():
                raise FileNotFoundError(
                    f"scene {scene.scene_id} line {line_index} audio is missing: {line.audio_path}"
                )
            if not line.audio_path and not manifest.cast[line.speaker].voice and manifest.cast[line.speaker].tts_provider == "gpt_sovits":
                raise ValueError(f"cast.{line.speaker}.voice is required for gpt_sovits synthesis")


def audit_story_video_controls(
    manifest_path: str | Path,
    output_dir: str | Path,
) -> list[VideoControlReport]:
    manifest = StoryVideoManifest.load(manifest_path)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    return _validate_scene_controls(manifest, destination)


def _validate_scene_controls(
    manifest: StoryVideoManifest,
    control_dir: Path,
) -> list[VideoControlReport]:
    gate = VideoControlGate()
    reports: list[VideoControlReport] = []
    for scene in manifest.scenes:
        if not scene.control_manifest:
            continue
        control_manifest = VideoControlManifest.load(scene.control_manifest)
        if control_manifest.video_path.resolve() != Path(scene.video_path).resolve():
            raise ValueError(
                f"scene {scene.scene_id} control manifest validates a different video: "
                f"{control_manifest.video_path}"
            )
        report_path = control_dir / f"{scene.scene_id}.control.json"
        report = gate.inspect_manifest(
            scene.control_manifest,
            report_path,
        )
        if not report.passed:
            if not manifest.allow_user_overrides or not scene.control_review:
                details = "; ".join(f"{issue.code}: {issue.message}" for issue in report.issues)
                raise RuntimeError(f"scene {scene.scene_id} control gate rejected video: {details}")
            override = _load_user_control_override(scene)
            report.metadata["strict_gate_passed"] = False
            report.metadata["user_override"] = override
            report.issues = [
                VideoControlIssue(
                    code=issue.code,
                    message=issue.message,
                    severity="warning",
                )
                for issue in report.issues
            ]
            report.write_json(report_path)
        reports.append(report)
    return reports


def _load_user_control_override(scene: StoryScene) -> dict[str, object]:
    review_path = Path(scene.control_review or "")
    if not review_path.is_file():
        raise FileNotFoundError(f"scene {scene.scene_id} control review is missing: {review_path}")
    try:
        value = json.loads(review_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"scene {scene.scene_id} control review is invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"scene {scene.scene_id} control review must be an object")
    status = value.get("status")
    reason = value.get("user_override_reason")
    review_video = value.get("video_path")
    if status != "accepted_by_user_override":
        raise ValueError(f"scene {scene.scene_id} control review status is not accepted_by_user_override")
    if value.get("user_override") is not True or value.get("composition_eligible") is not True:
        raise ValueError(f"scene {scene.scene_id} control review is not composition eligible")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError(f"scene {scene.scene_id} control review requires user_override_reason")
    if not isinstance(review_video, str) or not review_video.strip():
        raise ValueError(f"scene {scene.scene_id} control review requires video_path")
    resolved_review_video = Path(review_video)
    if not resolved_review_video.is_absolute():
        resolved_review_video = review_path.parent / resolved_review_video
    if resolved_review_video.resolve() != Path(scene.video_path).resolve():
        raise ValueError(f"scene {scene.scene_id} control review validates a different video")
    return {
        "review_path": str(review_path),
        "status": status,
        "reason": reason.strip(),
        "reviewer": value.get("reviewer"),
    }


def _render_scene_audio(
    *,
    scene: StoryScene,
    cast: dict[str, StoryCastMember],
    audio_dir: Path,
    scene_index: int,
) -> tuple[Path, list[dict[str, object]]]:
    inputs: list[tuple[Path | None, float]] = []
    timeline: list[dict[str, object]] = []
    cursor = 0.0
    engines: dict[tuple[str, str], TTSEngine] = {}
    for line_index, line in enumerate(scene.lines):
        audio_path = Path(line.audio_path) if line.audio_path else _synthesize_line(
            line=line,
            cast_member=cast[line.speaker],
            audio_dir=audio_dir,
            scene_index=scene_index,
            line_index=line_index,
            engines=engines,
        )
        duration = _duration(audio_path)
        if duration <= 0:
            raise RuntimeError(f"scene {scene.scene_id} line {line_index} has invalid audio duration")
        timeline.append(
            {
                "speaker": line.speaker,
                "speaker_name": cast[line.speaker].name,
                "text": line.text,
                "audio_path": str(audio_path),
                "start": round(cursor, 3),
                "end": round(cursor + duration, 3),
            }
        )
        inputs.append((audio_path, duration))
        cursor += duration
        if line.pause_after_seconds:
            inputs.append((None, line.pause_after_seconds))
            cursor += line.pause_after_seconds

    scene_audio = audio_dir / f"scene_{scene_index:03d}_{scene.scene_id}.m4a"
    _concatenate_audio(inputs, scene_audio)
    return scene_audio, timeline


def _synthesize_line(
    *,
    line: StoryLine,
    cast_member: StoryCastMember,
    audio_dir: Path,
    scene_index: int,
    line_index: int,
    engines: dict[tuple[str, str], TTSEngine],
) -> Path:
    engine_key = (cast_member.tts_provider, cast_member.voice)
    engine = engines.setdefault(
        engine_key,
        TTSEngine(output_dir=str(audio_dir), provider_type=cast_member.tts_provider),
    )
    extension = "wav" if cast_member.tts_provider == "gpt_sovits" else "mp3"
    synthesis_key = "\0".join(
        (
            cast_member.tts_provider,
            cast_member.voice,
            line.text,
            line.rate,
            line.volume,
            line.pitch,
        )
    )
    content_hash = hashlib.sha256(synthesis_key.encode("utf-8")).hexdigest()[:12]
    output_name = f"scene_{scene_index:03d}_line_{line_index:03d}_{line.speaker}_{content_hash}.{extension}"
    cached_path = audio_dir / output_name
    if cached_path.is_file() and _duration(cached_path) > 0:
        return cached_path
    generated = engine.generate_audio(
        line.text,
        filename=output_name,
        voice=cast_member.voice or None,
        rate=line.rate,
        volume=line.volume,
        pitch=line.pitch,
    )
    if isinstance(generated, list):
        raise RuntimeError(f"TTS returned multiple files for scene {scene_index} line {line_index}")
    if not generated:
        raise RuntimeError(f"TTS failed for scene {scene_index} line {line_index} ({line.speaker})")
    generated_path = Path(generated)
    if not generated_path.is_file():
        raise RuntimeError(f"TTS did not create its reported file: {generated_path}")
    return generated_path


def _concatenate_audio(inputs: list[tuple[Path | None, float]], output: Path) -> None:
    if not inputs:
        raise ValueError("scene requires at least one audio input")
    command = ["ffmpeg", "-y"]
    for audio_path, silence_duration in inputs:
        if audio_path is None:
            command.extend(["-f", "lavfi", "-t", f"{silence_duration:.3f}", "-i", "anullsrc=r=48000:cl=stereo"])
        else:
            command.extend(["-i", str(audio_path)])
    filters = [
        f"[{index}:a]aresample=48000,aformat=sample_rates=48000:channel_layouts=stereo[audio{index}]"
        for index in range(len(inputs))
    ]
    joined = "".join(f"[audio{index}]" for index in range(len(inputs)))
    filters.append(f"{joined}concat=n={len(inputs)}:v=0:a=1,asetpts=N/SR/TB[outa]")
    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[outa]",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )
    _run_ffmpeg(command, f"concatenate scene audio: {output}")


def _compose_scene(
    video_path: str,
    audio_path: Path,
    output: Path,
    duration: float,
    profile: VideoQualityProfile,
    video_fit_mode: str = "loop",
) -> None:
    video_filter = (
        f"[0:v]scale={profile.width}:{profile.height}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={profile.width}:{profile.height},fps={profile.fps},setsar=1,format={profile.pixel_format}"
    )
    if video_fit_mode == "hold_last":
        video_filter += (
            f",tpad=stop_mode=clone:stop_duration={duration:.3f},"
            f"trim=duration={duration:.3f},setpts=PTS-STARTPTS"
        )
    filter_value = f"{video_filter}[outv]"
    command = [
        "ffmpeg",
        "-y",
        *(["-stream_loop", "-1"] if video_fit_mode == "loop" else []),
        "-i", video_path,
        "-i",
        str(audio_path),
        "-filter_complex",
        filter_value,
        "-map",
        "[outv]",
        "-map",
        "1:a",
        "-t",
        f"{duration:.3f}",
        *profile.video_encoding_args(),
        *profile.audio_encoding_args(),
        *profile.muxing_args(),
        str(output),
    ]
    _run_ffmpeg(command, f"compose scene: {output}")


def _concatenate_scenes(scene_outputs: list[Path], output: Path, profile: VideoQualityProfile) -> None:
    if not scene_outputs:
        raise ValueError("story requires at least one rendered scene")
    command = ["ffmpeg", "-y"]
    for scene_output in scene_outputs:
        command.extend(["-i", str(scene_output)])
    streams = "".join(f"[{index}:v][{index}:a]" for index in range(len(scene_outputs)))
    filter_value = (
        f"{streams}concat=n={len(scene_outputs)}:v=1:a=1[outv][story_audio];"
        "[story_audio]loudnorm=I=-16:TP=-1.5:LRA=11[outa]"
    )
    command.extend(
        [
            "-filter_complex",
            filter_value,
            "-map",
            "[outv]",
            "-map",
            "[outa]",
            *profile.video_encoding_args(),
            *profile.audio_encoding_args(),
            *profile.muxing_args(),
            str(output),
        ]
    )
    _run_ffmpeg(command, f"concatenate story scenes: {output}")


def _duration(path: Path | str) -> float:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        return float(subprocess.check_output(command, text=True, timeout=20).strip())
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise RuntimeError(f"cannot read duration for {path}: {exc}") from exc


def _run_ffmpeg(command: list[str], purpose: str) -> None:
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed to {purpose}: {result.stderr[-1500:]}")


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
