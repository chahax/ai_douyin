from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


P0_ROOT = Path(r"D:\IT\ai_douyin_p0")
if str(P0_ROOT) not in sys.path:
    sys.path.insert(0, str(P0_ROOT))

from src.novel_promotion.models import (  # noqa: E402
    EventType,
    FanqiePromotionTask,
    FanqieScriptVersion,
    FanqieVideoJob,
    TaskStatus,
    VideoJobStatus,
)
from src.novel_promotion.repositories import PromotionTaskRepository  # noqa: E402
from src.novel_promotion.video_generation_service import (  # noqa: E402
    _build_transition_chain,
    _validate_output_mp4,
)
from src.shared.database import SessionLocal  # noqa: E402


TASK_ID = 1
ROOT = Path(
    r"D:\IT\ai_douyin\data\fanqie_promotion\renders\task1_story_v5_full"
)
VIDEO_PATH = ROOT / "task1_story_v5_review.mp4"
FLOW_PATH = Path(
    r"D:\IT\ai_douyin\data\fanqie_promotion\scene_plans\task1_story_v5_live_action_flow_ready.json"
)
STORY_MANIFEST_PATH = ROOT / "task1_story_v5_review.story_manifest.json"
STORY_AUDIT_PATH = ROOT / "task1_story_v5_review.audit.json"
QUALITY_PATH = ROOT / "task1_story_v5_review_raw.quality.json"
ACCEPTED_PROGRESS_PATH = ROOT / "batch_progress_accepted.json"
TECHNICAL_AUDIT_PATH = ROOT / "technical_audit_accepted.json"
FINAL_CONTACT_PATH = Path(
    r"D:\IT\ai_douyin\data\qa\task1_story_v5_final_contact_v4.png"
)
AUDIT_ROOT = Path(r"D:\IT\ai_douyin\data\fanqie_promotion\audit")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _verify_artifacts() -> dict:
    required = (
        VIDEO_PATH,
        FLOW_PATH,
        STORY_MANIFEST_PATH,
        STORY_AUDIT_PATH,
        QUALITY_PATH,
        ACCEPTED_PROGRESS_PATH,
        TECHNICAL_AUDIT_PATH,
        FINAL_CONTACT_PATH,
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Required audit artifacts missing: {missing}")

    story_audit = _load_json(STORY_AUDIT_PATH)
    quality = _load_json(QUALITY_PATH)
    accepted = _load_json(ACCEPTED_PROGRESS_PATH)
    technical = _load_json(TECHNICAL_AUDIT_PATH)
    video_sha = _sha256(VIDEO_PATH)
    validation = _validate_output_mp4(str(VIDEO_PATH))

    errors: list[str] = []
    if not validation.ok:
        errors.append(validation.error)
    if story_audit.get("output_sha256", "").lower() != video_sha.lower():
        errors.append("Story audit output SHA-256 does not match final video")
    if not quality.get("passed"):
        errors.append("Raw composition quality gate did not pass")
    if not accepted.get("success") or len(accepted.get("shots", [])) != 9:
        errors.append("Accepted batch does not prove 9 successful shots")
    if accepted.get("publish_allowed") is not False:
        errors.append("Accepted batch must remain publish_allowed=false")
    if not technical.get("all_ok") or technical.get("shot_count") != 9:
        errors.append("Accepted per-shot technical audit did not pass")
    if errors:
        raise RuntimeError("; ".join(errors))

    return {
        "video_sha256": video_sha,
        "duration_ms": validation.duration_ms,
        "file_size": validation.file_size,
        "accepted": accepted,
        "technical": technical,
        "story_audit": story_audit,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Register the audited task-1 LTX story candidate for human review."
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Write the review-required VideoJob and audit events.",
    )
    args = parser.parse_args()
    verified = _verify_artifacts()

    with SessionLocal() as db:
        task = db.query(FanqiePromotionTask).filter_by(id=TASK_ID).one_or_none()
        if task is None:
            raise RuntimeError(f"Task {TASK_ID} does not exist")
        script = (
            db.query(FanqieScriptVersion)
            .filter_by(task_id=TASK_ID, status="approved")
            .order_by(FanqieScriptVersion.version.desc(), FanqieScriptVersion.id.desc())
            .first()
        )
        if script is None:
            raise RuntimeError(f"Task {TASK_ID} has no approved script")

        existing = (
            db.query(FanqieVideoJob)
            .filter(FanqieVideoJob.output_sha256 == verified["video_sha256"])
            .first()
        )
        summary = {
            "action": "already_registered" if existing else "dry_run",
            "confirm_requested": args.confirm,
            "task_id": task.id,
            "task_uuid": task.task_uuid,
            "task_status": task.status,
            "task_publish_type": task.publish_type,
            "script_id": script.id,
            "script_status": script.status,
            "video_path": str(VIDEO_PATH),
            "video_sha256": verified["video_sha256"],
            "duration_ms": verified["duration_ms"],
            "machine_gate_passed": True,
            "visual_pre_review": "codex_pre_review_pass_pending_user",
            "target_video_mode": "story_video",
            "target_publish_type": "AIGC",
            "publish_allowed": False,
            "publish_block_reason": (
                "human video approval pending; task publish_type=AI数字人 does not "
                "match story_video/AIGC"
            ),
        }
        if existing:
            summary.update(
                {"video_job_id": existing.id, "video_job_status": existing.status}
            )
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0
        if not args.confirm:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0

        job_uuid = uuid.uuid4().hex
        review_dir = AUDIT_ROOT / task.task_uuid / "videos" / job_uuid / "review_packet"
        review_dir.mkdir(parents=True, exist_ok=False)
        accepted = verified["accepted"]
        per_shot_stages = {
            shot["scene_id"]: shot["assets"][0]["metadata"].get(
                "per_stage_sha256", {}
            )
            for shot in accepted["shots"]
        }
        packet = {
            "schema_version": "fanqie_video_review_packet/v2",
            "job_uuid": job_uuid,
            "task_id": task.id,
            "task_uuid": task.task_uuid,
            "script_id": script.id,
            "video_mode": "story_video",
            "provider": "comfyui_ltx_i2v",
            "has_presenter": False,
            "output_path": str(VIDEO_PATH),
            "output_sha256": verified["video_sha256"],
            "duration_ms": verified["duration_ms"],
            "scene_count": 9,
            "flow_manifest_path": str(FLOW_PATH),
            "flow_manifest_sha256": _sha256(FLOW_PATH),
            "story_manifest_path": str(STORY_MANIFEST_PATH),
            "story_manifest_sha256": _sha256(STORY_MANIFEST_PATH),
            "accepted_progress_path": str(ACCEPTED_PROGRESS_PATH),
            "accepted_progress_sha256": _sha256(ACCEPTED_PROGRESS_PATH),
            "technical_audit_path": str(TECHNICAL_AUDIT_PATH),
            "technical_audit_sha256": _sha256(TECHNICAL_AUDIT_PATH),
            "quality_report_path": str(QUALITY_PATH),
            "quality_report_sha256": _sha256(QUALITY_PATH),
            "final_contact_path": str(FINAL_CONTACT_PATH),
            "final_contact_sha256": _sha256(FINAL_CONTACT_PATH),
            "per_shot_stages": per_shot_stages,
            "machine_gate_passed": True,
            "visual_pre_review": "codex_pre_review_pass_pending_user",
            "human_review_required": True,
            "auto_approved": False,
            "publish_allowed": False,
            "publish_block_reason": summary["publish_block_reason"],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        packet_path = review_dir / "review_packet.json"
        packet_path.write_text(
            json.dumps(packet, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        video = FanqieVideoJob(
            job_uuid=job_uuid,
            task_id=task.id,
            script_id=script.id,
            video_mode="story_video",
            quality_profile="publish",
            status=VideoJobStatus.REVIEW_REQUIRED,
            request_path=str(FLOW_PATH),
            manifest_path=str(STORY_MANIFEST_PATH),
            output_path=str(VIDEO_PATH),
            quality_report_path=str(QUALITY_PATH),
            review_packet_path=str(packet_path),
            output_sha256=verified["video_sha256"],
            runtime_json={
                "provider": "comfyui_ltx_i2v",
                "provider_version": "1.0.0",
                "scene_count": 9,
                "machine_gate_passed": True,
                "visual_pre_review": "codex_pre_review_pass_pending_user",
                "composer": "compose_story_video+ffmpeg_libass",
                "template": "story_video/v1",
                "has_presenter": False,
                "test_only_provider": False,
                "publish_type_matches": False,
                "publish_block_reason": summary["publish_block_reason"],
                "accepted_progress_sha256": _sha256(ACCEPTED_PROGRESS_PATH),
                "per_shot_stages": per_shot_stages,
            },
            duration_ms=verified["duration_ms"],
            cost_json={"external_cost": 0, "local_gpu": True},
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
        )
        db.add(video)
        db.flush()

        repository = PromotionTaskRepository(db)
        for _from_status, to_status in _build_transition_chain(
            task.status, TaskStatus.REVIEW_REQUIRED
        ):
            if not repository.transition_status(
                task,
                to_status,
                actor_type="local-p0-ltx-pipeline",
                payload={
                    "video_job_id": video.id,
                    "job_uuid": job_uuid,
                    "artifact": str(packet_path),
                },
            ):
                db.rollback()
                raise RuntimeError(
                    f"Failed task transition toward {TaskStatus.REVIEW_REQUIRED}"
                )

        repository.append_event(
            task.id,
            EventType.MANUAL_ACTION,
            from_status=task.status,
            to_status=task.status,
            actor_type="human-review-gate",
            payload={
                "action": "video_candidate_registered",
                "video_job_id": video.id,
                "review_status": "pending",
                "machine_gate_passed": True,
                "visual_pre_review": "codex_pre_review_pass_pending_user",
                "publish_forbidden": True,
                "publish_block_reason": summary["publish_block_reason"],
                "video_sha256": verified["video_sha256"],
            },
            artifact_path=str(packet_path),
            audit_artifact_hash=_sha256(packet_path),
        )
        db.commit()
        summary.update(
            {
                "action": "registered",
                "video_job_id": video.id,
                "video_job_uuid": job_uuid,
                "video_job_status": video.status,
                "task_status": task.status,
                "task_version": task.version,
                "review_packet": str(packet_path),
                "review_packet_sha256": _sha256(packet_path),
            }
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
