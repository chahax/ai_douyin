from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / "data" / "qa" / "reference_404263_detailed_two_style_full_20260826"


def _load(style: str) -> dict:
    return json.loads((QA / style / "story_project.json").read_text(encoding="utf-8"))


def test_generation_prompts_are_english_and_keep_chinese_audit_fields() -> None:
    chinese = re.compile(r"[\u4e00-\u9fff]")
    for style in ("semireal", "bighead3d"):
        project = _load(style)
        for shot in project["shots"]:
            assert not chinese.search(shot["prompt"]), shot["id"]
            assert not chinese.search(shot["motion"]), shot["id"]
            assert chinese.search(shot["prompt_zh_audit"]), shot["id"]
            assert chinese.search(shot["motion_zh_audit"]), shot["id"]


def test_hard_gate_shots_have_explicit_physical_staging() -> None:
    project = _load("semireal")
    shots = {shot["id"]: shot for shot in project["shots"]}
    for shot_id in ("001", "015", "017", "032", "039", "049", "058", "064f"):
        assert shots[shot_id]["benchmark_human_gate_fix"] is True
    assert "Exactly two" in shots["058"]["prompt"]
    assert "already pressed flat to his right ear" in shots["064f"]["prompt"]
    assert "full chair" in shots["017"]["prompt"]
