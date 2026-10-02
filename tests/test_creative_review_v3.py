from copy import deepcopy
import pytest
from src.content_factory.creative_review_v3 import CHECKS, VERSION, build_review_prompt, validate_v3_review
from src.content_factory.creative_review_gate import review_prompt, review_rules, SUPPORTED_VERSIONS
from src.content_factory.creative_workflow_contract import CreativeContractError


def sample(joint=False):
    context = {"script": {"beats": [{"id": "B01", "before": "许宁放下纸杯。"}]}}
    if joint:
        context["shots"] = {"shots": [
            {"id": "SH01", "opening_prompt": "许宁手持纸杯。", "action": "许宁放下纸杯。"},
            {"id": "SH02", "opening_prompt": "纸杯在桌面。", "action": "许宁转向周临。"},
        ]}
    rows = context["shots"]["shots"] if joint else context["script"]["beats"]
    root = "shots.shots" if joint else "script.beats"
    coverage = []
    for index, row in enumerate(rows):
        field = "action" if joint else "before"
        ref = {"path": f"{root}.{index}.{field}", "quote": row[field]}
        checks = {}
        for name in CHECKS:
            na = not joint and name in ("assets", "first_frame")
            checks[name] = {"status": "not_applicable" if na else "pass",
                            "reason": "当前仅审核剧本，无分镜资产。" if na else "依据正文核对本项。",
                            "evidence_refs": [] if na else [deepcopy(ref)], "issue_ids": []}
        if joint and index:
            checks["continuity"]["evidence_refs"].append({"path": f"{root}.{index-1}.action", "quote": rows[index-1]["action"]})
        coverage.append({"id": row["id"], "checks": checks})
    return context, {"story_preserved": True, "issues": [], "suggestions": [], "calibration_focus": [], "coverage": coverage}


def test_script_and_joint_complete_reviews():
    for joint in (False, True):
        context, review = sample(joint)
        validate_v3_review(review, context)


@pytest.mark.parametrize("mutation", ["missing_row", "duplicate_row", "missing_check", "invalid_quote", "wrong_row", "missing_reason"])
def test_incomplete_or_ungrounded_coverage_rejected(mutation):
    context, review = sample(True)
    if mutation == "missing_row":
        review["coverage"].pop()
    elif mutation == "duplicate_row":
        review["coverage"][1] = deepcopy(review["coverage"][0])
    elif mutation == "missing_check":
        del review["coverage"][0]["checks"]["assets"]
    elif mutation == "invalid_quote":
        review["coverage"][0]["checks"]["requirements"]["evidence_refs"][0]["quote"] = "正文不存在"
    elif mutation == "wrong_row":
        review["coverage"][0]["checks"]["requirements"]["evidence_refs"] = [{"path": "shots.shots.1.action", "quote": "许宁转向周临。"}]
    else:
        review["coverage"][0]["checks"]["requirements"]["reason"] = ""
    with pytest.raises(CreativeContractError):
        validate_v3_review(review, context)


def test_continuity_requires_previous_shot_evidence():
    context, review = sample(True)
    review["coverage"][1]["checks"]["continuity"]["evidence_refs"].pop()
    with pytest.raises(CreativeContractError, match="上一镜"):
        validate_v3_review(review, context)


def test_segment_requires_external_previous_shot():
    context, review = sample(True)
    context["shots"]["shots"] = context["shots"]["shots"][:1]
    review["coverage"] = review["coverage"][:1]
    context["previous_shot"] = {"id": "SH00", "action": "许宁手持纸杯。"}
    with pytest.raises(CreativeContractError, match="上一镜"):
        validate_v3_review(review, context)
    review["coverage"][0]["checks"]["continuity"]["evidence_refs"].append({"path": "previous_shot.action", "quote": "许宁手持纸杯。"})
    validate_v3_review(review, context)


def test_first_frame_cannot_skip():
    context, review = sample(True)
    review["coverage"][0]["checks"]["first_frame"]["status"] = "not_applicable"
    with pytest.raises(CreativeContractError, match="首帧"):
        validate_v3_review(review, context)


