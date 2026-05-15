import os
import subprocess
from pathlib import Path

from src.content_factory.presenter.models import CharacterAsset, PresenterSegment
from src.content_factory.video_composer import get_duration


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


class PresenterComposer:
    def __init__(self, width: int = 1080, height: int = 1920, fps: int = 30, crf: int = 23):
        self.width = width
        self.height = height
        self.fps = fps
        self.crf = crf

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

        cmd = ["ffmpeg", "-y"]
        self._append_background_input(cmd, background_path)
        self._append_character_input(cmd, character)
        cmd.extend(["-loop", "1", "-framerate", str(self.fps), "-i", segment.text_layer_path])
        cmd.extend(["-i", segment.audio_path])

        role_width = self._role_width(character_size)
        role_x, role_y = self._role_position(character_position)
        filter_complex = (
            f"[0:v]scale={self.width}:{self.height}:force_original_aspect_ratio=increase,"
            f"crop={self.width}:{self.height},setsar=1[bg];"
            f"[1:v]scale={role_width}:-1,format=rgba[role];"
            f"[2:v]scale={self.width}:{self.height},format=rgba[text];"
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
                "-r",
                str(self.fps),
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                str(self.crf),
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                str(output_path),
            ]
        )

        self._run(cmd, timeout=600)
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
                str(output_path),
            ]
            self._run(mix_cmd, timeout=600)

        return str(output_path)

    def _append_background_input(self, cmd: list[str], path: str) -> None:
        if self._is_image(path):
            cmd.extend(["-loop", "1", "-framerate", str(self.fps), "-i", path])
        else:
            cmd.extend(["-stream_loop", "-1", "-i", path])

    def _append_character_input(self, cmd: list[str], character: CharacterAsset) -> None:
        if character.kind == "sequence":
            cmd.extend(["-stream_loop", "-1", "-framerate", str(self.fps), "-i", character.path])
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
        return sizes.get((size or "medium").strip().lower(), sizes["medium"])

    def _role_position(self, position: str) -> tuple[str, str]:
        positions = {
            "right_bottom": ("W-w-42", "H-h-86"),
            "left_bottom": ("42", "H-h-86"),
            "center_bottom": ("(W-w)/2", "H-h-70"),
        }
        return positions.get((position or "right_bottom").strip().lower(), positions["right_bottom"])

    def _run(self, cmd: list[str], timeout: int = 600) -> None:
        result = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=timeout)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg 失败:\n{result.stderr[-1600:]}")
