"""Authorized local-media runner for the existing Qwen and Paraformer scripts."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Callable

from .base import ContentAnalysisRequest


CommandRunner = Callable[[list[str]], None]


class LocalContentToolchain:
    def __init__(
        self,
        *,
        project_root: str | Path | None = None,
        output_root: str | Path | None = None,
        command_runner: CommandRunner | None = None,
        frame_interval_seconds: float = 3.0,
    ):
        self.project_root = Path(project_root or Path(__file__).resolve().parents[3]).resolve()
        self.output_root = Path(
            output_root or self.project_root / "data" / "video_analysis" / "trend"
        ).resolve()
        self.command_runner = command_runner or self._run_command
        self.frame_interval_seconds = max(1.0, float(frame_interval_seconds))

    def prepare_request(self, request: ContentAnalysisRequest) -> ContentAnalysisRequest:
        if request.media_access_mode != "local_media_authorized":
            raise PermissionError("toolchain requires local_media_authorized")
        video = Path(request.local_video_path).resolve()
        if not video.is_file():
            raise FileNotFoundError(video)
        identity = hashlib.sha256(
            f"{request.item_id}|{video}|{video.stat().st_size}".encode("utf-8")
        ).hexdigest()[:24]
        work_dir = (self.output_root / identity).resolve()
        if not work_dir.is_relative_to(self.output_root):
            raise ValueError("analysis output escaped configured output root")
        frames = work_dir / "frames"
        audio = work_dir / "audio.wav"
        qwen = work_dir / "qwen.json"
        transcript = work_dir / "transcript.json"
        frames.mkdir(parents=True, exist_ok=True)

        if not any(frames.glob("*.jpg")):
            self.command_runner(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(video),
                    "-vf",
                    f"fps=1/{self.frame_interval_seconds:g}",
                    str(frames / "frame_%04d.jpg"),
                ]
            )
        if not audio.is_file():
            self.command_runner(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(video),
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    str(audio),
                ]
            )
        if not qwen.is_file():
            self.command_runner(
                [
                    sys.executable,
                    str(self.project_root / "scripts" / "analyze_video_frames_qwen.py"),
                    str(frames),
                    str(qwen),
                    "--interval-seconds",
                    f"{self.frame_interval_seconds:g}",
                ]
            )
        if not transcript.is_file():
            transcript_command = [
                sys.executable,
                str(self.project_root / "scripts" / "transcribe_video_local.py"),
                str(audio),
                str(transcript),
            ]
            hotwords = request.account_profile.matching_terms()
            if hotwords:
                transcript_command.extend(["--hotword", " ".join(hotwords[:50])])
            self.command_runner(transcript_command)
        return replace(
            request,
            qwen_analysis_path=str(qwen),
            transcript_path=str(transcript),
        )

    @staticmethod
    def _run_command(command: list[str]) -> None:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3600,
        )
