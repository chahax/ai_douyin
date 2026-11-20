"""Fake-provider integration, never a creative/media quality acceptance."""
from copy import deepcopy
import json
import socket

import pytest

from scripts import run_creative_shared_full_production_v1 as original
from src.content_factory import creative_complete_production_coordinator_v3 as flow
from src.content_factory import creative_complete_production_pipeline_v3 as p
from src.content_factory import creative_production_revision_loop_v3 as loop
from src.content_factory import creative_shared_production_contract_v1 as shared
from tests.test_creative_complete_production_pipeline_v2 import v2_fixture
from tests.test_creative_shared_production_pipeline_v1 import provider_fixture


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("coordinator integration is offline")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def fixture(tmp_path):
    script, manifest, initial, direction, performances = v2_fixture()
    _, provider, _ = provider_fixture(tmp_path)
    manifest["provider_policy"] = deepcopy(provider["provider_policy"])
    manifest["provenance_catalog"] = [row for row in manifest["provenance_catalog"] if row["source_id"] != "policy"]
    manifest["provenance_catalog"] += [deepcopy(row) for row in provider["provenance_catalog"] if row["source_id"] == "policy"]
    manifest["asset_catalog"] = []
    for row in [*manifest["actors"], *manifest["scenes"]]:
        row["asset_binding"] = shared.unknown("离线模拟新选角，尚无实际画面批准")
    direction = p.compile_direction(direction["native"], script, manifest)
    context = json.loads(next(row["text"] for row in manifest["provenance_catalog"] if row["source_id"] == "frozen_source_context"))
    dynamic = original.bootstrap_dynamic_state(manifest, {"brief": context})
    def opening(row):
        return shared.compile_segment_context(manifest, script, dynamic, row["source_refs"], bootstrap=True)
    return script, manifest, initial, direction, performances, context, opening


def receipt(label, request, native, ordinal, status="contract_valid"):
    output = {"payload_json": json.dumps(native, ensure_ascii=False)} if "output_transport" in request else deepcopy(native)
    payload = {"choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": [{"type": "function",
        "function": {"name": "submit_creative_json", "arguments": json.dumps(output, ensure_ascii=False)}}]}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}}
    return {"schema": "offline_fake_provider_receipt", "ordinal": ordinal, "label": label,
        "request": deepcopy(request), "request_sha256": p.digest(request), "source_binding_sha256": "a" * 64,
        "status": status, "output": output, "document_output": deepcopy(native) if "output_transport" in request else None,
        "response_payload": payload, "response_metadata": {"http_status_code": 200, "response_body_complete": True,
            "finish_reason": "tool_calls", "raw_body_sha256": p.digest(payload), "prompt_tokens": 10,
            "completion_tokens": 10, "total_tokens": 20}, "automatic_retry": False}


class FakeService:
    def __init__(self, direction, performances, *, mode=None):
        self.direction = direction
        self.performances = performances
        self.calls, self.saved, self.guards = [], [], 0
        self.mode = mode
        self.directors = 0
        self.reviews = 0

    def save(self, state): self.saved.append(deepcopy(state))
    def guard(self): self.guards += 1

    def invoke(self, label, request, validate):
        stage = request["stage"]
        inputs = json.loads(request["messages"][1]["content"])
        if stage == "whole_direction":
            assert self.saved[-1]["director_events"][-1]["event"] == "claim"
            self.directors += 1
            native = deepcopy(self.direction["native"])
            if self.mode == "window" and self.directors > 1:
                native["segments"][1]["budget_tier"] = "action"
            if self.mode == "review_fail" and self.directors > 1:
                native["whole_observation"] = "观察交涉中听者如何接住要求"
        elif stage == "local_performance":
            idx = int(inputs["current_direction"]["segment_id"][1:]) - 1
            native = deepcopy(self.performances[idx]["native"])
            if self.mode == "window" and idx == 1:
                native["post_reaction_seconds"] = 3
        else:
            self.reviews += 1
            native = {"checks": [{"check": key, "status": "pass", "source_refs": ["B1.S01"],
                "reason": "离线模拟全文审查通过，不是创作质量证据"} for key in original.PRODUCTION_CHECKS],
                "revision_requirements": [], "review_limitations": ["实际人物与声音未经人工审查"]}
            if self.mode in ("review_fail", "review_unknown") and self.reviews == 1:
                native["checks"][0]["status"] = "unknown" if self.mode == "review_unknown" else "fail"
                native["revision_requirements"] = ["离线模拟需要重做整体观察安排"]
        try:
            validate(native)
            status = "contract_valid"
        except ValueError:
            status = "contract_rejected"
        result = receipt(label, request, native, 100 + len(self.calls), status)
        if self.mode in ("unknown", "missing_tool", "truncated", "usage_unknown") and stage == "local_performance":
            if self.mode == "unknown": result["response_metadata"]["http_status_code"] = None
            if self.mode == "missing_tool": result["response_payload"]["choices"][0]["message"]["tool_calls"] = []
            if self.mode == "truncated": result["response_metadata"]["finish_reason"] = "length"
            if self.mode == "usage_unknown": result["response_metadata"]["total_tokens"] = None
            result["status"] = "interface_rejected"
        self.calls.append(deepcopy(result))
        return result


