"""视频输出质量档位与共享 FFmpeg 编码参数。"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class VideoQualityProfile:
    """一个可复用的最终视频输出规格。"""

    name: str
    width: int
    height: int
    fps: int
    crf: int
    preset: str
    min_video_bitrate: int
    target_video_bitrate: int
    rate_control: str = "cbr"
    video_codec: str = "libx264"
    h264_profile: str = "high"
    h264_level: str = "4.2"
    pixel_format: str = "yuv420p"
    color_space: str = "bt709"
    color_primaries: str = "bt709"
    color_transfer: str = "bt709"
    audio_codec: str = "aac"
    audio_bitrate: str = "192k"

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0 or self.fps <= 0:
            raise ValueError("视频尺寸和帧率必须为正数")
        if not 0 <= self.crf <= 51:
            raise ValueError("CRF 必须在 0 到 51 之间")
        if self.target_video_bitrate < self.min_video_bitrate:
            raise ValueError("target_video_bitrate must be >= min_video_bitrate")
        if self.rate_control not in {"cbr", "crf"}:
            raise ValueError("rate_control must be cbr or crf")
        if self.min_video_bitrate < 0:
            raise ValueError("最低视频码率不能为负数")

    def video_encoding_args(self) -> list[str]:
        """返回每条最终视频都应使用的编码参数。"""
        args = [
            "-r",
            str(self.fps),
            "-c:v",
            self.video_codec,
            "-preset",
            self.preset,
            "-profile:v",
            self.h264_profile,
            "-level:v",
            self.h264_level,
            "-pix_fmt",
            self.pixel_format,
            "-colorspace",
            self.color_space,
            "-color_primaries",
            self.color_primaries,
            "-color_trc",
            self.color_transfer,
        ]
        if self.rate_control == "cbr":
            args.extend(
                [
                    "-b:v",
                    str(self.target_video_bitrate),
                    "-minrate",
                    str(self.target_video_bitrate),
                    "-maxrate",
                    str(self.target_video_bitrate),
                    "-bufsize",
                    str(self.target_video_bitrate * 2),
                ]
            )
        else:
            args.extend(["-crf", str(self.crf)])
        if self.video_codec == "libx264":
            x264_params = "colorprim=bt709:transfer=bt709:colormatrix=bt709"
            if self.rate_control == "cbr":
                x264_params = f"nal-hrd=cbr:{x264_params}"
            args.extend(
                [
                    "-x264-params",
                    x264_params,
                ]
            )
        return args

    def audio_encoding_args(self) -> list[str]:
        return ["-c:a", self.audio_codec, "-b:a", self.audio_bitrate]

    def muxing_args(self) -> list[str]:
        return ["-movflags", "+faststart"]

    def with_overrides(
        self,
        *,
        width: int | None = None,
        height: int | None = None,
        fps: int | None = None,
        crf: int | None = None,
    ) -> "VideoQualityProfile":
        """为兼容特定画布创建派生档位，不修改全局预设。"""
        updated = replace(
            self,
            width=width if width is not None else self.width,
            height=height if height is not None else self.height,
            fps=fps if fps is not None else self.fps,
            crf=crf if crf is not None else self.crf,
        )
        return replace(updated, rate_control="crf") if crf is not None else updated


VIDEO_QUALITY_PROFILES: dict[str, VideoQualityProfile] = {
    "preview": VideoQualityProfile(
        name="preview",
        width=540,
        height=960,
        fps=24,
        crf=26,
        preset="fast",
        min_video_bitrate=700_000,
        target_video_bitrate=1_000_000,
    ),
    "publish": VideoQualityProfile(
        name="publish",
        width=1080,
        height=1920,
        fps=30,
        crf=19,
        preset="medium",
        min_video_bitrate=2_000_000,
        target_video_bitrate=3_000_000,
    ),
    "master": VideoQualityProfile(
        name="master",
        width=1080,
        height=1920,
        fps=30,
        crf=17,
        preset="slow",
        min_video_bitrate=4_000_000,
        target_video_bitrate=6_000_000,
    ),
}


def available_quality_profiles() -> tuple[str, ...]:
    return tuple(VIDEO_QUALITY_PROFILES)


def resolve_quality_profile(
    profile: str | VideoQualityProfile | None = None,
) -> VideoQualityProfile:
    """将调用方输入解析为不可变的质量档位。"""
    if isinstance(profile, VideoQualityProfile):
        return profile

    profile_name = (profile or "publish").strip().lower()
    try:
        return VIDEO_QUALITY_PROFILES[profile_name]
    except KeyError as exc:
        choices = ", ".join(available_quality_profiles())
        raise ValueError(f"未知视频质量档位: {profile_name}，可选值: {choices}") from exc
