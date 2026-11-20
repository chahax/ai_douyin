"""Independent runner routing and immutable accounting, with pure fake clients.

Fixtures are explicitly artificial and do not judge creative quality. The new
SDK adapter has separate MockTransport tests. These tests never touch live roots,
old receipts/freeze files, credentials, or actual model/video services.
"""
from copy import deepcopy
import json
import socket

import pytest

from scripts import run_m31_flash_script_test_v1 as runner
from scripts import creative_bounded_format_role_clients_v1 as bounded
from scripts import creative_evidenced_role_clients_v1 as evidenced
from tests.test_creative_fresh_legal_text_pipeline_v1 import (
    inputs, theme_for, raw_script, plan_for_fresh, review_for,
)


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("new-model runner tests cannot use sockets")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def fixture_context():
    case = inputs()
    preferences = {**case["production_preferences"], "whole_film_max_seconds": 180}
    brief = runner.fresh.compile_brief(theme_for(case["packet"]), case["packet"],
        case["legal_context"], preferences, case["source_binding_sha256"])
    return {"brief": brief, "creative_scene_plan": plan_for_fresh(brief),
        "source_packet": case["packet"], "verified_legal_context": case["legal_context"],
        "reference_fulltext": "独立路由测试的唯一参考全文；纯模拟，不作创作质量判断。",
        "expression_standards": case["expression_standards"],
        "production_preferences": preferences,
        "automatic_creative_choice_not_user_approval": True}


def envelope(role, value, *, tools=True, finish=None, usage=True, wrong_model=False):
    message = {"role": "assistant", "content": None}
    if tools:
        message["tool_calls"] = [{"id": "offline-tool", "type": "function", "function": {
            "name": runner.clients.TOOL_NAME, "arguments": json.dumps(value, ensure_ascii=False)}}]
    else:
        message["content"] = json.dumps(value, ensure_ascii=False)
    payload = {"id": "offline-writer" if role == "writer" else "offline-review",
        "model": "MiniMax-M3" if wrong_model else (
            runner.clients.WRITER_MODEL if role == "writer" else runner.clients.REVIEW_MODEL),
        "choices": [{"index": 0, "message": message,
            "finish_reason": finish or ("tool_calls" if tools else "stop")}],
        "base_resp": {"status_code": 0}}
    if usage:
        payload["usage"] = {"prompt_tokens": 90, "completion_tokens": 10, "total_tokens": 100}
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def temporary_run(tmp_path, monkeypatch, *, writer_body=None, fault=None):
    project = tmp_path / "project"
    root = project / "trial"
    project.mkdir()
    source = project / "source.json"
    source.write_text('{"fixture":"offline_only"}', encoding="utf-8")
    profile = project / "profile.json"
    profile.write_text(json.dumps(runner.read(runner.PROFILE)), encoding="utf-8")
    monkeypatch.setattr(runner, "PROJECT", project)
    monkeypatch.setattr(runner, "ROOT", root)
    monkeypatch.setattr(runner, "PROFILE", profile)
    context = fixture_context()
    prior = {"output": raw_script(), "ordinal": 528}
    monkeypatch.setattr(runner, "input_context", lambda: (deepcopy(prior), deepcopy(context)))
    runtime = runner.M31Runtime(project, root, [source],
        {"calls_started": 528, "reported_tokens": 9951442, "calls_with_known_usage": 526,
         "pending_ordinals": [70, 160], "unknown_token_reservations": 93117},
        runner.models(), inherited_guard=lambda: None, quota_state=None)
    runtime.prepare()
    monkeypatch.setattr(runner, "get_runtime", lambda: runtime)
    runner.write(root / "USER_SCOPE.json", {"grant_id": runner.GRANT,
        "native_writer_limit": 1, "full_review_limit": 1, "automatic_retry": False})
    request = runner.writer_request()
    runner.write(root / "REQUEST_PREVIEW.json", request, True)
    calls = []
    writer_body = deepcopy(writer_body or raw_script())

    class FakeClient:
        def __init__(self, expected_request):
            self.request = deepcopy(expected_request)

        def call(self, role, messages, *, max_tokens, temperature, thinking, structured_schema, evidence):
            assert role == self.request["role"] and messages == self.request["messages"]
            assert structured_schema == self.request["structured_schema"]
            assert evidence.identity["request_sha256"] == runner.digest(self.request)
            calls.append(deepcopy(self.request))
            outgoing = json.dumps(runner.clients.expected_wire_request(self.request),
                                  ensure_ascii=False).encode("utf-8")
            bounded.save_request_body(evidence, outgoing, role=role)
            if role == "writer":
                value = deepcopy(writer_body)
            else:
                payload = json.loads(messages[1]["content"])
                value = review_for(payload["full_current_script"], payload["brief"],
                    payload["full_scene_plan"], payload["verified_legal_context"])
            raw = envelope(role, value,
                tools=not (role == "writer" and fault == "missing_tool"),
                finish="length" if role == "writer" and fault == "truncated" else None,
                usage=not (role == "writer" and fault == "usage_unknown"),
                wrong_model=role == "writer" and fault == "model_mismatch")
            protected, manifest = evidence.save_body(raw,
                evidenced.http_metadata(200, {"x-request-id": "offline-response"}))
            return evidenced.parse_saved_response(protected, manifest, role, self.request["model"],
                thinking, structured_schema, evidence)

    monkeypatch.setattr(runner.clients, "make_client_factory", lambda request: lambda: FakeClient(request))
    return runtime, root, request, context, calls


