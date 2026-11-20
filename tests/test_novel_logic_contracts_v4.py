"""Offline contract failures are technical; these fixtures are not model reviews."""
from copy import deepcopy

import pytest

from src.content_factory import novel_logic_contracts_v4 as contracts


def header(artifact_id="ledger-1", draft="draft-sha256-1"):
    return {"artifact_id": artifact_id, "schema_version": contracts.VERSION,
            "source_binding": "source-sha256-1", "draft_binding": draft,
            "producer_version": "offline-human-fixture/1", "parent_artifact_ids": [],
            "status": "complete"}


def fact(value="doorway"):
    return {"subject_id": "father", "predicate": "relative_position", "value": value,
            "certainty": "explicit", "evidence_refs": ["S01:opening"],
            "qualifiers": {"scope": "physical", "evidence_status": "located"}}


def event(event_id="E01"):
    return {"event_id": event_id, "timeline_id": "present", "narrative_layer": "performance",
            "entities": ["father", "son"], "relation": "new_event", "referent_event_id": None,
            "before": [fact()], "after": [fact("table")], "interpretation_status": "explicit",
            "context": {"scene_id": "S01", "location": "S01:paragraph-2",
                        "description": "Father moves from the doorway to the table."}}


def ledger():
    return {"header": header(), "events": [event()]}


def issue(issue_id="I01", severity="major"):
    return {"issue_id": issue_id, "root_cause_id": "location-change-1",
            "dimensions": ["space_gaze_action", "causality"], "event_ids": ["E01"],
            "evidence": ["S01:paragraph-2: no intervening movement in the declared account"],
            "reasonable_explanations": ["An omitted transition may explain it."], "counterevidence": [],
            "impact": "Actor position may be impossible to stage.", "severity": severity,
            "severity_certainty": "possible", "finding_status": "unresolved", "blocking": True}


def review(issues=None, verdict="pass"):
    issues = [] if issues is None else issues
    return {"header": header("review-1"), "provider": "deepseek",
            "native_response_ref": "fixture:not-real-service-response", "native_verdict": verdict,
            "whole_text_reviewed": True, "source_complete": True, "draft_complete": True,
            "checks": [{"dimension": dimension, "checked": True, "assessment": "Offline declared coverage only.",
                        "issue_ids": [item["issue_id"] for item in issues if dimension in item["dimensions"]]}
                       for dimension in contracts.REVIEW_DIMENSIONS], "issues": issues}


def adjudication(original_review, new_issues=None):
    new_issues = [] if new_issues is None else new_issues
    return {"header": header("adjudication-1"), "review_artifact_id": original_review["header"]["artifact_id"],
            "new_issues": new_issues,
            "dispositions": [{"issue_id": item["issue_id"], "disposition": "unresolved",
                              "basis": ["Need to distinguish transition omission from impossible action."],
                              "new_issue_ids": [], "blocking": True}
                             for item in original_review["issues"] + new_issues]}


def episode():
    return {"header": header("episode-1", draft=None), "episode_id": "episode-1",
            "source_range": {"chapter_ids": ["chapter-1"], "start_anchor": "opening", "end_anchor": "chapter-1:end"},
            "selected_event_ids": ["E01"], "prior_end_state": [], "unrevealed_facts": ["Later reconciliation is not acquired."],
            "adaptation_boundaries": {"preserve": ["Current conflict and identity"],
                                      "allowed_changes": ["Dialogue phrasing"], "unknown_facts": ["Exact age"]}}


def director():
    return {"header": header("director-1"), "text_gate_artifact_id": "gate-1",
            "scene_ledger_artifact_id": "ledger-1", "episode_artifact_id": "episode-1",
            "segments": [{"segment_id": "S01", "timeline_id": "present", "location": "room",
                          "environment": "A table beside the entrance.", "present_characters": ["father", "son"],
                          "start_state": [fact()], "end_state": [fact("table")],
                          "performance": [{"event_id": "E01", "actor_id": "father", "action": "Walks to the table.",
                                           "expression": "Tense", "gaze": "Toward son", "dialogue": "",
                                           "reaction": "Son watches him approach.", "reaction_window": "During movement"}],
                          "emotion_focus": "Threat before speaking", "next_cause": "Son answers after arrival.",
                          "estimated_duration_seconds": 8, "duration_basis": "Walking and a readable silent reaction."}],
            "event_coverage": [{"event_id": "E01", "segment_ids": ["S01"], "relation": "new_event"}],
            "asset_requirements": [{"asset_type": "character", "search_tags": ["father", "middle-aged"],
                                    "candidate_id": None, "candidate_version": None, "status": "pending"}]}


def codes(errors):
    return {error["code"] for error in errors}


