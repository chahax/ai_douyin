"""Exact citation wire/source bindings; no live provider invocation."""
from copy import deepcopy
import json
import pytest
from jsonschema import ValidationError
from src.content_factory import creative_goal_context_workflow_v4 as workflow
from src.content_factory import creative_goal_audit_citation_contract_v1 as citations
from tests.test_goal_context_text_production_v5 import scenario, prior_scenario


def test_actual_audit_payload_manifest_and_exact_source_schema(scenario):
    inputs, profile, goal, audit, _, _ = scenario
    prepared = workflow.prepare_goal_audit_request(inputs, profile, goal)
    payload = json.loads(prepared["wire"]["messages"][1]["content"])
    assert workflow.digest(payload) == audit["audit_context_sha256"]
    assert payload["goal_evidence_catalog"] == citations.build_evidence_catalog(goal)
    assert prepared["manifest"]["reference_proof"]["payload_occurrences"] == 1
    assert any(row["path"] == "goal_evidence_catalog" for row in prepared["manifest"]["field_manifest"])
    assert prepared["wire"]["model"] == "deepseek-flash" and prepared["dispatch_performed"] is False


@pytest.mark.parametrize("change", ["native", "audited_source", "claim_coverage", "citation"])
def test_altered_goal_source_or_review_cannot_prepare_author(scenario, change):
    inputs, profile, goal, audit, ids, _ = deepcopy(scenario)
    if change == "native":
        goal["whole_plan"]["premise"] += "changed"
    elif change == "audited_source":
        inputs["user_goal_contract"]["audience_goals"][0]["text"] += "changed"
    elif change == "claim_coverage":
        audit["claim_checks"].pop(next(iter(audit["claim_checks"])))
    else:
        audit["goal_checks"][next(iter(audit["goal_checks"]))]["evidence_refs"] = ["G999999"]
    with pytest.raises((ValidationError, ValueError)):
        workflow.prepare_script_request(inputs, profile, goal, audit, **ids)


def test_script_repair_preserves_audited_goal_and_actual_law_review_binding(scenario):
    inputs, profile, goal, audit, ids, native = scenario
    first = workflow.prepare_script_request(inputs, profile, goal, audit, **ids)
    dirty = {**deepcopy(inputs), "previous_complete_document": native,
        "revision_diagnostics": {"synthetic_content_rejection": "complete replacement required"}}
    revised = workflow.prepare_script_request(dirty, profile, goal, audit, **ids)
    assert first["goal_audit_sha256"] == revised["goal_audit_sha256"]
    prepared = workflow.prepare_full_review_request(inputs, profile, native, first["views"])
    payload = json.loads(prepared["wire"]["messages"][1]["content"])
    assert prepared["review_legal_context"] == payload["verified_legal_context"]
    assert prepared["request"]["structured_schema"]["properties"]["legal_context_sha256"]["const"] == workflow.digest(payload["verified_legal_context"])
