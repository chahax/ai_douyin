"""Independent cross-stage regressions; native envelopes are local fixtures only."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

from src.content_factory import novel_agent_pipeline_v5 as pipe


_spec = importlib.util.spec_from_file_location(
    "novel_v5_review_fixtures", Path(__file__).with_name("test_novel_agent_pipeline_v5.py"))
fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixtures)


@pytest.fixture
def independent_run(tmp_path, monkeypatch):
    monkeypatch.setattr(pipe, "CANONICAL_REGISTRY", tmp_path / "canonical")
    monkeypatch.setattr(pipe.core, "_legacy_blocks", lambda *args, **kwargs: [])
    source = tmp_path / "story.txt"
    source.write_text("原创测试源：他先站在桌前答话，随后坐下继续回答。", encoding="utf-8")
    run = tmp_path / "run"
    pipe.prepare(run, source_path=source, title="独立审查测试")
    return run


def _ambiguous_initial_ledger():
    initial = fixtures.review()
    second = fixtures.event()
    second.update(event_id="E02", before=[fixtures.fact("sitting")], after=[fixtures.fact("sitting")])
    second["context"]["continuity_from_event_id"] = "E01"
    initial["scene_ledger"]["events"].append(second)
    return initial


def test_same_draft_native_pass_can_correct_a_false_extraction_without_erasing_old_issue(independent_run):
    """Clarification can correct auxiliary extraction; the native story stays identical."""
    initial = _ambiguous_initial_ledger()
    client = fixtures.FakeClients([fixtures.result("完整稿：他站着回答，随后坐下继续回答。"),
                                  fixtures.result(initial, "director")])
    view = pipe.execute(independent_run, clients=client, max_steps=2)
    assert view["stage"] == "clarify_full"
    required = pipe.core._read(independent_run / "GATE_002.json")["scene_candidate_issues"]
    assert len(required) == 1

    corrected = fixtures.review(required=required, disposition="rejected")
    corrected["scene_ledger"] = deepcopy(initial["scene_ledger"])
    # The native reviewer now recognizes the sitting transition that the first
    # extractor had missed. Event identities are retained; this is not a rewrite.
    corrected["scene_ledger"]["events"][1]["before"] = [fixtures.fact("standing")]
    corrective = fixtures.FakeClients([fixtures.result(corrected, "director")])
    final = pipe.execute(independent_run, clients=corrective, max_steps=1)
    assert final["stage"] == "director_full", final["blockers"]
    assert final["state"]["revisions_used"] == 0
    saved = pipe.core._read(independent_run / "ADJUDICATION_003.json")
    assert saved["new_issues"] == required
    assert saved["dispositions"][0]["disposition"] == "rejected"
    assert len(client.calls) == 2 and len(corrective.calls) == 1


def test_director_response_saved_before_adoption_resumes_without_duplicate(independent_run, monkeypatch):
    pipe.execute(independent_run, clients=fixtures.FakeClients(fixtures.success_values()[:2]), max_steps=2)
    original = pipe._adopt_response
    monkeypatch.setattr(pipe, "_adopt_response", lambda *args: (_ for _ in ()).throw(KeyboardInterrupt()))
    sent = fixtures.FakeClients([fixtures.result(fixtures.plan())])
    with pytest.raises(KeyboardInterrupt):
        pipe.execute(independent_run, clients=sent)
    monkeypatch.setattr(pipe, "_adopt_response", original)
    last = fixtures.FakeClients([fixtures.result(fixtures.director_review(), "director")])
    result = pipe.execute(independent_run, clients=last)
    assert result["status"] == "text_ready_for_production"
    assert result["calls_started"] == 4 and result["known_reported_tokens"] == 400
    assert len(sent.calls) == 1 and len(last.calls) == 1


def test_old_rejected_candidate_cannot_settle_a_new_conflict(independent_run):
    initial = _ambiguous_initial_ledger()
    pipe.execute(independent_run, clients=fixtures.FakeClients([
        fixtures.result("完整稿：他站着回答，随后坐下继续回答。"),
        fixtures.result(initial, "director")]), max_steps=2)
    required = pipe.core._read(independent_run / "GATE_002.json")["scene_candidate_issues"]
    changed = fixtures.review(required=required, disposition="rejected")
    changed["scene_ledger"] = deepcopy(initial["scene_ledger"])
    changed["scene_ledger"]["events"][1]["before"] = [fixtures.fact("lying")]
    client = fixtures.FakeClients([fixtures.result(changed, "director")])
    result = pipe.execute(independent_run, clients=client, max_steps=1)
    assert result["status"] == "needs_attention"
    assert result["stage"] != "director_full"
    assert result["state"]["revisions_used"] == 0
    assert result["state"]["clarifications_used"] == 1
    assert result["calls_started"] == 3 and len(client.calls) == 1
    assert not (independent_run / "PRODUCTION_HANDOFF.json").exists()


def test_lost_handoff_file_cannot_redispatch_or_claim_complete(independent_run):
    pipe.execute(independent_run, clients=fixtures.FakeClients(fixtures.success_values()))
    (independent_run / "PRODUCTION_HANDOFF.json").unlink()
    client = fixtures.FakeClients([])
    view = pipe.execute(independent_run, clients=client)
    assert view["status"] == "incomplete_artifacts"
    assert client.calls == [] and view["calls_started"] == 4

