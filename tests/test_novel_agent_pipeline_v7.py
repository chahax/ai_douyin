"""V7 local director timeline projection preserves the complete spending chain."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

from src.content_factory import novel_agent_pipeline_v7 as pipe
from src.content_factory import novel_agent_pipeline_v6 as v6
from src.content_factory import novel_agent_pipeline_v5 as v5

_spec = importlib.util.spec_from_file_location("v7_fixtures", Path(__file__).with_name("test_novel_agent_pipeline_v5.py"))
fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixtures)


@pytest.fixture
def chain(tmp_path, monkeypatch):
    canonical = tmp_path / "canonical"
    for module in (pipe, v6, v5):
        monkeypatch.setattr(module, "CANONICAL_REGISTRY", canonical)
    monkeypatch.setattr(pipe.core, "_legacy_blocks", lambda *args, **kwargs: [])
    source = tmp_path / "source.txt"
    source.write_text("第1章\n他站在桌前抬头说：我要自己决定。", encoding="utf-8")
    grand = tmp_path / "v5"
    v5.prepare(grand, source_path=source, title="测试源", book_id="test-v7", brief={"target_duration_seconds": 180})
    review = fixtures.review()
    review["scene_ledger"]["events"][0].update(before=["他站在桌前。"], after=["他抬头答话。"])
    with pytest.raises(ValueError):
        v5.execute(grand, clients=fixtures.FakeClients([fixtures.result("完整背景人物规划及剧本：他在桌前抬头答话，结尾。"),
                    fixtures.result(review, "director")]))
    parent = tmp_path / "v6"
    v6.prepare_continuation(parent, parent_run=grand)
    invalid = fixtures.plan()
    invalid["segments"][0]["timeline_id"] = "now"
    view = v6.execute(parent, clients=fixtures.FakeClients([fixtures.result(invalid), fixtures.result(deepcopy(invalid))]))
    assert view["status"] == "director_revision_exhausted"
    assert view["combined_calls_started"] == 4
    return tmp_path, source, grand, parent, canonical


def snapshot(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_v7_local_plan_keeps_v6_failure_and_all_inherited_spending(chain):
    base, _, grand, parent, canonical = chain
    before_grand, before_parent, before_aliases = snapshot(grand), snapshot(parent), snapshot(canonical)
    child = base / "v7"
    view = pipe.prepare_director_continuation(child, parent_run=parent)
    assert view["status"] == "running" and view["stage"] == "director_review"
    assert view["calls_started"] == 0 and view["combined_calls_started"] == 4
    assert view["combined_known_reported_tokens"] == 400
    assert view["state"]["director_revisions_used"] == 1 and view["state"]["full_reviews_used"] == 1
    assert pipe.preview(child)["remaining_calls"] == 16
    assert pipe.preview(child)["remaining_known_tokens"] == 499600
    assert not list(child.glob("REQUEST_*.json"))
    assert snapshot(grand) == before_grand and snapshot(parent) == before_parent
    for path, data in before_aliases.items():
        assert (canonical / path).read_bytes() == data
    assert v6.inspect(parent)["status"] == "director_revision_exhausted"


def test_v7_only_new_service_call_is_same_director_deepseek_review(chain):
    base, _, _, parent, _ = chain
    child = base / "v7"
    pipe.prepare_director_continuation(child, parent_run=parent)
    client = fixtures.FakeClients([fixtures.result(fixtures.director_review(), "director")])
    view = pipe.execute(child, clients=client)
    assert view["status"] == "text_ready_for_production", view["blockers"]
    assert [call["role"] for call in client.calls] == ["director"]
    assert view["calls_started"] == 1 and view["combined_calls_started"] == 5
    assert view["combined_known_reported_tokens"] == 500
    assert view["state"]["director_revisions_used"] == 1
    assert pipe.execute(child, clients=fixtures.FakeClients([]))["calls_started"] == 1


def test_v7_native_director_revise_does_not_generate_another_director(chain):
    base, _, _, parent, _ = chain
    child = base / "v7"
    pipe.prepare_director_continuation(child, parent_run=parent)
    client = fixtures.FakeClients([fixtures.result(fixtures.director_review("revise"), "director")])
    view = pipe.execute(child, clients=client)
    assert view["status"] == "director_revision_exhausted" and view["calls_started"] == 1
    assert view["state"]["director_revisions_used"] == 1 and len(client.calls) == 1
    assert not (child / "PRODUCTION_HANDOFF.json").exists()


def test_v7_cannot_fork_parent_or_force_another_writer_stage(chain):
    base, _, _, parent, _ = chain
    child = base / "v7"
    pipe.prepare_director_continuation(child, parent_run=parent)
    with pytest.raises(RuntimeError, match="分叉"):
        pipe.prepare_director_continuation(base / "other", parent_run=parent)
    binding, state = pipe._verify(child)
    with pipe.core._lock(child / ".execution.lock"):
        with pytest.raises(RuntimeError, match="只允许"):
            pipe._dispatch(child, binding, state, "director_full", {}, fixtures.FakeClients([]))


@pytest.mark.parametrize("target", ["parent_response", "grand_response", "parent_draft"])
def test_v7_native_chain_tamper_stops_before_dispatch(chain, target):
    base, _, grand, parent, _ = chain
    child = base / "v7"
    pipe.prepare_director_continuation(child, parent_run=parent)
    path = {"parent_response": parent / "RESPONSE_002.json", "grand_response": grand / "RESPONSE_002.json",
            "parent_draft": grand / "DRAFT_001.md"}[target]
    path.write_bytes(path.read_bytes() + b" ")
    client = fixtures.FakeClients([])
    with pytest.raises(ValueError):
        pipe.execute(child, clients=client)
    assert not client.calls


@pytest.mark.parametrize("point", ["claim", "SOURCE.json", "BINDING.json", "BINDING_ANCHOR.json", "STATE_00001.json"])
def test_v7_partial_preparation_resumes_exact_owner_without_api(chain, monkeypatch, point):
    base, _, _, parent, canonical = chain
    child = base / "v7"
    original = pipe.core._write
    fired = False

    def fault(path, value):
        nonlocal fired
        original(path, value)
        path = Path(path)
        match = path.parent == canonical / "_continuations" / "v7" if point == "claim" else path == child / point
        if match and not fired:
            fired = True
            raise OSError("Preparation failure")

    monkeypatch.setattr(pipe.core, "_write", fault)
    with pytest.raises(OSError):
        pipe.prepare_director_continuation(child, parent_run=parent)
    monkeypatch.setattr(pipe.core, "_write", original)
    view = pipe.prepare_director_continuation(child, parent_run=parent)
    assert view["stage"] == "director_review" and view["calls_started"] == 0
    assert view["combined_calls_started"] == 4 and not list(child.glob("REQUEST_*.json"))


def test_v7_fresh_story_retains_complete_workflow(chain):
    base, _, _, _, _ = chain
    source = base / "fresh.txt"
    source.write_text("全新小说：他站在另一间房间里作出了决定。", encoding="utf-8")
    run = base / "fresh-v7"
    pipe.prepare(run, source_path=source, title="另一本小说")
    view = pipe.execute(run, clients=fixtures.FakeClients(fixtures.success_values()))
    assert view["status"] == "text_ready_for_production"
    assert view["calls_started"] == view["combined_calls_started"] == 4


def test_v7_rejects_v5_and_unexhausted_v6_parent(chain):
    base, _, grand, parent, _ = chain
    with pytest.raises(ValueError):
        pipe.prepare_director_continuation(base / "v7-v5-parent", parent_run=grand)
    assert not (base / "v7-v5-parent").exists()
    state = pipe.core._read(parent / "state.json")
    state["status"] = "running"
    pipe.core._save_state(parent, state)
    with pytest.raises(ValueError, match="停点"):
        pipe.prepare_director_continuation(base / "v7-unexhausted", parent_run=parent)


def test_v7_continuation_stage_scope_must_match_immutable_unique_claim(chain):
    base, _, _, parent, _ = chain
    child = base / "v7"
    pipe.prepare_director_continuation(child, parent_run=parent)
    binding = pipe.core._read(child / "BINDING.json")
    binding["continuation"]["allowed_new_stages"].append("director_full")
    (child / "BINDING.json").write_text(__import__("json").dumps(binding, ensure_ascii=False), encoding="utf-8")
    (child / "BINDING_ANCHOR.json").write_text(__import__("json").dumps({"sha256": pipe.core._digest(binding)}), encoding="utf-8")
    clients = fixtures.FakeClients([])
    with pytest.raises(ValueError, match="允许阶段"):
        pipe.execute(child, clients=clients)
    assert not clients.calls


@pytest.mark.parametrize("finish,unknown", [("length", False), ("stop", True)])
def test_v7_unknown_or_truncated_new_review_stops_without_another_request(chain, finish, unknown):
    base, _, _, parent, _ = chain
    child = base / "v7"
    pipe.prepare_director_continuation(child, parent_run=parent)
    with pytest.raises(RuntimeError):
        pipe.execute(child, clients=fixtures.FakeClients([
            fixtures.result(fixtures.director_review(), "director", finish=finish, unknown=unknown)]))
    view = pipe.inspect(child)
    assert view["status"] == "needs_attention" and view["pending_call"] == 1
    assert view["calls_started"] == 1 and view["combined_calls_started"] == 5
    assert pipe.execute(child, clients=fixtures.FakeClients([]))["calls_started"] == 1
