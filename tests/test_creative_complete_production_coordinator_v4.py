"""Endpoint-to-handoff fake-service integration, never media quality proof."""
from copy import deepcopy
import base64
import hashlib
import json
from pathlib import Path
import socket

import pytest
from jsonschema import ValidationError

from scripts import run_creative_shared_full_production_v1 as original
from src.content_factory import creative_complete_production_coordinator_v4 as flow
from src.content_factory import creative_complete_production_pipeline_v4 as pipeline
from src.content_factory import creative_production_revision_loop_v3 as loop
from src.content_factory import creative_reference_compiler_v4 as references
from tests.test_creative_complete_production_coordinator_v3 import fixture, receipt
from src.content_factory import creative_complete_production_pipeline_v2 as ranges

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "data/production_revisions/shared_full_production_20261012/probe_v4"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("endpoint coordinator tests are offline")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def endpoints(direction, script, manifest):
    edges = {row["range_id"]: row for row in ranges.candidate_graph(script, manifest)["ranges"]}
    native = {key: deepcopy(value) for key, value in direction["native"].items() if key != "segments"}
    native["segments"] = [{**{key: deepcopy(value) for key, value in row.items() if key != "range_id"},
        "end_source_ref": edges[row["range_id"]]["end_source_ref"]}
        for row in direction["native"]["segments"]]
    return native


class FakeService:
    def __init__(self, native, performances, mode=None):
        self.direction, self.performances, self.mode = native, performances, mode
        self.calls, self.saved, self.directors, self.reviews = [], [], 0, 0
        self.guards = 0
        self.base_ordinal = 100

    def save(self, state): self.saved.append(deepcopy(state))
    def guard(self): self.guards += 1

    def invoke(self, label, request, validate):
        assert self.saved[-1]["stage_dispatch_events"][-1]["event"] == "claim"
        assert self.saved[-1]["stage_dispatch_events"][-1]["request_sha256"] == pipeline.digest(request)
        stage = request["stage"]
        inp = json.loads(request["messages"][1]["content"])
        if stage == "whole_direction":
            assert self.saved[-1]["director_events"][-1]["event"] == "claim"
            assert "endpoint_graph" in inp and "candidate_graph" not in inp
            assert "只选择end_source_ref" in request["messages"][0]["content"]
            self.directors += 1
            native = deepcopy(self.direction)
            if self.mode == "director_invalid" and self.directors == 1:
                native["segments"][-1]["end_source_ref"] = native["segments"][0]["end_source_ref"]
            if self.mode == "window" and self.directors > 1:
                native["segments"][1]["budget_tier"] = "action"
            if self.mode == "review_fail" and self.directors > 1:
                native["whole_observation"] = "观察交涉中听者如何接住要求"
        elif stage == "local_performance":
            index = int(inp["current_direction"]["segment_id"][1:]) - 1
            native = deepcopy(self.performances[index]["native"])
            if self.mode == "window" and index == 1:
                native["post_reaction_seconds"] = 3
            if self.mode == "local_invalid":
                native["segment_id"] = "not_current_segment"
        else:
            self.reviews += 1
            assert inp["whole_direction_native"] == inp["whole_direction"]["native"]
            assert all("end_source_ref" in row and "range_id" not in row
                for row in inp["whole_direction_native"]["segments"])
            assert inp["whole_direction_original_service_identity"]["native_sha256"] == pipeline.digest(inp["whole_direction_native"])
            native = {"checks": [{"check": key, "status": "pass", "source_refs": ["B1.S01"],
                "reason": "仅模拟完整服务审查，不证明创作或视频质量"} for key in original.PRODUCTION_CHECKS],
                "revision_requirements": [], "review_limitations": ["模拟服务，不是人工视频批准"]}
            if self.mode in ("review_fail", "review_unknown") and self.reviews == 1:
                native["checks"][0]["status"] = "unknown" if self.mode == "review_unknown" else "fail"
                native["revision_requirements"] = ["模拟需重做整片观察安排"]
        try:
            validate(native)
            status = "contract_valid"
        except (ValueError, ValidationError):
            status = "contract_rejected"
        result = receipt(label, request, native, self.base_ordinal + len(self.calls), status)
        if self.mode in ("unknown", "missing_tool", "truncated", "usage_unknown", "wrong_source") and stage == "local_performance":
            if self.mode == "unknown": result["response_metadata"]["http_status_code"] = None
            if self.mode == "missing_tool": result["response_payload"]["choices"][0]["message"]["tool_calls"] = []
            if self.mode == "truncated": result["response_metadata"]["finish_reason"] = "length"
            if self.mode == "usage_unknown": result["response_metadata"]["total_tokens"] = None
            if self.mode == "wrong_source": result["source_binding_sha256"] = "f" * 64
            result["status"] = "interface_rejected"
        self.calls.append(deepcopy(result))
        if self.mode == "exception" and stage == "local_performance":
            raise TimeoutError("explicit fake transport timeout")
        return result


