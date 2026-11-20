"""Scoped authority review never changes native scope or old provider records."""
from copy import deepcopy
import socket

import pytest
from jsonschema import ValidationError

from src.content_factory import creative_scoped_source_review_v1 as review
from tests.test_creative_goal_legal_usage_source_audit_v1 import authority, goal, ref_for
from tests.test_creative_legal_speech_scope_v1 import synthetic_scope, add_assertion, add_ambiguity


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **kw): raise AssertionError("scoped source tests must be offline")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


@pytest.fixture
def fixture(goal, authority):
    # Only this synthetic fixture is normalized to the existing fixed legal rule.
    goal["claims"][1]["text"] = authority["verified_legal_context"]["facts"][1]["paraphrase"]
    context = {**authority, "source_packet": {"schema": "synthetic/offline"},
        "user_goal_contract": {"constraints": [{"id": "U1", "text": "保留法律条件。"}]}}
    report = synthetic_scope(goal)
    add_assertion(report, review.legal.build_evidence_catalog(goal), "C:CC6")
    return goal, report, context


def usage(goal, ref, scoped):
    content = next(row["content"] for row in scoped["scope_observations"] if row["source_ref"] == ref)
    return {"kind": "legal_assertion", "quote": review.legal.build_evidence_catalog(goal)[ref]["quote"],
        "assertion_scope": content["assertion_scope"], "interpretation": content["proposition"],
        "authority_refs": ["L002"], "basis_relation": "supported", "treatment": "asserted",
        "actual_case_conditions": [], "reason": "Synthetic relation judgment only", "required_revision": ""}


def synthetic_review(goal, scoped, context):
    built = review.build_review_context(goal, scoped, context)
    return {"schema": review.VERSION, "native_goal_sha256": review.digest(goal), "scope_native_sha256": review.digest(scoped),
        "audit_context_sha256": built["manifest"]["audit_context_sha256"],
        "authority_context_sha256": built["manifest"]["authority_context_sha256"],
        "claim_checks": {row["id"]: {"status": "pass", "reason": "Synthetic provenance only", "required_revision": ""}
            for row in goal["claims"]},
        "legal_observations": [{"source_ref": ref, "usages": [usage(goal, ref, scoped)]}
            for ref in built["payload"]["scope_projection"]["legal_assertions"]], "scope_challenges": []}


def validate(document, fixture):
    goal, scoped, context = fixture
    return review.validate_review(document, goal, scoped, context,
        context_sha256=review.build_review_context(goal, scoped, context)["manifest"]["audit_context_sha256"])


def cc_usage(document):
    return next(row["usages"][0] for row in document["legal_observations"] if row["source_ref"] == "C:CC6")


def test_complete_provenance_scoped_legal_and_native_immutability(fixture):
    goal, scoped, context = fixture
    native = synthetic_review(*fixture)
    before = deepcopy((fixture, native))
    result = validate(native, fixture)
    assert result["accepted"] and result["route"] == "native_source_review_accepted"
    assert result["all_native_claim_checks_covered"] and result["scoped_legal_refs_covered"]
    assert result["legal_usage_citations"]["C:CC6"][0]["authority_citations"][0]["fact"] == context["verified_legal_context"]["facts"][1]
    assert not result["semantic_truth_deterministically_proven"] and not result["creative_quality_passed"]
    assert (fixture, native) == before


@pytest.mark.parametrize("status,route", [("fail", "complete_new_native_content_revision"), ("unknown", "halt_external_source_or_legal_unknown")])
def test_all_claim_provenance_is_independent_and_preserves_failure(fixture, status, route):
    native = synthetic_review(*fixture)
    native["claim_checks"]["CC6"].update(status=status, required_revision="Complete new native plan" if status == "fail" else "")
    result = validate(native, fixture)
    assert not result["accepted"] and result["route"] == route


