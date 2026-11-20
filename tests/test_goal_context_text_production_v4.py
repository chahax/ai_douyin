"""Synthetic offline coordinator v3 integration, using real claims/evidence.

These fixtures exercise control flow; their passing judgements do not establish
production authorship, legal accuracy, artistic quality, or user approval.
The filename retains the original v2 audit task; the imports select the corrected
independent v3. Frozen v2 failures remain in the first-round XML evidence.
"""
from collections import Counter
from copy import deepcopy
import json
import socket
import sqlite3
from pathlib import Path

import pytest

from scripts import run_goal_context_text_production_v4 as runner
from scripts import creative_goal_context_dispatch_v3 as adapter
from scripts import creative_bounded_format_role_clients_v1 as bounded
from scripts import creative_evidenced_role_clients_v1 as evidenced
from src.content_factory import creative_full_review_contract_v3 as reviews
from tests.test_creative_goal_context_workflow_v3 import scenario
from tests.test_creative_fresh_legal_text_pipeline_v1 import review_for


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("coordinator fixtures may not connect to a provider")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def full_review(payload, mode="valid"):
    script, brief, plan = (payload[key] for key in ("full_current_script", "brief", "creative_scene_plan"))
    native = deepcopy(review_for(script, brief, plan, payload["verified_legal_context"]))
    for table, key in reviews._COVERAGE_KEYS.items():
        native[table] = {row[key]: {k: v for k, v in row.items() if k != key}
                         for row in native[table]}
    for ref, row in native["dialogue_checks"].items():
        row.update(source_refs=[ref], turn_function="request", purpose="合成测试话轮",
                   stimulus_ref=None, reaction_refs=[], emotional_change=None)
    native["action_checks"] = {"E0003": {"status": "pass", "source_refs": ["E0003"],
        "reason": "合成状态判断", "required_revision": "", "subjects": ["worker", "book"],
        "preconditions": [], "state_changes": []}}
    for table in ("initial_checks", "observed_prop_initial"):
        for key, row in native[table].items():
            if key in ("character:worker", "prop:book", "book"):
                row["source_refs"] = ["E0003"]
    native["goal_checks"] = {key: {"status": "pass", "source_refs": ["E0002"],
        "reason": "合成局部结果判断，不是审美金标", "required_revision": "",
        "evidence": [{"source_ref": "E0002", "quote": "这份申请我今天不收。"}]}
        for key in reviews.GOAL_FIELDS}
    native.update(schema=reviews.VERSION,
                  goal_contract_sha256=runner.digest(payload["native_goal_document"]))
    if mode in ("fail", "unknown"):
        first = native["goal_checks"][next(iter(reviews.GOAL_FIELDS))]
        first.update(status=mode, required_revision="完整新稿回应本场尝试" if mode == "fail" else "")
    elif mode == "incomplete_review":
        native["dialogue_checks"] = {}
    return native


