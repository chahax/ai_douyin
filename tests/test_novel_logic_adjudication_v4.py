"""Offline guard and route cases; no model, service, or production file writes."""
from copy import deepcopy

import pytest

from src.content_factory import novel_logic_adjudication_v4 as gate
from src.content_factory import novel_logic_contracts_v4 as contracts


def header(artifact_id):
    return {"artifact_id": artifact_id, "schema_version": contracts.VERSION,
            "source_binding": "source-1", "draft_binding": "draft-1",
            "producer_version": "offline-fixture/v1", "parent_artifact_ids": [],
            "status": "complete"}


def issue(issue_id="I1", *, root="root-1", severity="major", certainty="confirmed"):
    return {"issue_id": issue_id, "root_cause_id": root, "dimensions": ["causality"],
            "event_ids": ["E1"], "evidence": ["scene-1: action context"],
            "reasonable_explanations": [], "counterevidence": [], "impact": "Affect character causal understanding.",
            "severity": severity, "severity_certainty": certainty,
            "finding_status": "confirmed" if certainty == "confirmed" else "unresolved",
            "blocking": False}


def review(verdict="pass", issues=None):
    issues = [] if issues is None else deepcopy(issues)
    return {"header": header("R1"), "provider": "deepseek", "native_response_ref": "native-1",
            "native_verdict": verdict, "whole_text_reviewed": True,
            "source_complete": True, "draft_complete": True, "issues": issues,
            "checks": [{"dimension": dimension, "checked": True, "assessment": "Offline complete check.",
                        "issue_ids": [item["issue_id"] for item in issues if dimension in item["dimensions"]]}
                       for dimension in contracts.REVIEW_DIMENSIONS]}


def ledger():
    return {"header": header("L1"), "events": [{
        "event_id": "E1", "timeline_id": "current", "narrative_layer": "performance",
        "entities": ["father", "son"], "relation": "new_event", "referent_event_id": None,
        "before": [], "after": [], "interpretation_status": "explicit",
        "context": {"scene_id": "S1", "location": "room", "description": "Action context."},
    }]}


def evidence(review_value):
    return {"status": "complete", "usage_known": True, "finish_reason": "stop",
            "identity_verified": True, "files_verified": True, "whole_text_verified": True,
            "review_payload_verified": True, "native_provider": "deepseek",
            "source_binding": "source-1", "draft_binding": "draft-1",
            "review_artifact_id": review_value["header"]["artifact_id"],
            "native_response_ref": review_value["native_response_ref"],
            "native_verdict": review_value["native_verdict"]}


def capacity():
    return {"per_draft_clarification_limit": 1, "per_draft_clarification_used": 0,
            "run_clarification_limit": 2, "run_clarification_used": 0,
            "content_revision_limit": 2, "content_revisions_used": 0,
            "full_review_limit": 5, "full_reviews_used": 1,
            "call_limit": 10, "calls_used": 2, "token_limit": 10000,
            "tokens_used": 1000, "request_token_reservation": 100}


def adjudication(review_value, states=None, new_issues=None):
    new_issues = [] if new_issues is None else deepcopy(new_issues)
    states = {} if states is None else states
    return {"header": header("A1"), "review_artifact_id": review_value["header"]["artifact_id"],
            "new_issues": new_issues,
            "dispositions": [{"issue_id": item["issue_id"], "disposition": states.get(item["issue_id"], "confirmed"),
                              "basis": ["Compared full event context and actual impact."],
                              "new_issue_ids": [], "blocking": False}
                             for item in review_value["issues"] + new_issues]}


def evaluate(review_value=None, **overrides):
    review_value = review() if review_value is None else review_value
    inputs = {"source_binding": "source-1", "draft_binding": "draft-1", "review": review_value,
              "scene_ledger": ledger(), "evidence": evidence(review_value), "capacity": capacity()}
    inputs.update(overrides)
    return gate.evaluate_gate(**inputs)


