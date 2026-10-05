"""Serialized state commits with immutable command replay, never held over providers."""

from contextlib import contextmanager
from pathlib import Path
import os
import time
from .creative_stage_contracts import persist, read, digest


class CreativeDispatchBlocked(RuntimeError):
    provider_dispatch_started = False


@contextmanager
def state_lock(run_dir):
    path = Path(run_dir) / ".creative_debug/state.commit.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if stream.seek(0, 2) == 0:
            stream.write(b"0")
            stream.flush()
        deadline = time.monotonic() + 30
        while True:
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("task state commit lock timeout")
                time.sleep(0.01)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def publish_immutable_locked(path, value):
    """Publish complete JSON atomically; caller must hold this task's state lock."""
    path = Path(path)
    if path.exists():
        if read(path) != value:
            raise ValueError("immutable receipt changed: " + str(path))
        return
    persist(path, value)


def append_command_locked(root, kind, receipt):
    root = Path(root).resolve()
    receipt = Path(receipt).resolve()
    if not receipt.is_relative_to(root):
        raise ValueError("command receipt escaped task")
    commands = root / ".creative_debug/state_commands"
    commands.mkdir(parents=True, exist_ok=True)
    binding = {
        "kind": kind,
        "receipt": receipt.relative_to(root).as_posix(),
        "receipt_sha256": digest(read(receipt)),
    }
    command_id = digest(binding)
    paths = sorted(commands.glob("*.json"))
    for path in paths:
        prior = read(path)
        if prior["command_id"] == command_id:
            return prior
    event = {
        "schema": "creative_state_command/v1",
        "sequence": len(paths) + 1,
        "command_id": command_id,
        **binding,
    }
    publish_immutable_locked(
        commands / (f"{event['sequence']:08}_" + command_id + ".json"),
        event,
    )
    return event


def _recover_receipts_locked(root):
    feedback, controls, failures = [], [], []
    for path in (root / ".creative_debug/feedback").glob("*/*.json"):
        try:
            value = read(path)
            if value.get("schema") != "creative_stage_feedback/v1":
                continue
            payload = {
                key: value[key]
                for key in (
                    "stage_id",
                    "output_sha256",
                    "disposition",
                    "message",
                    "evidence",
                )
            }
            if "input_sha256" in value:
                payload["input_sha256"] = value["input_sha256"]
            if value["feedback_id"] != digest(payload)[:20] or value[
                "disposition"
            ] not in ("must_fix", "suggestion"):
                raise ValueError("immutable feedback identity changed")
            feedback.append((value["recorded_at"], path))
        except (ValueError, KeyError, OSError) as exc:
            failures.append(
                {
                    "receipt": path.relative_to(root).as_posix(),
                    "error": "resolved feedback replay binding changed: " + str(exc),
                }
            )
    for _, path in sorted(feedback):
        append_command_locked(root, "feedback", path)
    for path in (root / ".creative_debug/control_history").glob("*.json"):
        value = read(path)
        if value.get("schema") == "creative_execution_control/v1":
            controls.append((value["requested_at"], path))
    for _, path in sorted(controls):
        append_command_locked(root, "control", path)
    return failures