def test_contract_headers_use_explicit_version_and_same_source_same_draft():
    value = header()
    assert contracts.validate_header(value, expected_source_binding="source-sha256-1",
                                     expected_draft_binding="draft-sha256-1") == []
    assert "ARTIFACT_BINDING_MISMATCH" in codes(contracts.validate_header(value, expected_draft_binding="old-draft"))
    value["schema_version"] = "novel_plaintext_contracts/v3"
    assert "SCHEMA_VERSION_MISMATCH" in codes(contracts.validate_header(value))


@pytest.mark.parametrize("artifact_status", contracts.ARTIFACT_STATUSES)
def test_status_is_declared_data_not_automatic_gate_success(artifact_status):
    value = header()
    value["status"] = artifact_status
    assert contracts.validate_header(value) == []


def test_source_episode_can_explicitly_precede_draft_but_review_cannot():
    assert contracts.validate_source_episode(episode()) == []
    value = review()
    value["header"]["draft_binding"] = None
    assert contracts.validate_full_review(value)
    value = episode()
    del value["header"]["draft_binding"]
    assert contracts.validate_source_episode(value)


def test_native_text_and_extra_context_are_preserved_without_layout_contracts():
    value = ledger()
    text = '他说：“走吧。”\n\n“走吧。”也可自然改写，标点不必匹配原文。'
    value["native_text"] = text
    value["events"][0]["context"]["extra_analysis"] = {"not_a_metric_coordinate": "beside the door"}
    before = deepcopy(value)
    assert contracts.validate_scene_ledger(value) == []
    assert value == before and value["native_text"] == text


def test_summary_and_same_event_expansion_are_legitimate_distinct_records():
    value = ledger()
    value["events"][0]["narrative_layer"] = "summary"
    expanded = event("E02")
    expanded["relation"] = "same_event"
    expanded["referent_event_id"] = "E01"
    value["events"].append(expanded)
    assert contracts.validate_scene_ledger(value) == []


@pytest.mark.parametrize("mutation,expected", [
    (lambda value: value["events"].append(deepcopy(value["events"][0])), "SIDECAR_DUPLICATE"),
    (lambda value: value["events"][0].update(relation="same_event", referent_event_id="missing"), "ARTIFACT_REFERENCE_MISSING"),
    (lambda value: value["events"][0].update(relation="same_event", referent_event_id="E01"), "ARTIFACT_REFERENCE_INVALID"),
    (lambda value: value["events"][0]["before"][0].update(evidence_refs=[]), "EVIDENCE_REFERENCE_MISSING"),
    (lambda value: value["events"][0]["before"][0].update(value=float("nan")), "SIDECAR_FORMAT"),
    (lambda value: value["events"][0]["context"].update(continuity_from_event_id="missing"), "ARTIFACT_REFERENCE_MISSING"),
])
def test_bad_auxiliary_scene_data_is_technical_not_writer_content_repair(mutation, expected):
    value = ledger()
    mutation(value)
    assert expected in codes(contracts.validate_scene_ledger(value))


def test_explicit_and_ambiguous_states_can_keep_shared_holders_and_unknown_values():
    value = ledger()
    value["events"][0]["after"] = [{"subject_id": "rope", "predicate": "holders", "value": ["father", "son"],
                                    "certainty": "ambiguous", "evidence_refs": [], "qualifiers": {}}]
    assert contracts.validate_scene_ledger(value) == []
    value["events"][0]["after"][0]["value"] = None
    assert contracts.validate_scene_ledger(value) == []


def test_review_requires_complete_nine_dimensions_not_just_count():
    value = review()
    assert contracts.validate_full_review(value) == []
    value["checks"][-1] = deepcopy(value["checks"][0])
    assert "REVIEW_COVERAGE" in codes(contracts.validate_full_review(value))


@pytest.mark.parametrize("field", ["whole_text_reviewed", "source_complete", "draft_complete"])
def test_partial_scope_declaration_never_counts_as_full_review(field):
    value = review()
    value[field] = False
    assert contracts.validate_full_review(value)


def test_native_pass_plus_new_major_remains_content_input_not_format_rewrite():
    value = review([issue()], verdict="pass")
    assert contracts.validate_full_review(value) == []
    # A gate must route the contradiction; this schema cannot pronounce pass.
    assert value["issues"][0]["severity_certainty"] == "possible"


def test_native_revise_without_issues_is_kept_for_gate_attention_not_fabrication():
    assert contracts.validate_full_review(review(verdict="revise")) == []


def test_issue_links_must_match_checked_dimensions_and_cannot_reference_foreign_ledger():
    value = review([issue()])
    value["checks"][0]["issue_ids"] = ["I01"]
    assert "REVIEW_ISSUE_COVERAGE" in codes(contracts.validate_full_review(value))
    assert "ARTIFACT_REFERENCE_MISSING" in codes(contracts.validate_issue(issue(), event_ids={"old-event"}))