def test_complete_native_pass_can_deliver_locally_without_new_request():
    result = evaluate()
    assert result["decision"] == "pass"
    assert result["next_action"] == "deliver_local"
    assert result["requires_new_request"] is False


def test_zero_request_capacity_does_not_discard_already_received_pass():
    spent = capacity()
    for field in ("call_limit", "calls_used", "token_limit", "tokens_used",
                  "per_draft_clarification_limit", "run_clarification_limit", "full_review_limit"):
        spent[field] = 0
    assert evaluate(capacity=spent)["decision"] == "pass"
    assert evaluate(capacity=None)["decision"] == "pass"


def test_rejected_major_from_native_revise_requires_new_full_review():
    value = review("revise", [issue()])
    result = evaluate(value, adjudication=adjudication(value, {"I1": "rejected"}))
    assert result["decision"] == "needs_attention"
    assert result["next_action"] == "full_review_same_draft"
    assert result["requires_new_request"] is True
    assert value["native_verdict"] == "revise"


def test_native_revise_without_issues_is_not_local_pass():
    result = evaluate(review("revise"))
    assert result["decision"] == "needs_attention"
    assert result["next_action"] == "full_review_same_draft"


@pytest.mark.parametrize("native", ["pass", "revise"])
@pytest.mark.parametrize("severity", ["major", "blocking"])
def test_confirmed_major_overrides_even_original_native_pass(native, severity):
    value = review(native, [issue(severity=severity)])
    result = evaluate(value, adjudication=adjudication(value))
    assert result["decision"] == "revise"
    assert result["next_action"] == "revise_full_draft"
    assert result["blocking_issue_ids"] == ["I1"]


@pytest.mark.parametrize("severity", ["minor", "major", "blocking", "unknown"])
@pytest.mark.parametrize("certainty", ["possible", "unknown"])
def test_unknown_severity_never_becomes_minor_by_advisory_label(severity, certainty):
    value = review("pass", [issue(severity=severity, certainty=certainty)])
    result = evaluate(value, adjudication=adjudication(value, {"I1": "advisory"}))
    assert result["decision"] == "needs_attention"
    assert result["next_action"] == "clarify_same_draft"
    assert result["unresolved_issue_ids"] == ["I1"]


def test_confirmed_minor_advisory_can_remain_in_machine_accepted_text():
    value = review("pass", [issue(severity="minor")])
    result = evaluate(value, adjudication=adjudication(value, {"I1": "advisory"}))
    assert result["decision"] == "pass"


@pytest.mark.parametrize("disposition", ["confirmed", "advisory", "unresolved"])
def test_known_minor_impact_can_be_retained_without_spending_clarification(disposition):
    value = review("pass", [issue(severity="minor")])
    value["issues"][0]["finding_status"] = "unresolved"
    table = adjudication(value, {"I1": disposition})
    before = deepcopy(table)
    result = evaluate(value, adjudication=table, capacity=None)
    assert result["decision"] == "pass"
    assert result["next_action"] == "deliver_local"
    assert result["requires_new_request"] is False
    assert result["unresolved_issue_ids"] == []
    assert table == before


@pytest.mark.parametrize("certainty", ["possible", "unknown"])
def test_unresolved_minor_with_uncertain_impact_still_requires_verification(certainty):
    value = review("pass", [issue(severity="minor", certainty=certainty)])
    result = evaluate(value, adjudication=adjudication(value, {"I1": "unresolved"}))
    assert result["decision"] == "needs_attention"
    assert result["next_action"] == "clarify_same_draft"
    assert result["unresolved_issue_ids"] == ["I1"]


@pytest.mark.parametrize("blocking_owner", ["issue", "disposition"])
def test_unresolved_known_minor_cannot_hide_explicit_blocking_flag(blocking_owner):
    value = review("pass", [issue(severity="minor")])
    table = adjudication(value, {"I1": "unresolved"})
    target = value["issues"][0] if blocking_owner == "issue" else table["dispositions"][0]
    target["blocking"] = True
    result = evaluate(value, adjudication=table)
    assert result["decision"] != "pass"
    assert result["next_action"] == "clarify_same_draft"


