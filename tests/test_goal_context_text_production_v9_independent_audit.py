"""Independent durable fake-service split coordinator, zero production calls."""
from copy import deepcopy
import json
import socket
import sqlite3

import pytest

from scripts import run_goal_context_text_production_v9 as runner
from scripts import creative_goal_context_dispatch_v6 as adapter
from scripts import creative_bounded_format_role_clients_v1 as bounded
from scripts import creative_evidenced_role_clients_v1 as evidenced
from tests import test_goal_context_text_production_v4 as helpers
from tests.test_creative_goal_context_workflow_v7_independent_audit import causal_scenario, prior_scenario

INHERITED = {"calls_started": 552, "reported_tokens": 10626112, "calls_with_known_usage": 550,
    "pending_ordinals": [70, 160], "unknown_token_reservations": 93117}


@pytest.fixture(autouse=True)
def no_network_or_old_guard(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("independent split coordinator may not contact a provider or old runtime")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(runner.previous, "get_runtime", deny)


def phase(request):
    provenance = request["input_provenance"]
    if provenance.get("substage") == "opening_setup":
        return "opening_setup"
    if request["stage"] == "goal_audit":
        return "source" if "claim_checks" in request["structured_schema"]["properties"] else "drama"
    return provenance.get("review_part", request["stage"])


def replay(tmp_path, monkeypatch, causal_scenario, modes=None):
    inputs, profile, goal, opening, bundle, ids, native = deepcopy(causal_scenario)
    project, root = tmp_path / "synthetic_project", tmp_path / "synthetic_project/run"
    project.mkdir()
    source = project / "source.txt"
    source.write_text("仅独立离线来源", encoding="utf-8")
    profile_path = project / "profile.json"
    profile_path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(runner, "PROJECT", project)
    monkeypatch.setattr(runner, "ROOT", root)
    monkeypatch.setattr(runner, "PROFILE", profile_path)
    sends, counts = [], {}
    modes = modes or {}

    def factory(request):
        current = phase(request)
        counts[current] = counts.get(current, 0) + 1
        mode = modes.get((current, counts[current]), "valid")

        class Fake:
            def call(self, role, messages, *, max_tokens, temperature, thinking, structured_schema, evidence):
                sends.append(deepcopy(request))
                assert runner.read(runtime.ledger)["calls"][-1]["ordinal"] == evidence.identity["ordinal"]
                with sqlite3.connect(root / "TASKS.sqlite3") as db:
                    assert db.execute("SELECT COUNT(*) FROM attempts WHERE status='claimed'").fetchone()[0] == 1
                bounded.save_request_body(evidence, json.dumps(runner.clients.expected_wire_request(request), ensure_ascii=False).encode(), role=role)
                if mode == "transport_unknown":
                    raise evidenced.EvidenceCallError("TRANSPORT_EXCEPTION", started=True, outcome_known=False)
                body = json.loads(messages[1]["content"])
                if current == "goal_plan":
                    value = deepcopy(goal)
                    value["whole_plan"]["premise"] = "合成新原生整片规划" + str(counts[current])
                elif current in ("source", "drama"):
                    value = deepcopy(bundle["native_" + current + "_audit"])
                    for field in ("goal_sha256", "audit_context_sha256"):
                        value[field] = structured_schema["properties"][field]["const"]
                elif current == "opening_setup":
                    value = deepcopy(opening)
                    value["goal_sha256"] = body["native_goal_sha256"]
                elif current == "complete_script":
                    value = deepcopy(native)
                    value["title"] = "合成完整正文" + str(counts[current])
                else:
                    assert current in ("semantic", "physical")
                    views = runner.workflow.compile_native_views(body["native_goal_document"], body["native_opening_setup_document"], **ids)
                    compiled = runner.legacy.contract.compile_script(body["native_script_document"], views["brief"])
                    legal = runner.workflow.prepare_full_review_part_request(inputs, profile, body["native_script_document"], views, current)["review_legal_context"]
                    # Private synthetic response construction only. Compiler
                    # duplicates are not inserted into the actual wire body.
                    local_payload = {"full_current_script": compiled, "brief": views["brief"],
                        "creative_scene_plan": views["plan"], "native_goal_document": views["goal"],
                        "verified_legal_context": legal}
                    synthetic_full = helpers.full_review(local_payload)
                    synthetic_full.update(opening_setup_sha256=runner.digest(views["opening_setup"]))
                    value = {key: deepcopy(synthetic_full[key]) for key in structured_schema["properties"] if key in synthetic_full}
                    for key in ("schema", "part", "context_sha256"):
                        value[key] = structured_schema["properties"][key]["const"]
                    if "revision_target" in structured_schema["properties"]:
                        value["revision_target"] = "none"
                    if mode in ("fail", "unknown", "plan_fail"):
                        table = "goal_checks" if current == "semantic" else "action_checks"
                        next(iter(value[table].values())).update(status="fail" if mode == "plan_fail" else mode,
                            required_revision="提交完整新原生规划。" if mode == "plan_fail" else "完整新稿修复功能缺口。" if mode == "fail" else "")
                        if "revision_target" in value and mode != "unknown":
                            value["revision_target"] = "plan" if mode == "plan_fail" else "script"
                    elif mode == "extra_zero_table":
                        value["plan_support"] = {}
                    elif mode == "mixed_script":
                        value["script_sha256"] = "c" * 64
                message = {"role": "assistant", "content": None, "tool_calls": [{"id": "offline",
                    "type": "function", "function": {"name": runner.clients.TOOL_NAME, "arguments": json.dumps(value, ensure_ascii=False)}}]}
                response = {"id": "offline-" + str(evidence.identity["ordinal"]), "model": request["model"],
                    "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls"}],
                    "usage": {"prompt_tokens": 90, "completion_tokens": 10, "total_tokens": 100}}
                saved, manifest = evidence.save_body(json.dumps(response, ensure_ascii=False).encode(), evidenced.http_metadata(200, {}))
                return evidenced.parse_saved_response(saved, manifest, role, request["model"], thinking, structured_schema, evidence)
        return lambda: Fake()

    runtime = adapter.GoalContextRuntime(project, root, [source], deepcopy(INHERITED), profile=profile,
        stage_limits={"goal_plan": 4, "goal_audit": 4, "complete_script": 3, "full_review": 6},
        client_factory_builder=factory, quota_state=None)
    runtime.prepare()
    runner.write(root / "INPUTS.json", inputs, True)
    runner.write(root / "USER_SCOPE.json", {"stage_limits": runtime.stage_limits}, True)
    runner.write(root / "INHERITED_NATIVE_GOAL.json", goal, True)
    runner.write(root / "INHERITED_DIAGNOSTICS.json", {"independent_failure_quotes": "合成失败机制，不含旧整篇剧情"}, True)
    monkeypatch.setattr(runner, "get_runtime", lambda: runtime)
    return runtime, root, sends


