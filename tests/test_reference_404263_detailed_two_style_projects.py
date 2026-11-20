from __future__ import annotations

from pathlib import Path

from scripts.build_reference_404263_detailed_two_style_projects import (
    CHARACTER_BY_SHOT,
    DEFAULT_SCRIPT,
    build_project,
    parse_rows,
    rounded_frames,
)


def _rows() -> list[dict[str, object]]:
    assert "docs/archive/2026-09-video-pipeline-reset" in Path(DEFAULT_SCRIPT).as_posix()
    return parse_rows(Path(DEFAULT_SCRIPT).read_text(encoding="utf-8"))


def test_detailed_script_expands_to_69_segments_and_exact_timeline() -> None:
    rows = _rows()

    assert len(rows) == 69
    assert [row["id"] for row in rows[-6:]] == [
        "064a", "064b", "064c", "064d", "064e", "064f"
    ]
    assert rows[0]["start"] == 0.0
    assert rows[-1]["end"] == 104.3


def test_two_style_projects_keep_content_fixed_and_release_locked() -> None:
    rows = _rows()
    semireal = build_project("semireal", rows, DEFAULT_SCRIPT)
    bighead = build_project("bighead3d", rows, DEFAULT_SCRIPT)

    assert len(semireal["shots"]) == len(bighead["shots"]) == 69
    assert semireal["duration_seconds"] == bighead["duration_seconds"] == 104.3
    assert [shot["id"] for shot in semireal["shots"]] == [
        shot["id"] for shot in bighead["shots"]
    ]
    assert [shot["source_action"] for shot in semireal["shots"]] == [
        shot["source_action"] for shot in bighead["shots"]
    ]
    assert sum(shot["render_mode"] == "ltx_i2v" for shot in semireal["shots"]) == 50
    assert sum(shot["render_mode"] == "deterministic" for shot in semireal["shots"]) == 19
    assert semireal["publish_allowed"] is False
    assert bighead["douyin_upload_allowed"] is False
    assert bighead["fanqie_backfill_allowed"] is False


def test_character_mapping_and_ltx_lengths_are_complete() -> None:
    rows = _rows()

    assert set(CHARACTER_BY_SHOT) == {str(row["id"]) for row in rows}
    for row in rows:
        duration = float(row["end"]) - float(row["start"])
        frames = rounded_frames(duration)
        assert (frames - 1) % 8 == 0
        assert frames / 25.0 >= duration
