from __future__ import annotations

"""Prepare or render the reviewed task-1 V6.1 failed-shot smoke set.

The default mode is deliberately static: it validates the immutable plan,
anchors, selected shot boundary, local tool configuration and source hashes,
then writes an audit record.  It does not contact ComfyUI, run TTS, write a
database, open a browser, publish, or backfill.

``--prepare-audio`` renders the reviewed emotional dialogue and performs the
provider's complete read-only runtime preflight.  ``--execute`` additionally
generates video and requires an explicit confirmation token.
"""

import argparse
import hashlib
import json
import re
import sys
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(r"D:\IT\ai_douyin")
P0_ROOT = Path(r"D:\IT\ai_douyin_p0")
if str(P0_ROOT) not in sys.path:
    sys.path.insert(0, str(P0_ROOT))

from src.novel_promotion.emotion_tts import EmotionVoiceConfig  # noqa: E402
from src.novel_promotion.video_generation_service import (  # noqa: E402
    _load_structured_scene_plan,
    _synthesize_performance_audio,
)
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))
from audit_task1_story_v61_creative_contract import audit as audit_creative_contract  # noqa: E402
from sadtalker_fullframe_provider import HybridLiveActionV61Provider  # noqa: E402


PLAN_PATH = PROJECT_ROOT / (
    "data/fanqie_promotion/scene_plans/"
    "task1_story_v61_reviewed_anchors.json"
)
EXPECTED_PLAN_SHA256 = (
    "D2C15C86B0AC57BE8CD26EF687C65C049D64B2069568707C8B699AE6D5828CB4"
)
FAILED_SHOT_IDS = (
    "b01_boast",
    "b03_object_question",
    "b04_confused_answer",
    "b05_age_burst",
    "b06_pull_away",
    "b07_protest",
    "b08_offer_one",
)
EXECUTION_CONFIRMATION = "TASK1-V61-FAILED-SMOKE"
RUN_ID_PATTERN = re.compile(r"[0-9]{8}_[0-9]{6}")

DEFAULT_OUTPUT = PROJECT_ROOT / (
    "data/fanqie_promotion/renders/task1_story_v61_failed_smoke"
)
DEFAULT_EVIDENCE = PROJECT_ROOT / (
    "data/fanqie_promotion/evidence/task1_story_v61"
)
DEFAULT_PROGRESS = PROJECT_ROOT / (
    "data/qa/task1_story_v61_failed_smoke_progress.json"
)
DEFAULT_VALIDATION = PROJECT_ROOT / (
    "data/qa/task1_story_v61_failed_smoke_validation.json"
)
DEFAULT_AUDIO = PROJECT_ROOT / (
    "data/fanqie_promotion/audio/task1_story_v61_failed_smoke"
)

