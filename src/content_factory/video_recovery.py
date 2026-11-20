"""Turn rejected AI-video reports into one controlled recovery action."""

from __future__ import annotations

import json
from pathlib import Path

from src.content_factory.video_control_policy import VideoShotIntent


MANIFEST_TEMPLATE = "video_recovery/v1"
REPORT_TEMPLATE = "video_recovery_report/v1"

LEGACY_CHECK_MAP = {
    "character_identity": "identity_consistency",
    "hands_and_fingers": "hand_anatomy",
    "phone_pose_stability": "phone_position",
    "background_stability": "static_background",
    "camera_stability": "camera_constraint",
    "flicker_and_morphing": "flicker",
    "assigned_micro_action_only": "motion_scope",
    "technical_specification": "technical_metadata",
}
TECHNICAL_FAILURES = {
    "file_missing",
    "scan_failed",
    "samples_insufficient",
    "technical_metadata",
    "video_stream_missing",
    "duration_invalid",
    "duration_mismatch",
    "fps_mismatch",
    "codec_mismatch",
    "pixel_format_mismatch",
}
HAND_OBJECT_FAILURES = {
    "hand_anatomy",
    "hand_position",
    "phone_position",
    "single_phone",
    "hand_object_contact",
}
BACKGROUND_FAILURES = {
    "static_background",
    "static_region_changed",
    "reference_lock_failed",
}
LIGHTING_FAILURES = {
    "lighting_stability",
    "lighting_flicker",
    "color_flicker",
    "background_light_match",
    "skin_tone",
    "lighting_exposure_mismatch",
    "lighting_color_cast_mismatch",
    "lighting_contrast_mismatch",
    "lighting_temporal_drift",
}
DIRECTIONAL_LIGHT_FAILURES = {
    "light_direction",
    "light_direction_mismatch",
    "local_exposure",
    "subject_light_mismatch",
}
FLICKER_FAILURES = {"lighting_flicker", "color_flicker"}
FLICKER_DERIVED_FAILURES = {
    "lighting_flicker",
    "color_flicker",
    "motion_too_large",
    "anchor_drift",
    "active_area_too_large",
}
MOTION_LARGE_FAILURES = {
    "motion_scope",
    "motion_too_large",
    "anchor_drift",
    "active_area_too_large",
    "region_motion_too_large",
    "region_anchor_drift",
    "region_active_area_too_large",
    "flicker",
}
MOTION_MISSING_FAILURES = {
    "motion_missing",
    "dynamic_region_static",
    "motion_too_subtle",
}
SMOOTHNESS_FAILURES = {
    "cadence_stutter",
    "duplicate_frames",
    "judder",
    "low_frame_rate",
}
FULL_FRAME_MOTION_FAILURES = {
    "full_frame_motion_missing",
    "scene_too_static",
    "static_storyboard",
}
STYLE_FAILURES = {
    "render_style_mismatch",
    "style_lineart_mismatch",
    "style_palette_mismatch",
    "temporal_style_drift",
}


