"""Regular complete revisions retain history without prompt accumulation."""
from copy import deepcopy
import json
import socket

import pytest

from tests.test_creative_complete_production_coordinator_v4 import (
    FakeService, endpoints, fixture, run,
)
from src.content_factory import creative_complete_production_coordinator_v4 as flow
from src.content_factory import creative_complete_production_pipeline_v4 as pipeline
from src.content_factory import creative_production_revision_loop_v3 as loop


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("offline prompt-scope check")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


class TwoRejectedDirectors(FakeService):
    def invoke(self, label, request, validate):
        original = self.direction
        if request["stage"] == "whole_direction" and self.directors < 2:
            self.direction = deepcopy(original)
            self.direction["whole_observation"] = "完整失败原稿_" + str(self.directors + 1)
            self.direction["segments"][-1]["end_source_ref"] = self.direction["segments"][0]["end_source_ref"]
        try:
            return super().invoke(label, request, validate)
        finally:
            self.direction = original


def test_third_director_receives_latest_complete_failure_only_and_history_survives(tmp_path):
    script, manifest, initial, direction, performances, brief, opening = fixture(tmp_path)
    service = TwoRejectedDirectors(endpoints(direction, script, manifest), performances)
    state = loop.initial_loop_state([], "a" * 64, default_limit=3,
        stable_scope_material={"full_current_script": script, "shared_manifest": manifest,
            "planned_initial_state": initial})
    context = {"brief": brief, "reference_fulltext": "R01完整教学参考全文", "production_preferences": {}}
    runner = flow.CompleteProductionCoordinator(invoke=service.invoke, persist_state=service.save,
        verify_frozen_source=service.guard, opening_context_builder=opening,
        models={"writer": "MiniMax-M3", "director": "deepseek-flash"})
    result = runner.run(script=script, manifest=manifest, initial=initial,
        reference_fulltext=context["reference_fulltext"], preferences={}, brief=brief,
        source_review_binding={"writer_ordinal": 1, "review_ordinal": 2,
            "script_sha256": pipeline.digest(script), "machine_text_review_passed": True,
            "production_context_sha256": pipeline.digest(context)}, state=state,
        scope={"max_new_video_submissions": 0})
    assert result["complete_text_handoff_ready"] is True
    directors = [r for r in service.calls if r["request"]["stage"] == "whole_direction"]
    assert len(directors) == 3
    latest_input = json.loads(directors[2]["request"]["messages"][1]["content"])
    serialized = json.dumps(latest_input, ensure_ascii=False)
    assert "完整失败原稿_2" in serialized
    assert "完整失败原稿_1" not in serialized
    history = json.dumps(result["loop_state"]["director_events"], ensure_ascii=False)
    assert "完整失败原稿_1" in history and "完整失败原稿_2" in history
    assert loop.candidate_capacity(result["loop_state"])["attempts_including_claims"] == 3
    assert result["budget_reset"] is False


def test_feedback_replacement_keeps_stop_summary_without_earlier_native_or_mutation():
    summary = {"previous_stop_summary": {"reason": "bounded", "terminal_sha256": "a" * 64}}
    old = [summary, {"prior_complete_native_direction": {"title": "old complete"}}]
    current = {"complete_failed_native": {"title": "latest complete"}}
    value = flow.CompleteProductionCoordinator._latest_revision_diagnostics(old, current)
    assert value == [summary, current]
    current["complete_failed_native"]["title"] = "changed"
    assert value[1]["complete_failed_native"]["title"] == "latest complete"
    assert len(old) == 2


@pytest.mark.parametrize("mode", ["window", "review_fail"])
def test_window_and_full_review_routes_keep_one_latest_complete_feedback(tmp_path, mode):
    result, service = run(tmp_path, mode)
    assert result["complete_text_handoff_ready"]
    inputs = [json.loads(r["request"]["messages"][1]["content"])
        for r in service.calls if r["request"]["stage"] == "whole_direction"]
    assert len(inputs) == 2
    # The director input has one native revision feedback, while the earlier
    # complete results and full review remain in the state and event journal.
    feedback_lists = [v for k, v in inputs[-1].items() if "diagnostic" in k]
    assert feedback_lists and all(isinstance(v, list) and len(v) == 1 for v in feedback_lists)
    assert result["loop_state"]["stage_dispatch_events"]
