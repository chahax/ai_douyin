"""Durable dispatch tests with fake saved envelopes, no credentials or sockets."""
from copy import deepcopy
import json
import socket

import pytest

from scripts import creative_goal_context_dispatch_v2 as adapter
from scripts import creative_bounded_format_role_clients_v1 as bounded
from scripts import creative_evidenced_role_clients_v1 as evidenced


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("dispatch adapter unit tests cannot connect to a provider")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def request(profile, stage="goal_plan", version=1):
    role = adapter.STAGE_ROLES[stage]
    parameters = deepcopy(profile[role]["parameters"])
    parameters.update(profile.get("stage_parameters", {}).get(stage, {}))
    return {"stage": stage, "role": role, "model": profile[role]["model"],
            "messages": [{"role": "system", "content": "纯离线工具合同，不是创作质量判断。"},
                         {"role": "user", "content": json.dumps({"stage": stage, "version": version})}],
            "parameters": parameters,
            "structured_schema": {"type": "object", "properties": {"value": {"type": "string"}},
                                  "required": ["value"], "additionalProperties": False},
            "input_provenance": {"fixture": "explicit_offline_only"}}


def temporary_runtime(tmp_path, *, fault=None, validator_result=None, stage_limits=None, admission=None):
    project = tmp_path / "project"
    project.mkdir()
    root = project / "run"
    source = project / "source.txt"
    source.write_text("离线来源快照，不是实际请求。", encoding="utf-8")
    profile = adapter.read(adapter.DEFAULT_PROFILE)
    inherited = {"calls_started": 530, "reported_tokens": 10025612, "calls_with_known_usage": 528,
                 "pending_ordinals": [70, 160], "unknown_token_reservations": 93117}
    sends, constructions = [], []

    def factory_builder(wire):
        expected = deepcopy(wire)
        constructions.append(deepcopy(wire))

        class FakeClient:
            def call(self, role, messages, *, max_tokens, temperature, thinking, structured_schema, evidence):
                assert adapter.read(root / "CALL_LEDGER.json")["calls"][-1]["ordinal"] == evidence.identity["ordinal"]
                pending = adapter.read(root / adapter.read(root / "CALL_LEDGER.json")["calls"][-1]["receipt"])
                assert pending["status"] == "pending_response" and pending["request"] == expected
                assert messages == expected["messages"] and structured_schema == expected["structured_schema"]
                assert max_tokens == expected["parameters"]["max_completion_tokens"]
                assert thinking == ("adaptive" if role == "writer" else "disabled")
                sends.append(deepcopy(expected))
                outgoing = json.dumps(adapter.clients.expected_wire_request(expected), ensure_ascii=False).encode("utf-8")
                bounded.save_request_body(evidence, outgoing, role=role)
                if fault == "transport_unknown":
                    raise evidenced.EvidenceCallError("TRANSPORT_EXCEPTION", started=True, outcome_known=False)
                value = {"value": expected["stage"]}
                if fault == "type_error":
                    value["value"] = 42
                text = json.dumps(value, ensure_ascii=False)
                if fault == "duplicate_json_key":
                    text = '{"value":"first","value":"second"}'
                if fault == "invalid_json":
                    text = '{"value":'
                message = {"role": "assistant", "content": None, "tool_calls": [{
                    "id": "fake-tool", "type": "function", "function": {
                        "name": adapter.clients.TOOL_NAME, "arguments": text}}]}
                if fault == "missing_tool":
                    message = {"role": "assistant", "content": text}
                payload = {"id": "duplicate-id" if fault == "duplicate_response" else "fake-" + str(evidence.identity["ordinal"]),
                           "model": "other-model" if fault == "model_mismatch" else expected["model"],
                           "choices": [{"index": 0, "message": message,
                                        "finish_reason": "length" if fault == "truncated" else "tool_calls"}],
                           "usage": {"prompt_tokens": 90, "completion_tokens": 10, "total_tokens": 100}}
                if fault == "usage_unknown":
                    payload.pop("usage")
                if fault == "usage_negative":
                    payload["usage"]["total_tokens"] = -1
                if fault == "usage_boolean":
                    payload["usage"]["total_tokens"] = True
                raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                status = 400 if fault == "http_error" else 200
                protected, manifest = evidence.save_body(raw, evidenced.http_metadata(status, {"x-request-id": "offline"}))
                return evidenced.parse_saved_response(protected, manifest, role, expected["model"], thinking, structured_schema, evidence)

        return lambda: FakeClient()

    runtime = adapter.GoalContextRuntime(project, root, [source], inherited, profile=profile,
                                        stage_limits=stage_limits, admission=admission,
                                        client_factory_builder=factory_builder)
    runtime.prepare()
    return runtime, profile, sends, constructions


