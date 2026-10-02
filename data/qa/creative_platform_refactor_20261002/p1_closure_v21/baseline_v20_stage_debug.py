"""Versioned debug controls around the existing creative stage runner.

This module does not call models or media providers. It records immutable
snapshots of validated stage outputs, exposes read/compare operations, and
binds user feedback to the exact output hash that was inspected.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEBUG_SCHEMA = "creative_stage_debug_index/v1"
ARTIFACT_SCHEMA = "creative_stage_artifact/v1"
FEEDBACK_SCHEMA = "creative_stage_feedback/v1"
_SAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]+")


class CreativeStageBreakpointReached(RuntimeError):
    """Non-failure control signal emitted after a validated stage is saved."""

    def __init__(self, stage_name: str, reason: str):
        super().__init__(f"creative stage breakpoint reached: {stage_name}")
        self.stage_name = stage_name
        self.reason = reason


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def pending_must_fix_feedback(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Return immutable must-fix records that lack a revised-output binding."""
    return [
        row for row in state.get("debug_feedback", [])
        if row.get("disposition") == "must_fix"
        and not row.get("resolved_by_output_sha256")
    ]


def replayable_resolved_stage_feedback(
    run_dir: Path,
    state: dict[str, Any],
    stage_name: str,
) -> list[dict[str, Any]]:
    """Rebuild the exact repair context only while its validated output is current."""
    current = next((
        row for row in reversed(state.get("stages", []))
        if row.get("name") == stage_name
    ), None)
    if current is None:
        return []
    run_root = Path(run_dir).resolve()
    replay = []
    for row in state.get("debug_feedback", []):
        if (row.get("stage_id") != stage_name
                or row.get("disposition") != "must_fix"
                or row.get("resolved_by_output_sha256") != current.get("output_sha256")):
            continue
        feedback_path = (run_root / row["receipt"]).resolve()
        resolution_path = (run_root / row.get("resolution_receipt", "")).resolve()
        if (not feedback_path.is_relative_to(run_root)
                or not resolution_path.is_relative_to(run_root)):
            raise ValueError("feedback replay receipt escaped the run directory")
        feedback = _read(feedback_path)
        resolution = _read(resolution_path)
        if (feedback.get("feedback_id") != row.get("feedback_id")
                or feedback.get("stage_id") != stage_name
                or feedback.get("output_sha256") != row.get("output_sha256")
                or resolution.get("schema") != "creative_stage_feedback_resolution/v1"
                or resolution.get("feedback_id") != row.get("feedback_id")
                or resolution.get("stage_id") != stage_name
                or resolution.get("feedback_sha256") != _hash(feedback)
                or resolution.get("previous_output_sha256") != row.get("output_sha256")
                or resolution.get("resolved_by_output_sha256") != current.get("output_sha256")):
            raise ValueError("resolved feedback replay binding changed")
        replay.append({
            "feedback_id": row["feedback_id"],
            "message": feedback["message"],
            "evidence": feedback.get("evidence", []),
            "previous_output_sha256": row["output_sha256"],
        })
    return replay


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _debug_root(run_dir: Path) -> Path:
    return Path(run_dir) / ".creative_debug"


def _safe_stage(stage_name: str) -> str:
    safe = _SAFE_NAME.sub("_", stage_name).strip("._")
    if not safe:
        raise ValueError("stage name is empty")
    return safe


def _load_index(run_dir: Path) -> dict[str, Any]:
    path = _debug_root(run_dir) / "index.json"
    if not path.exists():
        return {"schema": DEBUG_SCHEMA, "stages": {}}
    value = _read(path)
    if value.get("schema") != DEBUG_SCHEMA or not isinstance(value.get("stages"), dict):
        raise ValueError("creative stage debug index is invalid")
    return value


