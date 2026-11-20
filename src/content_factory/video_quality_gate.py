"""最终视频的基础规格与帧异常质量门禁。"""

from __future__ import annotations

import json
import math
import subprocess
from dataclasses import asdict, dataclass, field
from io import BytesIO
from pathlib import Path

from PIL import Image

from src.content_factory.video_quality import VideoQualityProfile, resolve_quality_profile


@dataclass(frozen=True, slots=True)
class VideoQualityIssue:
    code: str
    message: str
    severity: str = "error"


@dataclass(slots=True)
class FrameQualityMetrics:
    timestamp: float
    mean_luma: float
    luma_stddev: float
    mean_chroma: float
    sharpness: float
    row_luma_stddev: float
    column_luma_stddev: float


@dataclass(slots=True)
class VideoQualityReport:
    path: str
    profile: str
    metadata: dict[str, object] = field(default_factory=dict)
    frame_metrics: list[FrameQualityMetrics] = field(default_factory=list)
    issues: list[VideoQualityIssue] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    @property
    def warnings(self) -> list[VideoQualityIssue]:
        return [issue for issue in self.issues if issue.severity != "error"]

    def add_issue(self, code: str, message: str, severity: str = "error") -> None:
        self.issues.append(VideoQualityIssue(code=code, message=message, severity=severity))

    def write_json(self, output_path: str | Path) -> None:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                {
                    "path": self.path,
                    "profile": self.profile,
                    "passed": self.passed,
                    "metadata": self.metadata,
                    "frame_metrics": [asdict(metric) for metric in self.frame_metrics],
                    "issues": [asdict(issue) for issue in self.issues],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


class VideoQualityGate:
    """只依赖 ffprobe、ffmpeg 和 Pillow 的发布前质量检查。"""

    def __init__(self, sample_count: int = 3):
        self.sample_count = max(1, sample_count)

    def inspect(
        self,
        video_path: str | Path,
        quality_profile: str | VideoQualityProfile = "publish",
        *,
        expected_duration: float | None = None,
        panel_motion_policy: dict[str, str] | None = None,
        panel_regions: dict[str, tuple[int, int, int, int]] | None = None,
    ) -> VideoQualityReport:
        path = Path(video_path)
        profile = resolve_quality_profile(quality_profile)
        report = VideoQualityReport(path=str(path), profile=profile.name)
        if not path.is_file():
            report.add_issue("file_missing", f"视频文件不存在: {path}")
            return report

        try:
            probe = self._probe(path)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError) as exc:
            report.add_issue("probe_failed", f"无法读取媒体信息: {exc}")
            return report

        self.evaluate_probe(report, probe, profile, expected_duration=expected_duration)
        duration = _to_float(report.metadata.get("duration"))
        if duration <= 0:
            return report

        try:
            samples = self._sample_frames(path, duration)
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            severity = "error" if panel_motion_policy else "warning"
            report.add_issue("frame_scan_unavailable", f"无法执行帧质检: {exc}", severity=severity)
            return report

        for timestamp, image in samples:
            metrics = self.frame_metrics(image, timestamp)
            report.frame_metrics.append(metrics)
            self._evaluate_frame(report, metrics)

        self._evaluate_static_frames(report, samples, duration)
        if panel_motion_policy:
            self._evaluate_panel_motion(report, samples, panel_motion_policy, panel_regions or {})
        return report

    def inspect_character_asset(
        self,
        asset_path: str | Path,
        asset_kind: str,
        *,
        chroma_key_color: tuple[int, int, int] = (244, 246, 236),
    ) -> VideoQualityReport:
        """检查透明角色素材或绿幕角色素材的可用性与边缘风险。"""
        path = Path(asset_path)
        report = VideoQualityReport(path=str(path), profile="character_asset")
        report.metadata["asset_kind"] = asset_kind
        if asset_kind == "sequence" and not path.exists():
            path = Path(str(path).replace("%06d", "000001").replace("%05d", "00001"))

        if not path.is_file():
            report.add_issue("character_asset_missing", f"角色素材不存在: {path}")
            return report

        if asset_kind in {"static", "sequence"}:
            self._inspect_alpha_asset(report, path)
        elif asset_kind == "video_chroma":
            self._inspect_chroma_asset(report, path, chroma_key_color)
        return report

    @staticmethod
    def evaluate_probe(
        report: VideoQualityReport,
        probe: dict[str, object],
        profile: VideoQualityProfile,
        *,
        expected_duration: float | None = None,
    ) -> None:
        streams = probe.get("streams") if isinstance(probe, dict) else None
        streams = streams if isinstance(streams, list) else []
        video_stream = next(
            (stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "video"),
            None,
        )
        audio_stream = next(
            (stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "audio"),
            None,
        )
        format_info = probe.get("format") if isinstance(probe, dict) else None
        format_info = format_info if isinstance(format_info, dict) else {}

        if not isinstance(video_stream, dict):
            report.add_issue("video_stream_missing", "媒体中未找到视频流")
            return
        if not isinstance(audio_stream, dict):
            report.add_issue("audio_stream_missing", "媒体中未找到音频流")

        width = _to_int(video_stream.get("width"))
        height = _to_int(video_stream.get("height"))
        fps = _parse_frame_rate(video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate"))
        duration = _to_float(format_info.get("duration") or video_stream.get("duration"))
        bit_rate = _to_int(video_stream.get("bit_rate") or format_info.get("bit_rate"))
        metadata = {
            "width": width,
            "height": height,
            "fps": round(fps, 3),
            "duration": duration,
            "bit_rate": bit_rate,
            "codec": str(video_stream.get("codec_name") or ""),
            "pixel_format": str(video_stream.get("pix_fmt") or ""),
            "color_space": str(video_stream.get("color_space") or ""),
            "color_primaries": str(video_stream.get("color_primaries") or ""),
            "color_transfer": str(video_stream.get("color_transfer") or ""),
        }
        report.metadata.update(metadata)

        if duration <= 0:
            report.add_issue("duration_invalid", "视频时长必须大于 0")
        if (width, height) != (profile.width, profile.height):
            report.add_issue(
                "dimensions_mismatch",
                f"输出尺寸 {width}x{height}，期望 {profile.width}x{profile.height}",
            )
        if abs(fps - profile.fps) > 0.5:
            report.add_issue("fps_mismatch", f"输出帧率 {fps:.3f}，期望 {profile.fps}")
        if metadata["codec"] != "h264":
            report.add_issue("codec_mismatch", f"输出编码为 {metadata['codec']}，期望 h264")
        if metadata["pixel_format"] != profile.pixel_format:
            report.add_issue(
                "pixel_format_mismatch",
                f"像素格式为 {metadata['pixel_format']}，期望 {profile.pixel_format}",
            )
        expected_color_values = {
            "color_space": profile.color_space,
            "color_primaries": profile.color_primaries,
            "color_transfer": profile.color_transfer,
        }
        for field_name, expected_value in expected_color_values.items():
            actual_value = str(metadata[field_name]).lower()
            if actual_value in {"", "unknown", "n/a"}:
                report.add_issue(
                    "color_metadata_missing",
                    f"{field_name} 缺失，期望 {expected_value}",
                    severity="warning",
                )
            elif actual_value != expected_value:
                report.add_issue(
                    "color_metadata_mismatch",
                    f"{field_name} 为 {actual_value}，期望 {expected_value}",
                    severity="warning",
                )
        if bit_rate and bit_rate < profile.min_video_bitrate:
            report.add_issue(
                "low_bitrate",
                f"视频码率 {bit_rate} bps 低于 {profile.min_video_bitrate} bps",
                severity="warning",
            )
        if expected_duration is not None and abs(duration - expected_duration) > 0.35:
            report.add_issue(
                "duration_mismatch",
                f"实际时长 {duration:.3f}s，与期望 {expected_duration:.3f}s 不一致",
            )

    @staticmethod
    def frame_metrics(image: Image.Image, timestamp: float) -> FrameQualityMetrics:
        reduced = image.convert("RGB").resize((96, 128))
        pixels = list(reduced.getdata())
        luma_values = [0.2126 * red + 0.7152 * green + 0.0722 * blue for red, green, blue in pixels]
        chroma_values = [max(red, green, blue) - min(red, green, blue) for red, green, blue in pixels]
        mean_luma = sum(luma_values) / len(luma_values)
        luma_stddev = _standard_deviation(luma_values, mean_luma)
        mean_chroma = sum(chroma_values) / len(chroma_values)

        row_means = [sum(luma_values[row * 96:(row + 1) * 96]) / 96 for row in range(128)]
        column_means = [sum(luma_values[column::96]) / 128 for column in range(96)]
        laplacian_values = []
        for row in range(1, 127):
            for column in range(1, 95):
                index = row * 96 + column
                laplacian_values.append(
                    4 * luma_values[index]
                    - luma_values[index - 1]
                    - luma_values[index + 1]
                    - luma_values[index - 96]
                    - luma_values[index + 96]
                )
        return FrameQualityMetrics(
            timestamp=timestamp,
            mean_luma=round(mean_luma, 3),
            luma_stddev=round(luma_stddev, 3),
            mean_chroma=round(mean_chroma, 3),
            sharpness=round(_standard_deviation(laplacian_values) ** 2, 3),
            row_luma_stddev=round(_standard_deviation(row_means), 3),
            column_luma_stddev=round(_standard_deviation(column_means), 3),
        )

    def _probe(self, path: Path) -> dict[str, object]:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            timeout=20,
        )
        return json.loads(result.stdout)

    def _sample_frames(self, path: Path, duration: float) -> list[tuple[float, Image.Image]]:
        timestamps = self._sample_timestamps(duration)
        samples: list[tuple[float, Image.Image]] = []
        for timestamp in timestamps:
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-ss",
                    f"{timestamp:.3f}",
                    "-i",
                    str(path),
                    "-frames:v",
                    "1",
                    "-f",
                    "image2pipe",
                    "-vcodec",
                    "png",
                    "-",
                ],
                capture_output=True,
                check=True,
                timeout=30,
            )
            if not result.stdout:
                raise ValueError(f"无法抽取 {timestamp:.3f}s 的视频帧")
            with Image.open(BytesIO(result.stdout)) as image:
                samples.append((timestamp, image.convert("RGB").copy()))
        return samples

    def _sample_timestamps(self, duration: float) -> list[float]:
        """Choose deterministic, non-uniform offsets to avoid loop-phase aliasing."""
        golden_ratio = 0.61803398875
        fractions = sorted(((index + 1) * golden_ratio) % 1 for index in range(self.sample_count))
        edge_padding = min(0.05, duration / 10)
        return [min(duration - edge_padding, max(edge_padding, duration * fraction)) for fraction in fractions]

    @staticmethod
    def _evaluate_frame(report: VideoQualityReport, metrics: FrameQualityMetrics) -> None:
        if metrics.mean_luma < 10:
            report.add_issue("black_frame", f"{metrics.timestamp:.2f}s 检测到近黑帧")
        elif 20 < metrics.mean_luma < 235 and metrics.mean_chroma < 6 and metrics.luma_stddev < 5:
            report.add_issue("gray_frame", f"{metrics.timestamp:.2f}s 检测到低变化灰帧")
        elif (
            metrics.mean_chroma < 8
            and metrics.luma_stddev > 8
            and max(metrics.row_luma_stddev, metrics.column_luma_stddev) > metrics.luma_stddev * 0.82
        ):
            report.add_issue("stripe_frame", f"{metrics.timestamp:.2f}s 检测到疑似低饱和条纹帧")
        if 15 < metrics.mean_luma < 240 and metrics.sharpness < 2.0:
            report.add_issue(
                "low_sharpness",
                f"{metrics.timestamp:.2f}s 清晰度指标偏低 ({metrics.sharpness:.2f})",
                severity="warning",
            )

    @staticmethod
    def _evaluate_static_frames(
        report: VideoQualityReport,
        samples: list[tuple[float, Image.Image]],
        duration: float,
    ) -> None:
        if duration < 3 or len(samples) < 2:
            return
        distances = [
            _mean_pixel_distance(samples[index - 1][1], samples[index][1])
            for index in range(1, len(samples))
        ]
        if distances and max(distances) < 1.2:
            report.add_issue("static_video", "抽样帧几乎无变化，建议确认是否符合镜头设计", severity="warning")

    @staticmethod
    def _evaluate_panel_motion(
        report: VideoQualityReport,
        samples: list[tuple[float, Image.Image]],
        panel_motion_policy: dict[str, str],
        panel_regions: dict[str, tuple[int, int, int, int]],
    ) -> None:
        """Verify that named panels stay static or show visible motion as declared."""
        if len(samples) < 2:
            report.add_issue("panel_motion_unavailable", "不足两张抽样帧，无法验证分区运动策略")
            return

        motion_metrics: dict[str, object] = {}
        for panel_name, expected_motion in panel_motion_policy.items():
            region = panel_regions.get(panel_name)
            if expected_motion not in {"static", "dynamic"}:
                report.add_issue("panel_motion_policy_invalid", f"{panel_name} 的运动策略无效: {expected_motion}")
                continue
            if not region:
                report.add_issue("panel_region_missing", f"{panel_name} 未提供可验证的区域")
                continue
            x, y, width, height = region
            if width <= 0 or height <= 0:
                report.add_issue("panel_region_invalid", f"{panel_name} 的区域尺寸无效")
                continue
            crops = [image.crop((x, y, x + width, y + height)) for _, image in samples]
            differences = [_frame_difference(crops[index - 1], crops[index]) for index in range(1, len(crops))]
            distances = [difference[0] for difference in differences]
            active_ratios = [difference[1] for difference in differences]
            max_distance = max(distances, default=0.0)
            mean_distance = sum(distances) / len(distances) if distances else 0.0
            max_active_ratio = max(active_ratios, default=0.0)
            motion_metrics[panel_name] = {
                "expected": expected_motion,
                "mean_frame_distance": round(mean_distance, 3),
                "max_frame_distance": round(max_distance, 3),
                "max_active_pixel_ratio": round(max_active_ratio, 4),
            }
            if expected_motion == "static" and (max_distance > 1.2 or max_active_ratio > 0.02):
                report.add_issue(
                    "static_panel_motion_detected",
                    f"{panel_name} 应保持静态，但帧差异为 {max_distance:.3f}、活跃像素占比为 {max_active_ratio:.4f}",
                )
            elif expected_motion == "dynamic" and max_distance < 1.2 and max_active_ratio < 0.002:
                report.add_issue(
                    "dynamic_panel_motion_missing",
                    f"{panel_name} 应有可见动态，但帧差异仅为 {max_distance:.3f}、活跃像素占比为 {max_active_ratio:.4f}",
                )
        report.metadata["panel_motion"] = motion_metrics

    def _inspect_alpha_asset(self, report: VideoQualityReport, path: Path) -> None:
        try:
            with Image.open(path) as image:
                if "A" not in image.getbands():
                    report.add_issue("alpha_missing", "角色图没有 Alpha 通道，可能出现硬边", severity="warning")
                    return
                alpha = image.getchannel("A").resize((128, 128), Image.Resampling.NEAREST)
                alpha_values = list(alpha.getdata())
        except OSError as exc:
            report.add_issue("character_asset_unreadable", f"无法读取角色图: {exc}")
            return

        transparent_ratio = sum(value == 0 for value in alpha_values) / len(alpha_values)
        soft_edge_ratio = sum(0 < value < 255 for value in alpha_values) / len(alpha_values)
        report.metadata.update(
            {
                "transparent_ratio": round(transparent_ratio, 4),
                "soft_edge_ratio": round(soft_edge_ratio, 4),
            }
        )
        if transparent_ratio > 0.98:
            report.add_issue("character_asset_empty", "角色图几乎完全透明")
        elif transparent_ratio > 0.02 and soft_edge_ratio < 0.001:
            report.add_issue("hard_alpha_edge", "角色图缺少半透明边缘，可能出现锯齿", severity="warning")

    def _inspect_chroma_asset(
        self,
        report: VideoQualityReport,
        path: Path,
        chroma_key_color: tuple[int, int, int],
    ) -> None:
        try:
            probe = self._probe(path)
            duration = _to_float((probe.get("format") or {}).get("duration"))
            samples = self._sample_frames(path, duration) if duration > 0 else []
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            report.add_issue("chroma_scan_unavailable", f"无法检查绿幕角色素材: {exc}", severity="warning")
            return

        ratios = []
        for _, image in samples:
            reduced = image.convert("RGB").resize((96, 128))
            matches = sum(
                max(abs(red - chroma_key_color[0]), abs(green - chroma_key_color[1]), abs(blue - chroma_key_color[2])) < 42
                for red, green, blue in reduced.getdata()
            )
            ratios.append(matches / (96 * 128))
        if not ratios:
            report.add_issue("chroma_frame_missing", "未能从绿幕角色素材抽取视频帧", severity="warning")
            return

        key_ratio = sum(ratios) / len(ratios)
        report.metadata["chroma_key_ratio"] = round(key_ratio, 4)
        if key_ratio < 0.005:
            report.add_issue("chroma_key_not_detected", "未检测到足够的预期绿幕色，建议检查色键颜色", severity="warning")
        elif key_ratio > 0.98:
            report.add_issue("character_foreground_missing", "绿幕素材几乎全为键控颜色")