def test_native_revise_still_requires_native_full_pass_when_only_known_minor_remains():
    value = review("revise", [issue(severity="minor")])
    result = evaluate(value, adjudication=adjudication(value, {"I1": "unresolved"}))
    assert result["decision"] == "needs_attention"
    assert result["next_action"] == "full_review_same_draft"
    assert result["unresolved_issue_ids"] == []


def test_original_blocking_flag_cannot_disappear_through_minor_advisory():
    value = review("pass", [issue(severity="minor")])
    value["issues"][0]["blocking"] = True
    result = evaluate(value, adjudication=adjudication(value, {"I1": "advisory"}))
    assert result["decision"] != "pass"
    assert result["next_action"] == "clarify_same_draft"


def test_unresolved_unknown_severity_candidate_cannot_be_advisory_downgraded():
    value, candidate = review(), issue("new", severity="minor", certainty="unknown")
    table = adjudication(value, {"new": "advisory"}, [candidate])
    result = evaluate(value, adjudication=table, additional_issues=[candidate])
    assert result["decision"] == "needs_attention"
    assert result["unresolved_issue_ids"] == ["new"]


def test_new_major_discovered_after_native_pass_is_not_hidden():
    value = review()
    result = evaluate(value, adjudication=adjudication(value, new_issues=[issue("new")]))
    assert result["decision"] == "revise"
    assert result["blocking_issue_ids"] == ["new"]


def test_independent_state_candidate_without_disposition_requests_clarification():
    candidate = issue("candidate-1", certainty="unknown")
    result = evaluate(additional_issues=[candidate])
    assert result["decision"] == "needs_attention"
    assert result["next_action"] == "clarify_same_draft"
    assert result["unresolved_issue_ids"] == ["candidate-1"]


def test_candidate_can_be_rejected_only_by_traceable_explicit_adjudication():
    value, candidate = review(), issue("candidate-1", certainty="unknown")
    table = adjudication(value, {"candidate-1": "rejected"}, [candidate])
    assert evaluate(value, adjudication=table, additional_issues=[candidate])["decision"] == "pass"
    changed = deepcopy(candidate)
    changed["impact"] = "A different candidate under same ID."
    assert evaluate(value, adjudication=table, additional_issues=[changed])["stop_reasons"] == ["additional_issue_identity_conflict"]


def test_each_issue_requires_disposition_even_when_shared_root_deduplicates():
    values = [issue("one"), issue("two")]
    value = review("revise", values)
    table = adjudication(value)
    table["dispositions"].pop()
    result = evaluate(value, adjudication=table)
    assert result["stop_reasons"] == ["adjudication_contract_invalid"]
    assert evaluate(value)["stop_reasons"] == ["adjudication_missing"]


def test_dedup_keeps_all_members_and_never_escalates_severity_by_votes():
    values = [issue("one", severity="minor"), issue("two", severity="minor")]
    values[1]["dimensions"] = ["space_gaze_action"]
    before = deepcopy(values)
    groups = gate.deduplicate_issues(values)
    assert len(groups) == 1
    assert groups[0]["severity"] == "minor"
    assert groups[0]["issue_ids"] == ["one", "two"]
    assert groups[0]["dimensions"] == ["causality", "space_gaze_action"]
    assert values == before
    groups[0]["members"][0]["impact"] = "changed locally"
    assert values == before


def test_dedup_does_not_guess_root_from_equal_text_or_accept_duplicate_id():
    assert len(gate.deduplicate_issues([issue("a", root="a"), issue("b", root="b")])) == 2
    with pytest.raises(ValueError):
        gate.deduplicate_issues([issue(), issue()])


