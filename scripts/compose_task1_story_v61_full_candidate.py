from __future__ import annotations

"""Compose the immutable 19-beat V6.1 candidate after the full render gate.

This script has no database, browser, upload or backfill integration.  It only
turns a completed, hash-verified 19-shot progress record into a local candidate
that still requires a separate authenticated frontend whole-video review.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable


PROJECT_ROOT = Path(r"D:\IT\ai_douyin")
P0_ROOT = Path(r"D:\IT\ai_douyin_p0")
for root in (PROJECT_ROOT / "scripts", P0_ROOT):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

import run_task1_story_v61_failed_smoke as smoke  # noqa: E402
import validate_task1_story_v61_smoke_review as smoke_review_gate  # noqa: E402
import validate_task1_story_v61_full_batch_attestation as render_attestation_gate  # noqa: E402
from src.content_factory.story_video import compose_story_video  # noqa: E402
from src.novel_promotion.scene_provider import SceneAsset  # noqa: E402
from src.novel_promotion.video_generation_service import _build_manifest  # noqa: E402


PROGRESS_SCHEMA = "fanqie_v61_full_batch_progress/v2"
AUDIT_SCHEMA = "fanqie_v61_full_candidate_audit/v2"
EXECUTION_CONFIRMATION = "TASK1-V61-COMPOSE-FULL-CANDIDATE"
EXPECTED_RESULT = "FULL_19_SHOTS_RENDERED_AWAITING_ASSEMBLY_AND_HUMAN_REVIEW"
EXPECTED_SHOT_COUNT = 19
EXPECTED_DURATION = 40.8
DEFAULT_PROGRESS = PROJECT_ROOT / "data/qa/task1_story_v61_full_batch_progress.json"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "data/qa/task1_story_v61_full_candidate"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"JSON file not found: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _probe_video(path: Path) -> dict[str, Any]:
    result = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries",
        "stream=codec_type,avg_frame_rate,width,height,sample_rate,channels",
        "-show_entries", "format=duration", "-of", "json", str(path),
    ], capture_output=True, text=True, encoding="utf-8", errors="replace",
       check=False, timeout=60)
    if result.returncode != 0:
        raise ValueError(f"ffprobe rejected {path}: {result.stderr[-800:]}")
    try:
        payload = json.loads(result.stdout)
        streams = payload["streams"]
        video = next(item for item in streams if item.get("codec_type") == "video")
        audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
        numerator, denominator = str(video["avg_frame_rate"]).split("/", 1)
        return {
            "duration_seconds": float(payload["format"]["duration"]),
            "fps": float(numerator) / float(denominator),
            "width": int(video["width"]),
            "height": int(video["height"]),
            "audio_present": audio is not None,
            "audio_sample_rate": int(audio["sample_rate"]) if audio else None,
            "audio_channels": int(audio["channels"]) if audio else None,
        }
    except (KeyError, StopIteration, TypeError, ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"ffprobe returned invalid metadata for {path}") from exc


def _srt_time(seconds: float) -> str:
    milliseconds = int(round(seconds * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def _wrap_zh(text: str, width: int = 22) -> str:
    compact = "".join(text.split())
    return "\n".join(compact[index:index + width] for index in range(0, len(compact), width))


def _write_subtitles(path: Path, plans: list[Any]) -> None:
    cursor = 0.0
    blocks: list[str] = []
    subtitle_index = 1
    for plan in plans:
        duration = float(plan.estimated_duration_s)
        text = str(plan.metadata.get("dialogue") or plan.metadata.get("narration_text") or "").strip()
        if text:
            blocks.append(
                f"{subtitle_index}\n{_srt_time(cursor)} --> {_srt_time(cursor + duration)}\n"
                f"{_wrap_zh(text)}\n"
            )
            subtitle_index += 1
        cursor += duration
    path.write_text("\n".join(blocks), encoding="utf-8-sig")


def _burn_subtitles(raw_video: Path, subtitles: Path, output: Path) -> None:
    subtitle_filter = (
        f"subtitles={subtitles.name}:"
        "force_style='FontName=Microsoft YaHei,FontSize=13,"
        "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
        "BorderStyle=1,Outline=1.5,Shadow=0,Alignment=2,"
        "MarginL=30,MarginR=30,MarginV=45'"
    )
    result = subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(raw_video), "-vf", subtitle_filter,
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", "-r", "50",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart", str(output),
    ], cwd=str(subtitles.parent), capture_output=True, text=True, check=False,
       timeout=1800)
    if result.returncode != 0 or not output.is_file():
        raise ValueError(f"subtitle burn failed: {result.stderr[-1200:]}")


def _validate_progress(
    progress_path: Path,
    plan_path: Path,
    *,
    probe_video: Callable[[Path], dict[str, Any]],
    validate_smoke_review=smoke_review_gate.validate_review,
    validate_render_attestation=render_attestation_gate.validate_attestation,
) -> tuple[dict[str, Any], list[Any], list[SceneAsset], list[dict[str, Any]]]:
    progress = _load_json(progress_path)
    render_attestation = validate_render_attestation(progress_path)
    if render_attestation.get("accepted") is not True:
        raise ValueError("full-batch render attestation is not accepted")
    if str(render_attestation.get("progress_sha256") or "").upper() != _sha256(progress_path):
        raise ValueError("full-batch render attestation progress SHA mismatch")
    receipt_path = Path(
        str(render_attestation.get("attestation_receipt_path") or "")
    ).resolve()
    receipt_sha = str(
        render_attestation.get("attestation_receipt_sha256") or ""
    ).upper()
    if (
        render_attestation.get("attestation_receipt_schema")
        != render_attestation_gate.RECEIPT_SCHEMA
        or not receipt_path.is_file()
        or not receipt_sha
        or _sha256(receipt_path) != receipt_sha
    ):
        raise ValueError("full-batch render attestation receipt is invalid")
    progress["_validated_render_attestation"] = render_attestation
    if progress.get("schema_version") != PROGRESS_SCHEMA:
        raise ValueError("full-batch progress schema mismatch")
    if progress.get("task_id") != 1 or progress.get("scope") != "full_19_beat_render":
        raise ValueError("full-batch progress task/scope mismatch")
    if progress.get("result") != EXPECTED_RESULT:
        raise ValueError("progress does not prove 19 rendered shots")
    gates = progress.get("gates")
    if not isinstance(gates, dict):
        raise ValueError("full-batch gates are missing")
    for key in (
        "smoke_machine_gate_passed", "full_audio_prepared",
        "full_runtime_preflight_passed", "full_19_shots_rendered",
    ):
        if gates.get(key) is not True:
            raise ValueError(f"full-batch gate {key} is not true")
    review_sequence = str(progress.get("review_sequence") or "smoke_then_full")
    if review_sequence == "full_video_only":
        if gates.get("smoke_human_review_passed") is not False or gates.get("full_review_first_authorized") is not True:
            raise ValueError("full-review-first gate boundary mismatch")
    elif gates.get("smoke_human_review_passed") is not True:
        raise ValueError("full-batch gate smoke_human_review_passed is not true")
    for key in (
        "full_video_human_approval_obtained", "matching_fanqie_task_confirmed",
        "publish_allowed", "fanqie_backfill_allowed",
    ):
        if gates.get(key) is not False:
            raise ValueError(f"full-batch gate {key} must remain false")

    review_path = Path(str(progress.get("review_path") or "")).resolve()
    smoke_progress_path = Path(str(progress.get("smoke_progress_path") or "")).resolve()
    if review_sequence == "full_video_only":
        machine_path = Path(str(progress.get("smoke_machine_packet_path") or "")).resolve()
        machine_sha = str(progress.get("smoke_machine_packet_sha256") or "").upper()
        if not machine_path.is_file() or _sha256(machine_path) != machine_sha:
            raise ValueError("full-review-first smoke machine packet changed")
        machine = _load_json(machine_path)
        raw_candidates = machine.get("candidates")
        if (
            machine.get("schema_version") != "fanqie_v61_smoke_machine_review_packet/v2"
            or machine.get("machine_gate_passed") is not True
            or not isinstance(raw_candidates, list)
        ):
            raise ValueError("full-review-first smoke machine packet is invalid")
        smoke_certificate = {
            "review_path": str(review_path),
            "review_sha256": _sha256(review_path),
            "progress_path": str(smoke_progress_path),
            "progress_sha256": _sha256(smoke_progress_path),
            "machine_packet_path": str(machine_path),
            "machine_packet_sha256": machine_sha,
            "candidates": [
                {"scene_id": item.get("scene_id"), "path": item.get("video_path"),
                 "sha256": item.get("video_sha256")}
                for item in raw_candidates if isinstance(item, dict)
            ],
        }
    else:
        smoke_certificate = validate_smoke_review(
            review_path, progress_path=smoke_progress_path
        )
    progress["_revalidated_smoke_review"] = smoke_certificate
    reviewed_by_id = {
        item["scene_id"]: item for item in smoke_certificate.get("candidates", [])
    }
    if len(reviewed_by_id) != 7:
        raise ValueError("frontend smoke review must contain exactly seven candidates")

    plans = smoke._load_structured_scene_plan(str(plan_path), "")
    if len(plans) != EXPECTED_SHOT_COUNT or _sha256(plan_path) != smoke.EXPECTED_PLAN_SHA256:
        raise ValueError("V6.1 plan count or SHA mismatch")
    shots = progress.get("shots")
    if not isinstance(shots, list) or len(shots) != EXPECTED_SHOT_COUNT:
        raise ValueError("progress must contain exactly 19 shots")
    if tuple(item.get("scene_id") for item in shots if isinstance(item, dict)) != tuple(
        plan.scene_id for plan in plans
    ):
        raise ValueError("progress shot order does not match the V6.1 plan")

    assets: list[SceneAsset] = []
    evidence: list[dict[str, Any]] = []
    spoken_renderers: set[str] = set()
    for plan, shot in zip(plans, shots, strict=True):
        if shot.get("missing"):
            raise ValueError(f"{plan.scene_id}: progress contains missing capabilities")
        raw_assets = shot.get("assets")
        if not isinstance(raw_assets, list) or len(raw_assets) != 1:
            raise ValueError(f"{plan.scene_id}: progress must contain one asset")
        raw = raw_assets[0]
        if not isinstance(raw, dict) or raw.get("scene_id") != plan.scene_id:
            raise ValueError(f"{plan.scene_id}: asset identity mismatch")
        video = Path(str(raw.get("video_path") or "")).resolve()
        if not video.is_file():
            raise ValueError(f"{plan.scene_id}: video file is missing")
        metadata = raw.get("metadata")
        if not isinstance(metadata, dict):
            raise ValueError(f"{plan.scene_id}: asset metadata is missing")
        video_sha = _sha256(video)
        if video_sha != str(metadata.get("final_sha256") or "").upper():
            raise ValueError(f"{plan.scene_id}: final video SHA mismatch")
        probe = probe_video(video)
        if _sha256(video) != video_sha:
            raise ValueError(f"{plan.scene_id}: video changed during probe")
        duration = float(probe["duration_seconds"])
        fps = float(probe["fps"])
        if abs(duration - float(plan.estimated_duration_s)) > 0.12:
            raise ValueError(f"{plan.scene_id}: duration outside +/-0.12s")
        if abs(fps - 50.0) > 0.01:
            raise ValueError(f"{plan.scene_id}: fps must be 50")
        if metadata.get("has_presenter") is not False:
            raise ValueError(f"{plan.scene_id}: has_presenter must be false")
        source = str(shot.get("source") or "")
        if plan.scene_id in reviewed_by_id:
            reviewed = reviewed_by_id[plan.scene_id]
            expected_reused_source = (
                "machine_verified_unreviewed_smoke_candidate"
                if review_sequence == "full_video_only"
                else "frontend_human_approved_smoke_candidate"
            )
            if source != expected_reused_source:
                raise ValueError(f"{plan.scene_id}: smoke candidate source mismatch")
            if video != Path(str(reviewed.get("path") or "")).resolve():
                raise ValueError(f"{plan.scene_id}: reused candidate path differs from frontend smoke review")
            if video_sha != str(reviewed.get("sha256") or "").upper():
                raise ValueError(f"{plan.scene_id}: reused candidate SHA differs from frontend smoke review")
        elif source != "new_full_batch_render":
            raise ValueError(f"{plan.scene_id}: unrecognized full-batch source")
        spoken = bool(plan.metadata.get("spoken_closeup"))
        if spoken:
            renderer = str(metadata.get("spoken_renderer") or "")
            legacy_musetalk = metadata.get("musetalk_used") is True
            sadtalker = (
                renderer == "sadtalker_fullframe"
                and metadata.get("spoken_renderer_used") is True
                and metadata.get("sadtalker_fullframe_used") is True
                and metadata.get("musetalk_used") is False
            )
            if not (legacy_musetalk or sadtalker):
                raise ValueError(
                    f"{plan.scene_id}: spoken shot lacks approved renderer evidence"
                )
            if sadtalker:
                spoken_renderers.add("sadtalker_fullframe")
                renderer_path = Path(
                    str(metadata.get("spoken_renderer_artifact_path") or "")
                ).resolve()
                renderer_sha = str(
                    metadata.get("spoken_renderer_sha256") or ""
                ).upper()
                audit_path = Path(
                    str(metadata.get("spoken_renderer_audit_path") or "")
                ).resolve()
                audit_sha = str(
                    metadata.get("spoken_renderer_audit_sha256") or ""
                ).upper()
                if (
                    not renderer_path.is_file()
                    or _sha256(renderer_path) != renderer_sha
                    or not audit_path.is_file()
                    or _sha256(audit_path) != audit_sha
                ):
                    raise ValueError(
                        f"{plan.scene_id}: SadTalker full-frame provenance changed"
                    )
                rife_binding_path = Path(
                    str(metadata.get("rife_binding_path") or "")
                ).resolve()
                rife_binding_sha = str(
                    metadata.get("rife_binding_sha256") or ""
                ).upper()
                if (
                    not rife_binding_path.is_file()
                    or _sha256(rife_binding_path) != rife_binding_sha
                ):
                    raise ValueError(
                        f"{plan.scene_id}: RIFE source/output binding changed"
                    )
                rife_binding = _load_json(rife_binding_path)
                if (
                    rife_binding.get("schema")
                    != "fanqie_sadtalker_fullframe/rife_binding/v1"
                    or str(rife_binding.get("source_sha256") or "").upper()
                    != renderer_sha
                    or str(rife_binding.get("output_sha256") or "").upper()
                    != video_sha
                    or not str(rife_binding.get("rife_model") or "").strip()
                    or not isinstance(rife_binding.get("rife_multiplier"), int)
                    or rife_binding["rife_multiplier"] <= 0
                    or rife_binding.get("delivery_fps") != 50
                ):
                    raise ValueError(
                        f"{plan.scene_id}: RIFE source/output binding contract failed"
                    )
                per_stage = metadata.get("per_stage_sha256")
                if (
                    not isinstance(per_stage, dict)
                    or str(per_stage.get("rife_binding_sha256") or "").upper()
                    != rife_binding_sha
                ):
                    raise ValueError(
                        f"{plan.scene_id}: RIFE binding is absent from per-stage evidence"
                    )
            else:
                spoken_renderers.add("musetalk_v15")
        audio = Path(str(metadata.get("dialogue_audio_path") or "")).resolve()
        if not audio.is_file():
            raise ValueError(f"{plan.scene_id}: explicit audio file is missing")
        audio_sha = _sha256(audio)
        declared_audio_sha = str(metadata.get("dialogue_audio_sha256") or "").upper()
        if audio_sha != declared_audio_sha:
            raise ValueError(f"{plan.scene_id}: explicit audio SHA mismatch")
        plan.metadata["dialogue_audio_path"] = str(audio)
        if not spoken:
            plan.metadata["is_silence"] = True
        assets.append(SceneAsset(
            scene_id=plan.scene_id,
            video_path=str(video),
            duration_s=duration,
            provider_name=str(raw.get("provider_name") or ""),
            metadata=metadata,
        ))
        evidence.append({
            "position": len(evidence) + 1,
            "scene_id": plan.scene_id,
            "source": shot.get("source"),
            "video_path": str(video),
            "video_sha256": video_sha,
            "duration_seconds": round(duration, 4),
            "fps": round(fps, 4),
            "audio_path": str(audio),
            "audio_sha256": audio_sha,
            "spoken_closeup": spoken,
            "spoken_renderer": (
                "sadtalker_fullframe" if spoken and sadtalker
                else "musetalk_v15" if spoken else ""
            ),
        })
    progress["_spoken_renderers"] = sorted(spoken_renderers)
    return progress, plans, assets, evidence


def compose_candidate(
    *,
    progress_path: Path,
    plan_path: Path,
    output_root: Path,
    probe_video=_probe_video,
    composer=compose_story_video,
    subtitle_burner=_burn_subtitles,
    validate_smoke_review=smoke_review_gate.validate_review,
    validate_render_attestation=render_attestation_gate.validate_attestation,
) -> dict[str, Any]:
    if output_root.exists():
        raise ValueError(f"Refusing to overwrite full candidate evidence: {output_root}")
    progress, plans, assets, shot_evidence = _validate_progress(
        progress_path, plan_path, probe_video=probe_video,
        validate_smoke_review=validate_smoke_review,
        validate_render_attestation=validate_render_attestation,
    )
    output_root.parent.mkdir(parents=True, exist_ok=True)
    try:
        output_root.mkdir(exist_ok=False)
    except FileExistsError as exc:
        raise ValueError(f"Full candidate output is already reserved: {output_root}") from exc
    staging = output_root / f".{uuid.uuid4().hex}.staging"
    try:
        manifest = _build_manifest(
            title="番茄推书真人剧情 V6.1 待审核",
            scene_plans=plans,
            assets=assets,
            script=SimpleNamespace(generation_params_json={}),
            emotion_voice_config=smoke._emotion_config(),
        )
        manifest["output_fps"] = 50
        spoken_renderers = progress.get("_spoken_renderers")
        if not isinstance(spoken_renderers, list) or len(spoken_renderers) != 1:
            raise ValueError("full candidate must use exactly one spoken renderer provenance")
        manifest["responsibilities"] = {
            "visuals": "comfyui_ltx_i2v",
            "spoken_closeups": spoken_renderers[0],
            "interpolation": "rife_50fps",
            "audio": "audited_explicit_audio_paths_no_tts_fallback",
            "approval": "authenticated_frontend_whole_video_review_required",
        }
        if any(
            not isinstance(scene.get("lines"), list)
            or not scene["lines"]
            or any(not line.get("audio_path") for line in scene["lines"])
            for scene in manifest["scenes"]
        ):
            raise ValueError("story manifest contains a line without explicit audio")
        staging.mkdir(parents=True)
        manifest_path = staging / "story_manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        raw_video = staging / "candidate_raw.mp4"
        composer(manifest_path, raw_video)
        subtitle_path = staging / "candidate.srt"
        _write_subtitles(subtitle_path, plans)
        candidate = staging / "candidate.mp4"
        subtitle_burner(raw_video, subtitle_path, candidate)
        for item in shot_evidence:
            if _sha256(Path(item["video_path"])) != item["video_sha256"]:
                raise ValueError(f"{item['scene_id']}: source video changed during composition")
            if _sha256(Path(item["audio_path"])) != item["audio_sha256"]:
                raise ValueError(f"{item['scene_id']}: source audio changed during composition")
        render_attestation = progress["_validated_render_attestation"]
        receipt_path = Path(
            str(render_attestation.get("attestation_receipt_path") or "")
        ).resolve()
        if _sha256(progress_path) != str(
            render_attestation.get("progress_sha256") or ""
        ).upper():
            raise ValueError("full-batch progress changed during composition")
        if _sha256(receipt_path) != str(
            render_attestation.get("attestation_receipt_sha256") or ""
        ).upper():
            raise ValueError("render attestation receipt changed during composition")
        if _sha256(plan_path) != str(
            render_attestation.get("plan_sha256") or ""
        ).upper():
            raise ValueError("V6.1 plan changed during composition")
        probe = probe_video(candidate)
        candidate_sha = _sha256(candidate)
        if abs(float(probe["duration_seconds"]) - EXPECTED_DURATION) > 0.30:
            raise ValueError("full candidate duration outside 40.8s +/-0.30s")
        if abs(float(probe["fps"]) - 50.0) > 0.01:
            raise ValueError("full candidate fps must be 50")
        if probe.get("audio_present") is not True:
            raise ValueError("full candidate must contain audio")
        audit = {
            "schema_version": AUDIT_SCHEMA,
            "task_id": 1,
            "scope": "full_19_beat_candidate",
            "review_sequence": str(progress.get("review_sequence") or "smoke_then_full"),
            "smoke_human_review_claimed": (
                str(progress.get("review_sequence") or "smoke_then_full") != "full_video_only"
            ),
            "plan_path": str(plan_path.resolve()),
            "plan_sha256": str(render_attestation.get("plan_sha256") or "").upper(),
            "source_progress_path": str(progress_path.resolve()),
            "source_progress_sha256": str(
                render_attestation.get("progress_sha256") or ""
            ).upper(),
            "render_attestation_signer_id": str(
                render_attestation.get("signer_id") or ""
            ),
            "render_attestation_receipt_schema": str(
                render_attestation.get("attestation_receipt_schema") or ""
            ),
            "render_attestation_receipt_path": str(
                render_attestation.get("attestation_receipt_path") or ""
            ),
            "render_attestation_receipt_sha256": str(
                render_attestation.get("attestation_receipt_sha256") or ""
            ).upper(),
            "smoke_review_certificate_sha256": progress.get("review_certificate_sha256"),
            "smoke_review_path": str(
                Path(str(progress["_revalidated_smoke_review"]["review_path"])).resolve()
            ),
            "smoke_review_sha256": str(
                progress["_revalidated_smoke_review"]["review_sha256"]
            ).upper(),
            "smoke_progress_path": str(
                Path(str(progress["_revalidated_smoke_review"]["progress_path"])).resolve()
            ),
            "smoke_progress_sha256": str(
                progress["_revalidated_smoke_review"]["progress_sha256"]
            ).upper(),
            "smoke_review_candidates": [
                {
                    "scene_id": item["scene_id"],
                    "path": str(Path(str(item["path"])).resolve()),
                    "sha256": str(item["sha256"]).upper(),
                }
                for item in progress["_revalidated_smoke_review"]["candidates"]
            ],
            "smoke_machine_packet_path": str(
                progress["_revalidated_smoke_review"].get("machine_packet_path") or ""
            ),
            "smoke_machine_packet_sha256": str(
                progress["_revalidated_smoke_review"].get("machine_packet_sha256") or ""
            ).upper(),
            "shot_count": len(shot_evidence),
            "shots": shot_evidence,
            "story_manifest_path": str((output_root / "story_manifest.json").resolve()),
            "story_manifest_sha256": _sha256(manifest_path),
            "subtitle_path": str((output_root / "candidate.srt").resolve()),
            "subtitle_sha256": _sha256(subtitle_path),
            "candidate_path": str((output_root / "candidate.mp4").resolve()),
            "candidate_sha256": candidate_sha,
            "probe": probe,
            "machine_composition_gate_passed": True,
            "human_full_video_review_completed": False,
            "matching_fanqie_task_confirmed": False,
            "douyin_upload_allowed": False,
            "fanqie_backfill_allowed": False,
        }
        (staging / "candidate_audit.json").write_text(
            json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        for artifact in staging.iterdir():
            artifact.replace(output_root / artifact.name)
        staging.rmdir()
        return {
            **audit,
            "candidate_audit_path": str((output_root / "candidate_audit.json").resolve()),
            "candidate_audit_sha256": _sha256(output_root / "candidate_audit.json"),
        }
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        if output_root.exists() and not any(output_root.iterdir()):
            output_root.rmdir()
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compose task-1 V6.1 full review candidate.")
    parser.add_argument("--progress", type=Path, default=DEFAULT_PROGRESS)
    parser.add_argument("--plan", type=Path, default=smoke.PLAN_PATH)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-execution", default="")
    args = parser.parse_args(argv)
    try:
        if not args.execute:
            progress, plans, _, evidence = _validate_progress(
                args.progress.resolve(), args.plan.resolve(), probe_video=_probe_video
            )
            result = {
                "success": True, "result": "FULL_COMPOSITION_GATE_VALIDATED",
                "source_progress_sha256": _sha256(args.progress.resolve()),
                "shot_count": len(plans), "evidence_count": len(evidence),
                "human_full_video_review_completed": False,
                "douyin_upload_allowed": False, "fanqie_backfill_allowed": False,
            }
        else:
            if args.confirm_execution != EXECUTION_CONFIRMATION:
                raise ValueError(f"confirmation must equal {EXECUTION_CONFIRMATION}")
            result = {"success": True, **compose_candidate(
                progress_path=args.progress.resolve(), plan_path=args.plan.resolve(),
                output_root=args.output_root.resolve(),
            )}
    except ValueError as exc:
        print(json.dumps({
            "success": False, "error": str(exc),
            "human_full_video_review_completed": False,
            "douyin_upload_allowed": False, "fanqie_backfill_allowed": False,
        }, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