SOURCE_FILES = (
    P0_ROOT / "src/novel_promotion/comfy_ltx_video_provider.py",
    P0_ROOT / "src/novel_promotion/video_generation_service.py",
    P0_ROOT / "src/novel_promotion/emotion_tts.py",
    P0_ROOT / "src/novel_promotion/live_action_flow.py",
    PROJECT_ROOT / "scripts/cosyvoice_story_batch.py",
    PROJECT_ROOT / "scripts/run_sadtalker_fullframe.py",
    PROJECT_ROOT / "scripts/sadtalker_fullframe_provider.py",
    PROJECT_ROOT / "scripts/audit_task1_story_v61_creative_contract.py",
    Path(__file__).resolve(),
)
EXPECTED_RUNTIME_SOURCE_SHA256S = {
    str(P0_ROOT / "src/novel_promotion/comfy_ltx_video_provider.py").replace("\\", "/"):
        "3D2D8ECA86683F58EC0C04A43484EBE3DDD396C89EB805414FF0BA5C2A819B80",
    str(P0_ROOT / "src/novel_promotion/video_generation_service.py").replace("\\", "/"):
        "02FBDB9FEC1D777AC78D66602A65BEFED25BCBCE50CEA56CE30BE27F83285D53",
    str(P0_ROOT / "src/novel_promotion/emotion_tts.py").replace("\\", "/"):
        "264A35055A61C5AF3969AF26422663CA04262D845A63D4730E21604392B5F226",
    str(P0_ROOT / "src/novel_promotion/live_action_flow.py").replace("\\", "/"):
        "FA24B01B078F9CA07A7DE02097E3218235B9907D85E298FAEB203D7FCCADB61D",
    str(PROJECT_ROOT / "scripts/cosyvoice_story_batch.py").replace("\\", "/"):
        "AA04BE203EEB4069BC07453DB6EB28DEBB977BFC2AA7F0C6B4E35F7096B730B2",
    str(PROJECT_ROOT / "scripts/run_sadtalker_fullframe.py").replace("\\", "/"):
        "58EAF4C73E816868CCF7DC8E7A1E3566E78FEA748B6F32161263A40CD631DDF2",
    str(PROJECT_ROOT / "scripts/sadtalker_fullframe_provider.py").replace("\\", "/"):
        "0D02A7B06F5281F78890DCB5D6BF74A4AF0C14455AECC9A4E6B649C884FDD3C1",
    str(PROJECT_ROOT / "scripts/audit_task1_story_v61_creative_contract.py").replace("\\", "/"):
        "B3E0D15F913C56CBA1ED1CA3E591C35F9916AC5335E7D4F87870027ABB4199B6",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _runtime_source_integrity() -> dict[str, Any]:
    """Re-hash every reviewed production input immediately before execution."""
    checks: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in SOURCE_FILES:
        key = str(path).replace("\\", "/")
        actual = _sha256(path) if path.is_file() else ""
        expected = EXPECTED_RUNTIME_SOURCE_SHA256S.get(key, "")
        # The runner records its own hash for audit, but cannot safely pin its
        # current file without creating a self-referential digest.  All imported
        # production components and the external TTS runner are hard-pinned.
        pinned = path.resolve() != Path(__file__).resolve()
        ok = bool(actual) and (not pinned or actual == expected)
        checks.append({
            "path": key,
            "expected_sha256": expected if pinned else "self_recorded_not_pinned",
            "actual_sha256": actual,
            "pinned": pinned,
            "ok": ok,
        })
        if not ok:
            errors.append(
                f"Reviewed runtime source missing or changed: {key} "
                f"(expected {expected}, got {actual})"
            )
    return {"ok": not errors, "errors": errors, "checks": checks}


def _execution_window(now: datetime | None = None) -> dict[str, Any]:
    """Return the current execution policy.

    Rendering is available immediately. Human approval happens after the
    candidate is generated, through the Streamlit review queue.
    """
    observed = now or datetime.now(timezone.utc)
    if observed.tzinfo is None:
        raise ValueError("execution-window clock must be timezone-aware")
    return {
        "open": True,
        "observed_at": observed.isoformat(),
        "not_before": None,
        "remaining_seconds": 0.0,
        "policy": "immediate_execution_with_frontend_human_review",
    }


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "__dict__"):
        return _jsonable(vars(value))
    return value


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp_path.replace(path)


def _protect_render_progress(
    path: Path,
    *,
    replace_incomplete: bool,
) -> None:
    """Preserve rendered evidence; never overwrite a run containing shots."""
    if not path.exists():
        return
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"Progress path already exists and is unreadable: {path}. "
            "Choose a new --progress-path."
        ) from exc
    shots = existing.get("shots") if isinstance(existing, dict) else None
    rendered_evidence = bool(shots) or (
        isinstance(existing, dict)
        and existing.get("result")
        == "FAILED_SCENE_SMOKE_RENDERED_AWAITING_HUMAN_REVIEW"
    )
    if rendered_evidence:
        raise ValueError(
            f"Refusing to overwrite smoke render evidence: {path}. "
            "Choose a new --progress-path for a new candidate run."
        )
    raise ValueError(
        f"Progress path already exists: {path}. Mutating runs require a new "
        "--progress-path; incomplete evidence is never overwritten."
    )


def _protect_validation_target(path: Path) -> None:
    """Never let a validate-only report replace render evidence."""
    if not path.exists():
        return
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"Validation target exists and is unreadable: {path}. Choose a new path."
        ) from exc
    if not isinstance(existing, dict):
        raise ValueError(f"Validation target is not a JSON object: {path}")
    if existing.get("shots") or existing.get("result") == (
        "FAILED_SCENE_SMOKE_RENDERED_AWAITING_HUMAN_REVIEW"
    ):
        raise ValueError(
            f"Refusing to overwrite smoke render evidence with validation: {path}"
        )


