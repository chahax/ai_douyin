from __future__ import annotations

"""Render all 19 V6.1 beats for a final whole-video review.

By default every invocation re-validates the original smoke render progress,
the human review and all candidate files.  ``--review-sequence full_video_only``
instead accepts the seven clips only as machine-verified, unreviewed inputs and
keeps the sole human decision at the assembled whole-video gate.  A certificate
alone is never trusted.  The
default mode performs only this gate and plan validation; emotional TTS and
video generation require explicit flags.  No database, browser, upload or
backfill path exists here.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(r"D:\IT\ai_douyin")
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
for root in (SCRIPTS_ROOT,):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

import run_task1_story_v61_failed_smoke as smoke  # noqa: E402
import validate_task1_story_v61_smoke_review as review_gate  # noqa: E402


EXPECTED_BEAT_COUNT = 19
EXECUTION_CONFIRMATION = "TASK1-V61-FULL-19-BEATS"
EXPECTED_RESULT = "FULL_19_SHOTS_RENDERED_AWAITING_ASSEMBLY_AND_HUMAN_REVIEW"
DEFAULT_REVIEW = PROJECT_ROOT / "data/qa/task1_story_v61_failed_smoke_review.json"
DEFAULT_SMOKE_PROGRESS = PROJECT_ROOT / "data/qa/task1_story_v61_failed_smoke_progress.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "data/fanqie_promotion/renders/task1_story_v61_full"
DEFAULT_AUDIO = PROJECT_ROOT / "data/fanqie_promotion/audio/task1_story_v61_full"
DEFAULT_EVIDENCE = PROJECT_ROOT / "data/fanqie_promotion/evidence/task1_story_v61"
DEFAULT_PROGRESS = PROJECT_ROOT / "data/qa/task1_story_v61_full_batch_progress.json"
DEFAULT_VALIDATION = PROJECT_ROOT / "data/qa/task1_story_v61_full_batch_validation.json"
RENDER_ATTESTATION_NAMESPACE = "fanqie-v61-full-batch-render"
RENDER_ATTESTATION_RECEIPT_SCHEMA = "fanqie_v61_render_attestation_receipt/v1"
RENDER_ATTESTATION_RECEIPT_SUFFIX = ".render_attestation.json"
SIGNER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.@+-]{3,128}$")
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{5,95}$")
REVIEW_SEQUENCES = ("smoke_then_full", "full_video_only")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def _write_json_new(path: Path, payload: dict[str, Any]) -> None:
    """Write an immutable receipt; never replace prior evidence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
    except FileExistsError as exc:
        raise ValueError(f"Refusing to overwrite immutable receipt: {path}") from exc


def _render_attestation_receipt_path(progress_path: Path) -> Path:
    """Derive the immutable render receipt path from one progress path."""
    resolved = progress_path.resolve()
    return resolved.with_name(resolved.name + RENDER_ATTESTATION_RECEIPT_SUFFIX)


def _render_attestation_receipt(
    *, progress_path: Path, receipt_path: Path, progress: dict[str, Any], plan_path: Path,
) -> dict[str, Any]:
    """Bind one completed progress file to its renderer and immutable inputs."""
    return {
        "schema_version": RENDER_ATTESTATION_RECEIPT_SCHEMA,
        "created_at": _now(),
        "task_id": 1,
        "scope": "full_19_beat_render",
        "result": EXPECTED_RESULT,
        "receipt_path": str(receipt_path.resolve()),
        "progress_path": str(progress_path.resolve()),
        "progress_sha256": smoke._sha256(progress_path.resolve()),
        "renderer_id": str(progress.get("render_signer_id") or "").strip(),
        "plan_path": str(plan_path.resolve()),
        "plan_sha256": smoke._sha256(plan_path.resolve()),
        "shot_count": EXPECTED_BEAT_COUNT,
    }


