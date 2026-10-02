"""Stage orchestration shared by automatic and breakpoint execution.

Provider transport, validators and budget accounting remain in the existing
runner; this boundary owns feedback replay, immutable artifacts and checkpoints.
"""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from .creative_stage_debug import record_stage_artifact, CreativeStageBreakpointReached


def finish_stage(
    self,
    name: str,
    role: str,
    output: dict[str, Any],
    *,
    completed_before: bool,
) -> dict[str, Any]:
    """Record a validated stage and emit a non-failure breakpoint signal."""
    from .creative_stage_debug import stage_dependencies
    from .creative_state_store import refresh_commands, consumed_feedback_ids
    refresh_commands(self)

    graph = stage_dependencies(self.state)
    if name not in self._debug_stage_trace:
        graph.setdefault(name, self._debug_stage_trace[-1:])
        self._debug_stage_trace.append(name)
    self.state["debug_stage_dependencies"] = graph
    artifact = record_stage_artifact(
        self.run_dir,
        self.state,
        name,
        role,
        output,
    )
    from .creative_stage_debug import resolve_stage_feedback

    resolve_stage_feedback(
        self.run_dir,
        self.state,
        name,
        artifact["output_sha256"],
        consumed_feedback_ids=consumed_feedback_ids(self, name),
        resolved_input_sha256=artifact.get("input_sha256"),
    )
    from .creative_stage_contracts import record_result

    record_result(self, name, artifact)
    self.state.setdefault("debug_stage_validity", {})[name] = "current"
    completed_after = any(
        row.get("name") == name for row in self.state.get("stages", [])
    )
    if completed_after and not completed_before:
        self._debug_new_stages += 1
    from .creative_execution_control import check_dispatch

    check_dispatch(self, name)
    reason = None
    if self.stop_after_stage == name:
        reason = "requested_stage"
    elif (
        self.max_new_stages is not None
        and self._debug_new_stages >= self.max_new_stages
    ):
        reason = "next_stage_completed"
    if reason:
        previous = self.state.get("debug_breakpoint")
        if previous:
            self.state.setdefault("debug_breakpoint_history", []).append(previous)
        self.state["status"] = "debug_breakpoint"
        self.state["debug_breakpoint"] = {
            "schema": "creative_stage_breakpoint/v1",
            "stage_id": name,
            "reason": reason,
            "input_sha256": artifact.get("input_sha256"),
            "output_sha256": artifact["output_sha256"],
            "calls_started": self.state.get("calls_started", 0),
            "stopped_at": datetime.now(timezone.utc).isoformat(),
            "automatic_media_submit": False,
        }
        self.state.pop("last_error", None)
        self._save()
        raise CreativeStageBreakpointReached(name, reason)
    self._save()
    return output


