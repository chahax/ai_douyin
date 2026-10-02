"""Build the canonical, non-publishable V6.2 hybrid render manifest.

The candidate intentionally uses true local LTX I2V for action-bearing units and
deterministic camera motion for deformation-sensitive inserts.  This collector
does not render or approve anything; it validates the completed files, binds
them to the V6.2 plan and records the renderer provenance per scene.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = ROOT / (
    r"data\fanqie_promotion\scene_plans\task1_story_v62_microshot_workflow.json"
)
DEFAULT_RENDER_DIR = ROOT / (
    r"data\qa\task1_story_v62_microshot_20260821\ltx\original_recomposed"
)

LTX_SCENES = {
    "b01_boast",
    "b02_grab_reaction",
    "b03_object_question",
    "b04_confused_answer",
    "b05_age_burst",
    "b06_pull_away",
    "b07_protest",
    "b11_flip",
    "b12_car_reveal",
    "b16_escape",
    "b18_cta",
}
STABLE_SCENES = {
    "b08_offer_one",
    "b09_offer_two",
    "b10_offer_three",
    "b13_registry_reveal",
    "b14_certificate",
    "b15_terms",
    "b17a_kiss_reaction",
    "b17b_hunt_order",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _write_atomic(path: Path, value: dict[str, object]) -> None:
    pending = path.with_suffix(path.suffix + ".pending")
    pending.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    pending.replace(path)


def _probe(path: Path) -> dict[str, object]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,r_frame_rate:format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode:
        raise RuntimeError(f"ffprobe failed for {path}: {result.stderr[-1000:]}")
    payload = json.loads(result.stdout)
    stream = payload["streams"][0]
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "fps": str(stream["r_frame_rate"]),
        "duration_seconds": round(float(payload["format"]["duration"]), 3),
    }


def _validate_probe(scene_id: str, probe: dict[str, object], minimum: float) -> None:
    if (probe["width"], probe["height"]) != (704, 1248):
        raise ValueError(f"unexpected dimensions for {scene_id}: {probe}")
    if probe["fps"] != "50/1":
        raise ValueError(f"unexpected delivery fps for {scene_id}: {probe}")
    if float(probe["duration_seconds"]) + 0.04 < minimum:
        raise ValueError(
            f"{scene_id} is too short for its micro-shots: "
            f"{probe['duration_seconds']}s < {minimum:.3f}s"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--render-dir", type=Path, default=DEFAULT_RENDER_DIR)
    args = parser.parse_args()

    plan_path = args.plan.resolve()
    render_dir = args.render_dir.resolve()
    plan = _load(plan_path)
    if plan.get("schema_version") != "fanqie_v62_microshot_workflow/v2":
        raise ValueError("unexpected V6.2 workflow schema")
    branch = plan["variants"]["original_recomposed"]
    if branch.get("publish_allowed") is not False:
        raise ValueError("original candidate branch lost its publication guard")

    units = list(branch["new_framepack_units"])
    unit_ids = {str(row["scene_id"]) for row in units}
    if LTX_SCENES & STABLE_SCENES or LTX_SCENES | STABLE_SCENES != unit_ids:
        raise ValueError("hybrid renderer partition does not match plan units")
    positions = {str(row["scene_id"]): i for i, row in enumerate(units, start=1)}
    unit_by_id = {str(row["scene_id"]): row for row in units}

    required_end: dict[str, float] = {scene_id: 0.0 for scene_id in unit_ids}
    for microshot in branch["microshots"]:
        source = str(microshot["source_unit"])
        required_end[source] = max(
            required_end[source],
            float(microshot["source_start_seconds"])
            + float(microshot["duration_seconds"]),
        )

    stable_path = render_dir / "stable_closeup_progress.json"
    stable = _load(stable_path)
    if stable.get("schema_version") != "fanqie_v62_stable_closeup_progress/v1":
        raise ValueError("unexpected stable-closeup manifest schema")
    if stable.get("plan_sha256") != _sha256(plan_path):
        raise ValueError("stable-closeup manifest is not bound to this plan")
    stable_rows = {str(row["scene_id"]): row for row in stable.get("shots", [])}
    if set(stable_rows) != STABLE_SCENES:
        raise ValueError("stable-closeup scene set is incomplete")

    twostage_path = render_dir / "twostage_progress.json"
    twostage = _load(twostage_path)
    if twostage.get("schema_version") != "fanqie_v62_ltx_twostage_progress/v1":
        raise ValueError("unexpected two-stage manifest schema")
    if twostage.get("plan_sha256") != _sha256(plan_path):
        raise ValueError("two-stage manifest is not bound to this plan")
    twostage_rows = {
        str(row["scene_id"]): row for row in twostage.get("shots", [])
    }
    alignment_path = render_dir / "delivery_duration_alignment.json"
    alignment = _load(alignment_path)
    if alignment.get("schema_version") != "fanqie_v62_delivery_duration_alignment/v1":
        raise ValueError("unexpected delivery-duration alignment schema")
    if alignment.get("plan_sha256") != _sha256(plan_path):
        raise ValueError("delivery-duration alignment is not bound to this plan")
    alignment_rows = {
        str(row["scene_id"]): row for row in alignment.get("rows", [])
    }

    shots: list[dict[str, object]] = []
    for scene_id in sorted(unit_ids, key=positions.__getitem__):
        unit = unit_by_id[scene_id]
        output = render_dir / f"{scene_id}.mp4"
        if not output.is_file():
            raise FileNotFoundError(f"render is missing: {output}")
        output_sha = _sha256(output)
        probe = _probe(output)
        _validate_probe(scene_id, probe, required_end[scene_id])

        anchor = Path(str(unit["anchor_path"])).resolve()
        if not anchor.is_file() or _sha256(anchor) != str(unit["anchor_sha256"]).upper():
            raise ValueError(f"anchor changed or is missing: {scene_id}")

        if scene_id in STABLE_SCENES:
            source = stable_rows[scene_id]
            if source.get("output_sha256") != output_sha:
                raise ValueError(f"stable render changed after binding: {scene_id}")
            provider_metadata = {
                "renderer": "deterministic_camera_motion_candidate_only",
                "deformation_sensitive_insert": True,
                "true_i2v": False,
                "source_manifest_path": str(stable_path),
                "source_manifest_sha256": _sha256(stable_path),
                "human_review_required": True,
                "publish_allowed": False,
            }
        else:
            state = twostage_rows.get(scene_id, {})
            aligned_delivery = alignment_rows.get(scene_id)
            state_bound_sha = (
                str(aligned_delivery.get("source_sha256") or "").upper()
                if aligned_delivery else output_sha
            )
            if state.get("output_sha256") not in (None, state_bound_sha):
                raise ValueError(f"two-stage render changed after binding: {scene_id}")
            if scene_id not in {"b01_boast", "b02_grab_reaction", "b04_confused_answer"}:
                if state.get("stage") != "final" or state.get("output_sha256") != state_bound_sha:
                    raise ValueError(f"two-stage LTX scene is not final: {scene_id}")
            if aligned_delivery:
                if str(aligned_delivery.get("output_sha256") or "").upper() != output_sha:
                    raise ValueError(f"delivery alignment output changed: {scene_id}")
                source_path = Path(str(aligned_delivery.get("source_path") or "")).resolve()
                if not source_path.is_file() or _sha256(source_path) != state_bound_sha:
                    raise ValueError(f"delivery alignment source changed: {scene_id}")
            evidence = render_dir / "twostage_audit" / f"{scene_id}.ltx.api.json"
            if not evidence.is_file():
                evidence = render_dir / "audit" / scene_id / "workflow.json"
            if not evidence.is_file():
                raise FileNotFoundError(f"LTX workflow evidence is missing: {scene_id}")
            provider_metadata = {
                "renderer": "local_comfyui_ltx_i2v",
                "true_i2v": True,
                "workflow_evidence_path": str(evidence),
                "workflow_evidence_sha256": _sha256(evidence),
                "raw_ltx_sha256": state.get("raw_sha256"),
                "aligned_sha256": state.get("aligned_sha256"),
                "delivery_duration_alignment": aligned_delivery,
                "delivery_alignment_manifest_path": str(alignment_path),
                "delivery_alignment_manifest_sha256": _sha256(alignment_path),
                "human_review_required": True,
                "publish_allowed": False,
            }

        shots.append(
            {
                "scene_id": scene_id,
                "position": positions[scene_id],
                "status": "rendered",
                "output_path": str(output),
                "output_sha256": output_sha,
                "probe": probe,
                "anchor_path": str(anchor),
                "anchor_sha256": _sha256(anchor),
                "provider_metadata": provider_metadata,
            }
        )

    progress_path = render_dir / "progress.json"
    if progress_path.is_file():
        backup = render_dir / "progress.pre_hybrid.json"
        if not backup.exists():
            shutil.copy2(progress_path, backup)
    now = datetime.now(timezone.utc).isoformat()
    progress = {
        "schema_version": "fanqie_v62_ltx_progress/v1",
        "variant": "original_recomposed",
        "role": branch.get("role"),
        "plan_path": str(plan_path),
        "plan_sha256": _sha256(plan_path),
        "started_at": twostage.get("started_at"),
        "updated_at": now,
        "renderer": "hybrid_ltx_i2v_and_deterministic_stable_closeups",
        "renderer_partition": {
            "local_comfyui_ltx_i2v": sorted(LTX_SCENES, key=positions.__getitem__),
            "deterministic_camera_motion_candidate_only": sorted(
                STABLE_SCENES, key=positions.__getitem__
            ),
        },
        "lip_sync_applied": False,
        "remote_calls": 0,
        "network_downloads": 0,
        "human_review_required": True,
        "publish_allowed": False,
        "fanqie_backfill_allowed": False,
        "shots": shots,
        "success": True,
    }
    _write_atomic(progress_path, progress)
    print(
        json.dumps(
            {
                "status": "HYBRID_PROGRESS_READY",
                "progress_path": str(progress_path),
                "progress_sha256": _sha256(progress_path),
                "ltx_i2v": len(LTX_SCENES),
                "stable_closeups": len(STABLE_SCENES),
                "publish_allowed": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
