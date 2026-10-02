#!/usr/bin/env python
"""Generate one audio-driven face crop and paste it into the reviewed plate.

This wrapper is intentionally single-shot and fail-closed.  It must be launched
with the dedicated SadTalker interpreter.  The full-frame result is transcoded
to the production 704x1248/25fps contract and an immutable audit JSON binds the
source plate, dialogue audio, intermediate crop and final MP4 by SHA-256.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any


SCHEMA = "fanqie_sadtalker_fullframe/v1"
FACE_BLEND_MARGIN_FRACTION = 0.025


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _run(command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None,
         timeout: int = 7200) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed ({result.returncode}): {command[0]}\n"
            f"STDERR: {(result.stderr or '')[-3000:]}\n"
            f"STDOUT: {(result.stdout or '')[-3000:]}"
        )
    return result


def _probe(path: Path) -> dict[str, Any]:
    result = _run([
        "ffprobe", "-v", "error", "-show_streams", "-show_format",
        "-of", "json", str(path),
    ], timeout=60)
    payload = json.loads(result.stdout)
    streams = payload.get("streams") or []
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    if not isinstance(video, dict):
        raise RuntimeError(f"No video stream: {path}")
    rate = str(video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1")
    try:
        numerator, denominator = rate.split("/", 1)
        denominator_value = float(denominator)
        if denominator_value == 0:
            raise ValueError("zero frame-rate denominator")
        fps = float(numerator) / denominator_value
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Invalid video frame rate {rate!r}: {path}") from exc
    duration = float((payload.get("format") or {}).get("duration") or video.get("duration") or 0)
    return {
        "duration_seconds": round(duration, 6),
        "fps": round(fps, 6),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "video_codec": str(video.get("codec_name") or ""),
        "pixel_format": str(video.get("pix_fmt") or ""),
        "audio_codec": str(audio.get("codec_name") or "") if audio else "",
        "has_audio": audio is not None,
        "video_frame_count": int(video.get("nb_frames") or 0),
    }


def _write_json_new(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
    except FileExistsError as exc:
        raise RuntimeError(f"Refusing to replace existing audit evidence: {path}") from exc


def _sadtalker_environment(temp_dir: Path) -> dict[str, str]:
    """Return the isolated SadTalker environment used by the audited wrapper.

    This SadTalker environment's Numba/librosa combination can spin forever in
    ``tempfile._mkstemp_inner`` while enabling decorator caches.  Disabling the
    optional JIT keeps the same Python implementations and makes the import
    deterministic; the setting is recorded in the immutable audit payload.
    """
    env = os.environ.copy()
    env["TEMP"] = str(temp_dir)
    env["TMP"] = str(temp_dir)
    env["NUMBA_DISABLE_JIT"] = "1"
    return env


def _plate_preservation_metrics(
    source: Path,
    video: Path,
    face_crop_quad: tuple[int, int, int, int],
) -> dict[str, Any]:
    """Verify the reviewed plate outside the explicitly animated face crop.

    SadTalker is expected to change pixels inside ``face_crop_quad``.  Treating
    those pixels as background made expressive but valid motion fail the old
    whole-frame gate.  The crop (plus a small blend margin) is therefore
    excluded from the pass/fail background metric, while both the face-region
    and whole-frame differences remain recorded for human/audit inspection.
    """
    import cv2  # type: ignore
    import numpy as np  # type: ignore

    anchor = cv2.imread(str(source))
    if anchor is None:
        raise RuntimeError(f"OpenCV could not read source plate: {source}")
    source_height, source_width = anchor.shape[:2]
    lx, ly, rx, ry = face_crop_quad
    if not (0 <= lx < rx <= source_width and 0 <= ly < ry <= source_height):
        raise RuntimeError(
            f"Face crop quad is outside source plate {source_width}x{source_height}: "
            f"{face_crop_quad}"
        )
    capture = cv2.VideoCapture(str(video))
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    if frame_count < 3:
        capture.release()
        raise RuntimeError("Full-frame output has too few frames for plate validation")
    samples: list[dict[str, Any]] = []
    for fraction in (0.15, 0.50, 0.85):
        index = round((frame_count - 1) * fraction)
        capture.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = capture.read()
        if not ok or frame is None:
            capture.release()
            raise RuntimeError(f"Could not read plate-validation frame {index}")
        resized = cv2.resize(
            anchor, (frame.shape[1], frame.shape[0]), interpolation=cv2.INTER_LANCZOS4
        )
        frame_height, frame_width = frame.shape[:2]
        scale_x = frame_width / source_width
        scale_y = frame_height / source_height
        # Paste-back blending can touch pixels immediately outside the raw crop.
        # A 2.5% frame margin keeps the measured paste-back transition out of
        # the background gate without relaxing any background-difference limit.
        margin_x = max(2, round(frame_width * FACE_BLEND_MARGIN_FRACTION))
        margin_y = max(2, round(frame_height * FACE_BLEND_MARGIN_FRACTION))
        scaled_lx = max(0, round(lx * scale_x) - margin_x)
        scaled_ly = max(0, round(ly * scale_y) - margin_y)
        scaled_rx = min(frame_width, round(rx * scale_x) + margin_x)
        scaled_ry = min(frame_height, round(ry * scale_y) + margin_y)
        face_mask = np.zeros((frame_height, frame_width), dtype=bool)
        face_mask[scaled_ly:scaled_ry, scaled_lx:scaled_rx] = True
        background_mask = ~face_mask
        background_fraction = float(background_mask.mean())
        if background_fraction < 0.15:
            capture.release()
            raise RuntimeError(
                "Face crop leaves less than 15% of the frame available for "
                "background plate validation"
            )
        difference = np.mean(
            np.abs(frame.astype(np.int16) - resized.astype(np.int16)), axis=2
        )

        def region_metrics(mask: Any) -> dict[str, float]:
            values = difference[mask]
            return {
                "mean_absolute_difference": round(float(values.mean()), 6),
                "changed_pixel_fraction_over_12": round(
                    float((values > 12.0).mean()), 6
                ),
                "difference_percentile_95": round(
                    float(np.quantile(values, 0.95)), 6
                ),
            }

        background = region_metrics(background_mask)
        face = region_metrics(face_mask)
        whole_frame = region_metrics(np.ones_like(face_mask, dtype=bool))
        mean_abs = background["mean_absolute_difference"]
        changed_fraction = background["changed_pixel_fraction_over_12"]
        percentile_95 = background["difference_percentile_95"]
        passed = mean_abs <= 6.0 and changed_fraction <= 0.08 and percentile_95 <= 12.0
        samples.append({
            "fraction": fraction,
            "frame_index": index,
            # Backwards-compatible top-level names now deliberately represent
            # the pass/fail background region, not the animated face crop.
            **background,
            "background_region": background,
            "animated_face_region": face,
            "whole_frame_diagnostic": whole_frame,
            "passed": passed,
        })
    capture.release()
    return {
        "method": "face_masked_scaled_reviewed_plate_rgb_absdiff/v2",
        "face_crop_quad_source_pixels": [lx, ly, rx, ry],
        "face_blend_margin_fraction": FACE_BLEND_MARGIN_FRACTION,
        "background_pixel_fraction": round(background_fraction, 6),
        "thresholds": {
            "mean_absolute_difference_max": 6.0,
            "changed_pixel_fraction_over_12_max": 0.08,
            "difference_percentile_95_max": 12.0,
        },
        "samples": samples,
        "passed": all(item["passed"] for item in samples),
    }


def _newest_result(directory: Path, started_at: float) -> Path:
    candidates = [
        path for path in directory.glob("*.mp4")
        if path.is_file() and path.stat().st_mtime >= started_at - 2
    ]
    if len(candidates) != 1:
        raise RuntimeError(
            f"Expected exactly one fresh SadTalker MP4 under {directory}, "
            f"found {len(candidates)}"
        )
    return candidates[0]


def _publish_validated_output(
    *, source: Path, temporary_output: Path, output: Path,
    face_crop_quad: tuple[int, int, int, int],
) -> tuple[str, dict[str, Any]]:
    """Validate before exclusive publication and always remove the temporary file."""
    try:
        plate_preservation = _plate_preservation_metrics(
            source, temporary_output, face_crop_quad
        )
        if plate_preservation["passed"] is not True:
            raise RuntimeError(
                f"Full-frame plate preservation check failed: {plate_preservation}"
            )
        output_sha = _sha256(temporary_output)
        try:
            # Hard-link publication is atomic and exclusive: a concurrent writer
            # or stale path can never be overwritten.
            os.link(temporary_output, output)
        except FileExistsError as exc:
            raise RuntimeError(f"Refusing to replace existing output: {output}") from exc
        except OSError as exc:
            raise RuntimeError(
                "Could not atomically publish output with an exclusive hard link; "
                "work-dir and output must be on the same filesystem"
            ) from exc
        return output_sha, plate_preservation
    finally:
        temporary_output.unlink(missing_ok=True)


def _write_audit_or_remove_output(
    *, output: Path, audit_path: Path, payload: dict[str, Any]
) -> None:
    """Never retain a published video without its immutable audit receipt."""
    try:
        _write_json_new(audit_path, payload)
    except Exception:
        output.unlink(missing_ok=True)
        raise


def _publish_with_audit_receipt(
    *,
    source: Path,
    audio: Path,
    crop_video: Path,
    pasted: Path,
    temporary_output: Path,
    output: Path,
    audit_path: Path,
    face_crop_quad: tuple[int, int, int, int],
    payload_context: dict[str, Any],
) -> dict[str, Any]:
    """Hash every input before making the externally visible output immutable."""
    input_bindings = {
        "source_image_path": str(source),
        "source_image_sha256": _sha256(source),
        "dialogue_audio_path": str(audio),
        "dialogue_audio_sha256": _sha256(audio),
        "raw_crop_video_path": str(crop_video.resolve()),
        "raw_crop_video_sha256": _sha256(crop_video),
        "pasted_source_resolution_path": str(pasted.resolve()),
        "pasted_source_resolution_sha256": _sha256(pasted),
    }
    output_sha, plate_preservation = _publish_validated_output(
        source=source,
        temporary_output=temporary_output,
        output=output,
        face_crop_quad=face_crop_quad,
    )
    payload = {
        "schema": SCHEMA,
        "created_at_epoch": round(time.time(), 3),
        **input_bindings,
        "output_path": str(output),
        "output_sha256": output_sha,
        "face_crop_quad": list(face_crop_quad),
        "plate_preservation": plate_preservation,
        **payload_context,
    }
    _write_audit_or_remove_output(
        output=output, audit_path=audit_path, payload=payload
    )
    return payload


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-image", type=Path, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--sadtalker-root", type=Path, required=True)
    parser.add_argument("--checkpoint-dir", type=Path, required=True)
    parser.add_argument("--width", type=int, default=704)
    parser.add_argument("--height", type=int, default=1248)
    parser.add_argument("--fps", type=int, default=25)
    parser.add_argument("--expression-scale", type=float, default=0.58)
    parser.add_argument("--timeout-seconds", type=int, default=7200)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    source = args.source_image.resolve()
    audio = args.audio.resolve()
    output = args.output.resolve()
    audit_path = args.audit.resolve()
    work_dir = args.work_dir.resolve()
    root = args.sadtalker_root.resolve()
    checkpoint_dir = args.checkpoint_dir.resolve()

    if not source.is_file() or not audio.is_file():
        raise FileNotFoundError("source image and audio must both exist")
    if output.exists() or audit_path.exists() or work_dir.exists():
        raise RuntimeError("output, audit and work-dir must all be new paths")
    if args.width <= 0 or args.height <= 0 or args.fps <= 0:
        raise ValueError("width, height and fps must be positive")
    if not (0.1 <= args.expression_scale <= 1.5):
        raise ValueError("expression-scale outside reviewed range 0.1..1.5")
    inference = root / "inference.py"
    if not inference.is_file() or not checkpoint_dir.is_dir():
        raise FileNotFoundError("SadTalker inference.py/checkpoint directory missing")
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("ffmpeg and ffprobe are required")

    work_dir.mkdir(parents=True, exist_ok=False)
    result_dir = work_dir / "raw_result"
    temp_dir = work_dir / "temp"
    result_dir.mkdir()
    temp_dir.mkdir()
    env = _sadtalker_environment(temp_dir)

    started_at = time.time()
    _run([
        sys.executable, str(inference),
        "--driven_audio", str(audio),
        "--source_image", str(source),
        "--checkpoint_dir", str(checkpoint_dir),
        "--result_dir", str(result_dir),
        "--size", "256", "--preprocess", "crop", "--still",
        "--expression_scale", f"{args.expression_scale:.6f}",
        "--pose_style", "0", "--batch_size", "2",
    ], cwd=root, env=env, timeout=args.timeout_seconds)
    crop_video = _newest_result(result_dir, started_at)

    sys.path.insert(0, str(root))
    import cv2  # type: ignore
    from src.utils.croper import Preprocesser  # type: ignore
    from src.utils.paste_pic import paste_pic  # type: ignore

    frame = cv2.imread(str(source))
    if frame is None:
        raise RuntimeError(f"OpenCV could not read source image: {source}")
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    preprocessor = Preprocesser("cuda")
    _, crop, quad = preprocessor.crop([rgb], still=False, xsize=512)
    lx, ly, rx, ry = (int(value) for value in quad)
    if rx <= lx or ry <= ly:
        raise RuntimeError(f"Invalid face crop quad: {quad}")
    crop_info = ((rx - lx, ry - ly), crop, quad)
    pasted = work_dir / "pasted_source_resolution.mp4"
    paste_pic(
        str(crop_video), str(source), crop_info, str(audio), str(pasted),
        extended_crop=False,
    )
    if not pasted.is_file():
        raise RuntimeError("SadTalker paste-back did not create a full-frame MP4")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = work_dir / f"final_{uuid.uuid4().hex}.mp4"
    _run([
        "ffmpeg", "-y", "-v", "error", "-i", str(pasted), "-i", str(audio),
        "-map", "0:v:0", "-map", "1:a:0",
        "-vf", f"scale={args.width}:{args.height}:flags=lanczos,fps={args.fps}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart", "-shortest", str(temporary_output),
    ], timeout=300)
    probe = _probe(temporary_output)
    if (
        probe["width"] != args.width
        or probe["height"] != args.height
        or abs(float(probe["fps"]) - args.fps) > 0.01
        or probe["video_codec"] != "h264"
        or probe["pixel_format"] != "yuv420p"
        or probe["has_audio"] is not True
    ):
        raise RuntimeError(f"Full-frame output contract failed: {probe}")
    audio_probe = _probe_audio_duration(audio)
    if abs(float(probe["duration_seconds"]) - audio_probe) > 0.12:
        raise RuntimeError(
            f"Output/audio duration mismatch: {probe['duration_seconds']} vs {audio_probe}"
        )
    payload = _publish_with_audit_receipt(
        source=source,
        audio=audio,
        crop_video=crop_video,
        pasted=pasted,
        temporary_output=temporary_output,
        output=output,
        audit_path=audit_path,
        face_crop_quad=(lx, ly, rx, ry),
        payload_context={
            "expression_scale": args.expression_scale,
            "pose_style": 0,
            "preprocess": "crop",
            "still": True,
            "numba_disable_jit": True,
            "output_probe": probe,
            "audio_duration_seconds": round(audio_probe, 6),
            "sadtalker_root": str(root),
            "checkpoint_dir": str(checkpoint_dir),
            "python_executable": str(Path(sys.executable).resolve()),
        },
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _probe_audio_duration(path: Path) -> float:
    result = _run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ], timeout=60)
    return float(result.stdout.strip())


if __name__ == "__main__":
    raise SystemExit(main())
