"""Audit a source-bound novel storyboard and persist a review decision."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

from src.content_factory.novel_schemas import NovelSplit
from src.content_factory.novel_splitter import (
    _audit_storyboard_grounding,
    _find_dialogue_emotion_errors,
    _find_dialogue_timing_errors,
    _find_unanchored_dialogue,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--storyboard", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source = args.source.read_text(encoding="utf-8").strip()
    analysis = json.loads(args.analysis.read_text(encoding="utf-8"))
    payload = json.loads(args.storyboard.read_text(encoding="utf-8"))
    storyboard = NovelSplit.model_validate(payload["storyboard"])
    selected = analysis["selected_highlight"]
    excerpt = source[int(selected["source_start_char"]) : int(selected["source_end_char"])]

    checks = {
        "source_hash_matches_analysis": (
            hashlib.sha256(source.encode("utf-8")).hexdigest().upper()
            == str(analysis["source_sha256"]).upper()
        ),
        "excerpt_hash_matches_storyboard": (
            hashlib.sha256(excerpt.encode("utf-8")).hexdigest().upper()
            == str(payload["source_excerpt_sha256"]).upper()
        ),
        "dialogue_source_errors": _find_unanchored_dialogue(storyboard, excerpt),
        "dialogue_timing_errors": _find_dialogue_timing_errors(storyboard),
        "emotion_errors": _find_dialogue_emotion_errors(storyboard),
    }
    grounding_errors = _audit_storyboard_grounding(
        storyboard,
        excerpt,
        caller="novel_highlight_storyboard_final_audit",
        use_cache=True,
    )
    passed = (
        checks["source_hash_matches_analysis"]
        and checks["excerpt_hash_matches_storyboard"]
        and not checks["dialogue_source_errors"]
        and not checks["dialogue_timing_errors"]
        and not checks["emotion_errors"]
        and not grounding_errors
    )
    report = {
        "schema": "novel_storyboard_review/v1",
        "decision": "passed" if passed else "rejected",
        "reviewed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "storyboard_path": str(args.storyboard),
        "storyboard_sha256": hashlib.sha256(args.storyboard.read_bytes()).hexdigest().upper(),
        "scene_count": len(storyboard.scenes),
        "duration_seconds": storyboard.total_duration_seconds,
        "checks": checks,
        "grounding_errors": grounding_errors,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if passed else 2)


if __name__ == "__main__":
    main()
