"""LangGraph adapter; the native runtime remains the sole dispatch authority.

SQLite checkpoints contain runtime references, never another service budget.
A replayed node re-reads the durable native checkpoint and uses the same claim
admission. No LangGraph retry policy or model tools are configured.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import sys
from typing import TypedDict

VERSION = "novel_agent_graph/v7"
STAGES = ("adopt_parent_director", "adopt_parent_review", "writer_full", "review_full", "clarify_full", "director_full", "director_review", "complete")


def _imports():
    """Load pinned project-local dependencies without installing into old venv."""
    root = Path(__file__).resolve().parents[2]
    base = root / "data/development_dependencies/novel_langgraph_v5"
    existing = sys.modules.get("langsmith")
    if existing is not None and (base / "site_packages").is_dir():
        loaded = Path(getattr(existing, "__file__", "")).resolve()
        if not loaded.is_relative_to((base / "site_packages").resolve()):
            raise RuntimeError("LangGraph requires its isolated dependency process; use the fresh CLI langgraph engine, not an already loaded legacy LangSmith process")
    for name in ("site_packages", "sqlite_site_packages"):
        path = str(base / name)
        if (base / name).is_dir() and path not in sys.path:
            sys.path.insert(0, path)
    from langgraph.graph import StateGraph, START, END
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langsmith import tracing_context
    return StateGraph, START, END, SqliteSaver, tracing_context


class GraphState(TypedDict, total=False):
    run_dir: str
    stage: str
    status: str
    calls_started: int
    runtime_checkpoint: dict
    pending_request_id: int | None
    nodes_this_invocation: int
    stop: bool


def execute_graph(run_dir, *, clients=None, max_nodes=None):
    """Run real stage nodes against the shared native admission and ledger.

    ``max_nodes`` pauses this graph invocation; it never alters frozen stage or
    service capacities. Rerunning after a graph-checkpoint failure adopts native
    results rather than resending the prior request.
    """
    from . import novel_agent_pipeline_v7 as runtime
    from . import novel_adaptation_pipeline_v1 as core

    if max_nodes is not None and (type(max_nodes) is not int or max_nodes < 1):
        raise ValueError("max_nodes must be a positive integer or None")
    run = Path(run_dir).resolve()
    # Inspection is read-only; an old/unprepared run cannot gain graph files.
    view = runtime.inspect(run)
    if view.get("projection_recovery_available") is True:
        view = runtime.recover_projection(run)
    if view["status"] in runtime.TERMINAL | {"unprepared", "evidence_invalid", "incomplete_artifacts"}:
        return {**view, "engine": VERSION, "graph_dispatched_requests": 0}
    StateGraph, START, END, SqliteSaver, tracing_context = _imports()
    db = run / "GRAPH_CHECKPOINTS.sqlite3"
    binding = core._read(run / "BINDING.json")
    if binding.get("schema") != runtime.VERSION:
        raise ValueError("Graph cannot migrate another frozen runtime")

    def references(current, count):
        snapshots = sorted(run.glob("STATE_*.json"))
        return {"run_dir": str(run), "stage": current.get("stage", "complete"), "status": current["status"],
                "calls_started": current.get("calls_started", 0),
                "runtime_checkpoint": core._binding(snapshots[-1]) if snapshots else {},
                "pending_request_id": current.get("pending_call"), "nodes_this_invocation": count,
                "stop": current["status"] in runtime.TERMINAL
                        or current["status"] in {"evidence_invalid", "incomplete_artifacts"}
                        or (max_nodes is not None and count >= max_nodes)}

    def route(state):
        return END if state.get("stop") else state["stage"]

    builder = StateGraph(GraphState)
    for stage in STAGES:
        def advance(state, expected_stage=stage):
            current = runtime.inspect(run)
            if current.get("projection_recovery_available") is True:
                current = runtime.recover_projection(run)
            count = state.get("nodes_this_invocation", 0)
            if current["status"] in runtime.TERMINAL | {"evidence_invalid", "incomplete_artifacts"}:
                return references(current, count)
            if current.get("stage") != expected_stage:
                # Another native entry advanced the authoritative checkpoint.
                return references(current, count)
            current = runtime.execute(run, clients=clients, max_steps=1)
            return references(current, count + 1)
        builder.add_node(stage, advance, retry_policy=None)
        builder.add_conditional_edges(stage, route)
    builder.add_conditional_edges(START, route)
    thread = hashlib.sha256(str(run).encode("utf-8")).hexdigest()
    initial_calls = view.get("calls_started", 0)
    with core._lock(run / ".graph_driver.lock"):
        with SqliteSaver.from_conn_string(str(db)) as saver:
            graph = builder.compile(checkpointer=saver)
            with tracing_context(enabled=False):
                graph.invoke(references(runtime.inspect(run), 0),
                             {"configurable": {"thread_id": thread},
                              "recursion_limit": max(40, binding["budget"]["max_calls"] * 3 + 10)})
    result = runtime.inspect(run)
    return {**result, "engine": VERSION, "graph_checkpoint_path": str(db),
            "graph_thread_id": thread, "graph_dispatched_requests": result.get("calls_started", 0) - initial_calls,
            "graph_budget_authority": False, "automatic_retry": False}