def test_adjudication_covers_each_original_and_each_new_issue_without_overwrite():
    original = review([issue()])
    new_issue = issue("I02", "blocking")
    value = adjudication(original, [new_issue])
    before = deepcopy((original, value))
    assert contracts.validate_adjudication(value, review=original) == []
    assert (original, value) == before
    value["dispositions"].pop()
    assert "ADJUDICATION_COVERAGE" in codes(contracts.validate_adjudication(value, review=original))


def test_adjudication_cannot_relabel_an_original_issue_as_new_or_cross_bind_draft():
    original = review([issue()])
    value = adjudication(original, [issue()])
    assert "SIDECAR_DUPLICATE" in codes(contracts.validate_adjudication(value, review=original))
    value = adjudication(original)
    value["header"]["draft_binding"] = "another-draft"
    assert "ARTIFACT_BINDING_MISMATCH" in codes(contracts.validate_adjudication(value, review=original))


def test_disposition_needs_evidence_even_when_dismissing_a_report():
    original = review([issue()])
    value = adjudication(original)
    value["dispositions"][0].update(disposition="rejected", basis=[])
    assert contracts.validate_adjudication(value, review=original)


def test_effective_severity_is_explicit_paired_and_does_not_rewrite_the_report():
    original = review([issue()])
    before = deepcopy(original)
    value = adjudication(original)
    value["dispositions"][0].update(disposition="confirmed", effective_severity="major",
                                     effective_severity_certainty="confirmed")
    assert contracts.validate_adjudication(value, review=original) == []
    assert original == before and original["issues"][0]["severity_certainty"] == "possible"
    del value["dispositions"][0]["effective_severity_certainty"]
    assert "ADJUDICATION_EFFECTIVE_SEVERITY_INCOMPLETE" in codes(contracts.validate_adjudication(value, review=original))


@pytest.mark.parametrize("field,invalid", [("effective_severity", "safe"), ("effective_severity_certainty", True)])
def test_effective_judgment_requires_known_enums_and_basis(field, invalid):
    original = review([issue()])
    value = adjudication(original)
    value["dispositions"][0].update(effective_severity="major", effective_severity_certainty="confirmed")
    value["dispositions"][0][field] = invalid
    assert contracts.validate_adjudication(value, review=original)


def test_adjudication_requires_each_new_issue_even_without_reference_review():
    original = review()
    value = adjudication(original, [issue("new-major")])
    value["dispositions"] = []
    assert "ADJUDICATION_COVERAGE" in codes(contracts.validate_adjudication(value))


def test_director_contract_has_coverage_reactions_duration_basis_and_pending_assets():
    value = director()
    assert contracts.validate_director_consumption(value) == []
    value["event_coverage"][0]["segment_ids"] = ["missing"]
    assert "ARTIFACT_REFERENCE_MISSING" in codes(contracts.validate_director_consumption(value))


def test_director_mapping_cannot_claim_a_different_event_was_performed():
    value = director()
    value["event_coverage"][0]["event_id"] = "unperformed-event"
    errors = codes(contracts.validate_director_consumption(value))
    assert "DIRECTOR_COVERAGE_INCOMPLETE" in errors and "ARTIFACT_REFERENCE_MISSING" in errors


@pytest.mark.parametrize("duration", [True, float("nan"), float("inf"), 0, -1])
def test_director_duration_is_an_explicit_finite_positive_estimate(duration):
    value = director()
    value["segments"][0]["estimated_duration_seconds"] = duration
    assert contracts.validate_director_consumption(value)


@pytest.mark.parametrize("status,candidate_id,candidate_version,valid", [
    ("pending", None, None, True), ("candidate", "asset-12", "v2", True),
    ("candidate", "asset-12", None, False), ("pending", "asset-12", "v2", False),
    ("bound", "asset-12", "v2", False),
])
def test_asset_names_or_candidates_never_imply_production_binding(status, candidate_id, candidate_version, valid):
    value = director()
    value["asset_requirements"][0].update(status=status, candidate_id=candidate_id, candidate_version=candidate_version)
    assert (contracts.validate_director_consumption(value) == []) is valid


@pytest.mark.parametrize("validator", [contracts.validate_header, contracts.validate_scene_ledger,
    contracts.validate_full_review, contracts.validate_adjudication, contracts.validate_source_episode,
    contracts.validate_director_consumption, contracts.validate_issue])
@pytest.mark.parametrize("value", [None, [], "native screenplay text", 0, {"header": [], "events": None}])
def test_untrusted_malformed_json_returns_errors_without_throwing(validator, value):
    assert validator(value)