def phases(sends):
    return [phase(request) for request in sends]


def test_both_native_parts_handoff_history_and_reentry_are_exact(tmp_path, monkeypatch, causal_scenario):
    runtime, root, sends = replay(tmp_path, monkeypatch, causal_scenario)
    result = runner.run()
    assert result["status"] == "text_ready_for_director", result
    assert phases(sends) == ["goal_plan", "source", "drama", "opening_setup", "complete_script", "semantic", "physical"]
    handoff = runner.read(root / "TEXT_HANDOFF.json")
    bundle = handoff["native_full_review_bundle"]
    for part in ("semantic", "physical"):
        assert bundle["native_" + part + "_review"] == runner.read(root / "scripts/version_01" / ("NATIVE_" + part.upper() + "_REVIEW.json"))
    assert handoff["decision"]["native_single_full_review"] is False
    assert not handoff["media_authorized"] and not handoff["production_dispatch_eligible"]
    spend = runtime.summary()
    assert spend["effective_calls_started"] == 559 and spend["effective_reported_tokens"] == 10626812
    assert spend["effective_calls_with_known_usage"] == 557 and spend["historical_pending_ordinals"] == [70, 160]
    assert spend["unknown_token_reservations"] == 93117 and not spend["old_budget_reset"]
    assert result["cumulative_goal_candidates_used"] == 11 and result["inherited_goal_candidates_used"] == 10
    assert runner.read(runtime.ledger)["starting_spend"] == INHERITED
    first_body = json.loads(sends[0]["messages"][1]["content"])
    assert "previous_complete_document" not in first_body
    before = runtime.ledger.read_bytes()
    with pytest.raises(FileExistsError):
        runner.run()
    assert runtime.ledger.read_bytes() == before and len(sends) == 7


