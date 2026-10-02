from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


P0_ROOT = Path(r"D:\IT\ai_douyin_p0")
if str(P0_ROOT) not in sys.path:
    sys.path.insert(0, str(P0_ROOT))

from src.novel_promotion.comfy_ltx_video_provider import (  # noqa: E402
    ComfyLTXVideoSceneProvider,
)
from src.novel_promotion.live_action_flow import load_live_action_flow  # noqa: E402


DEFAULT_MANIFEST = Path(
    r"D:\IT\ai_douyin\data\fanqie_promotion\scene_plans\task1_story_v5_live_action_flow_ready.json"
)
DEFAULT_OUTPUT = Path(
    r"D:\IT\ai_douyin\data\fanqie_promotion\renders\task1_story_v5_full"
)
DEFAULT_EVIDENCE = Path(
    r"D:\IT\ai_douyin\data\fanqie_promotion\evidence\task1_story_v5"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _jsonable(value):
    if hasattr(value, "__dict__"):
        return {key: _jsonable(item) for key, item in value.__dict__.items()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


def _write_progress(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate the audited Fanqie task-1 live-action v5 shot set."
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--comfy-base-url", default="http://127.0.0.1:8190")
    parser.add_argument(
        "--shot-id",
        action="append",
        default=[],
        help="Generate only this scene id; may be repeated.",
    )
    parser.add_argument(
        "--progress-path",
        type=Path,
        default=None,
        help="Progress JSON path; defaults to <output-dir>/batch_progress.json.",
    )
    args = parser.parse_args()

    manifest = args.manifest.resolve()
    output_dir = args.output_dir.resolve()
    progress_path = (
        args.progress_path.resolve()
        if args.progress_path is not None
        else output_dir / "batch_progress.json"
    )
    flow = load_live_action_flow(manifest)
    masters = {character.id: character.master_image for character in flow.characters}
    plans = flow.to_scene_plans()
    if args.shot_id:
        requested = set(args.shot_id)
        known = {plan.scene_id for plan in plans}
        unknown = sorted(requested - known)
        if unknown:
            raise ValueError(f"Unknown --shot-id values: {', '.join(unknown)}")
        plans = [plan for plan in plans if plan.scene_id in requested]
    for plan in plans:
        plan.metadata["master_image_paths"] = masters

    provider = ComfyLTXVideoSceneProvider(
        base_url=args.comfy_base_url,
        comfy_input=r"D:\IT\AI_vido\ComfyUI\input",
        comfy_output=r"D:\IT\AI_vido\ComfyUI\output",
        evidence_root=str(args.evidence_root.resolve()),
        timeout_seconds=7200,
        musetalk_available=True,
        musetalk_executable=(
            r"D:\IT\ai_douyin\scripts\run_musetalk_fixed_audio.py"
        ),
        musetalk_root=r"D:\IT\MuseTalk",
        musetalk_model_dir=r"D:\IT\MuseTalk\models\musetalkV15",
        musetalk_whisper_dir=r"D:\IT\MuseTalk\models\whisper",
        musetalk_python=r"D:\IT\ai_douyin\.venv\Scripts\python.exe",
    )
    provider.set_master_images(masters)
    preflight = provider.preflight(plans)

    progress = {
        "schema_version": "fanqie_ltx_batch_progress/v1",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "manifest_path": str(manifest),
        "manifest_sha256": _sha256(manifest),
        "output_dir": str(output_dir),
        "publish_allowed": False,
        "requested_shot_ids": [plan.scene_id for plan in plans],
        "preflight": _jsonable(preflight),
        "shots": [],
    }
    _write_progress(progress_path, progress)
    if not preflight.ok:
        print(json.dumps(progress, ensure_ascii=False, indent=2), flush=True)
        return 2

    had_failure = False
    for position, plan in enumerate(plans, start=1):
        print(
            json.dumps(
                {
                    "event": "shot_started",
                    "position": position,
                    "total": len(plans),
                    "scene_id": plan.scene_id,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        result = provider.provide_scenes([plan], output_dir)
        shot_result = {
            "scene_id": plan.scene_id,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "assets": _jsonable(result.assets),
            "missing": _jsonable(result.missing),
        }
        progress["shots"].append(shot_result)
        progress["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_progress(progress_path, progress)
        if result.missing:
            had_failure = True
        print(
            json.dumps(
                {
                    "event": "shot_finished",
                    "scene_id": plan.scene_id,
                    "success": bool(result.assets) and not result.missing,
                    "asset_count": len(result.assets),
                    "missing_count": len(result.missing),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    progress["finished_at"] = datetime.now(timezone.utc).isoformat()
    progress["success"] = not had_failure and len(progress["shots"]) == len(plans)
    progress["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write_progress(progress_path, progress)
    print(json.dumps(progress, ensure_ascii=False, indent=2), flush=True)
    return 1 if had_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
