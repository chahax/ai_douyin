"""Offline seeded continuation. Synthetic passes are not creative approval."""
from copy import deepcopy
import json
import sqlite3
import pytest

from scripts import run_goal_context_text_production_v5 as runner
from src.content_factory import creative_goal_context_workflow_v4 as workflow
from src.content_factory import creative_goal_audit_citation_contract_v1 as citations
from tests import test_goal_context_text_production_v4 as helper
from tests.test_creative_goal_context_workflow_v3 import scenario as prior_scenario


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    import socket
    def deny(*args, **kwargs):
        raise AssertionError("offline fixture must never connect to a provider")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


@pytest.fixture
def scenario(prior_scenario):
    inputs, profile, goal, _, _, native = prior_scenario
    prepared = workflow.prepare_goal_audit_request(inputs, profile, goal)
    ref = next(iter(citations.build_evidence_catalog(goal)))
    judgment = {"status": "pass", "reason": "合成合同测试，不是生产审查", "required_revision": ""}
    audit = {"schema": citations.VERSION, "goal_sha256": runner.digest(goal),
        "audit_context_sha256": prepared["request"]["structured_schema"]["properties"]["audit_context_sha256"]["const"],
        "claim_checks": {row["id"]: deepcopy(judgment) for row in goal["claims"]},
        "goal_checks": {key: {**deepcopy(judgment), "evidence_refs": [ref]} for key in workflow.GOAL_CHECKS}}
    return inputs, profile, goal, audit, workflow.origin_ids(inputs), native


def temp_run(tmp_path, monkeypatch, scenario, modes=None):
    monkeypatch.setattr(helper, "runner", runner)
    runtime, root, sends = helper.temporary_run(tmp_path, monkeypatch, scenario, modes)
    runner.write(root / "INHERITED_NATIVE_GOAL.json", scenario[2], True)
    return runtime, root, sends


def test_seed_audit_actual_reference_catalog_then_full_native_flow(tmp_path, monkeypatch, scenario):
    runtime, root, sends = temp_run(tmp_path, monkeypatch, scenario)
    state = runner.run()
    assert helper.stages(sends) == ["goal_audit", "complete_script", "full_review"]
    assert state["status"] == "text_ready_for_director" and state["native_goal_ordinal"] == 536
    assert state["cumulative_goal_candidates_used"] == 6
    assert not state["human_quality_approved"] and not state["creative_quality_passed"]
    payload = json.loads(sends[0]["messages"][1]["content"])
    assert payload["native_goal_document"] == scenario[2]
    assert payload["goal_evidence_catalog"] == citations.build_evidence_catalog(scenario[2])
    assert runtime.summary()["new_calls"] == 3
    assert runtime.summary()["historical_pending_ordinals"] == [70, 160]
    assert runtime.summary()["unknown_token_reservations"] == 93117
    before = runtime.ledger.read_bytes()
    with pytest.raises(FileExistsError):
        runner.run()
    assert runtime.ledger.read_bytes() == before and len(sends) == 3


@pytest.mark.parametrize("mode", ["missing_tool", "truncated", "usage_unknown", "transport_unknown", "model_mismatch", "null_document", "incomplete_review", "unknown"])
def test_seed_protocol_or_unknown_stops_without_repeating(tmp_path, monkeypatch, scenario, mode):
    _, root, sends = temp_run(tmp_path, monkeypatch, scenario, {("goal_audit", 1): mode})
    state = runner.run()
    assert state["status"].startswith("halt_seed_audit_")
    assert helper.stages(sends) == ["goal_audit"]
    assert not (root / "TEXT_HANDOFF.json").exists()


def test_semantic_seed_rejection_generates_complete_new_plan_then_script(tmp_path, monkeypatch, scenario):
    _, root, sends = temp_run(tmp_path, monkeypatch, scenario, {("goal_audit", 1): "fail"})
    state = runner.run()
    assert state["status"] == "text_ready_for_director"
    assert helper.stages(sends) == ["goal_audit", "goal_plan", "goal_audit", "complete_script", "full_review"]
    repair = json.loads(sends[1]["messages"][1]["content"])
    assert repair["previous_complete_document"] == scenario[2]
    assert repair["revision_diagnostics"]["complete_same_source_goal_audit"]["findings"]
    assert runner.read(root / "goals/native_01.json") != scenario[2]
    assert state["cumulative_goal_candidates_used"] == 7


