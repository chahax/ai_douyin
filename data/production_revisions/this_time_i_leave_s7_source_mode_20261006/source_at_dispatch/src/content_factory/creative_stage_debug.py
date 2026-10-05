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


def current_stage_records(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep logical stage order while selecting the latest validated record."""
    current = {}
    for row in state.get("stages", []):
        current[row["name"]] = row
    return list(current.values())


def stage_dependencies(state: dict[str, Any]) -> dict[str, list[str]]:
    """Conservative prerequisites, independent of revision execution order.

    Older runs have no graph: bootstrap from their first traversal, never from
    later repair order. Field-level compatibility and pruning are later work.
    """
    graph = state.get("debug_stage_dependencies")
    if graph is None:
        names = [row["name"] for row in current_stage_records(state)]
        graph = {name: names[i - 1:i] if i else [] for i, name in enumerate(names)}
    if not isinstance(graph, dict):
        raise ValueError("invalid stage dependency graph")
    for name, parents in graph.items():
        if not isinstance(parents, list) or any(parent not in graph for parent in parents):
            raise ValueError(f"unknown stage prerequisite: {name}")
        stage_ancestors(graph, name)
    return graph


def stage_ancestors(graph: dict[str, list[str]], name: str) -> set[str]:
    ancestors = set()

    def visit(node, path):
        if node in path:
            raise ValueError("cyclic stage dependency graph")
        for parent in graph.get(node, []):
            if parent not in ancestors:
                visit(parent, path | {node})
                ancestors.add(parent)

    visit(name, set())
    return ancestors


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
    relative = Path("artifacts") / safe / f"{output_hash}__{stage_state.get('input_sha256')}.json"
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
    current = current_stage_records(state)
    history = []
    latest_ordinals = {row["name"]: i for i, row in enumerate(state.get("stages", []), 1)}
    for ordinal, stage in enumerate(state.get("stages", []), 1):
        name = stage.get("name")
        versions = index["stages"].get(name, [])
        current_hash = stage.get("output_sha256")
        artifact = next(
            (row for row in reversed(versions)
             if row.get("output_sha256") == current_hash
             and row.get("input_sha256") == stage.get("input_sha256")),
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
                and saved.get("input_sha256") == stage.get("input_sha256")
                and _hash(saved.get("output")) == current_hash
            )
            if not artifact_verified:
                raise ValueError(f"stage artifact verification failed: {name}")
        is_current = latest_ordinals[name] == ordinal
        if is_current and artifact_verified:
            receipt_path = run_dir / f"{_safe_stage(name)}.json"
            receipt = _read(receipt_path) if receipt_path.exists() else {}
            def matches_current(value):
                return (value.get("status") == "validated"
                        and value.get("output_sha256") == current_hash
                        and _hash(value.get("output")) == current_hash
                        and value.get("input_sha256") == stage.get("input_sha256"))
            if not matches_current(receipt):
                # While a repair is in flight the last validated version remains viewable.
                # A changed/tampered validated receipt is never excused by this fallback.
                in_flight_repair = (
                    receipt.get("status") != "validated"
                    and receipt.get("input_sha256") != stage.get("input_sha256")
                    and (run_dir / ".creative_execution.lock").exists()
                    and any(x["stage_id"] == name for x in pending_must_fix_feedback(state))
                )
                archived = any(matches_current(_read(p)) for p in run_dir.glob(f"{_safe_stage(name)}__before_feedback_*.json")) if in_flight_repair else False
                if not archived:
                    raise ValueError(f"current stage receipt verification failed: {name}")
        row = {
            "ordinal": ordinal,
            "stage_id": name,
            "role": stage.get("role"),
            "input_sha256": stage.get("input_sha256"),
            "output_sha256": current_hash,
            "version_count": len(versions),
            "artifact": str(artifact_path) if artifact_path else None,
            "artifact_verified": artifact_verified,
            "validity": validity.get(name, "current") if is_current else "historical",
            "usage": stage.get("usage", {}),
        }
        history.append(row)
        if is_current:
            rows.append(row)
    by_name = {row["stage_id"]: row for row in rows}
    rows = [by_name[row["name"]] for row in current]
    return {
        "schema": "creative_stage_snapshot/v1",
        "run_dir": str(run_dir),
        "workflow_status": state.get("status"),
        "breakpoint": state.get("debug_breakpoint"),
        "feedback_status": state.get("debug_feedback_status"),
        "calls_started": state.get("calls_started", 0),
        "budget_policy_version": state.get("budget_policy_version"),
        "stages": rows,
        "history": history,
        "stage_dependencies": stage_dependencies(state),
    }


def compare_stage_versions(
    run_dir: Path, stage_name: str, *, base_sha256: str | None = None,
    target_sha256: str | None = None, base_input_sha256: str | None = None,
    target_input_sha256: str | None = None,
) -> dict[str, Any]:
    """Compare immutable request/output identities, including identical outputs."""
    run_dir = Path(run_dir).resolve()
    versions = _load_index(run_dir)["stages"].get(stage_name, [])
    if len(versions) < 2:
        raise ValueError(f"stage has fewer than two recorded versions: {stage_name}")
    def select(output_hash, input_hash, default_index):
        if output_hash is None and input_hash is None:
            return versions[default_index]
        matches = [row for row in versions if (output_hash is None or row["output_sha256"] == output_hash)
                   and (input_hash is None or row["input_sha256"] == input_hash)]
        if len(matches) != 1:
            raise ValueError("stage comparison identity is invalid or ambiguous; specify input and output hashes")
        return matches[0]
    base = select(base_sha256, base_input_sha256, -2)
    target = select(target_sha256, target_input_sha256, -1)
    if base == target:
        raise ValueError("stage comparison hashes are invalid")
    def load(row):
        path = (_debug_root(run_dir) / row["artifact"]).resolve()
        if not path.is_relative_to(_debug_root(run_dir).resolve()):
            raise ValueError("stage artifact escaped the debug directory")
        value = _read(path)
        if (_hash(value.get("output")) != row["output_sha256"]
            or value.get("input_sha256") != row["input_sha256"] or value.get("stage_id") != stage_name):
            raise ValueError("stage artifact content hash mismatch")
        return value["output"]
    def input_value(row):
        for path in (_debug_root(run_dir) / 'inputs' / _safe_stage(stage_name)).glob('*.json'):
            record = _read(path)
            if record.get('input_sha256') == row['input_sha256']:
                if _hash(record.get('payload')) != row['input_sha256']:
                    raise ValueError('stage input snapshot changed')
                return record['payload']
        return None
    def diff(left, right, label_left, label_right):
        return "\n".join(difflib.unified_diff(
            json.dumps(left,ensure_ascii=False,indent=2,sort_keys=True).splitlines(),
            json.dumps(right,ensure_ascii=False,indent=2,sort_keys=True).splitlines(),
            fromfile=label_left,tofile=label_right,lineterm=''))
    old, new = load(base), load(target)
    old_input, new_input = input_value(base), input_value(target)
    available = old_input is not None and new_input is not None
    return {"schema":"creative_stage_comparison/v1", "stage_id":stage_name,
        "base_sha256":base['output_sha256'], "target_sha256":target['output_sha256'],
        "base_input_sha256":base['input_sha256'], "target_input_sha256":target['input_sha256'],
        "output_identical":old == new,
        "diff":diff(old,new,base['output_sha256'],target['output_sha256']),
        "input_snapshots_available":available,
        "input_diff":diff(old_input,new_input,base['input_sha256'],target['input_sha256']) if available else None}


def record_stage_feedback(run_dir, stage_name, message, **kwargs):
    from .creative_state_store import state_lock
    with state_lock(run_dir):
        return _record_stage_feedback_locked(run_dir, stage_name, message, **kwargs)


def _record_stage_feedback_locked(
    run_dir: Path,
    stage_name: str,
    message: str,
    *,
    disposition: str = "must_fix",
    evidence: list[dict[str, Any]] | None = None,
    expected_output_sha256: str | None = None,
    expected_input_sha256: str | None = None,
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
    if expected_output_sha256 is not None and selected["output_sha256"] != expected_output_sha256:
        raise ValueError("displayed stage version changed; refresh before feedback")
    if expected_input_sha256 is not None and selected["input_sha256"] != expected_input_sha256:
        raise ValueError("displayed stage input version changed; refresh before feedback")
    payload = {
        "stage_id": stage_name,
        "input_sha256": selected["input_sha256"],
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

    from .creative_state_store import append_command_locked, commit_state_locked
    append_command_locked(run_dir, "feedback", path)
    state = _read(run_dir / "state.json")
    commit_state_locked(run_dir, state)
    return receipt


def resolve_stage_feedback(
    run_dir: Path,
    state: dict[str, Any],
    stage_name: str,
    output_sha256: str,
    *,
    consumed_feedback_ids: set[str] | None = None,
    resolved_input_sha256: str | None = None,
) -> list[str]:
    """Resolve only feedback whose exact stage has a different validated output."""
    pending = [
        row for row in pending_must_fix_feedback(state)
        if row.get("stage_id") == stage_name
        and (consumed_feedback_ids is None or row["feedback_id"] in consumed_feedback_ids)
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
            **({"resolved_by_input_sha256": resolved_input_sha256} if resolved_input_sha256 else {}),
        }
        resolution_path = feedback_path.with_name(
            feedback_path.stem + ".resolution.json"
        )
        if resolution_path.exists():
            existing = _read(resolution_path)
            if any(existing.get(key) != value for key, value in resolution.items() if key != "resolved_at"):
                raise RuntimeError("feedback resolution receipt conflicts with existing record")
            resolution = existing
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
        base_input_sha256: str | None = None,
        target_input_sha256: str | None = None,
    ) -> dict[str, Any]:
        return compare_stage_versions(
            self.run_dir,
            stage_name,
            base_sha256=base_sha256,
            target_sha256=target_sha256, base_input_sha256=base_input_sha256,
            target_input_sha256=target_input_sha256,
        )

    def feedback(
        self,
        stage_name: str,
        message: str,
        *,
        disposition: str = "must_fix",
        expected_output_sha256: str | None = None,
        expected_input_sha256: str | None = None,
        evidence: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return record_stage_feedback(
            self.run_dir,
            stage_name,
            message,
            disposition=disposition, expected_output_sha256=expected_output_sha256,
            expected_input_sha256=expected_input_sha256, evidence=evidence,
        )
