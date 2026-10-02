from __future__ import annotations

"""Create machine evidence and a pending frontend review for seven smoke clips.

Machine-observed paths, hashes, duration, fps and frames are populated. Human
judgments remain null/pending. Existing packet or review artifacts
are never overwritten.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(r"D:\IT\ai_douyin")
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import validate_task1_story_v61_smoke_review as gate  # noqa: E402


PACKET_SCHEMA = "fanqie_v61_smoke_machine_review_packet/v2"
DEFAULT_PROGRESS = PROJECT_ROOT / "data/qa/task1_story_v61_failed_smoke_progress.json"
DEFAULT_TEMPLATE = PROJECT_ROOT / "data/qa/task1_story_v61_failed_smoke_review_template.json"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "data/qa/task1_story_v61_smoke_review_packet"
DEFAULT_REVIEW = PROJECT_ROOT / "data/qa/task1_story_v61_failed_smoke_review.json"
FRAME_FRACTIONS = (0.15, 0.50, 0.85)
REVIEW_TOP_LEVEL_KEYS = {
    "schema_version", "task_id", "scope", "plan_sha256", "review_status",
    "reviewer", "reviewer_id", "reviewed_at",
    "source_progress_path", "reviewed_progress_sha256",
    "machine_review_packet_path", "machine_review_packet_sha256",
    "candidate_contact_sheet", "candidate_contact_sheet_sha256",
    "global_gates", "shots", "approval_contract",
}
REVIEW_SHOT_KEYS = {
    "scene_id", "expected_duration_seconds", "candidate_path",
    "candidate_sha256", "machine_observed_duration_seconds",
    "machine_observed_fps", *gate.SHOT_REVIEW_CHECKS, "decision", "notes",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _spoken_renderer_evidence(metadata: dict[str, Any], scene_id: str) -> dict[str, str]:
    """Normalize reviewed spoken-renderer provenance without hiding its engine."""
    renderer = str(metadata.get("spoken_renderer") or "").strip()
    if renderer == "sadtalker_fullframe":
        if metadata.get("spoken_renderer_used") is not True:
            raise ValueError(f"{scene_id}: SadTalker full-frame renderer was not recorded")
        if metadata.get("sadtalker_fullframe_used") is not True:
            raise ValueError(f"{scene_id}: SadTalker full-frame provenance flag is missing")
        if metadata.get("musetalk_used") is not False:
            raise ValueError(f"{scene_id}: MuseTalk must not be claimed for SadTalker output")
        artifact_path = Path(
            str(metadata.get("spoken_renderer_artifact_path") or "")
        ).resolve()
        artifact_sha = str(metadata.get("spoken_renderer_sha256") or "").upper()
        audit_path = Path(
            str(metadata.get("spoken_renderer_audit_path") or "")
        ).resolve()
        audit_sha = str(metadata.get("spoken_renderer_audit_sha256") or "").upper()
        for label, path, sha in (
            ("artifact", artifact_path, artifact_sha),
            ("audit", audit_path, audit_sha),
        ):
            if not path.is_file() or len(sha) != 64 or _sha256(path) != sha:
                raise ValueError(f"{scene_id}: spoken renderer {label} evidence is invalid")
        return {
            "renderer": renderer,
            "artifact_path": str(artifact_path),
            "artifact_sha256": artifact_sha,
            "audit_path": str(audit_path),
            "audit_sha256": audit_sha,
        }
    if metadata.get("musetalk_used") is True:
        artifact_path = Path(str(metadata.get("musetalk_artifact_path") or "")).resolve()
        artifact_sha = str(metadata.get("musetalk_sha256") or "").upper()
        if not artifact_path.is_file() or len(artifact_sha) != 64 or _sha256(artifact_path) != artifact_sha:
            raise ValueError(f"{scene_id}: MuseTalk stage artifact SHA mismatch")
        return {
            "renderer": "musetalk_v15",
            "artifact_path": str(artifact_path),
            "artifact_sha256": artifact_sha,
            "audit_path": "",
            "audit_sha256": "",
        }
    raise ValueError(
        f"{scene_id}: MuseTalk must be used or SadTalker full-frame evidence supplied"
    )


def _rife_binding_evidence(
    metadata: dict[str, Any], spoken: dict[str, str], final_sha: str, scene_id: str,
) -> dict[str, str]:
    if spoken["renderer"] != "sadtalker_fullframe":
        return {"path": "", "sha256": ""}
    path = Path(str(metadata.get("rife_binding_path") or "")).resolve()
    declared_sha = str(metadata.get("rife_binding_sha256") or "").upper()
    if not path.is_file() or len(declared_sha) != 64 or _sha256(path) != declared_sha:
        raise ValueError(f"{scene_id}: RIFE source/output binding evidence is invalid")
    value = _load_json(path)
    if (
        value.get("schema") != "fanqie_sadtalker_fullframe/rife_binding/v1"
        or str(value.get("source_sha256") or "").upper() != spoken["artifact_sha256"]
        or str(value.get("output_sha256") or "").upper() != final_sha
        or not str(value.get("rife_model") or "").strip()
        or not isinstance(value.get("rife_multiplier"), int)
        or value["rife_multiplier"] <= 0
        or value.get("delivery_fps") != 50
    ):
        raise ValueError(f"{scene_id}: RIFE source/output binding contract failed")
    return {"path": str(path), "sha256": declared_sha}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"JSON file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid JSON {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return data


def _write_json_new(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
    except FileExistsError as exc:
        raise ValueError(f"Refusing to overwrite existing evidence: {path}") from exc


def _publish_packet_and_review(
    *, staging_root: Path, output_root: Path,
    staged_review_path: Path, review_path: Path,
) -> None:
    """Publish the complete packet and an exclusive review hard-link or roll back."""
    review_path.parent.mkdir(parents=True, exist_ok=True)
    staging_root.replace(output_root)
    canonical_review = output_root / staged_review_path.name
    try:
        os.link(canonical_review, review_path)
    except FileExistsError as exc:
        shutil.rmtree(output_root)
        raise ValueError(
            f"Refusing to overwrite existing evidence: {review_path}"
        ) from exc
    except OSError:
        # output_root belongs to this invocation: it was absent at entry and
        # was created by the immediately preceding exclusive rename.
        shutil.rmtree(output_root)
        raise


def _extract_frame(video: Path, output: Path, timestamp: float) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{timestamp:.6f}", "-i", str(video),
        "-frames:v", "1", "-update", "1", str(output),
    ], capture_output=True, text=True, check=False, timeout=60)
    if result.returncode != 0 or not output.is_file():
        raise ValueError(
            f"Frame extraction failed for {video} at {timestamp:.3f}s: "
            f"{result.stderr[-800:]}"
        )


def _fit(image: Image.Image, width: int, height: int) -> Image.Image:
    canvas = Image.new("RGB", (width, height), "#161616")
    thumbnail = image.convert("RGB")
    thumbnail.thumbnail((width, height), Image.Resampling.LANCZOS)
    canvas.paste(thumbnail, ((width - thumbnail.width) // 2, (height - thumbnail.height) // 2))
    return canvas


def _contact_sheet(items: list[tuple[str, Path]], output: Path) -> None:
    columns, width, height, label_height = 3, 320, 568, 42
    rows = (len(items) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * width, rows * (height + label_height)), "black")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=17)
    for index, (label, image_path) in enumerate(items):
        with Image.open(image_path) as source:
            image = _fit(source, width, height)
        column, row = index % columns, index // columns
        x, y = column * width, row * (height + label_height)
        sheet.paste(image, (x, y))
        draw.text((x + 8, y + height + 10), label, fill="white", font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.stem}.{uuid.uuid4().hex}.png")
    sheet.save(temporary)
    temporary.replace(output)


def _validate_progress(progress: dict[str, Any]) -> list[dict[str, Any]]:
    if progress.get("schema_version") != gate.PROGRESS_SCHEMA:
        raise ValueError("progress schema mismatch")
    if progress.get("task_id") != 1 or progress.get("scope") != "failed_scene_smoke":
        raise ValueError("progress task/scope mismatch")
    if str(progress.get("expected_plan_sha256") or "").upper() != gate.EXPECTED_PLAN_SHA256:
        raise ValueError("progress plan SHA mismatch")
    if tuple(progress.get("selected_shot_ids") or ()) != gate.SHOT_IDS:
        raise ValueError("progress must contain the exact seven-shot boundary")
    if progress.get("result") != "FAILED_SCENE_SMOKE_RENDERED_AWAITING_HUMAN_REVIEW":
        raise ValueError("progress does not prove a completed smoke render")
    gates = progress.get("gates")
    if not isinstance(gates, dict):
        raise ValueError("progress gates missing")
    for key in (
        "static_validation_passed", "audio_prepared",
        "runtime_preflight_passed", "failed_scene_smoke_rendered",
    ):
        if gates.get(key) is not True:
            raise ValueError(f"progress machine gate {key} is not true")
    for key in (
        "human_video_approval_obtained", "matching_fanqie_task_confirmed",
        "publish_allowed", "fanqie_backfill_allowed",
    ):
        if gates.get(key) is not False:
            raise ValueError(f"progress platform gate {key} must remain false")
    shots = progress.get("shots")
    if not isinstance(shots, list) or len(shots) != len(gate.SHOT_IDS):
        raise ValueError("progress must contain exactly seven shot results")
    if tuple(item.get("scene_id") for item in shots if isinstance(item, dict)) != gate.SHOT_IDS:
        raise ValueError("progress shot order mismatch")
    return shots


def _clean_review_template(template: dict[str, Any]) -> dict[str, Any]:
    """Return a fail-closed unsigned draft with no inherited approval fields."""
    unknown_top_level = set(template) - REVIEW_TOP_LEVEL_KEYS
    if unknown_top_level:
        raise ValueError(
            "human-review template contains unrecognized fields: "
            + ", ".join(sorted(unknown_top_level))
        )
    global_gates = template.get("global_gates")
    if not isinstance(global_gates, dict) or set(global_gates) != set(gate.GLOBAL_REVIEW_CHECKS):
        raise ValueError("human-review template global gate schema mismatch")
    clean_shots: list[dict[str, Any]] = []
    shots = template.get("shots")
    if not isinstance(shots, list):
        raise ValueError("human-review template shots must be a list")
    for source in shots:
        if not isinstance(source, dict) or set(source) - REVIEW_SHOT_KEYS:
            raise ValueError("human-review template shot schema mismatch")
        scene_id = str(source.get("scene_id") or "")
        if scene_id not in gate.SHOT_DURATIONS:
            raise ValueError("human-review template contains an unexpected shot")
        clean_shots.append({
            "scene_id": scene_id,
            "expected_duration_seconds": gate.SHOT_DURATIONS[scene_id],
            "candidate_path": "",
            "candidate_sha256": "",
            "machine_observed_duration_seconds": None,
            "machine_observed_fps": None,
            **{key: None for key in gate.SHOT_REVIEW_CHECKS},
            "decision": "pending",
            "notes": "",
        })
    if tuple(item["scene_id"] for item in clean_shots) != gate.SHOT_IDS:
        raise ValueError("human-review template shot order mismatch")
    return {
        "schema_version": gate.SCHEMA,
        "task_id": 1,
        "scope": "failed_scene_smoke",
        "plan_sha256": gate.EXPECTED_PLAN_SHA256,
        "review_status": "pending_review",
        "reviewer": "",
        "reviewer_id": "",
        "reviewed_at": None,
        "source_progress_path": "",
        "reviewed_progress_sha256": "",
        "machine_review_packet_path": "",
        "machine_review_packet_sha256": "",
        "candidate_contact_sheet": "",
        "candidate_contact_sheet_sha256": "",
        "global_gates": {
            key: False if key == "approved_for_full_video_generation" else None
            for key in gate.GLOBAL_REVIEW_CHECKS
        },
        "shots": clean_shots,
    }


def _prepare_packet(
    *,
    progress_path: Path,
    template_path: Path,
    output_root: Path,
    review_path: Path,
    probe_video=gate._probe_video,
    extract_frame=_extract_frame,
    build_contact_sheet=_contact_sheet,
    staging_root: Path | None = None,
) -> dict[str, Any]:
    packet_path = output_root / "machine_review_packet.json"
    contact_path = output_root / "contact_sheet.png"
    existing = [
        str(path) for path in (output_root, review_path)
        if path.exists()
    ]
    if existing:
        raise ValueError(
            "Refusing to overwrite an existing review artifact: " + ", ".join(existing)
        )

    progress = _load_json(progress_path)
    progress_sha = _sha256(progress_path)
    progress_shots = _validate_progress(progress)
    source_template = _load_json(template_path)
    if source_template.get("schema_version") != gate.SCHEMA:
        raise ValueError("human-review template schema mismatch")
    template = _clean_review_template(source_template)
    review_by_id = {
        item.get("scene_id"): item
        for item in template.get("shots", []) if isinstance(item, dict)
    }
    if set(review_by_id) != set(gate.SHOT_IDS):
        raise ValueError("human-review template shot boundary mismatch")

    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging_root = staging_root or (
        output_root.parent / f".{output_root.name}.{uuid.uuid4().hex}.staging"
    )
    staging_contact_path = staging_root / "contact_sheet.png"
    candidates: list[dict[str, Any]] = []
    contact_items: list[tuple[str, Path]] = []
    for progress_shot in progress_shots:
        scene_id = progress_shot["scene_id"]
        asset = gate._single_progress_asset(progress_shot, scene_id)
        video = Path(str(asset.get("video_path") or "")).resolve()
        if not video.is_file():
            raise ValueError(f"{scene_id}: candidate video missing")
        pre_sha = _sha256(video)
        metadata = asset.get("metadata")
        if not isinstance(metadata, dict):
            raise ValueError(f"{scene_id}: asset metadata missing")
        if pre_sha != str(metadata.get("final_sha256") or "").upper():
            raise ValueError(f"{scene_id}: candidate SHA mismatch")
        if metadata.get("has_presenter") is not False:
            raise ValueError(f"{scene_id}: has_presenter must be false")
        spoken_evidence = _spoken_renderer_evidence(metadata, scene_id)
        rife_binding = _rife_binding_evidence(
            metadata, spoken_evidence, pre_sha, scene_id
        )
        dialogue_sha = str(metadata.get("dialogue_audio_sha256") or "").upper()
        if len(dialogue_sha) != 64 or any(
            character not in "0123456789ABCDEF" for character in dialogue_sha
        ):
            raise ValueError(f"{scene_id}: dialogue audio SHA is invalid")
        dialogue_audio_path = Path(
            str(metadata.get("dialogue_audio_path") or "")
        ).resolve()
        if not dialogue_audio_path.is_file():
            raise ValueError(f"{scene_id}: dialogue audio file is missing")
        if _sha256(dialogue_audio_path) != dialogue_sha:
            raise ValueError(f"{scene_id}: dialogue audio file SHA mismatch")
        per_stage = metadata.get("per_stage_sha256")
        if not isinstance(per_stage, dict):
            raise ValueError(f"{scene_id}: per-stage SHA evidence is missing")
        if str(per_stage.get("dialogue_audio_sha256") or "").upper() != dialogue_sha:
            raise ValueError(f"{scene_id}: per-stage dialogue SHA mismatch")
        stage_key = (
            "musetalk_sha256"
            if spoken_evidence["renderer"] == "musetalk_v15"
            else "spoken_renderer_sha256"
        )
        if str(per_stage.get(stage_key) or "").upper() != spoken_evidence["artifact_sha256"]:
            raise ValueError(f"{scene_id}: per-stage spoken renderer SHA mismatch")
        if spoken_evidence["audit_sha256"] and str(
            per_stage.get("spoken_renderer_audit_sha256") or ""
        ).upper() != spoken_evidence["audit_sha256"]:
            raise ValueError(f"{scene_id}: per-stage spoken renderer audit SHA mismatch")
        if rife_binding["sha256"] and str(
            per_stage.get("rife_binding_sha256") or ""
        ).upper() != rife_binding["sha256"]:
            raise ValueError(f"{scene_id}: per-stage RIFE binding SHA mismatch")
        if str(per_stage.get("rife_sha256") or "").upper() != pre_sha:
            raise ValueError(f"{scene_id}: per-stage RIFE SHA mismatch")
        try:
            recorded_fps = float(metadata.get("rife_fps"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{scene_id}: recorded RIFE fps is invalid") from exc
        if abs(recorded_fps - 50.0) > 0.01:
            raise ValueError(f"{scene_id}: recorded RIFE fps must be 50")
        probed = probe_video(video)
        if _sha256(video) != pre_sha:
            raise ValueError(f"{scene_id}: candidate changed during probe")
        duration, fps = float(probed["duration_seconds"]), float(probed["fps"])
        if abs(duration - gate.SHOT_DURATIONS[scene_id]) > 0.12:
            raise ValueError(f"{scene_id}: duration outside ±0.12s")
        if abs(fps - 50.0) > 0.01:
            raise ValueError(f"{scene_id}: delivery fps must be 50")

        frames: list[dict[str, Any]] = []
        for position, fraction in enumerate(FRAME_FRACTIONS, start=1):
            timestamp = max(0.0, min(duration - 0.02, duration * fraction))
            relative_frame_path = Path("frames") / f"{scene_id}_{position}.png"
            staging_frame_path = staging_root / relative_frame_path
            final_frame_path = output_root / relative_frame_path
            extract_frame(video, staging_frame_path, timestamp)
            frames.append({
                "position": position,
                "fraction": fraction,
                "timestamp_seconds": round(timestamp, 4),
                "path": str(final_frame_path.resolve()),
                "sha256": _sha256(staging_frame_path),
            })
            contact_items.append((f"{scene_id} {timestamp:.2f}s", staging_frame_path))

        candidates.append({
            "scene_id": scene_id,
            "video_path": str(video),
            "video_sha256": pre_sha,
            "duration_seconds": round(duration, 4),
            "fps": round(fps, 4),
            "provider_name": str(asset.get("provider_name") or ""),
            "has_presenter": False,
            "spoken_renderer": spoken_evidence["renderer"],
            "spoken_renderer_artifact_path": spoken_evidence["artifact_path"],
            "spoken_renderer_sha256": spoken_evidence["artifact_sha256"],
            "spoken_renderer_audit_path": spoken_evidence["audit_path"],
            "spoken_renderer_audit_sha256": spoken_evidence["audit_sha256"],
            "rife_binding_path": rife_binding["path"],
            "rife_binding_sha256": rife_binding["sha256"],
            "dialogue_audio_sha256": dialogue_sha,
            "dialogue_audio_path": str(dialogue_audio_path),
            "rife_fps": round(recorded_fps, 4),
            "frames": frames,
        })
        review_shot = review_by_id[scene_id]
        review_shot["candidate_path"] = str(video)
        review_shot["candidate_sha256"] = pre_sha
        review_shot["machine_observed_duration_seconds"] = round(duration, 4)
        review_shot["machine_observed_fps"] = round(fps, 4)

    build_contact_sheet(contact_items, staging_contact_path)
    contact_sha = _sha256(staging_contact_path)
    for candidate in candidates:
        if _sha256(Path(candidate["video_path"])) != candidate["video_sha256"]:
            raise ValueError(
                f"{candidate['scene_id']}: candidate changed while review evidence was prepared"
            )
        if _sha256(Path(candidate["dialogue_audio_path"])) != candidate["dialogue_audio_sha256"]:
            raise ValueError(
                f"{candidate['scene_id']}: dialogue audio changed while review evidence was prepared"
            )
        if _sha256(Path(candidate["spoken_renderer_artifact_path"])) != candidate["spoken_renderer_sha256"]:
            raise ValueError(
                f"{candidate['scene_id']}: spoken renderer artifact changed while review evidence was prepared"
            )
        if candidate["spoken_renderer_audit_path"] and _sha256(
            Path(candidate["spoken_renderer_audit_path"])
        ) != candidate["spoken_renderer_audit_sha256"]:
            raise ValueError(
                f"{candidate['scene_id']}: spoken renderer audit changed while review evidence was prepared"
            )
        if candidate["rife_binding_path"] and _sha256(
            Path(candidate["rife_binding_path"])
        ) != candidate["rife_binding_sha256"]:
            raise ValueError(
                f"{candidate['scene_id']}: RIFE binding changed while review evidence was prepared"
            )
    packet = {
        "schema_version": PACKET_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "task_id": 1,
        "scope": "failed_scene_smoke",
        "plan_sha256": gate.EXPECTED_PLAN_SHA256,
        "source_progress_path": str(progress_path.resolve()),
        "source_progress_sha256": progress_sha,
        "candidate_count": len(candidates),
        "frames_per_candidate": len(FRAME_FRACTIONS),
        "machine_gate_scope": "file_integrity_and_pipeline_provenance_only",
        "human_visual_and_audio_semantic_review_required": True,
        "contact_sheet_path": str(contact_path.resolve()),
        "contact_sheet_sha256": contact_sha,
        "candidates": candidates,
        "downstream_source_contract": gate.current_downstream_source_contract(),
        "machine_gate_passed": True,
        "human_review_completed": False,
        "full_19_shot_generation_allowed": False,
        "douyin_upload_allowed": False,
        "fanqie_backfill_allowed": False,
    }
    staging_packet_path = staging_root / "machine_review_packet.json"
    _write_json_new(staging_packet_path, packet)
    packet_sha = _sha256(staging_packet_path)

    template["source_progress_path"] = str(progress_path.resolve())
    template["reviewed_progress_sha256"] = progress_sha
    template["machine_review_packet_path"] = str(packet_path.resolve())
    template["machine_review_packet_sha256"] = packet_sha
    template["candidate_contact_sheet"] = str(contact_path.resolve())
    template["candidate_contact_sheet_sha256"] = contact_sha
    staged_review_path = staging_root / "review_draft.json"
    _write_json_new(staged_review_path, template)
    _publish_packet_and_review(
        staging_root=staging_root,
        output_root=output_root,
        staged_review_path=staged_review_path,
        review_path=review_path,
    )
    return {
        "packet_path": str(packet_path.resolve()),
        "packet_sha256": packet_sha,
        "contact_sheet_path": str(contact_path.resolve()),
        "contact_sheet_sha256": contact_sha,
        "review_draft_path": str(review_path.resolve()),
        "review_draft_sha256": _sha256(review_path),
        "candidate_count": len(candidates),
        "human_review_completed": False,
        "full_19_shot_generation_allowed": False,
        "douyin_upload_allowed": False,
        "fanqie_backfill_allowed": False,
    }


def prepare_packet(
    *,
    progress_path: Path,
    template_path: Path,
    output_root: Path,
    review_path: Path,
    probe_video=gate._probe_video,
    extract_frame=_extract_frame,
    build_contact_sheet=_contact_sheet,
) -> dict[str, Any]:
    """Prepare evidence and remove only this invocation's abandoned staging dirs."""
    staging_root = (
        output_root.parent / f".{output_root.name}.{uuid.uuid4().hex}.staging"
    )
    try:
        return _prepare_packet(
            progress_path=progress_path,
            template_path=template_path,
            output_root=output_root,
            review_path=review_path,
            probe_video=probe_video,
            extract_frame=extract_frame,
            build_contact_sheet=build_contact_sheet,
            staging_root=staging_root,
        )
    finally:
        if staging_root.is_dir():
            shutil.rmtree(staging_root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare V6.1 smoke evidence and frontend review draft.")
    parser.add_argument("--progress", type=Path, default=DEFAULT_PROGRESS)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--review-output", type=Path, default=DEFAULT_REVIEW)
    args = parser.parse_args(argv)
    try:
        result = prepare_packet(
            progress_path=args.progress.resolve(), template_path=args.template.resolve(),
            output_root=args.output_root.resolve(), review_path=args.review_output.resolve(),
        )
    except (ValueError, OSError) as exc:
        print(json.dumps({
            "success": False, "error": str(exc), "human_review_completed": False,
            "full_19_shot_generation_allowed": False,
            "douyin_upload_allowed": False, "fanqie_backfill_allowed": False,
        }, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"success": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