@pytest.mark.parametrize("part,mode", [("semantic", "unknown"), ("semantic", "transport_unknown"),
    ("physical", "unknown"), ("physical", "transport_unknown")])
def test_first_unknown_halts_later_part_and_second_unknown_never_retries_or_handoffs(tmp_path, monkeypatch, causal_scenario, part, mode):
    runtime, root, sends = replay(tmp_path, monkeypatch, causal_scenario, {(part, 1): mode})
    result = runner.run()
    assert result["status"] in ("halt_full_review_uncertain", "halt_review_interface_or_unknown"), result
    expected = ["goal_plan", "source", "drama", "opening_setup", "complete_script", "semantic"]
    if part == "physical":
        expected.append("physical")
    assert phases(sends) == expected
    assert not (root / "TEXT_HANDOFF.json").exists() and not (root / "scripts/version_02").exists()
    assert not (root / "scripts/version_01/NATIVE_REVIEW_BUNDLE.json").exists()
    before = runtime.ledger.read_bytes()
    with pytest.raises(FileExistsError):
        runner.run()
    assert runtime.ledger.read_bytes() == before and phases(sends) == expected
    assert not result["spend"]["old_budget_reset"]


@pytest.mark.parametrize("part,mode", [("semantic", "extra_zero_table"), ("physical", "mixed_script")])
def test_schema_or_mixed_source_failure_never_reaches_bundle_or_handoff(tmp_path, monkeypatch, causal_scenario, part, mode):
    _, root, sends = replay(tmp_path, monkeypatch, causal_scenario, {(part, 1): mode})
    result = runner.run()
    assert result["status"] == "halt_full_review_contract_requires_pipeline_diagnosis", result
    assert not (root / "TEXT_HANDOFF.json").exists() and not (root / "scripts/version_01/NATIVE_REVIEW_BUNDLE.json").exists()
    assert phases(sends).count("complete_script") == 1
    assert phases(sends).count("physical") == (part == "physical")


def test_complete_known_semantic_failure_revises_whole_native_body_before_both_new_parts(tmp_path, monkeypatch, causal_scenario):
    runtime, root, sends = replay(tmp_path, monkeypatch, causal_scenario, {("semantic", 1): "fail"})
    result = runner.run()
    assert result["status"] == "text_ready_for_director", result
    assert phases(sends) == ["goal_plan", "source", "drama", "opening_setup", "complete_script", "semantic", "complete_script", "semantic", "physical"]
    old = runner.read(root / "scripts/version_01/NATIVE_SCRIPT.json")
    second = next(request for request in sends if phase(request) == "complete_script" and json.loads(request["messages"][1]["content"]).get("previous_complete_document"))
    assert json.loads(second["messages"][1]["content"])["previous_complete_document"] == old
    assert not (root / "scripts/version_01/NATIVE_PHYSICAL_REVIEW.json").exists()
    assert not (root / "scripts/version_01/NATIVE_REVIEW_BUNDLE.json").exists()
    assert runner.read(root / "TEXT_HANDOFF.json")["native_script"] == runner.read(root / "scripts/version_02/NATIVE_SCRIPT.json")
    assert runtime.summary()["effective_calls_started"] == 561 and not runtime.summary()["old_budget_reset"]


