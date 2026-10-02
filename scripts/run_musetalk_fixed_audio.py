from __future__ import annotations

import runpy
import sys
import os
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import numpy as np
import soundfile as sf
import yaml


MUSETALK_DIR = Path(r"D:\IT\MuseTalk")
CACHE_DIR = Path(r"D:\IT\ai_douyin\data\cache\musetalk")


def _option_value(argv: list[str], name: str, *, default: str = "") -> str:
    """Return one exact CLI option value without accepting abbreviated flags."""
    try:
        index = argv.index(name)
    except ValueError:
        return default
    if index + 1 >= len(argv) or argv[index + 1].startswith("--"):
        raise ValueError(f"{name} requires a value")
    return argv[index + 1]


def _preserved_result_frame_dirs(argv: list[str]) -> set[Path]:
    """Derive only the rendered-frame directories owned by this invocation.

    MuseTalk 1.5 deletes its rendered PNG sequence before returning.  The
    caller needs that exact sequence to rebuild an MP4 when MuseTalk's own
    ffmpeg assembly silently truncates the video stream.  Source-extraction
    frames and every directory outside ``--result_dir/<version>`` remain under
    MuseTalk's normal cleanup behavior.
    """
    config_value = _option_value(argv, "--inference_config")
    result_value = _option_value(argv, "--result_dir")
    version = _option_value(argv, "--version", default="v15")
    if not config_value or not result_value:
        raise ValueError("MuseTalk wrapper requires --inference_config and --result_dir")
    if not version or Path(version).name != version or version in {".", ".."}:
        raise ValueError(f"Unsafe MuseTalk --version value: {version!r}")

    config_path = Path(config_value).resolve(strict=True)
    result_root = Path(result_value).resolve(strict=False)
    version_root = (result_root / version).resolve(strict=False)
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not payload:
        raise ValueError("MuseTalk inference config must contain at least one task")

    protected: set[Path] = set()
    for task_id, task in payload.items():
        if not isinstance(task, dict):
            raise ValueError(f"MuseTalk task {task_id!r} must be a mapping")
        video_path = str(task.get("video_path") or "")
        audio_path = str(task.get("audio_path") or "")
        if not video_path or not audio_path:
            raise ValueError(f"MuseTalk task {task_id!r} requires video_path and audio_path")
        # Match upstream inference.py exactly: basename, then split at the
        # first dot rather than Path.stem's last-dot behavior.
        video_base = os.path.basename(video_path).split(".")[0]
        audio_base = os.path.basename(audio_path).split(".")[0]
        if not video_base or not audio_base:
            raise ValueError(f"MuseTalk task {task_id!r} has an unsafe media basename")
        frame_dir = (version_root / f"{video_base}_{audio_base}").resolve(strict=False)
        if frame_dir.parent != version_root:
            raise ValueError(f"MuseTalk task {task_id!r} escapes the result directory")
        protected.add(frame_dir)
    return protected


@contextmanager
def _preserve_rendered_frames(argv: list[str]) -> Iterator[set[Path]]:
    """Temporarily suppress deletion of only the current rendered PNG dirs."""
    protected = _preserved_result_frame_dirs(argv)
    original_rmtree = shutil.rmtree

    def guarded_rmtree(path, *args, **kwargs):
        resolved = Path(path).resolve(strict=False)
        if resolved in protected:
            print(f"Preserving rendered MuseTalk frames for caller validation: {resolved}")
            return None
        return original_rmtree(path, *args, **kwargs)

    shutil.rmtree = guarded_rmtree
    try:
        yield protected
    finally:
        shutil.rmtree = original_rmtree


def soundfile_audio_feature(self, wav_path, start_index=0, weight_dtype=None):
    del start_index
    samples, sampling_rate = sf.read(wav_path, dtype="float32", always_2d=False)
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    if sampling_rate != 16000:
        raise ValueError(f"MuseTalk fixed reader requires 16 kHz PCM, got {sampling_rate}: {wav_path}")
    segment_length = 30 * sampling_rate
    segments = [samples[i:i + segment_length] for i in range(0, len(samples), segment_length)]
    features = []
    for segment in segments:
        feature = self.feature_extractor(segment, return_tensors="pt", sampling_rate=sampling_rate).input_features
        if weight_dtype is not None:
            feature = feature.to(dtype=weight_dtype)
        features.append(feature)
    return features, len(samples)


def main() -> int:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(CACHE_DIR / "huggingface"))
    os.environ.setdefault("TRANSFORMERS_CACHE", str(CACHE_DIR / "transformers"))
    os.environ.setdefault("NUMBA_CACHE_DIR", str(CACHE_DIR / "numba"))
    os.environ["TEMP"] = str(CACHE_DIR)
    os.environ["TMP"] = str(CACHE_DIR)
    sys.path.insert(0, str(MUSETALK_DIR))
    from musetalk.utils.audio_processor import AudioProcessor

    AudioProcessor.get_audio_feature = soundfile_audio_feature
    inference = MUSETALK_DIR / "scripts" / "inference.py"
    forwarded_argv = list(sys.argv[1:])
    sys.argv = [str(inference), *forwarded_argv]
    with _preserve_rendered_frames(forwarded_argv):
        runpy.run_path(str(inference), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