def _parse_frame_rate(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str) or not value:
        return 0.0
    if "/" not in value:
        return _to_float(value)
    numerator, denominator = value.split("/", maxsplit=1)
    denominator_value = _to_float(denominator)
    return _to_float(numerator) / denominator_value if denominator_value else 0.0


def _to_int(value: object) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return 0


def _to_float(value: object) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return 0.0


def _standard_deviation(values: list[float], mean: float | None = None) -> float:
    if not values:
        return 0.0
    sample_mean = mean if mean is not None else sum(values) / len(values)
    return math.sqrt(sum((value - sample_mean) ** 2 for value in values) / len(values))


def _mean_pixel_distance(left: Image.Image, right: Image.Image) -> float:
    return _frame_difference(left, right)[0]


def _frame_difference(left: Image.Image, right: Image.Image) -> tuple[float, float]:
    left_pixels = list(left.resize((64, 64)).convert("RGB").getdata())
    right_pixels = list(right.resize((64, 64)).convert("RGB").getdata())
    differences = [
        abs(left_red - right_red) + abs(left_green - right_green) + abs(left_blue - right_blue)
        for (left_red, left_green, left_blue), (right_red, right_green, right_blue) in zip(left_pixels, right_pixels)
    ]
    mean_distance = sum(differences) / (len(differences) * 3) if differences else 0.0
    active_ratio = sum(difference >= 36 for difference in differences) / len(differences) if differences else 0.0
    return mean_distance, active_ratio