def test_seed_plus_two_whole_plan_revisions_are_bounded(tmp_path, monkeypatch, scenario):
    _, root, sends = temp_run(tmp_path, monkeypatch, scenario,
        {("goal_audit", i): "fail" for i in (1, 2, 3)})
    state = runner.run()
    assert state["status"] == "halt_goal_content_capacity_exhausted"
    assert helper.stages(sends) == ["goal_audit", "goal_plan", "goal_audit", "goal_plan", "goal_audit"]
    assert state["cumulative_goal_candidates_used"] == 8
    assert not (root / "TEXT_HANDOFF.json").exists()


@pytest.mark.parametrize("stage,mode", [("complete_script", "bad_order"), ("full_review", "fail")])
def test_whole_script_repair_reuses_same_native_goal_and_audit(tmp_path, monkeypatch, scenario, stage, mode):
    _, root, sends = temp_run(tmp_path, monkeypatch, scenario, {(stage, 1): mode})
    state = runner.run()
    assert state["status"] == "text_ready_for_director"
    authors = [row for row in sends if row["stage"] == "complete_script"]
    assert len(authors) == 2 and helper.stages(sends).count("goal_audit") == 1
    assert authors[0]["input_provenance"]["goal_audit_sha256"] == authors[1]["input_provenance"]["goal_audit_sha256"]
    revised = json.loads(authors[1]["messages"][1]["content"])
    assert revised["previous_complete_document"] == runner.read(root / "scripts/version_01/NATIVE_SCRIPT.json")
    assert revised["revision_diagnostics"]


def test_goal_repair_context_does_not_enter_first_screenplay(tmp_path, monkeypatch, scenario):
    inputs, *rest = scenario
    dirty = {**deepcopy(inputs), "previous_complete_document": scenario[2],
        "revision_diagnostics": {"old_goal_error": "not a screenplay error"},
        "revision_requirements": ["not an author instruction"]}
    _, _, sends = temp_run(tmp_path, monkeypatch, (dirty, *rest))
    assert runner.run()["status"] == "text_ready_for_director"
    author = json.loads(sends[1]["messages"][1]["content"])
    for key in ("previous_complete_document", "revision_diagnostics", "revision_requirements"):
        assert key not in author


def test_preparation_preserves_actual_spent_lineage_and_native_seed(tmp_path, monkeypatch):
    parent = runner.PREFLIGHT_PARENT
    before = (parent / "CALL_LEDGER.json").read_bytes()
    root, claim = tmp_path / "newrun", tmp_path / "claim/CLAIM.json"
    approval = tmp_path / "approval.json"
    runner.write(approval, {"human_authorized": True, "user_quote": "minimax随便追加",
        "parent_ledger_sha256": runner.sha_file(parent / "CALL_LEDGER.json"),
        "parent_goal_candidates_used": 6, "authority_source_sha256": runner.sha_file(runner.previous.APPROVAL)}, True)
    monkeypatch.setattr(runner, "ROOT", root)
    monkeypatch.setattr(runner, "CLAIM", claim)
    monkeypatch.setattr(runner, "APPROVAL", approval)
    result = runner.prepare()
    assert result["new_calls"] == 0 and result["effective_calls_started"] == 537
    assert result["effective_reported_tokens"] == 10218615
    assert result["effective_calls_with_known_usage"] == 535
    assert result["historical_pending_ordinals"] == [70, 160]
    assert result["unknown_token_reservations"] == 93117
    assert (parent / "CALL_LEDGER.json").read_bytes() == before
    assert runner.read(root / "INHERITED_NATIVE_GOAL.json") == runner.read(parent / "goals/native_03.json")
    assert not (root / "RUN_CLAIM.json").exists()
    assert runner.read(root / "USER_SCOPE.json")["stage_limits"]["goal_plan"] == 2