def test_invalid_bundle_after_two_native_parts_still_cannot_save_handoff(tmp_path, monkeypatch, causal_scenario):
    actual = runner.reviews.validate_bundle
    def reject(*args, **kwargs):
        result = actual(*args, **kwargs)
        assert result["valid"] and result["accepted"]
        return {**result, "valid": False, "accepted": False, "status": "independent_synthetic_bundle_fault"}
    monkeypatch.setattr(runner.reviews, "validate_bundle", reject)
    _, root, sends = replay(tmp_path, monkeypatch, causal_scenario)
    result = runner.run()
    assert result["status"] == "halt_full_review_bundle_contract_requires_pipeline_diagnosis"
    assert not (root / "TEXT_HANDOFF.json").exists() and len(sends) == 7


@pytest.mark.parametrize("part", ["semantic", "physical"])
def test_native_plan_target_with_zero_plan_support_never_dispatches_another_body(tmp_path, monkeypatch, causal_scenario, part):
    _, root, sends = replay(tmp_path, monkeypatch, causal_scenario, {(part, 1): "plan_fail"})
    result = runner.run()
    assert result["status"] == "halt_full_review_requires_new_complete_goal", result
    assert phases(sends).count("complete_script") == 1 and not (root / "TEXT_HANDOFF.json").exists()
    assert phases(sends).count("physical") == (part == "physical")
    decision = runner.read(root / "scripts/version_01" / (part.upper() + "_DECISION.json"))
    assert decision["requires_new_goal_plan"] and any(item["target"] == "plan" for item in decision["findings"])


@pytest.mark.parametrize("status", ["halt_same_story_prior_allowance_exhausted", "halt_prior_story_relation_unknown"])
def test_typed_special_prior_halt_is_not_treated_as_a_whole_body_repair(tmp_path, monkeypatch, causal_scenario, status):
    # Coordinator boundary only; native scope validation is independently
    # exercised by the split-contract tests with real prior_story_relation.
    actual = runner.reviews.validate_part
    def prior_halt(*args, **kwargs):
        result = actual(*args, **kwargs)
        assert result["valid"] and result["accepted"]
        return {**result, "accepted": False, "status": status,
                "independent_synthetic_control_boundary": True}
    monkeypatch.setattr(runner.reviews, "validate_part", prior_halt)
    _, root, sends = replay(tmp_path, monkeypatch, causal_scenario)
    result = runner.run()
    assert result["status"] == status
    assert phases(sends) == ["goal_plan", "source", "drama", "opening_setup", "complete_script", "semantic"]
    assert not (root / "TEXT_HANDOFF.json").exists() and not (root / "scripts/version_02").exists()


def test_new_dispatch_exact_six_acceptance_seven_rejection_and_frozen_three_remain(tmp_path, causal_scenario):
    from scripts import creative_goal_context_dispatch_v5 as frozen
    inputs, profile, *_ = causal_scenario
    project = tmp_path / "constructor_only"
    project.mkdir()
    source = project / "source.txt"
    source.write_text("仅独立上限测试", encoding="utf-8")
    limits = {"goal_plan": 4, "goal_audit": 4, "complete_script": 3, "full_review": 6}
    runtime = adapter.GoalContextRuntime(project, project / "new", [source], INHERITED, profile=profile, stage_limits=limits)
    assert runtime.stage_limits == limits and adapter.LIMIT_CEILINGS["full_review"] == 6
    with pytest.raises(ValueError):
        adapter.GoalContextRuntime(project, project / "bad", [source], INHERITED, profile=profile, stage_limits={**limits, "full_review": 7})
    assert frozen.LIMIT_CEILINGS["full_review"] == 3
    with pytest.raises(ValueError):
        frozen.GoalContextRuntime(project, project / "old", [source], INHERITED, profile=profile, stage_limits=limits)
