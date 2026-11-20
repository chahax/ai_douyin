"""Sparse native partition and unchanged scalar gate, without report conversion."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

from jsonschema import Draft202012Validator, ValidationError
import pytest

from src.content_factory import creative_goal_legal_usage_source_audit_v5 as audit
from src.content_factory import creative_goal_legal_usage_source_audit_v4 as frozen
from tests.test_creative_goal_legal_usage_source_audit_v1 import authority, goal, ref_for

CONTEXT = "d" * 64
PROJECT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **kw): raise AssertionError("source5 must be offline")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def source_usages(document, ref):
    return next(row["usages"] for row in document["source_observations"] if row["source_ref"] == ref)


def _usages(document, ref):
    for row in document["source_observations"]:
        if row["source_ref"] == ref: return row["usages"]
    document["no_legal_refs"].remove(ref)
    document["source_observations"].append({"source_ref": ref, "usages": []})
    return document["source_observations"][-1]["usages"]


def add_legal_usage(document, goal, ref, *, relation="supported", scope="general_rule", treatment="asserted",
                    actual_case_conditions=None):
    row = {"kind": "legal_assertion", "quote": audit.build_evidence_catalog(goal)[ref]["quote"],
        "assertion_scope": scope, "interpretation": "Synthetic legal interpretation, not local extraction",
        "authority_refs": ["L002"] if relation not in ("not_covered", "unknown") else [],
        "basis_relation": relation, "treatment": treatment, "actual_case_conditions": deepcopy(actual_case_conditions or []),
        "reason": "Synthetic reported relation to exercise the policy",
        "required_revision": "Complete native revision" if relation in ("contradicts", "application_contradicted") and treatment == "asserted" else ""}
    _usages(document, ref).append(row)
    return row


def add_uncertain_usage(document, goal, ref):
    row = {"kind": "uncertain", "quote": audit.build_evidence_catalog(goal)[ref]["quote"],
        "interpretation": "Unresolved legal meaning, do not put in negative refs", "reason": "Synthetic meaningful uncertainty"}
    _usages(document, ref).append(row)
    return row


def synthetic_source(goal, authority, context=CONTEXT):
    document = {"schema": audit.VERSION, "goal_sha256": audit.digest(goal), "audit_context_sha256": context,
        "authority_context_sha256": audit.digest(authority), "claim_checks": {claim["id"]: {
            "status": "pass", "reason": "Synthetic provenance judgment", "required_revision": ""} for claim in goal["claims"]},
        "source_observations": [], "no_legal_refs": list(audit.build_evidence_catalog(goal))}
    for claim in goal["claims"]:
        if claim["kind"] == "verified_legal":
            row = add_legal_usage(document, goal, "C:" + claim["id"])
            row["authority_refs"] = list(claim["origin_ids"])
    return document


def actual_witness(goal, path="whole_plan.beats.0.response", quote=None):
    ref = ref_for(goal, path)
    return {"event_ref": ref, "quote": quote or audit.build_evidence_catalog(goal)[ref]["quote"]}


def validate(document, goal, authority):
    return audit.validate_source(document, goal, authority, context_sha256=CONTEXT)


def test_sparse_full_partition_and_claim_checks_without_frame_or_negative_semantic_proof(goal, authority):
    document = synthetic_source(goal, authority)
    before = deepcopy((document, goal, authority))
    result = validate(document, goal, authority)
    assert result["accepted"] and set(result) == audit.DECISION_FIELDS
    assert result["sparse_partition_verified"] and result["legal_usage_coverage_complete"]
    assert result["detailed_source_count"] + result["no_legal_source_count"] == len(audit.build_evidence_catalog(goal))
    assert result["no_legal_refs"] == document["no_legal_refs"]
    assert set(result["usage_gates"]) == {row["source_ref"] for row in document["source_observations"]}
    for flag in ("negative_classification_proven", "sparse_semantic_coverage_proven", "legal_semantic_extraction_proven",
                 "semantic_occurrence_verified", "semantic_occurrence_proven", "human_approved"):
        assert result[flag] is False
    schema = audit.build_source_schema(goal, authority, context_sha256=CONTEXT)
    Draft202012Validator.check_schema(schema)
    assert set(schema["properties"]["claim_checks"]["properties"]) == {row["id"] for row in goal["claims"]}
    assert set(schema["properties"]["no_legal_refs"]["items"]["enum"]) == set(audit.build_evidence_catalog(goal))
    assert "non_legal_context" not in schema["$defs"] and "interpretation_frame" not in schema["$defs"]
    assert "interpretation_frame_evidence" not in schema["$defs"]["legal_assertion"]["properties"]
    assert (document, goal, authority) == before


@pytest.mark.parametrize("fault", ["missing_negative", "duplicate_negative", "duplicate_detailed", "overlap", "foreign_ref",
    "verified_negative", "empty_usages", "missing_claim", "extra_claim", "old_version", "wrong_goal", "wrong_context", "wrong_authority"])
def test_exact_partition_and_three_sha_are_never_silently_repaired(goal, authority, fault):
    document = synthetic_source(goal, authority)
    if fault == "missing_negative": document["no_legal_refs"].pop()
    elif fault == "duplicate_negative": document["no_legal_refs"].append(document["no_legal_refs"][0])
    elif fault == "duplicate_detailed": document["source_observations"].append(deepcopy(document["source_observations"][0]))
    elif fault == "overlap": document["no_legal_refs"].append(document["source_observations"][0]["source_ref"])
    elif fault == "foreign_ref": document["no_legal_refs"][0] = "G999"
    elif fault == "verified_negative":
        ref = document["source_observations"].pop()["source_ref"]
        document["no_legal_refs"].append(ref)
        add_uncertain_usage(document, goal, "C:CC6")  # Same array length cannot replace verified C.
    elif fault == "empty_usages": document["source_observations"][0]["usages"] = []
    elif fault == "missing_claim": document["claim_checks"].pop("CC6")
    elif fault == "extra_claim": document["claim_checks"]["extra"] = deepcopy(document["claim_checks"]["CC6"])
    elif fault == "old_version": document["schema"] = frozen.VERSION
    else: document[{"wrong_goal": "goal_sha256", "wrong_context": "audit_context_sha256", "wrong_authority": "authority_context_sha256"}[fault]] = "0" * 64
    before = deepcopy(document)
    with pytest.raises((ValidationError, audit.LegalUsageContractError)): validate(document, goal, authority)
    assert document == before


@pytest.mark.parametrize("relation,scope,treatment,gate", [
    ("supported", "general_rule", "asserted", "clear"), ("contradicts", "general_rule", "asserted", "fail"),
    ("not_covered", "general_rule", "asserted", "unknown"), ("unknown", "general_rule", "asserted", "unknown"),
    ("application_not_demonstrated", "case_application", "asserted", "unknown"),
    ("application_contradicted", "case_application", "asserted", "fail"), ("supported", "case_application", "asserted", "clear"),
    ("contradicts", "general_rule", "actually_corrected", "clear"),
    ("application_contradicted", "case_application", "actually_corrected", "clear"),
    ("not_covered", "general_rule", "actually_corrected", "unknown")])
def test_same_finite_relation_policy_conditions_and_corrections(goal, authority, relation, scope, treatment, gate):
    document = synthetic_source(goal, authority)
    conditions = [actual_witness(goal)] if treatment == "actually_corrected" or scope == "case_application" and relation != "application_not_demonstrated" else []
    usage = add_legal_usage(document, goal, "C:CC6", relation=relation, scope=scope, treatment=treatment, actual_case_conditions=conditions)
    result = validate(document, goal, authority)
    assert result["usage_gates"]["C:CC6"][0]["gate"] == gate
    assert result["accepted"] is (gate == "clear")
    findings = result["findings"] if gate == "fail" else result["uncertainties"] if gate == "unknown" else []
    if findings: assert findings[0]["native_usage"] == usage


@pytest.mark.parametrize("fault", ["missing_condition", "cross_quote", "self_condition", "claim_condition", "purpose_condition",
    "frame_extra", "nonlegal_detail", "supported_corrected", "missing_authority", "fail_without_revision"])
def test_case_or_correction_evidence_limits_and_removed_fields(goal, authority, fault):
    document = synthetic_source(goal, authority)
    row = add_legal_usage(document, goal, "C:CC6")
    if fault == "missing_condition": row["assertion_scope"] = "case_application"
    elif fault == "cross_quote": row["actual_case_conditions"] = [actual_witness(goal, quote="串到别行的引文")]
    elif fault == "self_condition": row.update(assertion_scope="case_application", actual_case_conditions=[actual_witness(goal, quote=row["quote"])])
    elif fault == "claim_condition": row["actual_case_conditions"] = [{"event_ref": "C:VL2", "quote": goal["claims"][1]["text"]}]
    elif fault == "purpose_condition": row["actual_case_conditions"] = [actual_witness(goal, "whole_plan.beats.0.goal")]
    elif fault == "frame_extra": row["interpretation_frame_evidence"] = []
    elif fault == "nonlegal_detail": row.update(kind="non_legal_context", pragmatic_function="case_offer_or_promise")
    elif fault == "supported_corrected": row.update(treatment="actually_corrected", actual_case_conditions=[actual_witness(goal)])
    elif fault == "missing_authority": row["authority_refs"] = []
    else: row.update(basis_relation="contradicts", required_revision="")
    with pytest.raises((ValidationError, audit.LegalUsageContractError)): validate(document, goal, authority)


def test_unknown_never_clears_and_future_event_ref_is_not_occurrence_proof(goal, authority):
    goal["whole_plan"]["beats"][0]["response"] = "我明天会去咨询，今晚还没有咨询。"
    ref = ref_for(goal, "whole_plan.beats.0.response")
    document = synthetic_source(goal, authority)
    add_legal_usage(document, goal, ref, scope="case_application", relation="application_not_demonstrated",
                    actual_case_conditions=[actual_witness(goal)])
    result = validate(document, goal, authority)
    assert not result["accepted"] and result["uncertainties"][0]["gate"] == "unknown"
    assert ref not in result["no_legal_refs"] and not result["semantic_occurrence_proven"]
    assert audit.build_evidence_role_catalog(goal)["event_ref_position_only"]
    assert "明天咨询" in audit.SOURCE_REVIEW_RULE
    document = synthetic_source(goal, authority)
    add_uncertain_usage(document, goal, ref)
    document["no_legal_refs"].append(ref)
    with pytest.raises(audit.LegalUsageContractError): validate(document, goal, authority)


def test_mixed_double_signature_negative_classification_cannot_prove_extraction(goal, authority):
    goal["whole_plan"]["beats"][0]["stimulus"] = "我愿意等你谈；两边都签了才算说定，空着就是没说定。"
    ref = ref_for(goal, "whole_plan.beats.0.stimulus")
    document = synthetic_source(goal, authority)
    shape_only = validate(document, goal, authority)
    assert ref in shape_only["no_legal_refs"] and not shape_only["negative_classification_proven"]
    assert not shape_only["mixed_utterance_extraction_proven"]  # Local code does not judge Chinese semantics.
    uncertain = add_uncertain_usage(document, goal, ref)
    uncertain["quote"] = "两边都签了才算说定，空着就是没说定"
    result = validate(document, goal, authority)
    assert not result["accepted"] and result["uncertainties"][0]["native_usage"] == uncertain
    assert "两边都签了才算说定" in audit.SOURCE_REVIEW_RULE


def test_only_old_pure_scalar_gate_may_be_called(goal, authority, monkeypatch):
    def deny(*a, **kw): raise AssertionError("old native report schema or admission called")
    for module in (frozen, audit.exact, audit.relation_policy):
        for name in ("build_source_schema", "validate_source"): monkeypatch.setattr(module, name, deny)
    assert validate(synthetic_source(goal, authority), goal, authority)["accepted"]


def test_original617_bad_frame_report_is_never_adapted_into_source5():
    root = PROJECT / "data/production_trials/goal_context_text_production_20261013/round_24"
    path = root / "call_617_goal_source_audit_01.json"
    original = path.read_bytes();receipt = json.loads(original)
    goal = json.loads((root / "call_616_goal_plan_28.json").read_text(encoding="utf-8"))["output"]
    payload = json.loads(receipt["request"]["messages"][1]["content"])
    authority = {key: payload[key] for key in ("verified_legal_context", "origin_catalog")}
    assert receipt["status"] == "contract_rejected" and receipt["output"]["schema"] == frozen.VERSION
    with pytest.raises(frozen.LegalUsageContractError) as original_error:
        frozen.validate_source(receipt["output"], goal, authority, context_sha256=frozen.digest(payload))
    assert original_error.value.path == "/source_observations/152/usages/0/interpretation_frame_evidence/1/quote"
    assert receipt["output"]["source_observations"][152]["source_ref"] == "C:VL3"
    for native in (receipt["output"], {**deepcopy(receipt["output"]), "schema": audit.VERSION}):
        with pytest.raises((ValidationError, audit.LegalUsageContractError)):
            audit.validate_source(native, goal, authority, context_sha256=audit.digest(payload))
    assert path.read_bytes() == original


@pytest.mark.parametrize("field,limit", [("quote", audit.MAX_QUOTE_CHARS), ("interpretation", audit.MAX_INTERPRETATION_CHARS),
    ("reason", audit.MAX_REASON_CHARS), ("required_revision", audit.MAX_REVISION_CHARS)])
def test_sparse_detail_output_bounds_reject_instead_of_truncate(goal, authority, field, limit):
    document = synthetic_source(goal, authority)
    add_legal_usage(document, goal, "C:CC6")[field] = "长" * (limit + 1)
    before = deepcopy(document)
    with pytest.raises(ValidationError): validate(document, goal, authority)
    assert document == before


def test_sparse_detail_capacity_does_not_allow_omitting_law_propositions(goal, authority):
    document = synthetic_source(goal, authority)
    for index in range(audit.MAX_USAGES_PER_SOURCE + 1):
        add_legal_usage(document, goal, "C:CC6")["interpretation"] += str(index)
    with pytest.raises(ValidationError): validate(document, goal, authority)
