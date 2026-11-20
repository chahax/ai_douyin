from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from scripts.run_musetalk_fixed_audio import (
    _preserve_rendered_frames,
    _preserved_result_frame_dirs,
)


def _argv(tmp_path: Path) -> tuple[list[str], Path, Path]:
    result_root = tmp_path / "result"
    config = tmp_path / "task.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "task_1": {
                    "video_path": str(tmp_path / "clip.aligned.mp4"),
                    "audio_path": str(tmp_path / "dialogue.aligned.wav"),
                    "result_name": "output.mp4",
                }
            }
        ),
        encoding="utf-8",
    )
    argv = [
        "--inference_config", str(config),
        "--result_dir", str(result_root),
        "--version", "v15",
    ]
    expected = result_root / "v15" / "clip_dialogue"
    return argv, result_root, expected


def test_preserved_frame_dir_matches_musetalk_first_dot_naming(tmp_path):
    argv, _, expected = _argv(tmp_path)
    assert _preserved_result_frame_dirs(argv) == {expected.resolve()}


def test_rmtree_guard_preserves_only_rendered_frames_and_restores(tmp_path):
    argv, result_root, expected = _argv(tmp_path)
    source_frames = result_root / "v15" / "clip"
    expected.mkdir(parents=True)
    source_frames.mkdir(parents=True)
    (expected / "00000000.png").write_bytes(b"rendered")
    (source_frames / "00000000.png").write_bytes(b"source")
    original = shutil.rmtree

    with _preserve_rendered_frames(argv):
        shutil.rmtree(expected)
        shutil.rmtree(source_frames)
        assert expected.is_dir()
        assert not source_frames.exists()

    assert shutil.rmtree is original
    shutil.rmtree(expected)
    assert not expected.exists()


@pytest.mark.parametrize(
    "argv, message",
    [
        (["--result_dir", "result"], "--inference_config"),
        (["--inference_config", "task.yaml"], "--result_dir"),
        (
            [
                "--inference_config", "task.yaml",
                "--result_dir", "result",
                "--version", "../outside",
            ],
            "Unsafe MuseTalk --version",
        ),
    ],
)
def test_preservation_contract_rejects_missing_or_unsafe_options(
    tmp_path, monkeypatch, argv, message,
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "task.yaml").write_text(
        yaml.safe_dump(
            {"task": {"video_path": "video.mp4", "audio_path": "audio.wav"}}
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=message):
        _preserved_result_frame_dirs(argv)