def run(tmp_path, mode=None, limit=3, *, state=None, script_override=None,
        enricher=None, models=None, preflight=None, context_override=None, missing_context_proof=False,
        mutate_request=None):
    script, manifest, initial, direction, performances, brief, opening = fixture(tmp_path)
    service = FakeService(endpoints(direction, script, manifest), performances, mode)
    def invoke(label, request, validate):
        row = service.invoke(label, request, validate)
        if mutate_request is not None:
            mutate_request(request)
            row["request"] = deepcopy(request)
            row["request_sha256"] = pipeline.digest(request)
        return row
    coordinator = flow.CompleteProductionCoordinator(invoke=invoke, persist_state=service.save,
        verify_frozen_source=service.guard, opening_context_builder=opening,
        models=models or {"writer": "MiniMax-M3", "director": "deepseek-flash"},
        director_request_enricher=enricher, preflight_text_request=preflight)
    actual_script = script_override or script
    state = state or loop.initial_loop_state([], "a" * 64, default_limit=limit,
        stable_scope_material={"full_current_script": script, "shared_manifest": manifest, "planned_initial_state": initial})
    inherited_ids = [event["result"]["result_id"] for event in state["director_events"] if "result" in event]
    inherited_ids += [event["evidence"]["result_id"] for event in state.get("stage_dispatch_events", []) if "evidence" in event]
    service.base_ordinal = max([99, *[int(value) for value in inherited_ids if str(value).isdigit()]]) + 1
    context = {"brief": brief, "reference_fulltext": "R01完整教学参考全文", "production_preferences": {}}
    binding = {"writer_ordinal": 1, "review_ordinal": 2,
            "script_sha256": pipeline.digest(actual_script), "machine_text_review_passed": True,
            "production_context_sha256": pipeline.digest(context), "offline_fixture_only": True}
    if missing_context_proof:
        binding.pop("production_context_sha256")
    context.update(deepcopy(context_override or {}))
    result = coordinator.run(script=actual_script, manifest=manifest, initial=initial,
        reference_fulltext=context["reference_fulltext"], preferences=context["production_preferences"], brief=context["brief"],
        source_review_binding=binding, state=state, scope={"offline_fixture_only": True,
            "max_new_video_submissions": 0})
    return result, service