def execute_stage(
    self,
    name: str,
    role: str,
    payload: dict[str, Any],
    validator: Any,
) -> dict[str, Any]:
    from .creative_workflow import _read, _write, REVIEW_V6
    from .creative_execution_control import check_dispatch

    check_dispatch(self, name)
    completed_before = any(
        row.get("name") == name for row in self.state.get("stages", [])
    )
    from .creative_narrative_transfer import enrich_review_context

    payload = enrich_review_context(
        self.state.get("narrative_focus_binding"), name, payload
    )
    from .creative_reference_expression import enrich_reference_context

    payload = enrich_reference_context(
        self.state.get("reference_expression_binding"), name, payload
    )
    from .creative_stage_debug import (
        current_stage_records,
        pending_must_fix_feedback,
        replayable_resolved_stage_feedback,
        stage_ancestors,
        stage_dependencies,
    )

    pending_feedback = pending_must_fix_feedback(self.state)
    stage_validity = self.state.get("debug_stage_validity", {})
    graph = stage_dependencies(self.state)
    current_records = {row["name"]: row for row in current_stage_records(self.state)}
    local_feedback = [row for row in pending_feedback if row["stage_id"] == name]
    # Resolved upstream repairs retain their exact request context even when
    # another stage has pending feedback. _stage_impl still checks all hashes.
    replayed_feedback = replayable_resolved_stage_feedback(
        self.run_dir,
        self.state,
        name,
    )
    if replayed_feedback and not local_feedback:
        payload = {**payload, "debug_must_fix_feedback": replayed_feedback}
    if pending_feedback:
        ancestors = stage_ancestors(graph, name)
        blocking = [row for row in pending_feedback if row["stage_id"] in ancestors]
        if blocking:
            raise RuntimeError(
                f"阶段 {blocking[0]['stage_id']} 存在未修复的 must_fix 反馈；"
                f"已在 {name} 调用前阻断，需先修订责任阶段"
            )
        if not local_feedback:
            upstream_of_target = any(
                name in stage_ancestors(graph, row["stage_id"])
                for row in pending_feedback
            )
            cached_path = self.run_dir / f"{name}.json"
            cached_record = _read(cached_path) if cached_path.is_file() else {}
            replayable_upstream = (
                upstream_of_target
                and stage_validity.get(name) != "invalidated"
                and cached_record.get("status") in ("response_received", "validated")
            )
            # A legitimately invalidated intermediate stage may be rebuilt
            # after its upstream repair resolves, before the next target.
            rebuildable_upstream = (
                upstream_of_target
                and stage_validity.get(name) == "invalidated"
                and any(
                    row["stage_id"] in ancestors
                    and row.get("resolved_by_output_sha256")
                    == current_records.get(row["stage_id"], {}).get("output_sha256")
                    and row.get("resolved_by_output_sha256") is not None
                    and stage_validity.get(row["stage_id"]) == "current"
                    for row in self.state.get("debug_feedback", [])
                )
            )
            if not (replayable_upstream or rebuildable_upstream):
                raise RuntimeError(
                    f"阶段 {pending_feedback[0]['stage_id']} 存在未修复的 must_fix 反馈；"
                    f"已在 {name} 调用前阻断，需先修订责任阶段"
                )
        else:
            current = current_records.get(name)
            cached_path = self.run_dir / f"{name}.json"
            archive = (
                self.run_dir
                / f"{name}__before_feedback_{local_feedback[0]['feedback_id']}.json"
            )
            repairing = False
            if archive.is_file() and cached_path.is_file():
                prior = _read(archive)
                cached = _read(cached_path)
                repairing = (
                    prior.get("status") == "validated"
                    and all(
                        row.get("repair_base_output_sha256", row.get("output_sha256")) == prior.get("output_sha256")
                        for row in local_feedback
                    )
                    and cached.get("input_sha256") != prior.get("input_sha256")
                    and cached.get("role") == prior.get("role")
                )
                if not repairing:
                    raise RuntimeError("返修恢复的原版本或新请求绑定不一致")
            if current is None or (
                not repairing
                and any(
                    row.get("repair_base_output_sha256", row.get("output_sha256")) != current.get("output_sha256")
                    for row in local_feedback
                )
            ):
                raise RuntimeError("must_fix 反馈绑定的阶段产物已变化，请重新登记反馈")
            payload = {
                **payload,
                "debug_must_fix_feedback": [
                    {
                        "feedback_id": row["feedback_id"],
                        "message": _read(self.run_dir / row["receipt"])["message"],
                        "evidence": _read(self.run_dir / row["receipt"]).get(
                            "evidence", []
                        ),
                        "previous_output_sha256": row["output_sha256"],
                    }
                    for row in local_feedback
                ],
            }
            cached_path = self.run_dir / f"{name}.json"
            if cached_path.is_file() and not repairing:
                feedback_id = local_feedback[0]["feedback_id"]
                archive = self.run_dir / f"{name}__before_feedback_{feedback_id}.json"
                if archive.exists():
                    raise RuntimeError("must_fix 修订归档已存在；拒绝覆盖旧执行记录")
                cached_record = _read(cached_path)
                cached_record["superseded_reason"] = "explicit_must_fix_feedback"
                _write(cached_path, cached_record)
                cached_path.replace(archive)
                from .creative_stage_contracts import archive_stage_dependents

                archive_stage_dependents(self, name)
            completed_before = False
    if stage_validity.get(name) == "invalidated":
        completed_before = False
    from .creative_governed_runtime import verify_rules

    verify_rules(self, name)
    from .creative_focused_review_stage import enabled as focused_enabled, run_review

    if focused_enabled(self, name, payload):
        output = run_review(self, name, role, payload)
        return self._finish_debug_stage(
            name,
            role,
            output,
            completed_before=(
                completed_before
                or name in getattr(self, "_debug_compatible_stages", set())
            ),
        )
    # Raw model ID reviews stay in the stage receipt; only a separate derived
    # artifact is expanded for the existing semantic/assistant review gate.
    raw = self._stage_impl(name, role, payload, validator)
    if (
        self.review_policy_version == REVIEW_V6
        and name.startswith(("writer_check", "script_review"))
        and self.state.get("review_evidence_interface_version") == "evidence_ids_v1"
    ):
        from .creative_review_evidence_ids import save_expansion

        output = save_expansion(self.run_dir, name, raw, payload)
    else:
        output = raw
    return self._finish_debug_stage(
        name,
        role,
        output,
        completed_before=(
            completed_before or name in getattr(self, "_debug_compatible_stages", set())
        ),
    )
