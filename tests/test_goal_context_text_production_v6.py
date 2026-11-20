"""Offline production coordinator with two native audit phases."""
from copy import deepcopy
import json
import pytest
from scripts import run_goal_context_text_production_v6 as runner
from scripts import creative_goal_context_dispatch_v4 as adapter
from scripts import creative_bounded_format_role_clients_v1 as bounded
from scripts import creative_evidenced_role_clients_v1 as evidenced
from tests import test_goal_context_text_production_v4 as helper
from tests.test_creative_goal_context_workflow_v5 import scenario, prior_scenario, payload


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    import socket
    def deny(*args, **kwargs):
        raise AssertionError("no real provider in fixture")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def setup_run(tmp_path, monkeypatch, scenario, modes=None):
    inputs, profile, goal, ids, native, _, _, bundle = scenario
    monkeypatch.setattr(helper, "runner", runner)
    monkeypatch.setattr(helper, "adapter", adapter)
    runtime, root, sends = helper.temporary_run(tmp_path, monkeypatch,
        (inputs, profile, goal, bundle, ids, native))
    runner.write(root / "INHERITED_NATIVE_GOAL.json", goal, True)
    runner.write(root / "INHERITED_DIAGNOSTICS.json", {"complete_goal_diagnosis": "synthetic full diagnosis"}, True)
    modes, counts = modes or {}, {}
    def builder(request):
        phase = ("source" if "claim_checks" in request["structured_schema"].get("properties", {}) else "drama") if request["stage"] == "goal_audit" else request["stage"]
        counts[phase] = counts.get(phase, 0) + 1
        mode = modes.get((phase, counts[phase]), "valid")
        class Fake:
            def call(self, role, messages, *, max_tokens, temperature, thinking, structured_schema, evidence):
                sends.append(deepcopy(request))
                body = json.loads(messages[1]["content"])
                bounded.save_request_body(evidence, json.dumps(runner.clients.expected_wire_request(request)).encode(), role=role)
                if mode == "transport_unknown":
                    raise evidenced.EvidenceCallError("TRANSPORT_EXCEPTION", started=True, outcome_known=False)
                if phase == "goal_plan":
                    value = deepcopy(goal)
                    value["whole_plan"]["premise"] = "合成新规划" + str(counts[phase])
                    if mode == "type_error":
                        value["whole_plan"]["premise"] = counts[phase]
                elif phase in ("source", "drama"):
                    value = deepcopy(bundle["native_" + phase + "_audit"])
                    value["goal_sha256"] = structured_schema["properties"]["goal_sha256"]["const"]
                    value["audit_context_sha256"] = structured_schema["properties"]["audit_context_sha256"]["const"]
                    table = "claim_checks" if phase == "source" else "goal_checks"
                    if mode in ("fail", "unknown"):
                        value[table][next(iter(value[table]))].update(status=mode, required_revision="整份规划必须改" if mode == "fail" else "")
                    elif mode == "incomplete":
                        value[table] = {}
                elif phase == "complete_script":
                    value = deepcopy(native)
                    value["title"] = "合成正文" + str(counts[phase])
                else:
                    value = helper.full_review(body, mode)
                message = {"role": "assistant", "content": None, "tool_calls": [{"id": "mock", "type": "function", "function": {"name": runner.clients.TOOL_NAME, "arguments": json.dumps(value, ensure_ascii=False)}}]}
                raw = {"id": "synthetic-" + str(evidence.identity["ordinal"]), "model": request["model"], "choices": [{"index": 0, "message": message, "finish_reason": "length" if mode == "truncated" else "tool_calls"}], "usage": {"prompt_tokens": 90, "completion_tokens": 10, "total_tokens": 100}}
                if mode == "usage_unknown":
                    raw.pop("usage")
                saved, manifest = evidence.save_body(json.dumps(raw, ensure_ascii=False).encode(), evidenced.http_metadata(200, {}))
                return evidenced.parse_saved_response(saved, manifest, role, request["model"], thinking, structured_schema, evidence)
        return lambda: Fake()
    runtime.client_factory_builder = builder
    return runtime, root, sends


