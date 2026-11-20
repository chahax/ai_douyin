"""Offline preservation, provenance and real round_11 context measurements."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

import pytest

from scripts.creative_m31_flash_role_clients_v1 import M31FlashRoleClients
from src.content_factory import creative_goal_context_workflow_v11 as frozen
from src.content_factory import creative_goal_revision_feedback_v1 as feedback

PROJECT = Path(__file__).resolve().parents[1]
ACTUAL = PROJECT / "data/production_trials/goal_context_text_production_20261013/round_11"


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("feedback preparation may not create clients or contact providers")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(M31FlashRoleClients, "__init__", deny)


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def decision(*, accepted=True, findings=None, uncertainties=None):
    return {"valid": True, "accepted": accepted, "audit_kind": "drama",
        "findings": findings or [], "uncertainties": uncertainties or [],
        "native_goal_sha256": "goal", "audit_sha256": "audit",
        "audit_context_sha256": "context", "receipt_sha256": "receipt", "schema": "original/schema",
        "citations": {"check": [{"path": "whole_plan.beats.0.event", "quote": "原生动作完整"}]},
        "counterevidence_citations": {"check": []},
        "commitment_check_evidence": {"id": {"quote": "重复引用"}},
        "commitment_usage_catalog": {"id": {"usages": ["b1"]}},
        "scope_observation_evidence": {"b1": {"operated_props": []}},
        "undeclared_scope_observations": [], "future_field": {"original": "不可推断或删掉"}}


def native_row(status):
    return {"status": status, "reason": "原生原因，不改句。", "required_revision": "完整新计划需解决关系",
            "evidence_refs": ["G001"], "counterevidence_refs": ["C:CC_PHOTO_TIMING"],
            "counterexample_analysis": "原句比较完整保留", "evidence": [{"quote": "原证据完整"}]}


def test_exact_failed_unknown_rows_and_separate_pipeline_diagnosis_are_preserved():
    d = {"complete_same_source_goal_audits": [decision(), decision(accepted=False,
         findings=[native_row("fail")], uncertainties=[native_row("unknown")])],
         "verified_pipeline_diagnosis": {"classification": "review_self_contradiction",
              "original_report_authority_disputed": True, "exactquotes": ["未改的C/G原句"]},
         "unrecognized_diagnosis": {"status": "unknown", "reason": "不能删未知字段"}}
    before = deepcopy(d)
    result = feedback.project_goal_revision_feedback(d)
    projected, manifest = result["projected_diagnostics"], result["projection_manifest"]
    assert d == before
    assert projected["complete_same_source_goal_audits"][1]["findings"] == d["complete_same_source_goal_audits"][1]["findings"]
    assert projected["complete_same_source_goal_audits"][1]["uncertainties"] == d["complete_same_source_goal_audits"][1]["uncertainties"]
    assert projected["verified_pipeline_diagnosis"] == d["verified_pipeline_diagnosis"]
    assert projected["unrecognized_diagnosis"] == d["unrecognized_diagnosis"]
    assert len(manifest["preserved_unresolved_rows"]) == 3
    assert not manifest["finding_semantic_authority_decided"]
    for index, original in enumerate(d["complete_same_source_goal_audits"]):
        output = projected["complete_same_source_goal_audits"][index]
        for key in set(original) - set(feedback.COMPILED_TABLES):
            assert output[key] == original[key]


def test_deterministic_canonical_identity_and_no_false_local_file_claim():
    d = {"complete_same_source_goal_audits": [decision()]}
    result = feedback.project_goal_revision_feedback(d)
    reordered = {"complete_same_source_goal_audits": [dict(reversed(list(decision().items())))]}
    assert feedback.project_goal_revision_feedback(reordered) == result
    manifest = result["projection_manifest"]
    assert manifest["original_artifact"]["local_binding_pending"]
    assert manifest["original_artifact"]["local_path"] is None
    assert not manifest["original_artifact"]["local_json_verified"]
    for row in manifest["externalized_tables"]:
        original = feedback._resolve_pointer(d, row["json_pointer"])
        reference = feedback._resolve_pointer(result["projected_diagnostics"], row["json_pointer"])
        assert row["sha256"] == reference["original_value_sha256"] == feedback.digest(original)
        assert reference["source_status"] == "passed"
        assert reference["local_binding_pending"]
    assert not manifest["dispatch_performed"]


def test_optional_original_artifact_is_read_only_verified_and_bound(tmp_path):
    d = {"complete_same_source_goal_audit": decision()}
    path = tmp_path / "diagnostics.json"
    path.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    raw = path.read_bytes()
    result = feedback.project_goal_revision_feedback(d, original_diagnostics_path=path)
    artifact = result["projection_manifest"]["original_artifact"]
    assert artifact == {"canonical_json_sha256": feedback.digest(d), "local_path": str(path.resolve()),
        "local_file_sha256": hashlib.sha256(raw).hexdigest(), "local_json_verified": True,
        "local_binding_pending": False}
    assert path.read_bytes() == raw
    assert all(feedback._resolve_pointer(result["projected_diagnostics"], item["json_pointer"])["local_path"]
               == str(path.resolve()) for item in result["projection_manifest"]["externalized_tables"])


@pytest.mark.parametrize("content", ['{"different":true}', '{"duplicate":1,"duplicate":1}', '{"bad":NaN}'])
def test_changed_or_noncanonical_original_artifact_rejected(tmp_path, content):
    path = tmp_path / "changed.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(feedback.FeedbackProjectionError):
        feedback.project_goal_revision_feedback({"errors": []}, original_diagnostics_path=path)


@pytest.mark.parametrize("unsafe", [native_row("fail"), native_row("unknown"), {"errors": ["unresolved"]},
    {"declared_character_id": None}, {"declared_prop_id": None}])
def test_unresolved_or_undeclared_item_in_compiled_table_keeps_entire_table(unsafe):
    audit = decision()
    audit["citations"]["new_table_shape"] = deepcopy(unsafe)
    d = {"complete_same_source_goal_audits": [audit]}
    result = feedback.project_goal_revision_feedback(d)
    assert result["projected_diagnostics"]["complete_same_source_goal_audits"][0]["citations"] == audit["citations"]
    assert any(row["json_pointer"].endswith("/citations")
               for row in result["projection_manifest"]["retained_tables_or_decisions"])


@pytest.mark.parametrize("field,value", [("complete_same_source_goal_audits", [{"status": "unknown", "errors": ["missing"]}]),
    ("complete_same_source_goal_audits", None), ("transport_failure", {"failure": "known_complete_schema_rejection"})])
def test_unrecognized_incomplete_and_non_audit_feedback_are_exact_passthrough(field, value):
    d = {field: value}
    result = feedback.project_goal_revision_feedback(d)
    assert result["projected_diagnostics"] == d
    assert result["projection_manifest"]["externalized_tables"] == []


@pytest.mark.parametrize("level", ["diagnostic", "decision"])
def test_top_level_fail_unknown_parent_is_an_original_row_and_preserved_whole(level):
    d = {"complete_same_source_goal_audits": [decision()]}
    target = d if level == "diagnostic" else d["complete_same_source_goal_audits"][0]
    target["status"] = "unknown"
    result = feedback.project_goal_revision_feedback(d)
    assert result["projected_diagnostics"] == d
    assert not result["projection_manifest"]["externalized_tables"]


def test_unknown_compiled_table_shape_is_not_dropped():
    d = {"complete_same_source_goal_audits": [decision()]}
    d["complete_same_source_goal_audits"][0]["citations"] = "原未知表，不按已知结构省略"
    result = feedback.project_goal_revision_feedback(d)
    assert result["projected_diagnostics"]["complete_same_source_goal_audits"][0]["citations"] == d["complete_same_source_goal_audits"][0]["citations"]


@pytest.mark.parametrize("value", [{}, [], {1: "not JSON key"}, {"bad": float("nan")}, {"bad": (1, 2)}])
def test_invalid_json_input_rejected(value):
    with pytest.raises(feedback.FeedbackProjectionError):
        feedback.project_goal_revision_feedback(value)


def actual_inputs():
    if not ACTUAL.exists():
        pytest.skip("read-only historical round_11 fixture not present in this checkout")
    inputs = read(ACTUAL / "INPUTS.json")
    goal = read(ACTUAL / "goals/native_01.json")
    diagnostics = {"complete_same_source_goal_audits": [read(ACTUAL / "goals" / name)
        for name in ("source_audit_decision_01.json", "drama_audit_decision_01.json")]}
    inputs = {key: value for key, value in inputs.items()
        if key not in ("previous_complete_document", "revision_diagnostics", "revision_requirements",
                       "complete_script_feasibility_diagnostics", "fresh_reconception_context")}
    profile = read(PROJECT / "config/creative_goal_context_model_profile_v3.json")
    return inputs, goal, diagnostics, profile


@pytest.mark.parametrize("explicit_policy", [None, {"max_payload_characters": 80_000, "max_payload_utf8_bytes": 120_000}])
def test_actual_568_570_original_overflows_projected_fits_without_source_changes(explicit_policy):
    inputs, goal, diagnostics, profile = actual_inputs()
    paths = [ACTUAL / "INPUTS.json", ACTUAL / "EXECUTION_ERROR.json", ACTUAL / "STATE.json",
             ACTUAL / "CALL_LEDGER.json", *sorted((ACTUAL / "goals").glob("*.json")),
             *sorted(ACTUAL.glob("call_56*.json")), ACTUAL / "call_570_goal_drama_audit_01.json"]
    before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    if explicit_policy is not None:
        inputs["context_policy"] = explicit_policy
    revision = {**inputs, "previous_complete_document": deepcopy(goal), "revision_diagnostics": deepcopy(diagnostics)}
    original_copy = deepcopy(revision)
    with pytest.raises(frozen.contexts.ContextError, match="exceeds explicit safety budget"):
        frozen.prepare_goal_request(revision, profile)
    result = feedback.project_goal_revision_feedback(diagnostics)
    projected = {**revision, "revision_diagnostics": result["projected_diagnostics"]}
    prepared = frozen.prepare_goal_request(projected, profile)
    payload = json.loads(prepared["request"]["messages"][1]["content"])
    policy = prepared["manifest"]["context_policy"]
    assert policy == (explicit_policy or {"max_payload_characters": 100_000, "max_payload_utf8_bytes": 300_000})
    assert prepared["manifest"]["payload_identity"]["characters"] <= policy["max_payload_characters"]
    assert prepared["manifest"]["payload_identity"]["utf8_bytes"] <= policy["max_payload_utf8_bytes"]
    assert payload["previous_complete_document"] == goal
    def occurrences(value):
        if type(value) is dict:
            return int(value == goal) + sum(occurrences(child) for child in value.values())
        if type(value) is list:
            return sum(occurrences(child) for child in value)
        return 0
    assert occurrences(payload) == 1
    assert payload["reference_fulltext"] == inputs["reference_fulltext"]
    assert frozen.contexts._reference_occurrences(payload, inputs["reference_fulltext"]) == 1
    assert payload["revision_diagnostics"]["complete_same_source_goal_audits"][1]["findings"] == diagnostics["complete_same_source_goal_audits"][1]["findings"]
    assert revision == original_copy
    assert not prepared["dispatch_performed"]
    assert {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths} == before
