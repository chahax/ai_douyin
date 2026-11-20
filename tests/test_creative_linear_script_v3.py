"""Offline boundaries for untimed complete scripts; no provider calls."""
from copy import deepcopy
import hashlib
import json
import math

import pytest
from jsonschema import Draft202012Validator

from scripts import creative_linear_script_v3 as v3
from scripts.creative_script_review_sources_v7 import validate_review_v7
from src.content_factory.creative_workflow_contract import CreativeContractError
from tests.test_creative_linear_script_v2 import previous, context, action, dialogue, playback


def raw():
    return {"title": "完整新稿", "premise": "刺激引出拒绝，拒绝造成回应。",
            "selected_candidate_id": "C01", "beats": [
        {"id": "NEW1", "event": "拒绝与回应", "trigger": "关系里默认的付出被打破",
         "steps": [action("林屿递出签字笔。"), dialogue("方澄", "这次我先走，你自己对吧。"),
                   action("林屿伸出的手停住。"), dialogue("林屿", "我知道了。"),
                   action("林屿收回签字笔。")]},
        {"id": "NEW2", "event": "各自选择", "trigger": "回应此前拒绝",
         "steps": [action("方澄背包出门。"), action("林屿落笔核对明细。")]}]}


def test_model_contract_has_no_timing_fields_and_rejects_duration():
    schema = v3.build_linear_script_schema(context())
    beat_schema = schema["properties"]["beats"]["items"]
    assert set(beat_schema["properties"]) == {"id", "event", "trigger", "steps"}
    assert "duration_seconds" not in json.dumps(schema)
    Draft202012Validator(schema).validate(raw())
    invalid = raw()
    invalid["beats"][0]["duration_seconds"] = 11
    assert list(Draft202012Validator(schema).iter_errors(invalid))
    with pytest.raises(CreativeContractError, match="LINEAR_SCHEMA_INVALID"):
        v3.accept_linear_script(previous(), invalid)


def test_complete_new_script_identity_order_and_all_source_strings_are_preserved():
    old, generated = previous(), raw()
    saved = deepcopy((old, generated))
    derived = v3.accept_linear_script(old, generated)
    assert (old, generated) == saved
    assert [b["id"] for b in derived["beats"]] == ["NEW1", "NEW2"]
    assert derived["selected_candidate_id"] == "C01"
    for source, target in zip(generated["beats"], derived["beats"]):
        assert playback(target) == [(s["kind"], s["speaker"], s["text"]) for s in source["steps"]]
        assert target["event"] == source["event"] and target["trigger"] == source["trigger"]
    assert "旧句" not in derived["screenplay_markdown"]
    assert derived["duration_seconds"] == sum(b["duration_seconds"] for b in derived["beats"])
    assert "preliminary_timing_estimates" not in derived
    assert set(derived) == {"title", "premise", "selected_candidate_id", "duration_seconds", "beats", "screenplay_markdown"}
    assert all("duration_seconds" not in b for b in generated["beats"])