def accept(value):
    return {"valid": True, "accepted": True, "fixture_not_quality": True}


def test_complete_stage_requests_inherit_full_spend_and_explicit_model_protocol(tmp_path):
    runtime, profile, sends, constructions = temporary_runtime(tmp_path)
    for index, stage in enumerate(adapter.STAGE_ROLES):
        wire = request(profile, stage)
        receipt = runtime.dispatch(stage + "_01", wire, accept)
        assert receipt["ordinal"] == 531 + index and receipt["status"] == "contract_valid"
        assert receipt["validation"]["fixture_not_quality"]
        assert runtime.evidence_path(531 + index).joinpath("response_body.raw").exists()
    assert len(sends) == len(constructions) == 4
    summary = runtime.summary()
    assert summary["effective_calls_started"] == 534 and summary["effective_reported_tokens"] == 10026012
    assert summary["effective_calls_with_known_usage"] == 532
    assert summary["historical_pending_ordinals"] == [70, 160]
    assert summary["unknown_token_reservations"] == summary["inherited_unknown_token_reservations"] == 93117
    assert summary["new_unknown_token_reservations"] == 0
    assert summary["stage_calls"] == {stage: 1 for stage in adapter.STAGE_ROLES}
    assert not summary["old_budget_reset"] and summary["media_calls"] == 0
    assert sends[1]["parameters"]["max_completion_tokens"] == 8000
    assert sends[3]["parameters"]["max_completion_tokens"] == 24000


def test_same_request_reuses_saved_copy_without_new_send_or_receipt_mutation(tmp_path):
    runtime, profile, sends, _ = temporary_runtime(tmp_path)
    wire = request(profile)
    first = runtime.dispatch("goal_01", wire, accept)
    before = runtime.ledger.read_bytes()
    receipt_path = runtime.root / adapter.read(runtime.ledger)["calls"][0]["receipt"]
    receipt_bytes = receipt_path.read_bytes()
    cached = runtime.dispatch("another_label_same_request", wire, lambda value: {"valid": False, "findings": ["new local diagnosis"]})
    assert len(sends) == 1 and cached["ordinal"] == first["ordinal"]
    assert cached["cached_response_read_only"] and cached["provider_called"] is False
    assert cached["status"] == "contract_rejected"
    assert runtime.ledger.read_bytes() == before and receipt_path.read_bytes() == receipt_bytes


def test_complete_rejected_contract_can_be_locally_rechecked_without_paid_retry(tmp_path):
    runtime, profile, sends, _ = temporary_runtime(tmp_path)
    wire = request(profile)
    receipt = runtime.dispatch("goal_01", wire, lambda value: {"valid": False, "findings": ["local reject"]})
    original = (runtime.root / adapter.read(runtime.ledger)["calls"][0]["receipt"]).read_bytes()
    cached = runtime.dispatch("goal_01", wire, accept)
    assert receipt["status"] == "contract_rejected" and cached["status"] == "contract_valid"
    assert len(sends) == 1 and (runtime.root / adapter.read(runtime.ledger)["calls"][0]["receipt"]).read_bytes() == original


def test_duplicate_label_with_different_context_is_blocked_before_claim(tmp_path):
    runtime, profile, sends, _ = temporary_runtime(tmp_path)
    runtime.dispatch("goal_01", request(profile), accept)
    with pytest.raises(RuntimeError, match="label bound"):
        runtime.dispatch("goal_01", request(profile, version=2), accept)
    assert len(sends) == 1 and runtime.summary()["new_calls"] == 1


def test_known_schema_type_failure_preserves_original_and_permits_bounded_native_revision(tmp_path):
    runtime, profile, sends, _ = temporary_runtime(tmp_path, fault="type_error")
    first = runtime.dispatch("goal_01", request(profile), accept)
    second = runtime.dispatch("goal_02", request(profile, version=2), accept)
    assert first["status"] == second["status"] == "contract_rejected"
    assert first["output"] == {"value": 42} and first["failure"]["code"] == "MODULE_SCHEMA_INVALID"
    assert len(sends) == 2 and runtime.summary()["new_reported_tokens"] == 200


