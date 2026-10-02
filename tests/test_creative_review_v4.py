from copy import deepcopy
import json
from pathlib import Path
import pytest
from src.content_factory.creative_review_v3 import validate_v3_review, build_review_prompt as prompt_v3
from src.content_factory.creative_review_v4 import (VERSION, build_review_prompt, validate_review_v4, required_execution_paths)
from src.content_factory.creative_review_gate import SUPPORTED_VERSIONS, review_prompt, review_rules
from src.content_factory.creative_workflow_contract import CreativeContractError


def recorded():
    return json.loads((Path(__file__).parent / "fixtures/creative_review_sh04_failure.json").read_text(encoding="utf-8"))


def leaf(context, path):
    value = context
    for part in path.split("."):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def fully_cited_review(context, review):
    result = deepcopy(review)
    # Test-only deliberately wrong positive conclusion with exhaustive references.
    # This demonstrates that coverage does not establish semantic correctness.
    checks = result["coverage"][0]["checks"]
    refs = [{"path": p, "quote": leaf(context, p)} for p in required_execution_paths(context)["SH04"]]
    for name in ("timing", "continuity", "first_frame"):
        checks[name]["evidence_refs"].extend(deepcopy(refs))
    return result


def test_recorded_false_pass_was_v3_valid_but_v4_requires_missing_contradiction_fields():
    fixture = recorded()
    validate_v3_review(fixture["review"], fixture["context"])
    assert fixture["review"]["story_preserved"] is True
    with pytest.raises(CreativeContractError, match="production_choices.2"):
        validate_review_v4(fixture["review"], fixture["context"])
    shot = fixture["context"]["shots"]["shots"][0]
    assert "松沉不发生在道别对白之前" in shot["production_choices"][2]
    assert "椅仍在陈禾身后" in shot["start_state"]
    assert "椅已在陈禾身前" in shot["composition"]
    assert "5.5秒起切换" in shot["camera"]


def test_complete_evidence_is_not_a_semantic_pass_guarantee():
    fixture = recorded()
    # Intentionally preserve the known bad SH04 and its wrong pass conclusion.
    # No code can claim the production failure is solved from this test passing.
    review = fully_cited_review(fixture["context"], fixture["review"])
    validate_review_v4(review, fixture["context"])
    assert review["story_preserved"] is True
    assert "松沉不发生在道别对白之前" in fixture["context"]["shots"]["shots"][0]["production_choices"][2]


@pytest.mark.parametrize("name,path", [("timing","prompt"), ("continuity","end_state"), ("first_frame","visible_performance")])
def test_each_cross_check_needs_its_two_sides_even_if_other_check_cites_them(name,path):
    fixture = recorded()
    review = fully_cited_review(fixture["context"], fixture["review"])
    check = review["coverage"][0]["checks"][name]
    check["evidence_refs"] = [r for r in check["evidence_refs"] if r["path"] != "shots.shots.0." + path]
    with pytest.raises(CreativeContractError, match="对照双方"):
        validate_review_v4(review, fixture["context"])


def test_prompt_addresses_actual_missed_cases_and_preserves_v3_prompt():
    context = recorded()["context"]
    old = prompt_v3(context)
    prompt = build_review_prompt(context)
    assert "同一动作逐一核对" in prompt
    assert "正文与摘要相反" in prompt
    assert "planned_cut_requires_adapter仅描述镜间切换" in prompt
    assert "场景常态" in prompt and "尚未完成" in prompt
    assert "production_choices.2" in prompt and "production_choices.7" in prompt
    assert "后续节拍尚未制作" in prompt
    assert prompt_v3(context) == old
    assert VERSION in SUPPORTED_VERSIONS and review_rules(VERSION) == ""
    assert "coverage" in review_prompt(VERSION)


def test_valid_script_still_uses_v3_shape_no_new_required_keys():
    from tests.test_creative_review_v3 import sample
    context, review = sample()
    validate_review_v4(review, context)
    assert required_execution_paths(context) == {}