def test_native_replanning_then_two_reviews_and_whole_script(tmp_path, monkeypatch, scenario):
    runtime, root, sends = setup_run(tmp_path, monkeypatch, scenario)
    state = runner.run()
    assert helper.stages(sends) == ["goal_plan", "goal_audit", "goal_audit", "complete_script", "full_review"]
    assert state["status"] == "text_ready_for_director" and state["cumulative_goal_candidates_used"] == 7
    assert not state["human_quality_approved"] and not state["creative_quality_passed"]
    original = json.loads(sends[0]["messages"][1]["content"])
    assert original["previous_complete_document"] == scenario[2] and original["revision_diagnostics"]
    assert not json.loads(sends[3]["messages"][1]["content"]).get("previous_complete_document")
    handoff = runner.read(root / "TEXT_HANDOFF.json")
    assert set(handoff["native_goal_audit"]) == {"schema", "native_source_audit", "native_drama_audit"}
    before = runtime.ledger.read_bytes()
    with pytest.raises(FileExistsError):
        runner.run()
    assert runtime.ledger.read_bytes() == before and len(sends) == 5


@pytest.mark.parametrize("phase,mode,calls", [("goal_plan", "truncated", 1), ("source", "incomplete", 2), ("drama", "incomplete", 3), ("source", "unknown", 2), ("drama", "usage_unknown", 3), ("drama", "transport_unknown", 3)])
def test_contract_or_unknown_stops_at_phase_without_new_script(tmp_path, monkeypatch, scenario, phase, mode, calls):
    _, root, sends = setup_run(tmp_path, monkeypatch, scenario, {(phase, 1): mode})
    state = runner.run()
    assert state["status"].startswith("halt_") and not state["text_ready_for_director"]
    assert len(sends) == calls and not (root / "TEXT_HANDOFF.json").exists()


def test_whole_revision_after_source_failure_preserves_failed_native(tmp_path, monkeypatch, scenario):
    _, root, sends = setup_run(tmp_path, monkeypatch, scenario, {("source", 1): "fail"})
    assert runner.run()["status"] == "text_ready_for_director"
    assert helper.stages(sends) == ["goal_plan", "goal_audit", "goal_plan", "goal_audit", "goal_audit", "complete_script", "full_review"]
    revised = json.loads(sends[2]["messages"][1]["content"])
    assert revised["previous_complete_document"] == runner.read(root / "goals/native_01.json")
    assert revised["revision_diagnostics"]["complete_same_source_goal_audits"][0]["findings"]


def test_independent_dispatch_ceiling_allows_four_bound_audits_only(tmp_path, scenario):
    profile = scenario[1]
    runtime = adapter.GoalContextRuntime(tmp_path, tmp_path / "run", [], {}, profile=profile,
        stage_limits={"goal_plan": 2, "goal_audit": 4, "complete_script": 3, "full_review": 3})
    assert runtime.stage_limits["goal_audit"] == 4 and runtime._policy()["separate_source_and_drama_audits"]
    with pytest.raises(ValueError):
        adapter.GoalContextRuntime(tmp_path, tmp_path / "bad", [], {}, profile=profile,
            stage_limits={"goal_plan": 2, "goal_audit": 5, "complete_script": 3, "full_review": 3})


def test_drama_failure_revised_goal_is_audited_twice_without_capacity_reset(tmp_path, monkeypatch, scenario):
    runtime, root, sends = setup_run(tmp_path, monkeypatch, scenario, {("drama", 1): "fail"})
    assert runner.run()["status"] == "text_ready_for_director"
    assert helper.stages(sends).count("goal_plan") == 2 and helper.stages(sends).count("goal_audit") == 4
    assert runtime.summary()["stage_calls"]["goal_audit"] == 4
    assert not runtime.summary()["old_budget_reset"]
