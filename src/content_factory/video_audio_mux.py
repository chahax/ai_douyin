"""Build stable voiceover clips from short controlled portrait motion."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


MANIFEST_TEMPLATE = "video_audio_mux/v1"
REPORT_TEMPLATE = "video_audio_mux_report/v1"
LOOP_MODES = {"pingpong", "repeat", "hold"}


@dataclass(frozen=True, slots=True)
class VideoAudioMuxManifest:
    mux_id: str
    manifest_path: Path
    video_path: Path
    audio_path: Path
    output_path: Path
    loop_mode: str
    crf: int
    preset: str

    @classmethod
    def load(cls, manifest_path: str | Path) -> "VideoAudioMuxManifest":
        path = Path(manifest_path).resolve()
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("template") != MANIFEST_TEMPLATE:
            raise ValueError(f"template must be {MANIFEST_TEMPLATE}")
        loop_mode = str(data.get("loop_mode", "pingpong")).strip()
        if loop_mode not in LOOP_MODES:
            choices = ", ".join(sorted(LOOP_MODES))
            raise ValueError(f"loop_mode must be one of: {choices}")
        crf = data.get("crf", 18)
        if not isinstance(crf, int) or isinstance(crf, bool) or not 0 <= crf <= 51:
            raise ValueError("crf must be an integer between 0 and 51")
        preset = str(data.get("preset", "medium")).strip()
        if not preset:
            raise ValueError("preset must be a non-empty string")
        return cls(
            mux_id=_required_string(data, "id"),
            manifest_path=path,
            video_path=_required_path(path, data, "video_path"),
            audio_path=_required_path(path, data, "audio_path"),
            output_path=_required_path(path, data, "output_path"),
            loop_mode=loop_mode,
            crf=crf,
            preset=preset,
        )


def mux_portrait_voiceover(
    manifest_path: str | Path,
    *,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
) -> dict[str, object]:
    manifest = VideoAudioMuxManifest.load(manifest_path)
    if not manifest.video_path.is_file():
        raise FileNotFoundError(f"video not found: {manifest.video_path}")
    if not manifest.audio_path.is_file():
        raise FileNotFoundError(f"audio not found: {manifest.audio_path}")

    video = _probe_video(manifest.video_path, ffprobe=ffprobe)
    audio = _probe_audio(manifest.audio_path, ffprobe=ffprobe)
    filter_complex = _loop_filter(
        manifest.loop_mode,
        frame_count=video["frame_count"],
        fps=video["fps"],
        audio_duration=audio["duration"],
    )
    manifest.output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(manifest.video_path),
        "-i",
        str(manifest.audio_path),
        "-filter_complex",
        filter_complex,
        "-map",
        "[video]",
        "-map",
        "1:a:0",
        "-t",
        f"{audio['duration']:.6f}",
        "-r",
        f"{video['fps']:.6f}",
        "-c:v",
        "libx264",
        "-preset",
        manifest.preset,
        "-crf",
        str(manifest.crf),
        "-pix_fmt",
        "yuv420p",
        "-colorspace",
        "bt709",
        "-color_primaries",
        "bt709",
        "-color_trc",
        "bt709",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        str(manifest.output_path),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"voiceover mux failed:\n{result.stderr[-1600:]}")

    output = _probe_video(manifest.output_path, ffprobe=ffprobe)
    report = {
        "template": REPORT_TEMPLATE,
        "id": manifest.mux_id,
        "video_path": str(manifest.video_path),
        "audio_path": str(manifest.audio_path),
        "output_path": str(manifest.output_path),
        "loop_mode": manifest.loop_mode,
        "source_video": video,
        "source_audio": audio,
        "output": output,
    }
    report_path = manifest.output_path.with_suffix(".mux.report.json")
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    report["report_path"] = str(report_path)
    return report


def _loop_filter(
    loop_mode: str,
    *,
    frame_count: int,
    fps: float,
    audio_duration: float,
) -> str:
    if loop_mode == "pingpong":
        cycle_frames = frame_count * 2
        return (
            "[0:v]split=2[forward][reverse_in];"
            "[reverse_in]reverse[reverse];"
            "[forward][reverse]concat=n=2:v=1:a=0,"
            f"loop=loop=-1:size={cycle_frames}:start=0,"
            f"setpts=N/({fps:.6f}*TB),"
            "format=yuv420p[video]"
        )
    if loop_mode == "repeat":
        return (
            f"[0:v]loop=loop=-1:size={frame_count}:start=0,"
            f"setpts=N/({fps:.6f}*TB),"
            "format=yuv420p[video]"
        )
    return (
        f"[0:v]tpad=stop_mode=clone:stop_duration={audio_duration:.6f},"
        f"fps={fps:.6f},format=yuv420p[video]"
    )


def _probe_video(path: Path, *, ffprobe: str) -> dict[str, object]:
    data = _probe(path, ffprobe=ffprobe)
    stream = next(
        (
            item
            for item in data.get("streams", [])
            if item.get("codec_type") == "video"
        ),
        None,
    )
    if stream is None:
        raise ValueError(f"no video stream: {path}")
    duration = float(data.get("format", {}).get("duration") or 0)
    fps = _parse_rate(stream.get("avg_frame_rate"))
    raw_frames = stream.get("nb_frames")
    frame_count = (
        int(raw_frames)
        if isinstance(raw_frames, str) and raw_frames.isdigit()
        else max(1, round(duration * fps))
    )
    if duration <= 0 or fps <= 0:
        raise ValueError(f"invalid video metadata: {path}")
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "fps": round(fps, 6),
        "frame_count": frame_count,
        "duration": round(duration, 6),
        "codec": stream.get("codec_name"),
        "pixel_format": stream.get("pix_fmt"),
        "audio_present": any(
            item.get("codec_type") == "audio"
            for item in data.get("streams", [])
        ),
    }


def _probe_audio(path: Path, *, ffprobe: str) -> dict[str, object]:
    data = _probe(path, ffprobe=ffprobe)
    stream = next(
        (
            item
            for item in data.get("streams", [])
            if item.get("codec_type") == "audio"
        ),
        None,
    )
    if stream is None:
        raise ValueError(f"no audio stream: {path}")
    duration = float(
        stream.get("duration")
        or data.get("format", {}).get("duration")
        or 0
    )
    if duration <= 0:
        raise ValueError(f"invalid audio duration: {path}")
    return {
        "duration": round(duration, 6),
        "codec": stream.get("codec_name"),
        "sample_rate": (
            int(stream["sample_rate"])
            if str(stream.get("sample_rate", "")).isdigit()
            else None
        ),
        "channels": stream.get("channels"),
    }


def _probe(path: Path, *, ffprobe: str) -> dict[str, object]:
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,codec_name,width,height,avg_frame_rate,nb_frames,"
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
    return json.loads(result.stdout)


def _parse_rate(value: object) -> float:
    if not isinstance(value, str) or "/" not in value:
        raise ValueError("invalid frame rate")
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


def _required_path(
    manifest_path: Path,
    data: dict[str, object],
    key: str,
) -> Path:
    raw = _required_string(data, key)
    path = Path(raw)
    return path if path.is_absolute() else (manifest_path.parent / path).resolve()

