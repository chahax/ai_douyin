"""Independent modular coordinator replay through durable fake-service receipts."""
from copy import deepcopy
import json
import sqlite3

import pytest

from scripts import run_goal_context_text_production_v7 as runner
from scripts import creative_goal_context_dispatch_v5 as adapter
from scripts import creative_bounded_format_role_clients_v1 as bounded
from scripts import creative_evidenced_role_clients_v1 as evidenced
from tests import test_goal_context_text_production_v4 as helper
from tests.test_creative_goal_context_workflow_v6_independent_audit import audit_scenario, prior_scenario


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    import socket
    def deny(*args, **kwargs):
        raise AssertionError("independent coordinator fixture may not connect")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def phase_for(request):
    if request["input_provenance"].get("substage") == "opening_setup":
        return "opening_setup"
    if request["stage"] == "goal_audit":
        return "source" if "claim_checks" in request["structured_schema"]["properties"] else "drama"
    return request["stage"]


def setup_run(tmp_path, monkeypatch, audit_scenario, modes=None):
    inputs, profile, goal, opening, bundle, ids, native = audit_scenario
    monkeypatch.setattr(helper, "runner", runner)
    monkeypatch.setattr(helper, "adapter", adapter)
    monkeypatch.setattr(adapter, "DEFAULT_STAGE_LIMITS", adapter.LIMIT_CEILINGS, raising=False)
    runtime, root, sends = helper.temporary_run(tmp_path, monkeypatch,
        (inputs, profile, goal, bundle, ids, native))
    runner.write(root / "INHERITED_NATIVE_GOAL.json", goal, True)
    runner.write(root / "INHERITED_DIAGNOSTICS.json", {"native540": "known complete synthetic goal failure"}, True)
    modes, counts = modes or {}, {}
    def builder(request):
        phase = phase_for(request)
        counts[phase] = counts.get(phase, 0) + 1
        mode = modes.get((phase, counts[phase]), "valid")
        class Fake:
            def call(self, role, messages, *, max_tokens, temperature, thinking, structured_schema, evidence):
                sends.append(deepcopy(request))
                # Claim and ordinal exist before the provider, even for setup.
                assert runner.read(runtime.ledger)["calls"][-1]["ordinal"] == evidence.identity["ordinal"]
                with sqlite3.connect(root / "TASKS.sqlite3") as db:
                    assert db.execute("SELECT COUNT(*) FROM attempts WHERE status='claimed'").fetchone()[0] == 1
                body = json.loads(messages[1]["content"])
                bounded.save_request_body(evidence, json.dumps(runner.clients.expected_wire_request(request)).encode(), role=role)
                if mode == "transport_unknown":
                    raise evidenced.EvidenceCallError("TRANSPORT_EXCEPTION", started=True, outcome_known=False)
                if phase == "goal_plan":
                    value = deepcopy(goal)
                    value["whole_plan"]["premise"] = "合成完整新规划" + str(counts[phase])
                    if mode == "type_error":
                        value["whole_plan"]["premise"] = counts[phase]
                    elif mode == "unchanged":
                        value["whole_plan"]["premise"] = "合成完整新规划1"
                elif phase in ("source", "drama"):
                    value = deepcopy(bundle["native_" + phase + "_audit"])
                    value["goal_sha256"] = structured_schema["properties"]["goal_sha256"]["const"]
                    value["audit_context_sha256"] = structured_schema["properties"]["audit_context_sha256"]["const"]
                    table = "claim_checks" if phase == "source" else "goal_checks"
                    if mode in ("fail", "unknown"):
                        value[table][next(iter(value[table]))].update(status=mode,
                            required_revision="提交完整新规划修正来源和因果" if mode == "fail" else "")
                    elif mode == "incomplete":
                        value[table] = {}
                elif phase == "opening_setup":
                    value = deepcopy(opening)
                    value["goal_sha256"] = structured_schema["properties"]["goal_sha256"]["const"]
                    if mode == "unplaced":
                        value["props"]["book"].update(holder_character_id=None, location=None)
                    elif mode == "absent_with_holder":
                        value["props"]["paper"]["holder_character_id"] = "hr"
                    elif mode == "actor_mismatch":
                        value["characters"]["worker"]["location"] = "桌子右侧"
                    elif mode == "wrong_goal":
                        value["goal_sha256"] = "0" * 64
                    elif mode == "omitted_field":
                        value["props"]["paper"].pop("location")
                    elif mode == "unchanged":
                        value["props"]["book"].update(holder_character_id=None, location=None)
                elif phase == "complete_script":
                    value = deepcopy(native)
                    value["title"] = "合成完整正文" + str(counts[phase])
                    if mode == "bad_order":
                        value["beats"].reverse()
                else:
                    value = helper.full_review(body, "incomplete_review" if mode == "incomplete" else mode)
                text = "null" if mode == "null_document" else json.dumps(value, ensure_ascii=False)
                message = {"role": "assistant", "content": None, "tool_calls": [{"id": "mock", "type": "function",
                    "function": {"name": runner.clients.TOOL_NAME, "arguments": text}}]}
                if mode == "missing_tool":
                    message = {"role": "assistant", "content": text}
                raw = {"id": "synthetic-" + str(evidence.identity["ordinal"]), "model": request["model"],
                    "choices": [{"index": 0, "message": message,
                        "finish_reason": "length" if mode == "truncated" else "tool_calls"}],
                    "usage": {"prompt_tokens": 90, "completion_tokens": 10, "total_tokens": 100}}
                if mode == "usage_unknown":
                    raw.pop("usage")
                if mode == "model_mismatch":
                    raw["model"] = "wrong-model"
                saved, manifest = evidence.save_body(json.dumps(raw, ensure_ascii=False).encode(), evidenced.http_metadata(200, {}))
                return evidenced.parse_saved_response(saved, manifest, role, request["model"], thinking, structured_schema, evidence)
        return lambda: Fake()
    runtime.client_factory_builder = builder
    return runtime, root, sends


