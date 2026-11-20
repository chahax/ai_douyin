"""Independent native state projection and inherited-capacity continuation."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

from src.content_factory import novel_agent_pipeline_v6 as pipe
from src.content_factory import novel_agent_pipeline_v5 as old

_spec = importlib.util.spec_from_file_location("v6_native_fixtures", Path(__file__).with_name("test_novel_agent_pipeline_v5.py"))
fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixtures)


@pytest.fixture
def environment(tmp_path, monkeypatch):
    canonical = tmp_path / "canonical"
    monkeypatch.setattr(pipe, "CANONICAL_REGISTRY", canonical)
    monkeypatch.setattr(old, "CANONICAL_REGISTRY", canonical)
    monkeypatch.setattr(pipe.core, "_legacy_blocks", lambda *args, **kwargs: [])
    source = tmp_path / "chapter.txt"
    source.write_text("第1章\n房间里，他站在桌前答话：我要自己决定。", encoding="utf-8")
    return tmp_path, source, canonical


def string_review(verdict="pass"):
    value = fixtures.review(verdict)
    value["scene_ledger"]["events"][0]["before"] = ["他站在桌前，准备回答。"]
    value["scene_ledger"]["events"][0]["after"] = ["他抬起头，说出决定。"]
    return value


def stopped_parent(environment, *, max_calls=20, max_total_tokens=500000, review_value=None):
    base, source, _ = environment
    run = base / "parent"
    old.prepare(run, source_path=source, book_id="new-test-story", title="独立测试", max_calls=max_calls,
                max_total_tokens=max_total_tokens, brief={"target_duration_seconds": 180})
    clients = fixtures.FakeClients([fixtures.result("背景、人物、高潮、改编规划。完整稿：他站在桌前答话，结尾。"),
                                   fixtures.result(review_value or string_review(), "director")])
    with pytest.raises(ValueError, match="Auxiliary review contract invalid"):
        old.execute(run, clients=clients)
    assert old.inspect(run)["status"] == "needs_attention"
    return run


def snapshot(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_local_continuation_uses_old_native_pass_without_model_or_old_mutation(environment):
    base, _, canonical = environment
    parent = stopped_parent(environment)
    old_bytes, aliases = snapshot(parent), snapshot(canonical)
    child = base / "v6"
    view = pipe.prepare_continuation(child, parent_run=parent)
    assert view["status"] == "running" and view["stage"] == "director_full"
    assert view["calls_started"] == 0 and view["known_reported_tokens"] == 0
    assert view["combined_calls_started"] == 2 and view["combined_known_reported_tokens"] == 200
    assert pipe.preview(child)["budget"]["max_calls"] == 18
    assert pipe.preview(child)["budget"]["max_total_tokens"] == 499800
    assert view["state"]["full_reviews_used"] == 1 and view["state"]["revisions_used"] == 0
    assert not list(child.glob("REQUEST_*.json"))
    assert pipe.core._read(child / "REVIEW_PARENT_002.json")["native_verdict"] == "pass"
    assert snapshot(parent) == old_bytes
    for name, data in aliases.items():
        assert (canonical / name).read_bytes() == data
    assert old.inspect(parent)["status"] == "needs_attention"
    assert len(list((canonical / "_continuations" / "v6").glob("*.json"))) == 1


def test_continuation_generates_only_director_and_full_director_review(environment):
    base, _, _ = environment
    parent = stopped_parent(environment)
    child = base / "child"
    pipe.prepare_continuation(child, parent_run=parent)
    clients = fixtures.FakeClients([fixtures.result(fixtures.plan()),
                                   fixtures.result(fixtures.director_review(), "director")])
    view = pipe.execute(child, clients=clients)
    assert view["status"] == "text_ready_for_production", view["blockers"]
    assert [call["role"] for call in clients.calls] == ["writer", "director"]
    assert view["calls_started"] == 2 and view["combined_calls_started"] == 4
    assert view["known_reported_tokens"] == 200 and view["combined_known_reported_tokens"] == 400
    assert view["human_approved"] is False and view["media_generated"] is False
    assert pipe.execute(child, clients=fixtures.FakeClients([]))["combined_calls_started"] == 4


def test_parent_unique_continuation_cannot_fork_or_reset_registry(environment):
    base, _, _ = environment
    parent = stopped_parent(environment)
    pipe.prepare_continuation(base / "child", parent_run=parent)
    with pytest.raises(RuntimeError, match="分叉"):
        pipe.prepare_continuation(base / "other", parent_run=parent)
    with pytest.raises(RuntimeError, match="重领"):
        pipe.prepare(base / "fresh", source_path=environment[1], book_id="new-test-story", title="renamed")


@pytest.mark.parametrize("field", ["parent_response", "parent_draft", "parent_state", "registry"])
def test_parent_frozen_evidence_mutation_blocks_child_before_dispatch(environment, field):
    base, _, canonical = environment
    parent = stopped_parent(environment)
    child = base / "child"
    pipe.prepare_continuation(child, parent_run=parent)
    path = {"parent_response": parent / "RESPONSE_002.json", "parent_draft": parent / "DRAFT_001.md",
            "parent_state": parent / "state.json", "registry": next(canonical.glob("book_*.json"))}[field]
    path.write_bytes(path.read_bytes() + b" ")
    client = fixtures.FakeClients([])
    with pytest.raises(ValueError):
        pipe.execute(child, clients=client)
    assert not client.calls and pipe.inspect(child)["dispatch_blocked"] is True


def test_exhausted_parent_cannot_receive_new_capacity(environment):
    base, _, _ = environment
    parent = stopped_parent(environment, max_calls=2)
    with pytest.raises(ValueError, match="耗尽"):
        pipe.prepare_continuation(base / "child", parent_run=parent)


@pytest.mark.parametrize("finish,unknown", [("length", False), ("stop", True)])
def test_unknown_or_truncated_parent_is_never_adopted(environment, finish, unknown):
    base, source, _ = environment
    parent = base / "parent"
    old.prepare(parent, source_path=source)
    with pytest.raises(RuntimeError):
        old.execute(parent, clients=fixtures.FakeClients([fixtures.result("完整稿", finish=finish, unknown=unknown)]))
    with pytest.raises(ValueError, match="格式停点"):
        pipe.prepare_continuation(base / "child", parent_run=parent)


def test_v6_new_story_uses_full_workflow_and_shared_registry(environment):
    base, source, _ = environment
    run = base / "fresh"
    pipe.prepare(run, source_path=source)
    view = pipe.execute(run, clients=fixtures.FakeClients(fixtures.success_values()))
    assert view["status"] == "text_ready_for_production"
    assert view["combined_calls_started"] == view["calls_started"] == 4
    assert view["inherited_consumption"] == {"calls_started": 0, "reported_tokens": 0}


def test_inherited_budget_stops_before_an_extra_director_review(environment):
    base, _, _ = environment
    parent = stopped_parent(environment, max_calls=3)
    child = base / "child"
    pipe.prepare_continuation(child, parent_run=parent)
    clients = fixtures.FakeClients([fixtures.result(fixtures.plan())])
    with pytest.raises(RuntimeError, match="预算耗尽"):
        pipe.execute(child, clients=clients)
    view = pipe.inspect(child)
    assert len(clients.calls) == 1 and view["combined_calls_started"] == 3
    assert pipe.preview(child)["remaining_calls"] == 0


def test_local_projection_does_not_override_native_revise_or_dispatch_writer(environment):
    base, _, _ = environment
    parent = stopped_parent(environment, review_value=string_review("revise"))
    child = base / "child"
    view = pipe.prepare_continuation(child, parent_run=parent)
    assert view["status"] == "needs_attention"
    assert view["calls_started"] == 0 and view["combined_calls_started"] == 2
    assert pipe.core._read(child / "REVIEW_PARENT_002.json")["native_verdict"] == "revise"
    assert pipe.execute(child, clients=fixtures.FakeClients([]))["calls_started"] == 0
    assert not list(child.glob("REQUEST_*.json"))


def test_empty_native_state_description_stops_local_projection_without_request(environment):
    base, _, _ = environment
    malformed = string_review()
    malformed["scene_ledger"]["events"][0]["before"] = [""]
    parent = stopped_parent(environment, review_value=malformed)
    view = pipe.prepare_continuation(base / "child", parent_run=parent)
    assert view["status"] == "needs_attention" and view["calls_started"] == 0
    assert any("Empty native scene-state" in item for item in view["blockers"])


def test_fresh_v6_freezes_roles_v5_dependency_and_blocks_changed_binding(environment, monkeypatch):
    base, source, _ = environment
    run = base / "fresh"
    pipe.prepare(run, source_path=source)
    old_roles_path = str(Path(old.roles.__file__).resolve())
    binding = pipe.core._read(run / "BINDING.json")
    assert any(row["path"] == old_roles_path for row in binding["code_bindings"])
    original = pipe.core._binding

    def changed_dependency(path):
        row = original(path)
        if row["path"] == old_roles_path:
            return {**row, "sha256": "simulated-changed-dependency"}
        return row

    monkeypatch.setattr(pipe.core, "_binding", changed_dependency)
    client = fixtures.FakeClients([])
    with pytest.raises(ValueError, match="冻结文件变化"):
        pipe.execute(run, clients=client)
    assert client.calls == []


@pytest.mark.parametrize("crash", [KeyboardInterrupt, OSError])
def test_local_parent_derivation_saved_file_can_resume_with_no_api(environment, monkeypatch, crash):
    base, _, _ = environment
    parent = stopped_parent(environment)
    child = base / "child"
    original = pipe._store
    fired = False

    def interrupt_saved_file(*args, **kwargs):
        nonlocal fired
        original(*args, **kwargs)
        if not fired and args[2] == "review_bundle":
            fired = True
            raise crash("Injected after complete local bundle publication")

    monkeypatch.setattr(pipe, "_store", interrupt_saved_file)
    with pytest.raises(crash):
        pipe.prepare_continuation(child, parent_run=parent)
    assert not list(child.glob("REQUEST_*.json"))
    monkeypatch.setattr(pipe, "_store", original)
    view = pipe.prepare_continuation(child, parent_run=parent)
    assert view["stage"] == "director_full" and view["status"] == "running"
    assert view["calls_started"] == 0 and view["combined_calls_started"] == 2
    assert not list(child.glob("REQUEST_*.json"))


@pytest.mark.parametrize("point", ["claim", "SOURCE.json", "CATALOG_FROZEN.json", "BINDING.json",
                                    "BINDING_ANCHOR.json", "STATE_00001.json"])
def test_known_partial_preparation_can_resume_same_claim_without_api(environment, monkeypatch, point):
    base, _, canonical = environment
    parent = stopped_parent(environment)
    child = base / "child"
    parent_bytes = snapshot(parent)
    original = pipe.core._write
    fired = False

    def fail_after_publication(path, value):
        nonlocal fired
        original(path, value)
        path = Path(path)
        matches = (path.parent == canonical / "_continuations" / "v6") if point == "claim" else path == child / point
        if matches and not fired:
            fired = True
            raise OSError("Injected preparation interruption: " + point)

    monkeypatch.setattr(pipe.core, "_write", fail_after_publication)
    with pytest.raises(OSError):
        pipe.prepare_continuation(child, parent_run=parent)
    monkeypatch.setattr(pipe.core, "_write", original)
    view = pipe.prepare_continuation(child, parent_run=parent)
    assert view["stage"] == "director_full" and view["status"] == "running"
    assert view["calls_started"] == 0 and view["combined_calls_started"] == 2
    assert not list(child.glob("REQUEST_*.json")) and not list(child.glob("RESPONSE_*.json"))
    assert snapshot(parent) == parent_bytes
    assert len(list((canonical / "_continuations" / "v6").glob("*.json"))) == 1


@pytest.mark.parametrize("tamper", ["wrong_source", "unknown_file", "unreceived_request"])
def test_partial_preparation_mismatch_or_unknown_evidence_cannot_be_overwritten(environment, monkeypatch, tamper):
    base, _, _ = environment
    parent = stopped_parent(environment)
    child = base / "child"
    original = pipe.core._write

    def stop_after_source(path, value):
        original(path, value)
        if Path(path) == child / "SOURCE.json":
            raise OSError("Pause local preparation")

    monkeypatch.setattr(pipe.core, "_write", stop_after_source)
    with pytest.raises(OSError):
        pipe.prepare_continuation(child, parent_run=parent)
    monkeypatch.setattr(pipe.core, "_write", original)
    if tamper == "wrong_source":
        (child / "SOURCE.json").write_text('{"another_source":true}', encoding="utf-8")
    else:
        (child / ("unknown.txt" if tamper == "unknown_file" else "REQUEST_001.json")).write_text("unknown", encoding="utf-8")
    before = snapshot(child)
    with pytest.raises(ValueError):
        pipe.prepare_continuation(child, parent_run=parent)
    assert snapshot(child) == before
