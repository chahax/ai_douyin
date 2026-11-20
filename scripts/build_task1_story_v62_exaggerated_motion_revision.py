"""Create a V6.2.1 plan revision that fixes the frozen opening walk."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / r"data\fanqie_promotion\scene_plans\task1_story_v62_microshot_workflow.json"
OUTPUT = ROOT / r"data\fanqie_promotion\scene_plans\task1_story_v62_microshot_workflow_exaggerated_motion_v1.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def main() -> int:
    payload = json.loads(BASE.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "fanqie_v62_microshot_workflow/v2":
        raise ValueError("unexpected base plan schema")
    base_sha = _sha256(BASE)
    branch = payload["variants"]["original_recomposed"]
    unit = next(row for row in branch["new_framepack_units"] if row["scene_id"] == "b01_boast")
    unit["seed"] = 86220117
    unit["prompt"] = (
        "Full-body motion is mandatory and must remain visible. The adult male performs "
        "two large, confident, slightly comedic swaggering steps toward camera: first the "
        "front white sneaker plants clearly about forty centimetres ahead while the rear heel "
        "lifts, then the rear leg swings through with a visibly bent knee and plants ahead. "
        "His hips and torso translate forward, shoulders bounce once, opposite arms swing "
        "widely, and he finishes pocketing the phone with a smug eyebrow raise. Use a mostly "
        "locked full-body camera with only a very small push-in; do not track with his body, "
        "do not freeze either leg, and do not keep the opening crossed-leg pose. Preserve his "
        "exact face, blue overshirt, white T-shirt, dark jeans, white sneakers, glossy blue-hour "
        "campus and teal-orange neon lighting."
    )
    unit["negative_prompt"] = (
        str(unit["negative_prompt"])
        + ", frozen legs, static crossed-leg pose, sliding feet, moonwalk, foot skating, "
        "locked knees, camera tracking that cancels body translation, tiny restrained motion"
    )
    unit["motion_revision"] = {
        "profile": "exaggerated_full_body_two_step_v1",
        "reason": "opening 1-3 seconds showed upper-body-only motion and frozen legs",
        "required_visible_actions": [
            "front_foot_plant", "rear_heel_lift", "rear_leg_swing_through",
            "second_foot_plant", "hip_translation", "opposite_arm_swing",
        ],
        "camera": "mostly_locked_full_body_small_push_in",
    }
    replacements = {
        "m01": (0.0, 0.8, "lower_detail"),
        "m02": (0.8, 1.4, "full"),
        "m03": (2.2, 0.6, "upper_close"),
    }
    for shot in branch["microshots"]:
        if shot["shot_id"] in replacements:
            start, duration, crop = replacements[shot["shot_id"]]
            shot["source_start_seconds"] = start
            shot["duration_seconds"] = duration
            shot["crop"] = crop
    payload["revision"] = {
        "schema_version": "fanqie_v62_motion_revision/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "parent_plan_path": str(BASE.resolve()),
        "parent_plan_sha256": base_sha,
        "changed_scene_ids": ["b01_boast"],
        "changed_microshot_ids": ["m01", "m02", "m03"],
        "story_audio_subtitles_and_publication_boundary_unchanged": True,
        "publish_allowed": False,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "sha256": _sha256(OUTPUT), "parent_sha256": base_sha}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
