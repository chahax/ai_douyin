"""Compile a checked creative storyboard into locked Seedance request templates.

This module performs local mapping only.  It never creates a remote task and it
never treats a placeholder frame reference as reviewed media.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .seedance_client import SeedanceClient, SeedanceConfig, SeedanceReference


SCHEMA = "creative_seedance_segment_plan/v1"
LEGACY_ADAPTER_ID = "creative_storyboard_to_reviewed_seedance_segments/v1"
PREVIOUS_ADAPTER_ID = "creative_storyboard_to_reviewed_seedance_segments/v2"
ADAPTER_ID = "creative_storyboard_to_reviewed_seedance_segments/v3"
DIALOGUE_MODE_ALIASES = {"画内对白": "画内", "画外对白": "画外", "混合对白": "画内/画外", "无对白": "无对白"}


def _dialogue_mode(shot, normalize):
    mode = shot.get("dialogue_mode", "画内")
    return DIALOGUE_MODE_ALIASES.get(mode, mode) if normalize else mode
SUPPORTED_CONTINUITY = {"raw_tail_continuation", "planned_cut_requires_adapter"}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} 必须为非空文本")
    return value.strip()


def _shot_prompt(style: dict[str, Any], shot: dict[str, Any], *, normalize_mode: bool = True) -> str:
    dialogue = shot.get("dialogue_lock")
    if not isinstance(dialogue, list):
        raise ValueError(f"{shot.get('id', '镜头')} dialogue_lock 必须为列表")
    dialogue_lines = []
    for index, row in enumerate(dialogue):
        if not isinstance(row, dict):
            raise ValueError(f"{shot['id']} dialogue_lock[{index}] 必须为对象")
        dialogue_lines.append(
            f"{_text(row.get('speaker'), 'speaker')}说：{_text(row.get('text'), 'dialogue text')}"
        )
    choices = shot.get("production_choices")
    if not isinstance(choices, list) or any(not isinstance(row, str) for row in choices):
        raise ValueError(f"{shot['id']} production_choices 必须为文本列表")
    parts = [
        f"竖屏 9:16，{_text(style.get('visual_medium'), 'visual_medium')}。",
        f"色彩与光线：{_text(style.get('palette'), 'palette')}；"
        f"{_text(style.get('light_source'), 'light_source')}。",
        f"空间与人物锁定：{_text(style.get('spatial_layout'), 'spatial_layout')}；"
        f"{_text(style.get('character_lock'), 'character_lock')}。",
        f"本段只拍一个连续镜头，时长 {shot['duration_seconds']} 秒，片段内部不切镜、不换场。",
        f"构图：{_text(shot.get('composition'), 'composition')}。",
        f"摄影：{_text(shot.get('camera'), 'camera')}。",
        f"表演和动作：{_text(shot.get('visible_performance'), 'visible_performance')}。",
        f"首帧状态：{_text(shot.get('start_state'), 'start_state')}。",
        f"尾帧状态：{_text(shot.get('end_state'), 'end_state')}。",
        f"事件锁：{_text(shot.get('event_lock'), 'event_lock')}。",
    ]
    for key, label in (("purpose", "本镜信息与反应重点"), ("cut_reason", "剪辑意图（不触发人物动作）")):
        if shot.get(key):
            parts.append(label + "：" + _text(shot[key], key) + "。")
    if dialogue_lines:
        mode = _dialogue_mode(shot, normalize_mode)
        if mode not in {"画内", "画外", "画内/画外", "画内与画外"}:
            raise ValueError("有对白的镜头必须指定画内或画外方式")
        parts.append("仅包含以下" + mode + "对白，人物、文字和顺序不得改变：" + "；".join(dialogue_lines) + "。")
        if "画外" in mode:
            parts.append("画外声音仍属于已锁定说话人；画内听者只作既定反应，不跟随声音对口型。")
    else:
        parts.append("本段没有对白，不增加旁白、画外解释或内心独白。")
    if choices:
        parts.append("制作边界：" + "；".join(row.strip() for row in choices if row.strip()) + "。")
    parts.append("保持人物脸型、发型、年龄感、服装、道具、站位和持物连续；返回原始尾帧供下一段审核。")
    return "".join(parts)


def _legacy_shot_prompt(style: dict[str, Any], shot: dict[str, Any]) -> str:
    dialogue = shot.get("dialogue_lock")
    if not isinstance(dialogue, list):
        raise ValueError(f"{shot.get('id', '镜头')} dialogue_lock 必须为列表")
    dialogue_lines = []
    for index, row in enumerate(dialogue):
        if not isinstance(row, dict):
            raise ValueError(f"{shot['id']} dialogue_lock[{index}] 必须为对象")
        dialogue_lines.append(
            f"{_text(row.get('speaker'), 'speaker')}说：{_text(row.get('text'), 'dialogue text')}"
        )
    choices = shot.get("production_choices")
    if not isinstance(choices, list) or any(not isinstance(row, str) for row in choices):
        raise ValueError(f"{shot['id']} production_choices 必须为文本列表")
    parts = [
        f"竖屏 9:16，{_text(style.get('visual_medium'), 'visual_medium')}。",
        f"色彩与光线：{_text(style.get('palette'), 'palette')}；"
        f"{_text(style.get('light_source'), 'light_source')}。",
        f"空间与人物锁定：{_text(style.get('spatial_layout'), 'spatial_layout')}；"
        f"{_text(style.get('character_lock'), 'character_lock')}。",
        f"本段只拍一个连续镜头，时长 {shot['duration_seconds']} 秒，片段内部不切镜、不换场。",
        f"构图：{_text(shot.get('composition'), 'composition')}。",
        f"摄影：{_text(shot.get('camera'), 'camera')}。",
        f"表演和动作：{_text(shot.get('visible_performance'), 'visible_performance')}。",
        f"首帧状态：{_text(shot.get('start_state'), 'start_state')}。",
        f"尾帧状态：{_text(shot.get('end_state'), 'end_state')}。",
        f"事件锁：{_text(shot.get('event_lock'), 'event_lock')}。",
    ]
    if dialogue_lines:
        parts.append("仅包含以下画内对白，人物、文字和顺序不得改变：" + "；".join(dialogue_lines) + "。")
    else:
        parts.append("本段没有对白，不增加旁白、画外解释或内心独白。")
    if choices:
        parts.append("制作边界：" + "；".join(row.strip() for row in choices if row.strip()) + "。")
    parts.append("保持人物脸型、发型、年龄感、服装、道具、站位和持物连续；返回原始尾帧供下一段审核。")
    return "".join(parts)


def build_seedance_segment_plan(
    script: dict[str, Any], shots: dict[str, Any], capability: dict[str, Any],
    *, config: SeedanceConfig | None = None, _legacy: bool = False, _v2: bool = False,
) -> dict[str, Any]:
    """Build locally validated payload templates without submitting media."""
    if not isinstance(script.get("beats"), list) or not isinstance(shots.get("shots"), list):
        raise ValueError("剧本或分镜缺少列表")
    if not isinstance(shots.get("style"), dict):
        raise ValueError("分镜缺少画风锁")
    if capability.get("schema") not in {
        "creative_media_capability_audit/v1", "creative_media_capability_audit/v2",
    }:
        raise ValueError("媒体能力审计版本不受支持")
    config = config or SeedanceConfig.from_env(require_key=False)
    if (config.provider, config.model) != (capability.get("provider"), capability.get("model")):
        raise ValueError("媒体能力审计与当前 Seedance 配置不一致")
    minimum, maximum = capability.get("duration_min"), capability.get("duration_max")
    if type(minimum) is not int or type(maximum) is not int or minimum < 1 or maximum < minimum:
        raise ValueError("媒体能力审计的时长范围无效")
    audit_rows = capability.get("shots")
    if not isinstance(audit_rows, list):
        raise ValueError("媒体能力审计缺少逐镜记录")
    audit_by_id = {row.get("shot_id"): row for row in audit_rows if isinstance(row, dict)}
    if len(audit_by_id) != len(audit_rows):
        raise ValueError("媒体能力审计含重复或无效镜号")

    beat_ids = {row.get("id") for row in script["beats"] if isinstance(row, dict)}
    segments = []
    blocked_shots = []
    previous_segment_id = None
    with SeedanceClient(config) as client:
        for index, shot in enumerate(shots["shots"]):
            if not isinstance(shot, dict):
                raise ValueError(f"shots[{index}] 必须为对象")
            shot_id = _text(shot.get("id"), f"shots[{index}].id")
            beat_id = _text(shot.get("beat_id"), f"{shot_id}.beat_id")
            if beat_id not in beat_ids:
                raise ValueError(f"{shot_id} 引用了不存在的节拍")
            audit = audit_by_id.get(shot_id)
            if audit is None or audit.get("beat_id") != beat_id:
                raise ValueError(f"{shot_id} 没有匹配的能力审计记录")
            duration = shot.get("duration_seconds")
            fits = type(duration) is int and minimum <= duration <= maximum
            if audit.get("duration_seconds") != duration or audit.get("fits_single_model_request") is not fits:
                raise ValueError(f"{shot_id} 的时长能力审计与分镜不一致")
            continuity = shot.get("continuity_mode")
            if continuity not in SUPPORTED_CONTINUITY:
                raise ValueError(f"{shot_id} 的连续方式未适配: {continuity}")
            segment_id = f"SEG{index + 1:03d}"
            blockers = ["text_version_must_remain_bound", "paid_submit_not_authorized"]
            if index == 0:
                frame_source = "reviewed_opening_frame"
                reference_source = f"asset://pending-reviewed-opening/{shot_id}"
                blockers.append("reviewed_opening_frame_missing")
            elif continuity == "raw_tail_continuation":
                frame_source = "preceding_approved_raw_tail"
                reference_source = f"asset://pending-approved-raw-tail/{previous_segment_id}"
                blockers.extend(("preceding_segment_visual_review_missing", "preceding_original_tail_missing"))
            else:
                frame_source = "reviewed_new_camera_opening_frame"
                reference_source = f"asset://pending-reviewed-cut-opening/{shot_id}"
                blockers.extend(("reviewed_new_camera_opening_frame_missing", "offline_cut_assembly_unverified"))
            mode_invalid = (not _legacy and bool(shot.get("dialogue_lock"))
                            and _dialogue_mode(shot, not _v2) not in {"画内", "画外", "画内/画外", "画内与画外"})
            if not fits or mode_invalid:
                blockers.append("dialogue_mode_revision_required" if mode_invalid else "duration_revision_or_semantic_segment_split_required")
                payload = None
                payload_hash = None
                blocked_shots.append(shot_id)
            else:
                prompt = (_legacy_shot_prompt(shots["style"], shot) if _legacy
                          else _shot_prompt(shots["style"], shot, normalize_mode=not _v2))
                payload = client.build_task_payload(
                    prompt, duration=duration, ratio="9:16", resolution="480p",
                    generate_audio=True, return_last_frame=True,
                    references=[SeedanceReference("image", reference_source, "first_frame")],
                )
                payload_hash = _hash(payload)
            segment = {
                "segment_id": segment_id,
                "shot_id": shot_id,
                "beat_id": beat_id,
                "shot_sha256": _hash(shot),
                "duration_seconds": duration,
                "continuity_mode": continuity,
                "opening_frame_source": frame_source,
                "predecessor_segment_id": previous_segment_id,
                "payload_template": payload,
                "payload_template_sha256": payload_hash,
                "blockers_before_submit": blockers,
                "submission_ready": False,
                "actual_task_id": None,
                "actual_video_review": "not_performed",
            }
            segments.append(segment)
            previous_segment_id = segment_id
    if set(audit_by_id) != {row["shot_id"] for row in segments}:
        raise ValueError("媒体能力审计与分镜镜号集合不一致")
    return {
        "schema": SCHEMA,
        "adapter_id": LEGACY_ADAPTER_ID if _legacy else PREVIOUS_ADAPTER_ID if _v2 else ADAPTER_ID,
        "script_sha256": _hash(script),
        "shots_sha256": _hash(shots),
        "capability_audit_sha256": _hash(capability),
        "provider": capability["provider"],
        "model": capability["model"],
        "ratio": "9:16",
        "resolution": "480p",
        "segments": segments,
        "blocked_shots": blocked_shots,
        "mapping_status": "partial_mapping_blocked" if blocked_shots else "mapped_submission_locked",
        "remote_request_sent": False,
        "automatic_submit": False,
        "video_review_status": "not_performed",
    }


def validate_seedance_segment_plan(
    plan: dict[str, Any], script: dict[str, Any], shots: dict[str, Any],
    capability: dict[str, Any], *, config: SeedanceConfig | None = None,
) -> None:
    expected = build_seedance_segment_plan(script, shots, capability, config=config,
                                           _legacy=plan.get("adapter_id") == LEGACY_ADAPTER_ID,
                                           _v2=plan.get("adapter_id") == PREVIOUS_ADAPTER_ID)
    if plan != expected:
        raise ValueError("Seedance 分段计划与当前剧本、分镜或执行器不一致")