def phases(sends):
    return [phase_for(request) for request in sends]


def test_whole_native_goal_audits_setup_script_and_full_review_are_bound(tmp_path, monkeypatch, audit_scenario):
    runtime, root, sends = setup_run(tmp_path, monkeypatch, audit_scenario)
    state = runner.run()
    assert state["status"] == "text_ready_for_director"
    assert phases(sends) == ["goal_plan", "source", "drama", "opening_setup", "complete_script", "full_review"]
    assert state["cumulative_goal_candidates_used"] == 9 and state["opening_setup_calls"] == 1
    assert runtime.summary()["stage_calls"]["goal_plan"] == 2
    assert not state["creative_quality_passed"] and not state["human_quality_approved"] and not state["media_authorized"]
    handoff = runner.read(root / "TEXT_HANDOFF.json")
    assert handoff["native_opening_setup"] == runner.read(root / "setups/native_01.json")
    for request in sends[4:]:
        actual = json.loads(request["messages"][1]["content"])
        assert actual["native_opening_setup_document"] == handoff["native_opening_setup"]
        assert request["input_provenance"]["native_opening_setup_sha256"] == runner.digest(handoff["native_opening_setup"])
        assert request["input_provenance"]["native_goal_sha256"] == runner.digest(handoff["native_goal"])
    spend = runtime.summary()
    assert spend["effective_calls_started"] == 536 and spend["effective_reported_tokens"] == 10026212
    assert spend["historical_pending_ordinals"] == [70, 160] and spend["unknown_token_reservations"] == 93117
    assert not spend["old_budget_reset"]
    before = runtime.ledger.read_bytes()
    with pytest.raises(FileExistsError):
        runner.run()
    assert runtime.ledger.read_bytes() == before and len(sends) == 6