def recommend_video_recovery(manifest_path: str | Path) -> dict[str, object]:
    path = Path(manifest_path).resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("template") != MANIFEST_TEMPLATE:
        raise ValueError(f"template must be {MANIFEST_TEMPLATE}")

    recovery_id = _required_string(data, "id")
    control_path = _optional_path(path, data, "control_report")
    review_path = _optional_path(path, data, "review_report")
    plan_path = _optional_path(path, data, "plan_report")
    inventory_path = _optional_path(path, data, "inventory_report")
    shot_id = _optional_string(data, "shot_id")
    if (plan_path is None) != (shot_id is None):
        raise ValueError("plan_report and shot_id must be provided together")
    if control_path is None and review_path is None:
        raise ValueError("control_report or review_report is required")

    control = _read_json(control_path)
    review = _read_json(review_path)
    route = _load_route(plan_path, shot_id)
    raw_intent = data.get("intent")
    if raw_intent is None:
        raw_intent = control.get("metadata", {}).get("intent")
    if raw_intent is None:
        raw_intent = route.get("intent")
    intent = VideoShotIntent.from_dict(raw_intent) if raw_intent is not None else None
    current_tool = _optional_string(data, "current_tool")
    current_tool = current_tool or _infer_current_tool(control, review, route)
    failures, pending_review = _collect_failures(control, review)
    attempt_count = _attempt_count(data, review)
    inventory = _inventory_status(inventory_path)

    if pending_review:
        recovery = _blocked_recovery(
            "manual_review_pending",
            "人工抽帧验收尚未完成，不能修改参数或继续批量生成。",
        )
    elif not failures:
        recovery = {
            "status": "no_action",
            "generation_allowed": True,
            "action": "continue_pipeline",
            "next_tool": current_tool,
            "next_mode": route.get("control_mode"),
            "single_change": None,
            "reason": "现有机器和人工报告没有失败项。",
            "required_assets": [],
            "locked_fields": [],
        }
    else:
        recovery = _choose_recovery(
            failures,
            intent=intent,
            current_tool=current_tool,
            attempt_count=attempt_count,
            inventory=inventory,
        )

    recovery["agent_instructions"] = _agent_instructions(
        recovery,
        failures,
        current_tool=current_tool,
    )
    return {
        "template": REPORT_TEMPLATE,
        "id": recovery_id,
        "source_manifest": str(path),
        "status": recovery["status"],
        "generation_allowed": recovery["generation_allowed"],
        "current_tool": current_tool,
        "attempt_count": attempt_count,
        "failure_codes": sorted(failures),
        "intent": intent.to_dict() if intent else None,
        "route": recovery,
    }