@pytest.mark.parametrize("evidence_field,bad,reason", [
    ("status", "transport_unknown", "transport_unknown"),
    ("usage_known", False, "usage_unknown"),
    ("finish_reason", "length", "truncated"),
    ("identity_verified", False, "identity_verified_missing"),
    ("files_verified", False, "files_verified_missing"),
    ("whole_text_verified", False, "whole_text_verified_missing"),
    ("review_payload_verified", False, "review_payload_verified_missing"),
    ("native_provider", "minimax", "native_provider_mismatch"),
    ("source_binding", "other", "evidence_source_binding_mismatch"),
    ("draft_binding", "old-draft", "evidence_draft_binding_mismatch"),
    ("native_verdict", "revise", "evidence_native_verdict_mismatch"),
    ("native_response_ref", "other-response", "evidence_native_response_ref_mismatch"),
])
def test_technical_evidence_failure_stops_without_writer_repair(evidence_field, bad, reason):
    value = review()
    native = evidence(value)
    native[evidence_field] = bad
    result = evaluate(value, evidence=native)
    assert result["decision"] == "needs_attention"
    assert result["next_action"] == "stop"
    assert reason in result["stop_reasons"]


@pytest.mark.parametrize("artifact", ["review", "scene_ledger", "adjudication"])
@pytest.mark.parametrize("status", ["incomplete", "invalidated"])
def test_incomplete_or_stale_artifact_cannot_retain_pass(artifact, status):
    value, scenes = review(), ledger()
    table = adjudication(value)
    inputs = {"review": value, "scene_ledger": scenes, "adjudication": table}
    inputs[artifact]["header"]["status"] = status
    result = gate.evaluate_gate(source_binding="source-1", draft_binding="draft-1",
                               evidence=evidence(value), capacity=capacity(), **inputs)
    assert result["decision"] != "pass"
    assert result["next_action"] == "stop"


def test_nine_dimensions_and_same_current_draft_are_required():
    value = review()
    value["checks"].pop()
    assert "full_review_contract_invalid" in evaluate(value)["stop_reasons"]
    scenes = ledger()
    scenes["header"]["draft_binding"] = "old-draft"
    assert "scene_ledger_contract_invalid" in evaluate(scene_ledger=scenes)["stop_reasons"]


def test_issue_location_must_refer_to_same_scene_ledger():
    value = review("pass", [issue()])
    value["issues"][0]["event_ids"] = ["missing-event"]
    result = evaluate(value, adjudication=adjudication(value))
    assert result["stop_reasons"] == ["issue_event_binding_invalid"]


@pytest.mark.parametrize("field,value,reason", [
    ("per_draft_clarification_used", 1, "per_draft_clarification_limit"),
    ("run_clarification_used", 2, "run_clarification_limit"),
    ("full_reviews_used", 5, "full_review_limit"),
    ("calls_used", 10, "call_budget_exhausted"),
    ("tokens_used", 9950, "token_budget_exhausted"),
])
def test_same_draft_full_review_respects_each_independent_capacity(field, value, reason):
    frozen = capacity()
    frozen[field] = value
    result = evaluate(review("revise"), capacity=frozen)
    assert result["next_action"] == "stop"
    assert result["proposed_action"] == "full_review_same_draft"
    assert reason in result["stop_reasons"]


def test_revision_limit_keeps_content_decision_separate_from_dispatch_stop():
    value = review("revise", [issue()])
    frozen = capacity()
    frozen["content_revisions_used"] = 2
    result = evaluate(value, adjudication=adjudication(value), capacity=frozen)
    assert result["decision"] == "revise"
    assert result["next_action"] == "stop"
    assert result["stop_reasons"] == ["revision_limit"]


def test_major_unknown_uses_verification_not_writer_revision_capacity():
    value = review("pass", [issue(certainty="unknown")])
    frozen = capacity()
    frozen["content_revisions_used"] = 2
    result = evaluate(value, adjudication=adjudication(value, {"I1": "unresolved"}), capacity=frozen)
    assert result["next_action"] == "clarify_same_draft"
    assert "revision_limit" not in result["stop_reasons"]