@pytest.mark.parametrize("relation,assertion,treatment,expected", [
    ("supported", "general_rule", "asserted", "native_source_review_accepted"),
    ("contradicts", "general_rule", "asserted", "complete_new_native_content_revision"),
    ("not_covered", "general_rule", "asserted", "halt_external_source_or_legal_unknown"),
    ("unknown", "general_rule", "asserted", "halt_external_source_or_legal_unknown"),
    ("application_not_demonstrated", "case_application", "asserted", "halt_external_source_or_legal_unknown"),
    ("application_contradicted", "case_application", "asserted", "complete_new_native_content_revision"),
    ("supported", "case_application", "asserted", "native_source_review_accepted"),
    ("contradicts", "general_rule", "actually_corrected", "native_source_review_accepted")])
def test_unchanged_relation_policy_conditions_and_external_unknown_stops(fixture, relation, assertion, treatment, expected):
    next(row["content"] for row in fixture[1]["scope_observations"] if row["source_ref"] == "C:CC6")["assertion_scope"] = assertion
    native = synthetic_review(*fixture)
    row = cc_usage(native)
    row.update(basis_relation=relation, assertion_scope=assertion, treatment=treatment,
        required_revision="Complete new native plan" if expected == "complete_new_native_content_revision" else "")
    if relation in ("unknown", "not_covered"): row["authority_refs"] = []
    if relation in ("supported", "application_contradicted") and assertion == "case_application" or treatment == "actually_corrected":
        ref = ref_for(fixture[0], "whole_plan.beats.0.response")
        row["actual_case_conditions"] = [{"event_ref": ref, "quote": fixture[0]["whole_plan"]["beats"][0]["response"]}]
    result = validate(native, fixture)
    assert result["route"] == expected
    assert result["accepted"] is (expected == "native_source_review_accepted")


@pytest.mark.parametrize("fault", ["missing_claim", "extra_claim", "missing_legal", "duplicate_legal", "foreign_quote", "wrong_scope_sha",
    "wrong_authority_sha", "wrong_context", "wrong_goal", "unknown_authority", "duplicate_usage", "self_condition", "missing_condition", "claim_condition"])
def test_current_exact_identity_coverage_and_condition_contracts(fixture, fault):
    if fault in ("self_condition", "missing_condition", "claim_condition"):
        next(row["content"] for row in fixture[1]["scope_observations"] if row["source_ref"] == "C:CC6")["assertion_scope"] = "case_application"
    native = synthetic_review(*fixture)
    row = cc_usage(native)
    if fault == "missing_claim": native["claim_checks"].pop("UC1")
    elif fault == "extra_claim": native["claim_checks"]["extra"] = deepcopy(native["claim_checks"]["UC1"])
    elif fault == "missing_legal": native["legal_observations"].pop()
    elif fault == "duplicate_legal": native["legal_observations"][0] = deepcopy(native["legal_observations"][1])
    elif fault == "foreign_quote": row["quote"] = fixture[0]["claims"][1]["text"]
    elif fault in ("wrong_scope_sha", "wrong_authority_sha", "wrong_context", "wrong_goal"):
        native[{"wrong_scope_sha": "scope_native_sha256", "wrong_authority_sha": "authority_context_sha256", "wrong_context": "audit_context_sha256", "wrong_goal": "native_goal_sha256"}[fault]] = "0" * 64
    elif fault == "unknown_authority": row["authority_refs"] = ["unknown"]
    elif fault == "duplicate_usage": next(x for x in native["legal_observations"] if x["source_ref"] == "C:CC6")["usages"].append(deepcopy(row))
    elif fault == "self_condition":
        row.update(assertion_scope="case_application", actual_case_conditions=[{"event_ref": ref_for(fixture[0], "whole_plan.beats.0.stimulus"), "quote": row["quote"]}])
    elif fault == "missing_condition": row["assertion_scope"] = "case_application"
    else: row.update(assertion_scope="case_application", actual_case_conditions=[{"event_ref": "C:VL2", "quote": fixture[0]["claims"][1]["text"]}])
    before = deepcopy(native)
    with pytest.raises((ValidationError, review.ScopedSourceContractError, review.legal.LegalUsageContractError)): validate(native, fixture)
    assert native == before


