"""Presentation must not open mutable state while a provider runner owns its lock."""
from __future__ import annotations

from contextlib import nullcontext
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.web import natural_director_panel_v10 as panel


@pytest.fixture
def presentation(monkeypatch):
    events = []

    def capture(name):
        return lambda *args, **kwargs: events.append((name, args, kwargs))

    sink = SimpleNamespace(expander=lambda *args, **kwargs: nullcontext())
    for name in ("write", "code", "caption", "json", "info", "markdown"):
        setattr(sink, name, capture(name))
    monkeypatch.setattr(panel, "st", sink)
    monkeypatch.setattr(panel.history, "_log", capture("log"))
    return events


def _forbid(*args, **kwargs):
    raise AssertionError("a mutable or legacy reader ran while execution was locked")


def _checkpoint(run, *, number=4, stage="review_full"):
    path = run / f"STATE_{number:05}.json"
    path.write_text(json.dumps({"status": "running", "stage": stage, "calls_started": 1,
        "active": {"writer_full": {"file": {"path": str(run / "state.json")}}}}), encoding="utf-8")
    return path


@pytest.mark.parametrize("owner", ["writer", "director"])
@pytest.mark.parametrize("lock_name", [".execution.lock", ".graph_driver.lock"])
def test_active_source_or_director_skips_both_runtime_inspections_and_all_dynamic_artifacts(
        owner, lock_name, tmp_path, monkeypatch, presentation):
    source, director = tmp_path / "writer", tmp_path / "director"
    for run in (source, director):
        run.mkdir()
        _checkpoint(run)
        (run / "state.json").write_text("unreadable mutable projection", encoding="utf-8")
    (tmp_path / owner / lock_name).write_text("lock content must not be read", encoding="utf-8")
    monkeypatch.setattr(panel, "_runtime", _forbid)
    monkeypatch.setattr(panel.history, "artifact_files", _forbid)
    original = Path.read_bytes
    reads = []

    def checked_read(path):
        assert path.name == "STATE_00004.json"
        reads.append(path)
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", checked_read)
    panel._render_records(source, director)
    assert reads == [source / "STATE_00004.json", director / "STATE_00004.json"]
    snapshots = [args[0] for name, args, _ in presentation if name == "json"]
    assert len(snapshots) == 2
    assert all(row["current_state_verified"] is False for row in snapshots)
    assert all(row["checkpoint_summary"]["stage"] == "review_full" for row in snapshots)
    assert any(name == "log" for name, _, _ in presentation)


def test_latest_complete_checkpoint_falls_back_from_inflight_write_without_following_active_files(tmp_path):
    complete = _checkpoint(tmp_path)
    (tmp_path / "STATE_00005.json").write_text('{"stage":', encoding="utf-8")
    (tmp_path / "STATE_99999.json").write_text("[]", encoding="utf-8")
    (tmp_path / "STATE_z.json").write_text('{"stage":"invented"}', encoding="utf-8")
    snapshot = panel._last_immutable_checkpoint(tmp_path)
    assert snapshot["path"] == str(complete)
    assert snapshot["checkpoint_summary"]["stage"] == "review_full"
    assert "active" not in snapshot["checkpoint_summary"]
    assert snapshot["presentation_only"] is True and len(snapshot["sha256"]) == 64


def test_no_checkpoint_never_falls_back_to_mutable_state(tmp_path, monkeypatch, presentation):
    (tmp_path / "state.json").write_text('{"stage":"writer_full"}', encoding="utf-8")
    monkeypatch.setattr(Path, "read_bytes", _forbid)
    panel._render_inflight(tmp_path)
    assert not any(name == "json" for name, _, _ in presentation)
    assert any(name == "info" for name, _, _ in presentation)


@pytest.mark.parametrize("lock_name", [".execution.lock", ".graph_driver.lock"])
def test_direct_artifact_discovery_never_enters_legacy_state_reader_under_lock(
        lock_name, tmp_path, monkeypatch):
    (tmp_path / lock_name).touch()
    monkeypatch.setattr(panel.history, "artifact_files", _forbid)
    assert panel.artifact_files(tmp_path) == []


