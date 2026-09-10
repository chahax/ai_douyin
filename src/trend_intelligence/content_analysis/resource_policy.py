"""Source-scoped resource choices; no model imports or inference.

The choice is pinned before inference so a retry cannot accidentally discard
completed observations by selecting a different quantization or batch size.
"""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .artifacts import read_json, write_json

VERSION = "source-resource-policy-v1"
POLICY_SCHEMA = "source_analysis_resource_policy/v1"
MODES = {
    "guarded_standard": {
        "low_memory": False, "quantization": "none", "torch_dtype": "bfloat16",
        "max_images": 4, "minimum_load_ram_gib": 18.0,
        "minimum_load_vram_gib": 11.0, "release_below_ram_gib": 3.0,
    },
    "low_memory": {
        "low_memory": True, "quantization": "nf4_double", "torch_dtype": "bfloat16",
        "max_images": 2, "minimum_load_ram_gib": 6.0,
        "minimum_load_vram_gib": 5.0, "release_below_ram_gib": 2.0,
    },
}


def probe_resources() -> dict:
    """Read free resources without creating a CUDA context or loading torch."""
    import psutil

    available_vram = None
    try:
        result = subprocess.run(
            ["nvidia-smi", "--id=0", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        available_vram = float(result.stdout.strip()) / 1024
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return {"available_ram_gib": psutil.virtual_memory().available / 2**30,
            "available_vram_gib": available_vram,
            "observed_at": datetime.now(timezone.utc).isoformat()}


def _has_headroom(value: object, minimum: float) -> bool:
    return (type(value) in (int, float) and math.isfinite(value)
            and value >= minimum)


def select_resource_mode(policy: dict, source_sha256: str, resources: dict) -> dict | None:
    """Choose four-frame BF16 only for authorized sources with measured headroom."""
    if policy.get("schema") != POLICY_SCHEMA:
        raise ValueError("unsupported source resource policy")
    if policy.get("enabled") is not True:
        return None
    sources = policy.get("eligible_source_sha256")
    if (not isinstance(sources, list)
            or any(not isinstance(value, str) or len(value) != 64
                   or any(char not in "0123456789abcdef" for char in value) for value in sources)
            or len(sources) != len(set(sources))):
        raise ValueError("resource policy requires unique source SHA256 values")
    if source_sha256 not in sources:
        return None
    standard = MODES["guarded_standard"]
    enough = (_has_headroom(resources.get("available_ram_gib"), standard["minimum_load_ram_gib"])
              and _has_headroom(resources.get("available_vram_gib"), standard["minimum_load_vram_gib"]))
    mode = "guarded_standard" if enough else "low_memory"
    return {"resource_mode": mode, **MODES[mode],
            "selection_reason": "measured_ram_and_vram_headroom" if enough
            else "insufficient_or_unknown_headroom"}


def resolve_resource_policy(policy_path: Path, source_sha256: str, selection_path: Path,
                            *, resource_probe=probe_resources) -> dict | None:
    """Resolve an eligible source once and retain its exact choice on retries."""
    if not policy_path.is_file():
        return None
    raw = policy_path.read_bytes()
    policy = json.loads(raw)
    # Check scope before probing the GPU or writing any artifact.
    if select_resource_mode(policy, source_sha256, {}) is None:
        return None
    policy_sha256 = hashlib.sha256(raw).hexdigest()
    if selection_path.is_file():
        saved = read_json(selection_path)
        mode = saved.get("resource_mode")
        if (saved.get("schema") != "source_analysis_resource_selection/v1"
                or saved.get("selector_version") != VERSION
                or saved.get("source_video_sha256") != source_sha256
                or saved.get("policy_sha256") != policy_sha256
                or mode not in MODES
                or any(saved.get(key) != value for key, value in MODES[mode].items())):
            raise ValueError("resource selection changed; preserve cached observations before changing its identity")
        return {**saved, "selection_reused": True}
    resources = resource_probe()
    choice = select_resource_mode(policy, source_sha256, resources)
    selection = {
        "schema": "source_analysis_resource_selection/v1", "selector_version": VERSION,
        "source_video_sha256": source_sha256, "policy_path": str(policy_path.resolve()),
        "policy_sha256": policy_sha256, "selected_at": datetime.now(timezone.utc).isoformat(),
        "resources_at_selection": resources, **choice,
        "selection_reused": False,
    }
    write_json(selection_path, selection)
    return selection


def resource_inference_configuration(selection: dict, *, image_pixels: dict,
                                     max_new_tokens: int) -> dict:
    """Only actual inference parameters belong in the reusable cache identity."""
    return {"quantization": selection["quantization"], "torch_dtype": selection["torch_dtype"],
            "max_images": selection["max_images"], "image_pixels": dict(image_pixels),
            "max_new_tokens": max_new_tokens}
