"""Coordinate frozen source execution with two proof-gated, once-only recoveries.

This adapter never repairs native content, resets a budget, or retries transport.
Each recovery appends local evidence before frozen execution resumes its next stage.
"""
from __future__ import annotations

from pathlib import Path

from . import natural_director_pipeline_v10 as pipeline
from . import known_writer_projection_recovery_v1 as projection
from . import known_complete_review_revision_v1 as review_revision

core = pipeline.core
VERSION = "natural_director_source_runner/v11"
BINDING = "SOURCE_RUNNER_V11_BINDING.json"
ANCHOR = "SOURCE_RUNNER_V11_ANCHOR.json"
LOCK = ".source_runner_v11.lock"
RECOVERIES = (("writer_projection", projection, "plan_recovery", "apply_recovery"),
              ("complete_review_revision", review_revision, "plan_revision", "apply_revision"))


def _admission(source, run, authorization):
    if any((folder / name).exists() for folder in (source, run)
           for name in (".execution.lock", ".graph_driver.lock")):
        raise RuntimeError("原任务正在执行，不并发读取或派发")
    route = pipeline._source_route(source)
    if core._binding(authorization) != route["authorization_file"]:
        raise ValueError("协调器必须使用来源冻结的同一专属授权")
    binding, state = pipeline.parent._verify(source)
    if state.get("pending_call") is not None or state.get("reported_tokens") is None:
        raise RuntimeError("存在原未决请求或未知用量，协调器不重派")
    return binding, state


def _binding(source, run, authorization, source_binding):
    return {"schema": VERSION, "source_run_dir": str(source), "run_dir": str(run),
            "source_binding_id": source_binding["source"]["binding_id"],
            "authorization_file": core._binding(authorization),
            "source_binding_file": core._binding(source / "BINDING.json"),
            "writer_only_route": core._binding(source / "WRITER_ONLY_ROUTE.json"),
            "code_bindings": [core._binding(Path(module.__file__).resolve())
                              for module in (pipeline, projection, review_revision)]
                              + [core._binding(Path(__file__).resolve())],
            "automatic_recovery_limits": {kind: 1 for kind, *_ in RECOVERIES},
            "automatic_transport_retry": False, "budget_reset": False,
            "automatic_media_submit": False}


def _history(source, binding):
    previous = None
    paths = sorted(source.glob("SOURCE_RUNNER_V11_EVENT_*.json"))
    for number, path in enumerate(paths, 1):
        event = core._read(path)
        if (path.name != f"SOURCE_RUNNER_V11_EVENT_{number:05}.json"
                or event.get("schema") != VERSION or event.get("binding_sha256") != core._digest(binding)
                or event.get("previous") != previous):
            raise ValueError("协调器原不可变事件链变化")
        for key in ("plan_file", "attempt_file", "helper_record"):
            if event.get(key):
                core._verify_file(event[key])
        for row in event.get("preexisting_helper_recovery_files", {}).values():
            core._verify_file(row)
        previous = core._binding(path)
    return paths, previous


def _event(source, binding, kind, **details):
    paths, previous = _history(source, binding)
    path = source / f"SOURCE_RUNNER_V11_EVENT_{len(paths) + 1:05}.json"
    core._ensure(path, {"schema": VERSION, "binding_sha256": core._digest(binding),
                       "previous": previous, "kind": kind, **details})
    return core._binding(path)


def _recovery_summary(source, binding):
    paths, _ = _history(source, binding)
    applied = {core._read(path).get("recovery_kind") for path in paths
               if core._read(path).get("kind") == "recovery_applied"}
    attempts = {kind: (source / f"SOURCE_RUNNER_V11_{kind.upper()}_ATTEMPT.json").exists()
                for kind, *_ in RECOVERIES}
    recorded = {kind: (source / helper.RECORD).exists() for kind, helper, *_ in RECOVERIES}
    return {"automatic_recoveries_used": {kind: attempts[kind] and kind in applied and recorded[kind]
                                          for kind in attempts},
            "recorded_helper_recoveries": recorded,
            "preexisting_helper_recoveries": {kind: recorded[kind] and not attempts[kind] for kind in attempts},
            "awaiting_local_completion": [kind for kind in attempts if attempts[kind] and kind not in applied]}


