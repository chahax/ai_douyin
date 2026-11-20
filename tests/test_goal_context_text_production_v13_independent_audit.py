"""Remaining-scope coordinator and authorization checks; synthetic service only.

The shared replay creates provider envelopes and current-schema native documents.
All policy assertions below exercise v13, not the old coordinator's allowance.
"""
from copy import deepcopy
import json
from pathlib import Path
import socket
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import run_goal_context_text_production_v13 as runner
from scripts import record_review_feedback_continuation_v1 as authorizer
from tests import test_goal_context_production_v12 as provider_fixture
from tests.test_creative_goal_context_workflow_v7_independent_audit import causal_scenario, prior_scenario

INHERITED = {"calls_started": 570, "reported_tokens": 11068061,
    "calls_with_known_usage": 568, "pending_ordinals": [70, 160],
    "unknown_token_reservations": 93117}
PRIOR_GUARD, PREPARE = runner.prior_guard, runner.prepare


@pytest.fixture(autouse=True)
def no_real_provider_or_parent_runtime(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("independent v13 test cannot contact provider or acquire real parent runtime")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(runner.previous, "get_runtime", deny)
    monkeypatch.setattr(runner, "prior_guard", deny)


def replay(tmp_path, monkeypatch, scenario, modes=None):
    scenario = deepcopy(scenario)
    scenario[4]["native_drama_audit"]["closed_scope_findings"] = []
    monkeypatch.setattr(provider_fixture, "runner", runner)
    monkeypatch.setattr(provider_fixture, "INHERITED", deepcopy(INHERITED))
    constructor = provider_fixture.adapter.GoalContextRuntime
    def current_runtime(*args, **kwargs):
        kwargs["stage_limits"] = {"goal_plan": 3, "goal_audit": 2, "complete_script": 3, "full_review": 6}
        return constructor(*args, **kwargs)
    monkeypatch.setattr(provider_fixture.adapter, "GoalContextRuntime", current_runtime)
    runtime, root, sends = provider_fixture.replay(tmp_path, monkeypatch, scenario, modes)
    # Capacity is bound before the synthetic runtime's immutable policy is saved.
    return runtime, root, sends


def assert_no_reentry(runtime, root, sends):
    ledger = runtime.ledger.read_bytes()
    db_path = root / "TASKS.sqlite3"
    if db_path.exists():
        with sqlite3.connect(db_path) as db:
            claims = db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
    else:
        claims = None
    sent = len(sends)
    with pytest.raises(FileExistsError):
        runner.run()
    assert runtime.ledger.read_bytes() == ledger and len(sends) == sent
    if claims is None:
        assert not db_path.exists()
    else:
        with sqlite3.connect(db_path) as db:
            assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == claims


def test_remaining_native_plan_handoff_preserves570_spend_and17_candidate_maximum(
        tmp_path, monkeypatch, causal_scenario):
    runtime, root, sends = replay(tmp_path, monkeypatch, causal_scenario)
    preview = runner.read(root / "FIRST_GOAL_REQUEST_PREVIEW.json")
    result = runner.run()
    assert result["status"] == "text_ready_for_director", result
    assert sends[0] == preview["request"]
    assert provider_fixture.phases(sends) == ["goal_plan", "source", "drama", "opening_setup",
        "complete_script", "semantic", "physical"]
    ledger = runner.read(runtime.ledger)
    assert ledger["starting_spend"] == INHERITED
    assert [row["ordinal"] for row in ledger["calls"]] == list(range(571, 578))
    assert [row["label"] for row in ledger["calls"] if row["label"].startswith("goal_plan_")] == ["goal_plan_17"]
    assert result["inherited_goal_candidates_used"] == 16
    assert result["cumulative_goal_candidates_used"] == 17
    assert result["old_director_capacity"] == {"used": 7, "limit": 7, "remaining": 0}
    spend = runtime.summary()
    assert spend["effective_calls_started"] == 577
    assert spend["effective_reported_tokens"] == 11068761
    assert spend["effective_calls_with_known_usage"] == 575
    assert spend["historical_pending_ordinals"] == [70, 160]
    assert spend["unknown_token_reservations"] == 93117 and not spend["old_budget_reset"]
    handoff = runner.read(root / "TEXT_HANDOFF.json")
    assert handoff["native_goal_audit"]["schema"] == runner.drama_contract.BUNDLE_VERSION
    assert handoff["native_goal_audit"]["native_drama_audit"]["closed_scope_findings"] == []
    assert handoff["next_stage_requires_reconciled_director_lineage"]
    assert not handoff["media_authorized"] and not handoff["production_dispatch_eligible"]
    assert not result["human_quality_approved"] and not result["creative_quality_passed"]
    assert_no_reentry(runtime, root, sends)


@pytest.mark.parametrize("stage,mode,expected", [
    ("goal_plan", "contract_fail", ["goal_plan"]),
    ("drama", "commitment_fail", ["goal_plan", "source", "drama"]),
    ("goal_plan", "transport_unknown", ["goal_plan"]),
    ("goal_plan", "usage_unknown", ["goal_plan"]),
    ("goal_plan", "truncated", ["goal_plan"]),
])
def test_failed_remaining_goal_cannot_regrant_second_goal_or_restart_original(
        tmp_path, monkeypatch, causal_scenario, stage, mode, expected):
    runtime, root, sends = replay(tmp_path, monkeypatch, causal_scenario, {(stage, 1): mode})
    result = runner.run()
    assert provider_fixture.phases(sends) == expected
    assert result["status"] in {"halt_goal_content_capacity_exhausted", "halt_goal_interface_or_unknown"}
    assert result["cumulative_goal_candidates_used"] == 17
    assert not (root / "goals/native_02.json").exists()
    assert not (root / "setups").exists() and not (root / "TEXT_HANDOFF.json").exists()
    assert not runtime.summary()["old_budget_reset"]
    assert_no_reentry(runtime, root, sends)


def test_two_remaining_setups_three_bodies_six_reviews_do_not_add_whole_planning_capacity(
        tmp_path, monkeypatch, causal_scenario):
    modes = {("opening_setup", 1): "contract_fail", ("physical", 1): "fail", ("physical", 2): "fail"}
    runtime, root, sends = replay(tmp_path, monkeypatch, causal_scenario, modes)
    result = runner.run()
    assert result["status"] == "text_ready_for_director", result
    assert runtime.summary()["stage_calls"] == {"goal_plan": 3, "goal_audit": 2,
        "complete_script": 3, "full_review": 6}
    assert result["opening_setup_calls"] == 2 and result["cumulative_goal_candidates_used"] == 17
    assert [row["label"] for row in runner.read(runtime.ledger)["calls"] if row["label"].startswith("goal_plan_")] == ["goal_plan_17"]
    assert not (root / "goals/native_02.json").exists()
    assert not (root / "scripts/version_04").exists()
    assert_no_reentry(runtime, root, sends)


def test_frozen_actual_request_drift_stops_before_first_provider_attempt(
        tmp_path, monkeypatch, causal_scenario):
    runtime, root, sends = replay(tmp_path, monkeypatch, causal_scenario)
    changed = runner.read(root / "FIRST_GOAL_REQUEST_PREVIEW.json")
    changed["request_sha256"] = "f" * 64
    runner.write(root / "FIRST_GOAL_REQUEST_PREVIEW.json", changed)
    with pytest.raises(ValueError, match="exact preview"):
        runner.run()
    assert sends == [] and runner.read(runtime.ledger)["calls"] == []
    assert_no_reentry(runtime, root, sends)


def parent_fixture(tmp_path, monkeypatch):
    parent = tmp_path / "known-local-stop-parent"
    summary = {"stage_calls": {"goal_plan": 1, "goal_audit": 2, "complete_script": 0, "full_review": 0},
        "stage_limits": {"goal_plan": 4, "goal_audit": 4, "complete_script": 3, "full_review": 6},
        "effective_calls_started": 570, "effective_reported_tokens": 11068061}
    rows = []
    for ordinal in (568, 569, 570):
        path = parent / f"native{ordinal}.json"
        runner.write(path, {"status": "contract_valid", "output": {"native": ordinal},
            "response_metadata": {"http_status_code": 200, "response_body_complete": True,
                "finish_reason": "tool_calls", "total_tokens": 1}})
        rows.append({"ordinal": ordinal, "receipt": path.name, "receipt_sha256": runner.sha_file(path)})
    runner.write(parent / "CALL_LEDGER.json", {"calls": rows})
    for name, data in {
        "STATE.json": {"status": "goal_received"},
        "EXECUTION_ERROR.json": {"status": "stopped_original_request_requires_reconciliation",
            "error_type": "ContextError", "new_request_dispatched_by_recovery": False},
        "RUN_CLAIM.json": {"pid": 12345, "automatic_restart": False},
        "USER_SCOPE.json": {"local_goal_candidates_limit": 2, "local_opening_setup_limit": 2,
            "inherited_goal_candidates_used": 15, "stage_limits": deepcopy(summary["stage_limits"])},
        "PRODUCTION_FREEZE.json": {"original_immutable": True},
    }.items():
        runner.write(parent / name, data)
    certificate = {"schema": "known_local_repair_build_stop/v1", "parent_root": str(parent),
        "observed_session_exit_code": 1, "all_provider_results_and_usage_known": True,
        "no_provider_dispatch_after_570": True, "error_type": "ContextError",
        "error_phase": "prepare second whole-goal request before invoke", "state_was_not_rewritten": True,
        "parent_spend": deepcopy(summary), "inherited_goal_candidates_used": 16,
        "remaining_from_original_scope": {"whole_goal_candidates": 1, "goal_audit_calls": 2,
            "opening_setup_candidates": 2, "complete_script_calls": 3, "full_review_calls": 6},
        "source_files": {str((parent / name).resolve()): runner.sha_file(parent / name) for name in
            ("STATE.json", "EXECUTION_ERROR.json", "RUN_CLAIM.json", "CALL_LEDGER.json", "USER_SCOPE.json", "PRODUCTION_FREEZE.json")}}
    cert_path = tmp_path / "stop_certificate.json"
    runner.write(cert_path, certificate)
    monkeypatch.setattr(runner, "PREFLIGHT_PARENT", parent)
    monkeypatch.setattr(runner, "TERMINAL_CERT", cert_path)
    runtime = SimpleNamespace(ledger=parent / "CALL_LEDGER.json", summary=Mock(return_value=deepcopy(summary)))
    monkeypatch.setattr(runner.previous, "get_runtime", Mock(return_value=runtime))
    return parent, cert_path, certificate, summary, runtime


def test_local_context_stop_uses_known_receipts_and_preserves_stale_goal_received_state(tmp_path, monkeypatch):
    parent, _, _, summary, runtime = parent_fixture(tmp_path, monkeypatch)
    original = {path: path.read_bytes() for path in parent.glob("*.json")}
    assert PRIOR_GUARD() == summary
    assert runtime.summary.call_count == 1
    assert {path: path.read_bytes() for path in original} == original
    assert runner.read(parent / "STATE.json")["status"] == "goal_received"


@pytest.mark.parametrize("change", ["parent_root", "source_set", "error_type", "remaining_goal", "unknown_usage", "changed_state", "ordinal", "total_tokens"])
def test_wrong_stop_certificate_or_parent_receipt_cannot_authorize_remaining_scope(tmp_path, monkeypatch, change):
    parent, cert_path, certificate, _, runtime = parent_fixture(tmp_path, monkeypatch)
    if change == "parent_root":
        certificate["parent_root"] = str(tmp_path / "unrelated-parent")
    elif change == "source_set":
        certificate["source_files"].pop(str((parent / "EXECUTION_ERROR.json").resolve()))
    elif change == "error_type":
        certificate["error_type"] = "TransportError"
    elif change == "remaining_goal":
        certificate["remaining_from_original_scope"]["whole_goal_candidates"] = 2
    elif change in ("unknown_usage", "total_tokens"):
        path = parent / "native570.json"
        value = runner.read(path)
        value["response_metadata"]["total_tokens"] = None if change == "unknown_usage" else True
        runner.write(path, value)
        ledger = runner.read(runtime.ledger)
        ledger["calls"][-1]["receipt_sha256"] = runner.sha_file(path)
        runner.write(runtime.ledger, ledger)
        certificate["source_files"][str(runtime.ledger.resolve())] = runner.sha_file(runtime.ledger)
    elif change == "changed_state":
        runner.write(parent / "STATE.json", {"status": "dispatching"})
    else:
        ledger = runner.read(runtime.ledger)
        ledger["calls"][-1]["ordinal"] = 571
        runner.write(runtime.ledger, ledger)
    runner.write(cert_path, certificate)
    with pytest.raises(ValueError):
        PRIOR_GUARD()
    assert not (parent / "NEW_RUN_CLAIM.json").exists()


@pytest.mark.parametrize("change", ["inputs", "profile", "diagnosis", "actual_request", "saved_preview"])
def test_authorization_four_identities_and_saved_preview_reject_drift_before_any_claim(tmp_path, monkeypatch, change):
    from scripts import creative_flat_lineage_guard_v1 as lineage
    project, parent, root = tmp_path / "project", tmp_path / "project/parent", tmp_path / "project/new-run"
    authority, approval, claim = project / "old-authority.json", project / "grant/USER_CONTINUATION.json", project / "grant/CLAIM.json"
    profile_path, cert_path = project / "profile.json", project / "stop.json"
    preview_path = project / "data/qa/creative_review_feedback_20261014/REVIEW_FEEDBACK_REQUEST_PREVIEW_v1.json"
    seed, diagnostic = {"native": "exact568"}, {"verified_pipeline_diagnosis": "original qualified evidence"}
    inputs, profile = {"source": "original"}, {"writer": "same model"}
    prepared = {"request": {"source": "exact actual preview"}, "wire": {"source": "exact actual preview"}}
    for key, value in {"PROJECT": project, "PREFLIGHT_PARENT": parent, "ROOT": root, "APPROVAL": approval,
            "CLAIM": claim, "PROFILE": profile_path, "TERMINAL_CERT": cert_path}.items():
        monkeypatch.setattr(runner, key, value)
    monkeypatch.setattr(runner.previous, "APPROVAL", authority)
    runner.write(authority, {"human_authorized": True, "user_quote": "minimax随便追加"})
    runner.write(cert_path, {"parent_spend": {"effective_calls_started": 570, "effective_reported_tokens": 11068061,
        "effective_calls_with_known_usage": 568, "historical_pending_ordinals": [70, 160], "unknown_token_reservations": 93117}})
    runner.write(parent / "STATE.json", {"status": "goal_received"})
    runner.write(parent / "receipt568.json", {"output": seed})
    runner.write(parent / "CALL_LEDGER.json", {"calls": [{"ordinal": 568, "receipt": "receipt568.json"}]})
    runner.write(parent / "INPUTS.json", inputs)
    runner.write(profile_path, profile)
    runner.write(approval, {"human_authorized": True, "user_quote": "minimax随便追加",
        "parent_ledger_sha256": runner.sha_file(parent / "CALL_LEDGER.json"), "parent_goal_candidates_used": 16,
        "authority_source_sha256": runner.sha_file(authority), **runner.authorization_request_identity(diagnostic, prepared)})
    runner.write(preview_path, {"prepared": prepared})
    diag_mock, request_mock = Mock(return_value=deepcopy(diagnostic)), Mock(return_value=deepcopy(prepared))
    if change == "inputs":
        runner.write(parent / "INPUTS.json", {"source": "different"})
    elif change == "profile":
        runner.write(profile_path, {"writer": "different model"})
    elif change == "diagnosis":
        diag_mock.return_value["verified_pipeline_diagnosis"] = "changed qualified evidence"
    elif change == "actual_request":
        request_mock.return_value["request"]["source"] = "different actual request"
    else:
        runner.write(preview_path, {"prepared": {"request": "changed saved preview"}})
    before = {path: path.read_bytes() for path in project.rglob("*.json")}
    monkeypatch.setattr(lineage, "build_lineage_certificate", Mock(return_value={"offline_certificate": True}))
    monkeypatch.setattr(runner, "verify_seed_native", Mock(return_value={"ordinal": 568}))
    monkeypatch.setattr(runner, "build_revision_diagnostics", diag_mock)
    monkeypatch.setattr(runner.parent, "source_gate", Mock(return_value={"offline_gate": True}))
    monkeypatch.setattr(runner.workflow, "prepare_goal_request", request_mock)
    writes, runtimes = Mock(side_effect=AssertionError("drift must precede every claim write")), Mock(side_effect=AssertionError("no runtime after drift"))
    monkeypatch.setattr(runner, "write", writes)
    monkeypatch.setattr(runner, "get_runtime", runtimes)
    with pytest.raises(ValueError, match="authorization.*changed"):
        PREPARE()
    assert writes.call_count == runtimes.call_count == 0
    assert not root.exists() and not claim.exists()
    assert {path: path.read_bytes() for path in before} == before


@pytest.fixture
def local_binding(tmp_path, monkeypatch):
    project, parent = tmp_path / "binding-project", tmp_path / "binding-project/parent"
    authority, approval, claim = project / "authority.json", project / "grant/USER_CONTINUATION.json", project / "grant/CLAIM.json"
    profile, certificate = project / "profile.json", project / "stop.json"
    preview = project / "data/qa/creative_review_feedback_20261014/REVIEW_FEEDBACK_REQUEST_PREVIEW_v1.json"
    seed, diagnostic = {"native": "exact-complete568"}, {"verified_failure": "known actual native evidence"}
    for key, value in {"PROJECT": project, "PREFLIGHT_PARENT": parent, "APPROVAL": approval, "CLAIM": claim,
            "ROOT": project / "run", "PROFILE": profile, "TERMINAL_CERT": certificate}.items():
        monkeypatch.setattr(runner, key, value)
    monkeypatch.setattr(runner.previous, "APPROVAL", authority)
    runner.write(authority, {"human_authorized": True, "user_quote": "minimax随便追加"})
    runner.write(certificate, {"schema": "known_local_repair_build_stop/v1", "parent_spend": {
        "effective_calls_started": 570, "effective_reported_tokens": 11068061}, "inherited_goal_candidates_used": 16})
    runner.write(parent / "STATE.json", {"status": "goal_received"})
    runner.write(parent / "receipt568.json", {"output": seed})
    runner.write(parent / "CALL_LEDGER.json", {"calls": [{"ordinal": 568, "receipt": "receipt568.json"}]})
    runner.write(parent / "INPUTS.json", {"source": "original source"})
    runner.write(profile, {"writer": "same exact model"})
    prepared = {"request": {"stage": "goal_plan", "actual_input": "same compiled prompt"}, "local_manifest": "same"}
    guard = Mock(return_value={"known": True})
    diagnosis = Mock(return_value=deepcopy(diagnostic))
    prepare = Mock(return_value=deepcopy(prepared))
    monkeypatch.setattr(runner, "prior_guard", guard)
    monkeypatch.setattr(runner, "verify_seed_native", Mock(return_value={"ordinal": 568, "semantic_approved": False}))
    monkeypatch.setattr(runner, "build_revision_diagnostics", diagnosis)
    monkeypatch.setattr(runner.workflow, "prepare_goal_request", prepare)
    monkeypatch.setattr(runner, "get_runtime", Mock(side_effect=AssertionError("authorizer cannot dispatch or acquire runtime")))
    monkeypatch.setattr(runner, "now", Mock(side_effect=["first-local-time", "later-local-time"] * 3))
    originals = {path: path.read_bytes() for path in project.rglob("*.json")}
    return {"project": project, "approval": approval, "claim": claim, "preview": preview,
        "originals": originals, "guard": guard, "diagnosis": diagnosis, "prepare": prepare}


def test_authorizer_reentry_and_missing_preview_recovery_do_not_regrant_or_change_old_evidence(local_binding):
    local = local_binding
    authorizer.main()
    approval_bytes, preview_bytes = local["approval"].read_bytes(), local["preview"].read_bytes()
    authorizer.main()
    assert local["approval"].read_bytes() == approval_bytes and local["preview"].read_bytes() == preview_bytes
    local["preview"].unlink()  # Only this synthetic partial local artifact is removed.
    authorizer.main()
    assert local["approval"].read_bytes() == approval_bytes and local["preview"].read_bytes() == preview_bytes
    bound = runner.read(local["approval"])
    assert bound["parent_goal_candidates_used"] == 16
    assert bound["seed_native_identity"]["ordinal"] == 568
    assert bound["parent_script_submissions"] == bound["parent_setup_submissions"] == 0
    assert not bound["old_ledger_reset"] and not bound["media_authorized"] and not bound["publish_authorized"]
    assert bound["writer_total_call_user_limit"] is None and not bound["automatic_transport_retry"]
    assert local["guard"].call_count == 3
    assert not local["claim"].exists() and not runner.ROOT.exists()
    assert {path: path.read_bytes() for path in local["originals"]} == local["originals"]


@pytest.mark.parametrize("drift", ["diagnosis", "request"])
def test_authorizer_missing_preview_recovery_rejects_changed_diagnosis_or_actual_request(local_binding, drift):
    local = local_binding
    authorizer.main()
    original = local["approval"].read_bytes()
    local["preview"].unlink()
    if drift == "diagnosis":
        local["diagnosis"].return_value = {"verified_failure": "changed original evidence"}
    else:
        local["prepare"].return_value["request"]["actual_input"] = "different actual prompt"
    with pytest.raises(ValueError, match="existing text authorization differs"):
        authorizer.main()
    assert local["approval"].read_bytes() == original and not local["preview"].exists()
    assert not local["claim"].exists() and not runner.ROOT.exists()
    assert {path: path.read_bytes() for path in local["originals"]} == local["originals"]


def test_authorizer_requires_exact_parent_guard_before_any_local_preparation(local_binding):
    local_binding["guard"].side_effect = ValueError("parent remains unreconciled")
    with pytest.raises(ValueError, match="unreconciled"):
        authorizer.main()
    assert local_binding["prepare"].call_count == local_binding["diagnosis"].call_count == 0
    assert not local_binding["approval"].exists() and not local_binding["preview"].exists()
    assert not local_binding["claim"].exists() and not runner.ROOT.exists()

