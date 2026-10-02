"""Safe subprocess adapter for the official Dreamina (即梦) CLI.

The adapter never invokes a shell. Arguments are passed as a list so prompts
and local file paths cannot be interpreted as commands. Paid generation is
only performed by callers that explicitly invoke :meth:`submit_video`.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CLI_PATH = "data/tools/dreamina/dreamina.exe"
DEFAULT_MODEL_VERSION = "seedance2.5"
SUPPORTED_RATIOS = {"1:1", "3:4", "16:9", "4:3", "9:16", "21:9"}
SUPPORTED_RESOLUTIONS = {"480p", "720p", "1080p"}
TERMINAL_STATUSES = {"success", "fail"}


class DreaminaCLIError(RuntimeError):
    """Raised when the Dreamina executable or a CLI operation fails."""


@dataclass(frozen=True)
class DreaminaCLIConfig:
    executable: Path
    model_version: str = DEFAULT_MODEL_VERSION
    timeout_seconds: float = 120.0
    poll_interval_seconds: float = 3.0

    @classmethod
    def from_settings(cls) -> "DreaminaCLIConfig":
        from src.shared.config import settings

        # Streamlit can hot-reload this module while retaining an older
        # Settings singleton. Defaults keep the page usable until a full app
        # restart replaces that singleton.
        executable = Path(getattr(settings, "DREAMINA_CLI_PATH", DEFAULT_CLI_PATH))
        if not executable.is_absolute():
            executable = PROJECT_ROOT / executable
        return cls(
            executable=executable.resolve(),
            model_version=getattr(
                settings, "DREAMINA_MODEL_VERSION", DEFAULT_MODEL_VERSION
            ),
            timeout_seconds=float(
                getattr(settings, "DREAMINA_CLI_TIMEOUT_SECONDS", 120)
            ),
            poll_interval_seconds=float(
                getattr(settings, "DREAMINA_CLI_POLL_INTERVAL_SECONDS", 3)
            ),
        )


@dataclass(frozen=True)
class DreaminaCommandResult:
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    payload: dict[str, Any] | None


class DreaminaCLIClient:
    """Read account state and submit official Dreamina CLI tasks."""

    def __init__(
        self,
        config: DreaminaCLIConfig,
        *,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self.config = config
        self._runner = runner

    @property
    def installed(self) -> bool:
        return self.config.executable.is_file()

    def run(
        self,
        arguments: Sequence[str],
        *,
        timeout_seconds: float | None = None,
        check: bool = True,
    ) -> DreaminaCommandResult:
        if not self.installed:
            raise DreaminaCLIError(
                f"Dreamina CLI executable not found: {self.config.executable}"
            )
        command = [str(self.config.executable), *map(str, arguments)]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            completed = self._runner(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=(
                    self.config.timeout_seconds
                    if timeout_seconds is None
                    else timeout_seconds
                ),
                check=False,
                shell=False,
                creationflags=creationflags,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise DreaminaCLIError(f"Dreamina CLI could not be started: {exc}") from exc

        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        result = DreaminaCommandResult(
            command=tuple(command),
            returncode=int(completed.returncode),
            stdout=stdout,
            stderr=stderr,
            payload=_extract_last_json_object(f"{stdout}\n{stderr}"),
        )
        if check and result.returncode != 0:
            detail = _safe_cli_error_text(stderr or stdout)
            raise DreaminaCLIError(
                f"Dreamina CLI exited with code {result.returncode}: {detail}"
            )
        return result

    def version(self) -> dict[str, Any]:
        result = self.run(["version"])
        return result.payload or {"raw": result.stdout.strip()}

    def user_credit(self) -> dict[str, Any]:
        """Return the authoritative balance exposed by the logged-in CLI."""

        result = self.run(["user_credit"])
        return result.payload or {"raw": result.stdout.strip()}

    def build_video_arguments(
        self,
        prompt: str,
        *,
        duration: int,
        ratio: str = "9:16",
        resolution: str = "480p",
        session: int = 0,
        reference_images: Iterable[str | Path] = (),
        reference_videos: Iterable[str | Path] = (),
        reference_audio: Iterable[str | Path] = (),
        poll_seconds: int = 0,
    ) -> list[str]:
        prompt = prompt.strip()
        if not prompt:
            raise ValueError("prompt must not be empty")
        if duration < 4 or duration > 30:
            raise ValueError("Dreamina Seedance 2.5 duration must be between 4 and 30 seconds")
        if ratio not in SUPPORTED_RATIOS:
            raise ValueError(f"Dreamina CLI does not support ratio: {ratio}")
        if resolution not in SUPPORTED_RESOLUTIONS:
            raise ValueError(f"Dreamina CLI does not support resolution: {resolution}")
        if session < 0:
            raise ValueError("Dreamina session id must not be negative")
        if poll_seconds < 0:
            raise ValueError("poll_seconds must not be negative")

        images = _validated_local_files(reference_images, "image")
        videos = _validated_local_files(reference_videos, "video")
        audio = _validated_local_files(reference_audio, "audio")
        has_references = bool(images or videos or audio)
        arguments = ["multimodal2video" if has_references else "text2video"]
        arguments.extend(
            [
                f"--prompt={prompt}",
                f"--model_version={self.config.model_version}",
                f"--duration={duration}",
                f"--ratio={ratio}",
                f"--video_resolution={resolution}",
                f"--session={session}",
                f"--poll={poll_seconds}",
            ]
        )
        for path in images:
            arguments.append(f"--image={path}")
        for path in videos:
            arguments.append(f"--video={path}")
        for path in audio:
            arguments.append(f"--audio={path}")
        return arguments

    def submit_video(self, arguments: Sequence[str]) -> dict[str, Any]:
        """Submit one paid task and return the CLI JSON response."""

        poll_seconds = _argument_int(arguments, "--poll")
        result = self.run(
            arguments,
            timeout_seconds=max(self.config.timeout_seconds, poll_seconds + 30),
        )
        if result.payload is None:
            raise DreaminaCLIError("Dreamina CLI returned no JSON task response")
        return result.payload

    def query_result(
        self,
        submit_id: str,
        *,
        download_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        submit_id = _validated_submit_id(submit_id)
        arguments = ["query_result", f"--submit_id={submit_id}"]
        if download_dir is not None:
            directory = Path(download_dir).resolve()
            directory.mkdir(parents=True, exist_ok=True)
            arguments.append(f"--download_dir={directory}")
        result = self.run(arguments)
        if result.payload is None:
            raise DreaminaCLIError("Dreamina CLI returned no JSON query response")
        return result.payload

    def wait_for_result(
        self,
        submit_id: str,
        *,
        initial: dict[str, Any] | None = None,
        timeout_seconds: float = 1800,
        on_update: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        deadline = time.monotonic() + timeout_seconds
        current = initial or self.query_result(submit_id)
        previous_status = ""
        while True:
            status = _generation_status(current)
            if on_update is not None and status != previous_status:
                on_update(current)
            previous_status = status
            if status in TERMINAL_STATUSES:
                if status == "fail":
                    reason = current.get("fail_reason") or current.get("message") or "unknown"
                    raise DreaminaCLIError(
                        f"Dreamina task {submit_id} failed: {_safe_cli_error_text(str(reason))}"
                    )
                return current
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Dreamina task {submit_id} did not finish within {timeout_seconds:g}s"
                )
            time.sleep(self.config.poll_interval_seconds)
            current = self.query_result(submit_id)


def dreamina_report_status(payload: dict[str, Any]) -> str:
    """Translate Dreamina status names to the shared report status names."""

    status = _generation_status(payload)
    return {
        "success": "succeeded",
        "fail": "failed",
        "querying": "running",
    }.get(status, status or "submitted")


def dreamina_submit_id(payload: dict[str, Any]) -> str:
    value = payload.get("submit_id") or payload.get("id")
    return str(value).strip() if value is not None else ""


def _generation_status(payload: dict[str, Any]) -> str:
    value = payload.get("gen_status") or payload.get("status")
    return str(value).strip().lower() if value is not None else ""


def _extract_last_json_object(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    payloads: list[dict[str, Any]] = []
    index = 0
    while index < len(text):
        start = text.find("{", index)
        if start < 0:
            break
        try:
            value, consumed = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            index = start + 1
            continue
        if isinstance(value, dict):
            payloads.append(value)
        index = start + max(consumed, 1)
    return payloads[-1] if payloads else None


def _validated_local_files(
    values: Iterable[str | Path], kind: str
) -> list[Path]:
    paths: list[Path] = []
    for value in values:
        path = Path(value).expanduser().resolve()
        if not path.is_file():
            raise ValueError(f"Dreamina {kind} reference file not found: {path}")
        paths.append(path)
    return paths


def _validated_submit_id(value: str) -> str:
    value = value.strip()
    if not value or not all(character.isalnum() or character in {"-", "_"} for character in value):
        raise ValueError("invalid Dreamina submit id")
    return value


def _argument_int(arguments: Sequence[str], name: str) -> int:
    prefix = f"{name}="
    for argument in arguments:
        if argument.startswith(prefix):
            try:
                return int(argument[len(prefix) :])
            except ValueError:
                return 0
    return 0


def _safe_cli_error_text(value: str) -> str:
    return " ".join(value.split())[:1000] or "empty response"