def record_stage_artifact(
    run_dir: Path,
    state: dict[str, Any],
    stage_name: str,
    role: str,
    output: dict[str, Any],
) -> dict[str, Any]:
    """Persist one immutable, hash-addressed validated stage output."""
    matching = [row for row in state.get("stages", []) if row.get("name") == stage_name]
    if not matching:
        raise ValueError(f"validated stage is missing from state: {stage_name}")
    stage_state = matching[-1]
    output_hash = _hash(output)
    if stage_state.get("output_sha256") != output_hash:
        receipt_path = Path(run_dir) / f"{stage_name}.json"
        if not receipt_path.is_file():
            raise ValueError(f"stage output hash mismatch: {stage_name}")
        receipt = _read(receipt_path)
        output = receipt.get("output")
        output_hash = _hash(output)
        if (receipt.get("status") != "validated"
                or receipt.get("output_sha256") != output_hash
                or stage_state.get("output_sha256") != output_hash):
            raise ValueError(f"stage output hash mismatch: {stage_name}")
    safe = _safe_stage(stage_name)
    relative = Path("artifacts") / safe / f"{output_hash}.json"
    path = _debug_root(run_dir) / relative
    artifact = {
        "schema": ARTIFACT_SCHEMA,
        "stage_id": stage_name,
        "role": role,
        "input_sha256": stage_state.get("input_sha256"),
        "output_sha256": output_hash,
        "prompt_version": state.get("writer_prompt_version"),
        "model_profile": state.get("model_profile"),
        "rule_binding": state.get("rule_registry_binding"),
        "review_policy": state.get("review_policy_version"),
        "budget_scope": {
            "policy_version": state.get("budget_policy_version"),
            "max_calls": state.get("max_calls"),
            "max_total_tokens": state.get("max_total_tokens"),
        },
        "output": output,
    }
    if path.exists():
        if _read(path) != artifact:
            raise RuntimeError(f"immutable stage artifact changed: {stage_name}")
    else:
        _write_atomic(path, artifact)

    index = _load_index(run_dir)
    versions = index["stages"].setdefault(stage_name, [])
    entry = {
        "output_sha256": output_hash,
        "input_sha256": stage_state.get("input_sha256"),
        "artifact": str(relative).replace("\\", "/"),
    }
    if entry not in versions:
        versions.append(entry)
        index["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_atomic(_debug_root(run_dir) / "index.json", index)
    return entry


def stage_snapshot(run_dir: Path) -> dict[str, Any]:
    """Return a verified, readable stage list without executing the workflow."""
    run_dir = Path(run_dir).resolve()
    state_path = run_dir / "state.json"
    if not state_path.is_file():
        raise FileNotFoundError(state_path)
    state = _read(state_path)
    index = _load_index(run_dir)
    validity = state.get("debug_stage_validity", {})
    rows = []
    for ordinal, stage in enumerate(state.get("stages", []), 1):
        name = stage.get("name")
        versions = index["stages"].get(name, [])
        current_hash = stage.get("output_sha256")
        artifact = next(
            (row for row in reversed(versions) if row.get("output_sha256") == current_hash),
            None,
        )
        artifact_verified = False
        artifact_path = None
        if artifact is not None:
            artifact_path = (_debug_root(run_dir) / artifact["artifact"]).resolve()
            if not artifact_path.is_relative_to(_debug_root(run_dir).resolve()):
                raise ValueError("stage artifact escaped the debug directory")
            saved = _read(artifact_path)
            artifact_verified = (
                saved.get("schema") == ARTIFACT_SCHEMA
                and saved.get("stage_id") == name
                and saved.get("output_sha256") == current_hash
                and _hash(saved.get("output")) == current_hash
            )
            if not artifact_verified:
                raise ValueError(f"stage artifact verification failed: {name}")
        rows.append({
            "ordinal": ordinal,
            "stage_id": name,
            "role": stage.get("role"),
            "input_sha256": stage.get("input_sha256"),
            "output_sha256": current_hash,
            "version_count": len(versions),
            "artifact": str(artifact_path) if artifact_path else None,
            "artifact_verified": artifact_verified,
            "validity": validity.get(name, "current"),
            "usage": stage.get("usage", {}),
        })
    return {
        "schema": "creative_stage_snapshot/v1",
        "run_dir": str(run_dir),
        "workflow_status": state.get("status"),
        "breakpoint": state.get("debug_breakpoint"),
        "feedback_status": state.get("debug_feedback_status"),
        "calls_started": state.get("calls_started", 0),
        "budget_policy_version": state.get("budget_policy_version"),
        "stages": rows,
    }


def compare_stage_versions(
    run_dir: Path,
    stage_name: str,
    *,
    base_sha256: str | None = None,
    target_sha256: str | None = None,
) -> dict[str, Any]:
    """Compare two immutable stage versions as a unified JSON diff."""
    run_dir = Path(run_dir).resolve()
    versions = _load_index(run_dir)["stages"].get(stage_name, [])
    if len(versions) < 2 and not (base_sha256 and target_sha256):
        raise ValueError(f"stage has fewer than two recorded versions: {stage_name}")
    by_hash = {row["output_sha256"]: row for row in versions}
    base_sha256 = base_sha256 or versions[-2]["output_sha256"]
    target_sha256 = target_sha256 or versions[-1]["output_sha256"]
    if base_sha256 == target_sha256 or base_sha256 not in by_hash or target_sha256 not in by_hash:
        raise ValueError("stage comparison hashes are invalid")

    def load(row):
        path = (_debug_root(run_dir) / row["artifact"]).resolve()
        if not path.is_relative_to(_debug_root(run_dir).resolve()):
            raise ValueError("stage artifact escaped the debug directory")
        value = _read(path)
        if _hash(value.get("output")) != row["output_sha256"]:
            raise ValueError("stage artifact content hash mismatch")
        return json.dumps(value["output"], ensure_ascii=False, indent=2, sort_keys=True).splitlines()

    diff = "\n".join(difflib.unified_diff(
        load(by_hash[base_sha256]),
        load(by_hash[target_sha256]),
        fromfile=base_sha256,
        tofile=target_sha256,
        lineterm="",
    ))
    return {
        "schema": "creative_stage_comparison/v1",
        "stage_id": stage_name,
        "base_sha256": base_sha256,
        "target_sha256": target_sha256,
        "diff": diff,
    }


def record_stage_feedback(
    run_dir: Path,
    stage_name: str,
    message: str,
    *,
    disposition: str = "must_fix",
    evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Bind user feedback to the currently recorded output of one stage."""
    if disposition not in ("must_fix", "suggestion"):
        raise ValueError("feedback disposition must be must_fix or suggestion")
    message = message.strip()
    if not message:
        raise ValueError("feedback message is empty")
    run_dir = Path(run_dir).resolve()
    snapshot = stage_snapshot(run_dir)
    stages = snapshot["stages"]
    selected = next((row for row in stages if row["stage_id"] == stage_name), None)
    if selected is None or not selected["artifact_verified"]:
        raise ValueError("feedback requires a verified current stage artifact")
    payload = {
        "stage_id": stage_name,
        "output_sha256": selected["output_sha256"],
        "disposition": disposition,
        "message": message,
        "evidence": evidence or [],
    }
    feedback_id = _hash(payload)[:20]
    receipt = {
        "schema": FEEDBACK_SCHEMA,
        "feedback_id": feedback_id,
        **payload,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    path = _debug_root(run_dir) / "feedback" / _safe_stage(stage_name) / f"{feedback_id}.json"
    if path.exists():
        existing = _read(path)
        if {key: existing.get(key) for key in payload} != payload:
            raise RuntimeError("feedback receipt conflicts with existing immutable record")
        receipt = existing
    else:
        _write_atomic(path, receipt)

    state_path = run_dir / "state.json"
    state = _read(state_path)
    summaries = state.setdefault("debug_feedback", [])
    summary = {
        "feedback_id": feedback_id,
        "stage_id": stage_name,
        "output_sha256": selected["output_sha256"],
        "disposition": disposition,
        "receipt": str(path.relative_to(run_dir)).replace("\\", "/"),
    }
    if summary not in summaries:
        summaries.append(summary)
    if disposition == "must_fix":
        state["debug_feedback_status"] = "revision_required"
        validity = state.setdefault("debug_stage_validity", {})
        seen = False
        for row in stages:
            if row["stage_id"] == stage_name:
                seen = True
                validity[row["stage_id"]] = "needs_revision"
            elif seen:
                validity[row["stage_id"]] = "invalidated"
    else:
        state.setdefault("debug_feedback_status", "suggestions_recorded")
    _write_atomic(state_path, state)
    return receipt


def resolve_stage_feedback(
    run_dir: Path,
    state: dict[str, Any],
    stage_name: str,
    output_sha256: str,
) -> list[str]:
    """Resolve only feedback whose exact stage has a different validated output."""
    summaries = state.get("debug_feedback", [])
    pending = [
        row for row in pending_must_fix_feedback(state)
        if row.get("stage_id") == stage_name
    ]
    if not pending:
        return []
    resolved_ids = []
    for row in pending:
        if row.get("output_sha256") == output_sha256:
            raise ValueError("must-fix feedback requires a revised stage output")
        feedback_path = (Path(run_dir) / row["receipt"]).resolve()
        if not feedback_path.is_relative_to(Path(run_dir).resolve()):
            raise ValueError("feedback receipt escaped the run directory")
        feedback = _read(feedback_path)
        if (feedback.get("feedback_id") != row.get("feedback_id")
                or feedback.get("stage_id") != stage_name
                or feedback.get("output_sha256") != row.get("output_sha256")):
            raise ValueError("must-fix feedback receipt binding changed")
        resolution = {
            "schema": "creative_stage_feedback_resolution/v1",
            "feedback_id": row["feedback_id"],
            "stage_id": stage_name,
            "feedback_sha256": _hash(feedback),
            "previous_output_sha256": row["output_sha256"],
            "resolved_by_output_sha256": output_sha256,
            "resolved_at": datetime.now(timezone.utc).isoformat(),
        }
        resolution_path = feedback_path.with_name(
            feedback_path.stem + ".resolution.json"
        )
        if resolution_path.exists() and _read(resolution_path) != resolution:
            raise RuntimeError("feedback resolution receipt conflicts with existing record")
        if not resolution_path.exists():
            _write_atomic(resolution_path, resolution)
        row["resolved_by_output_sha256"] = output_sha256
        row["resolution_receipt"] = str(
            resolution_path.relative_to(Path(run_dir).resolve())
        ).replace("\\", "/")
        resolved_ids.append(row["feedback_id"])
    state.setdefault("debug_stage_validity", {})[stage_name] = "current"
    still_pending = bool(pending_must_fix_feedback(state))
    state["debug_feedback_status"] = (
        "revision_required" if still_pending else "resolved"
    )
    return resolved_ids


class CreativeStageCommandService:
    """Shared command layer used by CLI and Streamlit debug controls."""

    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir)

    def inspect(self) -> dict[str, Any]:
        return stage_snapshot(self.run_dir)

    def compare(
        self,
        stage_name: str,
        *,
        base_sha256: str | None = None,
        target_sha256: str | None = None,
    ) -> dict[str, Any]:
        return compare_stage_versions(
            self.run_dir,
            stage_name,
            base_sha256=base_sha256,
            target_sha256=target_sha256,
        )

    def feedback(
        self,
        stage_name: str,
        message: str,
        *,
        disposition: str = "must_fix",
    ) -> dict[str, Any]:
        return record_stage_feedback(
            self.run_dir,
            stage_name,
            message,
            disposition=disposition,
        )
