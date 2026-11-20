"""Independent graph continuation and immutable native proof checks for v7."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

from src.content_factory import novel_agent_pipeline_v7 as pipe
from src.content_factory import novel_agent_graph_v7 as graph
from src.content_factory import novel_director_handoff_v7 as director

_spec = importlib.util.spec_from_file_location(
    "independent_v7_fixtures", Path(__file__).with_name("test_novel_agent_pipeline_v7.py"))
helper = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(helper)
chain = helper.chain


def test_graph_continuation_dispatches_only_one_review_and_preserves_parent_chain(chain):
    base, _, grand, parent, canonical = chain
    snapshots = {str(path): helper.snapshot(path) for path in (grand, parent, canonical)}
    child = base / "independent-v7"
    prepared = pipe.prepare_director_continuation(child, parent_run=parent)
    assert prepared["combined_calls_started"] == 4 and prepared["calls_started"] == 0
    clients = helper.fixtures.FakeClients([
        helper.fixtures.result(helper.fixtures.director_review(), "director")])
    view = graph.execute_graph(child, clients=clients)
    assert view["status"] == "text_ready_for_production", view["blockers"]
    assert view["graph_dispatched_requests"] == 1 and len(clients.calls) == 1
    assert view["combined_calls_started"] == 5 and view["combined_known_reported_tokens"] == 500
    assert view["state"]["director_revisions_used"] == 1
    assert clients.calls[0]["role"] == "director"
    payload = json.loads(clients.calls[0]["messages"][-1]["content"])
    assert payload["source_text"] == pipe.core._read(child / "SOURCE.json")["text"]
    assert payload["accepted_full_draft"] == (grand / "DRAFT_001.md").read_bytes().decode("utf-8")
    assert payload["director"]["timeline_binding"]["semantic_pass"] is False
    assert view["human_approved"] is False and view["media_generated"] is False
    assert helper.snapshot(grand) == snapshots[str(grand)]
    assert helper.snapshot(parent) == snapshots[str(parent)]
    for path, data in snapshots[str(canonical)].items():
        assert (canonical / path).read_bytes() == data
    again = graph.execute_graph(child, clients=helper.fixtures.FakeClients([]))
    assert again["graph_dispatched_requests"] == 0 and again["combined_calls_started"] == 5


def test_timeline_projection_cannot_hide_a_changed_director_performance(chain):
    base, _, _, parent, _ = chain
    child = base / "independent-v7"
    pipe.prepare_director_continuation(child, parent_run=parent)
    pipe.execute(child, clients=helper.fixtures.FakeClients([
        helper.fixtures.result(helper.fixtures.director_review(), "director")]))
    binding, state = pipe._verify(child)
    plan, review = pipe._verify_director_native(binding, state)
    damaged = deepcopy(plan)
    damaged["segments"][0]["performance"][0]["dialogue"] = "Changed text not present in the MiniMax native response."
    with pytest.raises(director.DirectorContractError) as caught:
        director.verify_native_evidence(damaged, review,
            source_binding=binding["source"]["binding_id"],
            draft_binding=state["active"]["writer_full"]["file"]["sha256"],
            native_evidence=pipe._director_native_evidence(binding, state))
    assert any(row["code"] == "DIRECTOR_NATIVE_DERIVATION_MISMATCH" for row in caught.value.errors)


def test_changing_review_payload_cannot_claim_another_permitted_stage_request(chain):
    base, _, _, parent, _ = chain
    child = base / "independent-v7"
    pipe.prepare_director_continuation(child, parent_run=parent)
    clients = helper.fixtures.FakeClients([
        helper.fixtures.result(helper.fixtures.director_review("revise"), "director")])
    view = pipe.execute(child, clients=clients)
    assert view["status"] == "director_revision_exhausted"
    binding, state = pipe._verify(child)
    with pipe.core._lock(child / ".execution.lock"):
        with pytest.raises(RuntimeError, match="已使用"):
            pipe._dispatch(child, binding, state, "director_review", {"different": "payload"}, clients)
    assert len(clients.calls) == 1
    assert len(list(child.glob("REQUEST_*.json"))) == 1