def write_video_recovery_report(
    manifest_path: str | Path,
    output_path: str | Path,
) -> dict[str, object]:
    report = recommend_video_recovery(manifest_path)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def _choose_recovery(
    failures: set[str],
    *,
    intent: VideoShotIntent | None,
    current_tool: str | None,
    attempt_count: int,
    inventory: dict[str, str],
) -> dict[str, object]:
    if failures & TECHNICAL_FAILURES:
        return _actionable_recovery(
            action="reencode_technical",
            next_tool="ffmpeg",
            next_mode=None,
            field="encoding_profile",
            previous="source",
            value="h264_yuv420p_target_fps",
            reason="先修复容器、编码、帧率或时长；不要重新生成画面。",
        )

    if "lip_sync" in failures:
        if inventory.get("sonic") == "ready":
            return _actionable_recovery(
                action="switch_tool",
                next_tool="sonic",
                next_mode="micro_motion",
                field="resolved_tool",
                previous=current_tool,
                value="sonic",
                reason="口型同步失败，应切换专用音频肖像模型，不再调整画面提示词。",
                required_assets=("reference_image", "driven_audio"),
            )
        return _blocked_recovery(
            "lip_sync_tool_unavailable",
            "精准口型失败且 Sonic 未被本机库存确认 ready；禁止退回普通 I2V 碰运气。",
        )

    hands_or_phone = bool(failures & HAND_OBJECT_FAILURES)
    if intent is not None:
        hands_or_phone = hands_or_phone or intent.contains_hands or intent.contains_phone
    if hands_or_phone and (
        intent is None
        or intent.motion in {"none", "micro"}
        or attempt_count >= 3
    ):
        return _actionable_recovery(
            action="switch_tool",
            next_tool="deterministic_2d_compositor",
            next_mode="pixel_locked",
            field="resolved_tool",
            previous=current_tool,
            value="deterministic_2d_compositor",
            reason="手或手机在微动作镜头中漂移，继续改提示词没有控制力，应锁定原图像素。",
            required_assets=("reference_image", "deterministic_motion/v1"),
        )

    if failures & BACKGROUND_FAILURES:
        return _actionable_recovery(
            action="apply_postprocess",
            next_tool=current_tool,
            next_mode="subject_only",
            field="postprocess.static_background_composite",
            previous=False,
            value=True,
            reason="人物可继续使用现有动态，但必须回贴原始静态背景。",
            required_assets=("reference_image", "subject_mask"),
        )

    if failures & FLICKER_FAILURES and failures <= FLICKER_DERIVED_FAILURES:
        return _actionable_recovery(
            action="apply_postprocess",
            next_tool=current_tool,
            next_mode=None,
            field="postprocess.temporal_repair",
            previous=False,
            value="luma_gain_reference",
            reason="失败只包含曝光/色度闪烁及其全局差分派生项，应先做受控时序修复。",
            required_assets=(
                "input_control_manifest",
                "input_control_report",
                "reference_image",
            ),
        )

    if failures & DIRECTIONAL_LIGHT_FAILURES:
        return _actionable_recovery(
            action="replace_preprocess_asset",
            next_tool="keyframe_relight",
            next_mode="pixel_locked",
            field="preprocess.keyframe_relight",
            previous=False,
            value=True,
            reason=(
                "光源方向或局部曝光错误应先修批准关键帧；禁止逐帧重绘视频。"
            ),
            required_assets=("reference_image", "approved_relight_mask"),
        )

    if failures & SMOOTHNESS_FAILURES:
        return _actionable_recovery(
            action="apply_postprocess",
            next_tool="smoothness_repair",
            next_mode=None,
            field="postprocess.video_smoothness",
            previous=False,
            value="minterpolate_gated",
            reason=(
                "结构已通过但节奏卡顿时，插帧必须以重复帧、速度突变和运动"
                "保留率的前后证据决定是否采用。"
            ),
            required_assets=(
                "input_control_manifest",
                "input_control_report",
            ),
        )

    if failures & FULL_FRAME_MOTION_FAILURES:
        return _actionable_recovery(
            action="switch_tool",
            next_tool="deterministic_camera",
            next_mode="free",
            field="resolved_tool",
            previous=current_tool,
            value="deterministic_camera",
            reason=(
                "整幅静态故事板需要可见动态时，应使用受限全屏推拉，而不是"
                "分屏或重新生成手、脸和手机。"
            ),
            required_assets=("reference_image",),
        )

    if failures & STYLE_FAILURES:
        return _actionable_recovery(
            action="replace_source_asset",
            next_tool=current_tool,
            next_mode=None,
            field="reference_image",
            previous="current_keyframe",
            value="approved_style_keyframe",
            reason=(
                "跨镜头画风失败时必须回到批准画风关键帧；调提示词、插帧或"
                "Deflicker 不能修复线稿和渲染方式。"
            ),
            required_assets=("approved_style_reference",),
        )

    if failures & LIGHTING_FAILURES:
        return _actionable_recovery(
            action="apply_postprocess",
            next_tool=current_tool,
            next_mode=None,
            field="postprocess.reference_appearance_lock",
            previous=False,
            value=True,
            reason="保留当前运动，只把颜色和光线投回批准参考图。",
            required_assets=("reference_image", "subject_mask"),
        )

    if "identity_consistency" in failures:
        if (
            intent is not None
            and intent.motion == "micro"
            and intent.framing in {"detail", "head_shoulders"}
            and not intent.contains_hands
            and not intent.contains_phone
            and not intent.lip_sync_required
        ):
            return _actionable_recovery(
                action="switch_tool",
                next_tool="liveportrait",
                next_mode="micro_motion",
                field="resolved_tool",
                previous=current_tool,
                value="liveportrait",
                reason="无手部头肩微动应使用 LivePortrait，避免扩散模型重画身份。",
                required_assets=("reference_image", "face_driver_or_motion_template"),
            )
        return _blocked_recovery(
            "identity_source_or_tool_change_required",
            "身份不一致且没有安全的单参数修复；需要重新选择人物源图或专用人物驱动工具。",
        )

    if failures & MOTION_LARGE_FAILURES:
        if intent is not None and intent.motion == "micro":
            next_tool = (
                "liveportrait"
                if intent.framing in {"detail", "head_shoulders"}
                and not intent.contains_hands
                and not intent.contains_phone
                else "deterministic_2d_compositor"
            )
            next_mode = "micro_motion" if next_tool == "liveportrait" else "pixel_locked"
            return _actionable_recovery(
                action="switch_tool",
                next_tool=next_tool,
                next_mode=next_mode,
                field="resolved_tool",
                previous=current_tool,
                value=next_tool,
                reason="微动作幅度持续超限，应更换为局部人物驱动或确定性像素锁定。",
                required_assets=("reference_image",),
            )
        return _actionable_recovery(
            action="replace_driver_asset",
            next_tool=current_tool,
            next_mode="subject_only",
            field="driver_video",
            previous="current_driver",
            value="clean_locked_camera_single_subject_driver",
            reason="主体动作过大时只更换驱动素材，不同时调整 seed、提示词和采样参数。",
            required_assets=("driver_video", "subject_mask"),
        )

    if failures & MOTION_MISSING_FAILURES:
        return _actionable_recovery(
            action="adjust_one_parameter",
            next_tool=current_tool,
            next_mode=None,
            field="effect.opacity_or_motion_amplitude",
            previous="current",
            value="increase_one_step",
            reason="动态不可见，只提高一个效果强度参数，其他参数保持不变。",
        )

    return _blocked_recovery(
        "unmapped_failure",
        "失败项没有安全的自动恢复映射，需要人工确认后再增加规则。",
    )