def apply_commands_locked(root, state):
    from .creative_stage_debug import (
        pending_must_fix_feedback,
        stage_dependencies,
        stage_ancestors,
        current_stage_records,
    )

    root = Path(root).resolve()
    failures = _recover_receipts_locked(root)
    events = []
    state.pop("command_integrity_errors", None)
    for ordinal, path in enumerate(
        sorted((root / ".creative_debug/state_commands").glob("*.json")), 1
    ):
        event = read(path)
        source = (root / event["receipt"]).resolve()
        expected_binding = {
            key: event[key] for key in ("kind", "receipt", "receipt_sha256")
        }
        if (
            event.get("schema") != "creative_state_command/v1"
            or event.get("command_id") != digest(expected_binding)
            or event.get("sequence") != ordinal
        ):
            failures.append(
                {
                    "receipt": path.relative_to(root).as_posix(),
                    "error": "resolved feedback replay binding changed: command order or identity changed",
                }
            )
            continue
        if (
            not source.is_relative_to(root)
            or digest(read(source)) != event["receipt_sha256"]
        ):
            failures.append(
                {
                    "receipt": event["receipt"],
                    "error": "resolved feedback replay binding changed: immutable state command binding changed",
                }
            )
            continue
        value = read(source)
        events.append(event["command_id"])
        if event["kind"] == "control":
            state["execution_control"] = value
            persist(root / ".creative_debug/control.json", value)
            continue
        if event["kind"] != "feedback":
            raise RuntimeError("unknown state command")
        summary = {
            k: value[k]
            for k in (
                "feedback_id",
                "stage_id",
                "input_sha256",
                "output_sha256",
                "disposition",
            )
            if k in value
        }
        summary["receipt"] = event["receipt"]
        summaries = state.setdefault("debug_feedback", [])
        row = next(
            (x for x in summaries if x["feedback_id"] == value["feedback_id"]), None
        )
        if row is None:
            row = dict(summary)
            summaries.append(row)
        elif any(row.get(k) != v for k, v in summary.items()):
            raise RuntimeError("feedback state binding changed")
        resolution_path = source.with_name(source.stem + ".resolution.json")
        if resolution_path.exists():
            resolution = read(resolution_path)
            if (
                resolution.get("feedback_sha256") != digest(value)
                or resolution.get("feedback_id") != value["feedback_id"]
                or resolution.get("stage_id") != value["stage_id"]
                or resolution.get("previous_output_sha256") != value["output_sha256"]
                or not any(
                    x.get("name") == value["stage_id"]
                    and x.get("output_sha256")
                    == resolution.get("resolved_by_output_sha256")
                    for x in state.get("stages", [])
                )
            ):
                state.setdefault("command_integrity_errors", []).append(
                    {
                        "receipt": resolution_path.relative_to(root).as_posix(),
                        "error": "resolved feedback replay binding changed: feedback resolution is not bound to validated history",
                    }
                )
                continue
            if resolution.get("resolved_by_input_sha256"):
                adopted = False
                for input_path in (
                    root / ".creative_debug/inputs" / value["stage_id"]
                ).glob("*.json"):
                    source_input = read(input_path)
                    if (
                        digest(source_input) == input_path.stem
                        and digest(source_input["payload"])
                        == source_input.get("input_sha256")
                        and source_input.get("input_sha256")
                        == resolution["resolved_by_input_sha256"]
                        and value["feedback_id"]
                        in {
                            x["feedback_id"]
                            for x in source_input["payload"].get(
                                "debug_must_fix_feedback", []
                            )
                        }
                        and any(
                            x.get("name") == value["stage_id"]
                            and x.get("input_sha256")
                            == resolution["resolved_by_input_sha256"]
                            and x.get("output_sha256")
                            == resolution["resolved_by_output_sha256"]
                            for x in state.get("stages", [])
                        )
                    ):
                        adopted = True
                        break
                if not adopted:
                    state.setdefault("command_integrity_errors", []).append(
                        {
                            "receipt": resolution_path.relative_to(root).as_posix(),
                            "error": "resolved feedback replay binding changed: resolution did not consume accepted feedback",
                        }
                    )
                    continue
            row.update(
                resolved_by_output_sha256=resolution["resolved_by_output_sha256"],
                resolution_receipt=resolution_path.relative_to(root).as_posix(),
            )
    if failures:
        state.setdefault("command_integrity_errors", []).extend(failures)
    if events:
        state["applied_state_command_ids"] = events
    pending = pending_must_fix_feedback(state)
    if state.get("debug_feedback"):
        state["debug_feedback_status"] = (
            "revision_required"
            if pending
            else (
                "resolved"
                if any(x["disposition"] == "must_fix" for x in state["debug_feedback"])
                else "suggestions_recorded"
            )
        )
    if pending:
        if state.get("status") in (
            "media_handoff_pending_capability",
            "reviewed_revision_media_handoff_pending_capability",
        ):
            state.setdefault("status_before_debug_feedback", state["status"])
            state["status"] = "debug_revision_required"
        graph = stage_dependencies(state)
        state["debug_stage_dependencies"] = graph
        current = {x["name"]: x for x in current_stage_records(state)}
        validity = state.setdefault("debug_stage_validity", {})
        targets = {x["stage_id"] for x in pending}
        for row in pending:
            latest = current.get(row["stage_id"])
            binding = state.get("stage_input_bindings", {}).get(row["stage_id"])
            consumed = set()
            if binding:
                source_input = read(root / binding["receipt"])
                if digest(source_input) != binding["sha256"]:
                    raise RuntimeError("frozen feedback repair input changed")
                if latest and source_input["input_sha256"] == latest["input_sha256"]:
                    consumed = {
                        x["feedback_id"]
                        for x in source_input["payload"].get(
                            "debug_must_fix_feedback", []
                        )
                    }
            if (
                latest
                and latest["output_sha256"] != row["output_sha256"]
                and row["feedback_id"] not in consumed
            ):
                rebase = {
                    "schema": "creative_feedback_rebase/v1",
                    "feedback_id": row["feedback_id"],
                    "original_output_sha256": row["output_sha256"],
                    "repair_base_output_sha256": latest["output_sha256"],
                    "repair_base_input_sha256": latest["input_sha256"],
                    "reason": "accepted feedback was not consumed by intervening validated request",
                }
                publish_immutable_locked(
                    root
                    / ".creative_debug/feedback_rebases"
                    / (digest(rebase) + ".json"),
                    rebase,
                )
                row["repair_base_output_sha256"] = latest["output_sha256"]
        for name in set(graph) | set(current):
            if name in targets:
                validity[name] = "needs_revision"
            elif targets & stage_ancestors(graph, name):
                validity[name] = "invalidated"
    return state