def _recover_known(source, run, binding):
    # Writer recovery is only valid before any natural-director child exists.
    # It cannot revive a writer underneath a pending or completed downstream run.
    if (run / "BINDING.json").exists():
        return False
    _, state = pipeline.parent._verify(source)
    if (state.get("status") != "needs_attention" or state.get("pending_call") is not None
            or state.get("reported_tokens") is None):
        return False
    for kind, helper, planner, applier in RECOVERIES:
        attempt = source / f"SOURCE_RUNNER_V11_{kind.upper()}_ATTEMPT.json"
        if (source / helper.RECORD).exists() or attempt.exists():
            continue
        try:
            plan = getattr(helper, planner)(source)
        except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
            _event(source, binding, "recovery_not_applicable", recovery_kind=kind,
                   reason=str(exc), automatic_transport_retry=False)
            continue
        plan_path = source / f"SOURCE_RUNNER_V11_{kind.upper()}_PLAN.json"
        core._ensure(plan_path, plan)
        plan_file = core._binding(plan_path)
        # Persist consumption before apply; a restart cannot silently try again.
        core._ensure(attempt, {"schema": VERSION, "binding_sha256": core._digest(binding),
                              "recovery_kind": kind, "plan_file": plan_file,
                              "helper_code": core._binding(Path(helper.__file__).resolve()),
                              "max_automatic_applications": 1, "model_calls_started": 0})
        _event(source, binding, "recovery_apply_started", recovery_kind=kind,
               plan_file=plan_file, attempt_file=core._binding(attempt))
        result = getattr(helper, applier)(source, reviewed_plan=plan)
        expected = {"writer_projection": ("recovered", "review_full"),
                    "complete_review_revision": ("revision_prepared", "writer_full")}[kind]
        if (result.get("model_calls_started") != 0
                or (result.get("status"), result.get("stage")) != expected):
            raise ValueError("本地恢复结果、阶段或零模型派发证明不符")
        _event(source, binding, "recovery_applied", recovery_kind=kind,
               plan_file=plan_file, helper_record=core._binding(source / helper.RECORD),
               result=result, automatic_transport_retry=False)
        return True
    return False


def execute_source(source_run_dir, *, run_dir, authorization_path, clients=None, max_steps=None):
    """Run writer-only, prove at most two local recoveries, then frozen v10 route.

    Complete rejected reviews create a new bounded full draft through the frozen
    writer runtime. The old request is never reissued and no review is hand-edited.
    """
    if max_steps is not None and (type(max_steps) is not int or max_steps < 1):
        raise ValueError("max_steps必须为正整数")
    source, run = Path(source_run_dir).resolve(), Path(run_dir).resolve()
    authorization = Path(authorization_path).resolve()
    source_binding, _ = _admission(source, run, authorization)
    with core._lock(source / LOCK):
        source_binding, _ = _admission(source, run, authorization)
        binding = _binding(source, run, authorization, source_binding)
        core._ensure(source / BINDING, binding)
        core._ensure(source / ANCHOR, {"sha256": core._digest(binding)})
        paths, _ = _history(source, binding)
        if not paths:
            _event(source, binding, "admitted", preexisting_helper_recovery_files={
                kind: core._binding(source / helper.RECORD) for kind, helper, *_ in RECOVERIES
                if (source / helper.RECORD).exists()})
        summary = _recovery_summary(source, binding)
        if summary["awaiting_local_completion"]:
            return {"schema": VERSION, "status": "awaiting_local_completion", "dispatch_blocked": True,
                    "blockers": ["本协调器恢复尝试已有原记录但未确认完成，不重复apply或派发"],
                    "source_runner_binding": core._binding(source / BINDING), **summary,
                    "automatic_transport_retry": False, "automatic_media_submit": False}
        for _ in range(len(RECOVERIES) + 1):
            try:
                view = pipeline.execute_writer_only(source, clients=clients, max_steps=max_steps)
            except (ValueError, RuntimeError, OSError, KeyError, TypeError):
                if _recover_known(source, run, binding):
                    continue
                raise
            if view.get("writer_ready"):
                # The frozen coordinator rechecks the ready source before claiming
                # or resuming its natural-director owner and inherited budget.
                view = pipeline.execute_source(source, run_dir=run, authorization_path=authorization,
                                               clients=clients, max_steps=max_steps)
                break
            if not _recover_known(source, run, binding):
                break
        result = {**view, "source_runner_schema": VERSION,
                  "source_runner_binding": core._binding(source / BINDING),
                  **_recovery_summary(source, binding),
                  "automatic_transport_retry": False, "automatic_media_submit": False}
        _event(source, binding, "execution_returned", status=view.get("status"),
               stage=view.get("stage"), automatic_recoveries_used=result["automatic_recoveries_used"])
        return result