def _actionable_recovery(
    *,
    action: str,
    next_tool: str | None,
    next_mode: str | None,
    field: str,
    previous: object,
    value: object,
    reason: str,
    required_assets: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "status": "actionable",
        "generation_allowed": True,
        "action": action,
        "next_tool": next_tool,
        "next_mode": next_mode,
        "single_change": {
            "field": field,
            "from": previous,
            "to": value,
        },
        "reason": reason,
        "required_assets": list(required_assets),
        "locked_fields": [
            "seed",
            "prompt",
            "negative_prompt",
            "steps",
            "cfg",
            "sampler",
            "resolution",
            "duration",
        ],
    }


def _blocked_recovery(code: str, reason: str) -> dict[str, object]:
    return {
        "status": "blocked",
        "generation_allowed": False,
        "action": code,
        "next_tool": None,
        "next_mode": None,
        "single_change": None,
        "reason": reason,
        "required_assets": [],
        "locked_fields": [],
    }


def _agent_instructions(
    recovery: dict[str, object],
    failures: set[str],
    *,
    current_tool: str | None,
) -> dict[str, str]:
    failure_text = ", ".join(sorted(failures)) or "none"
    if recovery["status"] == "actionable":
        change = recovery["single_change"]
        assert isinstance(change, dict)
        hermes = (
            f"保留当前批准素材。只准备 {recovery['required_assets']}；"
            f"不得修改 {recovery['locked_fields']}。"
        )
        claude = (
            f"当前工具={current_tool}，失败项={failure_text}。"
            f"下一轮只修改 {change['field']}: {change['from']} -> {change['to']}；"
            "执行后重新生成 control report 和 review packet，未通过即停止。"
        )
    elif recovery["status"] == "no_action":
        hermes = "不再生成候选；保留当前批准素材。"
        claude = "现有报告已通过，可进入配音或故事合成。"
    else:
        hermes = "停止准备新候选，等待缺失模型、素材或人工结论。"
        claude = f"停止队列。失败项={failure_text}；原因：{recovery['reason']}"
    return {"hermes": hermes, "claude_code": claude}