def test_lock_release_restores_normal_inspection_and_artifact_view(tmp_path, monkeypatch, presentation):
    source, director = tmp_path / "writer", tmp_path / "director"
    source.mkdir()
    director.mkdir()
    lock = source / ".execution.lock"
    lock.touch()
    calls = []
    runtime = SimpleNamespace(
        inspect_source=lambda run: calls.append(("writer", run)) or {"status": "running"},
        inspect=lambda run: calls.append(("director", run)) or {"status": "prepared"})
    monkeypatch.setattr(panel, "_runtime", lambda: runtime)
    artifacts = []
    monkeypatch.setattr(panel, "artifact_files", lambda run: artifacts.append(run) or [])
    panel._render_records(source, director)
    assert not calls and not artifacts
    lock.unlink()
    panel._render_records(source, director)
    assert calls == [("writer", source), ("director", director)]
    assert artifacts == [source, director]


@pytest.mark.parametrize("owner", ["writer", "director"])
def test_repeat_launch_rejects_execution_lock_before_inspection_or_process_start(
        owner, tmp_path, monkeypatch):
    source, director = tmp_path / "writer", tmp_path / "director"
    source.mkdir()
    director.mkdir()
    (tmp_path / owner / ".execution.lock").touch()
    authorization = tmp_path / "AUTHORIZATION.json"
    authorization.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(panel, "get_current_role", lambda: "editor")
    monkeypatch.setattr(panel, "_runtime", _forbid)
    monkeypatch.setattr(panel.subprocess, "Popen", _forbid)
    with pytest.raises(RuntimeError, match="正在执行"):
        panel.launch_source(source, director, authorization_path=authorization)
    assert not (source / ".natural_web_launch.lock").exists()


def test_history_path_view_respects_execution_lock_and_resumes_after_release(
        tmp_path, monkeypatch, presentation):
    lock = tmp_path / ".execution.lock"
    lock.touch()
    _checkpoint(tmp_path)
    monkeypatch.setattr(panel.history, "_runtime", _forbid)
    monkeypatch.setattr(panel.history, "_outputs", _forbid)
    panel._render_legacy_records(tmp_path)
    calls = []
    runtime = SimpleNamespace(inspect=lambda run: calls.append("inspect") or {},
                              preview=lambda run: calls.append("preview") or {})
    monkeypatch.setattr(panel.history, "_runtime", lambda run: (runtime, None))
    monkeypatch.setattr(panel.history, "_outputs", lambda *args: calls.append("outputs"))
    lock.unlink()
    panel._render_legacy_records(tmp_path)
    assert calls == ["inspect", "preview", "outputs"]


def test_lock_observed_after_inspect_prevents_legacy_artifact_read(tmp_path, monkeypatch, presentation):
    source, director = tmp_path / "writer", tmp_path / "director"
    source.mkdir()
    director.mkdir()

    def inspect(run):
        (source / ".execution.lock").touch()
        return {"status": "running"}

    monkeypatch.setattr(panel, "_runtime", lambda: SimpleNamespace(inspect_source=inspect, inspect=_forbid))
    monkeypatch.setattr(panel, "artifact_files", _forbid)
    panel._render_records(source, director)


def test_lock_observed_after_launch_admission_prevents_preview_and_process(tmp_path, monkeypatch):
    source, director = tmp_path / "writer", tmp_path / "director"
    source.mkdir()
    director.mkdir()
    authorization = tmp_path / "AUTHORIZATION.json"
    authorization.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(panel, "get_current_role", lambda: "editor")

    def inspect(run):
        (source / ".execution.lock").touch()
        return {"status": "prepared", "dispatch_blocked": False}

    monkeypatch.setattr(panel, "_runtime", lambda: SimpleNamespace(inspect_source=inspect, preview_source=_forbid))
    monkeypatch.setattr(panel.subprocess, "Popen", _forbid)
    with pytest.raises(RuntimeError, match="正在执行"):
        panel.launch_source(source, director, authorization_path=authorization)
    assert not (source / ".natural_web_launch.lock").exists()
