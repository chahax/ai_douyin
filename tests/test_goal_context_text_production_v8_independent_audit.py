"""Targeted v8 control and full-source diagnostic audits, zero network calls.

Real parent files are read only and copied into pytest's workspace. Runtime
provider responses below are synthetic; they do not prove creative quality.
No production prepare, inherited recursive guard or original run is invoked.
"""
from copy import deepcopy
import json
from pathlib import Path
import socket
import sqlite3
from types import SimpleNamespace

import pytest

from scripts import run_goal_context_text_production_v8 as runner
from scripts import creative_goal_context_dispatch_v5 as adapter
from scripts import creative_bounded_format_role_clients_v1 as bounded
from scripts import creative_evidenced_role_clients_v1 as evidenced
from tests import test_goal_context_text_production_v4 as old_helpers
from tests.test_creative_goal_context_workflow_v7_independent_audit import causal_scenario, prior_scenario


INHERITED = {"calls_started": 546, "reported_tokens": 10457707, "calls_with_known_usage": 544,
             "pending_ordinals": [70, 160], "unknown_token_reservations": 93117}


@pytest.fixture(autouse=True)
def no_network_or_old_guard(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("independent replay must not contact providers or run an inherited guard")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(runner.previous, "get_runtime", deny)


def phase(request):
    if request["input_provenance"].get("substage") == "opening_setup":
        return "opening_setup"
    if request["stage"] == "goal_audit":
        return "source" if "claim_checks" in request["structured_schema"]["properties"] else "drama"
    return request["stage"]


def replay(tmp_path, monkeypatch, causal_scenario, outcomes=None):
    inputs, profile, goal, opening, bundle, _, native = deepcopy(causal_scenario)
    project, root = tmp_path / "project", tmp_path / "project/new_run"
    project.mkdir()
    source = project / "source.txt"
    source.write_text("仅合成离线数据", encoding="utf-8")
    profile_path = project / "profile.json"
    profile_path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(runner, "PROJECT", project)
    monkeypatch.setattr(runner, "ROOT", root)
    monkeypatch.setattr(runner, "PROFILE", profile_path)
    sends, counts = [], {}
    outcomes = outcomes or {}

    def factory(request):
        current = phase(request)
        counts[current] = counts.get(current, 0) + 1
        mode = outcomes.get((current, counts[current]), "valid")

        class Fake:
            def call(self, role, messages, *, max_tokens, temperature, thinking, structured_schema, evidence):
                sends.append(deepcopy(request))
                assert runner.read(runtime.ledger)["calls"][-1]["ordinal"] == evidence.identity["ordinal"]
                with sqlite3.connect(root / "TASKS.sqlite3") as db:
                    assert db.execute("SELECT COUNT(*) FROM attempts WHERE status='claimed'").fetchone()[0] == 1
                bounded.save_request_body(evidence, json.dumps(runner.clients.expected_wire_request(request),
                    ensure_ascii=False).encode(), role=role)
                if mode == "transport_unknown":
                    raise evidenced.EvidenceCallError("TRANSPORT_EXCEPTION", started=True, outcome_known=False)
                body = json.loads(messages[1]["content"])
                if current == "goal_plan":
                    value = deepcopy(goal)
                    value["whole_plan"]["premise"] = "合成完整新规划" + str(counts[current])
                elif current in ("source", "drama"):
                    value = deepcopy(bundle["native_" + current + "_audit"])
                    for field in ("goal_sha256", "audit_context_sha256"):
                        value[field] = structured_schema["properties"][field]["const"]
                    if mode == "unresolved_counterexample":
                        row = value["goal_checks"]["closed_production_scope"]
                        row["counterevidence_refs"] = row["evidence_refs"]
                elif current == "opening_setup":
                    value = deepcopy(opening)
                    value["goal_sha256"] = body["native_goal_sha256"]
                    if mode == "absent_container":
                        value["props"]["pen"]["container_prop_id"] = "paper"
                elif current == "complete_script":
                    value = deepcopy(native)
                else:
                    value = old_helpers.full_review(body, "valid")
                    value.update(schema=runner.reviews.VERSION,
                        opening_setup_sha256=runner.digest(body["native_opening_setup_document"]))
                    if mode == "plan_fail":
                        row = next(iter(value["goal_checks"].values()))
                        row.update(status="fail", required_revision="提交完整新原生规划，正文不能修补冻结来源。")
                message = {"role": "assistant", "content": None, "tool_calls": [{
                    "id": "offline", "type": "function", "function": {
                        "name": runner.clients.TOOL_NAME, "arguments": json.dumps(value, ensure_ascii=False)}}]}
                if mode == "missing_tool":
                    message = {"role": "assistant", "content": json.dumps(value, ensure_ascii=False)}
                response = {"id": "offline-" + str(evidence.identity["ordinal"]), "model": request["model"],
                    "choices": [{"index": 0, "message": message,
                        "finish_reason": "length" if mode == "truncated" else "tool_calls"}],
                    "usage": {"prompt_tokens": 90, "completion_tokens": 10, "total_tokens": 100}}
                if mode == "usage_unknown":
                    response.pop("usage")
                saved, manifest = evidence.save_body(json.dumps(response, ensure_ascii=False).encode(),
                    evidenced.http_metadata(200, {}))
                return evidenced.parse_saved_response(saved, manifest, role, request["model"],
                    thinking, structured_schema, evidence)
        return lambda: Fake()

    runtime = adapter.GoalContextRuntime(project, root, [source], deepcopy(INHERITED), profile=profile,
        stage_limits={"goal_plan": 4, "goal_audit": 4, "complete_script": 3, "full_review": 3},
        client_factory_builder=factory, quota_state=None)
    runtime.prepare()
    runner.write(root / "INPUTS.json", inputs, True)
    runner.write(root / "USER_SCOPE.json", {"stage_limits": runtime.stage_limits}, True)
    runner.write(root / "INHERITED_NATIVE_GOAL.json", goal, True)
    runner.write(root / "INHERITED_DIAGNOSTICS.json", {"seed_semantic_approved": False,
        "previous_complete_documents": "synthetic revision evidence, never adopted"}, True)
    monkeypatch.setattr(runner, "get_runtime", lambda: runtime)
    return runtime, root, sends


def test_new_native_setup_and_full_review_handoff_keep_full_spent_history(tmp_path, monkeypatch, causal_scenario):
    runtime, root, sends = replay(tmp_path, monkeypatch, causal_scenario)
    state = runner.run()
    assert state["status"] == "text_ready_for_director", state
    handoff = runner.read(root / "TEXT_HANDOFF.json")
    setup = runner.read(root / "setups/native_01.json")
    assert handoff["native_opening_setup"] == setup
    assert handoff["native_full_review"]["opening_setup_sha256"] == runner.digest(setup)
    for request in sends:
        assert not request.get("automatic_retry", False)
    author, review = [request for request in sends if phase(request) in ("complete_script", "full_review")]
    for request in (author, review):
        body = json.loads(request["messages"][1]["content"])
        assert body["native_opening_setup_document"] == setup
        assert body["native_goal_document"] == handoff["native_goal"]
        assert request["input_provenance"]["native_opening_setup_sha256"] == runner.digest(setup)
    witness = json.loads(review["messages"][1]["content"])["initial_evidence_catalog"]
    assert witness["initial:prop:pen"]["value"]["container_prop_id"] == "book"
    assert all(row["holder_character_id"] is None for row in handoff["views"]["brief"]["initial_state"]["prop_states"])
    spend = runtime.summary()
    assert spend["effective_calls_started"] == 552 and spend["effective_reported_tokens"] == 10458307
    assert spend["effective_calls_with_known_usage"] == 550
    assert spend["historical_pending_ordinals"] == [70, 160] and spend["unknown_token_reservations"] == 93117
    assert runner.read(runtime.ledger)["starting_spend"] == INHERITED
    assert state["inherited_goal_candidates_used"] == 9 and state["cumulative_goal_candidates_used"] == 10
    assert not any(state[key] for key in ("human_quality_approved", "creative_quality_passed", "media_authorized"))
    assert not spend["old_budget_reset"]
    before = runtime.ledger.read_bytes()
    with pytest.raises(FileExistsError):
        runner.run()
    assert runtime.ledger.read_bytes() == before and len(sends) == 6


def test_known_absent_container_requires_complete_native_setup_revision(tmp_path, monkeypatch, causal_scenario):
    runtime, root, sends = replay(tmp_path, monkeypatch, causal_scenario, {("opening_setup", 1): "absent_container"})
    state = runner.run()
    assert state["status"] == "text_ready_for_director", state
    setup_sends = [request for request in sends if phase(request) == "opening_setup"]
    assert len(setup_sends) == 2
    original = runner.read(root / "setups/native_01.json")
    revision = json.loads(setup_sends[1]["messages"][1]["content"])
    assert revision["previous_opening_setup"] == original
    assert original["props"]["pen"]["container_prop_id"] == "paper"
    assert revision["opening_setup_diagnostics"]
    assert runner.read(root / "TEXT_HANDOFF.json")["native_opening_setup"] == runner.read(root / "setups/native_02.json")
    assert state["cumulative_goal_candidates_used"] == 10 and state["opening_setup_calls"] == 2
    assert not runtime.summary()["old_budget_reset"]


@pytest.mark.parametrize("mode", ["truncated", "transport_unknown", "usage_unknown", "missing_tool"])
def test_setup_unknown_or_protocol_failure_never_dispatches_revision_or_restarts(tmp_path, monkeypatch, causal_scenario, mode):
    runtime, root, sends = replay(tmp_path, monkeypatch, causal_scenario, {("opening_setup", 1): mode})
    state = runner.run()
    assert state["status"] == "halt_opening_setup_interface_or_unknown"
    assert [phase(request) for request in sends] == ["goal_plan", "source", "drama", "opening_setup"]
    assert not (root / "TEXT_HANDOFF.json").exists() and state["spend"]["effective_calls_started"] == 550
    before = runtime.ledger.read_bytes()
    with pytest.raises(FileExistsError):
        runner.run()
    assert before == runtime.ledger.read_bytes() and len(sends) == 4
    assert not runtime.summary()["old_budget_reset"]


def test_pass_with_unresolved_counterexample_halts_before_setup(tmp_path, monkeypatch, causal_scenario):
    runtime, root, sends = replay(tmp_path, monkeypatch, causal_scenario,
        {("drama", 1): "unresolved_counterexample"})
    state = runner.run()
    assert state["status"] == "halt_goal_audit_contract_requires_pipeline_diagnosis"
    assert [phase(request) for request in sends] == ["goal_plan", "source", "drama"]
    assert not (root / "setups").exists() and not (root / "TEXT_HANDOFF.json").exists()
    assert runtime.summary()["effective_calls_started"] == 549


def test_unknown_full_review_does_not_turn_into_whole_script_repair_or_reset(tmp_path, monkeypatch, causal_scenario):
    runtime, root, sends = replay(tmp_path, monkeypatch, causal_scenario,
        {("full_review", 1): "transport_unknown"})
    state = runner.run()
    assert state["status"] == "halt_review_interface_or_unknown"
    assert sum(phase(request) == "complete_script" for request in sends) == 1
    assert sum(phase(request) == "full_review" for request in sends) == 1
    assert state["spend"]["historical_pending_ordinals"] == [70, 160]
    assert not state["text_ready_for_director"] and not (root / "TEXT_HANDOFF.json").exists()
    assert (root / "scripts/version_01/FULL_SCRIPT.md").exists()
    before = runtime.ledger.read_bytes()
    with pytest.raises(FileExistsError):
        runner.run()
    assert runtime.ledger.read_bytes() == before and len(sends) == 6


def test_full_review_plan_source_failure_cannot_be_repaired_by_a_new_body(tmp_path, monkeypatch, causal_scenario):
    # Current compiled plans deliberately have no plan_support rows. Exercise
    # the coordinator's typed decision boundary without inventing a native
    # plan row or claiming that v4 already derives this upstream route.
    native_validator = runner.reviews.validate_full_review
    def upstream_decision(*args, **kwargs):
        result = native_validator(*args, **kwargs)
        assert result["valid"] and not result["accepted"] and result["findings"]
        result["findings"][0]["target"] = "plan"
        result["synthetic_plan_target_control_boundary"] = True
        return result
    monkeypatch.setattr(runner.reviews, "validate_full_review", upstream_decision)
    runtime, root, sends = replay(tmp_path, monkeypatch, causal_scenario,
        {("full_review", 1): "plan_fail"})
    state = runner.run()
    first_decision = runner.read(root / "scripts/version_01/DECISION.json")
    assert first_decision["valid"] and not first_decision["accepted"]
    assert first_decision["synthetic_plan_target_control_boundary"]
    assert any(row["target"] == "plan" for row in first_decision["findings"])
    assert state["status"].startswith("halt_"), state
    assert not (root / "TEXT_HANDOFF.json").exists()
    assert sum(phase(request) == "complete_script" for request in sends) == 1
    assert sum(phase(request) == "full_review" for request in sends) == 1
    assert runtime.summary()["effective_calls_started"] == 552
    assert not runtime.summary()["old_budget_reset"]


def test_preview_wire_only_tamper_fails_before_ordinal_sql_claim_and_provider(tmp_path, monkeypatch, causal_scenario):
    runtime, root, sends = replay(tmp_path, monkeypatch, causal_scenario)
    inputs = runner.read(root / "INPUTS.json")
    prepared = runner.workflow.prepare_goal_request({**inputs,
        "previous_complete_document": runner.read(root / "INHERITED_NATIVE_GOAL.json"),
        "revision_diagnostics": runner.read(root / "INHERITED_DIAGNOSTICS.json")}, runner.read(runner.PROFILE))
    prepared["wire"]["max_completion_tokens"] += 1
    runner.write(root / "FIRST_GOAL_REQUEST_PREVIEW.json", prepared, True)
    before = runtime.ledger.read_bytes()
    with pytest.raises(ValueError, match="frozen exact preview"):
        runner.main(["run"])
    assert sends == [] and runner.read(runtime.ledger)["calls"] == []
    assert runtime.ledger.read_bytes() == before and not (root / "TASKS.sqlite3").exists()
    assert runner.read(root / "EXECUTION_ERROR.json")["new_request_dispatched_by_recovery"] is False


@pytest.fixture
def copied_parent(tmp_path, monkeypatch):
    original = runner.PREFLIGHT_PARENT
    parent = tmp_path / "read_only_parent_copy"
    parent.mkdir()
    diagnosis = deepcopy(runner.read(runner.CONTENT_DIAGNOSIS))
    for relative in ["CALL_LEDGER.json", "STATE.json", "call_542_goal_source_audit_01.json",
                     *diagnosis["source_file_sha256"]]:
        source, target = original / relative, parent / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    diagnosis["source_root"] = str(parent)
    diagnostic_file = tmp_path / "independent_diagnosis_copy.json"
    runner.write(diagnostic_file, diagnosis, True)
    monkeypatch.setattr(runner, "PREFLIGHT_PARENT", parent)
    monkeypatch.setattr(runner, "CONTENT_DIAGNOSIS", diagnostic_file)
    ledger = runner.read(parent / "CALL_LEDGER.json")
    seed_row = next(row for row in ledger["calls"] if row["ordinal"] == 541)
    seed = runner.read(parent / seed_row["receipt"])["output"]
    return parent, diagnostic_file, diagnosis, seed


def test_diagnostic_binds_all_seven_original_sources_without_adopting_seed(copied_parent):
    parent, _, verified, seed = copied_parent
    diagnostic = runner.build_revision_diagnostics(seed)
    assert diagnostic["native_goal_sha256"] == runner.digest(seed)
    assert diagnostic["previous_complete_script"] == runner.read(parent / "call_545_complete_script_01.json")["output"]
    identity = runner.verify_seed_native(seed)
    assert identity["contract_valid"] and identity["semantic_approved"] is False
    assert identity["used_only_for_complete_model_revision"] is True
    assert diagnostic["native_text_locally_patched"] is False
    assert diagnostic["independent_content_diagnosis"] == verified


@pytest.mark.parametrize("omitted", ["call_543_goal_drama_audit_01.json", "scripts/version_01/NATIVE_SCRIPT.json",
                                    "scripts/version_01/FULL_SCRIPT.md"])
def test_diagnostic_cannot_omit_a_cited_parent_source(copied_parent, omitted):
    _, file, verified, seed = copied_parent
    verified["source_file_sha256"].pop(omitted)
    runner.write(file, verified)
    with pytest.raises(ValueError):
        runner.build_revision_diagnostics(seed)


@pytest.mark.parametrize("target", ["root", "goal_sha", "file_sha", "escaped_path"])
def test_diagnostic_wrong_identity_hash_or_external_source_is_rejected(copied_parent, target):
    parent, file, verified, seed = copied_parent
    if target == "root":
        verified["source_root"] = str(parent.parent)
    elif target == "goal_sha":
        verified["native_goal_canonical_sha256"] = "0" * 64
    elif target == "file_sha":
        verified["source_file_sha256"]["scripts/version_01/FULL_SCRIPT.md"] = "0" * 64
    else:
        outside = parent.parent / "outside.txt"
        outside.write_text("不属于来源root", encoding="utf-8")
        verified["source_file_sha256"]["../outside.txt"] = runner.sha_file(outside)
    runner.write(file, verified)
    with pytest.raises(ValueError):
        runner.build_revision_diagnostics(seed)


def test_parent_terminal_guard_preserves_six_known_receipts_and_actual_spend(copied_parent, monkeypatch):
    parent, _, _, _ = copied_parent
    expected = runner.read(parent / "STATE.json")["spend"]
    calls = []
    def fake_parent_runtime():
        calls.append("snapshot")
        return SimpleNamespace(ledger=parent / "CALL_LEDGER.json", summary=lambda: deepcopy(expected))
    monkeypatch.setattr(runner.previous, "get_runtime", fake_parent_runtime)
    assert runner.prior_guard() == expected
    assert calls == ["snapshot"]
    assert expected["effective_calls_started"] == 546 and expected["effective_reported_tokens"] == 10457707
    assert expected["effective_calls_with_known_usage"] == 544
    assert expected["unknown_token_reservations"] == 93117 and expected["historical_pending_ordinals"] == [70, 160]
    state = runner.read(parent / "STATE.json")
    state["status"] = "opening_setup_in_progress"
    runner.write(parent / "STATE.json", state)
    with pytest.raises(ValueError, match="terminal"):
        runner.prior_guard()
