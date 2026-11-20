"""Recompute complete known endpoint failures offline; never submit or adopt."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

import pytest

from scripts import creative_resume_dispatch_v3 as runtime
from src.content_factory import creative_director_endpoint_contract_v4 as endpoint
from src.content_factory import creative_complete_production_pipeline_v4 as pipeline
from src.content_factory import creative_production_revision_loop_v3 as loop
from src.content_factory import creative_endpoint_revision_feedback_v5 as adapter
from src.content_factory.creative_endpoint_feedback_coordinator_v5 import EndpointFeedbackCoordinator
from src.content_factory import creative_complete_production_coordinator_v4 as original_coordinator
from tests.test_creative_complete_production_coordinator_v3 import fixture, receipt
from tests.test_creative_complete_production_coordinator_v4 import endpoints
from tests.test_creative_complete_production_coordinator_v4 import FakeService

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / "data/production_revisions/shared_full_production_20261012/capability_v5"


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("endpoint diagnostic repair tests cannot use a network")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def real_case(ordinal):
    path = next(REAL.glob(f"call_{ordinal}_whole_direction_*.json"))
    original = json.loads(path.read_text(encoding="utf-8"))
    evidence = loop.normalize_receipt(original)
    assert evidence["known_complete"] and evidence["status"] == "contract_rejected"
    inputs = evidence["actual_input"]
    return path, original, evidence, inputs["full_current_script"], inputs["shared_manifest"]


def feedback(evidence, *, code=loop.DIRECTOR_FAILURE):
    # Exact shape emitted by the frozen route_failure. This is offline prompt
    # material, without a claim, allowance change or newly forged service reply.
    return {"failure_code": code, "prior_complete_native_direction": deepcopy(evidence["native_document"]),
        "failed_complete_native_result": deepcopy(evidence["native_document"]),
        "diagnostic": {"validation_error": "historical generic error only"},
        "original_result_identity": {key: deepcopy(evidence[key]) for key in
            ("result_id", "request_sha256", "native_sha256", "receipt_sha256", "reported_tokens")},
        "instruction": "完整原生新计划；不拼接，不改变原句。"}


@pytest.mark.parametrize("ordinal,expected_ids", [(518, ["M004", "M011"]), (519, ["M004", "M011"]), (520, ["M006"])])
def test_actual_three_native_failures_get_exact_compact_diagnostics_without_mutation(ordinal, expected_ids):
    path, original, evidence, script, manifest = real_case(ordinal)
    before = path.read_bytes()
    native = deepcopy(evidence["native_document"])
    result = adapter.describe_endpoint_failure(native, script, manifest)
    assert result["code"] == "ENDPOINT_RANGE_OR_BUDGET_UNAVAILABLE"
    assert [row["segment_id"] for row in result["invalid_segments"]] == expected_ids
    assert result["native_sha256"] == evidence["native_sha256"]
    assert "native" not in result and "full_current_script" not in result
    assert native == evidence["native_document"]
    assert result["automatic_option_selected"] is False
    assert result["calls_authorized"] is False
    for row in result["invalid_segments"]:
        assert row["options_enumerated_only"] and not row["automatic_option_selected"]
        graph = endpoint.ranges.candidate_graph(script, manifest)
        legal = [candidate for candidate in graph["ranges"] if candidate["start_index"] == row["derived_start_index"]]
        assert [candidate["end_source_ref"] for candidate in row["legal_outgoing_from_derived_start"]] == [candidate["end_source_ref"] for candidate in legal]
        assert [candidate["budget_options"] for candidate in row["legal_outgoing_from_derived_start"]] == [candidate["budget_options"] for candidate in legal]
    assert path.read_bytes() == before
    assert hashlib.sha256(path.read_bytes()).hexdigest() == hashlib.sha256(before).hexdigest()


def test_520_wrong_tier_and_518_impossible_minimum_are_distinguished():
    _, _, evidence, script, manifest = real_case(520)
    row = adapter.describe_endpoint_failure(evidence["native_document"], script, manifest)["invalid_segments"][0]
    assert row["requested_budget_tier"] == "reaction"
    assert row["required_seconds_for_requested_tier"] == 15.227273
    assert row["legal_budget_tiers_for_selected_range"] == ["minimum", "natural"]
    assert not row["minimum_range_exceeds_provider_limit"]
    _, _, evidence, script, manifest = real_case(518)
    rows = adapter.describe_endpoint_failure(evidence["native_document"], script, manifest)["invalid_segments"]
    assert rows[0]["required_seconds_for_requested_tier"] == 15.530303
    assert rows[0]["legal_budget_tiers_for_selected_range"] == ["minimum"]
    assert rows[1]["required_seconds_for_minimum_tier"] == 16.663636
    assert rows[1]["minimum_range_exceeds_provider_limit"]
    assert rows[1]["legal_budget_tiers_for_selected_range"] == []
    assert rows[1]["legal_outgoing_from_derived_start"]


def test_frozen_runtime_really_saves_detail_from_original_response_document(tmp_path):
    _, original, evidence, script, manifest = real_case(520)
    rt = runtime.ContinuationRuntime(ROOT, tmp_path, [],
        {"calls_started": 0, "reported_tokens": 0}, {})
    copied = deepcopy(original)
    validation = adapter.wrap_endpoint_validator(
        lambda native: endpoint.compile_direction(native, script, manifest), script, manifest)
    result = rt._validate_output(copied, original["request"], validation)
    detail = result["validation_error"]["detail"]
    assert result["status"] == "contract_rejected"
    assert result["document_output"] == evidence["native_document"]
    assert result["response_text"] == original["response_text"]
    assert detail["native_sha256"] == evidence["native_sha256"]
    assert detail["invalid_segments"][0]["segment_id"] == "M006"
    assert result["failure"]["code"] == "ENDPOINT_RANGE_OR_BUDGET_UNAVAILABLE"
    assert original["validation_error"].get("detail", {}) == {}  # Old immutable receipt untouched.


def test_known_feedback_keeps_complete_native_once_and_full_source_next_request():
    _, original, evidence, script, manifest = real_case(520)
    old_feedback = feedback(evidence)
    saved = deepcopy(old_feedback)
    enriched = adapter.enrich_director_revision_input(old_feedback, script, manifest, result_evidence=evidence)
    assert old_feedback == saved
    assert enriched["failed_complete_native_result"] == evidence["native_document"]
    assert "prior_complete_native_direction" not in enriched
    assert enriched["prior_complete_native_direction_sha256"] == evidence["native_sha256"]
    assert enriched["prior_direction_and_failed_result_are_same_native_identity"]
    assert enriched["original_result_identity"] == old_feedback["original_result_identity"]
    assert enriched["diagnostic"]["endpoint_contract_diagnostic"]["invalid_segments"][0]["segment_id"] == "M006"
    inp = deepcopy(evidence["actual_input"])
    inp["known_complete_failure_diagnostics"] = [enriched]
    next_request = pipeline.build_request("whole_direction", inp,
        pipeline.whole_direction_schema(script, manifest), "MiniMax-M3")
    actual = json.loads(next_request["messages"][1]["content"])
    assert actual["full_current_script"] == script
    assert actual["shared_manifest"] == manifest
    assert actual["reference_fulltext"] == evidence["actual_input"]["reference_fulltext"]
    assert actual["planned_initial_state"] == evidence["actual_input"]["planned_initial_state"]
    latest = actual["known_complete_failure_diagnostics"][0]
    assert latest["failed_complete_native_result"] == evidence["native_document"]
    assert latest["diagnostic"]["source_input_sha256"] == evidence["actual_input_sha256"]
    assert latest["endpoint_feedback_adapter"]["calls_authorized"] is False
    assert original["document_output"] == evidence["native_document"]


@pytest.mark.parametrize("changed", ["native", "identity", "native_sha256", "source_script", "source_manifest", "actual_input_sha256", "request_input"])
def test_changed_original_identity_or_source_cannot_earn_feedback(changed):
    _, _, evidence, script, manifest = real_case(520)
    old_feedback = feedback(evidence)
    if changed == "native": old_feedback["failed_complete_native_result"]["segments"][0]["observation"] += " changed"
    elif changed == "identity": old_feedback["original_result_identity"]["result_id"] = "different"
    elif changed == "native_sha256": evidence["native_sha256"] = "0" * 64
    elif changed == "source_script": script["title"] += " changed"
    elif changed == "source_manifest": manifest["actors"][0]["appearance"] = "changed"
    elif changed == "actual_input_sha256": evidence["actual_input_sha256"] = "0" * 64
    else:
        evidence["actual_input"]["reference_fulltext"] += " changed"
        evidence["actual_input_sha256"] = pipeline.digest(evidence["actual_input"])
    with pytest.raises(adapter.EndpointFeedbackError) as error:
        adapter.enrich_director_revision_input(old_feedback, script, manifest, result_evidence=evidence)
    assert error.value.code in {"ENDPOINT_NATIVE_RESULT_IDENTITY_CHANGED", "ENDPOINT_SOURCE_INPUT_CHANGED"}


@pytest.mark.parametrize("mode", ["unknown", "usage_unknown", "truncated", "missing_tool"])
def test_unknown_or_incomplete_results_never_become_director_content_feedback(mode):
    _, original, _, script, manifest = real_case(520)
    if mode == "unknown": original["response_metadata"]["http_status_code"] = None
    elif mode == "usage_unknown": original["response_metadata"]["total_tokens"] = None
    elif mode == "truncated": original["response_metadata"]["finish_reason"] = "length"
    else: original["response_payload"]["choices"][0]["message"]["tool_calls"] = []
    evidence = loop.normalize_receipt(original)
    with pytest.raises(adapter.EndpointFeedbackError) as error:
        adapter.enrich_director_revision_input(feedback(evidence), script, manifest, result_evidence=evidence)
    assert error.value.code == "ENDPOINT_RESULT_NOT_COMPLETE"


@pytest.mark.parametrize("failure_code", [loop.WINDOW_FAILURE, loop.REVIEW_FAILURE])
def test_local_and_full_review_feedback_remain_exact_and_keep_distinct_whole_native(failure_code):
    _, _, evidence, script, manifest = real_case(520)
    old = feedback(evidence, code=failure_code)
    old["failed_complete_native_result"] = {"explicit_fake_local_or_review": True}
    result = adapter.enrich_director_revision_input(old, script, manifest)
    assert result == old and result is not old
    assert result["prior_complete_native_direction"] == evidence["native_document"]


def test_legal_validator_return_is_exact_and_non_endpoint_failures_are_not_wrapped(tmp_path):
    script, manifest, _, direction, *_ = fixture(tmp_path)
    native = endpoints(direction, script, manifest)
    original = deepcopy(native)
    expected = endpoint.compile_direction(native, script, manifest)
    wrapped = adapter.wrap_endpoint_validator(lambda raw: endpoint.compile_direction(raw, script, manifest), script, manifest)
    assert wrapped(native) == expected and native == original
    diagnostic = adapter.describe_endpoint_failure(native, script, manifest)
    assert diagnostic["status"] == "endpoint_numeric_contract_valid" and not diagnostic["invalid_segments"]
    failure = ValueError("not an endpoint failure")
    def other(_): raise failure
    with pytest.raises(ValueError) as caught:
        adapter.wrap_endpoint_validator(other, script, manifest)(native)
    assert caught.value is failure


def test_stale_endpoint_exception_diagnostic_is_rejected_not_repackaged():
    _, _, evidence, script, manifest = real_case(520)
    native = evidence["native_document"]
    diagnostic = endpoint.audit_endpoint_choices(native, script, manifest)
    diagnostic["native_sha256"] = "0" * 64
    def stale(_):
        raise endpoint.EndpointContractError("ENDPOINT_RANGE_OR_BUDGET_UNAVAILABLE", "stale", diagnostic)
    with pytest.raises(adapter.EndpointFeedbackError) as error:
        adapter.wrap_endpoint_validator(stale, script, manifest)(native)
    assert error.value.code == "ENDPOINT_DIAGNOSTIC_IDENTITY_CHANGED"


def test_subclass_actual_call_routes_runtime_detail_into_latest_complete_next_input(tmp_path):
    _, original, evidence, script, manifest = real_case(520)
    request = original["request"]
    rt = runtime.ContinuationRuntime(ROOT, tmp_path, [], {"calls_started": 0, "reported_tokens": 0}, {})
    saved = []
    def invoke(label, outgoing, validate):
        assert outgoing == request
        copied = deepcopy(original)
        copied["label"] = label
        return rt._validate_output(copied, outgoing, validate)
    coordinator = EndpointFeedbackCoordinator(invoke=invoke, persist_state=saved.append,
        verify_frozen_source=lambda: None, opening_context_builder=lambda *args: None,
        models={"writer": "MiniMax-M3", "director": "deepseek-flash"})
    # Pure synthetic state exists only to exercise route construction. Real7/7
    # capacity is separately tested below and is never enlarged on disk.
    state = loop.initial_loop_state([], evidence["source_binding_sha256"], default_limit=1,
        stable_scope_material={"full_current_script": script, "shared_manifest": manifest,
            "planned_initial_state": evidence["actual_input"]["planned_initial_state"]})
    called, normalized = coordinator._call("offline_endpoint_detail", request,
        lambda raw: endpoint.compile_direction(raw, script, manifest), state)
    assert normalized["known_complete"] and called["validation_error"]["detail"]["invalid_segments"][0]["segment_id"] == "M006"
    route = loop.route_failure(state, loop.DIRECTOR_FAILURE, normalized, normalized["native_document"], diagnostic={"validation_error": "generic old path"})
    assert route["action"] == "whole_direction_revision"
    diagnostics = coordinator._latest_revision_diagnostics([{"previous_stop_summary": {"reason": "synthetic"}}, {"obsolete": True}], route["revision_input"])
    assert len(diagnostics) == 2 and diagnostics[0]["previous_stop_summary"]["reason"] == "synthetic"
    assert diagnostics[-1]["diagnostic"]["endpoint_contract_diagnostic"]["invalid_segments"][0]["segment_id"] == "M006"
    assert "prior_complete_native_direction" not in diagnostics[-1]
    assert saved and state["stage_dispatch_events"][-1]["event"] == "result"


def test_actual_seven_of_seven_stops_before_invocation_and_remains_unchanged():
    path = REAL / "LOOP_STATE.json"
    original_bytes = path.read_bytes()
    state = json.loads(original_bytes)
    material = state["stable_scope_material"]
    calls = []
    def never(*args):
        calls.append(args)
        raise AssertionError("actual exhausted director task cannot invoke")
    coordinator = EndpointFeedbackCoordinator(invoke=never, persist_state=lambda value: None,
        verify_frozen_source=lambda: None, opening_context_builder=never,
        models={"writer": "MiniMax-M3", "director": "deepseek-flash"})
    # Existing binding matches the frozen context rather than claiming new text
    # approval; only the exhausted gate is exercised, with no paid client.
    _, _, evidence, _, _ = real_case(520)
    inputs = evidence["actual_input"]
    binding = {"writer_ordinal": 512, "review_ordinal": 513,
        "script_sha256": pipeline.digest(material["full_current_script"]), "machine_text_review_passed": True,
        "production_context_sha256": original_coordinator.production_context_digest(inputs["brief"], inputs["reference_fulltext"], inputs["production_preferences"])}
    result = coordinator.run(script=material["full_current_script"], manifest=material["shared_manifest"],
        initial=material["planned_initial_state"], reference_fulltext=inputs["reference_fulltext"],
        preferences=inputs["production_preferences"], brief=inputs["brief"], source_review_binding=binding, state=state)
    assert result["reason"] == "INHERITED_DIRECTOR_ALLOWANCE_EXHAUSTED" and not calls
    capacity = loop.candidate_capacity(result["loop_state"])
    assert capacity["candidate_limit"] == capacity["attempts_including_claims"] == 7
    assert capacity["remaining"] == 0 and path.read_bytes() == original_bytes


@pytest.mark.parametrize("invalid", ["wrong_type", "missing_field"])
def test_known_complete_non_endpoint_schema_failure_keeps_original_feedback_route(tmp_path, invalid):
    script, manifest, _, direction, *_ = fixture(tmp_path)
    native = endpoints(direction, script, manifest)
    if invalid == "wrong_type": native["whole_observation"] = []
    else: native.pop("whole_observation")
    inputs = endpoint.build_director_input(script, manifest,
        endpoint.local._frozen_initial(manifest), "合成参考", {})
    request = endpoint.build_director_request(inputs, script, manifest)
    original = receipt("offline_schema_failure", request, native, 100, "contract_rejected")
    evidence = loop.normalize_receipt(original)
    assert evidence["known_complete"]
    old_feedback = feedback(evidence)
    enriched = adapter.enrich_director_revision_input(old_feedback, script, manifest, result_evidence=evidence)
    assert enriched == old_feedback and enriched is not old_feedback
    assert "endpoint_feedback_adapter" not in enriched
    wrapped = adapter.wrap_endpoint_validator(lambda value: endpoint.compile_direction(value, script, manifest), script, manifest)
    with pytest.raises(ValueError) as caught:
        wrapped(native)
    assert not isinstance(caught.value, adapter.EndpointFeedbackError)


def test_resumed_terminal_latest_endpoint_feedback_is_enriched_without_state_or_grant_changes():
    path = REAL / "LOOP_STATE.json"
    before = path.read_bytes()
    original_state = json.loads(before)
    # Explicitly synthetic in-memory grant enables only the context-builder
    # branch. No new coordinator run, claim, client or actual authorization file.
    state = loop.authorize_extra_candidate(original_state, {"authority": "explicit_user",
        "grant_id": "offline_context_builder_fixture_only", "additional_candidates": 1,
        "user_quote": "合成测试夹具，非真实调用许可",
        "source_binding_sha256": original_state["source_binding_sha256"]})
    prior = deepcopy(state)
    coordinator = EndpointFeedbackCoordinator(invoke=lambda *args: pytest.fail("no invocation"),
        persist_state=lambda value: pytest.fail("no state persistence"), verify_frozen_source=lambda: None,
        opening_context_builder=lambda *args: None,
        models={"writer": "MiniMax-M3", "director": "deepseek-flash"})
    summary, enriched = coordinator._terminal_prompt_context(state["coordinator_terminal"], state)
    assert summary["previous_stop_summary"]["reason"] == "INHERITED_DIRECTOR_ALLOWANCE_EXHAUSTED"
    assert enriched["original_result_identity"]["result_id"] == "520"
    assert enriched["diagnostic"]["endpoint_contract_diagnostic"]["invalid_segments"][0]["segment_id"] == "M006"
    assert "prior_complete_native_direction" not in enriched
    assert enriched["prior_direction_and_failed_result_are_same_native_identity"]
    assert state == prior and path.read_bytes() == before


@pytest.mark.parametrize("first_failure", ["endpoint", "ordinary_schema"])
def test_full_subclass_run_delivers_correct_feedback_to_second_actual_fake_invocation(tmp_path, first_failure):
    script, manifest, initial, direction, performances, brief, opening = fixture(tmp_path)
    native = endpoints(direction, script, manifest)
    class Service(FakeService):
        def invoke(self, label, request, validate):
            if first_failure == "ordinary_schema" and request["stage"] == "whole_direction" and self.directors == 0:
                saved = deepcopy(self.direction)
                self.direction["whole_observation"] = []
                try:
                    return super().invoke(label, request, validate)
                finally:
                    self.direction = saved
            return super().invoke(label, request, validate)
    service = Service(native, performances, "director_invalid" if first_failure == "endpoint" else None)
    coordinator = EndpointFeedbackCoordinator(invoke=service.invoke, persist_state=service.save,
        verify_frozen_source=service.guard, opening_context_builder=opening,
        models={"writer": "MiniMax-M3", "director": "deepseek-flash"})
    state = loop.initial_loop_state([], "a" * 64, default_limit=2,
        stable_scope_material={"full_current_script": script, "shared_manifest": manifest,
            "planned_initial_state": initial})
    reference = "完整合成测试参考，不是正式作品质量证明"
    binding = {"writer_ordinal": 1, "review_ordinal": 2, "script_sha256": pipeline.digest(script),
        "machine_text_review_passed": True,
        "production_context_sha256": original_coordinator.production_context_digest(brief, reference, {})}
    result = coordinator.run(script=script, manifest=manifest, initial=initial,
        reference_fulltext=reference, preferences={}, brief=brief,
        source_review_binding=binding, state=state, scope={"offline_fixture_only": True})
    assert result["complete_text_handoff_ready"] and service.directors == 2
    requests = [row["request"] for row in service.calls if row["request"]["stage"] == "whole_direction"]
    actual = json.loads(requests[1]["messages"][1]["content"])
    assert actual["full_current_script"] == script and actual["shared_manifest"] == manifest
    assert actual["reference_fulltext"] == reference and actual["planned_initial_state"] == initial
    latest = actual["known_complete_failure_diagnostics"][-1]
    assert latest["failed_complete_native_result"] == service.calls[0]["document_output"]
    if first_failure == "endpoint":
        detail = latest["diagnostic"]["endpoint_contract_diagnostic"]
        assert detail["invalid_segments"] and detail["code"] == "ENDPOINT_ORDER_INVALID"
        assert "legal_outgoing_from_derived_start" in detail["invalid_segments"][0]
        assert "prior_complete_native_direction" not in latest
    else:
        assert "endpoint_contract_diagnostic" not in latest["diagnostic"]
        assert latest["prior_complete_native_direction"] == latest["failed_complete_native_result"]