def run(tmp_path, mode=None, limit=3, inherited=()):
    script, manifest, initial, direction, performances, brief, opening = fixture(tmp_path)
    service = FakeService(direction, performances, mode=mode)
    coordinator = flow.CompleteProductionCoordinator(invoke=service.invoke, persist_state=service.save,
        verify_frozen_source=service.guard, opening_context_builder=opening,
        models={"writer": "MiniMax-M3", "director": "deepseek-flash"})
    state = loop.initial_loop_state(inherited, "a" * 64, default_limit=limit,
        stable_scope_material={"full_current_script": script, "shared_manifest": manifest, "planned_initial_state": initial})
    result = coordinator.run(script=script, manifest=manifest, initial=initial,
        reference_fulltext="离线教学参考全文", preferences={}, brief=brief,
        source_review_binding={"writer_ordinal": 1, "review_ordinal": 2, "script_sha256": p.digest(script),
            "machine_text_review_passed": True, "offline_fixture_only": True}, state=state,
        scope={"offline_fixture_only": True, "max_new_video_submissions": 0})
    return result, service


def test_known_window_failure_returns_to_complete_director_and_reuses_exact_first_local(tmp_path):
    result, service = run(tmp_path, "window")
    assert result["complete_text_handoff_ready"]
    assert [r["request"]["stage"] for r in service.calls] == ["whole_direction", "local_performance",
        "local_performance", "whole_direction", "local_performance", "whole_production_review"]
    revising_input = json.loads(service.calls[3]["request"]["messages"][1]["content"])
    feedback = revising_input["known_complete_failure_diagnostics"][0]
    assert feedback["failure_code"] == "LOCAL_PERFORMANCE_WINDOW_EXCEEDED"
    assert feedback["failed_complete_native_result"]["post_reaction_seconds"] == 3
    assert any(event["stage"] == "reuse_check" and event["result"]["native_reused"] for event in result["events"])
    assert result["performances"][1]["native"]["post_reaction_seconds"] == 3
    assert not result["media_dispatch_allowed"] and not result["actual_media_quality_passed"]
    assert result["opening_actual_preview"]["request"]["content"][0]["text"] == result["opening_actual_prompt"]
    assert "当前段导演意图" in result["opening_actual_prompt"]
    assert all("离线教学参考全文" in row["request"]["messages"][1]["content"] for row in service.calls)


@pytest.mark.parametrize("mode", ["unknown", "missing_tool", "truncated", "usage_unknown"])
def test_unknown_or_incomplete_result_stops_without_redispatch(tmp_path, mode):
    result, service = run(tmp_path, mode)
    assert result["status"] == "needs_attention" and result["reason"] == "LOCAL_RESULT_NOT_COMPLETE"
    assert len(service.calls) == 2
    assert service.directors == 1 and service.reviews == 0
    assert not result["complete_text_handoff_ready"]


def test_full_review_failure_rebuilds_director_and_repeats_whole_review(tmp_path):
    result, service = run(tmp_path, "review_fail")
    assert result["complete_text_handoff_ready"]
    assert service.directors == 2 and service.reviews == 2
    assert len([r for r in service.calls if r["request"]["stage"] == "local_performance"]) == 2
    review_requests = [r["request"] for r in service.calls if r["request"]["stage"] == "whole_production_review"]
    first, second = [json.loads(r["messages"][1]["content"]) for r in review_requests]
    assert first["whole_direction"] != second["whole_direction"]
    assert second["complete_compilation"] == result["complete_compilation"]
    assert second["all_local_performances"] == result["performances"]
    assert second["opening_actual_provider_request"] == result["opening_actual_preview"]["request"]


def test_full_review_unknown_does_not_start_new_director(tmp_path):
    result, service = run(tmp_path, "review_unknown")
    assert result["reason"] == "FULL_PRODUCTION_REVIEW_UNKNOWN"
    assert service.directors == 1 and service.reviews == 1


