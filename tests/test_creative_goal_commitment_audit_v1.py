"""Offline source-bound focused relations, including a real-575 benchmark."""
from copy import deepcopy
import json
from pathlib import Path
import socket

from jsonschema import Draft202012Validator, ValidationError
import pytest

from src.content_factory import creative_goal_commitment_audit_v1 as audit

CONTEXT = "a" * 64
PROJECT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("focused audit tests must not contact any provider")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


@pytest.fixture
def goal():
    return {"claims": [
        {"id": "CC_ORDER", "kind": "creative_choice", "text": "签名之后才亮出记录。"},
        {"id": "CC_RETURN", "kind": "creative_choice", "text": "原件由员工保留。"},
        {"id": "CC_UNUSED", "kind": "creative_choice", "text": "没有明确使用的选择。"},
        {"id": "INF_MOTIVE", "kind": "inference", "text": "对手需要她明天到场。"}],
        "whole_plan": {"characters": [{"id": "worker", "name": "员工"},
                                      {"id": "boss", "name": "老板"}],
            "props": [{"id": "paper", "description": "原件", "owner_character_id": "boss"}],
            "scenes": [{"id": "office", "description": "办公室"}],
            "beats": [
                {"id": "b1", "stimulus": "员工先说自己有记录。", "response": "老板随后写下签名。",
                 "claim_refs": ["CC_ORDER", "CC_RETURN", "INF_MOTIVE"]},
                {"id": "b2", "response": "员工收起原件。", "claim_refs": ["CC_RETURN"]}],
            "ending": {"visible_consequence": "原件在员工包里。", "claim_refs": ["CC_RETURN"]}}}


def synthetic(goal):
    """A new synthetic document; never convert an older provider review."""
    checks = {}
    for identifier, usage in audit.build_commitment_usage_catalog(goal).items():
        checks[identifier] = {"claim_ref": usage["claim_ref"],
            "literal_requirement": "Synthetic literal interpretation, not a semantic judgment",
            "actual_usages": {key: {
                "evidence_refs": [row["evidence_refs"][0]],
                "actual_interpretation": "Synthetic observed action interpretation",
                "relationship": "compatible"} for key, row in usage["usages"].items()},
            "status": "pass", "reason": "Synthetic structure-only fixture",
            "required_revision": "", "counterevidence_refs": []}
    return {"schema": audit.VERSION, "goal_sha256": audit.digest(goal),
            "audit_context_sha256": CONTEXT, "commitment_checks": checks}


def validate(document, goal):
    return audit.validate_commitment_audit(document, goal, context_sha256=CONTEXT)


def set_relation(document, identifier, relation, status):
    row = document["commitment_checks"][identifier]
    first = next(iter(row["actual_usages"].values()))
    first["relationship"] = relation
    row["status"] = status
    row["required_revision"] = "Submit complete native plan revision" if status == "fail" else ""
    return row


def test_complete_native_identity_exact_coverage_and_no_input_mutation(goal):
    document = synthetic(goal)
    before, original = deepcopy(document), deepcopy(goal)
    schema = audit.build_commitment_audit_schema(goal, context_sha256=CONTEXT)
    Draft202012Validator.check_schema(schema)
    result = validate(document, goal)
    assert set(document["commitment_checks"]) == {"CC_ORDER", "CC_RETURN"}
    assert set(document["commitment_checks"]["CC_RETURN"]["actual_usages"]) == {"beat:b1", "beat:b2", "ending"}
    assert result["valid"] and result["accepted"]
    assert result["commitment_usage_coverage_complete"] and result["reported_relations_self_consistent"]
    assert result["native_goal_sha256"] == audit.digest(goal)
    assert result["audit_sha256"] == audit.digest(document)
    assert result["citations"]["CC_ORDER"]["claim"]["quote"] == goal["claims"][0]["text"]
    assert not result["semantic_truth_deterministically_proven"]
    assert not result["commitment_semantic_extraction_proven"] and not result["human_approved"]
    assert document == before and goal == original


@pytest.mark.parametrize("relation", ["contradicts", "not_demonstrated"])
def test_definite_reported_relation_validly_fails(goal, relation):
    document = synthetic(goal)
    set_relation(document, "CC_ORDER", relation, "fail")
    result = validate(document, goal)
    assert not result["accepted"] and result["findings"][0]["check"] == "CC_ORDER"
    assert result["uncertainties"] == []