def test_semantic_rejection_is_not_interface_failure(tmp_path):
    runtime, profile, _, _ = temporary_runtime(tmp_path)
    receipt = runtime.dispatch("goal_audit_01", request(profile, "goal_audit"),
                               lambda value: {"valid": True, "accepted": False, "findings": ["weak ending"]})
    assert receipt["status"] == "contract_valid" and receipt["validation"]["accepted"] is False
    assert "failure" not in receipt


def test_validator_returned_invalid_contract_keeps_diagnostics(tmp_path):
    runtime, profile, _, _ = temporary_runtime(tmp_path)
    receipt = runtime.dispatch("full_review_01", request(profile, "full_review"),
                               lambda value: {"valid": False, "findings": [{"code": "PRECONDITION"}]})
    assert receipt["status"] == "contract_rejected"
    assert receipt["validation_error"]["detail"]["findings"][0]["code"] == "PRECONDITION"


@pytest.mark.parametrize("failure,code", [
    ("missing_tool", "REQUIRED_TOOL_MISSING"), ("truncated", "RESPONSE_TRUNCATED"),
    ("model_mismatch", "MODEL_MISMATCH"), ("http_error", "HTTP_ERROR_RESPONSE"),
    ("usage_unknown", "USAGE_UNKNOWN"), ("usage_negative", "USAGE_UNKNOWN"),
    ("usage_boolean", "USAGE_UNKNOWN"), ("duplicate_json_key", "INVALID_JSON_RESPONSE"),
    ("invalid_json", "INVALID_JSON_RESPONSE"),
])
def test_incomplete_protocol_or_usage_blocks_all_later_new_dispatches(tmp_path, failure, code):
    runtime, profile, sends, constructions = temporary_runtime(tmp_path, fault=failure)
    receipt = runtime.dispatch("goal_01", request(profile), accept)
    assert receipt["status"] == "interface_rejected" and receipt["failure"]["code"] == code
    with pytest.raises(RuntimeError, match="no new dispatch"):
        runtime.dispatch("goal_02", request(profile, version=2), accept)
    assert len(sends) == len(constructions) == 1
    assert runtime.evidence_path(531).joinpath("response_body.raw").exists()
    assert runtime.summary()["new_calls"] == 1
    if failure.startswith("usage_"):
        assert runtime.summary()["new_reported_tokens"] == 0
        assert runtime.summary()["unknown_token_reservations"] > 93117


def test_unknown_transport_retains_original_claim_and_never_retries(tmp_path):
    runtime, profile, sends, _ = temporary_runtime(tmp_path, fault="transport_unknown")
    wire = request(profile)
    receipt = runtime.dispatch("goal_01", wire, accept)
    assert receipt["status"] == "outcome_unknown"
    cached = runtime.dispatch("goal_01", wire, accept)
    assert cached["status"] == "outcome_unknown" and cached["provider_called"] is False
    with pytest.raises(RuntimeError, match="no new dispatch"):
        runtime.dispatch("goal_02", request(profile, version=2), accept)
    assert len(sends) == 1 and runtime.summary()["unknown_token_reservations"] > 93117


def test_stage_three_version_allowance_is_persistent_across_restart(tmp_path):
    runtime, profile, sends, _ = temporary_runtime(tmp_path)
    for version in (1, 2, 3):
        runtime.dispatch("goal_0" + str(version), request(profile, version=version), accept)
    reloaded = adapter.GoalContextRuntime(runtime.project, runtime.root, runtime.sources, runtime.inherited,
                                         runtime.models, profile=profile, client_factory_builder=lambda wire: pytest.fail("exhausted stage cannot construct client"))
    reloaded.prepare()
    with pytest.raises(RuntimeError, match="allowance exhausted"):
        reloaded.dispatch("goal_04", request(profile, version=4), accept)
    assert len(sends) == 3 and reloaded.summary()["stage_calls"]["goal_plan"] == 3


def test_changed_stage_limit_cannot_reset_frozen_capacity(tmp_path):
    runtime, profile, _, _ = temporary_runtime(tmp_path, stage_limits={**adapter.DEFAULT_STAGE_LIMITS, "goal_plan": 1})
    runtime.dispatch("goal_01", request(profile), accept)
    runtime.stage_limits["goal_plan"] = 3
    with pytest.raises(RuntimeError, match="policy or stage allowance changed"):
        runtime.dispatch("goal_02", request(profile, version=2), accept)