@pytest.mark.parametrize("field,value", [
    ("content_revision_limit", 3), ("calls_used", True),
    ("tokens_used", None), ("request_token_reservation", 0),
])
def test_unknown_or_unfrozen_budget_does_not_authorize_request(field, value):
    frozen = capacity()
    frozen[field] = value
    result = evaluate(review("revise"), capacity=frozen)
    assert result["next_action"] == "stop"
    assert f"capacity_invalid:{field}" in result["stop_reasons"]
    assert evaluate(review("revise"), capacity=None)["stop_reasons"] == ["capacity_not_frozen"]


def test_explicit_unbounded_token_limit_does_not_reset_other_caps():
    frozen = capacity()
    frozen.update(token_limit=None, tokens_used=1000000, calls_used=10)
    assert evaluate(review("revise"), capacity=frozen)["stop_reasons"] == ["call_budget_exhausted"]


def test_evaluation_is_pure_preserves_review_receipts_counters_and_dispositions():
    value = review("revise", [issue()])
    frozen, table = capacity(), adjudication(value)
    objects = [value, frozen, table]
    before = deepcopy(objects)
    result = evaluate(value, capacity=frozen, adjudication=table)
    assert result["next_action"] == "revise_full_draft"
    assert objects == before


@pytest.mark.parametrize("field,value", [("status", []), ("finish_reason", []), ("native_provider", {})])
def test_malformed_evidence_is_technical_stop_not_exception(field, value):
    value_review = review()
    native = evidence(value_review)
    native[field] = value
    assert evaluate(value_review, evidence=native)["next_action"] == "stop"


@pytest.mark.parametrize("field,value", [("severity", []), ("severity", {}), ("finding_status", [])])
def test_malformed_issue_is_technical_stop_not_exception(field, value):
    value_review = review("pass", [issue()])
    value_review["issues"][0][field] = value
    assert evaluate(value_review)["next_action"] == "stop"


@pytest.mark.parametrize("binding", ["", None, [], {}])
def test_bad_current_binding_is_technical_stop_not_exception(binding):
    assert evaluate(source_binding=binding)["next_action"] == "stop"


@pytest.mark.parametrize("effective_severity,disposition,expected", [
    ("major", "confirmed", "revise"), ("blocking", "confirmed", "revise"),
    ("minor", "advisory", "pass"),
])
def test_explicit_verification_resolves_candidate_impact_without_rewriting_candidate(
        effective_severity, disposition, expected):
    value, candidate = review(), issue("candidate", certainty="unknown")
    table = adjudication(value, {"candidate": disposition}, [candidate])
    table["dispositions"][0].update(effective_severity=effective_severity,
                                      effective_severity_certainty="confirmed")
    original = deepcopy(candidate)
    result = evaluate(value, adjudication=table, additional_issues=[candidate])
    assert result["decision"] == expected
    assert candidate == original and candidate["severity_certainty"] == "unknown"
    assert result["issue_groups"][0]["members"][0]["severity_certainty"] == "unknown"


def test_paired_effective_fields_required_and_unknown_effective_impact_cannot_pass():
    value, candidate = review(), issue("candidate", certainty="unknown")
    table = adjudication(value, {"candidate": "advisory"}, [candidate])
    table["dispositions"][0]["effective_severity"] = "minor"
    assert evaluate(value, adjudication=table)["stop_reasons"] == ["adjudication_contract_invalid"]
    table["dispositions"][0]["effective_severity_certainty"] = "unknown"
    assert evaluate(value, adjudication=table)["decision"] == "needs_attention"


