"""Phase boundaries and typed arithmetic failures; no paid or media calls."""
from copy import deepcopy
import json

import pytest

from src.content_factory import creative_complete_production_pipeline_v3 as p
from src.content_factory import creative_complete_production_pipeline_v1 as old
from tests.test_creative_complete_production_pipeline_v2 import v2_fixture


def test_director_and_performance_have_separate_actual_request_rules():
    script, manifest, initial, direction, _ = v2_fixture()
    inputs = p.build_director_input(script, manifest, initial, "完整教学参考正文", {"style": "写实"})
    req = p.build_request("whole_direction", inputs, p.whole_direction_schema(script, manifest), "MiniMax-M3")
    assert req["messages"][0]["content"] == p.DIRECTOR_RULE
    assert "提交完整ending_state" not in req["messages"][0]["content"]
    assert "range_columns" in req["messages"][0]["content"] and "budget_columns" in req["messages"][0]["content"]
    assert "range_columns" in inputs["candidate_graph"] and "budget_columns" in inputs["candidate_graph"]
    assert json.loads(req["messages"][1]["content"]) == inputs
    assert req["messages"][1]["content"].count("完整教学参考正文") == 1
    assert "payload_json" in req["structured_schema"]["properties"]
    assert req["inner_document_schema"] == p.whole_direction_schema(script, manifest)
    assert "ending_state" not in req["inner_document_schema"]["properties"]
    local = p.build_performance_input(script, manifest, direction["segments"][0], initial, [], "完整教学参考正文", {})
    local_req = p.build_request("local_performance", local,
        p.performance_schema(script, manifest, direction["segments"][0], initial, []), "MiniMax-M3")
    assert local_req["messages"][0]["content"] == p.PERFORMANCE_RULE
    assert "ending_state" in local_req["inner_document_schema"]["properties"]
    assert "candidate_graph" not in local
    assert "full_current_script" not in local
    assert json.loads(local_req["messages"][1]["content"]) == local


def test_normal_unchanged_local_still_recompiles_identically():
    script, manifest, initial, direction, performances = v2_fixture()
    assert p.compile_performance(performances[0]["native"], script, manifest,
        direction["segments"][0], initial, []) == performances[0]
    complete = p.compile_complete(direction, performances, script, manifest, initial)
    assert complete["whole_source_coverage_complete"]
    assert not complete["actual_media_quality_passed"]


def test_overflow_returns_original_full_estimate_not_shortened_accepted_performance():
    script, manifest, initial, direction, performances = v2_fixture()
    raw = deepcopy(performances[0]["native"])
    raw["action_timings"][0]["duration_seconds"] = 6
    before = deepcopy(raw)
    with pytest.raises(p.PerformanceWindowExceeded) as result:
        p.compile_performance(raw, script, manifest, direction["segments"][0], initial, [])
    diagnostic = result.value.diagnostic
    assert diagnostic["required_seconds"] > diagnostic["target_seconds"]
    assert diagnostic["complete_native_performance"] == raw == before
    assert diagnostic["normal_schedule"][0]["duration_seconds"] == 6
    assert diagnostic["whole_direction_revision_required"]
    assert not diagnostic["manual_source_or_timing_patch_allowed"]
    assert diagnostic["result_is_not_adopted"]
    assert not diagnostic["physical_acting_verified"]


@pytest.mark.parametrize("defect", ["state", "unknown", "stimulus", "type"])
def test_other_failures_do_not_masquerade_as_director_timing_failure(defect):
    script, manifest, initial, direction, performances = v2_fixture()
    raw = deepcopy(performances[0]["native"])
    raw["action_timings"][0]["duration_seconds"] = 6
    if defect == "state": raw["state_changes"] = []
    if defect == "unknown": raw["availability"] = "unknown"
    if defect == "stimulus": raw["actor_goals"][1]["source_reception"]["stimuli"][0]["channel"] = "visible"
    if defect == "type": raw["action_timings"] = {"item": raw["action_timings"]}
    with pytest.raises(ValueError) as result:
        p.compile_performance(raw, script, manifest, direction["segments"][0], initial, [])
    assert not isinstance(result.value, p.PerformanceWindowExceeded)


def test_current_director_intent_is_in_video_prompt_without_future_dialogue():
    script, manifest, _, _, performances = v2_fixture()
    raw = deepcopy(performances[0])
    raw["segment"]["observation"] = "先看周姐发出要求，随后看小林是否接住"
    raw = old.compile_performance(raw["native"], script, manifest, raw["segment"], raw["planned_initial_state"], raw["completed_refs"])
    prompt = p.render_prompt(raw, script, manifest)
    assert "先看周姐发出要求，随后看小林是否接住" in prompt
    assert prompt.count("请看这张纸。") == 1
    assert "我先看一下。" not in prompt
    assert "离线全片计划预览" in prompt


def test_review_request_is_separate_and_unknown_remains_unknown():
    req = p.build_request("whole_production_review", {"full": "参考与当前全片"}, {"type": "object"}, "deepseek-v4-flash")
    assert req["role"] == "director"
    assert req["messages"][0]["content"] == p.REVIEW_RULE
    assert "unknown" in p.REVIEW_RULE
    assert "output_transport" not in req