def test_complete_fake_writer_then_same_source_full_review_inherits_spend(tmp_path, monkeypatch):
    runtime, root, request, context, calls = temporary_run(tmp_path, monkeypatch)
    state = runner.run()
    assert len(calls) == 2 and [row["role"] for row in calls] == ["writer", "director"]
    assert state["status"] == "text_ready_for_director" and state["complete_script_ready"] is True
    assert not state["human_quality_approved"] and not state["creative_quality_passed"]
    assert not state["media_authorized"]
    spend = runtime.summary()
    assert spend["new_calls"] == 2 and spend["effective_calls_started"] == 530
    assert spend["new_reported_tokens"] == 200 and spend["effective_reported_tokens"] == 9951642
    assert spend["old_budget_reset"] is False and spend["media_calls"] == 0
    assert spend["inherited_unknown_token_reservations"] == spend["unknown_token_reservations"] == 93117
    assert spend["new_unknown_token_reservations"] == 0 and spend["historical_pending_ordinals"] == [70, 160]
    ledger = runner.read(runtime.ledger)
    assert ledger["starting_spend"]["calls_started"] == 528
    assert ledger["starting_spend"]["reported_tokens"] == 9951442
    assert ledger["starting_spend"]["calls_with_known_usage"] == 526
    assert ledger["starting_spend"]["pending_ordinals"] == [70, 160]
    assert ledger["starting_spend"]["unknown_token_reservations"] == 93117
    assert [row["ordinal"] for row in ledger["calls"]] == [529, 530]
    compiled = runner.fresh.contract.compile_script(raw_script(), context["brief"])
    actual_review = json.loads(calls[1]["messages"][1]["content"])
    assert actual_review["full_current_script"] == compiled
    assert actual_review["evidence_catalog"] == runner.fresh.contract.evidence_catalog(compiled)
    assert calls[1]["input_provenance"]["full_script_sha256"] == runner.digest(compiled)
    assert runner.read(root / "NATIVE_SCRIPT.json") == raw_script()
    assert not (root / "PRODUCTION_RESULT.json").exists()


