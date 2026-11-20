"""Contract tests only; fixtures never constitute semantic or production proof."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket
import pytest
from jsonschema import Draft202012Validator, ValidationError
from src.content_factory import creative_goal_legal_usage_source_audit_v6 as audit
from tests.test_creative_goal_legal_usage_source_audit_v1 import authority, goal, ref_for

CONTEXT = "d" * 64
PROJECT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*a, **kw): raise AssertionError("source6 tests cannot dispatch")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


def synthetic_source(goal, authority, context=CONTEXT):
    """Wholly synthetic new-version fixture, not a converted provider result."""
    document = {"schema": audit.VERSION, "goal_sha256": audit.digest(goal), "audit_context_sha256": context,
        "authority_context_sha256": audit.digest(authority), "claim_checks": {claim["id"]: {
            "status": "pass", "reason": "Synthetic provenance judgment", "required_revision": ""} for claim in goal["claims"]},
        "source_observations": [], "speech_act_by_ref": {ref: "F" for ref in audit.build_evidence_catalog(goal)}}
    for claim in goal["claims"]:
        if claim["kind"] == "verified_legal":
            add_legal_usage(document, goal, "C:" + claim["id"], authority_refs=claim["origin_ids"])
    return document


def add_legal_usage(document, goal, ref, *, relation="supported", scope="general_rule", treatment="asserted", conditions=None, authority_refs=None):
    document["speech_act_by_ref"][ref] = "L"
    row = {"kind": "legal_assertion", "quote": audit.build_evidence_catalog(goal)[ref]["quote"],
        "assertion_scope": scope, "interpretation": "Synthetic asserted legal proposition, not program extraction",
        "authority_refs": list(authority_refs) if authority_refs is not None else (["L002"] if relation not in ("unknown", "not_covered") else []),
        "basis_relation": relation, "treatment": treatment, "actual_case_conditions": deepcopy(conditions or []),
        "reason": "Synthetic relation for unchanged gate", "required_revision": "Complete native revision" if relation in ("contradicts", "application_contradicted") and treatment == "asserted" else ""}
    found = next((item for item in document["source_observations"] if item["source_ref"] == ref), None)
    if found is None:
        found = {"source_ref": ref, "usages": []}; document["source_observations"].append(found)
    found["usages"].append(row)
    return row


def add_uncertain_usage(document, goal, ref):
    document["speech_act_by_ref"][ref] = "U"
    row = {"kind": "uncertain", "quote": audit.build_evidence_catalog(goal)[ref]["quote"],
        "interpretation": "Synthetic unresolved legal proposition", "reason": "Classification cannot erase uncertainty"}
    document["source_observations"].append({"source_ref": ref, "usages": [row]})
    return row


def validate(document, goal, authority):
    return audit.validate_source(document, goal, authority, context_sha256=CONTEXT)


def test_fixed_primitive_coverage_complete_claims_no_old_partition_or_semantic_proof(goal, authority):
    document = synthetic_source(goal, authority)
    before = deepcopy((document, goal, authority))
    result = validate(document, goal, authority)
    assert result["accepted"] and set(result) == audit.DECISION_FIELDS
    assert result["speech_act_key_coverage_verified"] and result["speech_act_detail_alignment_verified"]
    assert result["speech_act_by_ref"] == document["speech_act_by_ref"]
    assert "no_legal_refs" not in result
    schema = audit.build_source_schema(goal, authority, context_sha256=CONTEXT)
    acts = schema["properties"]["speech_act_by_ref"]
    assert set(acts["properties"]) == set(acts["required"]) == set(audit.build_evidence_catalog(goal))
    assert acts["additionalProperties"] is False
    assert set(schema["properties"]["claim_checks"]["properties"]) == {row["id"] for row in goal["claims"]}
    for flag in ("semantic_truth_deterministically_proven", "pragmatic_classification_proven", "mixed_utterance_extraction_proven",
                 "speech_act_semantic_classification_proven", "legal_semantic_extraction_proven", "human_approved",
                 "semantic_occurrence_proven", "negative_classification_proven"):
        assert result[flag] is False
    assert (document, goal, authority) == before


@pytest.mark.parametrize("fault", ["missing_key", "foreign_key", "invalid_class", "object_class", "missing_detail", "extra_detail",
    "duplicate_detail", "uncertain_without_usage", "legal_with_uncertain", "verified_factual", "missing_claim", "old_negative_array",
    "wrong_goal", "wrong_context", "wrong_authority", "old_version"])
def test_coverage_identity_and_alignment_rejected_without_repair(goal, authority, fault):
    document = synthetic_source(goal, authority)
    ref = next(ref for ref in document["speech_act_by_ref"] if ref.startswith("G"))
    if fault == "missing_key": del document["speech_act_by_ref"][ref]
    elif fault == "foreign_key": document["speech_act_by_ref"]["G999"] = "F"
    elif fault == "invalid_class": document["speech_act_by_ref"][ref] = "employment_topic"
    elif fault == "object_class": document["speech_act_by_ref"][ref] = {"kind": "factual_description"}
    elif fault == "missing_detail": document["speech_act_by_ref"][ref] = "L"
    elif fault == "extra_detail":
        add_legal_usage(document, goal, ref); document["speech_act_by_ref"][ref] = "R"
    elif fault == "duplicate_detail": document["source_observations"].append(deepcopy(document["source_observations"][0]))
    elif fault == "uncertain_without_usage":
        add_legal_usage(document, goal, ref); document["speech_act_by_ref"][ref] = "U"
    elif fault == "legal_with_uncertain":
        add_uncertain_usage(document, goal, ref); document["speech_act_by_ref"][ref] = "L"
    elif fault == "verified_factual": document["speech_act_by_ref"][document["source_observations"][0]["source_ref"]] = "F"
    elif fault == "missing_claim": document["claim_checks"].pop(next(iter(document["claim_checks"])))
    elif fault == "old_negative_array": document["no_legal_refs"] = [ref]
    elif fault == "old_version": document["schema"] = audit.prior.VERSION
    else: document[{"wrong_goal":"goal_sha256", "wrong_context":"audit_context_sha256", "wrong_authority":"authority_context_sha256"}[fault]] = "0" * 64
    before = deepcopy(document)
    with pytest.raises((ValidationError, audit.LegalUsageContractError)): validate(document, goal, authority)
    assert document == before


@pytest.mark.parametrize("relation,scope,treatment,gate", [
    ("supported", "general_rule", "asserted", "clear"), ("contradicts", "general_rule", "asserted", "fail"),
    ("not_covered", "general_rule", "asserted", "unknown"), ("unknown", "general_rule", "asserted", "unknown"),
    ("application_not_demonstrated", "case_application", "asserted", "unknown"),
    ("application_contradicted", "case_application", "asserted", "fail"), ("supported", "case_application", "asserted", "clear"),
    ("contradicts", "general_rule", "actually_corrected", "clear")])
def test_unchanged_relation_policy_still_requires_actual_case_or_correction(goal, authority, relation, scope, treatment, gate):
    document = synthetic_source(goal, authority)
    witness = ref_for(goal, "whole_plan.beats.0.response")
    conditions = [{"event_ref": witness, "quote": audit.build_evidence_catalog(goal)[witness]["quote"]}] if (
        treatment == "actually_corrected" or scope == "case_application" and relation != "application_not_demonstrated") else []
    row = add_legal_usage(document, goal, "C:CC6", relation=relation, scope=scope, treatment=treatment, conditions=conditions)
    result = validate(document, goal, authority)
    assert result["usage_gates"]["C:CC6"][0]["gate"] == gate
    assert result["accepted"] is (gate == "clear")
    unresolved = result["findings"] + result["uncertainties"]
    if gate != "clear": assert any(item["native_usage"] == row for item in unresolved)


@pytest.mark.parametrize("fault", ["cross_quote", "noncontinuous_quote", "condition_cross_quote", "claim_condition", "missing_condition", "overlong_interpretation"])
def test_exact_current_quotes_and_case_preconditions_are_not_weakened(goal, authority, fault):
    document = synthetic_source(goal, authority)
    row = add_legal_usage(document, goal, "C:CC6")
    if fault == "cross_quote": row["quote"] = "Only another field contains this quote."
    elif fault == "noncontinuous_quote":
        own = row["quote"]; row["quote"] = own[::2]
    elif fault == "condition_cross_quote": row["actual_case_conditions"] = [{"event_ref": ref_for(goal,"whole_plan.beats.0.response"), "quote": "Not its own quote"}]
    elif fault == "claim_condition": row["actual_case_conditions"] = [{"event_ref":"C:VL2", "quote":goal["claims"][1]["text"]}]
    elif fault == "missing_condition": row["assertion_scope"] = "case_application"
    else: row["interpretation"] = "x" * (audit.MAX_INTERPRETATION_CHARS + 1)
    with pytest.raises((ValidationError, audit.LegalUsageContractError)): validate(document, goal, authority)


def test_mixed_legal_condition_requires_model_extraction_not_fake_program_proof(goal, authority):
    goal["whole_plan"]["beats"][0]["stimulus"] = "我愿意等你谈；两边都签了才算说定，空着就是没说定。"
    ref = ref_for(goal, "whole_plan.beats.0.stimulus")
    document = synthetic_source(goal, authority)
    document["speech_act_by_ref"][ref] = "R"
    shape_only = validate(document, goal, authority)
    assert shape_only["accepted"] and not shape_only["mixed_utterance_extraction_proven"]
    add_uncertain_usage(document, goal, ref)
    result = validate(document, goal, authority)
    assert not result["accepted"] and result["uncertainties"][0]["gate"] == "unknown"
    assert "两边都签了才算说定" in audit.SOURCE_REVIEW_RULE


def test_no_old_native_admission_or_report_constructor(goal, authority, monkeypatch):
    def deny(*a, **kw): raise AssertionError("old native report admission called")
    for module in (audit.exact, audit.relation_policy, audit.prior):
        monkeypatch.setattr(module, "validate_source", deny)
    assert validate(synthetic_source(goal, authority), goal, authority)["accepted"]


def test_actual_619_omitted_g007_is_rejected_unchanged_and_new_directory_has_key():
    root = PROJECT / "data/production_trials/goal_context_text_production_20261013/round_25"
    oldpath = root / "call_619_goal_source_audit_01.json"
    original = oldpath.read_bytes(); receipt = json.loads(original)
    native = json.loads((root / "goals/native_01.json").read_text(encoding="utf-8"))
    payload = json.loads(receipt["request"]["messages"][1]["content"])
    authority = {key: payload[key] for key in ("verified_legal_context", "origin_catalog")}
    schema = audit.build_source_schema(native, authority, context_sha256=audit.digest(payload))
    assert "G007" in schema["properties"]["speech_act_by_ref"]["required"]
    assert len(schema["properties"]["speech_act_by_ref"]["required"]) == 175
    with pytest.raises(ValidationError):
        audit.validate_source(receipt["output"], native, authority, context_sha256=audit.digest(payload))
    assert oldpath.read_bytes() == original
