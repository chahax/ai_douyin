"""模型视频进入合成前的无损增强接口。

第一阶段仅依赖 FFmpeg，负责高质量缩放、规格归一和可选插帧；AI 超分可在
后续以独立 Provider 接入，不改变调用方接口。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from src.content_factory.video_quality import VideoQualityProfile, resolve_quality_profile


class VideoEnhancer:
    def __init__(self, quality_profile: str | VideoQualityProfile = "publish"):
        self.profile = resolve_quality_profile(quality_profile)

    def cover_filter(self) -> str:
        """覆盖式缩放到目标画布，适合背景和模板视频。"""
        return (
            f"scale={self.profile.width}:{self.profile.height}:"
            f"force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={self.profile.width}:{self.profile.height},setsar=1,"
            f"fps={self.profile.fps}"
        )

    def fit_filter(self, background_color: str = "black") -> str:
        """完整保留画面内容的缩放方式，适合需要留边的镜头。"""
        return (
            f"scale={self.profile.width}:{self.profile.height}:"
            f"force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={self.profile.width}:{self.profile.height}:(ow-iw)/2:(oh-ih):"
            f"color={background_color},setsar=1,fps={self.profile.fps}"
        )

    def enhance(
        self,
        source_path: str | Path,
        output_path: str | Path,
        *,
        fit: bool = False,
        interpolate: bool = False,
        timeout: int = 600,
    ) -> str:
        """生成新的增强文件，永远不覆盖模型原始输出。"""
        source = Path(source_path)
        output = Path(output_path)
        if not source.is_file():
            raise FileNotFoundError(f"待增强视频不存在: {source}")

        output.parent.mkdir(parents=True, exist_ok=True)
        filters = [self.fit_filter() if fit else self.cover_filter()]
        if interpolate:
            filters.append(
                f"minterpolate=fps={self.profile.fps}:mi_mode=mci:"
                "mc_mode=aobmc:me_mode=bidir:vsbmc=1"
            )

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-vf",
            ",".join(filters),
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            *self.profile.video_encoding_args(),
            *self.profile.audio_encoding_args(),
            *self.profile.muxing_args(),
            str(output),
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if result.returncode != 0:
            raise RuntimeError(f"视频增强失败:\n{result.stderr[-1600:]}")
        return str(output)