def test_complete_native_endpoint_chain_reaches_locals_compile_and_full_review(tmp_path):
    result, service = run(tmp_path)
    assert result["complete_text_handoff_ready"]
    assert [r["request"]["stage"] for r in service.calls] == ["whole_direction", "local_performance",
        "local_performance", "whole_production_review"]
    native = service.calls[0]["document_output"]
    assert result["direction"]["native"] == native == result["whole_direction_native"]
    assert result["complete_compilation"]["direction"]["native"] == native
    assert result["complete_compilation"]["manual_creative_patch_applied"] is False
    assert not result["media_dispatch_allowed"] and not result["human_creative_quality_passed"]
    journal = result["loop_state"]["stage_dispatch_events"]
    assert len([r for r in journal if r["event"] == "claim"]) == 4
    assert len([r for r in journal if r["event"] == "result"]) == 4
    assert all(r["preflight"]["status"] == "capability_preflight_passed" for r in journal if r["event"] == "claim")
    assert all("完整教学参考全文" in row["request"]["messages"][1]["content"] for row in service.calls)


def test_known_window_failure_revises_native_endpoint_plan_reuses_exact_first_local(tmp_path):
    result, service = run(tmp_path, "window")
    assert result["complete_text_handoff_ready"]
    assert [r["request"]["stage"] for r in service.calls] == ["whole_direction", "local_performance",
        "local_performance", "whole_direction", "local_performance", "whole_production_review"]
    feedback = json.loads(service.calls[3]["request"]["messages"][1]["content"])["known_complete_failure_diagnostics"][0]
    assert feedback["failure_code"] == loop.WINDOW_FAILURE
    assert "end_source_ref" in feedback["prior_complete_native_direction"]["segments"][0]
    assert feedback["failed_complete_native_result"]["post_reaction_seconds"] == 3
    assert any(e["stage"] == "reuse_check" and e["result"]["native_reused"] for e in result["events"])
    assert result["direction"]["native"] == service.calls[3]["document_output"]


def test_known_director_failure_revises_complete_native_without_format_projection(tmp_path):
    result, service = run(tmp_path, "director_invalid")
    assert result["complete_text_handoff_ready"] and service.directors == 2
    feedback = json.loads(service.calls[1]["request"]["messages"][1]["content"])["known_complete_failure_diagnostics"][0]
    assert feedback["failed_complete_native_result"] == service.calls[0]["document_output"]
    assert result["direction"]["native"] == service.calls[1]["document_output"]


def test_whole_review_fail_rebuilds_direction_and_review_without_recalling_unchanged_locals(tmp_path):
    result, service = run(tmp_path, "review_fail")
    assert result["complete_text_handoff_ready"] and service.reviews == service.directors == 2
    assert len([r for r in service.calls if r["request"]["stage"] == "local_performance"]) == 2
    assert any(e.get("full_production_review_invalidated") for e in result["events"])


@pytest.mark.parametrize("mode", ["unknown", "missing_tool", "truncated", "usage_unknown", "wrong_source"])
def test_incomplete_or_wrong_source_stops_and_reentry_never_redispatches(tmp_path, mode):
    result, service = run(tmp_path, mode)
    assert result["reason"] == "LOCAL_RESULT_NOT_COMPLETE" and len(service.calls) == 2
    assert not result["complete_text_handoff_ready"]
    restarted, second = run(tmp_path, state=result["loop_state"])
    assert restarted["reason"] == result["reason"] and second.calls == []


def test_transport_exception_preserves_unresolved_claim_and_stops_reentry(tmp_path):
    result, service = run(tmp_path, "exception")
    assert result["reason"] == "STAGE_DISPATCH_OUTCOME_UNKNOWN"
    journal = result["loop_state"]["stage_dispatch_events"]
    assert journal[-1]["outcome_unknown"] and journal[-2]["event"] == "claim"
    restarted, second = run(tmp_path, state=result["loop_state"])
    assert restarted["reason"] == result["reason"] and second.calls == []


def test_capability_preflight_precedes_director_claim_and_invoke(tmp_path):
    result, service = run(tmp_path, models={"writer": "unknown-new-model", "director": "deepseek-flash"})
    assert result["reason"] == "MODEL_ROLE_ASSIGNMENT_DIFFERS_FROM_FROZEN_POLICY"
    assert service.calls == [] and not result["loop_state"]["director_events"]
    assert not result["loop_state"].get("stage_dispatch_events")