def _validate_run_bound_paths(args: argparse.Namespace) -> None:
    if not RUN_ID_PATTERN.fullmatch(args.run_id):
        raise ValueError("--run-id is required for mutating modes and has an invalid format")
    paths = {
        "progress-path": args.progress_path.resolve(),
        "certificate": args.certificate.resolve(),
        "output-dir": args.output_dir.resolve(),
        "audio-dir": args.audio_dir.resolve(),
        "evidence-root": args.evidence_root.resolve(),
    }
    if args.execute:
        paths["render-attestation-receipt"] = (
            args.render_attestation_receipt_path.resolve()
        )
    token = args.run_id.casefold()
    for label, path in paths.items():
        if token not in path.name.casefold():
            raise ValueError(f"--{label} must be bound to --run-id in its final name")
    values = list(paths.values())
    if len(set(values)) != len(values):
        raise ValueError("Mutating output paths must be distinct")
    for index, left in enumerate(values):
        for right in values[index + 1:]:
            if left in right.parents or right in left.parents:
                raise ValueError("Mutating output paths must not be nested")
    for label in ("output-dir", "audio-dir", "evidence-root"):
        if paths[label].exists():
            raise ValueError(f"--{label} is already reserved: {paths[label]}")
    if paths["certificate"].exists():
        raise ValueError(f"--certificate is already reserved: {paths['certificate']}")
    if args.execute and paths["render-attestation-receipt"].exists():
        raise ValueError(
            "render attestation receipt is already reserved: "
            f"{paths['render-attestation-receipt']}"
        )
    if args.execute and not SIGNER_ID_PATTERN.fullmatch(str(args.render_signer_id or "")):
        raise ValueError("--render-signer-id must be a non-secret stable renderer identity")


def _reserve_run_directories(args: argparse.Namespace) -> None:
    created: list[Path] = []
    try:
        for path in (args.output_dir.resolve(), args.audio_dir.resolve(), args.evidence_root.resolve()):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.mkdir(exist_ok=False)
            created.append(path)
    except Exception:
        for path in reversed(created):
            try:
                path.rmdir()
            except OSError:
                pass
        raise


def _cleanup_empty_run_directories(args: argparse.Namespace) -> None:
    """Remove only this failed attempt's still-empty directory reservations."""
    for path in (
        args.evidence_root.resolve(), args.audio_dir.resolve(), args.output_dir.resolve()
    ):
        try:
            path.rmdir()
        except (FileNotFoundError, OSError):
            pass


def _protect_full_progress(path: Path) -> None:
    """Never overwrite a render attempt that contains any shot evidence."""
    if not path.exists():
        return
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"Full-batch progress exists and is unreadable: {path}. Choose a new path."
        ) from exc
    raise ValueError(
        f"Refusing to overwrite or resume full-batch progress: {path}. "
        "Choose a new --progress-path for every mutating run."
    )


