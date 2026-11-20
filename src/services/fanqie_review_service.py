"""Frontend review queue for immutable Fanqie V6.1 media artifacts.

The JSON review document remains the portable decision artifact. Every queue
and decision transition is also appended to the authoritative closed-loop
database so the frontend cannot create an approval that is invisible to the
later publish gate. No SSH key or detached signature is involved.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator


PROJECT_ROOT = Path(__file__).resolve().parents[2]
QA_ROOT = (PROJECT_ROOT / "data" / "qa").resolve()
FANQIE_ROOT = (PROJECT_ROOT / "data" / "fanqie_promotion").resolve()
MEDIA_ROOTS = (
    QA_ROOT,
    (FANQIE_ROOT / "renders").resolve(),
    (FANQIE_ROOT / "audio").resolve(),
    (FANQIE_ROOT / "evidence").resolve(),
)
CLOSED_LOOP_DB_PATH = Path(
    os.environ.get(
        "FANQIE_CLOSED_LOOP_DB_PATH",
        str(PROJECT_ROOT / "data" / "fanqie_closed_loop_p0.db"),
    )
).resolve()
SUPPORTED_SCHEMAS = {
    "fanqie_v61_failed_smoke_human_review/v1": "smoke",
    "fanqie_v61_full_human_review/v1": "full_video",
    "fanqie_v62_full_human_review/v1": "full_video_v62",
    "fanqie_v63_full_human_review/v1": "full_video_v63",
}
EXPECTED_SMOKE_SHOTS = 7
EXPECTED_PLAN_SHA256 = "D2C15C86B0AC57BE8CD26EF687C65C049D64B2069568707C8B699AE6D5828CB4"
SMOKE_SHOT_IDS = (
    "b01_boast", "b03_object_question", "b04_confused_answer",
    "b05_age_burst", "b06_pull_away", "b07_protest", "b08_offer_one",
)
SMOKE_SHOT_CHECKS = {
    "identity_consistent", "action_matches_reviewed_beat",
    "emotion_change_is_readable", "lip_sync_is_acceptable",
    "voice_emotion_and_pace_are_natural", "camera_motion_is_controlled",
    "anatomy_and_hands_are_plausible", "no_forbidden_visual_elements",
    "duration_within_tolerance",
}
SMOKE_GLOBAL_CHECKS = {
    "all_seven_shots_present", "all_outputs_match_recorded_sha256",
    "photorealistic_live_action_only",
    "no_anime_cartoon_chibi_or_digital_presenter",
    "no_explanatory_narration", "fixed_character_voices_consistent",
    "dialogue_is_clear_and_emotionally_natural",
    "pace_is_tight_without_slow_motion_or_long_hold",
    "no_readable_unapproved_text_logo_or_watermark",
    "approved_for_full_video_generation",
}
FULL_REVIEW_CHECKS = {
    "complete_video_watched_from_start_to_finish",
    "all_19_beats_present_in_reviewed_order",
    "photorealistic_live_action_only",
    "no_anime_cartoon_chibi_or_digital_presenter",
    "no_explanatory_narration",
    "character_identity_and_wardrobe_consistent",
    "actions_and_emotion_changes_are_readable",
    "lip_sync_is_acceptable_for_all_spoken_closeups",
    "voices_are_fixed_clear_and_emotionally_natural",
    "pace_is_tight_without_slow_motion_or_long_holds",
    "cuts_audio_and_subtitles_are_synchronized",
    "subtitle_text_is_correct_readable_and_safe",
    "no_unapproved_text_logo_watermark_or_visual_artifact",
    "approved_as_douyin_upload_candidate",
}
V62_FULL_REVIEW_CHECKS = {
    "complete_video_watched_from_start_to_finish",
    "all_19_beats_and_32_microshots_present_in_order",
    "reference_style_is_glossy_ai_live_action_blue_hour_neon",
    "no_natural_daylight_stock_or_documentary_style_drift",
    "character_identity_hair_and_wardrobe_are_consistent",
    "actions_are_continuous_without_stutter_or_unwanted_chaining",
    "hands_fingers_phone_booklet_and_car_geometry_are_plausible",
    "facial_expressions_and_emotional_turns_are_readable",
    "cuts_audio_and_subtitles_are_synchronized",
    "dialogue_music_and_silence_gaps_sound_natural",
    "subtitle_text_is_correct_readable_and_safe",
    "no_black_frame_long_freeze_logo_watermark_or_visual_artifact",
    "hybrid_renderer_disclosure_is_understood",
    "approved_as_internal_candidate_only_not_for_upload",
}
V62_RENDERERS = {
    "local_framepack_i2v",
    "local_comfyui_ltx_i2v",
    "local_composite_rife_bridge_and_ltx",
    "deterministic_camera_motion_candidate_only",
}
V62_ACTION_RENDERERS = V62_RENDERERS - {"deterministic_camera_motion_candidate_only"}
V62_STABLE_INSERT_SCENES = {
    "b08_offer_one",
    "b09_offer_two",
    "b10_offer_three",
    "b13_registry_reveal",
    "b14_certificate",
    "b15_terms",
    "b17a_kiss_reaction",
    "b17b_hunt_order",
}
V63_FULL_REVIEW_CHECKS = {
    "complete_video_watched_from_start_to_finish",
    "all_19_beats_and_32_microshots_present_in_order",
    "glossy_high_saturation_live_action_style_has_strong_visual_appeal",
    "neon_confrontation_gold_reversal_and_red_blue_chase_phases_are_distinct",
    "character_identity_hair_and_wardrobe_are_consistent",
    "full_body_leg_and_weight_transfer_actions_are_readable",
    "actions_are_continuous_without_stutter_or_unwanted_chaining",
    "hands_fingers_phone_booklet_and_car_geometry_are_plausible",
    "facial_expressions_and_emotional_turns_are_readable",
    "hard_cuts_are_motivated_and_retention_pace_is_effective",
    "cuts_audio_and_subtitles_are_synchronized",
    "subtitle_text_is_correct_readable_and_safe",
    "no_black_frame_long_freeze_logo_watermark_or_visual_artifact",
    "approved_as_internal_candidate_only_not_for_upload",
}
V63_RENDERERS = {
    "local_framepack_i2v",
    "deterministic_camera_motion_candidate_only",
}
V63_STABLE_INSERT_SCENES = set(V62_STABLE_INSERT_SCENES)
V63_ACTION_SCENES = {
    "b01_boast", "b02_grab_reaction", "b03_object_question",
    "b04_confused_answer", "b05_age_burst", "b06_pull_away",
    "b07_protest", "b11_flip", "b12_car_reveal", "b16_escape",
    "b18_cta",
}
DECISION_EVENT_TYPE = "manual_action"
EXPECTED_CLOSED_LOOP_ALEMBIC_HEAD = "0009_publish_monitor_bind_fields"
SHOT_METADATA_KEYS = {
    "scene_id", "expected_duration_seconds", "candidate_path",
    "candidate_sha256", "machine_observed_duration_seconds",
    "machine_observed_fps", "decision", "notes",
}
REVIEW_LOCK_TTL = timedelta(minutes=15)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("审核文件根节点必须是对象")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _safe_review_path(path: str | Path) -> Path:
    resolved = Path(path).resolve()
    if QA_ROOT not in resolved.parents or not resolved.is_file():
        raise ValueError("审核文件必须位于 data/qa 且真实存在")
    return resolved


def _safe_artifact(
    value: Any, field: str, *, allowed_roots: tuple[Path, ...] | None = None,
) -> Path:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} 为空")
    resolved = Path(text).resolve()
    allowed_roots = allowed_roots or (QA_ROOT,)
    if not any(root == resolved or root in resolved.parents for root in allowed_roots):
        raise ValueError(f"{field} 不在允许的审核产物目录")
    if not resolved.is_file():
        raise ValueError(f"{field} 不是真实文件")
    if resolved.stat().st_size <= 0:
        raise ValueError(f"{field} 是空文件")
    return resolved


def _require_hash(path: Path, expected: Any, field: str) -> str:
    declared = str(expected or "").strip().upper()
    if len(declared) != 64:
        raise ValueError(f"{field} 缺少合法 SHA-256")
    actual = _sha256(path)
    if actual != declared:
        raise ValueError(f"{field} SHA-256 不匹配")
    return actual


def _parse_timestamp(value: Any, field: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} 不能为空")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} 必须是 ISO-8601 时间") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} 必须包含时区")
    return parsed.astimezone(timezone.utc)


def _validate_spoken_renderer_binding(
    *,
    scene_id: str,
    metadata: dict[str, Any],
    packet_candidate: dict[str, Any],
    media_roots: tuple[Path, ...],
) -> None:
    """Require one explicit, hash-bound spoken renderer provenance chain."""
    renderer = str(
        packet_candidate.get("spoken_renderer")
        or metadata.get("spoken_renderer")
        or ""
    ).strip()
    if renderer == "sadtalker_fullframe":
        if (
            metadata.get("spoken_renderer") != renderer
            or metadata.get("spoken_renderer_used") is not True
            or metadata.get("sadtalker_fullframe_used") is not True
            or metadata.get("musetalk_used") is not False
        ):
            raise ValueError(f"{scene_id}: SadTalker 真人全画面来源标记不完整")
        for label, path_key, sha_key in (
            ("SadTalker 视频", "spoken_renderer_artifact_path", "spoken_renderer_sha256"),
            ("SadTalker 审计", "spoken_renderer_audit_path", "spoken_renderer_audit_sha256"),
        ):
            artifact = _safe_artifact(
                metadata.get(path_key), f"{scene_id} {label}", allowed_roots=media_roots
            )
            artifact_sha = _require_hash(
                artifact, metadata.get(sha_key), f"{scene_id} {label}"
            )
            if Path(str(packet_candidate.get(path_key) or "")).resolve() != artifact:
                raise ValueError(f"{scene_id}: 机器审核包未绑定{label}")
            if str(packet_candidate.get(sha_key) or "").upper() != artifact_sha:
                raise ValueError(f"{scene_id}: 机器审核包{label} SHA-256 不匹配")
        if packet_candidate.get("musetalk_used") is True:
            raise ValueError(f"{scene_id}: SadTalker 产物不能声明 MuseTalk")
        rife_binding = _safe_artifact(
            metadata.get("rife_binding_path"),
            f"{scene_id} RIFE 来源绑定",
            allowed_roots=media_roots,
        )
        rife_binding_sha = _require_hash(
            rife_binding,
            metadata.get("rife_binding_sha256"),
            f"{scene_id} RIFE 来源绑定",
        )
        if Path(str(packet_candidate.get("rife_binding_path") or "")).resolve() != rife_binding:
            raise ValueError(f"{scene_id}: 机器审核包未绑定 RIFE 来源证据")
        if str(packet_candidate.get("rife_binding_sha256") or "").upper() != rife_binding_sha:
            raise ValueError(f"{scene_id}: 机器审核包 RIFE 来源证据 SHA-256 不匹配")
        rife_value = _load(rife_binding)
        if (
            rife_value.get("schema") != "fanqie_sadtalker_fullframe/rife_binding/v1"
            or str(rife_value.get("source_sha256") or "").upper()
            != str(metadata.get("spoken_renderer_sha256") or "").upper()
            or str(rife_value.get("output_sha256") or "").upper()
            != str(metadata.get("final_sha256") or "").upper()
            or not str(rife_value.get("rife_model") or "").strip()
            or not isinstance(rife_value.get("rife_multiplier"), int)
            or rife_value["rife_multiplier"] <= 0
            or rife_value.get("delivery_fps") != 50
        ):
            raise ValueError(f"{scene_id}: RIFE 来源与输出绑定不完整")
        per_stage = metadata.get("per_stage_sha256")
        if (
            not isinstance(per_stage, dict)
            or str(per_stage.get("rife_binding_sha256") or "").upper()
            != rife_binding_sha
        ):
            raise ValueError(f"{scene_id}: RIFE 分阶段证据未绑定")
        return

    if renderer != "musetalk_v15":
        raise ValueError(f"{scene_id}: 不支持的口型同步渲染器 {renderer}")
    if metadata.get("musetalk_used") is not True:
        raise ValueError(f"{scene_id}: 口型同步机器证据缺失")
    artifact = _safe_artifact(
        metadata.get("musetalk_artifact_path"),
        f"{scene_id} MuseTalk 视频",
        allowed_roots=media_roots,
    )
    artifact_sha = _require_hash(
        artifact, metadata.get("musetalk_sha256"), f"{scene_id} MuseTalk 视频"
    )
    if Path(str(packet_candidate.get("spoken_renderer_artifact_path") or "")).resolve() != artifact:
        raise ValueError(f"{scene_id}: 机器审核包未绑定 MuseTalk 视频")
    if str(packet_candidate.get("spoken_renderer_sha256") or "").upper() != artifact_sha:
        raise ValueError(f"{scene_id}: 机器审核包 MuseTalk 视频 SHA-256 不匹配")
    if str(packet_candidate.get("spoken_renderer_audit_path") or "").strip():
        raise ValueError(f"{scene_id}: MuseTalk 不能声明不存在的独立审计文件")


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_bytes_atomic(path: Path, payload: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(payload)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _lock_payload(token: str) -> dict[str, Any]:
    return {
        "token": token,
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "acquired_at": datetime.now(timezone.utc).isoformat(),
    }


def _create_lock_file(lock_path: Path, payload: dict[str, Any]) -> None:
    descriptor = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(
            descriptor,
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"),
        )
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _lock_is_stale(raw: bytes, *, now: datetime | None = None) -> bool:
    try:
        payload = json.loads(raw.decode("utf-8"))
        acquired = _parse_timestamp(payload.get("acquired_at"), "锁时间")
        pid = int(payload.get("pid"))
        host = str(payload.get("host") or "")
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return True
    observed = now or datetime.now(timezone.utc)
    if observed - acquired > REVIEW_LOCK_TTL:
        return True
    if host != socket.gethostname():
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    except OSError:
        return True
    return False


@contextmanager
def _review_lock(path: Path) -> Iterator[None]:
    """Serialize decisions and safely reclaim abandoned local lock files."""
    lock_path = path.with_name(f".{path.name}.frontend-review.lock")
    reclaim_path = lock_path.with_name(f".{lock_path.name}.reclaim")
    token = uuid.uuid4().hex
    payload = _lock_payload(token)
    acquired = False
    try:
        if reclaim_path.exists():
            raise ValueError("审核锁正在恢复，请刷新后重试")
        try:
            _create_lock_file(lock_path, payload)
            acquired = True
        except FileExistsError as original_error:
            try:
                observed_raw = lock_path.read_bytes()
            except OSError as exc:
                raise ValueError("无法读取现有审核锁，请刷新后重试") from exc
            if not _lock_is_stale(observed_raw):
                raise ValueError("该审核任务正在被另一位操作人处理，请刷新后重试") from original_error
            reclaim_payload = _lock_payload(uuid.uuid4().hex)
            try:
                _create_lock_file(reclaim_path, reclaim_payload)
            except FileExistsError as exc:
                raise ValueError("审核锁正在恢复，请刷新后重试") from exc
            quarantine = lock_path.with_name(
                f".{lock_path.name}.{uuid.uuid4().hex}.abandoned"
            )
            try:
                if lock_path.read_bytes() != observed_raw:
                    raise ValueError("审核锁已变化，请刷新后重试")
                os.replace(lock_path, quarantine)
                try:
                    _create_lock_file(lock_path, payload)
                    acquired = True
                except FileExistsError as exc:
                    raise ValueError("另一位操作人已取得审核锁，请刷新后重试") from exc
            finally:
                quarantine.unlink(missing_ok=True)
                reclaim_path.unlink(missing_ok=True)
        yield
    finally:
        if acquired:
            try:
                current = json.loads(lock_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                current = {}
            if current.get("token") == token:
                lock_path.unlink(missing_ok=True)


def _status(value: dict[str, Any]) -> str:
    status = str(value.get("review_status") or "pending_review")
    if status in {"not_started", "pending", "pending_review"}:
        return "pending_review"
    if status == "approved":
        return "approved"
    if status == "rejected":
        return "rejected"
    return "invalid"


def _validate_v62_renderer_partition(
    progress_shots: list[dict[str, Any]], partition: Any
) -> dict[str, int]:
    """Validate exact scene-to-renderer disclosure for a V6.2 candidate."""

    if not isinstance(partition, dict):
        raise ValueError("V6.2 混合渲染来源披露不是对象")
    unknown = set(partition) - V62_RENDERERS
    if unknown:
        raise ValueError(f"V6.2 混合渲染来源包含未知渲染器: {sorted(unknown)}")
    scene_ids = [str(row.get("scene_id") or "") for row in progress_shots]
    if len(scene_ids) != 19 or len(set(scene_ids)) != 19 or any(not value for value in scene_ids):
        raise ValueError("V6.2 渲染进度镜头 ID 不完整或重复")

    disclosed: dict[str, str] = {}
    counts: dict[str, int] = {}
    for renderer in sorted(V62_RENDERERS):
        values = partition.get(renderer) or []
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise ValueError(f"V6.2 渲染器 {renderer} 的镜头列表无效")
        if len(values) != len(set(values)):
            raise ValueError(f"V6.2 渲染器 {renderer} 的镜头列表有重复")
        counts[renderer] = len(values)
        for scene_id in values:
            if scene_id in disclosed:
                raise ValueError(f"V6.2 镜头 {scene_id} 被多个渲染器重复披露")
            disclosed[scene_id] = renderer
    if set(disclosed) != set(scene_ids):
        raise ValueError("V6.2 混合渲染来源未精确覆盖 19 个镜头")
    stable = set(partition.get("deterministic_camera_motion_candidate_only") or [])
    if stable != V62_STABLE_INSERT_SCENES:
        raise ValueError("V6.2 形变敏感静态插镜集合发生变化")
    if sum(counts[renderer] for renderer in V62_ACTION_RENDERERS) != 11:
        raise ValueError("V6.2 真实动作渲染镜头数量不是 11")

    rows = {str(row["scene_id"]): row for row in progress_shots}
    for scene_id, renderer in disclosed.items():
        metadata = rows[scene_id].get("provider_metadata")
        if not isinstance(metadata, dict) or metadata.get("renderer") != renderer:
            raise ValueError(f"V6.2 镜头 {scene_id} 的渲染来源与镜头审计不一致")
    return counts


def _evidence_v62_full(value: dict[str, Any]) -> dict[str, Any]:
    """Validate the V6.2 hybrid micro-shot candidate without granting publish."""
    if value.get("task_id") != 1 or value.get("scope") != "v62_full_microshot_candidate":
        raise ValueError("V6.2 整片审核 task/scope 不匹配")
    plan = _safe_artifact(
        value.get("plan_path"), "V6.2 微镜头计划", allowed_roots=(FANQIE_ROOT,)
    )
    plan_sha = _require_hash(plan, value.get("plan_sha256"), "V6.2 微镜头计划")
    plan_value = _load(plan)
    if plan_value.get("schema_version") != "fanqie_v62_microshot_workflow/v2":
        raise ValueError("V6.2 微镜头计划 schema 不匹配")
    branch = (plan_value.get("variants") or {}).get("original_recomposed")
    if not isinstance(branch, dict) or branch.get("publish_allowed") is not False:
        raise ValueError("V6.2 原创候选分支缺少非发布门禁")
    if len(branch.get("new_framepack_units") or []) != 19 or len(branch.get("microshots") or []) != 32:
        raise ValueError("V6.2 微镜头计划不是 19 段/32 微镜头")

    packet = _safe_artifact(value.get("machine_review_packet_path"), "V6.2 机器审核包")
    packet_sha = _require_hash(packet, value.get("machine_review_packet_sha256"), "V6.2 机器审核包")
    packet_value = _load(packet)
    if packet_value.get("schema_version") != "fanqie_v62_full_machine_review_packet/v1":
        raise ValueError("V6.2 机器审核包 schema 不匹配")
    if packet_value.get("task_id") != 1 or packet_value.get("scope") != "v62_full_microshot_candidate":
        raise ValueError("V6.2 机器审核包 task/scope 不匹配")
    if str(packet_value.get("plan_sha256") or "").upper() != plan_sha:
        raise ValueError("V6.2 机器审核包计划 SHA-256 不匹配")
    if packet_value.get("machine_gate_passed") is not True:
        raise ValueError("V6.2 机器门禁未通过")
    if packet_value.get("visual_style_and_motion_require_human_confirmation") is not True:
        raise ValueError("V6.2 机器审核包未要求人工确认画风和动作")
    for key in (
        "human_full_video_review_completed", "douyin_upload_allowed",
        "fanqie_backfill_allowed",
    ):
        if packet_value.get(key) is not False:
            raise ValueError(f"V6.2 机器审核包 {key} 必须保持 false")

    media_roots = (QA_ROOT, *MEDIA_ROOTS[1:])
    candidate = _safe_artifact(
        value.get("candidate_path"), "V6.2 完整候选", allowed_roots=media_roots
    )
    candidate_sha = _require_hash(candidate, value.get("candidate_sha256"), "V6.2 完整候选")
    if Path(str(packet_value.get("candidate_path") or "")).resolve() != candidate:
        raise ValueError("V6.2 机器审核包未绑定当前候选")
    if str(packet_value.get("candidate_sha256") or "").upper() != candidate_sha:
        raise ValueError("V6.2 机器审核包候选 SHA-256 不匹配")

    contact = _safe_artifact(value.get("contact_sheet_path"), "V6.2 联系表")
    contact_sha = _require_hash(contact, value.get("contact_sheet_sha256"), "V6.2 联系表")
    if Path(str(packet_value.get("contact_sheet_path") or "")).resolve() != contact:
        raise ValueError("V6.2 机器审核包未绑定当前联系表")
    if str(packet_value.get("contact_sheet_sha256") or "").upper() != contact_sha:
        raise ValueError("V6.2 联系表 SHA-256 不匹配")

    audit = _safe_artifact(packet_value.get("candidate_audit_path"), "V6.2 合成审计")
    audit_sha = _require_hash(audit, packet_value.get("candidate_audit_sha256"), "V6.2 合成审计")
    audit_value = _load(audit)
    if audit_value.get("schema_version") != "fanqie_v62_microshot_candidate/v1":
        raise ValueError("V6.2 合成审计 schema 不匹配")
    if Path(str(audit_value.get("candidate_path") or "")).resolve() != candidate:
        raise ValueError("V6.2 合成审计未绑定当前候选")
    if str(audit_value.get("candidate_sha256") or "").upper() != candidate_sha:
        raise ValueError("V6.2 合成审计候选 SHA-256 不匹配")
    microshots = audit_value.get("microshots")
    if not isinstance(microshots, list) or len(microshots) != 32:
        raise ValueError("V6.2 合成审计没有 32 个微镜头")
    for index, row in enumerate(microshots, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"V6.2 第 {index} 个微镜头审计无效")
        artifact = _safe_artifact(
            row.get("output_path"), f"V6.2 第 {index} 个微镜头", allowed_roots=media_roots
        )
        _require_hash(artifact, row.get("output_sha256"), f"V6.2 第 {index} 个微镜头")

    progress = _safe_artifact(packet_value.get("render_progress_path"), "V6.2 渲染进度")
    progress_sha = _require_hash(progress, packet_value.get("render_progress_sha256"), "V6.2 渲染进度")
    progress_value = _load(progress)
    if progress_value.get("schema_version") != "fanqie_v62_ltx_progress/v1" or progress_value.get("success") is not True:
        raise ValueError("V6.2 渲染进度未完成")
    if str(progress_value.get("plan_sha256") or "").upper() != plan_sha:
        raise ValueError("V6.2 渲染进度计划 SHA-256 不匹配")
    progress_shots = progress_value.get("shots")
    if not isinstance(progress_shots, list) or len(progress_shots) != 19:
        raise ValueError("V6.2 渲染进度没有 19 个镜头单元")
    partition = progress_value.get("renderer_partition")
    renderer_counts = _validate_v62_renderer_partition(progress_shots, partition)
    disclosure = packet_value.get("render_disclosure")
    if not isinstance(disclosure, dict):
        raise ValueError("V6.2 机器审核包缺少混合渲染披露")
    disclosed_counts = disclosure.get("renderer_units")
    if disclosed_counts is None:
        disclosed_counts = {
            "local_comfyui_ltx_i2v": disclosure.get("local_comfyui_ltx_i2v_units"),
            "deterministic_camera_motion_candidate_only": disclosure.get(
                "deterministic_camera_motion_closeup_units"
            ),
            "local_framepack_i2v": 0,
        }
    if not isinstance(disclosed_counts, dict) or {
        key: int(disclosed_counts.get(key) or 0) for key in V62_RENDERERS
    } != renderer_counts:
        raise ValueError("V6.2 机器审核包与渲染进度的来源数量不一致")
    if disclosure.get("microshot_count") != 32 or disclosure.get("all_media_generated_locally") is not True:
        raise ValueError("V6.2 机器审核包的微镜头/本地生成披露不完整")
    for row in progress_shots:
        if not isinstance(row, dict) or row.get("status") != "rendered":
            raise ValueError("V6.2 渲染进度包含未完成镜头")
        artifact = _safe_artifact(
            row.get("output_path"), f"V6.2 镜头 {row.get('scene_id')}", allowed_roots=media_roots
        )
        _require_hash(artifact, row.get("output_sha256"), f"V6.2 镜头 {row.get('scene_id')}")

    probe = packet_value.get("probe")
    if not isinstance(probe, dict):
        raise ValueError("V6.2 机器审核包缺少成片探针")
    if (probe.get("width"), probe.get("height"), probe.get("fps")) != (1080, 1920, "30/1"):
        raise ValueError("V6.2 成片画幅或帧率不匹配")
    duration = float(probe.get("duration_seconds") or 0)
    if abs(duration - 40.8) > 0.08:
        raise ValueError("V6.2 成片时长不在允许范围")
    technical = packet_value.get("technical_scan")
    if not isinstance(technical, dict) or technical.get("freeze_event_count") != 0 or technical.get("black_event_count") != 0:
        raise ValueError("V6.2 黑帧/冻结帧机器检查未通过")
    frames = packet_value.get("frames")
    if not isinstance(frames, list) or len(frames) != 11:
        raise ValueError("V6.2 机器审核包必须包含 11 帧抽检证据")
    for index, frame in enumerate(frames, start=1):
        if not isinstance(frame, dict):
            raise ValueError(f"V6.2 第 {index} 个抽检帧无效")
        frame_path = _safe_artifact(frame.get("path"), f"V6.2 第 {index} 个抽检帧")
        _require_hash(frame_path, frame.get("sha256"), f"V6.2 第 {index} 个抽检帧")

    checks = value.get("checks")
    if not isinstance(checks, dict) or set(checks) != V62_FULL_REVIEW_CHECKS:
        raise ValueError("V6.2 整片审核项 schema 不匹配")
    confirmations = {
        f"check:{key}": {"label": key, "criteria": [key]}
        for key in sorted(checks)
    }
    return {
        "video_paths": [str(candidate)],
        "video_sha256s": [candidate_sha],
        "preview_path": str(contact),
        "preview_sha256": contact_sha,
        "machine_packet_path": str(packet),
        "machine_packet_sha256": packet_sha,
        "candidate_audit_path": str(audit),
        "candidate_audit_sha256": audit_sha,
        "progress_path": str(progress),
        "progress_sha256": progress_sha,
        "required_checks": sorted(confirmations),
        "required_confirmations": confirmations,
        "required_playback_seconds": duration,
    }


def _evidence_v63_full(value: dict[str, Any]) -> dict[str, Any]:
    """Validate the V6.3 visual-retention candidate without granting publish."""
    if value.get("task_id") != 1 or value.get("scope") != "v63_full_visual_retention_candidate":
        raise ValueError("V6.3 整片审核 task/scope 不匹配")
    plan = _safe_artifact(
        value.get("plan_path"), "V6.3 视觉留存计划", allowed_roots=(FANQIE_ROOT,)
    )
    plan_sha = _require_hash(plan, value.get("plan_sha256"), "V6.3 视觉留存计划")
    plan_value = _load(plan)
    if plan_value.get("schema_version") != "fanqie_v63_visual_retention_workflow/v1":
        raise ValueError("V6.3 视觉留存计划 schema 不匹配")
    branch = (plan_value.get("variants") or {}).get("visual_retention_v1")
    if not isinstance(branch, dict):
        raise ValueError("V6.3 视觉留存候选分支缺失")
    for key in (
        "reference_video_pixels_allowed", "reference_people_allowed",
        "reference_watermark_allowed", "publish_allowed", "fanqie_backfill_allowed",
    ):
        if branch.get(key) is not False:
            raise ValueError(f"V6.3 计划门禁 {key} 必须保持 false")
    if len(branch.get("new_framepack_units") or []) != 19 or len(branch.get("microshots") or []) != 32:
        raise ValueError("V6.3 计划不是 19 段/32 微镜头")
    if set(branch.get("action_scene_ids") or []) != V63_ACTION_SCENES:
        raise ValueError("V6.3 真实动作镜头集合发生变化")
    if set(branch.get("stable_insert_scene_ids") or []) != V63_STABLE_INSERT_SCENES:
        raise ValueError("V6.3 稳定信息插镜集合发生变化")

    packet = _safe_artifact(value.get("machine_review_packet_path"), "V6.3 机器审核包")
    packet_sha = _require_hash(packet, value.get("machine_review_packet_sha256"), "V6.3 机器审核包")
    packet_value = _load(packet)
    if packet_value.get("schema_version") != "fanqie_v63_full_machine_review_packet/v1":
        raise ValueError("V6.3 机器审核包 schema 不匹配")
    if packet_value.get("task_id") != 1 or packet_value.get("scope") != "v63_full_visual_retention_candidate":
        raise ValueError("V6.3 机器审核包 task/scope 不匹配")
    if str(packet_value.get("plan_sha256") or "").upper() != plan_sha:
        raise ValueError("V6.3 机器审核包计划 SHA-256 不匹配")
    if packet_value.get("machine_gate_passed") is not True:
        raise ValueError("V6.3 机器门禁未通过")
    if packet_value.get("visual_style_motion_and_retention_require_human_confirmation") is not True:
        raise ValueError("V6.3 机器审核包未要求人工确认观感、动作和节奏")
    for key in ("human_full_video_review_completed", "douyin_upload_allowed", "fanqie_backfill_allowed"):
        if packet_value.get(key) is not False:
            raise ValueError(f"V6.3 机器审核包 {key} 必须保持 false")

    media_roots = (QA_ROOT, *MEDIA_ROOTS[1:])
    candidate = _safe_artifact(
        value.get("candidate_path"), "V6.3 完整候选", allowed_roots=media_roots
    )
    candidate_sha = _require_hash(candidate, value.get("candidate_sha256"), "V6.3 完整候选")
    if Path(str(packet_value.get("candidate_path") or "")).resolve() != candidate:
        raise ValueError("V6.3 机器审核包未绑定当前候选")
    if str(packet_value.get("candidate_sha256") or "").upper() != candidate_sha:
        raise ValueError("V6.3 机器审核包候选 SHA-256 不匹配")
    contact = _safe_artifact(value.get("contact_sheet_path"), "V6.3 联系表")
    contact_sha = _require_hash(contact, value.get("contact_sheet_sha256"), "V6.3 联系表")
    if Path(str(packet_value.get("contact_sheet_path") or "")).resolve() != contact:
        raise ValueError("V6.3 机器审核包未绑定当前联系表")
    if str(packet_value.get("contact_sheet_sha256") or "").upper() != contact_sha:
        raise ValueError("V6.3 联系表 SHA-256 不匹配")

    audit = _safe_artifact(packet_value.get("candidate_audit_path"), "V6.3 合成审计")
    audit_sha = _require_hash(audit, packet_value.get("candidate_audit_sha256"), "V6.3 合成审计")
    audit_value = _load(audit)
    if audit_value.get("schema_version") != "fanqie_v63_visual_retention_candidate/v1":
        raise ValueError("V6.3 合成审计 schema 不匹配")
    if Path(str(audit_value.get("candidate_path") or "")).resolve() != candidate:
        raise ValueError("V6.3 合成审计未绑定当前候选")
    if str(audit_value.get("candidate_sha256") or "").upper() != candidate_sha:
        raise ValueError("V6.3 合成审计候选 SHA-256 不匹配")
    for key in ("reference_video_pixels_used", "reference_people_used", "reference_watermark_used"):
        if audit_value.get(key) is not False:
            raise ValueError(f"V6.3 合成审计 {key} 必须保持 false")
    microshots = audit_value.get("microshots")
    if not isinstance(microshots, list) or len(microshots) != 32:
        raise ValueError("V6.3 合成审计没有 32 个微镜头")
    for index, row in enumerate(microshots, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"V6.3 第 {index} 个微镜头审计无效")
        artifact = _safe_artifact(
            row.get("output_path"), f"V6.3 第 {index} 个微镜头", allowed_roots=media_roots
        )
        _require_hash(artifact, row.get("output_sha256"), f"V6.3 第 {index} 个微镜头")

    progress = _safe_artifact(packet_value.get("render_progress_path"), "V6.3 渲染进度")
    progress_sha = _require_hash(progress, packet_value.get("render_progress_sha256"), "V6.3 渲染进度")
    progress_value = _load(progress)
    if progress_value.get("schema_version") != "fanqie_v63_render_progress/v1" or progress_value.get("success") is not True:
        raise ValueError("V6.3 渲染进度未完成")
    if str(progress_value.get("plan_sha256") or "").upper() != plan_sha:
        raise ValueError("V6.3 渲染进度计划 SHA-256 不匹配")
    progress_shots = progress_value.get("shots")
    if not isinstance(progress_shots, list) or len(progress_shots) != 19:
        raise ValueError("V6.3 渲染进度没有 19 个镜头单元")
    partition = progress_value.get("renderer_partition")
    if not isinstance(partition, dict) or set(partition) != V63_RENDERERS:
        raise ValueError("V6.3 渲染来源必须恰好是 FramePack 动作和稳定信息插镜")
    if set(partition["local_framepack_i2v"]) != V63_ACTION_SCENES:
        raise ValueError("V6.3 FramePack 动作镜头披露不完整")
    if set(partition["deterministic_camera_motion_candidate_only"]) != V63_STABLE_INSERT_SCENES:
        raise ValueError("V6.3 稳定插镜披露不完整")
    disclosed = {
        scene_id: renderer
        for renderer, scene_ids in partition.items()
        for scene_id in scene_ids
    }
    if len(disclosed) != 19:
        raise ValueError("V6.3 渲染来源没有精确覆盖 19 个镜头")
    for row in progress_shots:
        if not isinstance(row, dict) or row.get("status") != "rendered":
            raise ValueError("V6.3 渲染进度包含未完成镜头")
        scene_id = str(row.get("scene_id") or "")
        if row.get("renderer") != disclosed.get(scene_id):
            raise ValueError(f"V6.3 镜头 {scene_id} 渲染来源与披露不一致")
        artifact = _safe_artifact(
            row.get("output_path"), f"V6.3 镜头 {scene_id}", allowed_roots=media_roots
        )
        _require_hash(artifact, row.get("output_sha256"), f"V6.3 镜头 {scene_id}")
        metrics = row.get("motion_metrics")
        if not isinstance(metrics, dict) or float(metrics.get("smoothness_score") or 0) < 65.0:
            raise ValueError(f"V6.3 镜头 {scene_id} 平滑度门禁未通过")
        limit = 0.12 if row.get("renderer") == "local_framepack_i2v" else 0.28
        if float(metrics.get("duplicate_ratio", 1.0)) > limit:
            raise ValueError(f"V6.3 镜头 {scene_id} 重复帧门禁未通过")
        if row.get("renderer") == "local_framepack_i2v" and float(metrics.get("mean_frame_distance") or 0) < 0.5:
            raise ValueError(f"V6.3 动作镜头 {scene_id} 运动量不足")

    disclosure = packet_value.get("render_disclosure")
    if not isinstance(disclosure, dict):
        raise ValueError("V6.3 机器审核包缺少渲染来源披露")
    counts = disclosure.get("renderer_units")
    if counts != {
        "local_framepack_i2v": 11,
        "deterministic_camera_motion_candidate_only": 8,
    }:
        raise ValueError("V6.3 机器审核包渲染数量不是 11 动作/8 插镜")
    if disclosure.get("microshot_count") != 32 or disclosure.get("all_media_generated_locally") is not True:
        raise ValueError("V6.3 机器审核包微镜头/本地生成披露不完整")
    if disclosure.get("reference_video_pixels_used") is not False:
        raise ValueError("V6.3 机器审核包禁止使用参考视频像素")

    probe = packet_value.get("probe")
    if not isinstance(probe, dict) or (probe.get("width"), probe.get("height"), probe.get("fps")) != (1080, 1920, "30/1"):
        raise ValueError("V6.3 成片画幅或帧率不匹配")
    duration = float(probe.get("duration_seconds") or 0)
    if abs(duration - 40.8) > 0.08:
        raise ValueError("V6.3 成片时长不在允许范围")
    technical = packet_value.get("technical_scan")
    if not isinstance(technical, dict) or technical.get("freeze_event_count") != 0 or technical.get("black_event_count") != 0:
        raise ValueError("V6.3 黑帧/冻结帧机器检查未通过")
    temporal = packet_value.get("temporal_metrics")
    if not isinstance(temporal, dict) or float(temporal.get("duplicate_ratio", 1.0)) > 0.12:
        raise ValueError("V6.3 整片重复帧门禁未通过")
    if float(temporal.get("mean_frame_distance") or 0) < 4.5:
        raise ValueError("V6.3 整片运动密度门禁未通过")
    frames = packet_value.get("frames")
    if not isinstance(frames, list) or len(frames) != 11:
        raise ValueError("V6.3 机器审核包必须包含 11 帧抽检证据")
    for index, frame in enumerate(frames, start=1):
        if not isinstance(frame, dict):
            raise ValueError(f"V6.3 第 {index} 个抽检帧无效")
        frame_path = _safe_artifact(frame.get("path"), f"V6.3 第 {index} 个抽检帧")
        _require_hash(frame_path, frame.get("sha256"), f"V6.3 第 {index} 个抽检帧")

    checks = value.get("checks")
    if not isinstance(checks, dict) or set(checks) != V63_FULL_REVIEW_CHECKS:
        raise ValueError("V6.3 整片审核项 schema 不匹配")
    confirmations = {
        f"check:{key}": {"label": key, "criteria": [key]}
        for key in sorted(checks)
    }
    return {
        "video_paths": [str(candidate)],
        "video_sha256s": [candidate_sha],
        "preview_path": str(contact),
        "preview_sha256": contact_sha,
        "machine_packet_path": str(packet),
        "machine_packet_sha256": packet_sha,
        "candidate_audit_path": str(audit),
        "candidate_audit_sha256": audit_sha,
        "progress_path": str(progress),
        "progress_sha256": progress_sha,
        "required_checks": sorted(confirmations),
        "required_confirmations": confirmations,
        "required_playback_seconds": duration,
    }


def _evidence(value: dict[str, Any], review_type: str) -> dict[str, Any]:
    """Validate the production packet/progress boundary before queueing."""
    if review_type == "full_video_v63":
        return _evidence_v63_full(value)
    if review_type == "full_video_v62":
        return _evidence_v62_full(value)
    if value.get("task_id") != 1:
        raise ValueError("审核源任务必须是 task 1")
    if str(value.get("plan_sha256") or "").upper() != EXPECTED_PLAN_SHA256:
        raise ValueError("审核计划 SHA-256 不匹配")
    packet = _safe_artifact(value.get("machine_review_packet_path"), "机器审核包")
    packet_sha = _require_hash(
        packet, value.get("machine_review_packet_sha256"), "机器审核包"
    )
    packet_value = _load(packet)
    media_roots = (QA_ROOT, *MEDIA_ROOTS[1:])

    if review_type == "smoke":
        if value.get("scope") != "failed_scene_smoke":
            raise ValueError("烟测审核 scope 不匹配")
        if packet_value.get("schema_version") != "fanqie_v61_smoke_machine_review_packet/v2":
            raise ValueError("烟测机器审核包 schema 不匹配")
        if packet_value.get("task_id") != 1 or packet_value.get("scope") != "failed_scene_smoke":
            raise ValueError("烟测机器审核包 task/scope 不匹配")
        if str(packet_value.get("plan_sha256") or "").upper() != EXPECTED_PLAN_SHA256:
            raise ValueError("烟测机器审核包计划 SHA-256 不匹配")
        if packet_value.get("machine_gate_passed") is not True:
            raise ValueError("烟测机器门禁未通过")
        if packet_value.get("human_visual_and_audio_semantic_review_required") is not True:
            raise ValueError("烟测机器审核包未要求人工语义审核")
        for key in (
            "human_review_completed", "full_19_shot_generation_allowed",
            "douyin_upload_allowed", "fanqie_backfill_allowed",
        ):
            if packet_value.get(key) is not False:
                raise ValueError(f"烟测机器审核包 {key} 必须保持 false")
        progress = _safe_artifact(value.get("source_progress_path"), "烟测进度")
        progress_sha = _require_hash(
            progress, value.get("reviewed_progress_sha256"), "烟测进度"
        )
        progress_value = _load(progress)
        if progress_value.get("schema_version") != "fanqie_v61_failed_smoke_progress/v1":
            raise ValueError("烟测进度 schema 不匹配")
        if progress_value.get("task_id") != 1 or progress_value.get("scope") != "failed_scene_smoke":
            raise ValueError("烟测进度 task/scope 不匹配")
        if str(progress_value.get("expected_plan_sha256") or "").upper() != EXPECTED_PLAN_SHA256:
            raise ValueError("烟测进度计划 SHA-256 不匹配")
        if tuple(progress_value.get("selected_shot_ids") or ()) != SMOKE_SHOT_IDS:
            raise ValueError("烟测进度镜头边界不匹配")
        if progress_value.get("result") != "FAILED_SCENE_SMOKE_RENDERED_AWAITING_HUMAN_REVIEW":
            raise ValueError("烟测进度不是可供人工审核的完成状态")
        progress_gates = progress_value.get("gates")
        if not isinstance(progress_gates, dict):
            raise ValueError("烟测进度机器门禁缺失")
        for key in (
            "static_validation_passed", "audio_prepared",
            "runtime_preflight_passed", "failed_scene_smoke_rendered",
        ):
            if progress_gates.get(key) is not True:
                raise ValueError(f"烟测进度门禁 {key} 未通过")
        for key in (
            "human_video_approval_obtained", "matching_fanqie_task_confirmed",
            "publish_allowed", "fanqie_backfill_allowed",
        ):
            if progress_gates.get(key) is not False:
                raise ValueError(f"烟测平台门禁 {key} 必须保持 false")
        if Path(str(packet_value.get("source_progress_path") or "")).resolve() != progress:
            raise ValueError("机器审核包未绑定当前烟测进度")
        if str(packet_value.get("source_progress_sha256") or "").upper() != progress_sha:
            raise ValueError("机器审核包烟测进度 SHA-256 不匹配")
        contact = _safe_artifact(value.get("candidate_contact_sheet"), "烟测联系表")
        contact_sha = _require_hash(
            contact, value.get("candidate_contact_sheet_sha256"), "烟测联系表"
        )
        if Path(str(packet_value.get("contact_sheet_path") or "")).resolve() != contact:
            raise ValueError("机器审核包未绑定当前烟测联系表")
        if str(packet_value.get("contact_sheet_sha256") or "").upper() != contact_sha:
            raise ValueError("机器审核包烟测联系表 SHA-256 不匹配")
        shots = value.get("shots")
        if not isinstance(shots, list) or len(shots) != EXPECTED_SMOKE_SHOTS:
            raise ValueError("烟测审核必须恰好包含 7 个真实候选镜头")
        if tuple(str(shot.get("scene_id") or "") for shot in shots if isinstance(shot, dict)) != SMOKE_SHOT_IDS:
            raise ValueError("烟测审核镜头顺序不匹配")
        progress_shots = progress_value.get("shots")
        packet_candidates = packet_value.get("candidates")
        if not isinstance(progress_shots, list) or len(progress_shots) != EXPECTED_SMOKE_SHOTS:
            raise ValueError("烟测进度必须包含 7 个镜头")
        if not isinstance(packet_candidates, list) or len(packet_candidates) != EXPECTED_SMOKE_SHOTS:
            raise ValueError("烟测机器审核包必须包含 7 个候选")
        if packet_value.get("candidate_count") != EXPECTED_SMOKE_SHOTS:
            raise ValueError("烟测机器审核包 candidate_count 不匹配")
        if packet_value.get("frames_per_candidate") != 3:
            raise ValueError("烟测机器审核包必须每个候选抽取 3 帧")
        videos: list[str] = []
        video_hashes: list[str] = []
        confirmations: dict[str, dict[str, Any]] = {}
        for index, (shot, progress_shot, packet_candidate) in enumerate(
            zip(shots, progress_shots, packet_candidates, strict=True), start=1
        ):
            if not isinstance(shot, dict):
                raise ValueError(f"第 {index} 个烟测镜头格式无效")
            scene_id = str(shot.get("scene_id") or "")
            if not isinstance(progress_shot, dict) or progress_shot.get("scene_id") != scene_id:
                raise ValueError(f"{scene_id}: 烟测进度镜头绑定不匹配")
            if not isinstance(packet_candidate, dict) or packet_candidate.get("scene_id") != scene_id:
                raise ValueError(f"{scene_id}: 烟测机器候选绑定不匹配")
            assets = progress_shot.get("assets")
            if not isinstance(assets, list) or len(assets) != 1 or not isinstance(assets[0], dict):
                raise ValueError(f"{scene_id}: 烟测进度必须恰好绑定一个视频产物")
            asset = assets[0]
            metadata = asset.get("metadata")
            if not isinstance(metadata, dict):
                raise ValueError(f"{scene_id}: 烟测进度缺少机器元数据")
            candidate = _safe_artifact(
                shot.get("candidate_path"), f"第 {index} 个烟测视频",
                allowed_roots=media_roots,
            )
            candidate_sha = _require_hash(
                candidate, shot.get("candidate_sha256"), f"第 {index} 个烟测视频"
            )
            if Path(str(asset.get("video_path") or "")).resolve() != candidate:
                raise ValueError(f"{scene_id}: 烟测进度视频路径不匹配")
            if str(metadata.get("final_sha256") or "").upper() != candidate_sha:
                raise ValueError(f"{scene_id}: 烟测进度视频 SHA-256 不匹配")
            if Path(str(packet_candidate.get("video_path") or "")).resolve() != candidate:
                raise ValueError(f"{scene_id}: 机器审核包视频路径不匹配")
            if str(packet_candidate.get("video_sha256") or "").upper() != candidate_sha:
                raise ValueError(f"{scene_id}: 机器审核包视频 SHA-256 不匹配")
            if metadata.get("has_presenter") is not False or packet_candidate.get("has_presenter") is not False:
                raise ValueError(f"{scene_id}: 检测到禁止的数字人 Presenter")
            _validate_spoken_renderer_binding(
                scene_id=scene_id,
                metadata=metadata,
                packet_candidate=packet_candidate,
                media_roots=media_roots,
            )
            shot_checks = set(shot) - SHOT_METADATA_KEYS
            if shot_checks != SMOKE_SHOT_CHECKS:
                raise ValueError(f"{scene_id}: 逐镜头审核项 schema 不匹配")
            videos.append(str(candidate))
            video_hashes.append(candidate_sha)
            confirmations[f"shot:{scene_id}"] = {
                "label": f"{scene_id}：已完整播放并确认全部逐镜头标准",
                "criteria": sorted(shot_checks),
            }
        gates = value.get("global_gates")
        if not isinstance(gates, dict) or set(gates) != SMOKE_GLOBAL_CHECKS:
            raise ValueError("烟测全局审核项 schema 不匹配")
        for key in sorted(gates):
            confirmations[f"global:{key}"] = {"label": key, "criteria": [key]}
        duration = sum(
            float(shot.get("expected_duration_seconds") or 0) for shot in shots
        )
        if duration <= 0:
            duration = sum(
                float(shot.get("machine_observed_duration_seconds") or 0)
                for shot in shots
            )
        if duration <= 0:
            raise ValueError("烟测候选缺少可审核时长")
        return {
            "video_paths": videos,
            "video_sha256s": video_hashes,
            "preview_path": str(contact),
            "preview_sha256": contact_sha,
            "machine_packet_path": str(packet),
            "machine_packet_sha256": packet_sha,
            "progress_path": str(progress),
            "progress_sha256": progress_sha,
            "required_checks": sorted(confirmations),
            "required_confirmations": confirmations,
            "required_playback_seconds": duration,
        }

    if value.get("scope") != "full_19_beat_candidate":
        raise ValueError("整片审核 scope 不匹配")
    if packet_value.get("schema_version") != "fanqie_v61_full_machine_review_packet/v1":
        raise ValueError("整片机器审核包 schema 不匹配")
    if packet_value.get("task_id") != 1 or packet_value.get("scope") != "full_19_beat_candidate":
        raise ValueError("整片机器审核包 task/scope 不匹配")
    if str(packet_value.get("plan_sha256") or "").upper() != EXPECTED_PLAN_SHA256:
        raise ValueError("整片机器审核包计划 SHA-256 不匹配")
    if packet_value.get("machine_gate_passed") is not True:
        raise ValueError("整片机器门禁未通过")
    if packet_value.get("human_visual_audio_editorial_review_required") is not True:
        raise ValueError("整片机器审核包未要求人工审核")
    for key in (
        "human_full_video_review_completed", "matching_fanqie_task_confirmed",
        "douyin_upload_allowed", "fanqie_backfill_allowed",
    ):
        if packet_value.get(key) is not False:
            raise ValueError(f"整片机器审核包 {key} 必须保持 false")
    candidate = _safe_artifact(
        value.get("candidate_path"), "整片候选视频", allowed_roots=media_roots
    )
    candidate_sha = _require_hash(
        candidate, value.get("candidate_sha256"), "整片候选视频"
    )
    if Path(str(packet_value.get("candidate_path") or "")).resolve() != candidate:
        raise ValueError("整片机器审核包候选路径不匹配")
    if str(packet_value.get("candidate_sha256") or "").upper() != candidate_sha:
        raise ValueError("整片审核与机器审核包绑定的视频不一致")
    contact = _safe_artifact(value.get("contact_sheet_path"), "整片联系表")
    contact_sha = _require_hash(
        contact, value.get("contact_sheet_sha256"), "整片联系表"
    )
    if Path(str(packet_value.get("contact_sheet_path") or "")).resolve() != contact:
        raise ValueError("整片机器审核包联系表路径不匹配")
    if str(packet_value.get("contact_sheet_sha256") or "").upper() != contact_sha:
        raise ValueError("整片机器审核包联系表 SHA-256 不匹配")
    audit = _safe_artifact(packet_value.get("candidate_audit_path"), "整片候选审计")
    audit_sha = _require_hash(
        audit, packet_value.get("candidate_audit_sha256"), "整片候选审计"
    )
    audit_value = _load(audit)
    if audit_value.get("schema_version") != "fanqie_v61_full_candidate_audit/v2":
        raise ValueError("整片候选审计 schema 不匹配")
    if audit_value.get("shot_count") != 19 or audit_value.get("machine_composition_gate_passed") is not True:
        raise ValueError("整片候选审计未证明 19 镜头机器合成门禁")
    if Path(str(audit_value.get("candidate_path") or "")).resolve() != candidate:
        raise ValueError("整片候选审计视频路径不匹配")
    if str(audit_value.get("candidate_sha256") or "").upper() != candidate_sha:
        raise ValueError("整片候选审计视频 SHA-256 不匹配")
    checks = value.get("checks")
    if not isinstance(checks, dict) or set(checks) != FULL_REVIEW_CHECKS:
        raise ValueError("整片审核项 schema 不匹配")
    duration = float((packet_value.get("probe") or {}).get("duration_seconds") or 0)
    if abs(duration - 40.8) > 0.30:
        raise ValueError("机器审核包整片时长不在允许范围")
    frames = packet_value.get("frames")
    if not isinstance(frames, list) or len(frames) != 11:
        raise ValueError("整片机器审核包必须包含 11 帧抽检证据")
    for index, frame in enumerate(frames, start=1):
        if not isinstance(frame, dict):
            raise ValueError(f"第 {index} 个整片抽检帧格式无效")
        frame_path = _safe_artifact(frame.get("path"), f"第 {index} 个整片抽检帧")
        _require_hash(frame_path, frame.get("sha256"), f"第 {index} 个整片抽检帧")
    confirmations = {
        f"check:{key}": {"label": key, "criteria": [key]}
        for key in sorted(checks)
    }
    return {
        "video_paths": [str(candidate)],
        "video_sha256s": [candidate_sha],
        "preview_path": str(contact),
        "preview_sha256": contact_sha,
        "machine_packet_path": str(packet),
        "machine_packet_sha256": packet_sha,
        "candidate_audit_path": str(audit),
        "candidate_audit_sha256": audit_sha,
        "required_checks": sorted(confirmations),
        "required_confirmations": confirmations,
        "required_playback_seconds": duration,
    }


def _database_connection() -> sqlite3.Connection:
    if not CLOSED_LOOP_DB_PATH.is_file():
        raise ValueError(f"闭环数据库不存在：{CLOSED_LOOP_DB_PATH}")
    connection = sqlite3.connect(str(CLOSED_LOOP_DB_PATH), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    required_tables = {
        "alembic_version", "fanqie_promotion_tasks", "fanqie_video_jobs",
        "fanqie_reviews", "fanqie_operation_events",
    }
    if not required_tables.issubset(tables):
        connection.close()
        raise ValueError("所选数据库不是完整的番茄闭环数据库")
    versions = {
        str(row[0]) for row in connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchall()
    }
    if EXPECTED_CLOSED_LOOP_ALEMBIC_HEAD not in versions:
        connection.close()
        raise ValueError(
            "番茄闭环数据库迁移版本不匹配："
            f"需要 {EXPECTED_CLOSED_LOOP_ALEMBIC_HEAD}，实际 {sorted(versions)}"
        )
    columns = {
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info(fanqie_operation_events)"
        ).fetchall()
    }
    required = {
        "event_uuid", "task_id", "event_type", "actor_type", "actor_id",
        "from_status", "to_status", "payload_json", "artifact_path",
        "audit_artifact_hash", "created_at",
    }
    if not required.issubset(columns):
        connection.close()
        raise ValueError("闭环数据库缺少 fanqie_operation_events 审计结构")
    return connection


def _event_uuid(action: str, path: Path, review_sha256: str) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"fanqie-v61-frontend-review:{action}:{path}:{review_sha256}",
        )
    )


def _append_event(
    *,
    action: str,
    path: Path,
    review_sha256: str,
    actor_id: str,
    review_type: str,
    payload: dict[str, Any],
) -> str:
    event_uuid = _event_uuid(action, path, review_sha256)
    task_id = payload.get("target_promotion_task_id")
    event_payload = {
        "action": action,
        "review_type": review_type,
        "review_path": str(path),
        **payload,
    }
    payload_json = json.dumps(
        event_payload, ensure_ascii=False, sort_keys=True,
    )
    connection = _database_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT OR IGNORE INTO fanqie_operation_events(
                event_uuid, task_id, event_type, from_status, to_status,
                actor_type, actor_id, payload_json, artifact_path,
                audit_artifact_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_uuid, task_id, DECISION_EVENT_TYPE,
                None, None,
                "human" if action != "review_queued" else "system",
                actor_id[:64],
                payload_json,
                str(path), review_sha256,
                datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
            ),
        )
        stored = connection.execute(
            """
            SELECT task_id, event_type, actor_type, actor_id, payload_json,
                   artifact_path, audit_artifact_hash
            FROM fanqie_operation_events WHERE event_uuid = ?
            """,
            (event_uuid,),
        ).fetchone()
        expected_actor_type = "human" if action != "review_queued" else "system"
        if (
            stored is None
            or stored[0] != task_id
            or stored[1] != DECISION_EVENT_TYPE
            or stored[2] != expected_actor_type
            or stored[3] != actor_id[:64]
            or stored[4] != payload_json
            or Path(str(stored[5] or "")).resolve() != path
            or str(stored[6] or "").upper() != review_sha256
        ):
            raise ValueError("数据库中存在冲突的审核审计事件")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return event_uuid


def _decision_event_exists(
    *,
    action: str,
    path: Path,
    review_sha256: str,
    actor_id: str,
    review_type: str,
    evidence: dict[str, Any],
    target_promotion_task_id: Any,
) -> tuple[bool, str]:
    """Require the database event to reproduce the complete frontend decision.

    Merely finding the deterministic event UUID is not enough: a stale,
    truncated or manually inserted row must not make a final JSON file appear
    audited in the frontend.
    """
    event_uuid = _event_uuid(action, path, review_sha256)
    connection = _database_connection()
    try:
        row = connection.execute(
            """
            SELECT task_id, actor_type, actor_id, payload_json, artifact_path,
                   audit_artifact_hash
            FROM fanqie_operation_events WHERE event_uuid = ?
            """,
            (event_uuid,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        return False, event_uuid
    try:
        payload = json.loads(str(row[3] or "{}"))
    except json.JSONDecodeError:
        return False, event_uuid
    expected_status = action.removeprefix("review_")
    expected_video_hashes = [
        str(value or "").upper()
        for value in evidence.get("video_sha256s") or []
    ]
    stored_video_hashes = [
        str(value or "").upper()
        for value in payload.get("video_sha256s") or []
    ] if isinstance(payload, dict) else []
    valid = (
        isinstance(payload, dict)
        and row[0] == target_promotion_task_id
        and row[1] == "human"
        and row[2] == actor_id
        and payload.get("action") == action
        and payload.get("review_type") == review_type
        and Path(str(payload.get("review_path") or "")).resolve() == path
        and payload.get("review_status") == expected_status
        and payload.get("decision_source") == "authenticated_streamlit_frontend"
        and payload.get("target_promotion_task_id") == target_promotion_task_id
        and str(payload.get("resulting_review_sha256") or "").upper()
        == review_sha256
        and stored_video_hashes == expected_video_hashes
        and str(payload.get("machine_packet_sha256") or "").upper()
        == str(evidence.get("machine_packet_sha256") or "").upper()
        and Path(str(row[4] or "")).resolve() == path
        and str(row[5] or "").upper() == review_sha256
    )
    return valid, event_uuid


def enqueue_review(path: str | Path) -> dict[str, Any]:
    """Idempotently append the valid pending candidate to the DB audit stream."""
    review_path = _safe_review_path(path)
    value = _load(review_path)
    review_type = SUPPORTED_SCHEMAS.get(str(value.get("schema_version") or ""))
    if not review_type:
        raise ValueError("不是受支持的番茄 V6.1/V6.2/V6.3 审核文件")
    if _status(value) != "pending_review":
        raise ValueError("只有待审核候选可以进入审核队列")
    evidence = _evidence(value, review_type)
    review_sha = _sha256(review_path)
    try:
        event_uuid = _append_event(
            action="review_queued", path=review_path, review_sha256=review_sha,
            actor_id="frontend_review_queue", review_type=review_type,
            payload={
                "review_status": "pending_review",
                "target_promotion_task_id": value.get("target_promotion_task_id"),
                "machine_packet_sha256": evidence["machine_packet_sha256"],
                "video_sha256s": evidence["video_sha256s"],
            },
        )
    except sqlite3.DatabaseError as exc:
        raise ValueError(f"待审核数据库事件写入失败：{exc}") from exc
    return {
        "event_uuid": event_uuid,
        "review_sha256": review_sha,
        "database_path": str(CLOSED_LOOP_DB_PATH),
    }


def list_reviews(
    status: str | None = None, *, sync_database: bool = False,
) -> list[dict[str, Any]]:
    """Discover real V6.1/V6.2/V6.3 candidates; templates never enter the queue."""
    items: list[dict[str, Any]] = []
    review_paths = {
        *QA_ROOT.glob("task1_story_v61*review*.json"),
        *QA_ROOT.glob("task1_story_v62*review*.json"),
        *QA_ROOT.glob("task1_story_v63*review*.json"),
    }
    for path in sorted(review_paths):
        try:
            value = _load(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        review_type = SUPPORTED_SCHEMAS.get(str(value.get("schema_version") or ""))
        if not review_type:
            continue
        item_status = _status(value)
        evidence: dict[str, Any] = {}
        validation_error = ""
        try:
            evidence = _evidence(value, review_type)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            validation_error = str(exc)
            if item_status == "pending_review":
                item_status = "invalid"
            elif item_status in {"approved", "rejected"}:
                item_status = "audit_error"
        database_status = "not_synced"
        database_error = ""
        database_event_uuid = ""
        if sync_database and item_status == "pending_review" and not validation_error:
            try:
                queued = enqueue_review(path)
                database_status = "queued"
                database_event_uuid = queued["event_uuid"]
            except (OSError, ValueError, sqlite3.DatabaseError) as exc:
                database_status = "error"
                database_error = str(exc)
        elif sync_database and item_status in {"approved", "rejected"}:
            action = f"review_{item_status}"
            try:
                exists, database_event_uuid = _decision_event_exists(
                    action=action, path=path, review_sha256=_sha256(path),
                    actor_id=str(value.get("reviewer") or ""),
                    review_type=review_type,
                    evidence=evidence,
                    target_promotion_task_id=value.get(
                        "target_promotion_task_id"
                    ),
                )
                if exists:
                    database_status = "decided"
                else:
                    database_status = "decision_event_missing"
                    database_error = "最终审核文件缺少对应的数据库决定事件"
                    item_status = "audit_error"
            except (OSError, ValueError, sqlite3.DatabaseError) as exc:
                database_status = "error"
                database_error = str(exc)
                item_status = "audit_error"
        if status and item_status != status:
            continue
        video_paths = list(evidence.get("video_paths") or [])
        items.append({
            "path": str(path.resolve()),
            "name": path.stem,
            "review_type": review_type,
            "status": item_status,
            "reviewer": str(value.get("reviewer") or ""),
            "reviewed_at": value.get("reviewed_at"),
            "notes": str(value.get("notes") or ""),
            "preview_path": str(evidence.get("preview_path") or ""),
            "video_path": str(video_paths[0]) if video_paths else "",
            "video_paths": video_paths,
            "required_checks": list(evidence.get("required_checks") or []),
            "required_confirmations": dict(
                evidence.get("required_confirmations") or {}
            ),
            "required_playback_seconds": float(
                evidence.get("required_playback_seconds") or 0
            ),
            "review_sha256": _sha256(path),
            "validation_error": validation_error,
            "database_status": database_status,
            "database_error": database_error,
            "database_event_uuid": database_event_uuid,
            "database_path": str(CLOSED_LOOP_DB_PATH),
            "mtime": path.stat().st_mtime,
        })
    return sorted(items, key=lambda item: item["mtime"], reverse=True)


def decide_review(
    path: str | Path,
    *,
    decision: str,
    reviewer: str,
    notes: str = "",
    expected_review_sha256: str,
    confirmations: dict[str, bool] | None = None,
    playback_started_at: str | None = None,
    playback_finished_at: str | None = None,
) -> dict[str, Any]:
    """Perform exactly one pending -> approved/rejected audited transition."""
    review_path = _safe_review_path(path)
    reviewer = reviewer.strip()
    if len(reviewer) < 2 or len(reviewer) > 64:
        raise ValueError("审核人必须是 2～64 字符的已登录账号")
    if decision not in {"approved", "rejected"}:
        raise ValueError("审核决定只能是 approved 或 rejected")
    if decision == "rejected" and not notes.strip():
        raise ValueError("驳回必须填写原因")

    with _review_lock(review_path):
        original_bytes = review_path.read_bytes()
        current_sha = hashlib.sha256(original_bytes).hexdigest().upper()
        if str(expected_review_sha256 or "").upper() != current_sha:
            raise ValueError("审核文件已变化，请刷新页面后重新审核")
        value = _load(review_path)
        review_type = SUPPORTED_SCHEMAS.get(str(value.get("schema_version") or ""))
        if not review_type:
            raise ValueError("不是受支持的番茄 V6.1/V6.2/V6.3 审核文件")
        if _status(value) != "pending_review":
            raise ValueError("该任务已经做出最终决定，不能覆盖原审核结果")
        evidence = _evidence(value, review_type)

        playback_started: datetime | None = None
        playback_finished: datetime | None = None
        if decision == "approved":
            supplied = confirmations or {}
            required_confirmations = evidence["required_confirmations"]
            if set(supplied) != set(required_confirmations):
                raise ValueError("通过前必须逐项提交页面列出的全部审核项")
            missing = [key for key, confirmed in supplied.items() if confirmed is not True]
            if missing:
                raise ValueError("以下审核项尚未确认：" + ", ".join(sorted(missing)))
            playback_started = _parse_timestamp(
                playback_started_at, "播放开始时间"
            )
            playback_finished = _parse_timestamp(
                playback_finished_at, "播放完成时间"
            )
            elapsed = (playback_finished - playback_started).total_seconds()
            required = float(evidence["required_playback_seconds"])
            if playback_finished <= playback_started or elapsed + 0.25 < required:
                raise ValueError(
                    f"完整播放计时不足：需要至少 {required:.2f} 秒，实际 {elapsed:.2f} 秒"
                )
            if playback_finished > datetime.now(timezone.utc):
                raise ValueError("播放完成时间不能晚于当前时间")

        now = datetime.now(timezone.utc)
        value["review_status"] = decision
        value["decision"] = decision
        value["reviewer"] = reviewer
        value["reviewer_id"] = reviewer
        value["reviewed_at"] = now.isoformat()
        value["notes"] = notes.strip()
        value.pop("signature_path", None)
        value["decision_source"] = "authenticated_streamlit_frontend"
        value["previous_review_sha256"] = current_sha

        if decision == "approved":
            assert playback_started is not None and playback_finished is not None
            value["playback_started_at"] = playback_started.isoformat()
            value["playback_finished_at"] = playback_finished.isoformat()
            value["frontend_attestation"] = {
                "all_required_checks_confirmed": True,
                "confirmations": dict(sorted(supplied.items())),
                "required_checks": evidence["required_checks"],
                "required_playback_seconds": evidence["required_playback_seconds"],
                "actual_playback_seconds": (
                    playback_finished - playback_started
                ).total_seconds(),
                "video_sha256s": evidence["video_sha256s"],
                "machine_packet_sha256": evidence["machine_packet_sha256"],
            }
            if review_type == "smoke":
                gates = value.get("global_gates")
                if isinstance(gates, dict):
                    for key in gates:
                        gates[key] = True
                for shot in value.get("shots") or []:
                    if not isinstance(shot, dict):
                        continue
                    shot["decision"] = "approved"
                    for key, current in list(shot.items()):
                        if current is None and key not in SHOT_METADATA_KEYS:
                            shot[key] = True
            else:
                checks = value.get("checks")
                if isinstance(checks, dict):
                    for key in checks:
                        checks[key] = True

        # Queue evidence must exist in the DB before a final decision can be
        # emitted. This is idempotent and does not mutate the review file.
        enqueue_review(review_path)
        _write_atomic(review_path, value)
        resulting_sha = _sha256(review_path)
        try:
            event_uuid = _append_event(
                action=f"review_{decision}", path=review_path,
                review_sha256=resulting_sha, actor_id=reviewer,
                review_type=review_type,
                payload={
                    "review_status": decision,
                    "decision_source": "authenticated_streamlit_frontend",
                    "target_promotion_task_id": value.get(
                        "target_promotion_task_id"
                    ),
                    "previous_review_sha256": current_sha,
                    "resulting_review_sha256": resulting_sha,
                    "video_sha256s": evidence["video_sha256s"],
                    "machine_packet_sha256": evidence["machine_packet_sha256"],
                    "notes": notes.strip(),
                },
            )
        except Exception as exc:
            _write_bytes_atomic(review_path, original_bytes)
            if isinstance(exc, sqlite3.DatabaseError):
                raise ValueError(f"最终审核数据库事件写入失败：{exc}") from exc
            raise

    return {
        "path": str(review_path),
        "review_type": review_type,
        "status": _status(value),
        "reviewer": reviewer,
        "reviewed_at": value["reviewed_at"],
        "review_sha256": resulting_sha,
        "database_event_uuid": event_uuid,
        "database_path": str(CLOSED_LOOP_DB_PATH),
    }