def test_wrong_preflight_identity_is_blocked_without_claim(tmp_path):
    def wrong(request, registry):
        return {"status": "capability_preflight_passed", "blocked": False, "request_sha256": "0" * 64}
    result, service = run(tmp_path, preflight=wrong)
    assert result["reason"] == "TEXT_PROVIDER_PREFLIGHT_IDENTITY_INVALID"
    assert service.calls == [] and not result["loop_state"]["director_events"]


def test_full_review_unknown_stops_no_whole_revision(tmp_path):
    result, service = run(tmp_path, "review_unknown")
    assert result["reason"] == "FULL_PRODUCTION_REVIEW_UNKNOWN"
    assert service.directors == service.reviews == 1


def test_local_content_revisions_are_bounded_full_native_versions(tmp_path):
    result, service = run(tmp_path, "local_invalid")
    assert result["reason"] == "LOCAL_CONTENT_REVISION_ALLOWANCE_EXHAUSTED"
    locals_ = [r for r in service.calls if r["request"]["stage"] == "local_performance"]
    assert len(locals_) == 3
    last = json.loads(locals_[-1]["request"]["messages"][1]["content"])
    assert len(last["previous_complete_rejected_versions"]) == 2
    assert all(row["complete_rejected_native"] == locals_[index]["document_output"]
        for index, row in enumerate(last["previous_complete_rejected_versions"]))


def test_cap_exhaustion_does_not_renew_for_local_window_failure(tmp_path):
    result, service = run(tmp_path, "window", limit=1)
    assert result["reason"] == "INHERITED_DIRECTOR_ALLOWANCE_EXHAUSTED" and service.directors == 1
    assert result["failure_route"]["manual_cut_or_duration_patch_allowed"] is False


def test_current_real_four_of_four_blocks_zero_invocation_and_keeps_old_hashes(tmp_path):
    paths = [PROBE / "LOOP_STATE.json", PROBE / "CALL_LEDGER.json", PROBE / "call_517_whole_direction_v3_3.json"]
    hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    state = json.loads(paths[0].read_text(encoding="utf8"))
    before_events = deepcopy(state["director_events"])
    material = state["stable_scope_material"]
    calls, saved = [], []
    def never(*args):
        calls.append(args)
        raise AssertionError("actual exhausted task may not invoke")
    coordinator = flow.CompleteProductionCoordinator(invoke=never, persist_state=saved.append,
        verify_frozen_source=lambda: None, opening_context_builder=never,
        models={"writer": "MiniMax-M3", "director": "deepseek-flash"})
    result = coordinator.run(script=material["full_current_script"], manifest=material["shared_manifest"],
        initial=material["planned_initial_state"], reference_fulltext="not used before exhaustion", preferences={},
        brief={}, source_review_binding={"writer_ordinal": 512, "review_ordinal": 513,
            "script_sha256": pipeline.digest(material["full_current_script"]), "machine_text_review_passed": True,
            "production_context_sha256": flow.production_context_digest({}, "not used before exhaustion", {})}, state=state)
    assert result["reason"] == "INHERITED_DIRECTOR_ALLOWANCE_EXHAUSTED" and calls == []
    assert result["loop_state"]["director_events"] == before_events
    capacity = loop.candidate_capacity(result["loop_state"])
    assert capacity["remaining"] == 0 and capacity["candidate_limit"] == capacity["attempts_including_claims"] == 4
    assert hashes == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def test_finished_run_cannot_repeat_calls_on_restart(tmp_path):
    result, _ = run(tmp_path)
    restarted, second = run(tmp_path, state=result["loop_state"])
    assert restarted["reason"] == "EXISTING_EXECUTION_RECONCILE_OR_REUSE_SAVED_HANDOFF" and second.calls == []