def _reserve_full_progress(path: Path, receipt_path: Path | None = None) -> None:
    """Atomically reserve a mutating-run progress path before long work starts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    reservation = {
        "schema_version": "fanqie_v61_full_batch_progress/v2",
        "result": "FULL_BATCH_PROGRESS_PATH_RESERVED",
        "shots": [],
        "render_attestation_receipt_path": (
            str(receipt_path.resolve()) if receipt_path is not None else ""
        ),
        "publish_allowed": False,
        "fanqie_backfill_allowed": False,
    }
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(reservation, handle, ensure_ascii=False, indent=2)
    except FileExistsError as exc:
        raise ValueError(
            f"Full-batch progress path was concurrently reserved: {path}"
        ) from exc


def _protect_validation_target(path: Path) -> None:
    """Validate-only reports are immutable and cannot race any prior run."""
    if not path.exists():
        return
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"Full-batch validation target is unreadable: {path}. Choose a new path."
        ) from exc
    if not isinstance(existing, dict):
        raise ValueError(f"Full-batch validation target is not a JSON object: {path}")
    raise ValueError(
        f"Refusing to overwrite any existing full-batch artifact with validation: {path}"
    )


def _closed_gates() -> dict[str, bool]:
    return {
        "smoke_machine_gate_passed": False,
        "smoke_human_review_passed": False,
        "full_review_first_authorized": False,
        "full_audio_prepared": False,
        "full_runtime_preflight_passed": False,
        "full_19_shots_rendered": False,
        "full_video_human_review_required": True,
        "full_video_human_approval_obtained": False,
        "matching_fanqie_task_confirmed": False,
        "publish_allowed": False,
        "fanqie_backfill_allowed": False,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render all 19 task-1 V6.1 beats after strict smoke review."
    )
    parser.add_argument("--plan", type=Path, default=smoke.PLAN_PATH)
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--smoke-progress", type=Path, default=DEFAULT_SMOKE_PROGRESS)
    parser.add_argument(
        "--review-sequence", choices=REVIEW_SEQUENCES,
        default="smoke_then_full",
        help="Use full_video_only to defer the only human decision to the assembled candidate.",
    )
    parser.add_argument("--certificate", type=Path, default=None,
                        help="Fresh run-bound smoke-review revalidation receipt (mutating modes only).")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--audio-dir", type=Path, default=DEFAULT_AUDIO)
    parser.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--progress-path", type=Path, default=None)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--comfy-base-url", default="http://127.0.0.1:8190")
    parser.add_argument("--prepare-audio", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-execution", default="")
    parser.add_argument(
        "--render-signer-id", default="system",
        help="Deprecated compatibility field; cryptographic signing is no longer required.",
    )
    return parser.parse_args(argv)


def _load_machine_verified_smoke_candidates(
    review_path: Path, progress_path: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Revalidate pending smoke machine evidence without claiming human approval."""
    review = json.loads(review_path.read_text(encoding="utf-8"))
    if (
        review.get("schema_version") != "fanqie_v61_failed_smoke_human_review/v1"
        or review.get("task_id") != 1
        or review.get("scope") != "failed_scene_smoke"
        or review.get("review_status") != "pending_review"
    ):
        raise ValueError("full-video-only mode requires an untouched pending smoke review")
    if Path(str(review.get("source_progress_path") or "")).resolve() != progress_path:
        raise ValueError("pending smoke review progress path mismatch")
    progress_sha = smoke._sha256(progress_path)
    if str(review.get("reviewed_progress_sha256") or "").upper() != progress_sha:
        raise ValueError("pending smoke review progress SHA mismatch")
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    if (
        progress.get("schema_version") != "fanqie_v61_failed_smoke_progress/v1"
        or progress.get("result") != "FAILED_SCENE_SMOKE_RENDERED_AWAITING_HUMAN_REVIEW"
        or tuple(progress.get("selected_shot_ids") or ()) != tuple(smoke.FAILED_SHOT_IDS)
    ):
        raise ValueError("smoke progress does not prove the exact completed seven-shot boundary")
    packet_path = Path(str(review.get("machine_review_packet_path") or "")).resolve()
    packet_sha = str(review.get("machine_review_packet_sha256") or "").upper()
    if not packet_path.is_file() or smoke._sha256(packet_path) != packet_sha:
        raise ValueError("pending smoke machine packet is missing or changed")
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    if (
        packet.get("schema_version") != "fanqie_v61_smoke_machine_review_packet/v2"
        or packet.get("task_id") != 1
        or packet.get("scope") != "failed_scene_smoke"
        or packet.get("machine_gate_passed") is not True
        or packet.get("candidate_count") != len(smoke.FAILED_SHOT_IDS)
        or Path(str(packet.get("source_progress_path") or "")).resolve() != progress_path
        or str(packet.get("source_progress_sha256") or "").upper() != progress_sha
    ):
        raise ValueError("pending smoke machine packet boundary mismatch")
    packet_candidates = {
        item.get("scene_id"): item
        for item in packet.get("candidates", []) if isinstance(item, dict)
    }
    shot_by_id = {
        item.get("scene_id"): item
        for item in progress.get("shots", []) if isinstance(item, dict)
    }
    if tuple(packet_candidates) != tuple(smoke.FAILED_SHOT_IDS) or set(shot_by_id) != set(packet_candidates):
        raise ValueError("pending smoke machine candidates do not match progress shots")
    candidates: dict[str, dict[str, Any]] = {}
    for scene_id in smoke.FAILED_SHOT_IDS:
        packet_item = packet_candidates[scene_id]
        shot = shot_by_id[scene_id]
        assets = shot.get("assets")
        if not isinstance(assets, list) or len(assets) != 1 or not isinstance(assets[0], dict):
            raise ValueError(f"{scene_id}: smoke progress asset boundary mismatch")
        asset = assets[0]
        video = Path(str(asset.get("video_path") or "")).resolve()
        metadata = asset.get("metadata")
        expected_sha = str(packet_item.get("video_sha256") or "").upper()
        if (
            not video.is_file() or not isinstance(metadata, dict)
            or video != Path(str(packet_item.get("video_path") or "")).resolve()
            or smoke._sha256(video) != expected_sha
            or str(metadata.get("final_sha256") or "").upper() != expected_sha
        ):
            raise ValueError(f"{scene_id}: machine-verified smoke video changed")
        audio = Path(str(metadata.get("dialogue_audio_path") or "")).resolve()
        if (
            not audio.is_file()
            or smoke._sha256(audio) != str(packet_item.get("dialogue_audio_sha256") or "").upper()
        ):
            raise ValueError(f"{scene_id}: machine-verified smoke audio changed")
        candidates[scene_id] = {
            "scene_id": scene_id,
            "path": str(video), "sha256": expected_sha,
            "duration_seconds": float(packet_item["duration_seconds"]),
            "provider_name": str(packet_item.get("provider_name") or ""),
            "metadata": metadata,
        }
    return {
        "schema_version": "fanqie_v61_full_review_first_authorization/v1",
        "created_at": _now(), "review_sequence": "full_video_only",
        "human_smoke_review_claimed": False,
        "machine_packet_path": str(packet_path),
        "machine_packet_sha256": packet_sha,
        "progress_path": str(progress_path), "progress_sha256": progress_sha,
        "candidates": list(candidates.values()),
        "publish_allowed": False, "fanqie_backfill_allowed": False,
    }, candidates


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    mutating = bool(args.prepare_audio or args.execute)
    if args.progress_path is None:
        args.progress_path = (
            DEFAULT_PROGRESS if mutating else DEFAULT_VALIDATION
        )
    args.render_attestation_receipt_path = (
        _render_attestation_receipt_path(args.progress_path.resolve())
        if args.execute else None
    )
    protected_smoke_path = args.smoke_progress.resolve()
    protected_outputs = [("progress-path", args.progress_path.resolve())]
    if args.certificate is not None:
        protected_outputs.append(("certificate", args.certificate.resolve()))
    for label, candidate_path in protected_outputs:
        if candidate_path == protected_smoke_path:
            print(json.dumps({
                "error": f"--{label} must not overwrite --smoke-progress",
                "publish_allowed": False,
                "fanqie_backfill_allowed": False,
            }, ensure_ascii=False, indent=2))
            return 2
    if args.execute and args.confirm_execution != EXECUTION_CONFIRMATION:
        print(json.dumps({
            "error": "Execution confirmation missing or invalid",
            "required_confirmation": EXECUTION_CONFIRMATION,
            "publish_allowed": False,
        }, ensure_ascii=False, indent=2))
        return 2
    if mutating and args.certificate is None:
        print(json.dumps({
            "error": "--certificate must name a fresh run-bound revalidation receipt",
            "publish_allowed": False, "fanqie_backfill_allowed": False,
        }, ensure_ascii=False, indent=2))
        return 2
    if mutating:
        try:
            _validate_run_bound_paths(args)
        except ValueError as exc:
            print(json.dumps({
                "error": str(exc), "publish_allowed": False,
                "fanqie_backfill_allowed": False,
            }, ensure_ascii=False, indent=2))
            return 2
        window = smoke._execution_window()
        if not window["open"]:
            print(json.dumps({
                "error": "TTS/GPU execution window is not open",
                "execution_window": window,
                "progress_created": False,
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
    progress: dict[str, Any] = {
        "schema_version": "fanqie_v61_full_batch_progress/v2",
        "created_at": _now(),
        "updated_at": _now(),
        "task_id": 1,
        "scope": "full_19_beat_render",
        "mode": "execute" if args.execute else (
            "prepare_audio" if args.prepare_audio else "validate_only"
        ),
        "plan_path": str(args.plan.resolve()),
        "review_path": str(args.review.resolve()),
        "smoke_progress_path": str(args.smoke_progress.resolve()),
        "review_sequence": args.review_sequence,
        "certificate_path": str(args.certificate.resolve()) if args.certificate else "",
        "run_id": args.run_id if mutating else "",
        "output_dir": str(args.output_dir.resolve()),
        "audio_dir": str(args.audio_dir.resolve()),
        "render_signer_id": args.render_signer_id if args.execute else "",
        "render_attestation_receipt_path": (
            str(args.render_attestation_receipt_path.resolve()) if args.execute else ""
        ),
        "render_attestation_namespace": (
            RENDER_ATTESTATION_NAMESPACE if args.execute else ""
        ),
        "render_attestation_required": bool(args.execute),
        "render_attestation_completed": False,
        "gates": _closed_gates(),
        "shots": [],
        "forbidden_side_effects": {
            "database_writes": 0,
            "browser_operations": 0,
            "douyin_uploads": 0,
            "fanqie_backfills": 0,
        },
    }

    try:
        if args.review_sequence == "full_video_only":
            certificate, reviewed_candidates = _load_machine_verified_smoke_candidates(
                args.review.resolve(), args.smoke_progress.resolve()
            )
        else:
            certificate = review_gate.validate_review(
                args.review.resolve(), progress_path=args.smoke_progress.resolve()
            )
            reviewed_candidates = {
                item["scene_id"]: item for item in certificate["candidates"]
            }
    except ValueError as exc:
        progress["result"] = "SMOKE_REVIEW_GATE_REJECTED"
        progress["error"] = str(exc)
        progress["updated_at"] = _now()
        if not mutating:
            _write_json(args.progress_path.resolve(), progress)
        print(json.dumps(progress, ensure_ascii=False, indent=2))
        return 3
    progress["review_sha256"] = str(certificate.get("review_sha256") or "").upper()
    progress["smoke_machine_packet_path"] = str(certificate.get("machine_packet_path") or "")
    progress["smoke_machine_packet_sha256"] = str(certificate.get("machine_packet_sha256") or "").upper()
    progress["downstream_source_contract"] = certificate.get("downstream_source_contract")
    progress["gates"]["smoke_machine_gate_passed"] = True
    progress["gates"]["smoke_human_review_passed"] = args.review_sequence == "smoke_then_full"
    progress["gates"]["full_review_first_authorized"] = args.review_sequence == "full_video_only"

    all_plans = smoke._load_structured_scene_plan(str(args.plan.resolve()), "")
    if len(all_plans) != EXPECTED_BEAT_COUNT:
        progress["result"] = "FULL_PLAN_VALIDATION_FAILED"
        progress["error"] = (
            f"Expected {EXPECTED_BEAT_COUNT} reviewed beats, got {len(all_plans)}"
        )
        if not mutating:
            _write_json(args.progress_path.resolve(), progress)
        print(json.dumps(progress, ensure_ascii=False, indent=2))
        return 4
    static = smoke._validate_static(
        plan_path=args.plan.resolve(), all_plans=all_plans, selected_plans=all_plans
    )
    progress["static_validation"] = static
    if not static["ok"]:
        progress["result"] = "FULL_PLAN_VALIDATION_FAILED"
        if not mutating:
            _write_json(args.progress_path.resolve(), progress)
        print(json.dumps(progress, ensure_ascii=False, indent=2))
        return 4

    # The seven clips accepted in the authenticated frontend are immutable inputs
    # to the full candidate.  Reuse them rather than rendering look-alikes.
    generation_plans = [
        plan for plan in all_plans if plan.scene_id not in reviewed_candidates
    ]
    if len(generation_plans) != EXPECTED_BEAT_COUNT - len(reviewed_candidates):
        progress["result"] = "REVIEWED_CANDIDATE_MAPPING_FAILED"
        progress["error"] = "Frontend-approved candidates do not map uniquely into the 19-beat plan"
        if not mutating:
            _write_json(args.progress_path.resolve(), progress)
        print(json.dumps(progress, ensure_ascii=False, indent=2))
        return 4
    progress["reviewed_smoke_shots_reused"] = list(reviewed_candidates)
    progress["shots_to_generate"] = [plan.scene_id for plan in generation_plans]

    if not mutating:
        progress["result"] = "FULL_BATCH_GATE_VALIDATION_PASSED"
        progress["updated_at"] = _now()
        _write_json(args.progress_path.resolve(), progress)
        print(json.dumps(progress, ensure_ascii=False, indent=2))
        return 0

    # Only after the frontend review, downstream source contract and full plan all
    # pass do we reserve any run artifact. Every mutating path is fresh and
    # names the same run ID, preventing stale or mixed-run asset reuse.
    try:
        _protect_full_progress(args.progress_path.resolve())
        _reserve_run_directories(args)
        try:
            _reserve_full_progress(
                args.progress_path.resolve(), args.render_attestation_receipt_path
            )
        except Exception:
            _cleanup_empty_run_directories(args)
            raise
        _write_json_new(args.certificate.resolve(), certificate)
    except (OSError, ValueError) as exc:
        _cleanup_empty_run_directories(args)
        progress["result"] = "FULL_RUN_RESERVATION_FAILED"
        progress["error"] = str(exc)
        if args.progress_path.resolve().is_file():
            _write_json(args.progress_path.resolve(), progress)
        print(json.dumps(progress, ensure_ascii=False, indent=2))
        return 2
    progress["review_certificate_sha256"] = smoke._sha256(args.certificate.resolve())
    _write_json(args.progress_path.resolve(), progress)

    audio_result = smoke._synthesize_performance_audio(
        scene_plans=generation_plans,
        emotion_config=smoke._emotion_config(),
        output_dir=str(args.audio_dir.resolve()),
        dry_run=False,
    )
    progress["audio_preparation"] = smoke._jsonable(audio_result)
    progress["gates"]["full_audio_prepared"] = bool(audio_result.get("success"))
    progress["updated_at"] = _now()
    _write_json(args.progress_path.resolve(), progress)
    if not audio_result.get("success"):
        progress["result"] = "FULL_AUDIO_PREPARATION_FAILED"
        _write_json(args.progress_path.resolve(), progress)
        print(json.dumps(progress, ensure_ascii=False, indent=2))
        return 5

    provider = smoke._provider(args.comfy_base_url, args.evidence_root)
    runtime_preflight = provider.preflight(generation_plans)
    progress["runtime_preflight"] = smoke._jsonable(runtime_preflight)
    progress["gates"]["full_runtime_preflight_passed"] = bool(runtime_preflight.ok)
    progress["updated_at"] = _now()
    _write_json(args.progress_path.resolve(), progress)
    if not runtime_preflight.ok:
        progress["result"] = "FULL_RUNTIME_PREFLIGHT_FAILED"
        _write_json(args.progress_path.resolve(), progress)
        print(json.dumps(progress, ensure_ascii=False, indent=2))
        return 6
    if not args.execute:
        progress["result"] = "FULL_AUDIO_AND_RUNTIME_PREFLIGHT_PASSED"
        _write_json(args.progress_path.resolve(), progress)
        print(json.dumps(progress, ensure_ascii=False, indent=2))
        return 0

    failed = False
    for position, plan in enumerate(all_plans, start=1):
        reviewed = reviewed_candidates.get(plan.scene_id)
        if reviewed is not None:
            reviewed_path = Path(str(reviewed.get("path") or "")).resolve()
            expected_sha = str(reviewed.get("sha256") or "").upper()
            if (
                not reviewed_path.is_file()
                or not expected_sha
                or smoke._sha256(reviewed_path) != expected_sha
            ):
                progress["result"] = "REUSED_SMOKE_CANDIDATE_INTEGRITY_FAILED"
                progress["error"] = f"Frontend-approved smoke candidate changed or is missing: {plan.scene_id}"
                progress["updated_at"] = _now()
                _write_json(args.progress_path.resolve(), progress)
                print(json.dumps(progress, ensure_ascii=False, indent=2))
                return 7
            progress["shots"].append({
                "position": position,
                "scene_id": plan.scene_id,
                "completed_at": _now(),
                "source": (
                    "frontend_human_approved_smoke_candidate"
                    if args.review_sequence == "smoke_then_full"
                    else "machine_verified_unreviewed_smoke_candidate"
                ),
                "assets": [{
                    "scene_id": plan.scene_id,
                    "video_path": str(reviewed_path),
                    "duration_s": reviewed["duration_seconds"],
                    "provider_name": reviewed.get("provider_name", "comfyui_ltx_i2v"),
                    "metadata": reviewed["metadata"],
                }],
                "missing": [],
            })
            continue
        result = provider.provide_scenes([plan], args.output_dir.resolve())
        item = {
            "position": position,
            "scene_id": plan.scene_id,
            "completed_at": _now(),
            "source": "new_full_batch_render",
            "assets": smoke._jsonable(result.assets),
            "missing": smoke._jsonable(result.missing),
        }
        progress["shots"].append(item)
        failed = failed or bool(result.missing) or not bool(result.assets)
        progress["updated_at"] = _now()
        _write_json(args.progress_path.resolve(), progress)

    rendered = not failed and len(progress["shots"]) == EXPECTED_BEAT_COUNT
    progress["gates"]["full_19_shots_rendered"] = rendered
    progress["result"] = (
        EXPECTED_RESULT
        if rendered else "FULL_19_SHOT_RENDER_FAILED"
    )
    progress["render_attestation_completed"] = rendered
    progress["finished_at"] = _now()
    progress["updated_at"] = _now()
    _write_json(args.progress_path.resolve(), progress)
    if rendered:
        receipt = _render_attestation_receipt(
            progress_path=args.progress_path.resolve(),
            receipt_path=args.render_attestation_receipt_path.resolve(),
            progress=progress,
            plan_path=args.plan.resolve(),
        )
        try:
            _write_json_new(args.render_attestation_receipt_path.resolve(), receipt)
        except (OSError, ValueError) as exc:
            print(json.dumps({
                "error": str(exc),
                "result": "RENDER_ATTESTATION_RECEIPT_WRITE_FAILED",
                "progress_path": str(args.progress_path.resolve()),
                "progress_sha256": smoke._sha256(args.progress_path.resolve()),
                "receipt_path": str(args.render_attestation_receipt_path.resolve()),
                "publish_allowed": False,
                "fanqie_backfill_allowed": False,
            }, ensure_ascii=False, indent=2))
            return 8
    print(json.dumps(progress, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