@pytest.mark.parametrize("fault,code", [
    ("missing_tool", "REQUIRED_TOOL_MISSING"),
    ("truncated", "RESPONSE_TRUNCATED"),
    ("model_mismatch", "MODEL_MISMATCH"),
    ("usage_unknown", None),
])
def test_protocol_or_usage_unknown_never_dispatches_review_or_retries(tmp_path, monkeypatch, fault, code):
    runtime, root, _, _, calls = temporary_run(tmp_path, monkeypatch, fault=fault)
    state = runner.run()
    assert len(calls) == 1 and state["status"] == "script_not_accepted_no_retry"
    assert state["complete_script_ready"] is False and state["automatic_retry"] is False
    assert "review_ordinal" not in state and not (root / "FULL_REVIEW.json").exists()
    ledger = runner.read(runtime.ledger)
    receipt = runner.read(root / ledger["calls"][0]["receipt"])
    if code:
        assert receipt["failure"]["code"] == code
    else:
        assert "total_tokens" not in receipt["response_metadata"]
        assert runtime.summary()["new_unknown_token_reservations"] > 0
        assert runtime.summary()["unknown_token_reservations"] > 93117
        assert runtime.summary()["new_reported_tokens"] == 0
        assert runtime.summary()["effective_reported_tokens"] == 9951442
    assert (runtime.evidence_path(529) / "response_body.raw").exists()


def test_dual_timing_diagnostics_stop_after_writer_and_preserve_original(tmp_path, monkeypatch):
    value = raw_script()
    # Three explicit synthetic long utterances exceed individual and whole
    # constraints; a pure fixture is not a repaired/adopted production draft.
    for beat in value["beats"]:
        for step in beat["steps"]:
            if step["kind"] == "dialogue":
                step["text"] = "字" * 210
    runtime, root, _, _, calls = temporary_run(tmp_path, monkeypatch, writer_body=value)
    state = runner.run()
    assert len(calls) == 1 and state["status"] == "script_not_accepted_no_retry"
    ledger = runner.read(runtime.ledger)
    receipt = runner.read(root / ledger["calls"][0]["receipt"])
    assert receipt["status"] == "contract_rejected"
    assert receipt["failure"]["code"] == "SCRIPT_FEASIBILITY_BLOCKED"
    report = runner.read(root / "SCRIPT_FEASIBILITY.json")
    assert {row["code"] for row in report["issues"]} == {
        "SCRIPT_DIALOGUE_WINDOW_EXCEEDED", "WHOLE_FILM_SPEECH_MINIMUM_EXCEEDED"}
    assert len(report["dialogue_window_diagnostics"]["violations"]) == 3
    assert runner.read(root / "NATIVE_SCRIPT.json") == value
    assert (root / "COMPLETE_SCRIPT_FOR_REVIEW.md").exists()
    assert not (root / "FULL_REVIEW.json").exists()


def test_run_claim_blocks_reentry_without_second_dispatch(tmp_path, monkeypatch):
    runtime, root, _, _, calls = temporary_run(tmp_path, monkeypatch)
    runner.run()
    ledger_bytes = runtime.ledger.read_bytes()
    with pytest.raises(FileExistsError):
        runner.run()
    assert len(calls) == 2 and runtime.ledger.read_bytes() == ledger_bytes
    assert runner.read(root / "RUN_CLAIM.json")["automatic_restart"] is False


def test_dispatch_cached_receipt_is_read_only_and_new_writer_scope_is_exhausted(tmp_path, monkeypatch):
    runtime, root, request, context, calls = temporary_run(tmp_path, monkeypatch)
    runner.run()
    validator = runner.feasibility.make_validator(context["brief"], context["production_preferences"])
    before = runtime.ledger.read_bytes()
    cached = runtime.dispatch("m31_complete_script_01", request, validator)
    assert cached["ordinal"] == 529 and cached["status"] == "contract_valid"
    assert runtime.ledger.read_bytes() == before and len(calls) == 2
    changed = deepcopy(request)
    changed["messages"][1]["content"] += " "
    with pytest.raises(RuntimeError, match="scope exhausted"):
        runtime.dispatch("m31_complete_script_03", changed, validator)
    assert len(calls) == 2 and runtime.ledger.read_bytes() == before


def test_review_request_with_different_script_identity_is_blocked_before_dispatch(tmp_path, monkeypatch):
    runtime, _, request, context, calls = temporary_run(tmp_path, monkeypatch)
    validator = runner.feasibility.make_validator(context["brief"], context["production_preferences"])
    runner.invoke(runtime, "m31_complete_script_01", request, validator)
    other = raw_script()
    other["title"] = "另一份正文"
    review = runner.review_request(other)
    with pytest.raises(RuntimeError, match="(?i)(script|source|identity|bound)"):
        runtime.dispatch("m31_full_review_01", review, lambda value: {})
    assert len(calls) == 1