def _collect_failures(
    control: dict[str, object],
    review: dict[str, object],
) -> tuple[set[str], bool]:
    failures: set[str] = set()
    if control:
        raw_issues = control.get("issues", [])
        if isinstance(raw_issues, list):
            for issue in raw_issues:
                if isinstance(issue, dict) and issue.get("severity", "error") == "error":
                    code = issue.get("code")
                    if isinstance(code, str) and code:
                        failures.add(code)

    pending = review.get("status") == "pending_manual_review"
    failed_checks = review.get("failed_checks", [])
    if isinstance(failed_checks, list):
        failures.update(
            item for item in failed_checks if isinstance(item, str) and item
        )
    category_checks = review.get("category_checks", {})
    if isinstance(category_checks, dict):
        for name, status in category_checks.items():
            if isinstance(name, str) and str(status).upper().startswith("FAIL"):
                failures.add(LEGACY_CHECK_MAP.get(name, name))
    return failures, pending


def _attempt_count(data: dict[str, object], review: dict[str, object]) -> int:
    raw = data.get("attempt_count")
    if raw is not None:
        if not isinstance(raw, int) or isinstance(raw, bool) or raw < 1:
            raise ValueError("attempt_count must be a positive integer")
        return raw
    history = review.get("attempt_history", [])
    if isinstance(history, list) and history:
        return len(history)
    return 1


def _load_route(
    plan_path: Path | None,
    shot_id: str | None,
) -> dict[str, object]:
    if plan_path is None or shot_id is None:
        return {}
    plan = _read_json(plan_path)
    routes = plan.get("routes", [])
    if not isinstance(routes, list):
        raise ValueError("plan_report routes must be an array")
    route = next(
        (
            item
            for item in routes
            if isinstance(item, dict) and item.get("id") == shot_id
        ),
        None,
    )
    if route is None:
        raise ValueError(f"shot_id not found in plan_report: {shot_id}")
    return route


def _infer_current_tool(
    control: dict[str, object],
    review: dict[str, object],
    route: dict[str, object],
) -> str | None:
    route_tool = route.get("resolved_tool") or route.get("primary_tool")
    if isinstance(route_tool, str) and route_tool:
        return route_tool
    recommendation = control.get("metadata", {}).get("recommendation", {})
    if isinstance(recommendation, dict):
        tool = recommendation.get("tool")
        if isinstance(tool, str) and tool:
            return tool
    model = str(review.get("model") or "").lower()
    video_path = str(review.get("video_path") or "").lower()
    if "ltx" in model or "ltx" in video_path:
        return "ltx_i2v"
    if "sadtalker" in model or "sadtalker" in video_path:
        return "sadtalker"
    if "wan" in model or "wan" in video_path:
        return "wan_animate_move"
    return None


def _inventory_status(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    data = _read_json(path)
    capabilities = data.get("capabilities", [])
    if not isinstance(capabilities, list):
        raise ValueError("inventory_report capabilities must be an array")
    result: dict[str, str] = {}
    for item in capabilities:
        if isinstance(item, dict):
            tool = item.get("tool")
            status = item.get("status")
            if isinstance(tool, str) and isinstance(status, str):
                result[tool] = status
    return result


def _read_json(path: Path | None) -> dict[str, object]:
    if path is None:
        return {}
    if not path.is_file():
        raise FileNotFoundError(f"report does not exist: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"report must be a JSON object: {path}")
    return data


def _optional_path(
    manifest_path: Path,
    data: dict[str, object],
    key: str,
) -> Path | None:
    raw = data.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{key} must be a non-empty string or null")
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = manifest_path.parent / candidate
    return candidate.resolve()


def _required_string(data: dict[str, object], key: str) -> str:
    raw = data.get(key)
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return raw.strip()


def _optional_string(data: dict[str, object], key: str) -> str | None:
    raw = data.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{key} must be a non-empty string or null")
    return raw.strip()
