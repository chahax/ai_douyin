"""Real installed LangGraph/SQLite against native runtime and fake services."""
import json
from pathlib import Path
import runpy
import sqlite3

import pytest

from src.content_factory import novel_agent_pipeline_v5 as runtime
from src.content_factory import novel_agent_graph_v5 as graph

HELPERS = runpy.run_path(str(Path(__file__).with_name("test_novel_agent_pipeline_v5.py")))


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "CANONICAL_REGISTRY", tmp_path / "canonical")
    monkeypatch.setattr(runtime.core, "_legacy_blocks", lambda *a, **kw: [])
    source = tmp_path / "novel.txt"
    source.write_text("这是图编排的独立小说夹具，他站在房间里抬头答话。", encoding="utf-8")
    run = tmp_path / "run"
    runtime.prepare(run, source_path=source, title="Graph test story")
    return run


def test_real_graph_runs_whole_native_flow_and_sqlite_only_stores_references(prepared):
    clients = HELPERS["FakeClients"](HELPERS["success_values"]())
    result = graph.execute_graph(prepared, clients=clients)
    assert result["status"] == "text_ready_for_production"
    assert len(clients.calls) == 4
    assert result["graph_budget_authority"] is False
    with sqlite3.connect(result["graph_checkpoint_path"]) as connection:
        rows = connection.execute("SELECT count(*) FROM checkpoints").fetchone()[0]
        assert rows >= 4
    final = graph.execute_graph(prepared, clients=HELPERS["FakeClients"]([]))
    assert final["calls_started"] == 4


def test_graph_pause_and_restart_cannot_reset_native_requests_or_stage_caps(prepared):
    clients = HELPERS["FakeClients"](HELPERS["success_values"]())
    first = graph.execute_graph(prepared, clients=clients, max_nodes=1)
    assert first["calls_started"] == 1 and first["stage"] == "review_full"
    result = graph.execute_graph(prepared, clients=clients)
    assert result["status"] == "text_ready_for_production"
    assert len(clients.calls) == 4
    assert first["graph_thread_id"] == result["graph_thread_id"]


def test_native_call_completed_before_graph_checkpoint_failure_is_not_resent(prepared, monkeypatch):
    StateGraph, START, END, SqliteSaver, tracing_context = graph._imports()
    original = SqliteSaver.put
    failed = False
    def put(saver, *args, **kwargs):
        nonlocal failed
        # Do not poll Windows state.json from the background saver thread:
        # holding its read handle can itself interfere with atomic replacement.
        checkpoint = args[1] if len(args) > 1 else kwargs.get("checkpoint", {})
        if checkpoint.get("channel_values", {}).get("calls_started", 0) >= 1 and not failed:
            failed = True
            raise OSError("Injected graph checkpoint failure after native result")
        return original(saver, *args, **kwargs)
    monkeypatch.setattr(SqliteSaver, "put", put)
    clients = HELPERS["FakeClients"](HELPERS["success_values"]())
    with pytest.raises(OSError, match="graph checkpoint failure"):
        graph.execute_graph(prepared, clients=clients)
    saved = runtime.inspect(prepared)
    assert saved["calls_started"] >= 1
    already_called = len(clients.calls)
    monkeypatch.setattr(SqliteSaver, "put", original)
    result = graph.execute_graph(prepared, clients=clients)
    assert result["status"] == "text_ready_for_production"
    assert already_called <= 4 and len(clients.calls) == 4


def test_graph_does_not_automatically_retry_unknown_native_request(prepared):
    clients = HELPERS["FakeClients"]([KeyboardInterrupt()])
    with pytest.raises(KeyboardInterrupt):
        graph.execute_graph(prepared, clients=clients)
    assert len(clients.calls) == 1
    with pytest.raises(RuntimeError, match="未知"):
        graph.execute_graph(prepared, clients=HELPERS["FakeClients"]([]))
    state = runtime.inspect(prepared)
    assert state["pending_call"] == 1 and state["calls_started"] == 1


def test_graph_recovers_verified_projection_without_counting_old_request_as_new(prepared):
    initial = (prepared / "state.json").read_bytes()
    clients = HELPERS["FakeClients"](HELPERS["success_values"]())
    runtime.execute(prepared, clients=clients, max_steps=1)
    (prepared / "state.json").write_bytes(initial)
    assert runtime.inspect(prepared)["projection_recovery_available"] is True
    result = graph.execute_graph(prepared, clients=clients)
    assert result["status"] == "text_ready_for_production"
    assert result["graph_dispatched_requests"] == 3
    assert len(clients.calls) == 4


def test_graph_does_not_recover_projection_from_incomplete_native_evidence(prepared):
    initial = (prepared / "state.json").read_bytes()
    runtime.execute(prepared, clients=HELPERS["FakeClients"](HELPERS["success_values"]()), max_steps=1)
    (prepared / "state.json").write_bytes(initial)
    (prepared / "RESPONSE_001.json").unlink()
    result = graph.execute_graph(prepared, clients=HELPERS["FakeClients"]([]))
    assert result["status"] == "evidence_invalid"
    assert result["projection_recovery_available"] is False
    assert not (prepared / "GRAPH_CHECKPOINTS.sqlite3").exists()


def test_graph_cannot_create_files_in_unprepared_or_legacy_run(tmp_path):
    run = tmp_path / "not-prepared"
    result = graph.execute_graph(run)
    assert result["status"] == "unprepared"
    assert not run.exists()
    run.mkdir()
    (run / "BINDING.json").write_text(json.dumps({"schema": "legacy"}), encoding="utf-8")
    before = {p.name: p.read_bytes() for p in run.iterdir()}
    with pytest.raises((KeyError, OSError, ValueError)):
        graph.execute_graph(run)
    assert {p.name: p.read_bytes() for p in run.iterdir()} == before