@pytest.mark.parametrize("mode", ["unplaced", "absent_with_holder", "actor_mismatch", "omitted_field"])
def test_known_complete_setup_failure_uses_whole_native_revision_only(tmp_path, monkeypatch, audit_scenario, mode):
    runtime, root, sends = setup_run(tmp_path, monkeypatch, audit_scenario, {("opening_setup", 1): mode})
    state = runner.run()
    assert state["status"] == "text_ready_for_director"
    assert phases(sends) == ["goal_plan", "source", "drama", "opening_setup", "opening_setup", "complete_script", "full_review"]
    assert state["cumulative_goal_candidates_used"] == 9 and state["opening_setup_calls"] == 2
    original = runner.read(root / "setups/native_01.json")
    revision = json.loads(sends[4]["messages"][1]["content"])
    assert revision["previous_opening_setup"] == original and revision["opening_setup_diagnostics"]
    assert revision["native_goal_document"] == runner.read(root / "goals/native_01.json")
    assert "previous_complete_document" not in revision
    actual_script = json.loads(sends[5]["messages"][1]["content"])
    assert actual_script["native_opening_setup_document"] == runner.read(root / "setups/native_02.json")
    assert "previous_opening_setup" not in actual_script and "opening_setup_diagnostics" not in actual_script
    assert not runtime.summary()["old_budget_reset"]


@pytest.mark.parametrize("phase,mode,expected_calls", [
    ("goal_plan", "truncated", 1), ("source", "unknown", 2), ("source", "incomplete", 2),
    ("drama", "incomplete", 3), ("drama", "usage_unknown", 3),
    *[("opening_setup", mode, 4) for mode in ("truncated", "usage_unknown", "transport_unknown", "missing_tool", "model_mismatch", "null_document")],
    ("complete_script", "truncated", 5), ("full_review", "incomplete", 6), ("full_review", "unknown", 6),
    ("full_review", "transport_unknown", 6),
])
def test_unknown_protocol_and_audit_contract_stop_without_repeated_dispatch(tmp_path, monkeypatch, audit_scenario, phase, mode, expected_calls):
    runtime, root, sends = setup_run(tmp_path, monkeypatch, audit_scenario, {(phase, 1): mode})
    state = runner.run()
    assert state["status"].startswith("halt_") and not state["text_ready_for_director"]
    assert len(sends) == expected_calls and phases(sends).count(phase) == 1
    assert not (root / "TEXT_HANDOFF.json").exists()
    before = runtime.ledger.read_bytes()
    with pytest.raises(FileExistsError):
        runner.run()
    assert runtime.ledger.read_bytes() == before and len(sends) == expected_calls
    assert not runtime.summary()["old_budget_reset"]


def test_setup_two_complete_failures_stop_before_author_without_candidate_reset(tmp_path, monkeypatch, audit_scenario):
    _, root, sends = setup_run(tmp_path, monkeypatch, audit_scenario,
        {("opening_setup", 1): "unplaced", ("opening_setup", 2): "unplaced"})
    state = runner.run()
    assert state["status"] == "halt_opening_setup_content_capacity_exhausted"
    assert phases(sends) == ["goal_plan", "source", "drama", "opening_setup", "opening_setup"]
    assert state["cumulative_goal_candidates_used"] == 9 and state["opening_setup_calls"] == 2
    assert not (root / "TEXT_HANDOFF.json").exists()


def test_semantic_goal_repair_does_not_spend_setup_until_both_audits_accept(tmp_path, monkeypatch, audit_scenario):
    runtime, root, sends = setup_run(tmp_path, monkeypatch, audit_scenario, {("drama", 1): "fail"})
    state = runner.run()
    assert state["status"] == "text_ready_for_director"
    assert phases(sends) == ["goal_plan", "source", "drama", "goal_plan", "source", "drama", "opening_setup", "complete_script", "full_review"]
    assert state["cumulative_goal_candidates_used"] == 10 and state["opening_setup_calls"] == 1
    assert runtime.summary()["stage_calls"]["goal_audit"] == 4
    assert not runtime.summary()["old_budget_reset"]


def test_script_whole_repair_reuses_same_goal_and_setup_and_full_review(tmp_path, monkeypatch, audit_scenario):
    _, root, sends = setup_run(tmp_path, monkeypatch, audit_scenario, {("full_review", 1): "fail"})
    state = runner.run()
    assert state["status"] == "text_ready_for_director"
    assert phases(sends) == ["goal_plan", "source", "drama", "opening_setup", "complete_script", "full_review", "complete_script", "full_review"]
    first, second = sends[4], sends[6]
    assert first["input_provenance"]["native_opening_setup_sha256"] == second["input_provenance"]["native_opening_setup_sha256"]
    assert first["input_provenance"]["goal_audit_sha256"] == second["input_provenance"]["goal_audit_sha256"]
    assert json.loads(second["messages"][1]["content"])["previous_complete_document"] == runner.read(root / "scripts/version_01/NATIVE_SCRIPT.json")


