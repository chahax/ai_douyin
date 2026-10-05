"""Reference-anchored appearance transfer for controlled micro-motion video."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageEnhance


def transfer_reference_appearance(
    generated: Image.Image,
    anchor: Image.Image,
    reference: Image.Image,
    mask: Image.Image,
    *,
    motion_gain: float = 0.35,
) -> Image.Image:
    """Transfer only temporal changes while anchoring color and lighting."""
    if motion_gain < 0:
        raise ValueError("motion_gain cannot be negative")

    size = generated.size
    generated_rgb = generated.convert("RGB")
    anchor_rgb = anchor.convert("RGB").resize(size, Image.Resampling.LANCZOS)
    reference_rgb = reference.convert("RGB").resize(size, Image.Resampling.LANCZOS)
    mask_l = mask.convert("L").resize(size, Image.Resampling.LANCZOS)

    positive = ImageChops.subtract(generated_rgb, anchor_rgb)
    negative = ImageChops.subtract(anchor_rgb, generated_rgb)
    if motion_gain != 1.0:
        positive = ImageEnhance.Brightness(positive).enhance(motion_gain)
        negative = ImageEnhance.Brightness(negative).enhance(motion_gain)

    transferred = ImageChops.subtract(
        ImageChops.add(reference_rgb, positive),
        negative,
    )
    return Image.composite(transferred, reference_rgb, mask_l)


def lock_video_appearance(
    input_video: str | Path,
    reference_image: str | Path,
    mask_image: str | Path,
    output_video: str | Path,
    *,
    motion_gain: float = 0.35,
    fps: float | None = None,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
) -> Path:
    """Render a video whose appearance remains anchored to one reference frame."""
    input_path = Path(input_video)
    reference_path = Path(reference_image)
    mask_path = Path(mask_image)
    output_path = Path(output_video)
    for path in (input_path, reference_path, mask_path):
        if not path.is_file():
            raise FileNotFoundError(path)

    resolved_fps = fps or _probe_fps(input_path, ffprobe=ffprobe)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="appearance_lock_") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        input_frames = temp_dir / "input"
        output_frames = temp_dir / "output"
        input_frames.mkdir()
        output_frames.mkdir()

        _run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(input_path),
                str(input_frames / "%06d.png"),
            ]
        )
        frame_paths = sorted(input_frames.glob("*.png"))
        if not frame_paths:
            raise RuntimeError(f"No frames decoded from {input_path}")

        with (
            Image.open(frame_paths[0]) as anchor,
            Image.open(reference_path) as reference,
            Image.open(mask_path) as mask,
        ):
            anchor_copy = anchor.copy()
            reference_copy = reference.copy()
            mask_copy = mask.copy()

        for index, frame_path in enumerate(frame_paths, start=1):
            with Image.open(frame_path) as frame:
                locked = transfer_reference_appearance(
                    frame,
                    anchor_copy,
                    reference_copy,
                    mask_copy,
                    motion_gain=motion_gain,
                )
            locked.save(output_frames / f"{index:06d}.png")

        _run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-framerate",
                f"{resolved_fps:.8f}",
                "-i",
                str(output_frames / "%06d.png"),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(output_path),
            ]
        )
    return output_path


def _probe_fps(path: Path, *, ffprobe: str) -> float:
    completed = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=avg_frame_rate",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
    )
    numerator, denominator = completed.stdout.strip().split("/", maxsplit=1)
    fps = float(numerator) / float(denominator)
    if fps <= 0:
        raise ValueError(f"Invalid frame rate reported for {path}: {fps}")
    return fps


def _run(
    command: list[str],
    *,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    executable = shutil.which(command[0]) or command[0]
    return subprocess.run(
        [executable, *command[1:]],
        check=True,
        capture_output=capture_output,
        text=True,
    )
