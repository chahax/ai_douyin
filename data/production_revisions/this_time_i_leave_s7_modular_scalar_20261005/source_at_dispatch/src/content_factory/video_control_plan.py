"""Compile multiple shot intents into executable local video-control routes."""

from __future__ import annotations

import json
from pathlib import Path

from src.content_factory.video_control_policy import (
    VideoControlRecommendation,
    VideoShotIntent,
    recommend_video_control,
)
from src.content_factory.video_tool_inventory import (
    VideoToolInventory,
    recommendation_readiness,
)


PLAN_TEMPLATE = "video_control_plan/v1"
REPORT_TEMPLATE = "video_control_plan_report/v1"
VIRTUAL_TOOL_GROUPS = {
    "wan_or_ltx_i2v": ("ltx_i2v", "wan_animate_move"),
}


def compile_video_control_plan(
    manifest_path: str | Path,
    inventory: VideoToolInventory,
) -> dict[str, object]:
    path = Path(manifest_path).resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("template") != PLAN_TEMPLATE:
        raise ValueError(f"template must be {PLAN_TEMPLATE}")

    plan_id = _required_string(data, "id")
    defaults = data.get("defaults", {})
    if not isinstance(defaults, dict):
        raise ValueError("defaults must be an object")
    allow_fallback = _boolean(data, "allow_fallback", False)
    raw_shots = data.get("shots")
    if not isinstance(raw_shots, list) or not raw_shots:
        raise ValueError("shots must be a non-empty array")

    shot_ids: set[str] = set()
    routes: list[dict[str, object]] = []
    for index, raw_shot in enumerate(raw_shots):
        if not isinstance(raw_shot, dict):
            raise ValueError(f"shots[{index}] must be an object")
        shot_id = _required_string(raw_shot, "id")
        if shot_id in shot_ids:
            raise ValueError(f"duplicate shot id: {shot_id}")
        shot_ids.add(shot_id)

        raw_intent = raw_shot.get("intent", {})
        if not isinstance(raw_intent, dict):
            raise ValueError(f"shots[{index}].intent must be an object")
        intent = VideoShotIntent.from_dict({**defaults, **raw_intent})
        recommendation = recommend_video_control(intent)
        readiness = recommendation_readiness(recommendation.tool, inventory)
        route_allow_fallback = _boolean(
            raw_shot,
            "allow_fallback",
            allow_fallback,
        )
        resolved_tool, route_status = _resolve_tool(
            recommendation,
            readiness,
            inventory,
            route_allow_fallback,
        )
        routes.append(
            {
                "id": shot_id,
                "intent": intent.to_dict(),
                "control_mode": recommendation.mode,
                "primary_tool": recommendation.tool,
                "resolved_tool": resolved_tool,
                "route_status": route_status,
                "generation_allowed": route_status in {"ready", "ready_fallback"},
                "risk": recommendation.risk,
                "required_assets": list(recommendation.required_assets),
                "postprocess": list(recommendation.postprocess),
                "warnings": list(recommendation.warnings),
                "readiness": readiness,
                "acceptance_checks": _acceptance_checks(intent, recommendation),
            }
        )

    blocked = [
        route["id"]
        for route in routes
        if not route["generation_allowed"]
    ]
    return {
        "template": REPORT_TEMPLATE,
        "id": plan_id,
        "source_manifest": str(path),
        "summary": {
            "shot_count": len(routes),
            "ready_count": len(routes) - len(blocked),
            "blocked_count": len(blocked),
            "blocked_shots": blocked,
        },
        "routes": routes,
    }


def _resolve_tool(
    recommendation: VideoControlRecommendation,
    readiness: dict[str, object],
    inventory: VideoToolInventory,
    allow_fallback: bool,
) -> tuple[str | None, str]:
    virtual_candidates = VIRTUAL_TOOL_GROUPS.get(recommendation.tool)
    if virtual_candidates:
        resolved = next(
            (
                tool
                for tool in virtual_candidates
                if (capability := inventory.find(tool)) is not None
                and capability.ready
            ),
            None,
        )
        return (resolved, "ready") if resolved else (None, "blocked")

    if readiness.get("pipeline_status") == "ready":
        return recommendation.tool, "ready"
    if not allow_fallback:
        return None, "blocked"

    ready_fallbacks = readiness.get("ready_fallbacks", [])
    if isinstance(ready_fallbacks, list) and ready_fallbacks:
        return str(ready_fallbacks[0]), "ready_fallback"
    return None, "blocked"


def _acceptance_checks(
    intent: VideoShotIntent,
    recommendation: VideoControlRecommendation,
) -> list[str]:
    checks = [
        "technical_metadata",
        "identity_consistency",
        "lighting_stability",
        (
            "declared_camera_motion"
            if intent.camera == "moving"
            else "camera_constraint"
        ),
        "motion_scope",
    ]
    if intent.contains_hands:
        checks.extend(("hand_anatomy", "hand_position"))
    if intent.contains_phone:
        checks.extend(("single_phone", "phone_position", "hand_object_contact"))
    if intent.audio_driven:
        checks.append("audio_track_presence")
    if intent.audio_driven and intent.lip_sync_required:
        checks.extend(("mouth_motion_presence", "lip_sync", "mouth_shape"))
    if intent.relight or intent.replacement:
        checks.extend(("subject_mask_edge", "background_light_match", "skin_tone"))
    if recommendation.mode == "subject_only":
        checks.extend(("subject_mask_edge", "static_background"))
    if intent.multi_person:
        checks.extend(("character_count", "character_identity_separation"))
    return list(dict.fromkeys(checks))


def _required_string(value: dict[str, object], key: str) -> str:
    raw = value.get(key)
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return raw.strip()


def _boolean(value: dict[str, object], key: str, default: bool) -> bool:
    raw = value.get(key, default)
    if not isinstance(raw, bool):
        raise ValueError(f"{key} must be a boolean")
    return raw
