from __future__ import annotations

import hashlib
from pathlib import Path

from scripts.build_task1_story_v62_microshot_plan import build
from scripts.compose_task1_story_v62_candidate import (
    _escape_subtitle_filter,
    _video_filter,
)


EXPECTED_BEATS = {
    "b01_boast",
    "b02_grab_reaction",
    "b03_object_question",
    "b04_confused_answer",
    "b05_age_burst",
    "b06_pull_away",
    "b07_protest",
    "b08_offer_one",
    "b09_offer_two",
    "b10_offer_three",
    "b11_flip",
    "b12_car_reveal",
    "b13_registry_reveal",
    "b14_certificate",
    "b15_terms",
    "b16_escape",
    "b17a_kiss_reaction",
    "b17b_hunt_order",
    "b18_cta",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def test_original_branch_rebuilds_every_story_beat() -> None:
    payload = build()
    branch = payload["variants"]["original_recomposed"]
    units = branch["new_framepack_units"]

    assert payload["schema_version"] == "fanqie_v62_microshot_workflow/v2"
    assert branch["all_story_beats_use_new_original_anchors"] is True
    assert branch["reuse_sources"] == {}
    assert {unit["scene_id"] for unit in units} == EXPECTED_BEATS
    assert len(units) == 19
    assert branch["publish_allowed"] is False
    assert branch["fanqie_backfill_allowed"] is False

    for unit in units:
        anchor = Path(unit["anchor_path"])
        assert anchor.is_file()
        assert _sha256(anchor) == unit["anchor_sha256"]
        assert unit["publish_allowed"] is False


def test_microshots_are_complete_and_bound_to_new_units() -> None:
    branch = build()["variants"]["original_recomposed"]
    unit_ids = {unit["scene_id"] for unit in branch["new_framepack_units"]}
    microshots = branch["microshots"]

    assert len(microshots) == 32
    assert {shot["source_unit"] for shot in microshots} == unit_ids
    assert round(sum(shot["duration_seconds"] for shot in microshots), 3) == 40.8
    assert all(shot["cut"] == "hard_cut_on_action" for shot in microshots)


def test_direct_reference_branch_can_never_authorize_publication() -> None:
    branch = build()["variants"]["direct_reference_i2v"]

    assert branch["role"] == "internal_motion_reference"
    assert branch["contains_reference_people_or_watermark"] is True
    assert branch["frontend_approval_cannot_authorize_publication"] is True
    assert branch["publish_allowed"] is False
    assert branch["fanqie_backfill_allowed"] is False
    assert len(branch["new_framepack_units"]) == 16
    assert len(branch["microshots"]) == 32
    assert round(sum(s["duration_seconds"] for s in branch["microshots"]), 3) == 40.8


def test_composer_supports_every_declared_crop() -> None:
    payload = build()
    crops = {
        shot["crop"]
        for branch in payload["variants"].values()
        for shot in branch["microshots"]
    }

    assert crops == {
        "background_detail",
        "eye_close",
        "full",
        "hand_close",
        "lower_detail",
        "upper_close",
    }
    assert all("fps=30" in _video_filter(crop) for crop in crops)


def test_subtitle_filter_escapes_windows_drive_colon() -> None:
    escaped = _escape_subtitle_filter(Path(r"D:\IT\ai_douyin\candidate.srt"))

    assert escaped.startswith(r"D\:/")
    assert escaped.count("\\") == 1