def temporary_run(tmp_path, monkeypatch, scenario, modes=None):
    """Keep all runtime files, SQLite, wire captures and claims in pytest tmp."""
    inputs, profile, goal, audit, _, native = deepcopy(scenario)
    project, root = tmp_path / "synthetic_project", tmp_path / "synthetic_project/run"
    project.mkdir()
    source = project / "source.txt"
    source.write_text("明确合成离线来源，不是生产材料", encoding="utf-8")
    profile_path = project / "profile.json"
    profile_path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(runner, "PROJECT", project)
    monkeypatch.setattr(runner, "ROOT", root)
    monkeypatch.setattr(runner, "PROFILE", profile_path)
    modes = modes or {}
    sends, counts = [], Counter()

    def factory_builder(wire):
        expected = deepcopy(wire)

        class FakeClient:
            def call(self, role, messages, *, max_tokens, temperature, thinking, structured_schema, evidence):
                stage = expected["stage"]
                counts[stage] += 1
                mode = modes.get((stage, counts[stage]), "valid")
                sends.append(deepcopy(expected))
                # Assert claim/evidence was durable before the fake service call.
                ledger = runner.read(root / "CALL_LEDGER.json")
                assert ledger["calls"][-1]["ordinal"] == evidence.identity["ordinal"]
                with sqlite3.connect(root / "TASKS.sqlite3") as db:
                    assert db.execute("SELECT COUNT(*) FROM attempts WHERE status='claimed'").fetchone()[0] == 1
                outbound = json.dumps(runner.clients.expected_wire_request(expected), ensure_ascii=False).encode()
                bounded.save_request_body(evidence, outbound, role=role)
                if mode == "transport_unknown":
                    raise evidenced.EvidenceCallError("TRANSPORT_EXCEPTION", started=True, outcome_known=False)
                payload = json.loads(messages[1]["content"])
                if stage == "goal_plan":
                    value = deepcopy(goal)
                    value["whole_plan"]["premise"] = f"合成整片版本{counts[stage]}，不是生产故事"
                    if mode == "unchanged_goal":
                        value["whole_plan"]["premise"] = "合成整片版本1，不是生产故事"
                    if mode == "type_error":
                        value["whole_plan"]["premise"] = 17 + counts[stage]
                elif stage == "goal_audit":
                    value = deepcopy(audit)
                    value["goal_sha256"] = runner.digest(payload["native_goal_document"])
                    value["audit_context_sha256"] = structured_schema["properties"]["audit_context_sha256"]["const"]
                    if mode in ("fail", "unknown"):
                        value["goal_checks"]["concrete_conflict"].update(status=mode,
                            required_revision="提交完整新目标强化关系阻力" if mode == "fail" else "")
                    elif mode == "incomplete_review":
                        value["claim_checks"] = {}
                elif stage == "complete_script":
                    value = deepcopy(native)
                    value["title"] = f"合成完整版本{counts[stage]}"
                    if mode == "bad_order":
                        value["beats"].reverse()
                else:
                    value = full_review(payload, mode)
                text = json.dumps(value, ensure_ascii=False)
                if mode == "null_document":
                    text = "null"
                message = {"role": "assistant", "content": None, "tool_calls": [{
                    "id": "synthetic-tool", "type": "function", "function": {
                        "name": runner.clients.TOOL_NAME, "arguments": text}}]}
                if mode == "missing_tool":
                    message = {"role": "assistant", "content": text}
                body = {"id": "synthetic-" + str(evidence.identity["ordinal"]), "model": expected["model"],
                    "choices": [{"index": 0, "message": message,
                        "finish_reason": "length" if mode == "truncated" else "tool_calls"}],
                    "usage": {"prompt_tokens": 90, "completion_tokens": 10, "total_tokens": 100}}
                if mode == "usage_unknown":
                    body.pop("usage")
                if mode == "model_mismatch":
                    body["model"] = "other-model"
                raw = json.dumps(body, ensure_ascii=False).encode()
                protected, manifest = evidence.save_body(raw,
                    evidenced.http_metadata(200, {"x-request-id": "synthetic-offline"}))
                return evidenced.parse_saved_response(protected, manifest, role,
                    expected["model"], thinking, structured_schema, evidence)

        return lambda: FakeClient()

    inherited = {"calls_started": 530, "reported_tokens": 10025612, "calls_with_known_usage": 528,
        "pending_ordinals": [70, 160], "unknown_token_reservations": 93117}
    runtime = adapter.GoalContextRuntime(project, root, [source], inherited, profile=profile,
        client_factory_builder=factory_builder, quota_state=None)
    runtime.prepare()
    runner.write(root / "USER_SCOPE.json", {"grant_id": runner.GRANT,
        "stage_limits": dict(adapter.DEFAULT_STAGE_LIMITS), "content_revision_limit": 2,
        "old_director_candidates_used": 7, "old_director_candidates_limit": 7,
        "additional_director_candidates": 0, "automatic_transport_retry": False,
        "media_authorized": False, "publish_authorized": False}, True)
    runner.write(root / "INPUTS.json", inputs, True)
    monkeypatch.setattr(runner, "get_runtime", lambda: runtime)
    return runtime, root, sends


def stages(sends):
    return [request["stage"] for request in sends]


