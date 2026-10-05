"""Durable stop/resume intent shared by CLI, UI and the stage runner."""

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from .creative_stage_contracts import read


def _command_locked(run_dir, action):
    if action not in ("stop", "resume"):
        raise ValueError("unknown execution control")
    root = Path(run_dir)
    if not (root / "state.json").is_file():
        raise ValueError("execution control requires an existing task")
    event = {
        "schema": "creative_execution_control/v1",
        "command_id": uuid4().hex,
        "action": action,
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "scope": "future_dispatch_only",
        "cancel_remote_task": False,
    }
    from .creative_state_store import publish_immutable_locked

    publish_immutable_locked(
        root / ".creative_debug/control_history" / (event["command_id"] + ".json"),
        event,
    )
    from .creative_state_store import append_command_locked, commit_state_locked

    append_command_locked(
        root,
        "control",
        root / ".creative_debug/control_history" / (event["command_id"] + ".json"),
    )
    commit_state_locked(root, read(root / "state.json"))
    return event


def command(run_dir, action):
    from .creative_state_store import state_lock

    with state_lock(run_dir):
        return _command_locked(run_dir, action)


def check_dispatch(workflow, stage):
    from .creative_state_store import refresh_commands

    refresh_commands(workflow)
    event = workflow.state.get("execution_control")
    if event is None:
        path = Path(workflow.run_dir) / ".creative_debug/control.json"
        event = read(path) if path.exists() else {}
    if event.get("action") != "stop":
        return
    from .creative_stage_debug import CreativeStageBreakpointReached

    workflow.state.update(
        status="debug_breakpoint",
        debug_breakpoint={
            "schema": "creative_stage_breakpoint/v1",
            "stage_id": stage,
            "reason": "user_stop",
            "command_id": event["command_id"],
            "calls_started": workflow.state.get("calls_started", 0),
            "automatic_media_submit": False,
        },
    )
    workflow._save()
    raise CreativeStageBreakpointReached(stage, "user_stop")