@pytest.mark.parametrize("analysis", [
    {"status": "needs_attention", "errors": ["KNOWN_EVENT_ID_REQUIRED"]},
    {"status": "needs_attention", "errors": ["INTERNALLY_CONFLICTING_FACT_SET"]},
    {"status": "analysis_complete", "errors": ["UNEXPECTED_ERROR"]},
    {"status": "analysis_complete"}, {}, [],
])
def test_failed_scene_analysis_prevents_pass_without_writer_format_repair(analysis):
    if isinstance(analysis, dict):
        analysis.update(source_binding="source-1", draft_binding="draft-1")
    result = evaluate(scene_analysis=analysis)
    assert result["decision"] == "needs_attention"
    assert result["next_action"] == "stop"
    assert "scene_analysis_failed" in result["stop_reasons"]


def test_scene_analysis_requires_current_binding_but_normal_ambiguity_is_not_failure():
    analysis = {"status": "analysis_complete", "errors": [],
                "source_binding": "source-1", "draft_binding": "draft-1",
                "retained_ambiguities": [{"reason": "relative location, no physical inference"}]}
    assert evaluate(scene_analysis=analysis)["decision"] == "pass"
    analysis["draft_binding"] = "old-draft"
    assert evaluate(scene_analysis=analysis)["stop_reasons"] == ["scene_analysis_binding_invalid"]


def scene_candidate_fixture():
    candidate = {"candidate_id": "candidate-1", "source_binding": "source-1", "draft_binding": "draft-1",
                 "root_cause_id": "root-1", "event_ids": ["E1"]}
    analysis = {"status": "analysis_complete", "errors": [], "source_binding": "source-1",
                "draft_binding": "draft-1", "candidates": [candidate]}
    candidate_issue = issue("candidate-issue", certainty="unknown")
    candidate_issue["origin_candidate_id"] = candidate["candidate_id"]
    return analysis, candidate_issue


def test_scene_candidate_cannot_disappear_when_adapter_omits_additional_issues():
    analysis, candidate_issue = scene_candidate_fixture()
    assert evaluate(scene_analysis=analysis)["stop_reasons"] == ["scene_candidate_unaccounted"]
    result = evaluate(scene_analysis=analysis, additional_issues=[candidate_issue])
    assert result["next_action"] == "clarify_same_draft"


def test_one_scene_candidate_cannot_have_two_contradictory_settlements():
    analysis, candidate_issue = scene_candidate_fixture()
    duplicate = deepcopy(candidate_issue)
    duplicate["issue_id"] = "duplicate-candidate"
    value = review()
    table = adjudication(value, {"candidate-issue": "rejected", "duplicate-candidate": "confirmed"},
                         [candidate_issue, duplicate])
    result = evaluate(value, scene_analysis=analysis, adjudication=table)
    assert result["stop_reasons"] == ["scene_candidate_duplicate_mapping"]


@pytest.mark.parametrize("field,value,reason", [
    ("source_binding", "other-source", "scene_candidate_binding_invalid"),
    ("draft_binding", "old-draft", "scene_candidate_binding_invalid"),
    ("root_cause_id", "wrong-root", "scene_candidate_mapping_mismatch"),
    ("event_ids", ["E2"], "scene_candidate_mapping_mismatch"),
    ("event_ids", [], "scene_candidates_contract_invalid"),
    ("event_ids", [{}], "scene_candidates_contract_invalid"),
])
def test_scene_candidate_mapping_must_bind_current_source_draft_root_and_events(field, value, reason):
    analysis, candidate_issue = scene_candidate_fixture()
    analysis["candidates"][0][field] = value
    result = evaluate(scene_analysis=analysis, additional_issues=[candidate_issue])
    assert result["decision"] == "needs_attention"
    assert reason in result["stop_reasons"]


def test_resolved_current_scene_candidate_keeps_original_candidate_and_explicit_disposition():
    analysis, candidate_issue = scene_candidate_fixture()
    value = review()
    table = adjudication(value, {candidate_issue["issue_id"]: "rejected"}, [candidate_issue])
    assert evaluate(value, scene_analysis=analysis, additional_issues=[candidate_issue], adjudication=table)["decision"] == "pass"