@pytest.mark.parametrize("relation,status", [("contradicts", "pass"), ("contradicts", "unknown"),
                                             ("not_demonstrated", "pass"), ("not_demonstrated", "unknown"),
                                             ("unknown", "pass")])
def test_schema_rejects_relationship_status_masking(goal, relation, status):
    document = synthetic(goal)
    set_relation(document, "CC_ORDER", relation, status)
    with pytest.raises(ValidationError):
        validate(document, goal)


def test_unknown_usage_blocks_acceptance(goal):
    document = synthetic(goal)
    set_relation(document, "CC_ORDER", "unknown", "unknown")
    result = validate(document, goal)
    assert not result["accepted"] and not result["findings"]
    assert result["uncertainties"][0]["check"] == "CC_ORDER"


def test_definite_failure_has_priority_over_other_unknown_usage(goal):
    document = synthetic(goal)
    row = set_relation(document, "CC_RETURN", "contradicts", "fail")
    row["actual_usages"]["beat:b2"]["relationship"] = "unknown"
    assert validate(document, goal)["findings"][0]["check"] == "CC_RETURN"


@pytest.mark.parametrize("status", ["fail", "unknown"])
def test_compatible_own_usage_may_have_cross_commitment_counterevidence(goal, status):
    document = synthetic(goal)
    row = document["commitment_checks"]["CC_ORDER"]
    row.update(status=status, counterevidence_refs=["C:CC_RETURN"],
               required_revision="Complete native plan revision" if status == "fail" else "")
    result = validate(document, goal)
    assert not result["accepted"]
    assert result["counterevidence_citations"]["CC_ORDER"][0]["source_ref"] == "C:CC_RETURN"


@pytest.mark.parametrize("status", ["fail", "unknown"])
def test_wider_nonpass_cannot_be_asserted_without_counterevidence(goal, status):
    document = synthetic(goal)
    row = document["commitment_checks"]["CC_ORDER"]
    row.update(status=status, required_revision="Complete native plan revision" if status == "fail" else "")
    with pytest.raises(audit.CommitmentReportContractError, match="cross-source counterevidence"):
        validate(document, goal)


def test_unknown_relation_may_be_failed_by_an_independent_cross_counterexample(goal):
    document = synthetic(goal)
    row = set_relation(document, "CC_ORDER", "unknown", "fail")
    row["counterevidence_refs"] = ["C:CC_RETURN"]
    assert not validate(document, goal)["accepted"]


@pytest.mark.parametrize("fault", ["missing_commitment", "extra_commitment", "missing_usage", "extra_usage",
    "wrong_c", "c_used_as_g", "cross_usage_g", "empty_refs", "duplicate_refs", "bogus_ref",
    "counter_bogus", "counter_duplicates", "pass_counter", "pass_revision", "fail_empty_revision",
    "blank_literal", "blank_actual", "blank_reason", "unknown_relation", "extra_field",
    "wrong_schema", "wrong_goal", "wrong_context"])
def test_source_coverage_types_and_verdict_boundaries(goal, fault):
    document = synthetic(goal)
    row = document["commitment_checks"]["CC_ORDER"]
    usage = row["actual_usages"]["beat:b1"]
    if fault == "missing_commitment": document["commitment_checks"].pop("CC_ORDER")
    elif fault == "extra_commitment": document["commitment_checks"]["CC_UNUSED"] = deepcopy(row)
    elif fault == "missing_usage": row["actual_usages"].pop("beat:b1")
    elif fault == "extra_usage": row["actual_usages"]["beat:b2"] = deepcopy(usage)
    elif fault == "wrong_c": row["claim_ref"] = "C:CC_RETURN"
    elif fault == "c_used_as_g": usage["evidence_refs"] = ["C:CC_ORDER"]
    elif fault == "cross_usage_g": usage["evidence_refs"] = document["commitment_checks"]["CC_RETURN"]["actual_usages"]["beat:b2"]["evidence_refs"]
    elif fault == "empty_refs": usage["evidence_refs"] = []
    elif fault == "duplicate_refs": usage["evidence_refs"] *= 2
    elif fault == "bogus_ref": usage["evidence_refs"] = ["G999"]
    elif fault == "counter_bogus": row["counterevidence_refs"] = ["C:OLD"]
    elif fault == "counter_duplicates": row.update(status="fail", required_revision="new native goal", counterevidence_refs=["C:CC_RETURN"] * 2)
    elif fault == "pass_counter": row["counterevidence_refs"] = ["C:CC_RETURN"]
    elif fault == "pass_revision": row["required_revision"] = "Rewrite despite pass"
    elif fault == "fail_empty_revision": row.update(status="fail", counterevidence_refs=["C:CC_RETURN"])
    elif fault == "blank_literal": row["literal_requirement"] = " "
    elif fault == "blank_actual": usage["actual_interpretation"] = "\n"
    elif fault == "blank_reason": row["reason"] = " "
    elif fault == "unknown_relation": usage["relationship"] = "maybe"
    elif fault == "extra_field": row["patched_old_review"] = True
    elif fault == "wrong_schema": document["schema"] = "creative_goal_drama_audit/v10"
    elif fault == "wrong_goal": document["goal_sha256"] = "0" * 64
    else: document["audit_context_sha256"] = "0" * 64
    with pytest.raises(ValidationError):
        validate(document, goal)