def test_budget_proof_is_separate_deterministic_and_never_actual_timing():
    generated = raw()
    saved = deepcopy(generated)
    proof = v3.preliminary_timing_estimates(generated)
    assert proof == v3.preliminary_budget_estimates(generated)
    assert generated == saved
    assert proof["raw_sha256"] == hashlib.sha256(json.dumps(generated, ensure_ascii=False,
        sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    assert proof["timing_status"] == "preliminary_budget_not_actual"
    assert proof["actual_windows_verified"] is False
    assert proof["action_timing_verified"] is False
    assert proof["semantic_approval"] is False and proof["production_ready"] is False
    for row in proof["by_beat_id"].values():
        assert row["action_duration_seconds"] is None
        assert row["pause_duration_seconds"] is None
        assert row["actual_dialogue_window_seconds"] is None
        assert row["actual_reaction_window_seconds"] is None
        assert "arbitrary" in row["allowance_basis"] and "unmeasured" in row["allowance_basis"]
    assert proof["estimated_total_budget_seconds"] == sum(row["budget_seconds"] for row in proof["by_beat_id"].values())
    derived = v3.accept_linear_script(previous(), generated)
    assert [b["duration_seconds"] for b in derived["beats"]] == [proof["by_beat_id"][b["id"]]["budget_seconds"] for b in generated["beats"]]


def test_speech_units_reuse_project_cjk_and_word_rules_not_english_letters():
    generated = raw()
    generated["beats"][0]["steps"] = [dialogue("方澄", "你好 John 123")]
    row = v3.preliminary_timing_estimates(generated)["by_beat_id"]["NEW1"]
    assert row["speech_units"] == 6
    assert row["speech_floor_seconds"] == pytest.approx(6 / 4.5)
    assert row["provisional_speech_budget_seconds"] == pytest.approx(6 / 3.5)
    assert row["budget_seconds"] == math.ceil(6 / 3.5 + 6)


def test_arbitrary_action_allowance_does_not_measure_compound_actions_or_declared_pause():
    first, second = raw(), raw()
    first["beats"][1]["steps"] = [action("他站着。")]
    second["beats"][1]["steps"] = [action("他停三十秒，然后拿纸、走到门边、折回、坐下、再翻阅一百页。")]
    a = v3.preliminary_timing_estimates(first)["by_beat_id"]["NEW2"]
    b = v3.preliminary_timing_estimates(second)["by_beat_id"]["NEW2"]
    assert a["budget_seconds"] == b["budget_seconds"] == 6
    assert b["pause_duration_seconds"] is None
    assert b["actual_windows_verified"] is False


def test_all_action_beat_positive_compatibility_budget_has_empty_dialogue_slots():
    generated = raw()
    generated["beats"][0]["steps"] = [action("她没有接笔。")]
    derived = v3.accept_linear_script(previous(), generated)
    assert derived["beats"][0]["duration_seconds"] > 0
    assert derived["beats"][0]["dialogue"] == []
    assert derived["beats"][0]["during"] == v3.EMPTY_ACTION
    assert derived["beats"][0]["after"] == v3.EMPTY_ACTION
    assert derived["beats"][0]["before"] == "她没有接笔。"


def test_new_silent_character_requires_bound_asset_name_not_previous_dialogue():
    generated = raw()
    generated["beats"][0]["steps"] = [dialogue("顾客", "谢谢。")]
    with pytest.raises(CreativeContractError):
        v3.accept_linear_script(previous(), generated)
    derived = v3.accept_linear_script(previous(), generated, character_names=["顾客", "方澄", "林屿"])
    assert derived["beats"][0]["dialogue"] == [{"speaker": "顾客", "text": "谢谢。"}]


def test_messages_keep_complete_reference_context_previous_and_issues_unchanged():
    ctx, old, issues = context(), previous(), [{"id": "I01", "evidence": "完整失败证据"}]
    saved = deepcopy((ctx, old, issues))
    messages = v3.build_linear_script_messages(ctx, old, issues)
    payload = json.loads(messages[1]["content"])
    assert (ctx, old, issues) == saved
    assert payload["context"] == ctx and payload["previous_script"] == old and payload["issues"] == issues
    assert payload["context"]["reference_pack"] == ctx["reference_pack"]
    assert payload["revision_mode"] == "complete_new_script"
    assert "duration_seconds" not in payload["field_dictionary"]
    assert "局部表演模型" in messages[0]["content"] and "任意动作预算未计时" in messages[0]["content"]
    assert "柔性范围" in messages[0]["content"]
    assert "每拍最多两句对白只是现有对白接口限制" in messages[0]["content"]
    assert "可含多个镜头" in messages[0]["content"]
    assert "一拍一个观察镜头" not in messages[0]["content"]


@pytest.mark.parametrize("mutate,code", [
    (lambda r: r.update(duration_seconds=11), "LINEAR_SCHEMA_INVALID"),
    (lambda r: r["beats"][0].update(duration_seconds=11), "LINEAR_SCHEMA_INVALID"),
    (lambda r: r["beats"][0].update(timing_estimate=11), "LINEAR_SCHEMA_INVALID"),
    (lambda r: r.update(selected_candidate_id="other"), "LINEAR_IDENTITY_CHANGED"),
    (lambda r: r["beats"][1].update(id="NEW1"), "LINEAR_BEAT_ID_INVALID"),
    (lambda r: r["beats"][0].update(event="  "), "LINEAR_SCHEMA_INVALID"),
    (lambda r: r["beats"][0]["steps"][0].update(text="  "), "LINEAR_STEP_TEXT_INVALID"),
    (lambda r: r["beats"][0]["steps"][0].update(speaker="方澄"), "LINEAR_ACTION_SPEAKER_INVALID"),
    (lambda r: r["beats"][0]["steps"][1].update(speaker=""), "LINEAR_SPEAKER_INVALID"),
    (lambda r: r["beats"][0]["steps"].append(dialogue("方澄", "第三句。")), "LINEAR_TOO_MANY_DIALOGUES"),
    (lambda r: r["beats"][0].update(steps=[]), "LINEAR_SCHEMA_INVALID"),
])
def test_invalid_complete_contract_rejected_without_source_rewrite(mutate, code):
    generated = raw()
    mutate(generated)
    saved = deepcopy(generated)
    with pytest.raises(CreativeContractError, match=code):
        v3.accept_linear_script(previous(), generated)
    assert generated == saved


def test_legacy_projection_cap_is_explicit_fail_not_silent_budget_capping():
    generated = raw()
    generated["beats"][0]["steps"] = [dialogue("方澄", "字" * 2100)]
    saved = deepcopy(generated)
    assert v3.preliminary_timing_estimates(generated)["by_beat_id"]["NEW1"]["budget_seconds"] > 600
    with pytest.raises(CreativeContractError, match="LINEAR_PRELIMINARY_COMPATIBILITY_LIMIT"):
        v3.accept_linear_script(previous(), generated)
    assert generated == saved


def review_without_actual_timing():
    derived = v3.accept_linear_script(previous(), raw())
    ctx = {"script": derived, "preliminary_timing_estimates": v3.preliminary_timing_estimates(raw())}
    coverage = []
    for i, beat in enumerate(derived["beats"]):
        own = {"path": f"script.beats.{i}.before", "quote": beat["before"]}
        checks = {name: {"status": "pass", "reason": "正文对照结论", "evidence_refs": [deepcopy(own)], "issue_ids": []}
                  for name in ["requirements", "timing", "continuity", "dialogue_timing", "first_frame", "assets"]}
        checks["timing"]["reason"] = "仅审steps刺激、对白和反应先后，实际秒数未编排。"
        checks["dialogue_timing"] = {"status": "not_applicable", "reason": "仅程序暂定预算，无实际对白及反应窗口，待局部排程。", "evidence_refs": [], "issue_ids": []}
        checks["first_frame"] = {"status": "not_applicable", "reason": "本次只有剧本正文。", "evidence_refs": [], "issue_ids": []}
        if i:
            checks["continuity"]["evidence_refs"].append({"path": f"script.beats.{i-1}.after", "quote": derived["beats"][i-1]["after"]})
        coverage.append({"id": beat["id"], "checks": checks})
    return ctx, {"story_preserved": True, "issues": [], "suggestions": [], "calibration_focus": [], "coverage": coverage}


def test_original_v7_allows_script_dialogue_na_without_losing_sequence_sources():
    ctx, review = review_without_actual_timing()
    before = deepcopy((ctx, review))
    validate_review_v7(review, ctx)
    assert (ctx, review) == before
    assert ctx["preliminary_timing_estimates"]["actual_windows_verified"] is False


def test_original_v7_still_requires_narrative_timing_and_previous_beat_sources():
    ctx, review = review_without_actual_timing()
    review["coverage"][0]["checks"]["timing"].update(status="not_applicable", evidence_refs=[])
    with pytest.raises(CreativeContractError, match="不能跳过"):
        validate_review_v7(review, ctx)
    ctx, review = review_without_actual_timing()
    review["coverage"][1]["checks"]["continuity"]["evidence_refs"] = review["coverage"][1]["checks"]["continuity"]["evidence_refs"][:1]
    with pytest.raises(CreativeContractError, match="v7"):
        validate_review_v7(review, ctx)