def test_review_role_model_mismatch_blocks_before_dispatch(tmp_path, monkeypatch):
    runtime, _, request, context, calls = temporary_run(tmp_path, monkeypatch)
    runner.invoke(runtime, "m31_complete_script_01", request,
        runner.feasibility.make_validator(context["brief"], context["production_preferences"]))
    review = runner.review_request(raw_script())
    review["model"] = "MiniMax-M3.1-Flash-Preview"
    with pytest.raises(RuntimeError, match="role model changed"):
        runtime.dispatch("m31_full_review_01", review, lambda value: {})
    assert len(calls) == 1


def test_real_request_has_one_reference_full_failed_528_and_original_525_plan():
    # This read-only replay uses real source bytes, but never creates a runtime,
    # test freeze, claim, service client, or production output directory.
    receipt, source = runner.input_context()
    request = runner.writer_request()
    actual = json.loads(request["messages"][1]["content"])
    assert actual["previous_complete_document"] == receipt["output"]
    native525 = runner.read(runner.OLD_ROOT / "call_525_fresh_plan_02_format_recovery.json")["output"]
    assert actual["creative_scene_plan"] == runner.fresh.contract.compile_plan(native525, actual["brief"])
    def count(value):
        if isinstance(value, str):
            return int(value == source["reference_fulltext"])
        if isinstance(value, dict):
            return sum(count(child) for child in value.values())
        if isinstance(value, list):
            return sum(count(child) for child in value)
        return 0
    assert count(actual) == 1
    assert actual["reference_fulltext"] == source["reference_fulltext"]
    assert {row["code"] for row in actual["complete_script_feasibility_diagnostics"]["issues"]} == {
        "SCRIPT_DIALOGUE_WINDOW_EXCEEDED", "WHOLE_FILM_SPEECH_MINIMUM_EXCEEDED"}
    wire = runner.clients.expected_wire_request(request)
    assert wire["model"] == "MiniMax-M3.1-Flash-Preview" and wire["reasoning_effort"] == "medium"
    assert wire["max_completion_tokens"] == 16000
    assert not ({"thinking", "reasoning_split", "tool_choice"} & set(wire))
    assert request["input_provenance"]["original_failed_ordinal"] == 528
    assert request["input_provenance"]["new_collection_performed"] is False


def test_real_review_request_consumes_exact_full_script_and_provenance():
    receipt, source = runner.input_context()
    native = receipt["output"]
    request = runner.review_request(native)
    payload = json.loads(request["messages"][1]["content"])
    compiled = runner.fresh.contract.compile_script(native, source["brief"])
    assert payload["full_current_script"] == compiled
    assert payload["full_scene_plan"] == source["creative_scene_plan"]
    assert payload["brief"] == source["brief"]
    assert request["input_provenance"]["full_script_sha256"] == runner.digest(compiled)
    assert request["input_provenance"]["native_script_sha256"] == runner.digest(native)
    assert request["structured_schema"]["properties"]["script_sha256"]["const"] == runner.digest(compiled)


def test_actual_source_freshness_gate_rejects_expired_snapshot_without_new_claim():
    before = (runner.OLD_ROOT / "source/SOURCE_PACKET.json").read_bytes()
    with pytest.raises(ValueError):
        runner.source_gate("2099-01-01T00:00:00+00:00")
    assert (runner.OLD_ROOT / "source/SOURCE_PACKET.json").read_bytes() == before


def test_prepare_source_gate_failure_occurs_before_scope_or_freeze(tmp_path, monkeypatch):
    root = tmp_path / "trial"
    monkeypatch.setattr(runner, "ROOT", root)
    monkeypatch.setattr(runner, "old_guard", lambda: {})
    def expired():
        raise ValueError("source freshness gate failed")
    monkeypatch.setattr(runner, "source_gate", expired)
    with pytest.raises(ValueError, match="freshness"):
        runner.prepare()
    assert not root.exists()