def test_current_real_three_failed_candidates_block_before_any_invocation(tmp_path):
    receipts = [original.control.read(original.ROOT / ("call_" + str(ordinal) + "_whole_direction_r" + str(ordinal - 514) + ".json"))
        for ordinal in (514, 515, 516)]
    state = loop.initial_loop_state(receipts)
    _, _, _, direction, performances, _, _ = fixture(tmp_path)
    script = state["stable_scope_material"]["full_current_script"]
    manifest = state["stable_scope_material"]["shared_manifest"]
    initial = state["stable_scope_material"]["planned_initial_state"]
    service = FakeService(direction, performances)
    coordinator = flow.CompleteProductionCoordinator(invoke=service.invoke, persist_state=service.save,
        verify_frozen_source=service.guard, opening_context_builder=lambda row: (_ for _ in ()).throw(AssertionError("no opening dispatch")),
        models={"writer": "MiniMax-M3", "director": "deepseek-flash"})
    result = coordinator.run(script=script, manifest=manifest, initial=initial, reference_fulltext="离线参考", preferences={},
        brief={}, source_review_binding={"writer_ordinal": 512, "review_ordinal": 513,
            "script_sha256": p.digest(script), "machine_text_review_passed": True}, state=state)
    assert result["reason"] == "INHERITED_DIRECTOR_ALLOWANCE_EXHAUSTED"
    assert service.calls == []
    assert loop.candidate_capacity(result["loop_state"])["attempts_including_claims"] == 3


def test_failed_window_does_not_renew_director_limit_by_revision(tmp_path):
    result, service = run(tmp_path, "window", limit=1)
    assert result["reason"] == "INHERITED_DIRECTOR_ALLOWANCE_EXHAUSTED"
    assert service.directors == 1
    assert len(service.calls) == 3
    assert result["failure_route"]["manual_cut_or_duration_patch_allowed"] is False


def resumed_fixture(tmp_path, state, *, script_override=None):
    script, manifest, initial, direction, performances, brief, opening = fixture(tmp_path)
    service = FakeService(direction, performances)
    coordinator = flow.CompleteProductionCoordinator(invoke=service.invoke, persist_state=service.save,
        verify_frozen_source=service.guard, opening_context_builder=opening,
        models={"writer": "MiniMax-M3", "director": "deepseek-flash"})
    result = coordinator.run(script=script_override or script, manifest=manifest, initial=initial,
        reference_fulltext="离线教学参考全文", preferences={}, brief=brief,
        source_review_binding={"writer_ordinal": 1, "review_ordinal": 2, "script_sha256": p.digest(script),
            "machine_text_review_passed": True}, state=state)
    return result, service


def test_restart_cannot_bypass_local_unknown_or_repeat_director(tmp_path):
    result, original_service = run(tmp_path, "unknown")
    restarted, service = resumed_fixture(tmp_path, result["loop_state"])
    assert restarted["reason"] == "LOCAL_RESULT_NOT_COMPLETE"
    assert service.calls == []
    assert restarted["loop_state"]["coordinator_terminal"]["events"] == result["events"]
    assert len(original_service.calls) == 2


def test_changed_preflight_input_preserves_previous_unknown_evidence(tmp_path):
    result, _ = run(tmp_path, "unknown")
    changed = deepcopy(result["loop_state"]["stable_scope_material"]["full_current_script"])
    changed["title"] = "来源被改变"
    restarted, service = resumed_fixture(tmp_path, result["loop_state"], script_override=changed)
    assert restarted["reason"] == "COMPLETE_CREATIVE_SOURCE_SCOPE_CHANGED"
    assert service.calls == []
    history = restarted["loop_state"]["coordinator_terminal_history"]
    assert history[-1] == result["loop_state"]["coordinator_terminal"]


def test_running_claim_restart_stops_instead_of_starting_another_request(tmp_path):
    script, manifest, initial, direction, _, _, _ = fixture(tmp_path)
    state = loop.initial_loop_state([], "a" * 64, stable_scope_material={
        "full_current_script": script, "shared_manifest": manifest, "planned_initial_state": initial})
    req = p.build_request("whole_direction", p.build_director_input(script, manifest, initial, "离线教学参考全文", {}),
        p.whole_direction_schema(script, manifest), "MiniMax-M3")
    state = loop.claim_director_request(state, p.digest(req))
    state["coordinator_status"] = "running"
    restarted, service = resumed_fixture(tmp_path, state)
    assert restarted["reason"] == "EXISTING_EXECUTION_RECONCILE_OR_REUSE_SAVED_HANDOFF"
    assert service.calls == []
    assert loop.candidate_capacity(restarted["loop_state"])["attempts_including_claims"] == 1
