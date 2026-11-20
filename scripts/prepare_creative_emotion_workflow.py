"""Prepare the new emotion/director/media contract offline, never dispatch."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.content_factory.creative_story_emotion import build_emotion_revision_input, digest
from src.content_factory.creative_video_projection import compile_generation_plan, file_sha

INPUT_NAMES = ("FULL_SCRIPT.json", "STATIC_ASSET_DEFINITIONS.json",
               "REVIEWED_EXECUTION_VIEW.json", "COMPILED_PERFORMANCE.json",
               "FULL_TEXT_REVIEW.json", "PRODUCTION_HANDOFF.json")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def prepare_run(source, brief_path, arrangement_path, reference_path, feedback_path,
                *, confirmation_path=None, model="doubao-seedance-2-0-mini-260615"):
    source = Path(source).resolve()
    paths = [source / n for n in INPUT_NAMES]
    before = {str(p): file_sha(p) for p in paths}
    script, assets, view, compiled, review, handoff = [read(p) for p in paths]
    for key, value in (("script_sha256", script), ("compiled_sha256", compiled),
                       ("reviewed_view_sha256", view), ("review_sha256", review)):
        if handoff.get(key) != digest(value):
            raise ValueError("production handoff source changed: " + key)
    brief, arrangement, references, feedback = [
        read(p) for p in (brief_path, arrangement_path, reference_path, feedback_path)]
    # Existing human feedback remains unresolved until a complete new source and
    # evidence-bound resolution explicitly consume it; never infer resolution.
    pending = feedback.get("decision") in {"revision_requested", "rejected", "needs_revision"}
    confirmation = read(confirmation_path) if confirmation_path else None
    plan = compile_generation_plan(script, assets, view, compiled, brief, review, arrangement,
                                  confirmation=confirmation, revision_feedback_unresolved=pending,
                                  model=model)
    writer = build_emotion_revision_input(script, brief, references, feedback)
    if any(file_sha(p) != h for p, h in before.items()):
        raise ValueError("source changed during preparation")
    evidence = {"schema": "emotion_workflow_preparation/v1", "sources": before,
                "inputs": {str(Path(p).resolve()): file_sha(p) for p in (
                    brief_path, arrangement_path, reference_path, feedback_path)},
                "generation_plan_sha256": digest(plan), "writer_input_sha256": digest(writer),
                "model_calls": 0, "media_calls": 0, "uploads": 0,
                "old_budget_reset": False, "frozen_records_modified": False,
                "creative_quality_passed": False, "sources_unchanged": True,
                "execution_status": "offline_prepared_not_submitted"}
    return plan, writer, evidence


def write_new(path, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n"
           if not isinstance(value, str) else value)
    if path.exists():
        if path.read_text(encoding="utf-8-sig") != raw:
            raise ValueError("output exists with different evidence: " + str(path))
    else:
        with path.open("x", encoding="utf-8", newline="\n") as f:
            f.write(raw)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Prepare complete emotion revision and source-bound video groups; offline only")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--brief", type=Path, required=True)
    parser.add_argument("--arrangement", type=Path, required=True)
    parser.add_argument("--reference-pack", type=Path, required=True)
    parser.add_argument("--feedback", type=Path, required=True)
    parser.add_argument("--story-confirmation", type=Path)
    parser.add_argument("--model", default="doubao-seedance-2-0-mini-260615")
    a = parser.parse_args(argv)
    plan, writer, evidence = prepare_run(a.source, a.brief, a.arrangement, a.reference_pack,
                                         a.feedback, confirmation_path=a.story_confirmation, model=a.model)
    a.output.mkdir(parents=True, exist_ok=True)
    write_new(a.output / "GENERATION_PLAN_OFFLINE.json", plan)
    write_new(a.output / "COMPLETE_REVISION_INPUT_NOT_SUBMITTED.json", writer)
    write_new(a.output / "EVIDENCE.json", evidence)
    prompts = []
    for n, row in enumerate(plan["segments"], 1):
        name = row["segment_id"] + "_PROMPT.txt"
        write_new(a.output / name, row["prompt"] + "\n")
        prompts.append(f"第{n}个生成段，{row['duration_seconds']}秒\n" + row["prompt"])
    write_new(a.output / "ALL_SERVICE_PROMPTS.txt", "\n\n".join(prompts) + "\n")
    print(json.dumps({"output": str(a.output.resolve()), "beats": plan["source_beat_count"],
                      "shots": plan["observation_shot_count"], "generation_segments": plan["generation_segment_count"],
                      "story_blockers": plan["story_blockers"], "model_calls": 0}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

