from __future__ import annotations

import hashlib
from pathlib import Path

from scripts.build_task1_story_v63_visual_retention_plan import (
    ACTION_SCENES,
    NATURAL_ACTION_SCENES,
    STABLE_SCENES,
    build,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def test_v63_uses_19_unique_original_anchors_and_no_reference_pixels() -> None:
    payload = build()
    branch = payload["variants"]["visual_retention_v1"]
    units = branch["new_framepack_units"]

    assert payload["schema_version"] == "fanqie_v63_visual_retention_workflow/v1"
    assert len(units) == 19
    assert len({unit["anchor_path"] for unit in units}) == 19
    assert len({unit["anchor_sha256"] for unit in units}) == 19
    assert branch["reference_video_pixels_allowed"] is False
    assert branch["reference_people_allowed"] is False
    assert branch["reference_watermark_allowed"] is False
    assert branch["publish_allowed"] is False
    assert branch["fanqie_backfill_allowed"] is False
    for unit in units:
        anchor = Path(unit["anchor_path"])
        assert anchor.is_file()
        assert _sha256(anchor) == unit["anchor_sha256"]


def test_v63_renderer_partition_is_exact() -> None:
    branch = build()["variants"]["visual_retention_v1"]
    by_renderer: dict[str, set[str]] = {}
    for unit in branch["new_framepack_units"]:
        by_renderer.setdefault(unit["renderer"], set()).add(unit["scene_id"])

    assert by_renderer == {
        "local_framepack_i2v": ACTION_SCENES,
        "deterministic_camera_motion_candidate_only": STABLE_SCENES,
    }
    assert branch["action_scene_ids"] == sorted(ACTION_SCENES)
    assert branch["stable_insert_scene_ids"] == sorted(STABLE_SCENES)


def test_v63_has_complete_40_8_second_microshot_timeline() -> None:
    payload = build()
    branch = payload["variants"]["visual_retention_v1"]
    microshots = branch["microshots"]
    unit_ids = {unit["scene_id"] for unit in branch["new_framepack_units"]}

    assert len(microshots) == 32
    assert {shot["source_unit"] for shot in microshots} == unit_ids
    assert round(sum(float(shot["duration_seconds"]) for shot in microshots), 3) == 40.8
    assert all(shot["cut"] == "hard_cut_on_action" for shot in microshots)
    assert payload["delivery"] == {
        "width": 1080,
        "height": 1920,
        "fps": 30,
        "target_duration_seconds": 40.8,
        "hard_cut_only": True,
    }


def test_v63_has_three_distinct_visual_phases() -> None:
    phases = build()["variants"]["visual_retention_v1"]["visual_phases"]

    assert [phase["range"] for phase in phases] == ["0.0-18.0", "18.0-30.0", "30.0-40.8"]
    assert len({phase["look"] for phase in phases}) == 3


def test_v63_natural_action_repairs_forbid_overacted_blocking_and_watch_check() -> None:
    branch = build()["variants"]["visual_retention_v1"]
    units = {unit["scene_id"]: unit for unit in branch["new_framepack_units"]}
    expected_anchors = {
        "b02_grab_reaction": "b02_natural_wrist_contact_v2.png",
        "b05_age_burst": "b05_direct_age_question_v2.png",
        "b06_pull_away": "b06_natural_wrist_lead_v2.png",
        "b07_protest": "b07_upright_protest_v2.png",
    }

    for scene_id in NATURAL_ACTION_SCENES:
        unit = units[scene_id]
        prompt = unit["prompt"].lower()
        negative = unit["negative_prompt"].lower()
        assert Path(unit["anchor_path"]).name == expected_anchors[scene_id]
        assert "upright" in prompt
        assert "crouch" in negative
        assert "lunge" in negative
        assert "looking at watch" in negative

    assert "watch" not in units["b05_age_burst"]["prompt"].lower().replace("no watch interaction", "")
    assert branch["action_direction_contract"]["external_minimax_used"] is False
    assert branch["action_direction_contract"]["local_prompt_review_model"] == "ollama/qwen2.5:7b"
