from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/audit_task1_story_v61_creative_contract.py"
REAL_PLAN = ROOT / "data/fanqie_promotion/scene_plans/task1_story_v61_reviewed_anchors.json"


def _module():
    spec = importlib.util.spec_from_file_location("v61_creative_audit", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _mutated(tmp_path: Path, mutate) -> Path:
    data = json.loads(REAL_PLAN.read_text(encoding="utf-8"))
    mutate(data)
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_real_plan_satisfies_exact_creative_contract() -> None:
    result = _module().audit(REAL_PLAN)
    assert result["passed"] is True, result["errors"]
    assert result["metrics"]["beat_count"] == 19
    assert result["metrics"]["total_seconds"] == 40.8
    assert result["metrics"]["median_shot_seconds"] == 2.0
    assert all(result["requirements"].values())
    assert result["human_quality_gates"]["natural_emotional_voice_proven"] is False
    assert result["human_quality_gates"][
        "natural_emotional_voice_requires_frontend_smoke_review"
    ] is True
    assert result["human_quality_gates"][
        "whole_video_natural_voice_requires_frontend_final_review"
    ] is True
    assert len(result["material_evidence"]["anchors"]) == 19
    assert len(result["material_evidence"]["character_masters"]) == 2
    assert len(result["material_evidence"]["voice_references"]) == 2
    assert all(
        item["ok"]
        for group in result["material_evidence"].values()
        for item in group
    )
    assert all(value == 0 for value in result["side_effects"].values())


@pytest.mark.parametrize(
    "mutate, marker",
    [
        (lambda d: d["creative_contract"].__setitem__("explanatory_narration_allowed", True), "explanatory narration"),
        (lambda d: d["beats"][0].__setitem__("visible_action", ""), "visible action"),
        (lambda d: d["beats"][0].__setitem__("emotion", ""), "readable emotion"),
        (lambda d: d["beats"][0].__setitem__("instruct", ""), "emotion/instruct"),
        (lambda d: d["beats"][0].__setitem__("speed", 1.5), "performance speed"),
        (lambda d: d["beats"][0].__setitem__("speed", "fast"), "performance speed"),
        (lambda d: d["beats"][0].__setitem__("speed", True), "performance speed"),
        (lambda d: d["cast"]["lin_xia"].__setitem__("age", "adult"), "explicitly adult"),
        (lambda d: d["beats"][0].__setitem__("speaker", ""), "cast speaker"),
        (lambda d: d["beats"][0].__setitem__("text", "本书讲述一个故事"), "explanatory narration marker"),
        (lambda d: d["beats"][0].__setitem__("duration_target_seconds", 8), "duration outside"),
        (lambda d: d["beats"].reverse(), "beat IDs/order"),
        (lambda d: d["beats"][-1].__setitem__("delivery_mode", "voiceover"), "delivered on camera"),
        (lambda d: d["creative_contract"].__setitem__("cta_delivery_mode", "voiceover"), "CTA delivery"),
        (lambda d: d["creative_contract"].__setitem__("voiceover_allowed", True), "voiceover must be forbidden"),
    ],
)
def test_creative_regressions_fail_closed(tmp_path: Path, mutate, marker: str) -> None:
    result = _module().audit(_mutated(tmp_path, mutate))
    assert result["passed"] is False
    assert marker in " ".join(result["errors"])


def test_audit_output_never_overwrites(tmp_path: Path) -> None:
    module = _module()
    output = tmp_path / "audit.json"
    module._write_exclusive(output, {"passed": True})
    with pytest.raises(ValueError, match="refusing to overwrite"):
        module._write_exclusive(output, {"passed": False})
    assert json.loads(output.read_text(encoding="utf-8"))["passed"] is True