def test_scope_challenge_stops_without_overwriting_original_native_classification(fixture):
    native = synthetic_review(*fixture)
    before = deepcopy(fixture[1])
    native["scope_challenges"] = [{"source_ref": "C:UC1", "quote": fixture[0]["claims"][0]["text"],
        "kind": "missed_legal_proposition", "candidate_proposition": "Synthetic candidate actually found in text", "reason": "Recheck the native scope"}]
    result = validate(native, fixture)
    assert not result["accepted"] and result["route"] == "scope_recheck_required"
    assert fixture[1] == before and fixture[1]["speech_act_by_ref"]["C:UC1"] == "F"


@pytest.mark.parametrize("fault", ["case_downgrade", "general_upgrade", "changed_proposition"])
def test_authority_stage_cannot_silently_redefine_scoped_assertion_or_bypass_case_conditions(fixture, fault):
    content = next(row["content"] for row in fixture[1]["scope_observations"] if row["source_ref"] == "C:CC6")
    content["assertion_scope"] = "case_application" if fault == "case_downgrade" else "general_rule"
    native = synthetic_review(*fixture)
    row = cc_usage(native)
    if fault == "case_downgrade": row["assertion_scope"] = "general_rule"  # Previously accepted supported + no conditions.
    elif fault == "general_upgrade": row["assertion_scope"] = "case_application"
    else: row["interpretation"] = "A different legal proposition despite exactly the same quote"
    with pytest.raises(review.ScopedSourceContractError): validate(native, fixture)


def test_disagreement_with_case_scope_requires_challenge_and_retains_original_meaning(fixture):
    content = next(row["content"] for row in fixture[1]["scope_observations"] if row["source_ref"] == "C:CC6")
    content["assertion_scope"] = "case_application"
    native = synthetic_review(*fixture)
    row = cc_usage(native)
    row["basis_relation"] = "application_not_demonstrated"
    native["scope_challenges"] = [{"source_ref": "C:CC6", "quote": content["quote"], "kind": "misread_scoped_assertion",
        "candidate_proposition": "Reviewer proposes a general-rule interpretation", "reason": "Do not silently downgrade the actual native scope"}]
    before = deepcopy(fixture[1])
    result = validate(native, fixture)
    assert result["route"] == "scope_recheck_required" and not result["accepted"] and result["uncertainties"]
    assert fixture[1] == before and row["assertion_scope"] == "case_application" and row["interpretation"] == content["proposition"]


def test_authority_copies_the_full_valid_scope_proposition_without_truncating_to_old_atom_limit(fixture):
    content = next(row["content"] for row in fixture[1]["scope_observations"] if row["source_ref"] == "C:CC6")
    content["proposition"] = "Synthetic bounded proposition. " * 10
    assert 240 < len(content["proposition"]) <= 400
    native = synthetic_review(*fixture)
    assert cc_usage(native)["interpretation"] == content["proposition"]
    assert validate(native, fixture)["accepted"]  # Structural compatibility, no semantic proof.


def test_scope_with_true_ambiguity_cannot_enter_authority_review(fixture):
    goal, scoped, context = fixture
    ref = ref_for(goal, "whole_plan.beats.0.stimulus")
    add_ambiguity(scoped, review.legal.build_evidence_catalog(goal), ref)
    with pytest.raises(review.scope.ScopeContractError): review.build_review_context(goal, scoped, context)


@pytest.mark.parametrize("fault", ["changed_fact", "two_origins", "wrong_origin", "missing_context", "context_type"])
def test_fixed_verified_law_and_complete_context_never_rewritten(fixture, fault):
    goal, scoped, context = fixture
    if fault == "changed_fact": goal["claims"][1]["text"] += "公司提出才行。"
    elif fault == "two_origins": goal["claims"][1]["origin_ids"] = ["L001", "L002"]
    elif fault == "wrong_origin": goal["claims"][1]["origin_ids"] = ["L001"]
    elif fault == "missing_context": context.pop("source_packet")
    else: context["user_goal_contract"] = None
    before = deepcopy(fixture)
    with pytest.raises(review.ScopedSourceContractError): review.build_review_context(goal, scoped, context)
    assert fixture == before


def test_no_previous_native_source_report_admission_is_used(fixture, monkeypatch):
    native = synthetic_review(*fixture)
    def deny(*a, **kw): raise AssertionError("cannot fabricate/adopt old source6 native")
    monkeypatch.setattr(review.legal, "validate_source", deny)
    assert validate(native, fixture)["accepted"]