def test_changed_source_stops_and_preserves_prior_terminal_evidence(tmp_path):
    result, _ = run(tmp_path, "unknown")
    script = deepcopy(result["loop_state"]["stable_scope_material"]["full_current_script"])
    script["title"] = "不同来源"
    restarted, service = run(tmp_path, state=result["loop_state"], script_override=script)
    assert restarted["reason"] == "COMPLETE_CREATIVE_SOURCE_SCOPE_CHANGED" and service.calls == []
    assert restarted["loop_state"]["coordinator_terminal_history"][-1] == result["loop_state"]["coordinator_terminal"]


def test_director_enrichment_cannot_rewrite_original_full_source(tmp_path):
    def wrong(request):
        request["messages"][1]["content"] = "changed source"
        return {"request": request, "proof": {}}
    result, service = run(tmp_path, enricher=wrong)
    assert result["reason"] == "DIRECTOR_VISUAL_ENRICHMENT_CHANGED_SOURCE_REQUEST"
    assert service.calls == [] and not result["loop_state"]["director_events"]


def synthetic_enricher(*, change_selection=False, defect=None):
    """Fake coverage exercises coordinator wiring, not B authenticity or art."""
    count = 0
    def enrich(request):
        nonlocal count
        count += 1
        original_messages = deepcopy(request["messages"])
        manifest = json.loads(original_messages[1]["content"])["shared_manifest"]
        required = [{"entity_type": kind, "entity_id": row["id"]}
            for kind, rows in (("actor", manifest["actors"]), ("scene", manifest["scenes"])) for row in rows]
        ordered, mapped, parts = [], [], []
        for number, entity in enumerate(required, 1):
            aid = "explicit_fake_asset_" + str(number)
            data = ("synthetic_image_fixture_" + str(number) + "_" + str(count if change_selection else 1)).encode()
            image = {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(data).decode()}}
            positions = {"content_index": number, "reference_number": number, "reference_label": "image" + str(number)}
            ordered.append({"asset_id": aid, "sha256": hashlib.sha256(data).hexdigest(), **positions,
                "original_task_id": "fake_offline_only_" + aid, "original_receipt_sha256": "b" * 64,
                "explicit_user_approval_sha256": "c" * 64})
            mapped.append({**entity, "asset_id": aid, **positions,
                "subject_key": "explicit_fake_subject", "subject_description": "合成测试夹具，非正式人物采用"})
            parts.append(image)
        actual = deepcopy(original_messages)
        actual.append({"role": "user", "content": [{"type": "text", "text": "离线合成映射\n" + json.dumps(mapped, ensure_ascii=False, sort_keys=True)}, *parts]})
        proof = {"schema": "creative_reference_compiler/v4/director_visual_coverage",
            "original_messages_sha256": pipeline.digest(original_messages), "actual_messages_sha256": pipeline.digest(actual),
            "original_messages_preserved": True, "multimodal_message_index": len(original_messages),
            "ordered_images": ordered, "entity_asset_mapping": mapped, "mapping_sha256": pipeline.digest(mapped),
            "required_visual_entities": required, "assistant_pixel_identity_verified": False,
            "provider_input_acceptance": "unknown", "voice_identity_guaranteed": False,
            "calls_authorized": False, "production_adopted": False, "new_paid_calls": 0}
        if defect == "empty": proof = {}
        if defect == "position": proof["ordered_images"][0]["content_index"] = 3
        if defect == "bytes": proof["ordered_images"][0]["sha256"] = "0" * 64
        request["messages"] = actual
        return {"request": request, "proof": proof}
    return enrich


