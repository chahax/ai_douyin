from __future__ import annotations

"""Build a fail-closed, smoke-only execution packet for task-1 V6.1.

The packet performs read-only static/runtime checks and writes one JSON report.
It never invokes TTS/GPU generation, creates render/audio/evidence directories,
opens a browser, writes the closed-loop database, uploads, or backfills.
"""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(r"D:\IT\ai_douyin")
P0_PROVIDER_SOURCE = Path(
    r"D:\IT\ai_douyin_p0\src\novel_promotion\comfy_ltx_video_provider.py"
)
EXPECTED_READ_ONLY_PREFLIGHT_PROVIDER_SHA256 = (
    "3D2D8ECA86683F58EC0C04A43484EBE3DDD396C89EB805414FF0BA5C2A819B80"
)
SMOKE_RUNNER_SOURCE = PROJECT_ROOT / "scripts/run_task1_story_v61_failed_smoke.py"
EXPECTED_SMOKE_RUNNER_SHA256 = (
    "78963646BDE4DEF9807D20457A5174BBB320CE1AFD007B76863256D02C3FCCC3"
)


def _source_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _assert_reviewed_read_only_preflight_source() -> dict[str, Any]:
    if not P0_PROVIDER_SOURCE.is_file():
        raise RuntimeError(f"reviewed preflight provider is missing: {P0_PROVIDER_SOURCE}")
    actual = _source_sha256(P0_PROVIDER_SOURCE)
    if actual != EXPECTED_READ_ONLY_PREFLIGHT_PROVIDER_SHA256:
        raise RuntimeError(
            "refusing to import or call unreviewed ComfyUI preflight provider: "
            f"expected {EXPECTED_READ_ONLY_PREFLIGHT_PROVIDER_SHA256}, got {actual}"
        )
    return {
        "path": str(P0_PROVIDER_SOURCE),
        "sha256": actual,
        "reviewed_read_only_contract": True,
        "allowed_http_methods": ["GET"],
        "allowed_endpoints": ["/system_stats", "/object_info"],
        "forbidden_endpoints": ["/prompt", "/queue", "/interrupt"],
    }


def _assert_reviewed_smoke_runner_source() -> dict[str, Any]:
    if not SMOKE_RUNNER_SOURCE.is_file():
        raise RuntimeError(f"reviewed smoke runner is missing: {SMOKE_RUNNER_SOURCE}")
    actual = _source_sha256(SMOKE_RUNNER_SOURCE)
    if actual != EXPECTED_SMOKE_RUNNER_SHA256:
        raise RuntimeError(
            "refusing to emit a command for an unreviewed smoke runner: "
            f"expected {EXPECTED_SMOKE_RUNNER_SHA256}, got {actual}"
        )
    return {"path": str(SMOKE_RUNNER_SOURCE), "sha256": actual, "reviewed": True}


# Fail before importing the runner/provider when the reviewed implementation
# changes. A new source hash requires fresh tests and Claude Code review.
_IMPORTED_PREFLIGHT_CONTRACT = _assert_reviewed_read_only_preflight_source()
_IMPORTED_SMOKE_RUNNER_CONTRACT = _assert_reviewed_smoke_runner_source()
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import run_task1_story_v61_failed_smoke as smoke  # noqa: E402


SCHEMA = "fanqie_v61_smoke_window_packet/v1"
DEFAULT_OUTPUT = PROJECT_ROOT / "data/qa/task1_story_v61_window_packet.json"
RUN_ID_PATTERN = re.compile(r"[0-9]{8}_[0-9]{6}")
MINIMUM_GPU_FREE_MIB = 8 * 1024
MAXIMUM_GPU_UTILIZATION_PERCENT = 80


