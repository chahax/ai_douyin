"""Candidate v7 source gate; all verification is offline."""
from copy import deepcopy

import pytest

from scripts.creative_script_review_sources_v7 import validate_review_v7
from src.content_factory.creative_review_v6 import validate_review_v6
from src.content_factory.creative_workflow_contract import CreativeContractError
from tests.test_creative_review_v3 import sample
from tests.test_creative_review_v6 import prepared


def two_script_beats():
    context, review = sample()
    context["script"]["beats"].append({"id": "B02", "before": "纸杯已在桌面，许宁转向周临。"})
    row = deepcopy(review["coverage"][0])
    row["id"] = "B02"
    for check in row["checks"].values():
        if check["evidence_refs"]:
            check["evidence_refs"] = [{"path": "script.beats.1.before",
                                      "quote": context["script"]["beats"][1]["before"]}]
    review["coverage"].append(row)
    return context, review


def previous_ref(context):
    return {"path": "script.beats.0.before", "quote": context["script"]["beats"][0]["before"]}


def test_original_script_source_gap_is_rejected_only_by_new_candidate():
    context, review = two_script_beats()
    before = deepcopy((context, review))
    validate_review_v6(review, context)
    with pytest.raises(CreativeContractError, match=r"v7.*script\.beats\.0\."):
        validate_review_v7(review, context)
    assert (context, review) == before


@pytest.mark.parametrize("status", ["pass", "fail"])
def test_real_previous_leaf_allows_pass_and_fail_without_changing_conclusions(status):
    context, review = two_script_beats()
    check = review["coverage"][1]["checks"]["continuity"]
    check["evidence_refs"].append(previous_ref(context))
    if status == "fail":
        check.update(status="fail", issue_ids=["I01"])
        review["story_preserved"] = False
        review["issues"] = [{"id": "I01", "owner": "writer", "location": "B02", "severity": "major",
            "rule": "离线连续性反例", "evidence": context["script"]["beats"][1]["before"],
            "contradiction": "测试原始必修结论", "impact": "测试状态连续性", "proposal": "保留原结论",
            "evidence_refs": deepcopy(check["evidence_refs"])}]
    # Sources are determined by actual script order, not output coverage order.
    review["coverage"].reverse()
    before = deepcopy((context, review))
    validate_review_v7(review, context)
    assert (context, review) == before


def test_first_script_beat_keeps_original_v6_rule():
    context, review = sample()
    validate_review_v6(review, context)
    validate_review_v7(review, context)
    review["coverage"][0]["checks"]["continuity"]["evidence_refs"] = []
    for validator in (validate_review_v6, validate_review_v7):
        with pytest.raises(CreativeContractError):
            validator(review, context)


def test_joint_review_keeps_original_v6_source_behavior():
    context, review = prepared()
    before = deepcopy((context, review))
    validate_review_v6(review, context)
    validate_review_v7(review, context)
    assert (context, review) == before
    check = review["coverage"][0]["checks"]["continuity"]
    check["evidence_refs"] = [ref for ref in check["evidence_refs"] if not ref["path"].startswith("previous_shot.")]
    with pytest.raises(CreativeContractError) as original:
        validate_review_v6(review, context)
    with pytest.raises(CreativeContractError) as candidate:
        validate_review_v7(review, context)
    assert str(candidate.value) == str(original.value)


@pytest.mark.parametrize("ref", [
    {"path": "script.beats.0.dialogue", "quote": "[]"},
    {"path": "script.beats.99.before", "quote": "不存在"},
])
def test_nonleaf_or_unknown_previous_source_is_still_rejected_by_original_gate(ref):
    context, review = two_script_beats()
    context["script"]["beats"][0]["dialogue"] = []
    review["coverage"][1]["checks"]["continuity"]["evidence_refs"].append(ref)
    with pytest.raises(CreativeContractError) as original:
        validate_review_v6(review, context)
    with pytest.raises(CreativeContractError) as candidate:
        validate_review_v7(review, context)
    assert str(candidate.value) == str(original.value)