def test_visual_input_is_in_original_request_receipt_and_full_review_binding(tmp_path):
    result, service = run(tmp_path, enricher=synthetic_enricher())
    assert result["complete_text_handoff_ready"]
    request = service.calls[0]["request"]
    assert any(part["type"] == "image_url" for part in request["messages"][-1]["content"])
    assert result["director_original_request"] == request
    assert service.calls[0]["request_sha256"] == pipeline.digest(request)
    inp = json.loads(service.calls[-1]["request"]["messages"][1]["content"])
    assert inp["director_actual_request_sha256"] == pipeline.digest(request)
    assert inp["director_visual_request_proof"] == result["director_visual_request_proof"]
    assert "data:image" not in service.calls[-1]["request"]["messages"][1]["content"]
    assert inp["director_original_text_input"]["reference_fulltext"] == "R01完整教学参考全文"


@pytest.mark.parametrize("defect", ["empty", "position", "bytes"])
def test_visual_coverage_wrong_or_missing_blocks_before_claim_and_invoke(tmp_path, defect):
    result, service = run(tmp_path, enricher=synthetic_enricher(defect=defect))
    assert result["reason"].startswith("DIRECTOR_VISUAL_")
    assert service.calls == [] and not result["loop_state"]["director_events"]


def test_same_selected_images_allow_exact_local_reuse_after_whole_review_revision(tmp_path):
    result, service = run(tmp_path, "review_fail", enricher=synthetic_enricher())
    assert result["complete_text_handoff_ready"] and service.directors == service.reviews == 2
    assert len([r for r in service.calls if r["request"]["stage"] == "local_performance"]) == 2
    assert any(e["stage"] == "reuse_check" and e["result"]["native_reused"] for e in result["events"])


def test_changed_selected_image_hash_invalidates_local_cache_and_full_review(tmp_path):
    result, service = run(tmp_path, "review_fail", enricher=synthetic_enricher(change_selection=True))
    assert result["complete_text_handoff_ready"] and service.directors == service.reviews == 2
    locals_ = [r for r in service.calls if r["request"]["stage"] == "local_performance"]
    assert len(locals_) == 4
    first, changed = [json.loads(row["request"]["messages"][1]["content"])["director_visual_binding"]
        for row in (locals_[0], locals_[2])]
    assert first["selected_material_sha256"] != changed["selected_material_sha256"]
    assert not any(e["stage"] == "reuse_check" and e["result"]["native_reused"] for e in result["events"])


def test_unresolved_durable_stage_claim_blocks_even_without_running_status(tmp_path):
    script, manifest, initial, *_ = fixture(tmp_path)
    state = loop.initial_loop_state([], "a" * 64, stable_scope_material={
        "full_current_script": script, "shared_manifest": manifest, "planned_initial_state": initial})
    state["coordinator_status"] = "stopped"
    state["stage_dispatch_events"] = [{"event": "claim", "dispatch_identity": "b" * 64,
        "label": "original_local_request", "request_sha256": "c" * 64}]
    result, service = run(tmp_path, state=state)
    assert result["reason"] == "ORIGINAL_STAGE_DISPATCH_UNRESOLVED" and service.calls == []
    assert not result["loop_state"]["director_events"]


def test_changed_stable_scope_digest_blocks_before_claim(tmp_path):
    script, manifest, initial, *_ = fixture(tmp_path)
    state = loop.initial_loop_state([], "a" * 64, stable_scope_material={
        "full_current_script": script, "shared_manifest": manifest, "planned_initial_state": initial})
    state["stable_scope_sha256"] = "b" * 64
    result, service = run(tmp_path, state=state)
    assert result["reason"] == "COMPLETE_CREATIVE_SOURCE_SCOPE_IDENTITY_INVALID" and service.calls == []


@pytest.mark.parametrize("code", ["SUBJECT_MAPPING_INVALID", "NATIVE_WINDOW_EXPIRED"])
def test_known_reference_binding_error_has_structured_stop_without_claim(tmp_path, code):
    def fail(request):
        raise references.ReferenceCompilerError(code, "explicit offline rejected reference fixture")
    result, service = run(tmp_path, enricher=fail)
    assert result["reason"] == "DIRECTOR_REFERENCE_BINDING_INVALID"
    assert result["events"][-1]["diagnostic"]["code"] == code
    assert service.calls == [] and not result["loop_state"]["director_events"]