def _gpu_readiness() -> dict[str, Any]:
    """Fail closed when the renderer would contend with another GPU workload."""
    command = [
        "nvidia-smi",
        "--query-gpu=index,name,memory.total,memory.free,utilization.gpu,temperature.gpu",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(
            command, check=True, capture_output=True, text=True,
            timeout=10, shell=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "ready": False,
            "error": f"GPU telemetry unavailable: {exc}",
            "minimum_free_mib": MINIMUM_GPU_FREE_MIB,
            "maximum_utilization_percent": MAXIMUM_GPU_UTILIZATION_PERCENT,
            "devices": [],
        }
    devices: list[dict[str, Any]] = []
    try:
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            values = [part.strip() for part in line.split(",")]
            if len(values) != 6:
                raise ValueError(f"unexpected nvidia-smi row: {line}")
            index, name, total, free, utilization, temperature = values
            devices.append({
                "index": int(index),
                "name": name,
                "memory_total_mib": int(total),
                "memory_free_mib": int(free),
                "utilization_percent": int(utilization),
                "temperature_c": int(temperature),
            })
    except ValueError as exc:
        return {
            "ready": False,
            "error": f"GPU telemetry invalid: {exc}",
            "minimum_free_mib": MINIMUM_GPU_FREE_MIB,
            "maximum_utilization_percent": MAXIMUM_GPU_UTILIZATION_PERCENT,
            "devices": [],
        }
    if len(devices) != 1:
        return {
            "ready": False,
            "error": f"expected exactly one rendering GPU, found {len(devices)}",
            "minimum_free_mib": MINIMUM_GPU_FREE_MIB,
            "maximum_utilization_percent": MAXIMUM_GPU_UTILIZATION_PERCENT,
            "devices": devices,
        }
    device = devices[0]
    ready = (
        device["memory_free_mib"] >= MINIMUM_GPU_FREE_MIB
        and device["utilization_percent"] <= MAXIMUM_GPU_UTILIZATION_PERCENT
    )
    reasons = []
    if device["memory_free_mib"] < MINIMUM_GPU_FREE_MIB:
        reasons.append("insufficient free GPU memory")
    if device["utilization_percent"] > MAXIMUM_GPU_UTILIZATION_PERCENT:
        reasons.append("GPU is already busy")
    return {
        "ready": ready,
        "error": "; ".join(reasons),
        "minimum_free_mib": MINIMUM_GPU_FREE_MIB,
        "maximum_utilization_percent": MAXIMUM_GPU_UTILIZATION_PERCENT,
        "devices": devices,
    }


def _jsonable(value: Any) -> Any:
    return smoke._jsonable(value)


def _paths(run_id: str) -> dict[str, Path]:
    return {
        "progress": PROJECT_ROOT / f"data/qa/task1_story_v61_failed_smoke_progress_{run_id}.json",
        "render": PROJECT_ROOT / f"data/fanqie_promotion/renders/task1_story_v61_failed_smoke_{run_id}",
        "audio": PROJECT_ROOT / f"data/fanqie_promotion/audio/task1_story_v61_failed_smoke_{run_id}",
        "evidence": PROJECT_ROOT / f"data/fanqie_promotion/evidence/task1_story_v61_{run_id}",
        "review_packet": PROJECT_ROOT / f"data/qa/task1_story_v61_smoke_review_packet_{run_id}",
        "review": PROJECT_ROOT / f"data/qa/task1_story_v61_failed_smoke_review_{run_id}.json",
        "certificate": PROJECT_ROOT / f"data/qa/task1_story_v61_smoke_review_certificate_{run_id}.json",
    }


def prepare(
    *, run_id: str, now: datetime | None = None,
    comfy_base_url: str = "http://127.0.0.1:8190",
) -> dict[str, Any]:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("run_id must use YYYYMMDD_HHMMSS")
    provider_contract = _assert_reviewed_read_only_preflight_source()
    runner_contract = _assert_reviewed_smoke_runner_source()
    observed = now or datetime.now(timezone.utc)
    window = smoke._execution_window(observed)
    all_plans = smoke._load_structured_scene_plan(str(smoke.PLAN_PATH), "")
    selected = smoke._select_plans(all_plans, [])
    static = smoke._validate_static(
        plan_path=smoke.PLAN_PATH, all_plans=all_plans, selected_plans=selected,
    )
    provider = smoke._provider(comfy_base_url, smoke.DEFAULT_EVIDENCE)
    runtime = provider.preflight(selected, require_dialogue_audio=False)
    runtime_json = _jsonable(runtime)
    runtime_json["dialogue_audio_deferred"] = True
    runtime_json["dialogue_audio_preflight_stage"] = (
        "the smoke runner repeats runtime preflight with generated dialogue audio "
        "after TTS and before any GPU video job"
    )
    disk = shutil.disk_usage(PROJECT_ROOT)
    disk_report = {
        "root": str(PROJECT_ROOT.anchor),
        "free_gb": round(disk.free / (1024 ** 3), 2),
        "minimum_free_gb": 100.0,
        "ready": disk.free >= 100 * 1024 ** 3,
    }
    gpu_report = _gpu_readiness()
    paths = _paths(run_id)
    collisions = [str(path) for path in paths.values() if path.exists()]
    prerequisites = {
        "execution_window_open": window["open"],
        "static_inputs_ready": static["ok"],
        "runtime_preflight_ready": runtime_json.get("ok") is True,
        "disk_space_ready": disk_report["ready"],
        "gpu_resource_ready": gpu_report["ready"],
        "immutable_paths_unused": not collisions,
    }
    executable = all(prerequisites.values())
    python = PROJECT_ROOT / ".venv/Scripts/python.exe"
    smoke_command = (
        f'& "{python}" "{PROJECT_ROOT / "scripts/run_task1_story_v61_failed_smoke.py"}" '
        f'--execute --confirm-execution {smoke.EXECUTION_CONFIRMATION} '
        f'--expected-runner-sha256 {runner_contract["sha256"]} '
        f'--run-id {run_id} '
        f'--progress-path "{paths["progress"]}" --output-dir "{paths["render"]}" '
        f'--audio-dir "{paths["audio"]}" --evidence-root "{paths["evidence"]}"'
    )
    packet_command = (
        f'& "{python}" "{PROJECT_ROOT / "scripts/prepare_task1_story_v61_smoke_review_packet.py"}" '
        f'--progress "{paths["progress"]}" --output-root "{paths["review_packet"]}" '
        f'--review-output "{paths["review"]}"'
    )
    blockers = [name for name, passed in prerequisites.items() if not passed]
    return {
        "schema_version": SCHEMA,
        "created_at": observed.astimezone(timezone.utc).isoformat(),
        "run_id": run_id,
        "scope": "seven_shot_live_action_smoke_only",
        "execution_window": window,
        "static_validation": static,
        "runtime_preflight": runtime_json,
        "runtime_preflight_source_contract": provider_contract,
        "smoke_runner_source_contract": runner_contract,
        "review_workflow": {
            "mode": "streamlit_pending_review",
            "ready": True,
            "signature_required": False,
        },
        "disk": disk_report,
        "gpu": gpu_report,
        "paths": {key: str(value) for key, value in paths.items()},
        "path_collisions": collisions,
        "prerequisites": prerequisites,
        "smoke_execution_allowed": executable,
        "blockers": blockers,
        "commands": {
            "render_seven_shot_smoke": smoke_command if executable else "",
            "prepare_human_review_packet_after_success": packet_command if executable else "",
            "full_batch_render": "",
            "douyin_publish": "",
            "fanqie_backfill": "",
        },
        "mandatory_stop": {
            "after": "prepare_human_review_packet_after_success",
            "reason": "frontend human approval is required before any 19-shot work",
        },
        "forbidden_side_effects": {
            "tts_calls": 0, "gpu_jobs_submitted": 0, "render_paths_created": 0,
            "database_writes": 0, "browser_operations": 0,
            "douyin_uploads": 0, "fanqie_backfills": 0,
        },
    }


def _write_new(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
    except FileExistsError as exc:
        raise ValueError(f"refusing to overwrite window packet: {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare a smoke-only V6.1 execution packet.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--comfy-base-url", default="http://127.0.0.1:8190")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        packet = prepare(
            run_id=args.run_id, comfy_base_url=args.comfy_base_url,
        )
        _write_new(args.output.resolve(), packet)
    except (ValueError, OSError, RuntimeError) as exc:
        print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(packet, ensure_ascii=False, indent=2))
    return 0 if packet["smoke_execution_allowed"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
