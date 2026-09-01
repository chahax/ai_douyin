"""Atomic, profile-based persistence for manual workflow node selections."""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.workflow.registry import WorkflowNodeRegistry


SCHEMA_VERSION = "workflow_node_selection/v1"
_PROFILE_PATTERN = re.compile(r"^[A-Za-z0-9_\-\u4e00-\u9fff]{1,48}$")


class WorkflowSelectionError(RuntimeError):
    pass


class WorkflowSelectionConflict(WorkflowSelectionError):
    pass


@dataclass(frozen=True, slots=True)
class WorkflowProfile:
    name: str
    description: str
    selections: dict[str, str]


@dataclass(frozen=True, slots=True)
class WorkflowSelectionSnapshot:
    revision: int
    active_profile: str
    updated_at: str
    profiles: dict[str, WorkflowProfile]

    @property
    def active(self) -> WorkflowProfile:
        return self.profiles[self.active_profile]


class WorkflowSelectionStore:
    """Read and update workflow profiles without requiring an app restart."""

    def __init__(self, path: str | Path, registry: WorkflowNodeRegistry) -> None:
        self.path = Path(path)
        self.registry = registry
        self._lock = threading.RLock()

    def load(self) -> WorkflowSelectionSnapshot:
        with self._lock:
            if not self.path.exists():
                return self._default_snapshot()
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise WorkflowSelectionError(f"cannot read workflow selections: {exc}") from exc
            return self._parse(data)

    def resolve(self, stage: str, requested: str | None = None) -> str:
        if requested and requested not in {"workflow_default", "current", "active"}:
            self.registry.get(stage, requested)
            return requested
        snapshot = self.load()
        return snapshot.active.selections[stage]

    def save_profile(
        self,
        name: str,
        selections: dict[str, str],
        *,
        description: str = "",
        activate: bool = False,
        expected_revision: int | None = None,
    ) -> WorkflowSelectionSnapshot:
        self._validate_profile_name(name)
        normalized = self.registry.normalize_selections(selections)
        with self._lock:
            current = self.load()
            self._check_revision(current, expected_revision)
            profiles = dict(current.profiles)
            profiles[name] = WorkflowProfile(
                name=name,
                description=description.strip(),
                selections=normalized,
            )
            active_profile = name if activate else current.active_profile
            updated = WorkflowSelectionSnapshot(
                revision=current.revision + 1,
                active_profile=active_profile,
                updated_at=self._now(),
                profiles=profiles,
            )
            self._write(updated)
            return updated

    def activate(
        self,
        name: str,
        *,
        expected_revision: int | None = None,
    ) -> WorkflowSelectionSnapshot:
        with self._lock:
            current = self.load()
            self._check_revision(current, expected_revision)
            if name not in current.profiles:
                raise WorkflowSelectionError(f"unknown workflow profile: {name}")
            if name == current.active_profile:
                return current
            updated = WorkflowSelectionSnapshot(
                revision=current.revision + 1,
                active_profile=name,
                updated_at=self._now(),
                profiles=dict(current.profiles),
            )
            self._write(updated)
            return updated

    def clone_profile(
        self,
        source: str,
        target: str,
        *,
        description: str = "",
        expected_revision: int | None = None,
    ) -> WorkflowSelectionSnapshot:
        self._validate_profile_name(target)
        with self._lock:
            current = self.load()
            self._check_revision(current, expected_revision)
            if source not in current.profiles:
                raise WorkflowSelectionError(f"unknown workflow profile: {source}")
            if target in current.profiles:
                raise WorkflowSelectionError(f"workflow profile already exists: {target}")
            profiles = dict(current.profiles)
            profiles[target] = WorkflowProfile(
                name=target,
                description=description.strip(),
                selections=dict(current.profiles[source].selections),
            )
            updated = WorkflowSelectionSnapshot(
                revision=current.revision + 1,
                active_profile=current.active_profile,
                updated_at=self._now(),
                profiles=profiles,
            )
            self._write(updated)
            return updated

    def _default_snapshot(self) -> WorkflowSelectionSnapshot:
        profile = WorkflowProfile(
            name="production",
            description="默认生产工作流",
            selections=self.registry.default_selections(),
        )
        return WorkflowSelectionSnapshot(
            revision=0,
            active_profile=profile.name,
            updated_at="",
            profiles={profile.name: profile},
        )

    def _parse(self, data: Any) -> WorkflowSelectionSnapshot:
        if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
            raise WorkflowSelectionError(f"schema_version must be {SCHEMA_VERSION}")
        revision = data.get("revision")
        active_profile = data.get("active_profile")
        raw_profiles = data.get("profiles")
        if not isinstance(revision, int) or revision < 0:
            raise WorkflowSelectionError("revision must be a non-negative integer")
        if not isinstance(active_profile, str) or not isinstance(raw_profiles, dict) or not raw_profiles:
            raise WorkflowSelectionError("active_profile and profiles are required")
        profiles: dict[str, WorkflowProfile] = {}
        for name, value in raw_profiles.items():
            self._validate_profile_name(name)
            if not isinstance(value, dict):
                raise WorkflowSelectionError(f"profile {name} must be an object")
            raw_selections = value.get("selections")
            if not isinstance(raw_selections, dict) or not all(
                isinstance(key, str) and isinstance(item, str)
                for key, item in raw_selections.items()
            ):
                raise WorkflowSelectionError(f"profile {name}.selections must be an object of strings")
            try:
                normalized = self.registry.normalize_selections(raw_selections)
            except (KeyError, ValueError) as exc:
                raise WorkflowSelectionError(f"invalid profile {name}: {exc}") from exc
            profiles[name] = WorkflowProfile(
                name=name,
                description=str(value.get("description") or ""),
                selections=normalized,
            )
        if active_profile not in profiles:
            raise WorkflowSelectionError("active_profile does not exist in profiles")
        return WorkflowSelectionSnapshot(
            revision=revision,
            active_profile=active_profile,
            updated_at=str(data.get("updated_at") or ""),
            profiles=profiles,
        )

    def _write(self, snapshot: WorkflowSelectionSnapshot) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "revision": snapshot.revision,
            "active_profile": snapshot.active_profile,
            "updated_at": snapshot.updated_at,
            "profiles": {
                name: {
                    "description": profile.description,
                    "selections": profile.selections,
                }
                for name, profile in snapshot.profiles.items()
            },
        }
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
                temporary_path = Path(handle.name)
            os.replace(temporary_path, self.path)
        except OSError as exc:
            raise WorkflowSelectionError(f"cannot save workflow selections: {exc}") from exc
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink(missing_ok=True)

    @staticmethod
    def _check_revision(
        current: WorkflowSelectionSnapshot,
        expected_revision: int | None,
    ) -> None:
        if expected_revision is not None and current.revision != expected_revision:
            raise WorkflowSelectionConflict(
                f"workflow profile changed: expected revision {expected_revision}, "
                f"current revision {current.revision}"
            )

    @staticmethod
    def _validate_profile_name(name: str) -> None:
        if not isinstance(name, str) or not _PROFILE_PATTERN.fullmatch(name):
            raise WorkflowSelectionError(
                "profile name must be 1-48 Chinese letters, ASCII letters, digits, _ or -"
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