@pytest.mark.parametrize("context", [None, 7, "", "a" * 63, "A" * 64, "g" * 64])
def test_context_identity_must_be_exact_lowercase_sha(goal, context):
    with pytest.raises(ValueError, match="SHA-256"):
        audit.build_commitment_audit_schema(goal, context_sha256=context)


def test_changed_native_source_cannot_reuse_an_accepted_document(goal):
    document = synthetic(goal)
    other = deepcopy(goal)
    other["claims"][0]["text"] = "完全不同的当前承诺。"
    with pytest.raises(ValidationError):
        validate(document, other)


def test_no_explicit_creative_usages_does_not_invent_an_audit_item(goal):
    other = deepcopy(goal)
    for beat in other["whole_plan"]["beats"]:
        beat["claim_refs"] = ["INF_MOTIVE"]
    other["whole_plan"]["ending"]["claim_refs"] = []
    document = synthetic(other)
    assert document["commitment_checks"] == {}
    assert validate(document, other)["accepted"]


def test_real_575_benchmark_requires_new_native_relationship_report_not_577_conversion():
    root = PROJECT / "data/production_trials/goal_context_text_production_20261013/round_13"
    goal_path, review_path = root / "goals/native_02.json", root / "call_577_goal_drama_audit_02.json"
    if not goal_path.exists() or not review_path.exists():
        pytest.skip("read-only actual 575/577 evidence absent")
    goal = json.loads(goal_path.read_text(encoding="utf-8-sig"))
    old = json.loads(review_path.read_text(encoding="utf-8-sig"))["output"]
    old_before, goal_before = deepcopy(old), deepcopy(goal)
    assert audit.digest(goal) == "4b84cbcee5d95c42b9ef7485bd7c315e18d73944c0f1ecb4449e96b4557b7583"
    assert old["commitment_checks"]["CC_LEVER"]["status"] == "pass"
    with pytest.raises(ValidationError):
        validate(old, goal)
    # Humans diagnosed these two relationships. This is a NEW synthetic
    # benchmark, not a provider response, automatic Chinese interpretation,
    # or a retroactively accepted native review.
    benchmark = synthetic(goal)
    lever = set_relation(benchmark, "CC_LEVER", "contradicts", "fail")
    lever["literal_requirement"] = "Only after the boss writes and signs may she reveal her records."
    lever["actual_usages"]["beat:B5"].update(evidence_refs=["G039", "G038"],
        actual_interpretation="B5 stimulus reveals records before the boss's writing response.")
    lever["counterevidence_refs"] = ["C:CC_LEVER", "G039", "G038"]
    slot = set_relation(benchmark, "CC_TOMORROW_SLOT", "not_demonstrated", "fail")
    slot["literal_requirement"] = "Payment and attendance return are exchanged for her indispensable installation work."
    slot["actual_usages"]["beat:B6"].update(evidence_refs=["G045", "G047"],
        actual_interpretation="Actual conversation specifies papers/money, not installation work.")
    result = validate(benchmark, goal)
    assert {row["check"] for row in result["findings"]} == {"CC_LEVER", "CC_TOMORROW_SLOT"}
    assert not result["accepted"] and not result["semantic_truth_deterministically_proven"]
    for identifier in ("CC_LEVER", "CC_TOMORROW_SLOT"):
        invalid = deepcopy(benchmark)
        invalid["commitment_checks"][identifier].update(status="pass", required_revision="", counterevidence_refs=[])
        with pytest.raises(ValidationError):
            validate(invalid, goal)
    assert old == old_before and goal == goal_before
