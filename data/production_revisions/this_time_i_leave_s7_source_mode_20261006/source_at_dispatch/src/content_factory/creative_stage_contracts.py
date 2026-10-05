"""Exact stage inputs and field projections; reuse never relaxes request hashes."""

from __future__ import annotations
import hashlib
import json
from pathlib import Path
from uuid import uuid4


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def persist(path, value, *, immutable=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if immutable:
        try:
            with path.open("x", encoding="utf-8") as stream:
                stream.write(data)
        except FileExistsError:
            if read(path) != value:
                raise ValueError("immutable receipt changed: " + str(path))
        return
    temp = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    temp.write_text(data, encoding="utf-8")
    temp.replace(path)


def fields(value, prefix=()):
    yield prefix, value
    if isinstance(value, dict):
        for key, item in value.items():
            yield from fields(item, prefix + (key,))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from fields(item, prefix + (i,))


def projections(workflow, name, payload):
    """Evidence of actual consumed subtrees, not an inferred semantic dependency.

    Scalar coincidences are excluded. Missing evidence retains the conservative
    dependency graph. A full parent copied into a request consumes every field.
    """
    inputs = {
        digest(value): path
        for path, value in fields(payload)
        if isinstance(value, (dict, list)) and value
    }
    parents = []
    latest = {row["name"]: row for row in workflow.state.get("stages", [])}
    for parent, row in latest.items():
        if parent == name:
            continue
        path = Path(workflow.run_dir) / (parent + ".json")
        if not path.is_file():
            continue
        record = read(path)
        if record.get("status") != "validated" or digest(
            record.get("output")
        ) != row.get("output_sha256"):
            continue
        matched = []
        for output_path, value in fields(record["output"]):
            key = digest(value)
            if key in inputs and not any(output_path[: len(p)] == p for p in matched):
                matched.append(output_path)
                parents.append(
                    {
                        "stage_id": parent,
                        "output_sha256": row["output_sha256"],
                        "output_field": list(output_path),
                        "input_field": list(inputs[key]),
                        "projection_sha256": key,
                    }
                )
    return parents


def record_input(workflow, name, role, payload, prompt_hash, input_hash):
    if digest(payload) != input_hash:
        raise ValueError("stage input mutated after request hashing")
    value = {
        "schema": "creative_stage_input/v1",
        "run_id": Path(workflow.run_dir).name,
        "task_id": workflow.state.get("logical_task_id"),
        "stage_id": name,
        "role": role,
        "input_sha256": input_hash,
        "prompt_sha256": prompt_hash,
        "model_profile": workflow.model_profile,
        "rule_binding": workflow.state.get("rule_registry_binding"),
        "review_policy_version": workflow.review_policy_version,
        "budget_limit": {
            "calls": workflow.max_calls,
            "tokens": workflow.state.get("max_total_tokens"),
        },
        "parents": projections(workflow, name, payload),
        "payload": payload,
    }
    # Parent versions may change while consumed projections remain identical.
    identity = digest(value)
    path = (
        Path(workflow.run_dir) / ".creative_debug/inputs" / name / (identity + ".json")
    )
    persist(path, value, immutable=True)
    workflow.state.setdefault("stage_input_bindings", {})[name] = {
        "receipt": str(path.relative_to(workflow.run_dir)).replace("\\", "/"),
        "sha256": identity,
    }


def reconcile_cached_stage(workflow, name, input_hash, prompt_hash):
    if workflow.state.get("debug_stage_validity", {}).get(name) != "invalidated":
        return
    path = Path(workflow.run_dir) / (name + ".json")
    if not path.is_file():
        return
    record = read(path)
    # An uncertain submission must never be archived to permit another call.
    if record.get("status") not in ("validated", "response_received", "blocked_before_dispatch"):
        raise RuntimeError("invalidated stage has an unresolved call receipt")
    compatible = (
        record.get("status") != "blocked_before_dispatch"
        and record.get("input_sha256") == input_hash
        and record.get("prompt_sha256") == prompt_hash
    )
    evidence = {
        "schema": "creative_stage_compatibility/v1",
        "stage_id": name,
        "input_sha256": input_hash,
        "prompt_sha256": prompt_hash,
        "previous_input_sha256": record.get("input_sha256"),
        "previous_output_sha256": record.get("output_sha256"),
        "input_binding": workflow.state["stage_input_bindings"][name],
        "compatible": compatible,
        "proof": "complete_request_input_and_prompt_hashes",
    }
    persist(
        Path(workflow.run_dir)
        / ".creative_debug/compatibility"
        / name
        / (digest(evidence) + ".json"),
        evidence,
        immutable=True,
    )
    if compatible:
        workflow.state["debug_stage_validity"][name] = "current"
        if not hasattr(workflow, "_debug_compatible_stages"):
            workflow._debug_compatible_stages = set()
        workflow._debug_compatible_stages.add(name)
    else:
        archive = path.with_name(
            name
            + "__invalidated_"
            + hashlib.sha256(path.read_bytes()).hexdigest()
            + ".json"
        )
        if archive.exists():
            raise RuntimeError("invalidated receipt archive collision")
        path.replace(archive)
        archive_stage_dependents(workflow, name)
    workflow._save()


def record_result(workflow, name, artifact):
    from .creative_stage_debug import pending_must_fix_feedback
    pending = pending_must_fix_feedback(workflow.state)
    result = {
        "schema": "creative_stage_result/v1",
        "stage_id": name,
        "input_binding": workflow.state.get("stage_input_bindings", {}).get(name),
        "output_sha256": artifact["output_sha256"],
        "artifact": artifact,
        "technical_status": "validated",
        "validation": "existing_stage_validator",
        "text_quality_status": "see_bound_review_receipts",
        "media_quality_status": "not_reviewed",
        "calls_started": workflow.state.get("calls_started"),
        "pending_feedback_ids": [x["feedback_id"] for x in pending],
        "next_action": "repair_upstream_feedback" if pending else "continue_text_or_stop_at_human_gate",
    }
    persist(
        Path(workflow.run_dir)
        / ".creative_debug/results"
        / name
        / (digest(result) + ".json"),
        result,
        immutable=True,
    )


def persist_derived(workflow, name, path, value):
    """Version an active derived view only after source-stage repair."""
    path = Path(path)
    if path.exists() and read(path) != value:
        rows = [
            row for row in workflow.state.get("stages", []) if row.get("name") == name
        ]
        authorized = (
            workflow.state.get("debug_stage_validity", {}).get(name)
            in ("needs_revision", "invalidated")
            or len({row.get("output_sha256") for row in rows}) > 1
        )
        if not authorized:
            from .creative_workflow_contract import CreativeContractError

            raise CreativeContractError("派生产物与当前源版本不一致，不能覆盖历史")
        old = read(path)
        persist(
            Path(workflow.run_dir)
            / ".creative_debug/derived"
            / name
            / (digest(old) + ".json"),
            {"source_stage": name, "path": path.name, "previous": old},
            immutable=True,
        )
    persist(path, value)


def archive_stage_dependents(workflow, name):
    """A new source request retires review decisions and derived receipts together."""
    suffixes = (
        "__review_packet.json",
        "__assistant_decision.json",
        "__decision_template.json",
        "__evidence_ids_expansion.json",
        "__focused_input.json",
        "__disposition.json",
        "__focused_review_expansion.json",
        "__focused_resolution.json",
        "__format_repair.json",
    )
    root = Path(workflow.run_dir)
    for suffix in suffixes:
        path = root / (name + suffix)
        if path.exists():
            archive = (
                root / ".creative_debug/retired" / name / (digest(read(path)) + suffix)
            )
            persist(archive, read(path), immutable=True)
            path.unlink()
    bindings = workflow.state.get("evidence_review_decisions", {})
    if name in bindings:
        workflow.state.setdefault("evidence_review_decision_history", []).append(
            {
                "stage_id": name,
                "binding": bindings.pop(name),
                "reason": "source_stage_revised",
            }
        )
    for field in ("pending_evidence_review", "pending_focused_review"):
        if workflow.state.get(field, {}).get("key") == name:
            workflow.state.setdefault(field + "_history", []).append(
                workflow.state.pop(field)
            )
