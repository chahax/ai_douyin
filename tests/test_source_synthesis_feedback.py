import json

import pytest

from src.trend_intelligence.content_analysis.hierarchical import synthesize_expression, _validate_summary


def evidence(count=90):
    return [{"id": f"V{i:04d}", "channel": "visual", "start_seconds": float(i),
             "end_seconds": float(i), "text": "原始画面：" + "纸张状态" * 40}
            for i in range(count)]


def input_rows(prompt):
    marker = '{"candidate_summaries":'
    if marker in prompt:
        return json.JSONDecoder().raw_decode(prompt[prompt.index(marker):])[0]["raw_evidence"]
    marker = "原始媒体证据：\n" if "原始媒体证据：\n" in prompt else "媒体证据：\n"
    return json.JSONDecoder().raw_decode(prompt.split(marker, 1)[1])[0]


def recorder(prompts):
    def infer(content):
        prompt = content[0]["text"]
        prompts.append(prompt)
        ref = input_rows(prompt)[0]["id"]
        claim = {"text": "原始画面显示纸张", "evidence_ids": [ref]}
        if prompt.startswith("FINAL_SCHEMA"):
            return {"schema": "video_expression_analysis/v1", "core_message": claim,
                    "expression_modes": [{"mode": "direct_explanation", "evidence_ids": [ref]}],
                    "visual_expression": [claim], "audio_expression": [],
                    "conflict": {"status": "not_observed"}, "uncertainties": []}
        return {"claims": [claim], "uncertainties": []}
    return infer


def run(tmp_path, prompts, feedback="", rows=None, budget=3000):
    return synthesize_expression(evidence() if rows is None else rows, 100,
                                 infer=recorder(prompts), synthesis_prompt="FINAL_SCHEMA",
                                 feedback_text=feedback, checkpoint_dir=tmp_path, binding={"source": "same"},
                                 max_input_chars=budget)


def test_feedback_reaches_leaf_merge_final_without_final_schema_in_leaf(tmp_path):
    prompts = []
    feedback = "独立反馈：付款人为甲方；保留最终未退款的结尾。"
    result, audit = run(tmp_path, prompts, feedback)
    assert audit["merge_levels"] >= 1
    assert {stage["stage"].split("_")[0] for stage in audit["stages"]} == {"leaf", "merge", "final"}
    assert all(feedback in prompt for prompt in prompts)
    assert all("FINAL_SCHEMA" not in prompt for prompt in prompts if not prompt.startswith("FINAL_SCHEMA"))
    assert result["evidence"] == evidence()
    for stage in audit["stages"]:
        with open(stage["checkpoint_path"], encoding="utf-8") as stream:
            checkpoint = json.load(stream)
        assert checkpoint["identity"]["binding"]["feedback_text"] == feedback


def test_changed_feedback_invalidates_every_stage_but_identical_feedback_resumes(tmp_path):
    first_prompts, revised_prompts = [], []
    kwargs = dict(synthesis_prompt="FINAL_SCHEMA", checkpoint_dir=tmp_path, binding={"source": "same"},
                  max_input_chars=3000)
    synthesize_expression(evidence(), 100, infer=recorder(first_prompts), feedback_text="旧反馈", **kwargs)
    _, unchanged = synthesize_expression(evidence(), 100, infer=lambda _: pytest.fail("cache missed"),
                                         feedback_text="旧反馈", **kwargs)
    assert all(stage["reused"] for stage in unchanged["stages"])
    _, changed = synthesize_expression(evidence(), 100, infer=recorder(revised_prompts),
                                       feedback_text="新反馈：付款人不能互换", **kwargs)
    assert revised_prompts
    assert not any(stage["reused"] for stage in changed["stages"])