@pytest.mark.parametrize("change", ["model", "thinking", "cap", "stage_role"])
def test_unverified_request_profile_blocks_before_claim_and_client(tmp_path, change):
    runtime, profile, sends, constructions = temporary_runtime(tmp_path)
    wire = request(profile)
    if change == "model":
        wire["model"] = "MiniMax-M3"
    elif change == "thinking":
        wire["parameters"]["thinking"] = "disabled"
    elif change == "cap":
        wire["parameters"]["max_completion_tokens"] = 8000
    else:
        wire["stage"] = "full_review"
    with pytest.raises(RuntimeError):
        runtime.dispatch("goal_01", wire, accept)
    assert not sends and not constructions and runtime.summary()["new_calls"] == 0


def test_admission_owns_stage_dependencies_and_runs_before_claim(tmp_path):
    def reject(label, wire, ledger):
        assert label == "goal_01" and ledger["calls"] == []
        ledger["calls"].append({"not_a_real_claim": True})
        raise RuntimeError("source admission failed")
    runtime, profile, sends, constructions = temporary_runtime(tmp_path, admission=reject)
    with pytest.raises(RuntimeError, match="source admission"):
        runtime.dispatch("goal_01", request(profile), accept)
    assert not sends and not constructions and runtime.summary()["new_calls"] == 0


def test_runtime_preparation_snapshots_sources_without_constructing_client(tmp_path):
    runtime, _, sends, constructions = temporary_runtime(tmp_path)
    assert not sends and not constructions
    assert (runtime.root / "DISPATCH_POLICY.json").exists()
    assert (runtime.root / "source_at_dispatch/source.txt").read_bytes() == runtime.sources[0].read_bytes()
    assert adapter.read(runtime.ledger)["starting_spend"] == runtime.inherited


def test_duplicate_response_billing_identity_preserves_evidence_and_blocks_followup(tmp_path):
    runtime, profile, sends, _ = temporary_runtime(tmp_path, fault="duplicate_response")
    runtime.dispatch("goal_01", request(profile), accept)
    with pytest.raises(RuntimeError, match="duplicate response identity"):
        runtime.dispatch("goal_02", request(profile, version=2), accept)
    assert len(sends) == 2 and len(adapter.read(runtime.ledger)["calls"]) == 2
    assert runtime.evidence_path(532).joinpath("response_body.raw").exists()
    with pytest.raises(RuntimeError, match="duplicate response identity"):
        runtime.dispatch("goal_03", request(profile, version=3), accept)
    assert len(sends) == 2


def test_native_validator_cannot_mutate_saved_model_output(tmp_path):
    runtime, profile, _, _ = temporary_runtime(tmp_path)
    def mutate(value):
        value["value"] = "hand-patched"
        return {"valid": True}
    receipt = runtime.dispatch("goal_01", request(profile), mutate)
    assert receipt["output"] == {"value": "goal_plan"}
    assert json.loads(receipt["response_text"]) == receipt["output"]


def test_false_admission_cannot_silently_dispatch(tmp_path):
    runtime, profile, sends, constructions = temporary_runtime(tmp_path, admission=lambda *args: False)
    with pytest.raises(RuntimeError, match="admission rejected"):
        runtime.dispatch("goal_01", request(profile), accept)
    assert not sends and not constructions and runtime.summary()["new_calls"] == 0


def test_cached_native_output_must_match_the_saved_response(tmp_path):
    runtime, profile, sends, _ = temporary_runtime(tmp_path)
    wire = request(profile)
    runtime.dispatch("goal_01", wire, accept)
    ledger = adapter.read(runtime.ledger)
    path = runtime.root / ledger["calls"][0]["receipt"]
    receipt = adapter.read(path)
    receipt["output"] = {"value": "manual-patch"}
    adapter.write(path, receipt)
    ledger["calls"][0]["receipt_sha256"] = adapter.sha_file(path)
    adapter.write(runtime.ledger, ledger)
    with pytest.raises(RuntimeError, match="cached output differs"):
        runtime.dispatch("goal_01", wire, accept)
    assert len(sends) == 1


def test_nonboolean_local_validity_is_not_treated_as_pass(tmp_path):
    runtime, profile, _, _ = temporary_runtime(tmp_path)
    receipt = runtime.dispatch("goal_01", request(profile), lambda value: {"valid": "false"})
    assert receipt["status"] == "contract_rejected"