@pytest.mark.parametrize("returned", [None, {}, {"request": None}, {"request": {"messages": None}}])
def test_malformed_enricher_result_is_stopped_without_claim(tmp_path, returned):
    result, service = run(tmp_path, enricher=lambda request: deepcopy(returned))
    assert result["reason"] == "DIRECTOR_REFERENCE_ENRICHER_RESULT_INVALID"
    assert service.calls == [] and not result["loop_state"]["director_events"]


def test_unknown_enricher_exception_does_not_start_or_repeat_a_request(tmp_path):
    def fail(request):
        raise RuntimeError("explicit offline builder failure")
    result, service = run(tmp_path, enricher=fail)
    assert result["reason"] == "DIRECTOR_REFERENCE_ENRICHER_FAILED" and service.calls == []
    assert not result["loop_state"]["director_events"]


@pytest.mark.parametrize("changed", [
    {"brief": {"title": "另一个未冻结创作方向"}},
    {"reference_fulltext": "不同参考全文，原冻结输入没有这个内容"},
    {"production_preferences": {"emotional_tone": "另一个未冻结情绪"}},
])
def test_changed_frozen_context_stops_before_any_claim_or_invocation(tmp_path, changed):
    result, service = run(tmp_path, context_override=changed)
    assert result["reason"] == "COMPLETE_FROZEN_PRODUCTION_CONTEXT_BINDING_REQUIRED"
    assert service.calls == [] and not result["loop_state"]["director_events"]
    assert not result["loop_state"].get("stage_dispatch_events")


def test_frozen_context_proof_is_mandatory_without_claiming_513_reviewed_preferences(tmp_path):
    result, service = run(tmp_path, missing_context_proof=True)
    assert result["reason"] == "COMPLETE_FROZEN_PRODUCTION_CONTEXT_BINDING_REQUIRED" and service.calls == []
    ready, ready_service = run(tmp_path)
    assert ready["complete_text_handoff_ready"]
    inp = json.loads(ready_service.calls[0]["request"]["messages"][1]["content"])
    binding = inp["production_context_binding"]
    assert binding["binding_kind"] == "external_frozen_input_identity" and binding["prior_semantic_review_claim"] is False
    assert binding["production_context_sha256"] == flow.production_context_digest(inp["brief"],
        inp["reference_fulltext"], inp["production_preferences"])


@pytest.mark.parametrize("models", [
    {"writer": "deepseek-flash", "director": "deepseek-flash"},
    {"writer": "MiniMax-M3", "director": "MiniMax-M3"},
])
def test_registered_model_cannot_silently_change_frozen_role_assignment(tmp_path, models):
    result, service = run(tmp_path, models=models)
    assert result["reason"] == "MODEL_ROLE_ASSIGNMENT_DIFFERS_FROM_FROZEN_POLICY" and service.calls == []
    assert not result["loop_state"]["director_events"]


@pytest.mark.parametrize("field", ["model", "reference_fulltext"])
def test_invoke_mutation_cannot_change_preflighted_snapshot_or_earn_content_revision(tmp_path, field):
    def mutate(request):
        if field == "model":
            request["model"] = "unregistered-model-after-preflight"
        else:
            inp = json.loads(request["messages"][1]["content"])
            inp["reference_fulltext"] = "替换了冻结参考"
            request["messages"][1]["content"] = json.dumps(inp, ensure_ascii=False)
    result, service = run(tmp_path, mutate_request=mutate)
    assert result["reason"] == "DIRECTOR_RESULT_NOT_COMPLETE"
    assert service.directors == 1 and len(service.calls) == 1 and service.reviews == 0
    journal = result["loop_state"]["stage_dispatch_events"]
    claim, output = journal[0], journal[1]
    assert output["evidence"]["known_complete"] is False
    assert "REQUEST_CHANGED" in output["evidence"]["errors"]
    assert claim["request_sha256"] == claim["preflight"]["request_sha256"]
    assert claim["request_sha256"] != output["evidence"]["request_sha256"]
    restarted, second = run(tmp_path, state=result["loop_state"])
    assert restarted["reason"] == result["reason"] and second.calls == []