def test_separate_four_writer_stage_and_four_audit_ceiling_is_explicit(tmp_path, audit_scenario):
    profile = audit_scenario[1]
    runtime = adapter.GoalContextRuntime(tmp_path, tmp_path / "run", [], {}, profile=profile,
        stage_limits={"goal_plan": 4, "goal_audit": 4, "complete_script": 3, "full_review": 3})
    assert runtime.stage_limits["goal_plan"] == 4
    assert runtime._policy()["substage_capacity_owned_by_frozen_coordinator"]
    with pytest.raises(ValueError):
        adapter.GoalContextRuntime(tmp_path, tmp_path / "bad", [], {}, profile=profile,
            stage_limits={"goal_plan": 5, "goal_audit": 4, "complete_script": 3, "full_review": 3})


def test_setup_wrong_goal_identity_stops_before_repair_dispatch(tmp_path, monkeypatch, audit_scenario):
    runtime, root, sends = setup_run(tmp_path, monkeypatch, audit_scenario,
        {("opening_setup", 1): "wrong_goal"})
    with pytest.raises(ValueError, match="unchanged native goal"):
        runner.main(["run"])
    assert phases(sends) == ["goal_plan", "source", "drama", "opening_setup"]
    assert len(runner.read(runtime.ledger)["calls"]) == 4
    assert runner.read(root / "setups/native_01.json")["goal_sha256"] == "0" * 64
    assert not (root / "requests/opening_setup_02.json").exists()
    assert not (root / "TEXT_HANDOFF.json").exists()
    error = runner.read(root / "EXECUTION_ERROR.json")
    assert error["new_request_dispatched_by_recovery"] is False
    assert not runtime.summary()["old_budget_reset"]
    before = runtime.ledger.read_bytes()
    with pytest.raises(FileExistsError):
        runner.run()
    assert before == runtime.ledger.read_bytes() and len(sends) == 4


def first_preview(root):
    inputs = runner.read(root / "INPUTS.json")
    return runner.workflow.prepare_goal_request({**deepcopy(inputs),
        "previous_complete_document": runner.read(root / "INHERITED_NATIVE_GOAL.json"),
        "revision_diagnostics": runner.read(root / "INHERITED_DIAGNOSTICS.json")},
        runner.read(runner.PROFILE))


def test_frozen_exact_preview_equal_allows_only_matching_first_request(tmp_path, monkeypatch, audit_scenario):
    runtime, root, sends = setup_run(tmp_path, monkeypatch, audit_scenario, {("goal_plan", 1): "truncated"})
    expected = first_preview(root)
    runner.write(root / "FIRST_GOAL_REQUEST_PREVIEW.json", expected, True)
    state = runner.run()
    assert phases(sends) == ["goal_plan"] and state["status"] == "halt_goal_interface_or_unknown"
    assert sends[0] == expected["request"] and len(runner.read(runtime.ledger)["calls"]) == 1


def test_frozen_exact_preview_tamper_refused_before_first_claim_or_send(tmp_path, monkeypatch, audit_scenario):
    runtime, root, sends = setup_run(tmp_path, monkeypatch, audit_scenario)
    altered = first_preview(root)
    altered["request"]["model"] = "unexpected-model"
    runner.write(root / "FIRST_GOAL_REQUEST_PREVIEW.json", altered, True)
    before = runtime.ledger.read_bytes()
    with pytest.raises(ValueError, match="frozen exact preview"):
        runner.main(["run"])
    assert sends == [] and runner.read(runtime.ledger)["calls"] == []
    assert runtime.ledger.read_bytes() == before and not (root / "TASKS.sqlite3").exists()
    assert not (root / "requests/goal_plan_09.json").exists()
    assert runner.read(root / "EXECUTION_ERROR.json")["new_request_dispatched_by_recovery"] is False
