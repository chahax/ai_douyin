"""Offline application-scope cases, preserving actual 582/584 evidence."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket

from jsonschema import Draft202012Validator, ValidationError
import pytest

from src.content_factory import creative_goal_commitment_audit_v1 as prior
from src.content_factory import creative_goal_commitment_audit_v2 as audit

CONTEXT = "b" * 64
PROJECT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("scope contract tests must not contact providers")
    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


@pytest.fixture
def goal():
    return {"claims": [
        {"id": "CC_BACKGROUND", "kind": "creative_choice", "text": "员工入职七年，带来的纸印着离职字样。"},
        {"id": "CC_BOOK", "kind": "creative_choice", "text": "员工带考勤本离开，原件不放回。"},
        {"id": "CC_UNUSED", "kind": "creative_choice", "text": "没有明确使用的选择。"},
        {"id": "INF_CHANGE", "kind": "inference", "text": "对手愿意让步。"}],
        "whole_plan": {"characters": [{"id": "worker", "role": "入职七年的员工"},
                                      {"id": "boss", "role": "主管"}],
            "props": [{"id": "paper", "description": "印着离职字样的纸", "owner_character_id": "boss"},
                      {"id": "book", "description": "原生考勤本", "owner_character_id": "worker"}],
            "scenes": [{"id": "office", "description": "办公室"}],
            "beats": [
                {"id": "b1", "stimulus": "主管把那张纸摊开。", "response": "员工请他稍等。",
                 "claim_refs": ["CC_BACKGROUND", "INF_CHANGE"]},
                {"id": "b2", "response": "员工把考勤本夹在腋下，走出办公室。", "claim_refs": ["CC_BOOK"]}],
            "ending": {"visible_consequence": "同一本考勤本留在办公室。", "claim_refs": ["CC_BOOK"]}}}


def synthetic(goal):
    """Construct NEW structure fixtures, not migrated service audit documents."""
    checks = {}
    for identifier, usage in audit.build_commitment_usage_catalog(goal).items():
        checks[identifier] = {"claim_ref": usage["claim_ref"],
            "literal_requirement": "Synthetic scope explanation; not semantic approval",
            "actual_usages": {key: {
                "evidence_refs": [row["evidence_refs"][0]],
                "actual_interpretation": "Synthetic actual usage explanation",
                "relationship": "compatible", "requirement_scope": "mixed",
                "comparison_refs": []} for key, row in usage["usages"].items()},
            "status": "pass", "reason": "Synthetic structure fixture",
            "required_revision": "", "counterevidence_refs": []}
    return {"schema": audit.VERSION, "goal_sha256": audit.digest(goal),
            "audit_context_sha256": CONTEXT, "commitment_checks": checks}


def validate(document, goal):
    return audit.validate_commitment_audit(document, goal, context_sha256=CONTEXT)


def exact_ref(goal, path):
    return next(ref for ref, row in audit.build_evidence_catalog(goal).items()
                if row["document_path"] == path)


def test_v2_extends_every_usage_without_mutating_frozen_v1(goal):
    v1 = prior.build_commitment_audit_schema(goal, context_sha256=CONTEXT)
    before = deepcopy(v1)
    v2 = audit.build_commitment_audit_schema(goal, context_sha256=CONTEXT)
    Draft202012Validator.check_schema(v2)
    assert v1 == before and v1["properties"]["schema"]["const"] == prior.VERSION
    for identifier, row in v2["properties"]["commitment_checks"]["properties"].items():
        old = v1["properties"]["commitment_checks"]["properties"][identifier]
        assert row["allOf"] == old["allOf"]
        for key, usage in row["properties"]["actual_usages"]["properties"].items():
            original = old["properties"]["actual_usages"]["properties"][key]
            assert usage["properties"]["evidence_refs"] == original["properties"]["evidence_refs"]
            assert usage["additionalProperties"] is False
            assert set(usage["required"]) == set(original["required"]) | {"requirement_scope", "comparison_refs"}


@pytest.mark.parametrize("scope", audit.REQUIREMENT_SCOPES)
def test_all_native_scope_categories_are_structurally_supported(goal, scope):
    document = synthetic(goal)
    document["commitment_checks"]["CC_BACKGROUND"]["actual_usages"]["beat:b1"]["requirement_scope"] = scope
    assert validate(document, goal)["accepted"]


def test_background_and_cross_beat_comparisons_are_distinct_from_own_usage(goal):
    document = synthetic(goal)
    original, native_original = deepcopy(document), deepcopy(goal)
    background = document["commitment_checks"]["CC_BACKGROUND"]["actual_usages"]["beat:b1"]
    refs = [exact_ref(goal, "whole_plan.characters.0.role"), exact_ref(goal, "whole_plan.props.0.description"),
            exact_ref(goal, "whole_plan.beats.1.response")]
    background.update(requirement_scope="background_consistency", comparison_refs=refs)
    result = validate(document, goal)
    assert result["accepted"] and result["citation_channels_kept_distinct"]
    own = result["citations"]["CC_BACKGROUND"]["actual_usages"]["beat:b1"]
    compared = result["comparison_citations"]["CC_BACKGROUND"]["beat:b1"]
    assert [row["source_ref"] for row in own] == original["commitment_checks"]["CC_BACKGROUND"]["actual_usages"]["beat:b1"]["evidence_refs"]
    assert [row["source_ref"] for row in compared] == refs
    assert compared[0]["quote"] == goal["whole_plan"]["characters"][0]["role"]
    assert not result["requirement_scope_semantically_proven"]
    assert not result["semantic_truth_deterministically_proven"] and not result["human_approved"]
    assert goal == native_original


@pytest.mark.parametrize("fault", ["missing_scope", "wrong_scope", "null_scope", "missing_comparisons",
    "c_comparison", "unknown_comparison", "duplicate_comparison", "scalar_comparison", "null_comparison",
    "cross_usage_as_own", "background_as_own", "empty_own", "duplicate_own", "extra_usage", "missing_usage",
    "wrong_claim", "missing_claim", "extra_claim", "extra_field", "wrong_goal", "wrong_context", "old_schema"])
def test_new_comparison_channel_does_not_relax_source_coverage(goal, fault):
    document = synthetic(goal)
    row = document["commitment_checks"]["CC_BACKGROUND"]
    usage = row["actual_usages"]["beat:b1"]
    other_ref = exact_ref(goal, "whole_plan.beats.1.response")
    background_ref = exact_ref(goal, "whole_plan.props.0.description")
    if fault == "missing_scope": usage.pop("requirement_scope")
    elif fault == "wrong_scope": usage["requirement_scope"] = "everything_in_this_beat"
    elif fault == "null_scope": usage["requirement_scope"] = None
    elif fault == "missing_comparisons": usage.pop("comparison_refs")
    elif fault == "c_comparison": usage["comparison_refs"] = ["C:CC_BACKGROUND"]
    elif fault == "unknown_comparison": usage["comparison_refs"] = ["G999"]
    elif fault == "duplicate_comparison": usage["comparison_refs"] = [other_ref] * 2
    elif fault == "scalar_comparison": usage["comparison_refs"] = other_ref
    elif fault == "null_comparison": usage["comparison_refs"] = None
    elif fault == "cross_usage_as_own": usage.update(evidence_refs=[other_ref], comparison_refs=[other_ref])
    elif fault == "background_as_own": usage["evidence_refs"] = [background_ref]
    elif fault == "empty_own": usage["evidence_refs"] = []
    elif fault == "duplicate_own": usage["evidence_refs"] *= 2
    elif fault == "extra_usage": row["actual_usages"]["beat:b2"] = deepcopy(usage)
    elif fault == "missing_usage": row["actual_usages"].pop("beat:b1")
    elif fault == "wrong_claim": row["claim_ref"] = "C:CC_BOOK"
    elif fault == "missing_claim": document["commitment_checks"].pop("CC_BACKGROUND")
    elif fault == "extra_claim": document["commitment_checks"]["CC_UNUSED"] = deepcopy(row)
    elif fault == "extra_field": usage["locally_repaired"] = True
    elif fault == "wrong_goal": document["goal_sha256"] = "0" * 64
    elif fault == "wrong_context": document["audit_context_sha256"] = "0" * 64
    else: document["schema"] = prior.VERSION
    with pytest.raises(ValidationError):
        validate(document, goal)


@pytest.mark.parametrize("relationship,status", [("contradicts", "pass"), ("contradicts", "unknown"),
    ("not_demonstrated", "pass"), ("not_demonstrated", "unknown"), ("unknown", "pass")])
def test_reported_failure_or_unknown_still_cannot_be_masked(goal, relationship, status):
    document = synthetic(goal)
    row = document["commitment_checks"]["CC_BOOK"]
    row["actual_usages"]["beat:b2"]["relationship"] = relationship
    row["status"] = status
    with pytest.raises(ValidationError):
        validate(document, goal)


@pytest.mark.parametrize("relationship,status", [("contradicts", "fail"), ("not_demonstrated", "fail"),
                                               ("unknown", "unknown")])
def test_native_reported_failure_and_unknown_block_with_separate_citations(goal, relationship, status):
    document = synthetic(goal)
    row = document["commitment_checks"]["CC_BOOK"]
    row.update(status=status, required_revision="Complete new native goal" if status == "fail" else "")
    row["actual_usages"]["beat:b2"].update(relationship=relationship,
        requirement_scope="cross_beat_relation", comparison_refs=[exact_ref(goal, "whole_plan.ending.visible_consequence")])
    result = validate(document, goal)
    assert not result["accepted"]
    finding = (result["findings"] if status == "fail" else result["uncertainties"])[0]
    assert finding["comparison_evidence"]["beat:b2"][0]["document_path"] == "whole_plan.ending.visible_consequence"
    assert document["commitment_checks"]["CC_BOOK"]["status"] == status


@pytest.mark.parametrize("status", ["fail", "unknown"])
def test_cross_scope_nonpass_requires_counterevidence_when_own_usages_compatible(goal, status):
    document = synthetic(goal)
    row = document["commitment_checks"]["CC_BOOK"]
    row.update(status=status, required_revision="Complete new native goal" if status == "fail" else "")
    with pytest.raises(audit.CommitmentReportContractError):
        validate(document, goal)
    row["counterevidence_refs"] = [exact_ref(goal, "whole_plan.ending.visible_consequence")]
    assert not validate(document, goal)["accepted"]


def test_pass_remains_without_unresolved_counterevidence_or_revision(goal):
    document = synthetic(goal)
    row = document["commitment_checks"]["CC_BOOK"]
    row["counterevidence_refs"] = [exact_ref(goal, "whole_plan.ending.visible_consequence")]
    with pytest.raises(ValidationError): validate(document, goal)
    row["counterevidence_refs"] = []
    row["required_revision"] = "change a passed goal"
    with pytest.raises(ValidationError): validate(document, goal)


@pytest.mark.parametrize("context", [None, "", "b" * 63, "B" * 64, "z" * 64, 17])
def test_context_sha_gate_preserved(goal, context):
    with pytest.raises(ValueError):
        audit.build_commitment_audit_schema(goal, context_sha256=context)


def test_unreferenced_creative_choice_or_inference_does_not_invent_local_obligations(goal):
    document = synthetic(goal)
    assert set(document["commitment_checks"]) == {"CC_BACKGROUND", "CC_BOOK"}
    assert document["commitment_checks"]["CC_BACKGROUND"]["actual_usages"]["beat:b1"]["comparison_refs"] == []


def test_old_v1_document_cannot_be_converted_merely_by_changing_its_version(goal):
    document = synthetic(goal)
    for row in document["commitment_checks"].values():
        for usage in row["actual_usages"].values():
            usage.pop("requirement_scope")
            usage.pop("comparison_refs")
    document["schema"] = prior.VERSION
    assert prior.validate_commitment_audit(document, goal, context_sha256=CONTEXT)["valid"]
    document["schema"] = audit.VERSION
    with pytest.raises(ValidationError):
        validate(document, goal)


def test_actual_582_584_scope_overreach_and_book_contradiction_are_new_synthetic_benchmark():
    root = PROJECT / "data/production_trials/goal_context_text_production_20261013/round_14"
    goal_path, audit_path = root / "goals/native_02.json", root / "call_584_goal_commitment_audit_02.json"
    if not goal_path.exists() or not audit_path.exists():
        pytest.skip("read-only actual582/584 evidence absent")
    old_bytes, goal_bytes = audit_path.read_bytes(), goal_path.read_bytes()
    goal = json.loads(goal_bytes.decode("utf-8-sig"))
    old = json.loads(old_bytes.decode("utf-8-sig"))["output"]
    assert audit.digest(goal) == "67b8f47191d099c84f374a311a69a9ef79ead8d3fcfb93177e47a07b9d8dd925"
    assert audit.digest(old) == "52f288eaf097d462a80a8569ca3c80d207ba730d6dc3da6332d89df119ab305e"
    assert old["commitment_checks"]["c_choice_premise"]["status"] == "fail"
    assert "同一拍" in old["commitment_checks"]["c_choice_premise"]["literal_requirement"]
    assert "同一拍" not in audit.build_evidence_catalog(goal)["C:c_choice_premise"]["quote"]
    assert old["commitment_checks"]["c_choice_paper"]["status"] == "fail"
    assert old["commitment_checks"]["c_choice_boundary"]["status"] == "pass"
    with pytest.raises(ValidationError):
        validate(old, goal)
    # Explicit human diagnosis is NEW synthetic evidence, not a native v2
    # service result, semantic automation, or a repaired/adopted old review.
    benchmark = synthetic(goal)
    premise = benchmark["commitment_checks"]["c_choice_premise"]
    premise["literal_requirement"] = "Background role and tenure; no requirement that every clause be repeated in b1."
    premise["actual_usages"]["beat:b1"].update(requirement_scope="mixed",
        comparison_refs=["G076", "G086", "G023", "G031", "G039"],
        actual_interpretation="Global roles establish tenure/identity; later actual beats establish white-shift pressure.")
    paper = benchmark["commitment_checks"]["c_choice_paper"]
    paper["literal_requirement"] = "Declared printed form and later demand to recover it; no demand that all occur in b1."
    paper["actual_usages"]["beat:b1"].update(requirement_scope="mixed", comparison_refs=["G093", "G045"],
        actual_interpretation="The declared form is unfolded in b1 and recovery demand occurs in b6.")
    boundary = benchmark["commitment_checks"]["c_choice_boundary"]
    boundary.update(status="fail", required_revision="Submit whole new plan resolving the same book terminal state.",
                    counterevidence_refs=["G063", "G091"])
    boundary["literal_requirement"] = "Terminal rewards and records must be consistent with the actual ending."
    for key, compare in [("beat:b8", "G091"), ("ending", "G063")]:
        boundary["actual_usages"][key].update(relationship="contradicts",
            requirement_scope="cross_beat_relation", comparison_refs=[compare],
            evidence_refs=["G063"] if key == "beat:b8" else ["G091"],
            actual_interpretation="Same unique book is carried away yet ending says its records remain in warehouse.")
    result = validate(benchmark, goal)
    assert not result["accepted"]
    assert {finding["check"] for finding in result["findings"]} == {"c_choice_boundary"}
    assert result["comparison_citations"]["c_choice_paper"]["beat:b1"][0]["source_ref"] == "G093"
    assert not result["requirement_scope_semantically_proven"] and not result["semantic_truth_deterministically_proven"]
    invalid = deepcopy(benchmark)
    invalid["commitment_checks"]["c_choice_boundary"].update(status="pass", required_revision="", counterevidence_refs=[])
    with pytest.raises(ValidationError): validate(invalid, goal)
    assert audit_path.read_bytes() == old_bytes and goal_path.read_bytes() == goal_bytes
    assert hashlib.sha256(old_bytes).hexdigest() == "a8fd67d7847f77696bc6d30e097dd3bfc06aa0e33e509fe9f9046d35689fe03c"
