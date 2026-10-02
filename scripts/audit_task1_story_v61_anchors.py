"""Fail-closed audit for the task-1 V6.1 reviewed shot-anchor plan.

This script verifies the production P0 parser, every declared anchor hash, and
the review contact sheet.  Its output is evidence for *video smoke generation
only*; it never grants human review or publishing approval.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


EXPECTED_BEAT_IDS = [
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
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--plan",
        type=Path,
        default=repo_root
        / "data/fanqie_promotion/scene_plans/task1_story_v61_reviewed_anchors.json",
    )
    parser.add_argument(
        "--contact-sheet",
        type=Path,
        default=repo_root / "data/qa/task1_story_v61_anchor_contact.jpg",
    )
    parser.add_argument(
        "--p0-root",
        type=Path,
        default=repo_root.parent / "ai_douyin_p0",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=repo_root / "data/qa/task1_story_v61_anchor_review.json",
    )
    args = parser.parse_args()

    errors: list[str] = []
    if not args.plan.is_file():
        errors.append(f"plan_not_found:{args.plan}")
    if not args.contact_sheet.is_file():
        errors.append(f"contact_sheet_not_found:{args.contact_sheet}")
    if not args.p0_root.is_dir():
        errors.append(f"p0_root_not_found:{args.p0_root}")
    if errors:
        raise SystemExit("; ".join(errors))

    data = json.loads(args.plan.read_text(encoding="utf-8"))
    beats = data.get("beats")
    if not isinstance(beats, list):
        raise SystemExit("plan beats must be a list")

    actual_ids = [str(beat.get("id", "")) for beat in beats]
    if actual_ids != EXPECTED_BEAT_IDS:
        errors.append("beat_ids_or_order_mismatch")
    if data.get("publish_allowed") is not False:
        errors.append("plan_publish_allowed_must_be_false")
    if data.get("status") != "reviewed_anchor_smoke_ready":
        errors.append("plan_status_must_be_reviewed_anchor_smoke_ready")

    anchor_records: list[dict[str, object]] = []
    seen_paths: set[str] = set()
    for beat in beats:
        beat_id = str(beat.get("id", ""))
        if beat.get("anchor_review_status") != "approved_for_video_smoke":
            errors.append(f"{beat_id}:anchor_not_approved_for_video_smoke")
        raw_path = str(beat.get("shot_anchor_image", "")).strip()
        expected_sha = str(beat.get("shot_anchor_sha256", "")).strip().upper()
        anchor_path = Path(raw_path)
        exists = anchor_path.is_file()
        actual_sha = sha256_file(anchor_path) if exists else ""
        sha_matches = bool(expected_sha) and actual_sha == expected_sha
        if not raw_path:
            errors.append(f"{beat_id}:missing_anchor_path")
        elif raw_path in seen_paths:
            errors.append(f"{beat_id}:duplicate_anchor_path")
        else:
            seen_paths.add(raw_path)
        if not exists:
            errors.append(f"{beat_id}:anchor_not_found")
        elif not sha_matches:
            errors.append(f"{beat_id}:anchor_sha_mismatch")
        anchor_records.append(
            {
                "beat_id": beat_id,
                "path": raw_path,
                "declared_sha256": expected_sha,
                "actual_sha256": actual_sha,
                "exists": exists,
                "sha256_matches": sha_matches,
                "review_scope": "codex_visual_precheck_for_video_smoke",
            }
        )

    sys.path.insert(0, str(args.p0_root))
    try:
        from src.novel_promotion.live_action_flow import load_performance_story_plan
        from src.novel_promotion.video_generation_service import (
            _load_structured_scene_plan,
        )

        validated_plan = load_performance_story_plan(str(args.plan))
        scene_plans = _load_structured_scene_plan(str(args.plan), "")
        parser_result = {
            "valid": validated_plan.is_valid,
            "errors": list(validated_plan.all_errors),
            "beat_count": len(validated_plan.beats),
            "scene_plan_count": len(scene_plans),
            "estimated_total_seconds": validated_plan.estimated_total_seconds,
            "all_motion_prompts_ascii": all(
                scene.visual_prompt.isascii() for scene in scene_plans
            ),
        }
        if not validated_plan.is_valid:
            errors.extend(f"p0_parser:{item}" for item in validated_plan.all_errors)
        if len(scene_plans) != len(EXPECTED_BEAT_IDS):
            errors.append("p0_scene_plan_count_mismatch")
        if not parser_result["all_motion_prompts_ascii"]:
            errors.append("non_ascii_motion_prompt")
    except Exception as exc:  # fail closed and preserve the exact parser failure
        parser_result = {"valid": False, "exception": repr(exc)}
        errors.append(f"p0_parser_exception:{exc!r}")

    passed = not errors
    report = {
        "schema_version": "fanqie_v61_anchor_review/v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "task_id": 1,
        "promotion_alias": data.get("promotion_alias", ""),
        "result": "approved_for_video_smoke" if passed else "rejected",
        "passed": passed,
        "errors": errors,
        "plan": {
            "path": str(args.plan.resolve()),
            "sha256": sha256_file(args.plan),
            "schema_version": data.get("schema_version", ""),
            "plan_revision": data.get("plan_revision", ""),
            "beat_count": len(beats),
            "estimated_total_seconds": data.get("estimated_total_seconds"),
        },
        "p0_parser_validation": parser_result,
        "contact_sheet": {
            "path": str(args.contact_sheet.resolve()),
            "sha256": sha256_file(args.contact_sheet),
        },
        "anchors": anchor_records,
        "gates": {
            "video_smoke_allowed": passed,
            "full_video_human_review_required": True,
            "human_video_approval_obtained": False,
            "matching_fanqie_task_required": True,
            "matching_fanqie_task_confirmed": False,
            "douyin_upload_allowed": False,
            "fanqie_backfill_allowed": False,
        },
        "notes": [
            "This report approves image anchors only for failed-scene video smoke generation.",
            "It is not human approval of a completed video and must not be used to publish.",
            "No Douyin upload or Fanqie backfill was performed by this audit.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
