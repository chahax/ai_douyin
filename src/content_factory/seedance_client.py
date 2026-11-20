"""Seedance asynchronous video-generation client.

The default endpoint is the official BytePlus LAS enhanced video-generation
operator.  The base URL and model ID are configurable so the same client can be
pointed at another official regional endpoint when it exposes the same API.
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

import httpx
from src.content_factory.seedance_models import validate_ark_request
from src.services.provider_call_ledger import ProviderCallLedger


DEFAULT_BASE_URL = "https://operator.las.ap-southeast-1.bytepluses.com/api/v1"
DEFAULT_MODEL = "dreamina-seedance-2-5-260628"
ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
ARK_MINI_MODEL = "doubao-seedance-2-0-mini-260615"
TASKS_PATH = "/contents/generations/tasks"
SUPPORTED_RATIOS = {"16:9", "4:3", "1:1", "3:4", "9:16", "21:9", "adaptive"}
SUPPORTED_RESOLUTIONS = {"480p", "720p"}
TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "expired"}


class SeedanceError(RuntimeError):
    """Base error for Seedance integration."""


class SeedanceConfigurationError(SeedanceError):
    """Raised when authentication or client configuration is incomplete."""


class SeedanceAPIError(SeedanceError):
    """Raised when the remote API returns an invalid or failed response."""
    def __init__(self,message,*,status_code=None,error_code=None):
        super().__init__(message)
        self.status_code=status_code
        self.error_code=error_code


@dataclass(frozen=True)
class SeedanceConfig:
    api_key: str = field(repr=False)
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout_seconds: float = 120.0
    poll_interval_seconds: float = 5.0
    provider: str = "byteplus_api"

    @classmethod
    def from_env(cls, provider: str | None = None, *, require_key: bool = True) -> "SeedanceConfig":
        """Load configuration without ever accepting a key on the command line."""

        # Reload settings so a newly saved key works without restarting callers.
        from src.shared.config import Settings
        current = Settings()
        provider = provider or current.SEEDANCE_PROVIDER
        if provider == "ark_api":
            api_key = current.ARK_API_KEY
            base_url, model = current.ARK_BASE_URL, current.ARK_SEEDANCE_MODEL
            key_name = "ARK_API_KEY"
        elif provider == "byteplus_api":
            api_key = current.SEEDANCE_API_KEY or os.getenv("LAS_API_KEY", "").strip()
            base_url, model = current.SEEDANCE_BASE_URL, current.SEEDANCE_MODEL
            key_name = "SEEDANCE_API_KEY"
        else:
            raise SeedanceConfigurationError("Choose ark_api or byteplus_api for API authentication")
        if not api_key and require_key:
            raise SeedanceConfigurationError(
                f"{key_name} is missing; set it in .env or the process environment"
            )
        return cls(
            api_key=api_key if require_key else "dry-run",
            base_url=base_url,
            model=model,
            timeout_seconds=current.SEEDANCE_TIMEOUT_SECONDS,
            poll_interval_seconds=current.SEEDANCE_POLL_INTERVAL_SECONDS,
            provider=provider,
        )


@dataclass(frozen=True)
class SeedanceReference:
    kind: str
    source: str
    role: str

    def to_content(self) -> dict[str, Any]:
        if self.kind not in {"image", "video", "audio"}:
            raise ValueError(f"unsupported reference kind: {self.kind}")
        if not self.source:
            raise ValueError("reference source must not be empty")
        roles={'image':{'reference_image','first_frame','last_frame'},'video':{'reference_video'},'audio':{'reference_audio'}}
        if self.role not in roles[self.kind]:raise ValueError('Reference role does not match its media type')
        allowed_prefixes = ("http://", "https://", "asset://")
        data_prefix = f"data:{self.kind}/"
        if not self.source.startswith(allowed_prefixes) and not self.source.startswith(
            data_prefix
        ):
            raise ValueError(
                "reference source must be a public URL, asset:// ID, or supported data URL"
            )
        if self.kind == "video" and self.source.startswith("data:"):
            raise ValueError("video references do not support base64 data URLs")
        return {
            "type": f"{self.kind}_url",
            f"{self.kind}_url": {"url": self.source},
            "role": self.role,
        }


class SeedanceClient:
    """Small synchronous client for task creation, polling, and download."""

    def __init__(
        self,
        config: SeedanceConfig,
        *,
        http_client: httpx.Client | None = None,
        ledger_path: str | Path | None = None,
        record_calls: bool | None = None,
    ) -> None:
        if not config.api_key:
            raise SeedanceConfigurationError("Seedance API key must not be empty")
        if not config.base_url.startswith("https://"):
            raise SeedanceConfigurationError("Seedance base URL must use HTTPS")
        self.config = config
        self._owns_client = http_client is None
        self._http = http_client or httpx.Client(
            timeout=config.timeout_seconds,
            follow_redirects=True,
        )
        if record_calls is None:
            # Injected HTTP clients are normally unit-test doubles.  Supplying an
            # explicit ledger_path still opts those tests/tools into recording.
            record_calls = http_client is None or ledger_path is not None
        self._call_ledger = (
            ProviderCallLedger(ledger_path) if record_calls else None
        )

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    def __enter__(self) -> "SeedanceClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def build_task_payload(
        self,
        prompt: str,
        *,
        duration: int,
        ratio: str = "9:16",
        resolution: str = "480p",
        generate_audio: bool = True,
        watermark: bool = False,
        return_last_frame: bool = True,
        seed: int | None = None,
        references: Iterable[SeedanceReference] = (),
        callback_url: str | None = None,
        task_type: str = 'auto',
        output_format: str | None = None,
    ) -> dict[str, Any]:
        prompt = prompt.strip()
        if not prompt:
            raise ValueError("prompt must not be empty")
        references=list(references)
        for reference in references:reference.to_content()
        extras={}
        if self.config.provider=='ark_api':
            extras=validate_ark_request(self.config.model,duration,resolution,ratio,references,task_type,output_format)
        elif type(duration) is not int or not 4<=duration<=30:
            raise ValueError(f'{self.config.model} duration must be an integer between 4 and 30 seconds')
        if ratio not in SUPPORTED_RATIOS:
            raise ValueError(f"unsupported ratio: {ratio}")
        if self.config.provider!='ark_api' and resolution not in SUPPORTED_RESOLUTIONS:
            raise ValueError(
                "This Seedance integration supports 480p or 720p output"
            )

        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        content.extend(reference.to_content() for reference in references)
        payload: dict[str, Any] = {
            "model": self.config.model,
            "content": content,
            "generate_audio": generate_audio,
            "resolution": resolution,
            "ratio": ratio,
            "duration": duration,
            "watermark": watermark,
            "return_last_frame": return_last_frame,
        }
        payload.update(extras)
        if seed is not None:
            payload["seed"] = seed
        if callback_url:
            payload["callback_url"] = callback_url
        return payload

    def create_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        call_id = ""
        if self._call_ledger is not None:
            call_id = self._call_ledger.begin_call(
                provider=self.config.provider,
                operation="video_generation",
                model=str(payload.get("model") or self.config.model),
                request=payload,
            )
        try:
            response = self._request("POST", TASKS_PATH, json=payload)
            task_id = response.get("id")
            if not isinstance(task_id, str) or not task_id:
                raise SeedanceAPIError("create-task response did not contain a task id")
        except Exception as exc:
            if self._call_ledger is not None and call_id:
                status_code = getattr(exc, "status_code", None)
                failure_status = (
                    "request_rejected"
                    if isinstance(status_code, int) and 400 <= status_code < 500
                    else "submit_outcome_unknown"
                )
                try:
                    self._call_ledger.mark_failed(
                        call_id,
                        exc,
                        status=failure_status,
                        http_status=status_code,
                        error_code=getattr(exc, "error_code", None),
                    )
                except Exception:
                    # The original provider failure is more important than a
                    # secondary attempt to enrich its ledger row.
                    pass
            raise
        if self._call_ledger is not None and call_id:
            self._call_ledger.mark_submitted(
                call_id,
                task_id=task_id,
                status="submitted",
                response=response,
            )
        return response

    def get_task(self, task_id: str) -> dict[str, Any]:
        task_id = _validated_task_id(task_id)
        response = self._request("GET", f"{TASKS_PATH}/{task_id}")
        status = response.get("status")
        if not isinstance(status, str):
            raise SeedanceAPIError("task response did not contain a valid status")
        if self._call_ledger is not None:
            self._call_ledger.update_task(
                provider=self.config.provider,
                task_id=task_id,
                status=status,
                response=response,
            )
        return response

    def wait_for_task(
        self,
        task_id: str,
        *,
        timeout_seconds: float = 1800,
        poll_interval_seconds: float | None = None,
        on_update: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        interval = (
            self.config.poll_interval_seconds
            if poll_interval_seconds is None
            else poll_interval_seconds
        )
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if interval < 0:
            raise ValueError("poll_interval_seconds must not be negative")

        deadline = time.monotonic() + timeout_seconds
        previous_status: str | None = None
        while True:
            task = self.get_task(task_id)
            status = str(task["status"])
            if on_update is not None and status != previous_status:
                on_update(task)
            previous_status = status
            if status in TERMINAL_STATUSES:
                if status != "succeeded":
                    raise SeedanceAPIError(
                        f"Seedance task {task_id} ended with status {status}: "
                        f"{_safe_error_text(task.get('error'))}"
                    )
                return task
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Seedance task {task_id} did not finish within {timeout_seconds:g}s"
                )
            if interval:
                time.sleep(interval)

    def download_video(
        self,
        task: dict[str, Any],
        output_path: str | Path,
    ) -> Path:
        return self._download_content(task, output_path, "video_url")

    def download_last_frame(self, task: dict[str, Any], output_path: str | Path) -> Path:
        """Save the provider's original last frame without sending API credentials."""
        return self._download_content(task, output_path, "last_frame_url")

    def _download_content(self, task, output_path, field):
        if task.get("status") != "succeeded":
            raise SeedanceAPIError("only a succeeded task can be downloaded")
        content = task.get("content")
        video_url = content.get(field) if isinstance(content, dict) else None
        if not isinstance(video_url, str) or not video_url.startswith("https://"):
            raise SeedanceAPIError(f"succeeded task did not contain a valid HTTPS {field}")

        destination = Path(output_path).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".part")
        try:
            with self._http.stream("GET", video_url) as response:
                response.raise_for_status()
                with temporary.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        handle.write(chunk)
            temporary.replace(destination)
        except Exception:
            if temporary.exists():
                temporary.unlink()
            raise
        return destination

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{self.config.base_url.rstrip('/')}/{path.lstrip('/')}"
        request_headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        request_headers.update(kwargs.pop("headers", {}))
        try:
            response = self._http.request(
                method,
                url,
                headers=request_headers,
                **kwargs,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = _safe_response_text(exc.response).replace(self.config.api_key,'[redacted]')
            try:error_code=exc.response.json().get('error',{}).get('code')
            except (ValueError,AttributeError):error_code=None
            raise SeedanceAPIError(
                f"Seedance API returned HTTP {exc.response.status_code}: {body}",
                status_code=exc.response.status_code,error_code=error_code,
            ) from exc
        except httpx.HTTPError as exc:
            raise SeedanceAPIError(f"Seedance API request failed: {exc}") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise SeedanceAPIError("Seedance API returned non-JSON content") from exc
        if not isinstance(payload, dict):
            raise SeedanceAPIError("Seedance API returned a non-object JSON response")
        return payload


def load_prompt_pack_segment(
    prompt_pack: dict[str, Any], segment_selector: str
) -> tuple[dict[str, Any], str, int]:
    if prompt_pack.get("schema") != "analysis_video_prompt_pack/v1":
        raise ValueError("prompt pack must use analysis_video_prompt_pack/v1")
    segments = prompt_pack.get("segments")
    if not isinstance(segments, list):
        raise ValueError("prompt pack segments must be an array")

    selector = segment_selector.strip().lower()
    selected: dict[str, Any] | None = None
    for candidate in segments:
        if not isinstance(candidate, dict):
            continue
        source = candidate.get("source")
        shot_number = source.get("shot_number") if isinstance(source, dict) else None
        identifiers = {
            str(candidate.get("id", "")).lower(),
            str(shot_number or "").lower(),
        }
        if selector in identifiers:
            selected = candidate
            break
    if selected is None:
        raise ValueError(f"segment not found in prompt pack: {segment_selector}")

    prompts = selected.get("prompts")
    prompt = prompts.get("video_prompt_zh") if isinstance(prompts, dict) else None
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError(f"segment {segment_selector} has no video_prompt_zh")
    generation = selected.get("generation")
    raw_duration = generation.get("duration_seconds") if isinstance(generation, dict) else 4
    try:
        duration = int(math.ceil(float(raw_duration)))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"segment {segment_selector} has invalid duration") from exc
    duration = max(4, min(duration, 30))
    return selected, prompt.strip(), duration


def _validated_task_id(task_id: str) -> str:
    task_id = task_id.strip()
    if not task_id or not all(char.isalnum() or char in {"-", "_"} for char in task_id):
        raise ValueError("invalid Seedance task id")
    return task_id


def _safe_response_text(response: httpx.Response) -> str:
    try:
        text = response.text
    except Exception:
        return "unreadable response"
    return " ".join(text.split())[:1000] or "empty response"


def _safe_error_text(error: Any) -> str:
    if error is None:
        return "no error details"
    return " ".join(str(error).split())[:1000]
