"""Atomic, local checkpoints for resumable collection jobs."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol


_SAFE_JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class CheckpointError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CollectionCheckpoint:
    job_id: str
    status: str
    cursor: dict[str, Any] = field(default_factory=dict)
    pages_processed: int = 0
    items_collected: int = 0
    stop_reason: str | None = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: int = 1

    def __post_init__(self) -> None:
        _validate_job_id(self.job_id)
        if not self.status:
            raise ValueError("status cannot be empty")
        if self.pages_processed < 0 or self.items_collected < 0:
            raise ValueError("checkpoint counters cannot be negative")
        if self.updated_at.tzinfo is None or self.updated_at.utcoffset() is None:
            raise ValueError("updated_at must be timezone-aware")
        if self.schema_version != 1:
            raise ValueError("unsupported checkpoint schema_version")
        sensitive_path = _find_sensitive_path(self.cursor)
        if sensitive_path:
            raise ValueError(f"sensitive data is not allowed in checkpoints: {sensitive_path}")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["updated_at"] = self.updated_at.isoformat()
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CollectionCheckpoint":
        try:
            updated_at = datetime.fromisoformat(str(payload["updated_at"]))
            return cls(
                job_id=str(payload["job_id"]),
                status=str(payload["status"]),
                cursor=dict(payload.get("cursor") or {}),
                pages_processed=int(payload.get("pages_processed", 0)),
                items_collected=int(payload.get("items_collected", 0)),
                stop_reason=payload.get("stop_reason"),
                updated_at=updated_at,
                schema_version=int(payload.get("schema_version", 0)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CheckpointError(f"invalid checkpoint payload: {exc}") from exc


class CheckpointStore(Protocol):
    def save(self, checkpoint: CollectionCheckpoint) -> Path | None: ...

    def load(self, job_id: str) -> CollectionCheckpoint | None: ...

    def clear(self, job_id: str) -> None: ...


class FileCheckpointStore:
    """One JSON file per job, written through fsync + atomic replace."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, job_id: str) -> Path:
        _validate_job_id(job_id)
        return self.root / f"{job_id}.checkpoint.json"

    def save(self, checkpoint: CollectionCheckpoint) -> Path:
        target = self.path_for(checkpoint.job_id)
        serialized = json.dumps(
            checkpoint.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.root,
                prefix=f".{checkpoint.job_id}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_name = temporary.name
                temporary.write(serialized)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, target)
        except OSError as exc:
            if temporary_name:
                Path(temporary_name).unlink(missing_ok=True)
            raise CheckpointError(f"failed to save checkpoint: {exc}") from exc
        return target

    def load(self, job_id: str) -> CollectionCheckpoint | None:
        target = self.path_for(job_id)
        if not target.exists():
            return None
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CheckpointError(f"failed to load checkpoint: {exc}") from exc
        if not isinstance(payload, dict):
            raise CheckpointError("invalid checkpoint payload: expected an object")
        checkpoint = CollectionCheckpoint.from_dict(payload)
        if checkpoint.job_id != job_id:
            raise CheckpointError("checkpoint job_id does not match requested job")
        return checkpoint

    def clear(self, job_id: str) -> None:
        try:
            self.path_for(job_id).unlink(missing_ok=True)
        except OSError as exc:
            raise CheckpointError(f"failed to clear checkpoint: {exc}") from exc


def _validate_job_id(job_id: str) -> None:
    if not _SAFE_JOB_ID.fullmatch(job_id):
        raise ValueError("job_id must be 1-128 safe filename characters")


_SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "cookies",
    "set_cookie",
    "password",
    "secret",
    "access_token",
    "refresh_token",
    "id_token",
    "session_token",
    "storage_state",
    "local_storage",
    "localstorage",
}


def _find_sensitive_path(value: Any, path: str = "cursor") -> str | None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized_key = str(key).strip().lower().replace("-", "_")
            nested_path = f"{path}.{key}"
            if normalized_key in _SENSITIVE_KEYS:
                return nested_path
            found = _find_sensitive_path(nested, nested_path)
            if found:
                return found
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            found = _find_sensitive_path(nested, f"{path}[{index}]")
            if found:
                return found
    return None
