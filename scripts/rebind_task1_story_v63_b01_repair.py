"""Rebind completed V6.3 progress to the black-jacket b01 plan repair."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / r"data\fanqie_promotion\scene_plans\task1_story_v63_visual_retention_workflow_v1.json"
PROGRESS = ROOT / r"data\qa\task1_story_v63_full_render_20260822_visual_retention_v1\progress.json"
REPAIRED_SCENE = "b01_boast"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def main() -> int:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    progress = json.loads(PROGRESS.read_text(encoding="utf-8"))
    if plan.get("schema_version") != "fanqie_v63_visual_retention_workflow/v1":
        raise ValueError("unexpected V6.3 plan schema")
    if progress.get("schema_version") != "fanqie_v63_render_progress/v1":
        raise ValueError("unexpected V6.3 progress schema")
    branch = plan["variants"]["visual_retention_v1"]
    units = {str(unit["scene_id"]): unit for unit in branch["new_framepack_units"]}
    rows = {str(row["scene_id"]): row for row in progress.get("shots", []) if isinstance(row, dict)}
    if set(rows) != set(units):
        raise ValueError("existing progress does not cover the repaired plan's 19 scenes")
    for scene_id, row in rows.items():
        if scene_id == REPAIRED_SCENE:
            continue
        unit = units[scene_id]
        if row.get("anchor_sha256") != unit.get("anchor_sha256"):
            raise ValueError(f"non-repaired anchor changed: {scene_id}")
        output = Path(str(row.get("output_path") or "")).resolve()
        if not output.is_file() or _sha256(output) != row.get("output_sha256"):
            raise ValueError(f"existing render changed: {scene_id}")

    rows.pop(REPAIRED_SCENE)
    action_partition = set(progress["renderer_partition"]["local_framepack_i2v"])
    action_partition.discard(REPAIRED_SCENE)
    progress["shots"] = [rows[key] for key in sorted(rows)]
    progress["plan_path"] = str(PLAN.resolve())
    progress["plan_sha256"] = _sha256(PLAN)
    progress["renderer_partition"]["local_framepack_i2v"] = sorted(action_partition)
    progress["action_complete"] = False
    progress["success"] = False
    progress["repair_reason"] = "opening male wardrobe changed from blue overshirt to the canonical black textured jacket"
    progress["updated_at"] = datetime.now(timezone.utc).isoformat()
    pending = PROGRESS.with_suffix(".pending.json")
    pending.write_text(json.dumps(progress, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pending.replace(PROGRESS)
    print(json.dumps({
        "plan_sha256": progress["plan_sha256"],
        "retained_scenes": len(rows),
        "rerender_required": REPAIRED_SCENE,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