def test_fail_needs_real_issue_and_issue_needs_fail():
    context, review = sample()
    check = review["coverage"][0]["checks"]["continuity"]
    check["status"] = "fail"
    with pytest.raises(CreativeContractError, match="fail"):
        validate_v3_review(review, context)
    issue = {"id": "I01", "owner": "writer", "location": "B01", "severity": "major",
             "rule": "纸杯归属连续", "contradiction": "测试矛盾", "evidence": "许宁放下纸杯。",
             "impact": "道具连续性", "proposal": "说明杯子起点", "evidence_refs": deepcopy(check["evidence_refs"])}
    review["issues"] = [issue]
    review["story_preserved"] = False
    check["issue_ids"] = ["I01"]
    validate_v3_review(review, context)
    check["status"], check["issue_ids"] = "pass", []
    with pytest.raises(CreativeContractError, match="对应fail"):
        validate_v3_review(review, context)


def test_independent_prompt_has_no_legacy_score_contract():
    context, _ = sample(True)
    prompt = build_review_prompt(context)
    assert "SH01" in prompt and "SH02" in prompt
    assert "上一镜" in prompt and "实际台词字数" in prompt and "动作发生前" in prompt
    assert "总分已达80" not in prompt and "只能有六个字段" not in prompt
    assert VERSION in SUPPORTED_VERSIONS
    assert review_rules(VERSION) == ""
    assert "coverage" in review_prompt(VERSION)


def test_segment_scope_is_explicit_and_does_not_change_other_review_prompts():
    context, _ = sample(True)
    ordinary = build_review_prompt(context)
    context["review_scope"] = "whole_film"
    assert build_review_prompt(context) == ordinary
    context["review_scope"] = "storyboard_segment"
    segment = build_review_prompt(context)
    assert segment.startswith(ordinary)
    assert "不能因本次shots没有后续节拍" in segment
    assert "至少引用一条shots.shots.当前索引.具体叶子" in segment
    assert "并不自动减少甲的可说话时间" in segment
    script, _ = sample()
    assert "单节拍分镜审核" not in build_review_prompt(script)


def test_unique_container_reference_repairs_only_path_and_is_pure():
    from src.content_factory.creative_review_v3 import canonicalize_unique_leaf_refs
    context = {"shots": {"shots": [{"production_choices": ["镜头固定", "眼神停留两秒"]}]}}
    ref = {"path": "shots.shots.0.production_choices", "quote": "眼神停留"}
    original = {"issues": [{"id": "I01", "evidence_refs": [deepcopy(ref)]}],
                "coverage": [{"id": "SH01", "checks": {"timing": {
                    "status": "fail", "reason": "原结论", "issue_ids": ["I01"], "evidence_refs": [deepcopy(ref)]}}}]}
    before = deepcopy(original)
    result, changes = canonicalize_unique_leaf_refs(original, context)
    assert original == before
    assert len(changes) == 2
    assert result["issues"][0]["evidence_refs"][0]["path"] == "shots.shots.0.production_choices.1"
    assert result["coverage"][0]["checks"]["timing"]["status"] == "fail"
    assert result["issues"][0]["evidence_refs"][0]["quote"] == "眼神停留"
    assert changes[0] == {"reference_path": "issues.0.evidence_refs.0",
                          "from_path": "shots.shots.0.production_choices",
                          "to_path": "shots.shots.0.production_choices.1", "quote": "眼神停留"}
    again, changes = canonicalize_unique_leaf_refs(result, context)
    assert again == result and changes == []


@pytest.mark.parametrize("leaves,quote", [
    (["停留", "再停留"], "停留"),
    (["一样", "一样"], "一样"),
    (["别的"], "不存在"),
    (["任意"], ""),
    ([True], "true"),
])
def test_ambiguous_or_absent_container_quote_is_never_repaired(leaves, quote):
    from src.content_factory.creative_review_v3 import canonicalize_unique_leaf_refs
    value = {"issues": [{"evidence_refs": [{"path": "body", "quote": quote}]}]}
    result, changes = canonicalize_unique_leaf_refs(value, {"body": leaves})
    assert result == value and changes == []