def test_complete_mock_flow_is_machine_text_only_with_full_inherited_consumption(tmp_path, monkeypatch, scenario):
    runtime, root, sends = temporary_run(tmp_path, monkeypatch, scenario)
    state = runner.run()
    assert stages(sends) == ["goal_plan", "goal_audit", "complete_script", "full_review"]
    assert state["status"] == "text_ready_for_director" and state["text_ready_for_director"]
    assert not state["human_quality_approved"] and not state["creative_quality_passed"] and not state["media_authorized"]
    assert state["old_director_capacity"] == {"used": 7, "limit": 7, "remaining": 0}
    handoff = runner.read(root / "TEXT_HANDOFF.json")
    assert not handoff["production_dispatch_eligible"] and handoff["next_stage_requires_reconciled_director_lineage"]
    assert handoff["native_script"] == runner.read(root / "scripts/version_01/NATIVE_SCRIPT.json")
    spend = runtime.summary()
    assert spend["effective_calls_started"] == 534 and spend["effective_reported_tokens"] == 10026012
    assert spend["effective_calls_with_known_usage"] == 532 and not spend["old_budget_reset"]
    assert spend["historical_pending_ordinals"] == [70, 160]
    assert spend["unknown_token_reservations"] == spend["inherited_unknown_token_reservations"] == 93117
    assert spend["new_unknown_token_reservations"] == 0
    ledger = runner.read(runtime.ledger)
    assert ledger["starting_spend"] == runtime.inherited
    assert [row["ordinal"] for row in ledger["calls"]] == [531, 532, 533, 534]
    with sqlite3.connect(root / "TASKS.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM attempts WHERE status='completed'").fetchone()[0] == 4


@pytest.mark.parametrize("mode", ["missing_tool", "truncated", "usage_unknown", "transport_unknown", "model_mismatch", "null_document"])
def test_first_goal_protocol_unknown_or_null_stops_without_second_send(tmp_path, monkeypatch, scenario, mode):
    runtime, root, sends = temporary_run(tmp_path, monkeypatch, scenario, {("goal_plan", 1): mode})
    state = runner.run()
    assert state["status"] == "halt_goal_interface_or_unknown" and not state["text_ready_for_director"]
    assert stages(sends) == ["goal_plan"] and not (root / "TEXT_HANDOFF.json").exists()
    before = runtime.ledger.read_bytes()
    with pytest.raises((RuntimeError, FileExistsError)):
        runner.run()
    assert len(sends) == 1 and runtime.ledger.read_bytes() == before
    with sqlite3.connect(root / "TASKS.sqlite3") as db:
        statuses = db.execute("SELECT status FROM attempts").fetchall()
        assert len(statuses) == 1 and statuses[0][0] in ("protocol_rejected", "result_unknown")
    if mode in ("usage_unknown", "transport_unknown"):
        assert runtime.summary()["unknown_token_reservations"] > 93117


@pytest.mark.parametrize("stage,status,expected_count", [
    ("goal_audit", "incomplete_review", 2), ("goal_audit", "unknown", 2),
    ("full_review", "incomplete_review", 4), ("full_review", "unknown", 4),
    ("complete_script", "truncated", 3), ("full_review", "transport_unknown", 4),
])
def test_audit_contract_or_uncertainty_never_becomes_ready_or_content_retry(tmp_path, monkeypatch, scenario, stage, status, expected_count):
    _, root, sends = temporary_run(tmp_path, monkeypatch, scenario, {(stage, 1): status})
    state = runner.run()
    assert state["status"].startswith("halt_") and not state["text_ready_for_director"]
    assert len(sends) == expected_count and not (root / "TEXT_HANDOFF.json").exists()
    assert Counter(stages(sends))[stage] == 1


