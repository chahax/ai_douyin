import subprocess
from pathlib import Path

from src.content_factory.presenter.models import CharacterAsset, PresenterSegment
from src.content_factory.video_enhancer import VideoEnhancer
from src.content_factory.video_quality import VideoQualityProfile, resolve_quality_profile
from src.content_factory.video_quality_gate import VideoQualityGate
from src.content_factory.video_composer import get_duration
from src.shared.logger import logger


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}


class PresenterComposer:
    def __init__(
        self,
        quality_profile: str | VideoQualityProfile = "publish",
        *,
        width: int | None = None,
        height: int | None = None,
        fps: int | None = None,
        crf: int | None = None,
    ):
        self.profile = resolve_quality_profile(quality_profile).with_overrides(
            width=width,
            height=height,
            fps=fps,
            crf=crf,
        )
        self.width = self.profile.width
        self.height = self.profile.height
        self.fps = self.profile.fps
        self.enhancer = VideoEnhancer(self.profile)
        self.quality_gate = VideoQualityGate()

    def compose_segment(
        self,
        segment: PresenterSegment,
        background_path: str,
        character: CharacterAsset,
        output_path: Path,
        character_position: str = "right_bottom",
        character_size: str = "medium",
    ) -> str:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        duration = segment.duration or get_duration(segment.audio_path)
        if duration <= 0:
            raise RuntimeError(f"无法读取段落音频时长: {segment.audio_path}")
        self._verify_character_asset(character, output_path)

        cmd = ["ffmpeg", "-y"]
        self._append_background_input(cmd, background_path)
        self._append_character_input(cmd, character)
        cmd.extend(["-loop", "1", "-framerate", str(self.fps), "-i", segment.text_layer_path])
        cmd.extend(["-i", segment.audio_path])

        role_width = self._role_width(character_size)
        role_x, role_y = self._role_position(character_position)
        content_panel_top = round(self.height * 1340 / 1920)
        role_filter = f"[1:v]scale={role_width}:-1:flags=lanczos,format=rgba[role];"
        if character.kind == "video_chroma":
            role_filter = (
                f"[1:v]scale={role_width}:-1:flags=lanczos,format=rgba,"
                f"colorkey=0xf4f6ec:0.10:0.04[role];"
            )

        filter_complex = (
            f"[0:v]{self.enhancer.cover_filter()},"
            f"drawbox=x=0:y={content_panel_top}:w={self.width}:h={self.height - content_panel_top}:color=0xE9F1F6@0.96:t=fill[bg];"
            f"{role_filter}"
            f"[2:v]scale={self.width}:{self.height}:flags=lanczos,format=rgba[text];"
            f"[bg][role]overlay=x={role_x}:y={role_y}:format=auto[tmp];"
            f"[tmp][text]overlay=0:0:format=auto[outv]"
        )

        cmd.extend(
            [
                "-filter_complex",
                filter_complex,
                "-map",
                "[outv]",
                "-map",
                "3:a",
                "-t",
                f"{duration:.3f}",
                "-shortest",
                *self.profile.video_encoding_args(),
                *self.profile.audio_encoding_args(),
                *self.profile.muxing_args(),
                str(output_path),
            ]
        )

        self._run(cmd, timeout=600)
        self._verify_final_video(output_path, expected_duration=duration)
        return str(output_path)

    def concatenate(self, segments: list[PresenterSegment], output_path: Path, bgm_path: str = "") -> str:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        concat_file = output_path.parent / "concat_segments.txt"
        with open(concat_file, "w", encoding="utf-8") as f:
            for segment in segments:
                clip_path = Path(segment.clip_path).resolve().as_posix()
                f.write(f"file '{clip_path}'\n")

        stitched = output_path
        if bgm_path and Path(bgm_path).exists():
            stitched = output_path.with_name(f"{output_path.stem}_voice.mp4")

        concat_cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c",
            "copy",
            *self.profile.muxing_args(),
            str(stitched),
        ]
        self._run(concat_cmd, timeout=600)

        if bgm_path and Path(bgm_path).exists():
            mix_cmd = [
                "ffmpeg",
                "-y",
                "-i",
                str(stitched),
                "-stream_loop",
                "-1",
                "-i",
                bgm_path,
                "-filter_complex",
                "[1:a]volume=0.18[bgm];[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=0[a]",
                "-map",
                "0:v",
                "-map",
                "[a]",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                *self.profile.muxing_args(),
                str(output_path),
            ]
            self._run(mix_cmd, timeout=600)

        self._verify_final_video(output_path)
        return str(output_path)

    def _append_background_input(self, cmd: list[str], path: str) -> None:
        if self._is_image(path):
            cmd.extend(["-loop", "1", "-framerate", str(self.fps), "-i", path])
        else:
            cmd.extend(["-stream_loop", "-1", "-i", path])

    def _append_character_input(self, cmd: list[str], character: CharacterAsset) -> None:
        if character.kind == "sequence":
            cmd.extend(["-stream_loop", "-1", "-framerate", str(self.fps), "-i", character.path])
        elif character.kind in {"video", "video_chroma"}:
            cmd.extend(["-stream_loop", "-1", "-an", "-i", character.path])
        else:
            cmd.extend(["-loop", "1", "-framerate", str(self.fps), "-i", character.path])

    def _is_image(self, path: str) -> bool:
        return Path(path).suffix.lower() in IMAGE_EXTENSIONS

    def _role_width(self, size: str) -> int:
        sizes = {
            "small": 340,
            "medium": 440,
            "large": 540,
        }
        base_width = sizes.get((size or "medium").strip().lower(), sizes["medium"])
        return round(base_width * self.width / 1080)

    def _role_position(self, position: str) -> tuple[str, str]:
        scale = self.width / 1080
        horizontal_margin = round(42 * scale)
        bottom_margin = round(86 * scale)
        center_bottom_margin = round(70 * scale)
        positions = {
            "right_bottom": (f"W-w-{horizontal_margin}", f"H-h-{bottom_margin}"),
            "left_bottom": (str(horizontal_margin), f"H-h-{bottom_margin}"),
            "center_bottom": ("(W-w)/2", f"H-h-{center_bottom_margin}"),
        }
        return positions.get((position or "right_bottom").strip().lower(), positions["right_bottom"])

    def _run(self, cmd: list[str], timeout: int = 600) -> None:
        result = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=timeout)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg 失败:\n{result.stderr[-1600:]}")

    def _verify_final_video(self, output_path: Path, expected_duration: float | None = None) -> None:
        report = self.quality_gate.inspect(
            output_path,
            self.profile,
            expected_duration=expected_duration,
        )
        report.write_json(output_path.with_suffix(".quality.json"))
        for warning in report.warnings:
            logger.warning(f"[VideoQualityGate] {warning.code}: {warning.message}")
        if not report.passed:
            details = "; ".join(f"{issue.code}: {issue.message}" for issue in report.issues)
            raise RuntimeError(f"最终视频未通过质量门禁: {details}")

    def _verify_character_asset(self, character: CharacterAsset, output_path: Path) -> None:
        report = self.quality_gate.inspect_character_asset(character.path, character.kind)
        report.write_json(output_path.with_suffix(".character.quality.json"))
        for warning in report.warnings:
            logger.warning(f"[CharacterQualityGate] {warning.code}: {warning.message}")
        if not report.passed:
            details = "; ".join(f"{issue.code}: {issue.message}" for issue in report.issues)
            raise RuntimeError(f"角色素材未通过质量门禁: {details}")