def test_unique_nested_numeric_leaf_and_existing_wrong_leaf():
    from src.content_factory.creative_review_v3 import canonicalize_unique_leaf_refs
    value = {"issues": [{"evidence_refs": [
        {"path": "body", "quote": "12"},
        {"path": "body.keep", "quote": "12"},
        {"path": "unknown", "quote": "12"}]}]}
    result, changes = canonicalize_unique_leaf_refs(value, {"body": {"rows": [{"seconds": 12}], "keep": "其他"}})
    assert len(changes) == 1
    assert result["issues"][0]["evidence_refs"][0]["path"] == "body.rows.0.seconds"
    assert result["issues"][0]["evidence_refs"][1:] == value["issues"][0]["evidence_refs"][1:]


@pytest.mark.parametrize("quote,expected_count", [("当前只审核文字", 1), ("审核文字", 1), ("不存在的引用", 0)])
def test_known_media_assumptions_alias_requires_real_leaf_quote(quote, expected_count):
    from src.content_factory.creative_review_v3 import canonicalize_unique_leaf_refs
    context = {"shots": {"shots": [{"id": "SH01"}],
                         "media_assumptions": [{"assumption": "当前只审核文字"}]}}
    value = {"issues": [{"evidence_refs": [{"path": "shots.shots.0.media_assumptions.0.assumption", "quote": quote}]}]}
    before = deepcopy(value)
    result, changes = canonicalize_unique_leaf_refs(value, context)
    assert value == before
    assert len(changes) == expected_count
    if expected_count:
        assert result["issues"][0]["evidence_refs"][0]["path"] == "shots.media_assumptions.0.assumption"
        assert changes[0]["from_path"] == "shots.shots.0.media_assumptions.0.assumption"
    else:
        assert result == value


def test_known_alias_does_not_override_existing_path_or_search_other_missing_paths():
    from src.content_factory.creative_review_v3 import canonicalize_unique_leaf_refs
    context = {"shots": {"shots": [{"media_assumptions": [{"assumption": "镜头自己的内容"}]}],
                         "media_assumptions": [{"assumption": "全局内容"}]}}
    value = {"issues": [{"evidence_refs": [
        {"path": "shots.shots.0.media_assumptions.0.assumption", "quote": "全局内容"},
        {"path": "shots.shots.99.media_assumptions.0.assumption", "quote": "全局内容"},
        {"path": "shots.shots.0.style.assumption", "quote": "全局内容"}]}]}
    result, changes = canonicalize_unique_leaf_refs(value, context)
    assert result == value and changes == []


def test_production_choices_unique_sibling_index_can_be_corrected():
    from src.content_factory.creative_review_v3 import canonicalize_unique_leaf_refs
    context = {"shots": {"shots": [{"production_choices": ["别的选择", "保持原文不变"]}]}}
    value = {"issues": [{"evidence_refs": [{"path": "shots.shots.0.production_choices.0", "quote": "保持原文不变"}]}]}
    original = deepcopy(value)
    result, changes = canonicalize_unique_leaf_refs(value, context)
    assert value == original
    assert result["issues"][0]["evidence_refs"][0] == {"path": "shots.shots.0.production_choices.1", "quote": "保持原文不变"}
    assert len(changes) == 1
    again, changes = canonicalize_unique_leaf_refs(result, context)
    assert again == result and changes == []


@pytest.mark.parametrize("field,choices,path_index", [
    ("production_choices", ["别的", "重复", "重复"], 0),
    ("production_choices", ["别的", "无匹配"], 0),
    ("production_choices", ["重复", "重复"], 0),
    ("other_choices", ["别的", "重复"], 0),
    ("production_choices", ["别的", "重复"], 99),
])
def test_sibling_index_fix_never_guesses_ambiguous_or_unrelated_refs(field, choices, path_index):
    from src.content_factory.creative_review_v3 import canonicalize_unique_leaf_refs
    context = {"shots": {"shots": [{field: choices}]}}
    value = {"issues": [{"evidence_refs": [{"path": f"shots.shots.0.{field}.{path_index}", "quote": "重复"}]}]}
    result, changes = canonicalize_unique_leaf_refs(value, context)
    assert result == value and changes == []