@pytest.mark.parametrize("stage,mode,expected", [
    ("goal_plan", "type_error", ["goal_plan", "goal_plan", "goal_audit", "complete_script", "full_review"]),
    ("goal_audit", "fail", ["goal_plan", "goal_audit", "goal_plan", "goal_audit", "complete_script", "full_review"]),
    ("complete_script", "bad_order", ["goal_plan", "goal_audit", "complete_script", "complete_script", "full_review"]),
    ("full_review", "fail", ["goal_plan", "goal_audit", "complete_script", "full_review", "complete_script", "full_review"]),
])
def test_known_complete_failure_revises_whole_native_and_reuses_unchanged_goal_authority(tmp_path, monkeypatch, scenario, stage, mode, expected):
    runtime, root, sends = temporary_run(tmp_path, monkeypatch, scenario, {(stage, 1): mode})
    state = runner.run()
    assert state["status"] == "text_ready_for_director" and stages(sends) == expected
    revised_stage = "goal_plan" if stage in ("goal_plan", "goal_audit") else "complete_script"
    label = revised_stage + ("_05.json" if revised_stage == "goal_plan" else "_02.json")
    prepared = runner.read(root / "requests" / label)
    actual = json.loads(prepared["request"]["messages"][1]["content"])
    if revised_stage == "goal_plan":
        previous = runner.read(root / "goals/native_01.json")
    else:
        previous = runner.read(root / "scripts/version_01/NATIVE_SCRIPT.json")
        writer_requests = [request for request in sends if request["stage"] == "complete_script"]
        assert len(writer_requests) == 2
        assert writer_requests[0]["input_provenance"]["goal_audit_sha256"] == writer_requests[1]["input_provenance"]["goal_audit_sha256"]
        assert Counter(stages(sends))["goal_audit"] == 1
        assert runner.read(root / "scripts/version_02/NATIVE_SCRIPT.json")["title"] == "合成完整版本2"
    assert actual["previous_complete_document"] == previous and actual["revision_diagnostics"]
    ledger = runner.read(runtime.ledger)
    original = runner.read(root / ledger["calls"][0]["receipt"])
    assert original["ordinal"] == 531 and not original.get("cached_response_read_only", False)
    assert runtime.summary()["new_calls"] == len(expected)


@pytest.mark.parametrize("stage,mode,expected_stage_count,expected_calls", [
    ("goal_plan", "type_error", 3, 3), ("goal_audit", "fail", 3, 6),
    ("complete_script", "bad_order", 3, 5), ("full_review", "fail", 3, 8),
])
def test_three_complete_versions_are_bounded_and_exhaustion_keeps_original_claims(tmp_path, monkeypatch, scenario, stage, mode, expected_stage_count, expected_calls):
    runtime, root, sends = temporary_run(tmp_path, monkeypatch, scenario,
        {(stage, index): mode for index in (1, 2, 3)})
    state = runner.run()
    assert state["status"] in ("halt_goal_content_capacity_exhausted", "halt_script_content_capacity_exhausted")
    assert not state["text_ready_for_director"] and not (root / "TEXT_HANDOFF.json").exists()
    assert Counter(stages(sends))[stage] == expected_stage_count and len(sends) == expected_calls
    assert runtime.summary()["effective_calls_started"] == 530 + expected_calls
    before = runtime.ledger.read_bytes()
    with pytest.raises((RuntimeError, FileExistsError)):
        runner.run()
    assert runtime.ledger.read_bytes() == before and len(sends) == expected_calls


def test_successful_run_cannot_repeat_or_mutate_original_claims_and_wire_evidence(tmp_path, monkeypatch, scenario):
    runtime, root, sends = temporary_run(tmp_path, monkeypatch, scenario)
    runner.run()
    frozen = {path: path.read_bytes() for path in root.rglob("*") if path.is_file() and path.suffix != ".sqlite3"}
    with pytest.raises((RuntimeError, FileExistsError)):
        runner.run()
    assert len(sends) == 4
    assert all(path.read_bytes() == raw for path, raw in frozen.items())
    for row in runner.read(runtime.ledger)["calls"]:
        receipt = runner.read(root / row["receipt"])
        assert runner.sha_file(root / row["receipt"]) == row["receipt_sha256"]
        wire = json.loads((runtime.evidence_path(row["ordinal"]) / "request_body.raw").read_text(encoding="utf-8"))
        assert wire == runner.clients.expected_wire_request(receipt["request"])


def test_existing_root_or_global_grant_cannot_be_regranted(tmp_path, monkeypatch):
    root, claim = tmp_path / "existing_run", tmp_path / "claim.json"
    monkeypatch.setattr(runner, "ROOT", root)
    monkeypatch.setattr(runner, "CLAIM", claim)
    monkeypatch.setattr(runner, "prior_guard", lambda: pytest.fail("existing grant must stop before old lineage reads"))
    root.mkdir()
    claim.write_text("original global claim", encoding="utf-8")
    with pytest.raises(RuntimeError, match="never regrant"):
        runner.prepare()
    assert claim.read_text(encoding="utf-8") == "original global claim" and list(root.iterdir()) == []


