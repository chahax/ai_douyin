from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.content_factory.dreamina_cli import (
    DreaminaCLIClient,
    DreaminaCLIConfig,
    DreaminaCLIError,
    dreamina_report_status,
    dreamina_submit_id,
)


def _fake_executable(tmp_path: Path) -> Path:
    executable = tmp_path / "dreamina.exe"
    executable.write_bytes(b"test")
    return executable


def test_build_text2video_defaults_to_seedance_25_vertical_480p(tmp_path: Path) -> None:
    client = DreaminaCLIClient(
        DreaminaCLIConfig(executable=_fake_executable(tmp_path))
    )

    arguments = client.build_video_arguments("街头剧情", duration=4)

    assert arguments[0] == "text2video"
    assert "--model_version=seedance2.5" in arguments
    assert "--ratio=9:16" in arguments
    assert "--video_resolution=480p" in arguments
    assert "--duration=4" in arguments


def test_references_use_multimodal_command_and_local_files(tmp_path: Path) -> None:
    executable = _fake_executable(tmp_path)
    image = tmp_path / "first.png"
    image.write_bytes(b"png")
    client = DreaminaCLIClient(DreaminaCLIConfig(executable=executable))

    arguments = client.build_video_arguments(
        "保持人物一致",
        duration=6,
        reference_images=[image],
    )

    assert arguments[0] == "multimodal2video"
    assert f"--image={image.resolve()}" in arguments


def test_run_extracts_outer_json_around_cli_warnings(tmp_path: Path) -> None:
    executable = _fake_executable(tmp_path)

    def runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='warning\n{"data":{"remaining_credit":88},"status":"ok"}\nfooter',
            stderr="",
        )

    client = DreaminaCLIClient(
        DreaminaCLIConfig(executable=executable), runner=runner
    )

    assert client.user_credit() == {
        "data": {"remaining_credit": 88},
        "status": "ok",
    }


def test_cli_error_keeps_concrete_message(tmp_path: Path) -> None:
    executable = _fake_executable(tmp_path)

    def runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="请先登录")

    client = DreaminaCLIClient(
        DreaminaCLIConfig(executable=executable), runner=runner
    )

    with pytest.raises(DreaminaCLIError, match="请先登录"):
        client.user_credit()


def test_dreamina_status_and_submit_id_mapping() -> None:
    payload = {"submit_id": "task-1", "gen_status": "success"}

    assert dreamina_submit_id(payload) == "task-1"
    assert dreamina_report_status(payload) == "succeeded"
