"""Resource selection and cache identity only; no model, media or GPU calls."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.trend_intelligence.content_analysis.artifacts import sha256
from src.trend_intelligence.content_analysis.hierarchical import VisualBatchCheckpoint
from src.trend_intelligence.content_analysis.resource_policy import (
    POLICY_SCHEMA, resolve_resource_policy, resource_inference_configuration, select_resource_mode,
)

SOURCE = "a" * 64
POLICY = {"schema": POLICY_SCHEMA, "enabled": True, "eligible_source_sha256": [SOURCE]}


def test_measured_headroom_selects_bf16_four_frames():
    choice = select_resource_mode(POLICY, SOURCE, {"available_ram_gib": 18, "available_vram_gib": 11})
    assert choice["resource_mode"] == "guarded_standard"
    assert choice["low_memory"] is False
    assert choice["max_images"] == 4
    assert choice["quantization"] == "none"
    assert choice["torch_dtype"] == "bfloat16"
    assert choice["release_below_ram_gib"] == 3


@pytest.mark.parametrize("ram,vram", [(17.99, 12), (20, 10.99), (20, None), (None, 12),
                                      (float("nan"), 12), (20, float("inf")), (True, 12)])
def test_missing_or_insufficient_headroom_retains_nf4(ram, vram):
    choice = select_resource_mode(POLICY, SOURCE, {"available_ram_gib": ram, "available_vram_gib": vram})
    assert choice["low_memory"] is True
    assert choice["quantization"] == "nf4_double"
    assert choice["max_images"] == 2


def test_current_or_unlisted_source_is_unchanged(tmp_path):
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps(POLICY), encoding="utf-8")
    def forbidden_probe():
        pytest.fail("unlisted source must not probe or change its resource mode")
    target = tmp_path / "selection.json"
    assert resolve_resource_policy(policy, "b" * 64, target, resource_probe=forbidden_probe) is None
    assert not target.exists()
    assert select_resource_mode({**POLICY, "enabled": False}, SOURCE, {}) is None


def test_retry_keeps_precision_and_batch_so_observations_remain_reusable(tmp_path):
    policy, selection = tmp_path / "policy.json", tmp_path / "selection.json"
    policy.write_text(json.dumps(POLICY), encoding="utf-8")
    first = resolve_resource_policy(policy, SOURCE, selection,
                                    resource_probe=lambda: {"available_ram_gib": 20, "available_vram_gib": 12})
    original_bytes = selection.read_bytes()
    def forbidden_probe():
        pytest.fail("a retry must keep its original cache identity and wait for sufficient resources")
    retry = resolve_resource_policy(policy, SOURCE, selection, resource_probe=forbidden_probe)
    assert retry["selection_reused"] is True
    assert retry["quantization"] == first["quantization"] == "none"
    assert retry["max_images"] == first["max_images"] == 4
    assert selection.read_bytes() == original_bytes
    saved = json.loads(original_bytes)
    saved["max_images"] = 6
    selection.write_text(json.dumps(saved), encoding="utf-8")
    with pytest.raises(ValueError, match="resource selection changed"):
        resolve_resource_policy(policy, SOURCE, selection, resource_probe=forbidden_probe)


def test_policy_change_requires_explicit_preservation_before_reconfiguration(tmp_path):
    policy, selection = tmp_path / "policy.json", tmp_path / "selection.json"
    policy.write_text(json.dumps(POLICY), encoding="utf-8")
    resolve_resource_policy(policy, SOURCE, selection, resource_probe=lambda: {})
    policy.write_text(json.dumps({**POLICY, "revision": 2}), encoding="utf-8")
    with pytest.raises(ValueError, match="resource selection changed"):
        resolve_resource_policy(policy, SOURCE, selection, resource_probe=lambda: {})


def test_actual_precision_and_batch_are_in_checkpoint_identity(tmp_path):
    frame_path = tmp_path / "frame.jpg"
    frame_path.write_bytes(b"opaque test frame bytes; never decoded")
    frames = [{"id": "V0001", "time_seconds": 0, "path": str(frame_path), "sha256": sha256(frame_path)}]
    observation = {"observations": [{"frame_id": "V0001", "event": "测试画面事实"}]}
    normal = select_resource_mode(POLICY, SOURCE, {"available_ram_gib": 20, "available_vram_gib": 12})
    low = select_resource_mode(POLICY, SOURCE, {})
    configs = [resource_inference_configuration(choice, image_pixels={"longest_edge": 262144},
                                                max_new_tokens=4000) for choice in (normal, low)]
    assert [(c["quantization"], c["max_images"]) for c in configs] == [("none", 4), ("nf4_double", 2)]
    caches = [VisualBatchCheckpoint(tmp_path / "cache", binding={"inference_configuration": config})
              for config in configs]
    caches[0].save(frames, observation)
    assert caches[0].load(frames) == observation
    assert caches[1].load(frames) is None
    caches[1].save(frames, observation)
    assert len(list((tmp_path / "cache").glob("visual_*.json"))) == 2


def test_invalid_policy_cannot_activate_resource_override():
    with pytest.raises(ValueError):
        select_resource_mode({**POLICY, "eligible_source_sha256": [SOURCE, SOURCE]}, SOURCE, {})
    with pytest.raises(ValueError):
        select_resource_mode({**POLICY, "schema": "unrecognized"}, SOURCE, {})
