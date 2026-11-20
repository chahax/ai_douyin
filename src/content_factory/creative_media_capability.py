"""Read-only capability audit for a creative storyboard's selected executor."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .creative_seedance_segments import ADAPTER_ID
from .seedance_client import SeedanceClient, SeedanceConfig, SeedanceReference
from .seedance_models import CATALOG, ark_model


ROOT = Path(__file__).resolve().parents[2]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_creative_executor(
    shots: dict[str, Any], *, config: SeedanceConfig | None = None,
) -> dict[str, Any]:
    """Validate local request shapes; never submit or assert visual compliance."""
    config = config or SeedanceConfig.from_env(require_key=False)
    if config.provider == "ark_api":
        model = ark_model(config.model)
        minimum, maximum = model["duration_min"], model["duration_max"]
        resolution = "480p" if "480p" in model["resolutions"] else model["resolutions"][0]
        guide = ROOT / "docs/reference/seedance/2026-09-07" / model["api_guide"]
        evidence = {
            "type": "archived_official_guide_and_local_request_validator",
            "catalog_sha256": _sha256(CATALOG),
            "archived_guide_sha256": _sha256(guide),
            "archived_guide_path": str(guide),
            "archive_date": "2026-09-07",
        }
    elif config.provider == "byteplus_api":
        if "2-5" not in config.model:
            raise ValueError("BytePlus 型号未登记时长能力，拒绝推断")
        minimum, maximum = 4, 30
        resolution = "480p"
        evidence = {"type": "local_client_parameter_validation_only",
                    "catalog_sha256": _sha256(CATALOG)}
    else:
        raise ValueError(f"未适配的创作媒体执行渠道: {config.provider}")

    # Synthetic asset IDs exercise payload construction without a network request.
    probe_seconds = minimum
    with SeedanceClient(config) as client:
        text_probe = client.build_task_payload(
            "只读能力检查，不提交", duration=probe_seconds,
            resolution=resolution, ratio="9:16", return_last_frame=True,
        )
        frame_probe = client.build_task_payload(
            "只读首帧参数检查，不提交", duration=probe_seconds,
            resolution=resolution, ratio="9:16", return_last_frame=True,
            references=[SeedanceReference("image", "asset://creative-capability-probe", "first_frame")],
        )
    if text_probe.get("model") != config.model or frame_probe.get("content", [{}])[-1].get("role") != "first_frame":
        raise RuntimeError("本地媒体参数探针未按所选模型构造")

    shot_rows = []
    for index, shot in enumerate(shots["shots"]):
        duration = shot["duration_seconds"]
        valid_duration = type(duration) is int and minimum <= duration <= maximum
        continuity = shot["continuity_mode"]
        requirements = ["actual_segment_review_before_continuation"]
        if index == 0:
            requirements.append("reviewed_opening_frame")
        elif continuity == "raw_tail_continuation":
            requirements.append("preceding_approved_raw_tail")
        else:
            requirements.append("new_camera_opening_frame_and_cut_adapter")
        if not valid_duration:
            requirements.append("segment_mapping_or_duration_revision")
        shot_rows.append({
            "shot_id": shot["id"], "beat_id": shot["beat_id"],
            "duration_seconds": duration, "fits_single_model_request": valid_duration,
            "continuity_mode": continuity, "requirements_before_submit": requirements,
            "ready_for_submit": False,
        })

    return {
        "schema": "creative_media_capability_audit/v2",
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "provider": config.provider, "model": config.model,
        "endpoint_base_url": config.base_url,
        "duration_min": minimum, "duration_max": maximum,
        "parameter_preflight": {
            "text_payload_built": True, "first_frame_payload_built": True,
            "return_last_frame_requested": True,
            "remote_request_sent": False, "visual_effect_verified": False,
        },
        "evidence": evidence,
        "shots": shot_rows,
        "segment_adapter": {
            "id": ADAPTER_ID,
            "local_request_mapping_available": True,
            "remote_submission_enabled": False,
        },
        "missing_runtime_capabilities": [
            "reviewed_opening_frame_binding",
            "reviewed_new_camera_opening_frame_binding",
            "approved_raw_tail_continuation_binding",
            "offline_cut_assembly_verification",
            "actual_segment_visual_and_audio_review",
        ],
        "automatic_submit": False,
        "status": "local_parameter_and_segment_mapping_available; media_submission_locked",
    }