def _reserve_render_progress(path: Path) -> None:
    """Atomically claim a new mutating-run evidence path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump({
                "schema_version": "fanqie_v61_failed_smoke_progress/v1",
                "result": "RUN_PATH_RESERVED",
                "created_at": _utc_now(),
                "gates": {
                    "publish_allowed": False,
                    "fanqie_backfill_allowed": False,
                },
            }, handle, ensure_ascii=False, indent=2)
    except FileExistsError as exc:
        raise ValueError(
            f"Progress path was claimed concurrently: {path}. Choose a new "
            "--progress-path."
        ) from exc


def _reserve_render_directories(*paths: Path) -> None:
    """Atomically claim every mutable artifact leaf before TTS/GPU work.

    Filesystems cannot reserve multiple directories as one transaction.  A
    partial claim is deliberately retained on failure as audit evidence; the
    operator must choose a completely new timestamped run instead of reusing it.
    """
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.mkdir(exist_ok=False)
        except FileExistsError as exc:
            raise ValueError(
                f"Mutable artifact directory already exists or was claimed "
                f"concurrently: {path}. Choose a new run ID and all-new paths."
            ) from exc


def _validate_mutating_run_paths(args: argparse.Namespace) -> None:
    """Bind one reviewer proof/run ID to one immutable artifact namespace."""
    if not RUN_ID_PATTERN.fullmatch(args.run_id):
        raise ValueError("run_id must use YYYYMMDD_HHMMSS")
    expected_names = {
        "progress_path": f"task1_story_v61_failed_smoke_progress_{args.run_id}.json",
        "output_dir": f"task1_story_v61_failed_smoke_{args.run_id}",
        "audio_dir": f"task1_story_v61_failed_smoke_{args.run_id}",
        "evidence_root": f"task1_story_v61_{args.run_id}",
    }
    for field, expected_name in expected_names.items():
        actual = getattr(args, field).resolve().name
        if actual != expected_name:
            raise ValueError(
                f"{field} must end in the exact run-bound name {expected_name!r}"
            )


def _emotion_config() -> EmotionVoiceConfig:
    return EmotionVoiceConfig(
        provider_name="cosyvoice3",
        runner_script=str(PROJECT_ROOT / "scripts/cosyvoice_story_batch.py"),
        engine_binary=r"C:\Users\c\.conda\envs\cosyvoice310\python.exe",
        engine_root=r"D:\IT\CosyVoice",
        model_dir=(
            r"D:\IT\CosyVoice\pretrained_models\Fun-CosyVoice3-0.5B"
        ),
        project_root=str(PROJECT_ROOT),
        voice_reference_dir=str(
            PROJECT_ROOT / "data/audio/kokoro/auditions"
        ),
        cache_dir=str(PROJECT_ROOT / "data/.cosyvoice_cache"),
        default_speed=1.08,
    )


def _provider(base_url: str, evidence_root: Path) -> HybridLiveActionV61Provider:
    return HybridLiveActionV61Provider(
        base_url=base_url,
        comfy_input=r"D:\IT\AI_vido\ComfyUI\input",
        comfy_output=r"D:\IT\AI_vido\ComfyUI\output",
        evidence_root=str(evidence_root.resolve()),
        timeout_seconds=7200,
        sadtalker_python=r"C:\Users\c\.conda\envs\sadtalker\python.exe",
        sadtalker_root=r"D:\IT\SadTalker",
        sadtalker_checkpoint_dir=r"D:\IT\SadTalker\checkpoints",
        sadtalker_wrapper=str(PROJECT_ROOT / "scripts/run_sadtalker_fullframe.py"),
    )


def _select_plans(all_plans: list[Any], requested: list[str]) -> list[Any]:
    selected_ids = requested or list(FAILED_SHOT_IDS)
    duplicates = sorted(
        shot_id for shot_id in set(selected_ids) if selected_ids.count(shot_id) > 1
    )
    if duplicates:
        raise ValueError("Duplicate --shot-id values: " + ", ".join(duplicates))
    outside_scope = sorted(set(selected_ids) - set(FAILED_SHOT_IDS))
    if outside_scope:
        raise ValueError(
            "This runner is restricted to the reviewed failed-shot set; "
            "outside-scope IDs: " + ", ".join(outside_scope)
        )
    by_id = {plan.scene_id: plan for plan in all_plans}
    missing = sorted(set(selected_ids) - set(by_id))
    if missing:
        raise ValueError("Selected shot IDs missing from V6.1 plan: " + ", ".join(missing))
    return [by_id[shot_id] for shot_id in selected_ids]


def _validate_static(
    *, plan_path: Path, all_plans: list[Any], selected_plans: list[Any]
) -> dict[str, Any]:
    errors: list[str] = []
    plan_sha = _sha256(plan_path)
    if plan_sha != EXPECTED_PLAN_SHA256:
        errors.append(
            f"V6.1 plan SHA mismatch: expected {EXPECTED_PLAN_SHA256}, got {plan_sha}"
        )
    if len(all_plans) != 19:
        errors.append(f"V6.1 plan must contain 19 beats, got {len(all_plans)}")

    anchor_checks: list[dict[str, Any]] = []
    master_checks_by_character: dict[str, dict[str, Any]] = {}
    voice_checks: list[dict[str, Any]] = []
    for plan in selected_plans:
        anchor_path = Path(str(plan.metadata.get("shot_anchor_image") or ""))
        expected_anchor_sha = str(
            plan.metadata.get("shot_anchor_sha256") or ""
        ).upper()
        actual_anchor_sha = _sha256(anchor_path) if anchor_path.is_file() else ""
        anchor_ok = bool(expected_anchor_sha) and actual_anchor_sha == expected_anchor_sha
        anchor_checks.append(
            {
                "scene_id": plan.scene_id,
                "path": str(anchor_path),
                "expected_sha256": expected_anchor_sha,
                "actual_sha256": actual_anchor_sha,
                "ok": anchor_ok,
            }
        )
        if not anchor_ok:
            errors.append(f"{plan.scene_id}: reviewed anchor is missing or changed")

        if not str(plan.visual_prompt).isascii():
            errors.append(f"{plan.scene_id}: motion prompt is not ASCII")

        master_paths = plan.metadata.get("master_image_paths") or {}
        master_sha256s = plan.metadata.get("master_image_sha256s") or {}
        for character_id in plan.metadata.get("character_ids") or []:
            if character_id in master_checks_by_character:
                continue
            master_path = Path(str(master_paths.get(character_id) or ""))
            expected_master_sha = str(
                master_sha256s.get(character_id) or ""
            ).upper()
            actual_master_sha = _sha256(master_path) if master_path.is_file() else ""
            master_ok = (
                bool(expected_master_sha)
                and actual_master_sha == expected_master_sha
            )
            master_checks_by_character[character_id] = {
                "character_id": character_id,
                "path": str(master_path),
                "expected_sha256": expected_master_sha,
                "actual_sha256": actual_master_sha,
                "ok": master_ok,
            }
            if not master_ok:
                errors.append(
                    f"{character_id}: reviewed character master is missing or changed"
                )

        if plan.metadata.get("spoken_closeup"):
            cast = plan.metadata.get("cast") or {}
            speaker = str(plan.metadata.get("speaker_id") or "")
            speaker_meta = cast.get(speaker) if isinstance(cast, dict) else None
            voice_path = Path(
                str(speaker_meta.get("voice_reference") or "")
            ) if isinstance(speaker_meta, dict) else Path("")
            voice_ok = bool(speaker) and voice_path.is_file()
            voice_checks.append(
                {
                    "scene_id": plan.scene_id,
                    "speaker_id": speaker,
                    "voice_reference": str(voice_path),
                    "ok": voice_ok,
                }
            )
            if not voice_ok:
                errors.append(f"{plan.scene_id}: fixed voice reference is unavailable")

    emotion_errors = _emotion_config().validate()
    errors.extend(f"CosyVoice3: {error}" for error in emotion_errors)

    runtime_sources = _runtime_source_integrity()
    errors.extend(runtime_sources["errors"])

    required_local_paths = (
        PROJECT_ROOT / "scripts/run_sadtalker_fullframe.py",
        PROJECT_ROOT / "scripts/sadtalker_fullframe_provider.py",
        Path(r"C:\Users\c\.conda\envs\sadtalker\python.exe"),
        Path(r"D:\IT\SadTalker\inference.py"),
        Path(r"D:\IT\SadTalker\checkpoints"),
        Path(r"D:\IT\AI_vido\ComfyUI\input"),
        Path(r"D:\IT\AI_vido\ComfyUI\output"),
    )
    path_checks = [
        {"path": str(path), "exists": path.exists()} for path in required_local_paths
    ]
    errors.extend(
        f"Required local path missing: {item['path']}"
        for item in path_checks
        if not item["exists"]
    )

    result = {
        "ok": not errors,
        "errors": errors,
        "plan_sha256": plan_sha,
        "all_beat_count": len(all_plans),
        "selected_shot_ids": [plan.scene_id for plan in selected_plans],
        "selected_duration_seconds": round(
            sum(float(plan.estimated_duration_s) for plan in selected_plans), 3
        ),
        "spoken_closeup_count": sum(
            bool(plan.metadata.get("spoken_closeup")) for plan in selected_plans
        ),
        "anchor_checks": anchor_checks,
        "master_checks": list(master_checks_by_character.values()),
        "voice_checks": voice_checks,
        "local_path_checks": path_checks,
        "cosyvoice_config_errors": emotion_errors,
        "runtime_source_integrity": runtime_sources,
    }
    creative = audit_creative_contract(plan_path)
    result["creative_contract_audit"] = creative
    if not creative["passed"]:
        result["ok"] = False
        result["errors"].extend(
            f"Creative contract: {error}" for error in creative["errors"]
        )
    return result


def _base_progress(
    *, args: argparse.Namespace, selected_plans: list[Any], static: dict[str, Any]
) -> dict[str, Any]:
    mode = "execute" if args.execute else (
        "prepare_audio" if args.prepare_audio else "validate_only"
    )
    return {
        "schema_version": "fanqie_v61_failed_smoke_progress/v1",
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "task_id": 1,
        "scope": "failed_scene_smoke",
        "mode": mode,
        "plan_path": str(args.plan.resolve()),
        "expected_plan_sha256": EXPECTED_PLAN_SHA256,
        "selected_shot_ids": [plan.scene_id for plan in selected_plans],
        "output_dir": str(args.output_dir.resolve()),
        "audio_dir": str(args.audio_dir.resolve()),
        "evidence_root": str(args.evidence_root.resolve()),
        "source_hashes": {
            item["path"]: item["actual_sha256"]
            for item in static["runtime_source_integrity"]["checks"]
        },
        "static_validation": static,
        "runtime_preflight": None,
        "audio_preparation": None,
        "shots": [],
        "gates": {
            "static_validation_passed": bool(static["ok"]),
            "audio_prepared": False,
            "runtime_preflight_passed": False,
            "selected_shots_rendered": False,
            "failed_scene_smoke_rendered": False,
            "human_review_required": True,
            "human_video_approval_obtained": False,
            "matching_fanqie_task_confirmed": False,
            "publish_allowed": False,
            "fanqie_backfill_allowed": False,
        },
        "forbidden_side_effects": {
            "database_writes": 0,
            "browser_operations": 0,
            "douyin_uploads": 0,
            "fanqie_backfills": 0,
        },
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate, prepare audio for, or render the seven reviewed V6.1 failed shots."
    )
    parser.add_argument("--plan", type=Path, default=PLAN_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--audio-dir", type=Path, default=DEFAULT_AUDIO)
    parser.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument(
        "--progress-path",
        type=Path,
        default=None,
        help=(
            "Audit output path. Defaults to a separate validation file in "
            "validate-only mode, and the render progress file for "
            "--prepare-audio/--execute."
        ),
    )
    parser.add_argument("--comfy-base-url", default="http://127.0.0.1:8190")
    parser.add_argument("--run-id", default="")
    parser.add_argument(
        "--expected-runner-sha256",
        default="",
        help=(
            "Required for --prepare-audio/--execute. Supplied by the reviewed "
            "window packet and rechecked before any path reservation or TTS/GPU work."
        ),
    )
    parser.add_argument(
        "--shot-id",
        action="append",
        default=[],
        help="Select a reviewed failed shot; repeat for multiple shots.",
    )
    parser.add_argument(
        "--prepare-audio",
        action="store_true",
        help="Run CosyVoice3 and complete provider preflight, but do not generate video.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Run CosyVoice3 and generate the selected failed-shot videos.",
    )
    parser.add_argument(
        "--confirm-execution",
        default="",
        help=f"Required with --execute; must equal {EXECUTION_CONFIRMATION!r}.",
    )
    parser.add_argument(
        "--replace-incomplete-progress",
        action="store_true",
        help="Deprecated compatibility flag; existing evidence is never overwritten.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.progress_path is None:
        args.progress_path = (
            DEFAULT_PROGRESS if args.prepare_audio or args.execute
            else DEFAULT_VALIDATION
        )
    if (
        not args.prepare_audio
        and not args.execute
        and args.progress_path.resolve() == DEFAULT_PROGRESS.resolve()
    ):
        print(json.dumps({
            "error": "Validate-only output must not target the smoke render progress path",
            "publish_allowed": False,
            "fanqie_backfill_allowed": False,
        }, ensure_ascii=False, indent=2))
        return 2
    if args.execute and args.confirm_execution != EXECUTION_CONFIRMATION:
        print(
            json.dumps(
                {
                    "error": "Execution confirmation missing or invalid",
                    "required_confirmation": EXECUTION_CONFIRMATION,
                    "publish_allowed": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    if args.prepare_audio or args.execute:
        actual_runner_sha = _sha256(Path(__file__).resolve())
        if args.expected_runner_sha256.upper() != actual_runner_sha:
            print(json.dumps({
                "error": "Smoke runner SHA is missing or differs from the reviewed window packet",
                "expected_runner_sha256": args.expected_runner_sha256.upper(),
                "actual_runner_sha256": actual_runner_sha,
                "publish_allowed": False,
                "fanqie_backfill_allowed": False,
            }, ensure_ascii=False, indent=2))
            return 2
        runtime_sources = _runtime_source_integrity()
        if not runtime_sources["ok"]:
            print(json.dumps({
                "error": "Reviewed runtime source integrity failed",
                "runtime_source_integrity": runtime_sources,
                "progress_created": False,
                "render_paths_created": False,
                "publish_allowed": False,
                "fanqie_backfill_allowed": False,
            }, ensure_ascii=False, indent=2))
            return 2
        window = _execution_window()
        if not window["open"]:
            print(json.dumps({
                "error": "TTS/GPU execution window is not open",
                "execution_window": window,
                "progress_created": False,
                "publish_allowed": False,
                "fanqie_backfill_allowed": False,
            }, ensure_ascii=False, indent=2))
            return 2

        if not args.run_id:
            print(json.dumps({
                "error": "Exact run ID is required",
                "publish_allowed": False,
                "fanqie_backfill_allowed": False,
            }, ensure_ascii=False, indent=2))
            return 2
        try:
            _validate_mutating_run_paths(args)
        except ValueError as exc:
            print(json.dumps({
                "error": str(exc), "progress_created": False,
                "publish_allowed": False, "fanqie_backfill_allowed": False,
            }, ensure_ascii=False, indent=2))
            return 2
    if args.prepare_audio or args.execute:
        try:
            _protect_render_progress(
                args.progress_path.resolve(),
                replace_incomplete=args.replace_incomplete_progress,
            )
            _reserve_render_progress(args.progress_path.resolve())
            _reserve_render_directories(
                args.output_dir.resolve(),
                args.audio_dir.resolve(),
                args.evidence_root.resolve(),
            )
        except ValueError as exc:
            print(json.dumps({
                "error": str(exc),
                "publish_allowed": False,
                "fanqie_backfill_allowed": False,
            }, ensure_ascii=False, indent=2))
            return 2
    else:
        try:
            _protect_validation_target(args.progress_path.resolve())
        except ValueError as exc:
            print(json.dumps({
                "error": str(exc), "publish_allowed": False,
                "fanqie_backfill_allowed": False,
            }, ensure_ascii=False, indent=2))
            return 2

    plan_path = args.plan.resolve()
    all_plans = _load_structured_scene_plan(str(plan_path), "")
    selected_plans = _select_plans(all_plans, args.shot_id)
    static = _validate_static(
        plan_path=plan_path,
        all_plans=all_plans,
        selected_plans=selected_plans,
    )
    progress = _base_progress(args=args, selected_plans=selected_plans, static=static)
    _write_json_atomic(args.progress_path.resolve(), progress)
    if not static["ok"]:
        print(json.dumps(progress, ensure_ascii=False, indent=2))
        return 2

    # Default mode ends here.  No service call, TTS invocation or GPU work.
    if not args.prepare_audio and not args.execute:
        progress["result"] = "STATIC_VALIDATION_PASSED"
        progress["updated_at"] = _utc_now()
        _write_json_atomic(args.progress_path.resolve(), progress)
        print(json.dumps(progress, ensure_ascii=False, indent=2))
        return 0

    audio_result = _synthesize_performance_audio(
        scene_plans=selected_plans,
        emotion_config=_emotion_config(),
        output_dir=str(args.audio_dir.resolve()),
        dry_run=False,
    )
    progress["audio_preparation"] = _jsonable(audio_result)
    progress["gates"]["audio_prepared"] = bool(audio_result.get("success"))
    progress["updated_at"] = _utc_now()
    _write_json_atomic(args.progress_path.resolve(), progress)
    if not audio_result.get("success"):
        progress["result"] = "AUDIO_PREPARATION_FAILED"
        _write_json_atomic(args.progress_path.resolve(), progress)
        print(json.dumps(progress, ensure_ascii=False, indent=2))
        return 3

    provider = _provider(args.comfy_base_url, args.evidence_root)
    runtime_preflight = provider.preflight(
        selected_plans, require_dialogue_audio=True,
    )
    progress["runtime_preflight"] = _jsonable(runtime_preflight)
    progress["gates"]["runtime_preflight_passed"] = bool(runtime_preflight.ok)
    progress["updated_at"] = _utc_now()
    _write_json_atomic(args.progress_path.resolve(), progress)
    if not runtime_preflight.ok:
        progress["result"] = "RUNTIME_PREFLIGHT_FAILED"
        _write_json_atomic(args.progress_path.resolve(), progress)
        print(json.dumps(progress, ensure_ascii=False, indent=2))
        return 4

    if not args.execute:
        progress["result"] = "AUDIO_AND_RUNTIME_PREFLIGHT_PASSED"
        _write_json_atomic(args.progress_path.resolve(), progress)
        print(json.dumps(progress, ensure_ascii=False, indent=2))
        return 0

    had_failure = False
    for position, plan in enumerate(selected_plans, start=1):
        result = provider.provide_scenes([plan], args.output_dir.resolve())
        shot_result = {
            "position": position,
            "scene_id": plan.scene_id,
            "completed_at": _utc_now(),
            "assets": _jsonable(result.assets),
            "missing": _jsonable(result.missing),
        }
        progress["shots"].append(shot_result)
        had_failure = had_failure or bool(result.missing) or not bool(result.assets)
        progress["updated_at"] = _utc_now()
        _write_json_atomic(args.progress_path.resolve(), progress)

    rendered = not had_failure and len(progress["shots"]) == len(selected_plans)
    full_smoke = rendered and {
        plan.scene_id for plan in selected_plans
    } == set(FAILED_SHOT_IDS)
    progress["gates"]["selected_shots_rendered"] = rendered
    progress["gates"]["failed_scene_smoke_rendered"] = full_smoke
    if full_smoke:
        progress["result"] = "FAILED_SCENE_SMOKE_RENDERED_AWAITING_HUMAN_REVIEW"
    elif rendered:
        progress["result"] = "DIAGNOSTIC_SHOTS_RENDERED_NOT_REVIEW_ELIGIBLE"
    else:
        progress["result"] = "FAILED_SCENE_SMOKE_RENDER_FAILED"
    progress["finished_at"] = _utc_now()
    progress["updated_at"] = _utc_now()
    _write_json_atomic(args.progress_path.resolve(), progress)
    print(json.dumps(progress, ensure_ascii=False, indent=2))
    return 1 if had_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
