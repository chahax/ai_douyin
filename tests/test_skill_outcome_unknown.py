from __future__ import annotations

import time

from src.agent.registry import SkillRegistry
from src.agent.skill_decorator import Skill


def test_timed_out_thread_is_outcome_unknown_and_not_retried(monkeypatch):
    effects = []

    def slow_side_effect():
        time.sleep(0.12)
        effects.append("completed")
        return {"success": True}

    registry = SkillRegistry()
    registry._skills["fixture_unknown"] = Skill(
        name="fixture_unknown",
        description="fixture",
        func=slow_side_effect,
        requires_confirmation=False,
        timeout_s=0.02,
        retries=2,
        retry_on=("timeout", "outcome_unknown"),
    )
    monkeypatch.setattr(registry, "_save_to_problem_memory", lambda *args: None)

    result = registry.call("fixture_unknown", {})

    assert result["success"] is False
    assert result["code"] == "outcome_unknown"
    assert result["attempts"] == 1
    assert result["error"]["retryable"] is False
    time.sleep(0.15)
    assert effects == ["completed"]
