"""Original607 evidence and full-source revision preparation; offline only."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

import pytest

from scripts import creative_deepseek_strict_role_clients_v2 as strict_clients
from scripts.creative_m31_flash_role_clients_v1 import M31FlashRoleClients
from src.content_factory import creative_known_source_report_revision_v1 as revision
from src.content_factory import creative_goal_context_workflow_v19 as workflow

PROJECT = Path(__file__).resolve().parents[1]
ROUND20 = PROJECT / "data/production_trials/goal_context_text_production_20261013/round_20"


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs): raise AssertionError("pure source revision tests cannot contact providers or create clients")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(M31FlashRoleClients, "__init__", deny)


@pytest.fixture
def original607():
    receipt = read(ROUND20 / "call_607_goal_source_audit_00.json")
    raw = (ROUND20 / "call_evidence/call_607/response_body.raw").read_bytes()
    goal = read(ROUND20 / "INHERITED_NATIVE_GOAL.json")
    payload = json.loads(receipt["request"]["messages"][1]["content"])
    return receipt, raw, goal, payload


def verify(case):
    receipt, raw, goal, payload = case
    return revision.verify_known_source_report(receipt, raw_response_body=raw, native_goal=goal, source_payload=payload)


def body_change(case, mutate):
    receipt, _, goal, payload = case
    body = deepcopy(receipt["response_payload"])
    mutate(body)
    raw = json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    receipt["response_payload"] = body
    receipt["response_metadata"]["raw_body_sha256"] = hashlib.sha256(raw).hexdigest()
    return receipt, raw, goal, payload


def test_original607_bytes_and_full_report_bind_exact_two_actual_legal_branch_errors(original607):
    before = deepcopy(original607)
    proof = verify(original607)
    assert proof["known_complete_result"] and not proof["original_report_modified"]
    assert not proof["semantic_approval_created"] and not proof["durable_file_or_lineage_verified_by_this_pure_function"]
    assert proof["original_usage"] == {"prompt_tokens": 33848, "completion_tokens": 17757, "total_tokens": 51605}
    assert proof["original_native_report_sha256"] == revision.digest(original607[0]["output"])
    errors = proof["schema_errors"]
    assert len(errors) == 2
    assert {tuple(error["path"]) for error in errors} == {
        ("source_observations", 152, "usages", 0, "context_evidence", 0, "source_ref"),
        ("source_observations", 153, "usages", 0, "context_evidence", 0, "source_ref")}
    assert all(error["native_kind_branch"] == "legal_assertion" and error["validator"] == "enum"
               and error["actual_value"] == "G106" and "G106" not in error["validator_value"] for error in errors)
    assert all("kind" not in error["path"] and "additionalProperties" != error["validator"] for error in errors)
    assert original607 == before


@pytest.mark.parametrize("fault", ["status_unknown", "status_interface", "length", "stop", "incomplete", "http500", "http_unknown",
    "usage_missing", "usage_null", "usage_bool", "usage_float", "usage_negative", "usage_sum", "saved_usage_unknown",
    "request_sha", "goal_identity", "source_payload", "schema_widened", "provenance_identity", "report_changed",
    "response_text_changed", "response_id", "response_model", "raw_short", "saved_body_changed", "missing_tool",
    "multiple_tools", "wrong_tool", "schema_error_changed", "failure_changed", "approval", "retry"])
def test_unknown_truncated_incomplete_or_changed_original_evidence_is_ineligible(original607, fault):
    receipt, raw, goal, payload = original607
    if fault == "status_unknown": receipt["status"] = "outcome_unknown"
    elif fault == "status_interface": receipt["status"] = "interface_rejected"
    elif fault in ("length", "stop"): receipt["response_metadata"]["finish_reason"] = fault
    elif fault == "incomplete": receipt["response_metadata"]["response_body_complete"] = False
    elif fault in ("http500", "http_unknown"): receipt["response_metadata"]["http_status_code"] = 500 if fault == "http500" else None
    elif fault.startswith("usage_"):
        def mutate(body):
            if fault == "usage_missing": body.pop("usage")
            else: body["usage"]["total_tokens"] = {"usage_null": None, "usage_bool": True, "usage_float": 51605.0,
                "usage_negative": -1, "usage_sum": 51606}[fault]
        receipt, raw, goal, payload = body_change(original607, mutate)
    elif fault == "saved_usage_unknown": receipt["response_metadata"]["total_tokens"] = None
    elif fault == "request_sha": receipt["request_sha256"] = "0" * 64
    elif fault == "goal_identity": goal["whole_plan"]["premise"] += "changed"
    elif fault == "source_payload": payload["verified_legal_context"]["facts"][0]["paraphrase"] += "changed"
    elif fault == "schema_widened":
        receipt["request"]["structured_schema"]["$defs"]["current_actual_evidence"]["properties"]["source_ref"]["enum"].append("G106")
        receipt["request_sha256"] = revision.digest(receipt["request"])
    elif fault == "provenance_identity":
        receipt["request"]["input_provenance"]["source_context_sha256"] = "0" * 64
        receipt["request_sha256"] = revision.digest(receipt["request"])
    elif fault == "report_changed": receipt["output"]["source_observations"][0]["usages"] = []
    elif fault == "response_text_changed": receipt["response_text"] += " "
    elif fault == "response_id": receipt["response_metadata"]["response_id"] = "changed"
    elif fault == "response_model": receipt["response_metadata"]["response_model"] = "changed"
    elif fault == "raw_short": raw = raw[:-1]
    elif fault == "saved_body_changed": receipt["response_payload"]["id"] = "changed"
    elif fault in ("missing_tool", "multiple_tools", "wrong_tool"):
        def mutate(body):
            tools = body["choices"][0]["message"]["tool_calls"]
            if fault == "missing_tool": body["choices"][0]["message"].pop("tool_calls")
            elif fault == "multiple_tools": tools.append(deepcopy(tools[0]))
            else: tools[0]["function"]["name"] = "other_tool"
        receipt, raw, goal, payload = body_change(original607, mutate)
    elif fault == "schema_error_changed": receipt["validation_error"]["path"] = ["wrong"]
    elif fault == "failure_changed": receipt["failure"]["code"] = "REQUIRED_TOOL_MISSING"
    elif fault == "approval": receipt["semantic_approval"] = True
    else: receipt["automatic_retry"] = True
    with pytest.raises(revision.KnownSourceReportRevisionError):
        verify((receipt, raw, goal, payload))


@pytest.mark.parametrize("arguments", ['{"incomplete":', '{"schema":"one","schema":"two"}', '{"bad":NaN}', '[]'])
def test_tool_arguments_must_be_complete_unique_finite_native_object(original607, arguments):
    case = body_change(original607, lambda body: body["choices"][0]["message"]["tool_calls"][0]["function"].update(arguments=arguments))
    with pytest.raises(revision.KnownSourceReportRevisionError): verify(case)


def test_feedback_contains_full_original607_with_only_pending_semantic_and_downstream_hints(original607):
    receipt, raw, goal, payload = original607
    before = deepcopy(original607)
    questions = read(PROJECT / "data/qa/creative_known_source_report_revision_20261014/ROOT_607_SEMANTIC_REVIEW_QUESTIONS_v1.json")
    feedback = revision.build_source_report_revision_feedback(receipt, raw_response_body=raw, native_goal=goal, source_payload=payload,
        reviewer_checks=questions["reviewer_checks"], pending_downstream_risks=questions["pending_downstream_risks"])
    assert feedback["previous_complete_source_report"] == receipt["output"]
    assert len(feedback["previous_complete_source_report"]["source_observations"]) == 178
    assert len(feedback["schema_errors"]) == 2 and "schema_errors" not in feedback["proof"]
    assert len(feedback["reviewer_checks"]) == 2
    catalog = workflow.source_audit.build_evidence_catalog(goal)
    for hint in feedback["reviewer_checks"]:
        assert hint["source_ref"] in ("G047", "G108") and hint["original_quote"] == catalog[hint["source_ref"]]["quote"]
        assert hint["semantic_status"] == "pending_model_review" and not hint["local_verdict_created"]
    risk = feedback["pending_downstream_risks"][0]
    assert risk["status"] == "pending_model_verification" and risk["owner_stages"] == ["drama", "physical"]
    assert not risk["source_legal_failure_created"] and not risk["new_hard_schema_check_created"]
    assert not risk["human_adoption_created"] and not risk["native_goal_modified"]
    assert {row["source_ref"] for row in risk["evidence"]} == {"G121", "G062", "G078", "G104", "G107"}
    assert feedback["reviewer_checks"] == questions["reviewer_checks"]
    assert feedback["pending_downstream_risks"] == questions["pending_downstream_risks"]
    assert not feedback["local_semantic_verdict_created"] and not feedback["human_adoption_created"]
    assert feedback["maximum_complete_report_revisions"] == 1 and not feedback["automatic_transport_retry"]
    assert "May be []" in feedback["general_rule_context_evidence"]
    assert original607 == before


def test_actual607_full_revision_messages_wire_and_original_three_sha_schema(original607):
    receipt, raw, goal, _ = original607
    prepared = read(ROUND20 / "FIRST_SOURCE_REQUEST_PREVIEW.json")
    assert prepared["request"] == receipt["request"]
    old_paths = [ROUND20 / "call_607_goal_source_audit_00.json", ROUND20 / "INHERITED_NATIVE_GOAL.json",
        ROUND20 / "PRODUCTION_FREEZE.json", Path(workflow.__file__), Path(workflow.source_audit.__file__), Path(strict_clients.__file__)]
    old_hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in old_paths}
    before = deepcopy((prepared, original607))
    result = revision.wrap_source_report_revision_request(prepared, receipt, raw_response_body=raw, native_goal=goal,
        wire_builder=strict_clients.expected_wire_request)
    payload = json.loads(result["request"]["messages"][1]["content"])
    baseline = json.loads(receipt["request"]["messages"][1]["content"])
    assert {key: value for key, value in payload.items() if key != revision.ENVELOPE_FIELD} == baseline
    assert payload[revision.ENVELOPE_FIELD]["previous_complete_source_report"] == receipt["output"]
    assert result["request"]["structured_schema"] == receipt["request"]["structured_schema"]
    for key in ("native_goal_sha256", "source_context_sha256", "authority_context_sha256"):
        assert result["request"]["input_provenance"][key] == receipt["request"]["input_provenance"][key]
    assert result["request_sha256"] == revision.digest(result["request"]) != receipt["request_sha256"]
    assert result["wire"] == strict_clients.expected_wire_request(result["request"])
    assert result["wire"]["tools"][0]["function"]["strict"] is True
    assert result["wire"]["messages"] == result["request"]["messages"]
    assert "source_protocol_binding" not in result["request"]["input_provenance"]
    assert result["manifest"]["source_protocol_rebinding_required"]
    assert result["request"]["parameters"] == receipt["request"]["parameters"]
    assert revision.REVISION_RULE in result["wire"]["messages"][0]["content"]
    assert result["manifest"]["payload_identity"]["characters"] < 100000
    compilation = strict_clients.schema_compilation_manifest(result["request"])
    assert compilation["service_schema_bytes"] == 36946 and compilation["expected_wire_bytes"] < 600000
    assert result["manifest"]["revision_envelope_sha256"] == revision.digest(payload)
    assert result["manifest"]["original_source_context_sha256"] == revision.digest(baseline)
    assert result["source_context_sha256"] == revision.digest(baseline)
    assert result["sdk_max_retries"] == 0 and not result["dispatch_performed"] and not result["production_dispatch_eligible"]
    assert (prepared, original607) == before
    assert old_hashes == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in old_paths}


def test_restarts_or_different_prepared_paths_cannot_issue_a_different_revision_scope(original607):
    receipt, raw, goal, _ = original607
    prepared = read(ROUND20 / "FIRST_SOURCE_REQUEST_PREVIEW.json")
    original = revision.wrap_source_report_revision_request(prepared, receipt, raw_response_body=raw, native_goal=goal,
        wire_builder=strict_clients.expected_wire_request)
    different_directory = deepcopy(prepared); different_directory["manifest"]["local_preview_path"] = "different/directory"
    second = revision.wrap_source_report_revision_request(different_directory, receipt, raw_response_body=raw, native_goal=goal,
        wire_builder=strict_clients.expected_wire_request)
    assert original["source_report_revision_feedback"]["revision_scope_key"] == second["source_report_revision_feedback"]["revision_scope_key"]
    assert original["request_sha256"] != second["request_sha256"]
    assert original["source_report_revision_proof"]["original_native_report_sha256"] == second["source_report_revision_proof"]["original_native_report_sha256"]


def test_wrapper_rejects_changed_prepared_request_or_implicit_wire_mapping(original607):
    receipt, raw, goal, _ = original607
    prepared = read(ROUND20 / "FIRST_SOURCE_REQUEST_PREVIEW.json")
    prepared["request"]["parameters"]["max_completion_tokens"] = 32000
    with pytest.raises(revision.KnownSourceReportRevisionError):
        revision.wrap_source_report_revision_request(prepared, receipt, raw_response_body=raw, native_goal=goal,
            wire_builder=strict_clients.expected_wire_request)
    prepared = read(ROUND20 / "FIRST_SOURCE_REQUEST_PREVIEW.json")
    with pytest.raises(revision.KnownSourceReportRevisionError):
        revision.wrap_source_report_revision_request(prepared, receipt, raw_response_body=raw, native_goal=goal, wire_builder=None)


def test_an_already_revised_envelope_is_not_an_original_report_revision_seed(original607):
    receipt, _, _, _ = original607
    payload = json.loads(receipt["request"]["messages"][1]["content"])
    payload[revision.ENVELOPE_FIELD] = {"previous_complete_source_report": receipt["output"]}
    receipt["request"]["messages"][1]["content"] = json.dumps(payload, ensure_ascii=False)
    receipt["request_sha256"] = revision.digest(receipt["request"])
    with pytest.raises(revision.KnownSourceReportRevisionError, match="before any report revision"):
        verify((receipt, original607[1], original607[2], payload))


def test_no_story_specific_questions_are_invented_by_default(original607):
    receipt, raw, goal, payload = original607
    result = revision.build_source_report_revision_feedback(receipt, raw_response_body=raw, native_goal=goal, source_payload=payload)
    assert result["reviewer_checks"] == [] and result["pending_downstream_risks"] == []
    assert all(ref not in Path(revision.__file__).read_text(encoding="utf-8") for ref in ("G047", "G108", "G121", "G062"))


@pytest.mark.parametrize("fault", ["review_ref", "review_path", "review_quote", "review_status", "review_verdict",
    "risk_ref", "risk_path", "risk_quote", "risk_status", "risk_verdict", "risk_empty_evidence", "risk_extra_field"])
def test_optional_pending_hints_cannot_cross_native_source_or_create_verdicts(original607, fault):
    receipt, raw, goal, payload = original607
    questions = read(PROJECT / "data/qa/creative_known_source_report_revision_20261014/ROOT_607_SEMANTIC_REVIEW_QUESTIONS_v1.json")
    checks, risks = questions["reviewer_checks"], questions["pending_downstream_risks"]
    if fault == "review_ref": checks[0]["source_ref"] = "G9999"
    elif fault == "review_path": checks[0]["document_path"] = "another.document"
    elif fault == "review_quote": checks[0]["original_quote"] = "另一个源的原句"
    elif fault == "review_status": checks[0]["semantic_status"] = "failed"
    elif fault == "review_verdict": checks[0]["local_verdict_created"] = True
    elif fault == "risk_ref": risks[0]["evidence"][0]["source_ref"] = "G9999"
    elif fault == "risk_path": risks[0]["evidence"][0]["document_path"] = "another.document"
    elif fault == "risk_quote": risks[0]["evidence"][0]["quote"] = "不在当前原句中"
    elif fault == "risk_status": risks[0]["status"] = "passed"
    elif fault == "risk_verdict": risks[0]["source_legal_failure_created"] = True
    elif fault == "risk_empty_evidence": risks[0]["evidence"] = []
    else: risks[0]["native_source_verdict"] = "fail"
    with pytest.raises(revision.KnownSourceReportRevisionError):
        revision.build_source_report_revision_feedback(receipt, raw_response_body=raw, native_goal=goal, source_payload=payload,
            reviewer_checks=checks, pending_downstream_risks=risks)


def test_provider_model_drift_cannot_hide_behind_matching_saved_metadata(original607):
    case = body_change(original607, lambda body: body.update(model="another-provider-model"))
    case[0]["response_metadata"]["response_model"] = "another-provider-model"
    with pytest.raises(revision.KnownSourceReportRevisionError, match="requested/returned"):
        verify(case)


def test_explicit_generic_question_reference_and_catalog_risk_row_are_preserved(original607):
    receipt, raw, goal, payload = original607
    catalog = workflow.source_audit.build_evidence_catalog(goal)
    ref = next(iter(catalog))
    question = {"source_ref": ref, "document_path": catalog[ref]["document_path"], "original_quote": catalog[ref]["quote"],
        "question": "A generic source question selected by the caller", "semantic_status": "pending_model_review", "local_verdict_created": False}
    risk = {"risk_id": "caller_generic_risk", "evidence": [{"source_ref": ref, **catalog[ref]}],
        "question": "Caller question, not automatically inferred from an ID", "owner_stages": ["drama"],
        "status": "pending_model_verification", "source_legal_failure_created": False, "new_hard_schema_check_created": False,
        "native_goal_modified": False, "human_adoption_created": False}
    result = revision.build_source_report_revision_feedback(receipt, raw_response_body=raw, native_goal=goal, source_payload=payload,
        reviewer_checks=[question], pending_downstream_risks=[risk])
    assert result["reviewer_checks"] == [question] and result["pending_downstream_risks"] == [risk]


def test_wrapper_includes_bound_questions_once_and_never_relaxes_original_actual_g(original607):
    receipt, raw, goal, _ = original607
    questions = read(PROJECT / "data/qa/creative_known_source_report_revision_20261014/ROOT_607_SEMANTIC_REVIEW_QUESTIONS_v1.json")
    prepared = read(ROUND20 / "FIRST_SOURCE_REQUEST_PREVIEW.json")
    result = revision.wrap_source_report_revision_request(prepared, receipt, raw_response_body=raw, native_goal=goal,
        wire_builder=strict_clients.expected_wire_request, reviewer_checks=questions["reviewer_checks"],
        pending_downstream_risks=questions["pending_downstream_risks"])
    payload = json.loads(result["request"]["messages"][1]["content"])
    assert payload[revision.ENVELOPE_FIELD]["reviewer_checks"] == questions["reviewer_checks"]
    assert payload[revision.ENVELOPE_FIELD]["pending_downstream_risks"] == questions["pending_downstream_risks"]
    assert result["wire"]["messages"][1]["content"] == result["request"]["messages"][1]["content"]
    assert result["request"]["structured_schema"] == receipt["request"]["structured_schema"]
    actual_refs = result["request"]["structured_schema"]["$defs"]["current_actual_evidence"]["properties"]["source_ref"]["enum"]
    assert "G106" not in actual_refs
    assert result["manifest"]["revision_envelope_within_original_context_policy"]
    assert result["manifest"]["payload_identity"]["characters"] <= prepared["manifest"]["context_policy"]["max_payload_characters"]


@pytest.mark.parametrize("fault", ["huge_question", "small_char_policy", "small_byte_policy", "missing_policy"])
def test_full_revision_over_explicit_context_limits_stops_without_truncating(original607, fault):
    receipt, raw, goal, _ = original607
    prepared = read(ROUND20 / "FIRST_SOURCE_REQUEST_PREVIEW.json")
    questions = read(PROJECT / "data/qa/creative_known_source_report_revision_20261014/ROOT_607_SEMANTIC_REVIEW_QUESTIONS_v1.json")
    if fault == "huge_question": questions["reviewer_checks"][0]["question"] = "长" * 100000
    elif fault == "small_char_policy": prepared["manifest"]["context_policy"]["max_payload_characters"] = 100
    elif fault == "small_byte_policy": prepared["manifest"]["context_policy"]["max_payload_utf8_bytes"] = 100
    else: prepared["manifest"].pop("context_policy")
    before = deepcopy((prepared, questions, original607))
    with pytest.raises(revision.KnownSourceReportRevisionError, match="context"):
        revision.wrap_source_report_revision_request(prepared, receipt, raw_response_body=raw, native_goal=goal,
            wire_builder=strict_clients.expected_wire_request, reviewer_checks=questions["reviewer_checks"],
            pending_downstream_risks=questions["pending_downstream_risks"])
    assert (prepared, questions, original607) == before
