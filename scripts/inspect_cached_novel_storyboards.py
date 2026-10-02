"""Collect cached storyboard candidates and run deterministic local gates."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

import diskcache
from pydantic import ValidationError

from src.content_factory.novel_schemas import NovelSplit
from src.content_factory.novel_splitter import (
    _find_dialogue_emotion_errors,
    _find_dialogue_timing_errors,
    _find_unanchored_dialogue,
    _fit_dialogue_durations,
    _restore_unique_source_dialogue,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    source = args.source.read_text(encoding="utf-8").strip()
    analysis = json.loads(args.analysis.read_text(encoding="utf-8"))
    selected = analysis["selected_highlight"]
    segment = source[int(selected["source_start_char"]) : int(selected["source_end_char"])]
    title = analysis["novel_title"]
    args.output_dir.mkdir(parents=True, exist_ok=True)

    cache = diskcache.Cache("./data/llm_cache")
    seen: set[str] = set()
    summaries: list[dict] = []
    for key in cache:
        value = cache.get(key)
        if not isinstance(value, str):
            continue
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict) or not isinstance(payload.get("scenes"), list):
            continue
        if str(payload.get("novel_title") or "") != title:
            continue
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        path = args.output_dir / f"candidate_{digest[:12]}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        summary = {"sha256": digest, "path": str(path), "raw_scene_count": len(payload["scenes"])}
        try:
            storyboard = NovelSplit.model_validate(copy.deepcopy(payload))
        except ValidationError as exc:
            summary.update(schema_valid=False, schema_error=exc.errors()[0]["msg"])
            summaries.append(summary)
            continue
        duration_repairs = _fit_dialogue_durations(storyboard)
        dialogue_repairs = _restore_unique_source_dialogue(storyboard, segment)
        summary.update(
            schema_valid=True,
            scene_count=len(storyboard.scenes),
            total_duration_seconds=storyboard.total_duration_seconds,
            duration_repairs=duration_repairs,
            dialogue_repairs=dialogue_repairs,
            dialogue_errors=_find_unanchored_dialogue(storyboard, segment),
            timing_errors=_find_dialogue_timing_errors(storyboard),
            emotion_errors=_find_dialogue_emotion_errors(storyboard),
            non_neutral=sum(
                line.emotion != "neutral"
                for scene in storyboard.scenes
                for line in scene.dialogue
            ),
            dialogue_count=sum(len(scene.dialogue) for scene in storyboard.scenes),
            opening=[
                {
                    "scene_id": scene.scene_id,
                    "narration": scene.narration,
                    "dialogue": [line.model_dump() for line in scene.dialogue],
                }
                for scene in storyboard.scenes[:2]
            ],
        )
        normalized_path = args.output_dir / f"candidate_{digest[:12]}.normalized.json"
        normalized_path.write_text(
            json.dumps(storyboard.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        summary["normalized_path"] = str(normalized_path)
        summaries.append(summary)
    summaries.sort(
        key=lambda item: (
            not item.get("schema_valid", False),
            len(item.get("dialogue_errors", [])),
            len(item.get("timing_errors", [])),
            len(item.get("emotion_errors", [])),
            abs(int(item.get("scene_count", 0)) - 17),
        )
    )
    report = {"candidate_count": len(summaries), "candidates": summaries}
    (args.output_dir / "candidate_summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
