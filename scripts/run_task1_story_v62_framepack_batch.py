"""Render one resumable V6.2 FramePack branch through the local Gradio API."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from gradio_client import Client, handle_file


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.content_factory.video_smoothness import analyze_video_smoothness


DEFAULT_PLAN = ROOT / (
    r"data\fanqie_promotion\scene_plans\task1_story_v62_microshot_workflow.json"
)
DEFAULT_ROOT = ROOT / r"data\qa\task1_story_v62_microshot_20260821\framepack"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _write_atomic(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def _video_candidates(value: object) -> list[Path]:
    """Collect media paths from final or intermediate Gradio generator payloads."""

    candidates: list[Path] = []
    if isinstance(value, (str, Path)):
        path = Path(str(value))
        if path.suffix.lower() in {".mp4", ".mov", ".webm", ".mkv"}:
            candidates.append(path)
        return candidates
    if isinstance(value, dict):
        preferred = ("video", "path", "name", "value")
        for key in preferred:
            if key in value:
                candidates.extend(_video_candidates(value[key]))
        for key, nested in value.items():
            if key not in preferred:
                candidates.extend(_video_candidates(nested))
        return candidates
    if isinstance(value, (tuple, list)):
        for nested in value:
            candidates.extend(_video_candidates(nested))
        return candidates
    path = getattr(value, "path", None)
    if path:
        candidates.extend(_video_candidates(path))
    return candidates


def _video_path(*payloads: object) -> Path:
    candidates: list[Path] = []
    for payload in payloads:
        candidates.extend(_video_candidates(payload))
    existing = [path for path in candidates if path.is_file() and path.stat().st_size]
    if existing:
        return existing[-1]
    raise RuntimeError(
        "FramePack completed without a usable video payload; "
        f"candidate paths were {[str(path) for path in candidates]}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--variant",
        choices=("original_recomposed", "direct_reference_i2v"),
        required=True,
    )
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--base-url", default="http://127.0.0.1:7861")
    parser.add_argument("--scene-id", action="append", default=[])
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    plan_path = args.plan.resolve()
    value = json.loads(plan_path.read_text(encoding="utf-8"))
    if value.get("schema_version") != "fanqie_v62_microshot_workflow/v2":
        raise ValueError("unexpected micro-shot plan schema")
    variant = value["variants"][args.variant]
    if variant.get("publish_allowed") is not False:
        raise ValueError("render plan must keep publish_allowed=false")
    all_units = list(variant.get("new_framepack_units") or [])
    unit_positions = {
        str(item.get("scene_id")): index
        for index, item in enumerate(all_units, start=1)
    }
    units = all_units
    if args.scene_id:
        requested = set(args.scene_id)
        known = {str(item.get("scene_id")) for item in units}
        unknown = sorted(requested - known)
        if unknown:
            raise ValueError(f"unknown scene ids: {', '.join(unknown)}")
        units = [item for item in units if item.get("scene_id") in requested]

    output_dir = args.output_root.resolve() / args.variant
    output_dir.mkdir(parents=True, exist_ok=True)
    progress_path = output_dir / "progress.json"
    progress: dict[str, object] = {
        "schema_version": "fanqie_v62_framepack_progress/v2",
        "variant": args.variant,
        "role": variant.get("role"),
        "plan_path": str(plan_path),
        "plan_sha256": _sha256(plan_path),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "server": args.base_url,
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

    client = Client(args.base_url)
    previous = {
        str(item.get("scene_id")): item
        for item in progress.get("shots", [])
        if isinstance(item, dict)
    }
    rows: list[dict[str, object]] = []
    failures = 0
    for unit in units:
        scene_id = str(unit["scene_id"])
        position = unit_positions[scene_id]
        destination = output_dir / f"{position:03d}_{scene_id}.mp4"
        cached = previous.get(scene_id)
        if (
            not args.force
            and cached
            and cached.get("status") == "rendered"
            and destination.is_file()
            and cached.get("output_sha256") == _sha256(destination)
        ):
            rows.append(cached)
            print(json.dumps({"event": "cache_hit", "scene_id": scene_id}))
            continue

        anchor = Path(str(unit["anchor_path"])).resolve()
        if not anchor.is_file() or _sha256(anchor) != unit.get("anchor_sha256"):
            raise ValueError(f"anchor missing or changed: {scene_id}")
        print(
            json.dumps(
                {
                    "event": "render_started",
                    "variant": args.variant,
                    "scene_id": scene_id,
                    "position": position,
                    "total": len(units),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        row: dict[str, object] = {
            "scene_id": scene_id,
            "anchor_path": str(anchor),
            "anchor_sha256": unit["anchor_sha256"],
            "seed": int(unit["seed"]),
            "target_duration_seconds": float(unit["target_duration_seconds"]),
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            job = client.submit(
                input_image=handle_file(str(anchor)),
                prompt=str(unit["prompt"]),
                n_prompt=str(unit.get("negative_prompt") or ""),
                seed=float(unit["seed"]),
                total_second_length=float(unit["target_duration_seconds"]),
                latent_window_size=9.0,
                steps=25.0,
                cfg=1.0,
                gs=10.0,
                rs=0.0,
                gpu_memory_preservation=6.0,
                use_teacache=True,
                api_name="/process",
            )
            final_result = job.result()
            generated = _video_path(job.outputs(), final_result)
            if not generated.is_file() or generated.stat().st_size <= 0:
                raise RuntimeError(f"FramePack result does not exist: {generated}")
            temporary = destination.with_suffix(".pending.mp4")
            shutil.copy2(generated, temporary)
            temporary.replace(destination)
            metrics = analyze_video_smoothness(
                destination,
                analysis_fps=30.0,
                analysis_width=160,
                duplicate_threshold=0.12,
            )
            row.update(
                {
                    "status": "rendered",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "output_path": str(destination),
                    "output_sha256": _sha256(destination),
                    "metrics": metrics,
                }
            )
        except Exception as exc:  # preserve a resumable per-shot audit
            failures += 1
            row.update(
                {
                    "status": "failed",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "error": str(exc),
                }
            )
        rows.append(row)
        progress["shots"] = rows
        progress["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_atomic(progress_path, progress)
        print(
            json.dumps(
                {
                    "event": "render_finished",
                    "scene_id": scene_id,
                    "status": row["status"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    progress["shots"] = rows
    progress["finished_at"] = datetime.now(timezone.utc).isoformat()
    progress["updated_at"] = progress["finished_at"]
    progress["success"] = failures == 0 and len(rows) == len(units)
    _write_atomic(progress_path, progress)
    print(json.dumps(progress, ensure_ascii=False, indent=2), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
