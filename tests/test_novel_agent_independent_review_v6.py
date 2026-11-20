"""Independent adversarial checks of versioned, zero-dispatch continuation."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

from src.content_factory import novel_agent_pipeline_v5 as parent_v5
from src.content_factory import novel_agent_pipeline_v6 as pipe

_spec = importlib.util.spec_from_file_location(
    "independent_v6_fixtures", Path(__file__).with_name("test_novel_agent_pipeline_v6.py"))
helper = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(helper)


@pytest.fixture
def environment(tmp_path, monkeypatch):
    canonical = tmp_path / "canonical"
    monkeypatch.setattr(pipe, "CANONICAL_REGISTRY", canonical)
    monkeypatch.setattr(parent_v5, "CANONICAL_REGISTRY", canonical)
    monkeypatch.setattr(pipe.core, "_legacy_blocks", lambda *args, **kwargs: [])
    source = tmp_path / "chapter.txt"
    source.write_text("第一章\n她在渡口与父亲告别，然后登船。", encoding="utf-8")
    return tmp_path, source, canonical


def test_same_owner_local_preparation_recovers_after_source_publication(environment, monkeypatch):
    base, _, _ = environment
    parent = helper.stopped_parent(environment)
    before = helper.snapshot(parent)
    child = base / "child"
    original_write = pipe.core._write
    fired = False

    def fail_after_source(path, value):
        nonlocal fired
        original_write(path, value)
        if Path(path) == child / "SOURCE.json" and not fired:
            fired = True
            raise OSError("Injected after local SOURCE.json publication")

    monkeypatch.setattr(pipe.core, "_write", fail_after_source)
    with pytest.raises(OSError, match="Injected"):
        pipe.prepare_continuation(child, parent_run=parent)
    monkeypatch.setattr(pipe.core, "_write", original_write)
    view = pipe.prepare_continuation(child, parent_run=parent)
    assert view["status"] == "running" and view["stage"] == "director_full"
    assert view["calls_started"] == 0 and not list(child.glob("REQUEST_*.json"))
    assert view["combined_calls_started"] == 2
    assert helper.snapshot(parent) == before


def test_mismatched_partial_source_is_not_overwritten(environment, monkeypatch):
    base, _, canonical = environment
    parent = helper.stopped_parent(environment)
    child = base / "child"
    original_write = pipe.core._write

    def fail_after_source(path, value):
        original_write(path, value)
        if Path(path) == child / "SOURCE.json":
            raise OSError("Injected after source")

    monkeypatch.setattr(pipe.core, "_write", fail_after_source)
    with pytest.raises(OSError):
        pipe.prepare_continuation(child, parent_run=parent)
    monkeypatch.setattr(pipe.core, "_write", original_write)
    (child / "SOURCE.json").write_text('{"different_source":true}', encoding="utf-8")
    damaged = (child / "SOURCE.json").read_bytes()
    with pytest.raises((ValueError, RuntimeError)):
        pipe.prepare_continuation(child, parent_run=parent)
    assert (child / "SOURCE.json").read_bytes() == damaged
    with pytest.raises(RuntimeError, match="分叉"):
        pipe.prepare_continuation(base / "another-child", parent_run=parent)
    assert len(list((canonical / "_continuations" / "v6").glob("*.json"))) == 1


def test_typed_physical_conflict_remains_blocking_after_string_projection(environment):
    base, _, _ = environment
    review = helper.string_review()
    first = review["scene_ledger"]["events"][0]
    first["after"] = [helper.fixtures.fact("standing")]
    second = deepcopy(first)
    second["event_id"] = "E02"
    second["context"]["continuity_from_event_id"] = "E01"
    second["before"] = [helper.fixtures.fact("sitting")]
    second["after"] = [helper.fixtures.fact("sitting")]
    review["scene_ledger"]["events"].append(second)
    parent = helper.stopped_parent(environment, review_value=review)
    child = base / "child"
    view = pipe.prepare_continuation(child, parent_run=parent)
    assert view["status"] == "needs_attention"
    assert view["calls_started"] == 0
    gate = pipe.core._read(child / "GATE_PARENT_002.json")
    assert gate["scene_analysis"]["candidates"]
    assert gate["gate"]["decision"] != "pass"
    assert not list(child.glob("REQUEST_*.json"))


@pytest.mark.parametrize("finish,unknown", [("length", False), ("stop", True)])
def test_saved_but_unknown_or_truncated_review_cannot_get_continuation(environment, finish, unknown):
    base, source, _ = environment
    parent = base / "parent"
    parent_v5.prepare(parent, source_path=source)
    clients = helper.fixtures.FakeClients([
        helper.fixtures.result("完整原生稿"),
        helper.fixtures.result(helper.string_review(), "director", finish=finish, unknown=unknown),
    ])
    with pytest.raises(RuntimeError):
        parent_v5.execute(parent, clients=clients)
    old = helper.snapshot(parent)
    assert (parent / "RESPONSE_002.json").exists()
    with pytest.raises(ValueError, match="格式停点"):
        pipe.prepare_continuation(base / "child", parent_run=parent)
    assert len(clients.calls) == 2 and helper.snapshot(parent) == old
    assert not (base / "child").exists()


def test_new_version_cannot_bypass_parent_alias_by_new_title_or_book_id(environment):
    base, source, _ = environment
    parent = helper.stopped_parent(environment)
    with pytest.raises(RuntimeError, match="重领"):
        pipe.prepare(base / "fresh", source_path=source, title="不同书名", book_id="different-book-id")
    assert parent_v5.inspect(parent)["status"] == "needs_attention"
    assert not (base / "fresh" / "BINDING.json").exists()