def test_feedback_is_counted_in_all_input_budgets_and_preserves_all_rows(tmp_path):
    plain_prompts, feedback_prompts = [], []
    _, plain = run(tmp_path / "plain", plain_prompts)
    rows = evidence()
    result, revised = run(tmp_path / "revised", feedback_prompts, "纠正要求" * 150, rows=rows)
    assert revised["leaf_count"] > plain["leaf_count"]
    assert max(map(len, feedback_prompts)) <= 3000
    assert result["evidence"] == rows
    assert set(revised["leaf_covered_evidence_ids"]) == {row["id"] for row in rows}
    with pytest.raises(ValueError, match="insufficient evidence budget"):
        run(tmp_path / "oversized", [], "大" * 4000, rows=rows)


def test_feedback_mention_does_not_authorize_out_of_segment_citation(tmp_path):
    rows, prompts = evidence(), []
    outside = rows[-1]["id"]
    def invalid(content):
        prompt = content[0]["text"]
        prompts.append(prompt)
        assert outside in prompt
        assert outside not in {row["id"] for row in input_rows(prompt)}
        return {"claims": [{"text": "反馈提到结尾", "evidence_ids": [outside]}], "uncertainties": []}
    with pytest.raises(ValueError, match="not in its input"):
        synthesize_expression(rows, 100, infer=invalid, synthesis_prompt="FINAL_SCHEMA",
                              feedback_text=f"结尾证据{outside}不得丢失", checkpoint_dir=tmp_path,
                              binding={}, max_input_chars=3000)
    assert len(prompts) == 2
    assert max(map(len, prompts)) <= 3000
    assert not list(tmp_path.glob("*.json"))


def test_short_direct_run_also_receives_feedback(tmp_path):
    prompts = []
    _, audit = run(tmp_path, prompts, "短片也要保持转述归属", rows=evidence(1))
    assert audit["strategy"] == "direct"
    assert len(prompts) == 1 and "短片也要保持转述归属" in prompts[0]


def test_configured_claim_count_keeps_facts_with_a_hard_upper_bound():
    claims = [{"text": f"独立事实{i}", "evidence_ids": ["V0001"]} for i in range(12)]
    result = {"claims": claims, "uncertainties": []}
    assert _validate_summary(result, {"V0001"}, max_claims=12) is result
    with pytest.raises(ValueError, match="1 to 6 claims"):
        _validate_summary(result, {"V0001"})
    with pytest.raises(ValueError, match="1 to 12 claims"):
        _validate_summary({"claims": claims + [claims[0]]}, {"V0001"}, max_claims=12)
    oversized = {"claims": [{"text": "真实陈述", "evidence_ids": [f"V{i:04d}" for i in range(33)]}]}
    with pytest.raises(ValueError, match="too many references"):
        _validate_summary(oversized, {f"V{i:04d}" for i in range(33)}, max_claims=12, max_claim_refs=32)


@pytest.mark.parametrize("limit", [0, 13, True, 6.5])
def test_invalid_claim_count_stops_before_inference(tmp_path, limit):
    with pytest.raises(ValueError, match="max_claims"):
        synthesize_expression(evidence(1), 10, infer=lambda _: pytest.fail("invalid budget inferred"),
                              synthesis_prompt="FINAL_SCHEMA", checkpoint_dir=tmp_path, binding={}, max_claims=limit)


def test_claim_count_reaches_both_summary_prompts_and_invalidates_cache(tmp_path):
    common = dict(synthesis_prompt="FINAL_SCHEMA", checkpoint_dir=tmp_path, binding={}, max_input_chars=3000,
                  feedback_text="保留条件，不能静默删除结尾")
    synthesize_expression(evidence(), 100, infer=recorder([]), max_claims=6, **common)
    prompts = []
    result, audit = synthesize_expression(evidence(), 100, infer=recorder(prompts), max_claims=12, **common)
    assert audit["merge_levels"] >= 1
    assert result["evidence"] == evidence()
    assert not any(stage["reused"] for stage in audit["stages"])
    assert max(map(len, prompts)) <= 3000
    assert all("最多12条claims" in prompt for prompt in prompts if not prompt.startswith("FINAL_SCHEMA"))
    for stage in audit["stages"]:
        with open(stage["checkpoint_path"], encoding="utf-8") as stream:
            checkpoint = json.load(stream)
        assert checkpoint["identity"]["binding"]["max_claims"] == 12
