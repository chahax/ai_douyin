"""Independent final-wire tests for pure workflow12 and original round_11."""
from copy import deepcopy
import hashlib
import json
import socket

from jsonschema import ValidationError
import pytest

from scripts.creative_m31_flash_role_clients_v1 import M31FlashRoleClients, expected_wire_request
from src.content_factory import creative_goal_context_workflow_v11 as old
from src.content_factory import creative_goal_context_workflow_v12 as workflow
from src.content_factory import creative_goal_revision_feedback_v1 as feedback
from tests.test_creative_goal_revision_feedback_v1 import ACTUAL, actual_inputs, read


@pytest.fixture(autouse=True)
def zero_dispatch(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("independent workflow12 verification is offline only")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(M31FlashRoleClients, "__init__", deny)


def occurrences(value, document):
    if type(value) is dict:
        return int(value == document) + sum(occurrences(child, document) for child in value.values())
    if type(value) is list:
        return sum(occurrences(child, document) for child in value)
    return 0


def check_final_request(prepared):
    payload = json.loads(prepared["request"]["messages"][1]["content"])
    manifest = prepared["manifest"]
    assert prepared["wire"] == expected_wire_request(prepared["request"])
    assert prepared["wire"]["tools"][0]["function"]["parameters"] == prepared["request"]["structured_schema"]
    assert prepared["request_sha256"] == workflow.digest(prepared["request"])
    assert prepared["request"]["input_provenance"]["context_manifest_sha256"] == workflow.digest(manifest)
    assert manifest["payload_identity"] == workflow.contexts._measure(payload)
    assert manifest["workflow_version"] == prepared["request"]["input_provenance"]["workflow_version"] == workflow.VERSION
    assert not prepared["dispatch_performed"] and prepared["sdk_max_retries"] == 0
    return payload


@pytest.mark.parametrize("qualified", [False, True])
def test_actual_raw_feedback_overflow_project_before_original_budget_and_final_hashes(qualified):
    inputs, goal, diagnostics, profile = actual_inputs()
    if qualified:
        from scripts import run_goal_context_text_production_v13 as producer
        diagnostics = producer.build_revision_diagnostics(goal)
    original_inputs = {**inputs, "previous_complete_document": goal, "revision_diagnostics": diagnostics}
    before = deepcopy(original_inputs)
    paths = [ACTUAL / "goals/native_01.json", ACTUAL / "goals/drama_native_audit_01.json",
             ACTUAL / "goals/drama_audit_decision_01.json", ACTUAL / "CALL_LEDGER.json", ACTUAL / "STATE.json"]
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    with pytest.raises(old.contexts.ContextError, match="exceeds explicit safety budget"):
        old.prepare_goal_request(original_inputs, profile)
    prepared = workflow.prepare_goal_request(original_inputs, profile)
    payload = check_final_request(prepared)
    assert original_inputs == before
    assert payload["previous_complete_document"] == goal and occurrences(payload, goal) == 1
    assert payload["reference_fulltext"] == inputs["reference_fulltext"]
    assert workflow.contexts._reference_occurrences(payload, inputs["reference_fulltext"]) == 1
    assert prepared["manifest"]["context_policy"] == {"max_payload_characters": 100_000, "max_payload_utf8_bytes": 300_000}
    projection = prepared["manifest"]["revision_feedback_projection"]
    assert projection["original_diagnostics"]["sha256"] == workflow.digest(diagnostics)
    assert projection["projected_diagnostics"]["sha256"] == workflow.digest(payload["revision_diagnostics"])
    assert prepared["manifest"]["original_input_identity"] == workflow.contexts._measure(original_inputs)
    assert payload["revision_diagnostics"]["complete_same_source_goal_audits"][1]["findings"] == diagnostics["complete_same_source_goal_audits"][1]["findings"]
    assert payload["revision_diagnostics"]["complete_same_source_goal_audits"][1]["accepted"] is False
    if qualified:
        assert payload["revision_diagnostics"]["verified_pipeline_diagnosis"] == diagnostics["verified_pipeline_diagnosis"]
        assert payload["revision_diagnostics"]["prior_drama_failure_disputed_not_adopted_as_truth"] is True
    assert hashes == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def test_explicit_stricter_cap_applies_after_projection_and_rejects_without_source_truncation():
    inputs, goal, diagnostics, profile = actual_inputs()
    revision = {**inputs, "previous_complete_document": goal, "revision_diagnostics": diagnostics,
                "context_policy": {"max_payload_characters": 80_000, "max_payload_utf8_bytes": 120_000}}
    prepared = workflow.prepare_goal_request(revision, profile)
    assert prepared["manifest"]["context_policy"] == revision["context_policy"]
    check_final_request(prepared)
    revision["context_policy"] = {"max_payload_characters": 10_000, "max_payload_utf8_bytes": 30_000}
    before = deepcopy(revision)
    with pytest.raises(workflow.contexts.ContextError, match="exceeds explicit safety budget"):
        workflow.prepare_goal_request(revision, profile)
    assert revision == before


def test_optional_local_feedback_artifact_is_verified_but_excluded_from_provider_payload(tmp_path):
    inputs, goal, diagnostics, profile = actual_inputs()
    p = tmp_path / "original.json"
    p.write_text(json.dumps(diagnostics, ensure_ascii=False), encoding="utf-8")
    revision = {**inputs, "previous_complete_document": goal, "revision_diagnostics": diagnostics,
                "goal_revision_feedback_evidence_path": str(p)}
    prepared = workflow.prepare_goal_request(revision, profile)
    payload = check_final_request(prepared)
    assert "goal_revision_feedback_evidence_path" not in payload
    assert prepared["manifest"]["revision_feedback_projection"]["original_artifact"]["local_json_verified"]
    assert prepared["manifest"]["revision_feedback_projection"]["original_artifact"]["local_path"] == str(p.resolve())
    p.write_text('{"changed":true}', encoding="utf-8")
    with pytest.raises(feedback.FeedbackProjectionError, match="differ"):
        workflow.prepare_goal_request(revision, profile)


def test_new_drama_schema_is_v10_and_original570_is_never_converted_or_accepted():
    inputs, goal, _, profile = actual_inputs()
    native570 = read(ACTUAL / "goals/drama_native_audit_01.json")
    before = deepcopy(native570)
    prepared = workflow.prepare_goal_drama_audit_request(inputs, profile, goal)
    payload = check_final_request(prepared)
    schema = prepared["request"]["structured_schema"]
    assert schema["properties"]["schema"]["const"] == workflow.DRAMA_AUDIT_VERSION == "creative_goal_drama_audit/v10"
    assert "closed_scope_findings" in schema["required"]
    assert payload["native_goal_document"] == goal and occurrences(payload, goal) == 1
    context_sha = schema["properties"]["audit_context_sha256"]["const"]
    with pytest.raises(ValidationError):
        workflow.validate_goal_drama_audit(native570, goal, context_sha256=context_sha)
    assert native570 == before
    assert native570["schema"] != workflow.DRAMA_AUDIT_VERSION
