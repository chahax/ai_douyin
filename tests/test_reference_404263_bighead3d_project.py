from __future__ import annotations

import json
from pathlib import Path

from scripts.build_reference_404263_bighead3d_project import build_story_project
from scripts.compose_reference_404263_bighead3d_candidate import audio_filter, srt_time, wrap_caption


ROOT = Path(__file__).resolve().parents[1]


def test_bighead3d_project_preserves_source_timeline_and_review_gate() -> None:
    plan = json.loads(
        (ROOT / "data/fanqie_promotion/scene_plans/reference_404263_full_workflows_v2.json").read_text(
            encoding="utf-8"
        )
    )
    project = build_story_project(plan)

    assert len(project["shots"]) == 24
    assert round(sum(float(shot["duration"]) for shot in project["shots"]), 2) == 103.63
    assert sum(1 for shot in project["shots"] if shot.get("continuity_from")) == 5
    assert all((int(shot["frames"]) - 1) % 8 == 0 for shot in project["shots"])
    assert project["continuity_policy"]["active_phone_screens_stay_lit"] is True
    assert project["publish_allowed"] is False
    assert project["douyin_upload_allowed"] is False
    assert project["fanqie_backfill_allowed"] is False


def test_bighead3d_composer_helper_contracts() -> None:
    assert srt_time(3.27) == "00:00:03,270"
    assert "\n" in wrap_caption("最像关心的话，原来只是批量复制的剧本。")
    assert "atrim=duration=3.270000" in audio_filter(3.98, 3.27)