@pytest.mark.parametrize("mode", ["valid", "transport_unknown"])
def test_identical_request_is_reused_before_new_sql_claim_even_under_another_label(tmp_path, monkeypatch, scenario, mode):
    runtime, root, sends = temporary_run(tmp_path, monkeypatch, scenario, {("goal_plan", 1): mode})
    inputs = runner.read(root / "INPUTS.json")
    prepared = runner.workflow.prepare_goal_request(inputs, runner.read(runner.PROFILE))
    ids = runner.workflow.origin_ids(inputs)
    validate = lambda value: runner.goals.validate_goal_document(value, **ids)
    first = runner.invoke(runtime, "goal_plan_01", prepared, validate)
    before = runtime.ledger.read_bytes()
    original_path = root / runner.read(runtime.ledger)["calls"][0]["receipt"]
    original = original_path.read_bytes()
    reused = runner.invoke(runtime, "goal_plan_same_request_other_label", prepared, validate)
    assert reused["ordinal"] == first["ordinal"] and reused["provider_called"] is False
    assert reused["cached_response_read_only"] is True and len(sends) == 1
    assert runtime.ledger.read_bytes() == before and original_path.read_bytes() == original
    with sqlite3.connect(root / "TASKS.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 1
    if mode == "transport_unknown":
        assert reused["status"] == "outcome_unknown" and not runner.repairable(reused)


def test_identical_native_goal_after_semantic_failure_stops_cached_audit_without_new_claim(tmp_path, monkeypatch, scenario):
    runtime, root, sends = temporary_run(tmp_path, monkeypatch, scenario,
        {("goal_audit", 1): "fail", ("goal_plan", 2): "unchanged_goal"})
    state = runner.run()
    assert state["status"] == "halt_cached_goal_audit_no_new_claim" and not state["text_ready_for_director"]
    assert stages(sends) == ["goal_plan", "goal_audit", "goal_plan"]
    assert runner.read(root / "goals/native_01.json") == runner.read(root / "goals/native_02.json")
    assert not (root / "TEXT_HANDOFF.json").exists()
    assert runtime.summary()["new_calls"] == 3 and runtime.summary()["stage_calls"]["goal_audit"] == 1
    with sqlite3.connect(root / "TASKS.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 3


def test_authorized_preparation_carries_all_parent_consumption_with_zero_dispatch(tmp_path, monkeypatch):
    actual_parent = runner.PREFLIGHT_PARENT
    before = (actual_parent / "CALL_LEDGER.json").read_bytes()
    approval = runner.read(runner.APPROVAL)
    root, claim = tmp_path / "newrun", tmp_path / "claim/CLAIM.json"
    approval_path = tmp_path / "approval.json"
    runner.write(approval_path, approval, True)
    monkeypatch.setattr(runner, "ROOT", root)
    monkeypatch.setattr(runner, "CLAIM", claim)
    monkeypatch.setattr(runner, "APPROVAL", approval_path)
    result = runner.prepare()
    assert result["new_calls"] == 0 and result["effective_calls_started"] == 533
    assert result["effective_reported_tokens"] == 10099695
    assert result["effective_calls_with_known_usage"] == 531
    assert result["historical_pending_ordinals"] == [70, 160]
    assert result["unknown_token_reservations"] == 93117
    assert not (root / "RUN_CLAIM.json").exists()
    assert (actual_parent / "CALL_LEDGER.json").read_bytes() == before
    scope = runner.read(root / "USER_SCOPE.json")
    assert scope["inherited_goal_candidates_used"] == 3
    assert scope["cumulative_goal_candidates_this_run_maximum"] == 6
    assert not scope["old_goal_allowance_reset"] and not scope["media_authorized"]


@pytest.mark.parametrize("change", ["missing_approval", "parent_digest_changed"])
def test_preparation_refuses_unbound_continuation_before_claim_or_provider(tmp_path, monkeypatch, change):
    approval = runner.read(runner.APPROVAL)
    if change == "missing_approval":
        approval["human_authorized"] = False
    else:
        approval["parent_ledger_sha256"] = "0" * 64
    path = tmp_path / "approval.json"
    runner.write(path, approval, True)
    root, claim = tmp_path / "newrun", tmp_path / "CLAIM.json"
    monkeypatch.setattr(runner, "ROOT", root)
    monkeypatch.setattr(runner, "CLAIM", claim)
    monkeypatch.setattr(runner, "APPROVAL", path)
    with pytest.raises(ValueError, match="explicit continuing"):
        runner.prepare()
    assert not root.exists() and not claim.exists()