def commit_state_locked(root, state):
    root = Path(root)
    apply_commands_locked(root, state)
    path = root / "state.json"
    previous = read(path) if path.exists() else None
    version = previous.get("state_revision", 0) if previous else 0
    same = previous is not None and {
        k: v for k, v in state.items() if k != "state_revision"
    } == {k: v for k, v in previous.items() if k != "state_revision"}
    state["state_revision"] = version if same else version + 1
    if not same:
        persist(path, state)


def commit_state(root, state):
    with state_lock(root):
        commit_state_locked(root, state)


def refresh_commands(workflow):
    with state_lock(workflow.run_dir):
        apply_commands_locked(workflow.run_dir, workflow.state)
        if workflow.state.get("command_integrity_errors"):
            raise RuntimeError(
                "resolved feedback replay binding changed: feedback command integrity check failed"
            )


def consumed_feedback_ids(workflow, name):
    binding = workflow.state.get("stage_input_bindings", {}).get(name)
    if not binding:
        return set()
    root = Path(workflow.run_dir).resolve()
    path = (root / binding["receipt"]).resolve()
    if not path.is_relative_to(root):
        raise RuntimeError("stage input escaped task")
    value = read(path)
    if digest(value) != binding["sha256"]:
        raise RuntimeError("frozen stage input changed")
    return {
        x["feedback_id"] for x in value["payload"].get("debug_must_fix_feedback", [])
    }


def authorize_dispatch(workflow, role, messages):
    from .creative_stage_debug import (
        pending_must_fix_feedback,
        stage_dependencies,
        stage_ancestors,
    )

    with state_lock(workflow.run_dir):
        apply_commands_locked(workflow.run_dir, workflow.state)
        if workflow.state.get("command_integrity_errors"):
            raise CreativeDispatchBlocked(
                "resolved feedback replay binding changed: feedback command integrity check failed"
            )
        control = workflow.state.get("execution_control", {})
        if control.get("action") == "stop":
            raise CreativeDispatchBlocked("user stop blocks future provider dispatch")
        name = workflow._active_stage_name
        consumed = consumed_feedback_ids(workflow, name)
        graph = stage_dependencies(workflow.state)
        pending = pending_must_fix_feedback(workflow.state)
        local = [x for x in pending if x["stage_id"] == name]
        ancestors = stage_ancestors(graph, name)
        repaired_ancestor = any(
            x["stage_id"] in ancestors and x.get("resolved_by_output_sha256")
            for x in workflow.state.get("debug_feedback", [])
        )
        permitted_intermediate = (
            workflow.state.get("debug_stage_validity", {}).get(name) == "invalidated"
            and repaired_ancestor
        )
        blocking = [
            x
            for x in pending
            if (
                x["stage_id"] == name
                and x["feedback_id"] not in consumed
                or x["stage_id"] != name
                and not (
                    name in stage_ancestors(graph, x["stage_id"])
                    and (local or permitted_intermediate)
                )
            )
        ]
        if blocking:
            raise CreativeDispatchBlocked(
                "未修复的 must_fix 反馈阻止模型派发：" + blocking[0]["stage_id"]
            )
        permit = {
            "schema": "creative_dispatch_permit/v1",
            "stage_id": name,
            "role": role,
            "messages_sha256": digest(messages),
            "call_ordinal": workflow.state.get("calls_started"),
            "state_revision": workflow.state.get("state_revision"),
            "applied_commands": workflow.state.get("applied_state_command_ids", []),
            "consumed_feedback_ids": sorted(consumed),
        }
        publish_immutable_locked(
            Path(workflow.run_dir)
            / ".creative_debug/dispatch_permits"
            / (digest(permit) + ".json"),
            permit,
        )


def check_media_dispatch(plan):
    """Pending text commands also block paid media; original-ID queries bypass this."""
    if not plan.get("source_run"):
        return
    from .creative_stage_debug import pending_must_fix_feedback

    root = Path(plan["source_run"])
    with state_lock(root):
        state = read(root / "state.json")
        commit_state_locked(root, state)
        if state.get("command_integrity_errors"):
            raise CreativeDispatchBlocked(
                "resolved feedback replay binding changed: feedback command integrity check failed"
            )
        if state.get("execution_control", {}).get("action") == "stop":
            raise CreativeDispatchBlocked("user stop blocks future media dispatch")
        if pending_must_fix_feedback(state) or any(
            value in ("invalidated", "needs_revision")
            for value in state.get("debug_stage_validity", {}).values()
        ):
            raise CreativeDispatchBlocked("未修复的 must_fix 或失效文本阻止媒体派发")
