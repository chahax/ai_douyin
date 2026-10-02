"""Render a resumable V6.2 branch with the local ComfyUI LTX provider.

This is a motion-source render only.  It deliberately disables per-shot
lip-sync and publication; the approved V6.1 audio is muxed only after the
micro-shot edit is complete.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = ROOT / (
    r"data\fanqie_promotion\scene_plans\task1_story_v62_microshot_workflow.json"
)
DEFAULT_OUTPUT = ROOT / r"data\qa\task1_story_v62_microshot_20260821\ltx"
DEFAULT_EVIDENCE = ROOT / (
    r"data\fanqie_promotion\evidence\task1_story_v62_microshot_20260822"
)
DEFAULT_P0_ROOT = ROOT.parent / "ai_douyin_p0"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def _probe(path: Path) -> dict[str, object]:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,avg_frame_rate:format=duration",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError(f"ffprobe failed: {result.stderr[-1000:]}")
    value = json.loads(result.stdout)
    stream = value["streams"][0]
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "fps": stream["avg_frame_rate"],
        "duration_seconds": float(value["format"]["duration"]),
    }


def _character_bindings(source_plan: dict[str, object]) -> dict[str, dict[str, object]]:
    raw_cast = source_plan.get("cast", {})
    if isinstance(raw_cast, dict):
        cast = {
            str(character_id): item
            for character_id, item in raw_cast.items()
            if isinstance(item, dict)
        }
    else:
        cast = {
            str(item["id"]): item
            for item in raw_cast
            if isinstance(item, dict) and item.get("id")
        }
    bindings: dict[str, dict[str, object]] = {}
    for beat in source_plan.get("beats", []):
        if not isinstance(beat, dict):
            continue
        scene_id = str(beat.get("id") or "")
        character_ids = [str(value) for value in beat.get("character_ids", [])]
        paths = {
            cid: str(cast[cid]["master_image"])
            for cid in character_ids
            if cid in cast
        }
        hashes = {
            cid: str(cast[cid]["master_sha256"])
            for cid in character_ids
            if cid in cast
        }
        bindings[scene_id] = {
            "character_ids": character_ids,
            "master_image_paths": paths,
            "master_image_sha256s": hashes,
        }
    return bindings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--variant",
        choices=("original_recomposed", "direct_reference_i2v"),
        required=True,
    )
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--p0-root", type=Path, default=DEFAULT_P0_ROOT)
    parser.add_argument("--base-url", default="http://127.0.0.1:8190")
    parser.add_argument("--scene-id", action="append", default=[])
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    p0_root = args.p0_root.resolve()
    if not (p0_root / "src/novel_promotion/comfy_ltx_video_provider.py").is_file():
        raise FileNotFoundError(f"P0 provider root is unavailable: {p0_root}")
    sys.path.insert(0, str(p0_root))
    from src.novel_promotion.comfy_ltx_video_provider import (  # noqa: PLC0415
        ComfyLTXVideoSceneProvider,
    )
    from src.novel_promotion.scene_provider import ScenePlan  # noqa: PLC0415

    plan_path = args.plan.resolve()
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "fanqie_v62_microshot_workflow/v2":
        raise ValueError("unexpected V6.2 workflow schema")
    branch = payload["variants"][args.variant]
    if branch.get("publish_allowed") is not False:
        raise ValueError("render branch must remain non-publishable")
    if branch.get("reuse_sources"):
        raise ValueError("V6.2 LTX render refuses legacy source reuse")

    units = list(branch.get("new_framepack_units") or [])
    all_positions = {
        str(unit["scene_id"]): index for index, unit in enumerate(units, start=1)
    }
    if args.scene_id:
        requested = set(args.scene_id)
        unknown = requested - set(all_positions)
        if unknown:
            raise ValueError(f"unknown scene ids: {', '.join(sorted(unknown))}")
        units = [unit for unit in units if unit["scene_id"] in requested]

    source_plan_path = Path(str(payload["source_story_plan"]))
    if _sha256(source_plan_path) != payload["source_story_plan_sha256"]:
        raise ValueError("source story plan changed")
    source_plan = json.loads(source_plan_path.read_text(encoding="utf-8"))
    bindings = _character_bindings(source_plan)

    plans = []
    for unit in units:
        scene_id = str(unit["scene_id"])
        anchor = Path(str(unit["anchor_path"]))
        if not anchor.is_file() or _sha256(anchor) != unit["anchor_sha256"]:
            raise ValueError(f"anchor missing or changed: {scene_id}")
        identity = bindings.get(scene_id, {}) if args.variant == "original_recomposed" else {}
        plans.append(
            ScenePlan(
                scene_id=scene_id,
                description="V6.2 local LTX motion-source render",
                visual_prompt=str(unit["prompt"]),
                estimated_duration_s=float(unit["target_duration_seconds"]),
                metadata={
                    **identity,
                    "seed": int(unit["seed"]),
                    "shot_anchor_image": str(anchor.resolve()),
                    "shot_anchor_sha256": str(unit["anchor_sha256"]),
                    "spoken_closeup": False,
                    "dialogue_audio_path": "",
                    "publish_allowed": False,
                },
            )
        )

    output_dir = args.output_root.resolve() / args.variant
    output_dir.mkdir(parents=True, exist_ok=True)
    progress_path = output_dir / "progress.json"
    progress: dict[str, object] = {
        "schema_version": "fanqie_v62_ltx_progress/v1",
        "variant": args.variant,
        "role": branch.get("role"),
        "plan_path": str(plan_path),
        "plan_sha256": _sha256(plan_path),
        "started_at": _utc_now(),
        "updated_at": _utc_now(),
        "base_url": args.base_url,
        "renderer": "local_comfyui_ltx_i2v",
        "lip_sync_applied": False,
        "remote_calls": 0,
        "network_downloads": 0,
        "publish_allowed": False,
        "fanqie_backfill_allowed": False,
        "shots": [],
    }
    if progress_path.is_file():
        prior = json.loads(progress_path.read_text(encoding="utf-8"))
        if (
            prior.get("schema_version") == progress["schema_version"]
            and prior.get("variant") == args.variant
            and prior.get("plan_sha256") == progress["plan_sha256"]
        ):
            progress["started_at"] = prior.get("started_at")
            progress["shots"] = list(prior.get("shots") or [])

    provider = ComfyLTXVideoSceneProvider(
        base_url=args.base_url,
        comfy_input=r"D:\IT\AI_vido\ComfyUI\input",
        comfy_output=r"D:\IT\AI_vido\ComfyUI\output",
        evidence_root=str(args.evidence_root.resolve()),
        timeout_seconds=7200,
        musetalk_available=False,
    )
    preflight = provider.preflight(plans, require_dialogue_audio=False)
    progress["preflight"] = {
        "ok": preflight.ok,
        "status": preflight.status,
        "error": preflight.error,
        "details": preflight.details,
    }
    _write_atomic(progress_path, progress)
    if not preflight.ok:
        raise RuntimeError(f"LTX preflight failed: {preflight.error}")

    previous = {
        str(row.get("scene_id")): row
        for row in progress.get("shots", [])
        if isinstance(row, dict)
    }
    rows: list[dict[str, object]] = []
    failures = 0
    for scene_plan in plans:
        scene_id = scene_plan.scene_id
        destination = output_dir / f"{scene_id}.mp4"
        cached = previous.get(scene_id)
        if (
            not args.force
            and cached
            and cached.get("status") == "rendered"
            and destination.is_file()
            and cached.get("output_sha256") == _sha256(destination)
        ):
            rows.append(cached)
            print(json.dumps({"event": "cache_hit", "scene_id": scene_id}), flush=True)
            continue

        print(
            json.dumps(
                {
                    "event": "render_started",
                    "scene_id": scene_id,
                    "position": all_positions[scene_id],
                    "total": len(all_positions),
                }
            ),
            flush=True,
        )
        row: dict[str, object] = {
            "scene_id": scene_id,
            "position": all_positions[scene_id],
            "started_at": _utc_now(),
        }
        result = provider.provide_scenes([scene_plan], output_dir)
        if result.missing or len(result.assets) != 1:
            failures += 1
            row.update(
                {
                    "status": "failed",
                    "completed_at": _utc_now(),
                    "errors": [item.reason for item in result.missing],
                }
            )
        else:
            asset_path = Path(result.assets[0].video_path)
            if asset_path.resolve() != destination.resolve() or not destination.is_file():
                raise RuntimeError(f"unexpected provider output for {scene_id}: {asset_path}")
            row.update(
                {
                    "status": "rendered",
                    "completed_at": _utc_now(),
                    "output_path": str(destination),
                    "output_sha256": _sha256(destination),
                    "probe": _probe(destination),
                    "provider_metadata": result.assets[0].metadata,
                }
            )
        rows.append(row)
        progress["shots"] = rows
        progress["updated_at"] = _utc_now()
        _write_atomic(progress_path, progress)
        print(
            json.dumps(
                {"event": "render_finished", "scene_id": scene_id, "status": row["status"]}
            ),
            flush=True,
        )

    progress["shots"] = rows
    progress["finished_at"] = _utc_now()
    progress["updated_at"] = progress["finished_at"]
    progress["success"] = failures == 0 and len(rows) == len(plans)
    _write_atomic(progress_path, progress)
    print(json.dumps(progress, ensure_ascii=False, indent=2), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