def fake_extra_grant(state):
    return loop.authorize_extra_candidate(state, {"authority": "explicit_user",
        "grant_id": "explicit_offline_fixture_grant_only", "user_quote": "合成测试授权，不代表任何真实调用许可",
        "additional_candidates": 1, "source_binding_sha256": state["source_binding_sha256"]})


def test_explicit_extra_grant_reopens_with_stop_summary_not_old_request_graph(tmp_path):
    stopped, first = run(tmp_path, "director_invalid", limit=1)
    assert stopped["reason"] == "INHERITED_DIRECTOR_ALLOWANCE_EXHAUSTED"
    original_terminal = deepcopy(stopped["loop_state"]["coordinator_terminal"])
    granted = fake_extra_grant(stopped["loop_state"])
    ready, second = run(tmp_path, state=granted)
    assert ready["complete_text_handoff_ready"]
    inputs = json.loads(second.calls[0]["request"]["messages"][1]["content"])
    diagnostics = inputs["known_complete_failure_diagnostics"]
    assert len(diagnostics) == 2
    summary, latest_feedback = diagnostics
    assert summary["previous_stop_summary"]["terminal_sha256"] == pipeline.digest(original_terminal)
    assert summary["previous_stop_summary"]["reason"] == stopped["reason"]
    assert latest_feedback["failed_complete_native_result"] == first.calls[0]["document_output"]
    assert "complete_previous_stop" not in summary
    forbidden = {"request", "messages", "receipt", "events", "response_payload", "full_current_script", "source_catalog"}
    def keys(value):
        if isinstance(value, dict):
            return set(value) | set().union(*(keys(row) for row in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(row) for row in value))
        return set()
    assert not keys(diagnostics) & forbidden
    assert ready["loop_state"]["coordinator_terminal_history"][-1] == original_terminal
    capacity = loop.candidate_capacity(ready["loop_state"])
    assert capacity["candidate_limit"] == capacity["attempts_including_claims"] == 2
    assert not ready["budget_reset"]


def test_extra_grant_after_window_exhaustion_keeps_only_latest_verified_native_feedback(tmp_path):
    stopped, first = run(tmp_path, "window", limit=1)
    assert stopped["reason"] == "INHERITED_DIRECTOR_ALLOWANCE_EXHAUSTED"
    ready, second = run(tmp_path, state=fake_extra_grant(stopped["loop_state"]))
    assert ready["complete_text_handoff_ready"]
    diagnostics = json.loads(second.calls[0]["request"]["messages"][1]["content"])["known_complete_failure_diagnostics"]
    assert len(diagnostics) == 2 and diagnostics[-1]["failure_code"] == loop.WINDOW_FAILURE
    assert diagnostics[-1]["failed_complete_native_result"] == first.calls[2]["document_output"]
    assert diagnostics[-1]["prior_complete_native_direction"] == first.calls[0]["document_output"]
    assert "request" not in diagnostics[-1] and "messages" not in diagnostics[-1]


def test_extra_grant_cannot_reopen_unknown_local_stop_or_reextract_old_full_history(tmp_path):
    stopped, first = run(tmp_path, "unknown", limit=1)
    terminal = deepcopy(stopped["loop_state"]["coordinator_terminal"])
    restarted, second = run(tmp_path, state=fake_extra_grant(stopped["loop_state"]))
    assert restarted["reason"] == "LOCAL_RESULT_NOT_COMPLETE" and second.calls == []
    assert restarted["loop_state"]["coordinator_terminal"] == terminal
