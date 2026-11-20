from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from src.content_factory.video_appearance_lock import transfer_reference_appearance
from src.content_factory.video_agent_pack import compile_video_agent_pack
from src.content_factory.video_audio_mux import (
    VideoAudioMuxManifest,
    _loop_filter,
)
from src.content_factory.video_candidate_benchmark import (
    VideoCandidateBenchmark,
    score_control_report,
)
from src.content_factory.deterministic_motion import (
    DeterministicMotionManifest,
    _pulse_strength,
    render_frame,
)
from src.content_factory.deterministic_camera import (
    DeterministicCameraManifest,
    _ease,
    render_camera_frame,
    run_deterministic_camera,
)
from src.content_factory.keyframe_relight import (
    DirectionalLight,
    KeyframeRelightManifest,
    render_keyframe_relight,
    run_keyframe_relight,
)
from src.content_factory.video_control_gate import (
    ControlRegion,
    VideoControlGate,
    VideoControlManifest,
    VideoControlReport,
    available_control_profiles,
    resolve_control_profile,
)
from src.content_factory.video_control_policy import (
    VideoShotIntent,
    recommend_video_control,
)
from src.content_factory.video_control_plan import compile_video_control_plan
from src.content_factory.video_tool_inventory import (
    VideoToolCapability,
    VideoToolInventory,
    recommendation_readiness,
    scan_video_tool_inventory,
)
from src.content_factory.video_mask import refine_subject_mask
from src.content_factory.video_recipe import VideoRecipe, run_video_recipe
from src.content_factory.video_recovery import recommend_video_recovery
from src.content_factory.video_temporal_repair import (
    TemporalRepairManifest,
    _brightness_gain,
    run_video_temporal_repair,
)
from src.content_factory.video_review_packet import (
    VideoReviewPacketManifest,
    _automatic_checks,
    _load_route_context,
    _sample_indices,
    finalize_video_review,
)
from src.content_factory.video_lighting_gate import (
    LightingAcceptance,
    VideoLightingGateManifest,
    compare_lighting,
    fingerprint_lighting,
    lighting_issues,
)
from src.content_factory.video_smoothness import (
    SmoothnessAcceptance,
    compare_smoothness,
    run_video_smoothness,
    summarize_frame_distances,
)
from src.content_factory.video_style_gate import (
    VideoStyleGateManifest,
    compare_fingerprints,
    fingerprint_image,
)
from src.content_factory.story_video import (
    StoryLine,
    StoryScene,
    StoryVideoManifest,
    _validate_scene_controls,
)


def test_control_profiles_cover_generation_modes():
    assert available_control_profiles() == (
        "free",
        "micro_motion",
        "subject_only",
        "pixel_locked",
        "replacement_relight",
    )
    assert resolve_control_profile("subject_only").require_regions is True
    assert resolve_control_profile("replacement_relight").require_reference is True


def test_deterministic_motion_rejects_excessive_effect_area(tmp_path: Path):
    source = tmp_path / "source.png"
    Image.new("RGB", (32, 32), "black").save(source)
    manifest = {
        "template": "deterministic_motion/v1",
        "source_image": str(source),
        "output_path": str(tmp_path / "output.mp4"),
        "width": 32,
        "height": 32,
        "fps": 25,
        "duration_seconds": 2,
        "safety": {"maximum_effect_area_ratio": 0.02},
        "effects": {
            "light_pulses": [
                {
                    "rect": [0.0, 0.0, 0.5, 0.5],
                    "start": 0.1,
                    "peak": 1.0,
                    "end": 1.9,
                }
            ]
        },
    }
    manifest_path = tmp_path / "motion.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="declared effect area"):
        DeterministicMotionManifest.load(manifest_path)


def test_deterministic_motion_frame_changes_only_declared_region(tmp_path: Path):
    source = tmp_path / "source.png"
    Image.new("RGB", (100, 100), (20, 30, 40)).save(source)
    manifest = {
        "template": "deterministic_motion/v1",
        "source_image": str(source),
        "output_path": str(tmp_path / "output.mp4"),
        "width": 100,
        "height": 100,
        "fps": 10,
        "duration_seconds": 2,
        "safety": {"maximum_effect_area_ratio": 0.04},
        "effects": {
            "light_pulses": [
                {
                    "name": "small_glow",
                    "rect": [0.1, 0.1, 0.2, 0.2],
                    "opacity": 0.3,
                    "blur": 0,
                    "start": 0.1,
                    "peak": 1.0,
                    "end": 1.9,
                }
            ]
        },
    }
    manifest_path = tmp_path / "motion.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    loaded = DeterministicMotionManifest.load(manifest_path)
    base = Image.open(source).convert("RGB")

    frame = render_frame(loaded, base, loaded.frame_count // 2)

    assert frame.getpixel((20, 20)) != base.getpixel((20, 20))
    assert frame.getpixel((80, 80)) == base.getpixel((80, 80))


def test_light_pulse_has_smooth_peak(tmp_path: Path):
    pulse_manifest = {
        "template": "deterministic_motion/v1",
        "source_image": "source.png",
        "output_path": "output.mp4",
        "width": 32,
        "height": 32,
        "fps": 25,
        "duration_seconds": 2,
        "effects": {
            "light_pulses": [
                {
                    "rect": [0.1, 0.1, 0.1, 0.1],
                    "start": 0.2,
                    "peak": 1.0,
                    "end": 1.8,
                }
            ]
        },
    }
    manifest_path = tmp_path / "motion_pulse_test.json"
    manifest_path.write_text(json.dumps(pulse_manifest), encoding="utf-8")
    pulse = DeterministicMotionManifest.load(manifest_path).light_pulses[0]

    assert _pulse_strength(0.0, pulse) == 0.0
    assert _pulse_strength(1.0, pulse) == pytest.approx(1.0)
    assert _pulse_strength(2.0, pulse) == 0.0


def test_keyframe_relight_preserves_pixels_outside_mask():
    source = Image.new("RGB", (12, 6), (80, 90, 100))
    mask = Image.new("L", source.size, 0)
    for y_position in range(1, 5):
        for x_position in range(2, 10):
            mask.putpixel((x_position, y_position), 255)
    light = DirectionalLight(
        direction="left",
        highlight_ev=0.4,
        shadow_ev=-0.1,
        color=(255, 210, 170),
        color_strength=0.08,
        curve=1.0,
    )

    output, _ = render_keyframe_relight(source, mask, light)

    assert output.getpixel((0, 0)) == source.getpixel((0, 0))
    assert output.getpixel((11, 5)) == source.getpixel((11, 5))
    assert sum(output.getpixel((2, 3))) > sum(output.getpixel((9, 3)))


def test_keyframe_relight_accepts_bounded_directional_change(tmp_path: Path):
    source = tmp_path / "source.png"
    mask = tmp_path / "mask.png"
    output = tmp_path / "output.png"
    Image.new("RGB", (40, 20), (70, 80, 90)).save(source)
    mask_image = Image.new("L", (40, 20), 0)
    for y_position in range(2, 18):
        for x_position in range(4, 28):
            mask_image.putpixel((x_position, y_position), 255)
    mask_image.save(mask)
    manifest_path = tmp_path / "relight.json"
    manifest_path.write_text(
        json.dumps(
            {
                "template": "keyframe_relight/v1",
                "source_image": str(source),
                "mask_image": str(mask),
                "output_image": str(output),
                "mask_blur": 0,
                "light": {
                    "direction": "left",
                    "highlight_ev": 0.32,
                    "shadow_ev": -0.06,
                    "color": [255, 214, 170],
                    "color_strength": 0.08,
                },
                "safety": {
                    "maximum_mask_area_ratio": 0.6,
                    "maximum_mean_pixel_change": 28,
                    "minimum_mean_pixel_change": 0.8,
                    "minimum_directional_luma_shift": 1.5,
                },
            }
        ),
        encoding="utf-8",
    )

    report = run_keyframe_relight(manifest_path)

    assert report["status"] == "accepted"
    assert output.is_file()
    assert report["metrics"]["outside_changed_pixels"] == 0
    assert report["metrics"]["directional_luma_shift"] >= 1.5


def test_keyframe_relight_rejects_oversized_mask(tmp_path: Path):
    source = tmp_path / "source.png"
    mask = tmp_path / "mask.png"
    output = tmp_path / "output.png"
    Image.new("RGB", (20, 20), (70, 80, 90)).save(source)
    Image.new("L", (20, 20), 255).save(mask)
    manifest_path = tmp_path / "relight.json"
    manifest_path.write_text(
        json.dumps(
            {
                "template": "keyframe_relight/v1",
                "source_image": str(source),
                "mask_image": str(mask),
                "output_image": str(output),
                "mask_blur": 0,
                "light": {
                    "direction": "top_left",
                    "highlight_ev": 0.3,
                    "shadow_ev": -0.1,
                },
                "safety": {
                    "maximum_mask_area_ratio": 0.2,
                    "minimum_directional_luma_shift": 0,
                },
            }
        ),
        encoding="utf-8",
    )

    report = run_keyframe_relight(manifest_path)

    assert report["status"] == "rejected"
    assert output.is_file() is False
    assert Path(report["pending_output"]).is_file()
    assert report["issues"][0]["code"] == "relight_mask_too_large"


def test_keyframe_relight_requires_lossless_output(tmp_path: Path):
    manifest_path = tmp_path / "relight.json"
    manifest_path.write_text(
        json.dumps(
            {
                "template": "keyframe_relight/v1",
                "source_image": "source.png",
                "mask_image": "mask.png",
                "output_image": "output.jpg",
                "light": {
                    "direction": "left",
                    "highlight_ev": 0.3,
                    "shadow_ev": -0.1,
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="lossless PNG"):
        KeyframeRelightManifest.load(manifest_path)


def test_deterministic_camera_rejects_exposed_image_border(
    tmp_path: Path,
):
    manifest_path = tmp_path / "camera.json"
    manifest_path.write_text(
        json.dumps(
            {
                "template": "deterministic_camera/v1",
                "source_image": "source.png",
                "output_path": "output.mp4",
                "width": 40,
                "height": 60,
                "fps": 25,
                "duration_seconds": 2,
                "motion": {
                    "start_zoom": 1.0,
                    "end_zoom": 1.02,
                    "start_center": [0.5, 0.5],
                    "end_center": [0.54, 0.5],
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="exposes image border"):
        DeterministicCameraManifest.load(manifest_path)


def test_deterministic_camera_renders_full_frame_without_black_border(
    tmp_path: Path,
):
    source_path = tmp_path / "source.png"
    Image.new("RGB", (40, 60), (80, 100, 120)).save(source_path)
    manifest_path = tmp_path / "camera.json"
    manifest_path.write_text(
        json.dumps(
            {
                "template": "deterministic_camera/v1",
                "source_image": str(source_path),
                "output_path": str(tmp_path / "output.mp4"),
                "width": 40,
                "height": 60,
                "fps": 10,
                "duration_seconds": 2,
                "motion": {
                    "start_zoom": 1.0,
                    "end_zoom": 1.05,
                    "start_center": [0.5, 0.5],
                    "end_center": [0.51, 0.49],
                },
            }
        ),
        encoding="utf-8",
    )
    manifest = DeterministicCameraManifest.load(manifest_path)
    source = Image.open(source_path).convert("RGB")

    first = render_camera_frame(manifest, source, 0)
    last = render_camera_frame(
        manifest,
        source,
        manifest.frame_count - 1,
    )

    assert first.getbbox() == (0, 0, 40, 60)
    assert last.getbbox() == (0, 0, 40, 60)
    assert all(channel > 0 for channel in last.getpixel((0, 0)))


def test_deterministic_camera_smooth_easing_has_soft_ends():
    assert _ease(0.0, "smooth") == 0.0
    assert _ease(1.0, "smooth") == 1.0
    assert _ease(0.1, "smooth") < 0.1
    assert _ease(0.9, "smooth") > 0.9


def test_deterministic_camera_separates_video_and_qa_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source = tmp_path / "source.png"
    Image.new("RGB", (4, 4), "white").save(source)
    raw_dir = tmp_path / "ComfyUI" / "output" / "shot"
    qa_dir = tmp_path / "ai_douyin" / "data" / "qa" / "shot"
    output = raw_dir / "camera.mp4"
    manifest_path = tmp_path / "camera.json"
    manifest_path.write_text(
        json.dumps(
            {
                "template": "deterministic_camera/v1",
                "source_image": str(source),
                "output_path": str(output),
                "width": 4,
                "height": 4,
                "fps": 2,
                "duration_seconds": 1,
                "motion": {
                    "start_zoom": 1.0,
                    "end_zoom": 1.05,
                    "start_center": [0.5, 0.5],
                    "end_center": [0.5, 0.5],
                },
                "safety": {
                    "minimum_activity_ratio": 0,
                },
            }
        ),
        encoding="utf-8",
    )

    def fake_render(manifest, output_path, *, ffmpeg):
        output_path.write_bytes(b"video")

    gate_report = VideoControlReport(path=str(output), mode="free")
    gate_report.metadata["temporal"] = {
        "max_active_pixel_ratio": 0.1,
        "luma_range": 0.0,
    }
    monkeypatch.setattr(
        "src.content_factory.deterministic_camera._render_video",
        fake_render,
    )
    monkeypatch.setattr(
        VideoControlGate,
        "inspect_manifest",
        lambda self, manifest_path, output_path=None: gate_report,
    )

    report = run_deterministic_camera(
        manifest_path,
        qa_dir=qa_dir,
    )

    assert Path(report["output"]).parent == raw_dir
    assert Path(report["control_manifest"]).parent == qa_dir
    assert Path(report["control_report"]).parent == qa_dir
    assert (qa_dir / "camera.camera.report.json").is_file()


def test_recovery_switches_failed_phone_micro_motion_to_deterministic(
    tmp_path: Path,
):
    review_path = tmp_path / "legacy_review.json"
    review_path.write_text(
        json.dumps(
            {
                "status": "rejected",
                "model": "LTX 2.3",
                "category_checks": {
                    "hands_and_fingers": "FAIL",
                    "phone_pose_stability": "FAIL",
                    "assigned_micro_action_only": "FAIL",
                },
                "attempt_history": ["attempt1", "attempt2", "attempt3"],
            }
        ),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "recovery.json"
    manifest_path.write_text(
        json.dumps(
            {
                "template": "video_recovery/v1",
                "id": "phone-recovery",
                "review_report": str(review_path),
                "current_tool": "ltx_i2v",
                "intent": {
                    "motion": "micro",
                    "framing": "medium",
                    "contains_hands": True,
                    "contains_phone": True,
                },
            }
        ),
        encoding="utf-8",
    )

    report = recommend_video_recovery(manifest_path)

    assert report["status"] == "actionable"
    assert report["route"]["next_tool"] == "deterministic_2d_compositor"
    assert report["route"]["single_change"]["field"] == "resolved_tool"
    assert report["attempt_count"] == 3


def test_recovery_restores_static_background_before_regeneration(tmp_path: Path):
    control_path = tmp_path / "control.json"
    control_path.write_text(
        json.dumps(
            {
                "passed": False,
                "metadata": {
                    "intent": {
                        "motion": "subject",
                        "camera": "locked",
                        "background": "static",
                    },
                    "recommendation": {"tool": "wan_animate_move"},
                },
                "issues": [
                    {
                        "code": "static_region_changed",
                        "message": "background changed",
                        "severity": "error",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "recovery.json"
    manifest_path.write_text(
        json.dumps(
            {
                "template": "video_recovery/v1",
                "id": "background-recovery",
                "control_report": str(control_path),
            }
        ),
        encoding="utf-8",
    )

    report = recommend_video_recovery(manifest_path)

    assert report["route"]["action"] == "apply_postprocess"
    assert (
        report["route"]["single_change"]["field"]
        == "postprocess.static_background_composite"
    )


def test_recovery_blocks_lip_sync_when_sonic_is_not_ready(tmp_path: Path):
    review_path = tmp_path / "review.json"
    review_path.write_text(
        json.dumps(
            {
                "template": "video_review_decision_report/v1",
                "status": "rejected",
                "failed_checks": ["lip_sync"],
            }
        ),
        encoding="utf-8",
    )
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text(
        json.dumps(
            {
                "capabilities": [
                    {"tool": "sonic", "status": "partial"},
                ]
            }
        ),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "recovery.json"
    manifest_path.write_text(
        json.dumps(
            {
                "template": "video_recovery/v1",
                "id": "lip-sync-recovery",
                "review_report": str(review_path),
                "inventory_report": str(inventory_path),
                "current_tool": "sadtalker",
            }
        ),
        encoding="utf-8",
    )

    report = recommend_video_recovery(manifest_path)

    assert report["status"] == "blocked"
    assert report["route"]["action"] == "lip_sync_tool_unavailable"
    assert report["generation_allowed"] is False


def test_recovery_allows_pipeline_when_reports_pass(tmp_path: Path):
    review_path = tmp_path / "review.json"
    review_path.write_text(
        json.dumps(
            {
                "template": "video_review_decision_report/v1",
                "status": "accepted",
                "failed_checks": [],
            }
        ),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "recovery.json"
    manifest_path.write_text(
        json.dumps(
            {
                "template": "video_recovery/v1",
                "id": "accepted",
                "review_report": str(review_path),
                "current_tool": "liveportrait",
            }
        ),
        encoding="utf-8",
    )

    report = recommend_video_recovery(manifest_path)

    assert report["status"] == "no_action"
    assert report["route"]["action"] == "continue_pipeline"


def test_recovery_routes_flicker_only_failure_to_temporal_repair(
    tmp_path: Path,
):
    video = tmp_path / "input.mp4"
    control_path = tmp_path / "control.json"
    control_path.write_text(
        json.dumps(
            {
                "path": str(video),
                "passed": False,
                "issues": [
                    {"code": "lighting_flicker", "severity": "error"},
                    {"code": "motion_too_large", "severity": "error"},
                    {"code": "anchor_drift", "severity": "error"},
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "recovery.json"
    manifest_path.write_text(
        json.dumps(
            {
                "template": "video_recovery/v1",
                "id": "flicker",
                "control_report": str(control_path),
                "current_tool": "ltx_i2v",
            }
        ),
        encoding="utf-8",
    )

    report = recommend_video_recovery(manifest_path)

    assert report["route"]["single_change"]["field"] == (
        "postprocess.temporal_repair"
    )
    assert report["route"]["single_change"]["to"] == "luma_gain_reference"


def test_recovery_routes_wrong_light_direction_to_keyframe_relight(
    tmp_path: Path,
):
    review_path = tmp_path / "review.json"
    review_path.write_text(
        json.dumps(
            {
                "template": "video_review_decision_report/v1",
                "status": "rejected",
                "failed_checks": ["light_direction"],
            }
        ),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "recovery.json"
    manifest_path.write_text(
        json.dumps(
            {
                "template": "video_recovery/v1",
                "id": "wrong-light-direction",
                "review_report": str(review_path),
                "current_tool": "ltx_i2v",
            }
        ),
        encoding="utf-8",
    )

    report = recommend_video_recovery(manifest_path)

    assert report["route"]["next_tool"] == "keyframe_relight"
    assert report["route"]["single_change"]["field"] == (
        "preprocess.keyframe_relight"
    )


def test_smoothness_score_penalizes_duplicate_and_jerky_cadence():
    smooth = summarize_frame_distances(
        [1.0, 1.1, 1.0, 0.9, 1.0, 1.1],
        duplicate_threshold=0.12,
    )
    jerky = summarize_frame_distances(
        [0.0, 2.0, 0.0, 2.1, 0.0, 1.9],
        duplicate_threshold=0.12,
    )

    assert smooth["smoothness_score"] > jerky["smoothness_score"]
    assert smooth["duplicate_ratio"] == 0.0
    assert jerky["duplicate_ratio"] == 0.5


def test_compare_smoothness_requires_gain_and_motion_retention():
    acceptance = SmoothnessAcceptance(
        minimum_score_gain=5.0,
        maximum_duplicate_ratio=0.12,
        minimum_motion_retention=0.7,
        maximum_motion_retention=1.4,
        maximum_duration_delta=0.08,
        minimum_motion_distance=0.12,
        duplicate_threshold=0.12,
    )

    accepted = compare_smoothness(
        {"smoothness_score": 50.0, "motion_path": 20.0},
        {
            "smoothness_score": 80.0,
            "motion_path": 19.0,
            "duplicate_ratio": 0.02,
        },
        input_duration=3.0,
        output_duration=3.02,
        output_fps=30.0,
        target_fps=30.0,
        acceptance=acceptance,
    )
    rejected = compare_smoothness(
        {"smoothness_score": 50.0, "motion_path": 20.0},
        {
            "smoothness_score": 51.0,
            "motion_path": 6.0,
            "duplicate_ratio": 0.3,
        },
        input_duration=3.0,
        output_duration=3.2,
        output_fps=29.0,
        target_fps=30.0,
        acceptance=acceptance,
    )

    assert accepted["issues"] == []
    assert {
        issue["code"] for issue in rejected["issues"]
    } == {
        "smoothness_target_fps_mismatch",
        "smoothness_gain_insufficient",
        "duplicate_frames_excessive",
        "motion_retention_out_of_range",
        "smoothness_duration_changed",
    }


def test_video_smoothness_blocks_failed_input_gate_before_ffmpeg(
    tmp_path: Path,
):
    video = tmp_path / "input.mp4"
    video.write_bytes(b"not-a-real-video")
    control_manifest = tmp_path / "input.control.manifest.json"
    control_manifest.write_text(
        json.dumps(
            {
                "template": "video_control/v1",
                "video_path": str(video),
                "mode": "micro_motion",
            }
        ),
        encoding="utf-8",
    )
    control_report = tmp_path / "input.control.report.json"
    control_report.write_text(
        json.dumps(
            {
                "path": str(video),
                "passed": False,
                "issues": [
                    {
                        "code": "phone_position",
                        "severity": "error",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "smoothness.json"
    manifest.write_text(
        json.dumps(
            {
                "template": "video_smoothness/v1",
                "input_video": str(video),
                "input_control_manifest": str(control_manifest),
                "input_control_report": str(control_report),
                "output_video": str(tmp_path / "output.mp4"),
                "smoothing": {"target_fps": 30},
            }
        ),
        encoding="utf-8",
    )

    report = run_video_smoothness(manifest)

    assert report["status"] == "blocked"
    assert report["blocked_issue_codes"] == ["phone_position"]


def test_recovery_routes_judder_to_gated_smoothness(tmp_path: Path):
    review_path = tmp_path / "review.json"
    review_path.write_text(
        json.dumps(
            {
                "template": "video_review_decision_report/v1",
                "status": "rejected",
                "failed_checks": ["judder"],
            }
        ),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "recovery.json"
    manifest_path.write_text(
        json.dumps(
            {
                "template": "video_recovery/v1",
                "id": "judder",
                "review_report": str(review_path),
                "current_tool": "liveportrait",
            }
        ),
        encoding="utf-8",
    )

    report = recommend_video_recovery(manifest_path)

    assert report["route"]["next_tool"] == "smoothness_repair"
    assert report["route"]["single_change"]["to"] == "minterpolate_gated"


def test_recovery_routes_static_storyboard_to_full_frame_camera(
    tmp_path: Path,
):
    review_path = tmp_path / "review.json"
    review_path.write_text(
        json.dumps(
            {
                "template": "video_review_decision_report/v1",
                "status": "rejected",
                "failed_checks": ["static_storyboard"],
            }
        ),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "recovery.json"
    manifest_path.write_text(
        json.dumps(
            {
                "template": "video_recovery/v1",
                "id": "static-storyboard",
                "review_report": str(review_path),
                "current_tool": "ltx_i2v",
            }
        ),
        encoding="utf-8",
    )

    report = recommend_video_recovery(manifest_path)

    assert report["route"]["next_tool"] == "deterministic_camera"
    assert report["route"]["single_change"]["to"] == (
        "deterministic_camera"
    )


def test_style_fingerprint_is_stable_for_identical_images():
    image = Image.new("RGB", (64, 64), (80, 120, 180))
    reference = fingerprint_image(image, size=64)
    candidate = fingerprint_image(image.copy(), size=64)

    metrics = compare_fingerprints(reference, candidate)

    assert metrics["style_distance"] == 0.0
    assert metrics["palette_distance"] == 0.0
    assert metrics["edge_density_delta"] == 0.0


def test_style_fingerprint_separates_soft_color_and_hard_lineart():
    soft = Image.new("RGB", (64, 64), (70, 100, 150))
    hard = Image.new("RGB", (64, 64), "white")
    for position in range(0, 64, 4):
        for coordinate in range(64):
            hard.putpixel((position, coordinate), (0, 0, 0))
    reference = fingerprint_image(soft, size=64)
    candidate = fingerprint_image(hard, size=64)

    metrics = compare_fingerprints(reference, candidate)

    assert metrics["style_distance"] > 0.2
    assert metrics["edge_density_delta"] > 0.1


def test_style_gate_requires_control_report_for_video_candidate(
    tmp_path: Path,
):
    reference = tmp_path / "reference.png"
    video = tmp_path / "candidate.mp4"
    reference.write_bytes(b"image")
    video.write_bytes(b"video")
    manifest_path = tmp_path / "style.json"
    manifest_path.write_text(
        json.dumps(
            {
                "template": "video_style_gate/v1",
                "id": "style",
                "reference": {"path": str(reference)},
                "candidates": [
                    {
                        "id": "candidate",
                        "path": str(video),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="control_report is required"):
        VideoStyleGateManifest.load(manifest_path)


def test_recovery_routes_style_mismatch_to_approved_keyframe(
    tmp_path: Path,
):
    review_path = tmp_path / "style.report.json"
    review_path.write_text(
        json.dumps(
            {
                "template": "video_style_gate_report/v1",
                "status": "rejected",
                "failed_checks": ["style_lineart_mismatch"],
            }
        ),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "recovery.json"
    manifest_path.write_text(
        json.dumps(
            {
                "template": "video_recovery/v1",
                "id": "style-recovery",
                "review_report": str(review_path),
                "current_tool": "ltx_i2v",
            }
        ),
        encoding="utf-8",
    )

    report = recommend_video_recovery(manifest_path)

    assert report["route"]["action"] == "replace_source_asset"
    assert report["route"]["single_change"]["to"] == (
        "approved_style_keyframe"
    )


def test_lighting_fingerprint_is_stable_for_identical_images():
    image = Image.new("RGB", (64, 64), (80, 120, 180))
    reference = fingerprint_lighting(image, size=64)
    candidate = fingerprint_lighting(image.copy(), size=64)

    metrics = compare_lighting(reference, candidate)

    assert metrics["exposure_ev_delta"] == 0.0
    assert metrics["temperature_delta"] == 0.0
    assert metrics["direction_angle_degrees"] == 0.0


def test_lighting_fingerprint_detects_opposite_light_direction():
    reference_image = Image.new("RGB", (64, 64))
    candidate_image = Image.new("RGB", (64, 64))
    for horizontal in range(64):
        value = round(30 + horizontal / 63 * 190)
        opposite = 250 - value
        for vertical in range(64):
            reference_image.putpixel(
                (horizontal, vertical),
                (value, value, value),
            )
            candidate_image.putpixel(
                (horizontal, vertical),
                (opposite, opposite, opposite),
            )
    reference = fingerprint_lighting(reference_image, size=64)
    candidate = fingerprint_lighting(candidate_image, size=64)

    metrics = compare_lighting(reference, candidate)

    assert metrics["direction_angle_degrees"] > 170
    assert metrics["exposure_ev_delta"] < 0.05


def test_lighting_issues_separate_color_and_direction_failures():
    acceptance = LightingAcceptance(
        maximum_exposure_ev_delta=0.35,
        maximum_temperature_delta=0.08,
        maximum_tint_delta=0.06,
        maximum_contrast_delta=0.15,
        maximum_highlight_ratio_delta=0.12,
        maximum_shadow_ratio_delta=0.12,
        maximum_direction_angle_degrees=45,
        maximum_direction_strength_delta=0.06,
        minimum_reference_direction_strength=0.015,
        maximum_temporal_exposure_range_ev=0.25,
        maximum_temporal_color_range=0.06,
        maximum_temporal_direction_range_degrees=45,
    )
    metrics = {
        "maximum_exposure_ev_delta": 0.1,
        "maximum_temperature_delta": 0.12,
        "maximum_tint_delta": 0.01,
        "contrast_delta": 0.02,
        "highlight_ratio_delta": 0.01,
        "shadow_ratio_delta": 0.01,
        "maximum_direction_angle_degrees": 100.0,
        "direction_strength_delta": 0.01,
        "reference_direction_strength": 0.1,
        "temporal_exposure_range_ev": 0.05,
        "temporal_temperature_range": 0.01,
        "temporal_tint_range": 0.01,
        "temporal_direction_range_degrees": 5.0,
    }

    codes = {
        issue["code"] for issue in lighting_issues(metrics, acceptance)
    }

    assert "lighting_color_cast_mismatch" in codes
    assert "light_direction_mismatch" in codes


def test_lighting_gate_requires_control_report_for_video_candidate(
    tmp_path: Path,
):
    reference = tmp_path / "reference.png"
    video = tmp_path / "candidate.mp4"
    reference.write_bytes(b"image")
    video.write_bytes(b"video")
    manifest_path = tmp_path / "lighting.json"
    manifest_path.write_text(
        json.dumps(
            {
                "template": "video_lighting_gate/v1",
                "id": "lighting",
                "reference": {"path": str(reference)},
                "candidates": [
                    {
                        "id": "candidate",
                        "path": str(video),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="control_report is required"):
        VideoLightingGateManifest.load(manifest_path)


def test_recovery_routes_lighting_color_mismatch_to_appearance_lock(
    tmp_path: Path,
):
    review_path = tmp_path / "lighting.report.json"
    review_path.write_text(
        json.dumps(
            {
                "template": "video_lighting_gate_report/v1",
                "status": "rejected",
                "failed_checks": ["lighting_color_cast_mismatch"],
            }
        ),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "recovery.json"
    manifest_path.write_text(
        json.dumps(
            {
                "template": "video_recovery/v1",
                "id": "lighting-recovery",
                "review_report": str(review_path),
                "current_tool": "wan_animate_move",
            }
        ),
        encoding="utf-8",
    )

    report = recommend_video_recovery(manifest_path)

    assert report["route"]["action"] == "apply_postprocess"
    assert report["route"]["single_change"]["field"] == (
        "postprocess.reference_appearance_lock"
    )


def test_agent_pack_isolates_comfyui_and_orchestrator_paths(tmp_path: Path):
    comfyui = tmp_path / "AI_vido" / "ComfyUI"
    orchestrator = tmp_path / "ai_douyin"
    plan_path = tmp_path / "plan.report.json"
    plan_path.write_text(
        json.dumps(
            {
                "template": "video_control_plan_report/v1",
                "routes": [
                    {
                        "id": "phone_notice",
                        "generation_allowed": True,
                        "route_status": "ready",
                        "control_mode": "pixel_locked",
                        "primary_tool": "deterministic_2d_compositor",
                        "resolved_tool": "deterministic_2d_compositor",
                        "required_assets": ["reference_image"],
                        "acceptance_checks": ["technical_metadata"],
                        "readiness": {"missing": []},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "pack.json"
    output_dir = orchestrator / "data" / "qa" / "tasks"
    manifest_path.write_text(
        json.dumps(
            {
                "template": "video_agent_pack/v1",
                "id": "pack",
                "namespace": "anti_fraud_v5",
                "plan_report": str(plan_path),
                "comfyui_root": str(comfyui),
                "orchestrator_root": str(orchestrator),
                "output_dir": str(output_dir),
            }
        ),
        encoding="utf-8",
    )

    report = compile_video_agent_pack(manifest_path)
    task = report["tasks"][0]
    contract = json.loads(Path(task["contract"]).read_text(encoding="utf-8"))
    hermes = Path(task["hermes_task"]).read_text(encoding="utf-8")
    claude = Path(task["claude_code_task"]).read_text(encoding="utf-8")

    assert Path(contract["paths"]["asset_input_dir"]).is_relative_to(comfyui)
    assert Path(contract["paths"]["raw_output_dir"]).is_relative_to(comfyui)
    assert Path(contract["paths"]["qa_output_dir"]).is_relative_to(orchestrator)
    assert f"不修改 `{orchestrator}`" in hermes
    assert f"不把 ComfyUI 原始输出写入 `{orchestrator}`" in claude


def test_agent_pack_rejects_output_outside_orchestrator(tmp_path: Path):
    plan_path = tmp_path / "plan.report.json"
    plan_path.write_text(
        json.dumps(
            {
                "template": "video_control_plan_report/v1",
                "routes": [{"id": "shot", "generation_allowed": False}],
            }
        ),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "pack.json"
    manifest_path.write_text(
        json.dumps(
            {
                "template": "video_agent_pack/v1",
                "id": "pack",
                "namespace": "test",
                "plan_report": str(plan_path),
                "comfyui_root": str(tmp_path / "ComfyUI"),
                "orchestrator_root": str(tmp_path / "orchestrator"),
                "output_dir": str(tmp_path / "wrong"),
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="output_dir must stay within"):
        compile_video_agent_pack(manifest_path)


def test_agent_pack_marks_blocked_route_as_stop_task(tmp_path: Path):
    comfyui = tmp_path / "ComfyUI"
    orchestrator = tmp_path / "orchestrator"
    plan_path = tmp_path / "plan.report.json"
    plan_path.write_text(
        json.dumps(
            {
                "template": "video_control_plan_report/v1",
                "routes": [
                    {
                        "id": "exact_lipsync",
                        "generation_allowed": False,
                        "route_status": "blocked",
                        "primary_tool": "sonic",
                        "resolved_tool": None,
                        "readiness": {"missing": ["Sonic UNet"]},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "pack.json"
    manifest_path.write_text(
        json.dumps(
            {
                "template": "video_agent_pack/v1",
                "id": "pack",
                "namespace": "test",
                "plan_report": str(plan_path),
                "comfyui_root": str(comfyui),
                "orchestrator_root": str(orchestrator),
                "output_dir": str(orchestrator / "tasks"),
            }
        ),
        encoding="utf-8",
    )

    report = compile_video_agent_pack(manifest_path)
    claude = Path(report["tasks"][0]["claude_code_task"]).read_text(
        encoding="utf-8"
    )

    assert report["summary"]["blocked_count"] == 1
    assert "STOP / BLOCKED" in claude
    assert "停止 ComfyUI 队列" in claude


def test_temporal_repair_builds_deflicker_before_interpolation(tmp_path: Path):
    video = tmp_path / "input.mp4"
    control_manifest = tmp_path / "input.control.manifest.json"
    control_report = tmp_path / "input.control.report.json"
    for file_path in (video, control_manifest, control_report):
        file_path.write_bytes(b"asset")
    manifest_path = tmp_path / "repair.json"
    manifest_path.write_text(
        json.dumps(
            {
                "template": "video_temporal_repair/v1",
                "input_video": str(video),
                "input_control_manifest": str(control_manifest),
                "input_control_report": str(control_report),
                "output_video": str(tmp_path / "output.mp4"),
                "repair": {
                    "deflicker": {
                        "enabled": True,
                        "size": 7,
                        "mode": "median",
                    },
                    "interpolation": "minterpolate",
                    "target_fps": 30,
                },
            }
        ),
        encoding="utf-8",
    )

    manifest = TemporalRepairManifest.load(manifest_path)

    assert manifest.filter_chain().startswith("deflicker=size=7:mode=median,")
    assert "minterpolate=fps=30.00000000" in manifest.filter_chain()


def test_temporal_repair_blocks_structural_failure_before_ffmpeg(tmp_path: Path):
    video = tmp_path / "input.mp4"
    video.write_bytes(b"video")
    control_manifest = tmp_path / "input.control.manifest.json"
    control_manifest.write_text(
        json.dumps(
            {
                "template": "video_control/v1",
                "video_path": str(video),
                "mode": "subject_only",
                "regions": {
                    "background": {
                        "rect": [0, 0, 10, 10],
                        "motion": "static",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    control_report = tmp_path / "input.control.report.json"
    control_report.write_text(
        json.dumps(
            {
                "path": str(video),
                "passed": False,
                "issues": [
                    {
                        "code": "lighting_flicker",
                        "severity": "error",
                    },
                    {
                        "code": "static_region_changed",
                        "severity": "error",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "repair.json"
    manifest_path.write_text(
        json.dumps(
            {
                "template": "video_temporal_repair/v1",
                "input_video": str(video),
                "input_control_manifest": str(control_manifest),
                "input_control_report": str(control_report),
                "output_video": str(tmp_path / "output.mp4"),
                "repair": {"deflicker": {"enabled": True}},
            }
        ),
        encoding="utf-8",
    )

    report = run_video_temporal_repair(manifest_path)

    assert report["status"] == "blocked"
    assert report["blocked_issue_codes"] == ["static_region_changed"]
    assert not (tmp_path / "output.mp4").exists()


def test_temporal_repair_rejects_empty_repair(tmp_path: Path):
    manifest_path = tmp_path / "repair.json"
    manifest_path.write_text(
        json.dumps(
            {
                "template": "video_temporal_repair/v1",
                "input_video": "input.mp4",
                "input_control_manifest": "input.control.json",
                "input_control_report": "input.report.json",
                "output_video": "output.mp4",
                "repair": {
                    "deflicker": {"enabled": False},
                    "interpolation": "none",
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="enable deflicker or interpolation"):
        TemporalRepairManifest.load(manifest_path)


def test_luma_gain_is_bounded_and_strength_controlled():
    assert _brightness_gain(
        50,
        100,
        strength=1.0,
        maximum_delta=0.25,
    ) == pytest.approx(1.25)
    assert _brightness_gain(
        100,
        50,
        strength=0.5,
        maximum_delta=0.5,
    ) == pytest.approx(0.75)


def test_candidate_score_rewards_target_fps_and_stable_background():
    regions = (
        ControlRegion(
            "background",
            (0, 0, 100, 50),
            "static",
            reference_lock=True,
        ),
        ControlRegion("face", (20, 20, 60, 70), "dynamic"),
    )
    slow = VideoControlReport(
        path="slow.mp4",
        mode="micro_motion",
        metadata={
            "fps": 16,
            "duration": 3.0,
            "temporal": {
                "luma_range": 0.5,
                "chroma_range": 0.4,
                "max_frame_distance": 2.0,
                "max_anchor_distance": 3.0,
                "max_active_pixel_ratio": 0.05,
            },
            "regions": {
                "background": {
                    "max_frame_distance": 0.1,
                    "max_anchor_distance": 0.1,
                    "max_active_pixel_ratio": 0.0,
                    "max_reference_distance": 1.0,
                },
                "face": {
                    "max_frame_distance": 5.0,
                    "max_anchor_distance": 6.0,
                    "max_active_pixel_ratio": 0.12,
                },
            },
        },
    )
    smooth = VideoControlReport(
        path="smooth.mp4",
        mode="micro_motion",
        metadata={**slow.metadata, "fps": 30},
    )

    assert score_control_report(smooth, regions) > score_control_report(slow, regions)


def test_candidate_benchmark_rejects_mixed_control_modes(tmp_path: Path):
    reference = tmp_path / "reference.png"
    _asset(reference)
    manifests = []
    for name, mode in (("first", "micro_motion"), ("second", "pixel_locked")):
        path = tmp_path / f"{name}.json"
        path.write_text(
            json.dumps(
                {
                    "template": "video_control/v1",
                    "video_path": f"{name}.mp4",
                    "reference_image": str(reference),
                    "mode": mode,
                }
            ),
            encoding="utf-8",
        )
        manifests.append(path)
    benchmark_path = tmp_path / "benchmark.json"
    benchmark_path.write_text(
        json.dumps(
            {
                "template": "video_candidate_benchmark/v1",
                "id": "mixed",
                "candidates": [
                    {
                        "id": "first",
                        "tool": "liveportrait",
                        "control_manifest": str(manifests[0]),
                    },
                    {
                        "id": "second",
                        "tool": "deterministic",
                        "control_manifest": str(manifests[1]),
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="same control mode"):
        VideoCandidateBenchmark.load(benchmark_path)


def test_subject_only_accepts_static_background_and_dynamic_subject():
    gate = VideoControlGate()
    report = VideoControlReport(path="video.mp4", mode="subject_only")
    first = Image.new("RGB", (200, 100), (40, 30, 20))
    second = first.copy()
    second.paste((70, 45, 30), (125, 20, 180, 85))
    regions = (
        ControlRegion("background", (0, 0, 100, 100), "static", reference_lock=True),
        ControlRegion("subject", (100, 0, 100, 100), "dynamic"),
    )

    gate.evaluate_samples(
        report,
        resolve_control_profile("subject_only"),
        [(0.0, first), (1.0, second)],
        regions=regions,
        reference=first,
    )

    assert report.passed
    assert report.metadata["regions"]["background"]["max_frame_distance"] == 0.0
    assert report.metadata["regions"]["subject"]["max_active_pixel_ratio"] > 0.002


def test_dynamic_region_can_reject_excessive_object_motion():
    gate = VideoControlGate()
    report = VideoControlReport(path="video.mp4", mode="subject_only")
    first = Image.new("RGB", (200, 100), "black")
    second = first.copy()
    second.paste("white", (120, 10, 190, 90))
    regions = (
        ControlRegion(
            "phone_hand",
            (100, 0, 100, 100),
            "dynamic",
            max_frame_distance=8.0,
            max_anchor_distance=10.0,
            max_active_pixel_ratio=0.2,
        ),
    )

    gate.evaluate_samples(
        report,
        resolve_control_profile("subject_only"),
        [(0.0, first), (1.0, second)],
        regions=regions,
    )

    codes = {issue.code for issue in report.issues}
    assert "region_motion_too_large" in codes
    assert "region_anchor_drift" in codes
    assert "region_active_area_too_large" in codes


def test_micro_motion_rejects_lighting_flash():
    gate = VideoControlGate()
    report = VideoControlReport(path="video.mp4", mode="micro_motion")
    dark = Image.new("RGB", (160, 90), (30, 20, 15))
    bright = Image.new("RGB", (160, 90), (150, 120, 100))

    gate.evaluate_samples(
        report,
        resolve_control_profile("micro_motion"),
        [(0.0, dark), (1.0, bright)],
    )

    codes = {issue.code for issue in report.issues}
    assert "lighting_flicker" in codes
    assert "motion_too_large" in codes


def test_pixel_locked_rejects_small_global_drift():
    gate = VideoControlGate()
    report = VideoControlReport(path="video.mp4", mode="pixel_locked")
    first = Image.new("RGB", (160, 90), "black")
    first.paste("white", (40, 20, 80, 70))
    second = Image.new("RGB", (160, 90), "black")
    second.paste("white", (48, 20, 88, 70))

    gate.evaluate_samples(
        report,
        resolve_control_profile("pixel_locked"),
        [(0.0, first), (1.0, second)],
    )

    codes = {issue.code for issue in report.issues}
    assert "motion_too_large" in codes
    assert "active_area_too_large" in codes


def test_manifest_resolves_relative_paths(tmp_path: Path):
    manifest_path = tmp_path / "control.json"
    manifest_path.write_text(
        json.dumps(
            {
                "template": "video_control/v1",
                "video_path": "candidate.mp4",
                "reference_image": "reference.png",
                "mode": "replacement_relight",
                "regions": {
                    "background": {
                        "rect": [0, 0, 100, 100],
                        "motion": "static",
                        "reference_lock": True,
                    },
                    "subject": {
                        "rect": [100, 0, 100, 100],
                        "motion": "dynamic",
                        "max_anchor_distance": 14.0,
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    manifest = VideoControlManifest.load(manifest_path)

    assert manifest.video_path == tmp_path / "candidate.mp4"
    assert manifest.reference_image == tmp_path / "reference.png"
    assert [region.name for region in manifest.regions] == ["background", "subject"]
    assert manifest.regions[1].max_anchor_distance == 14.0


def test_manifest_rejects_unknown_mode(tmp_path: Path):
    manifest_path = tmp_path / "control.json"
    manifest_path.write_text(
        json.dumps(
            {
                "template": "video_control/v1",
                "video_path": "candidate.mp4",
                "mode": "prompt_only",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown video control mode"):
        VideoControlManifest.load(manifest_path)


def test_phone_micro_motion_selects_pixel_locked_compositor():
    recommendation = recommend_video_control(
        VideoShotIntent(
            motion="micro",
            framing="medium",
            contains_hands=True,
            contains_phone=True,
        )
    )

    assert recommendation.mode == "pixel_locked"
    assert recommendation.tool == "deterministic_2d_compositor"
    assert recommendation.risk == "low"


def test_static_storyboard_with_moving_camera_selects_deterministic_camera():
    recommendation = recommend_video_control(
        VideoShotIntent(
            motion="none",
            camera="moving",
            background="static",
            preserve_reference=True,
        )
    )

    assert recommendation.mode == "free"
    assert recommendation.tool == "deterministic_camera"
    assert recommendation.risk == "low"


def test_close_portrait_micro_motion_selects_liveportrait():
    recommendation = recommend_video_control(
        VideoShotIntent(motion="micro", framing="head_shoulders")
    )

    assert recommendation.mode == "micro_motion"
    assert recommendation.tool == "liveportrait"


def test_audio_driven_close_portrait_selects_sadtalker():
    recommendation = recommend_video_control(
        VideoShotIntent(
            motion="micro",
            framing="head_shoulders",
            audio_driven=True,
        )
    )

    assert recommendation.mode == "micro_motion"
    assert recommendation.tool == "sadtalker"
    assert recommendation.required_assets == ("reference_image", "driven_audio")


def test_audio_driven_portrait_with_phone_stays_pixel_locked():
    recommendation = recommend_video_control(
        VideoShotIntent(
            motion="micro",
            framing="head_shoulders",
            contains_phone=True,
            audio_driven=True,
        )
    )

    assert recommendation.tool == "deterministic_2d_compositor"


def test_anime_voiceover_without_lip_sync_selects_liveportrait():
    recommendation = recommend_video_control(
        VideoShotIntent(
            motion="micro",
            framing="head_shoulders",
            audio_driven=True,
            visual_style="anime",
            lip_sync_required=False,
        )
    )

    assert recommendation.tool == "liveportrait"
    assert "audio_mux" in recommendation.postprocess


def test_anime_exact_lip_sync_selects_sonic():
    recommendation = recommend_video_control(
        VideoShotIntent(
            motion="micro",
            framing="head_shoulders",
            audio_driven=True,
            visual_style="anime",
            lip_sync_required=True,
        )
    )

    assert recommendation.tool == "sonic"
    assert recommendation.risk == "high"


def test_control_plan_routes_multiple_shot_types(tmp_path: Path):
    manifest_path = tmp_path / "plan.json"
    manifest_path.write_text(
        json.dumps(
            {
                "template": "video_control_plan/v1",
                "id": "routing-test",
                "defaults": {
                    "camera": "locked",
                    "background": "static",
                },
                "shots": [
                    {
                        "id": "phone",
                        "intent": {
                            "motion": "micro",
                            "contains_phone": True,
                        },
                    },
                    {
                        "id": "expression",
                        "intent": {
                            "motion": "micro",
                            "framing": "head_shoulders",
                        },
                    },
                    {
                        "id": "speech",
                        "intent": {
                            "motion": "micro",
                            "framing": "head_shoulders",
                            "audio_driven": True,
                        },
                    },
                    {
                        "id": "free",
                        "intent": {
                            "motion": "free",
                            "camera": "moving",
                            "background": "dynamic",
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    inventory = _ready_tool_inventory(
        "deterministic_2d_compositor",
        "liveportrait",
        "sadtalker",
        "ltx_i2v",
        "color_match_v2",
    )

    report = compile_video_control_plan(manifest_path, inventory)

    assert report["summary"]["blocked_count"] == 0
    routes = {route["id"]: route for route in report["routes"]}
    assert routes["phone"]["resolved_tool"] == "deterministic_2d_compositor"
    assert routes["expression"]["resolved_tool"] == "liveportrait"
    assert routes["speech"]["resolved_tool"] == "sadtalker"
    assert routes["free"]["resolved_tool"] == "ltx_i2v"
    assert "single_phone" in routes["phone"]["acceptance_checks"]
    assert "lip_sync" in routes["speech"]["acceptance_checks"]
    assert "mouth_motion_presence" in routes["speech"]["acceptance_checks"]


def test_control_plan_and_agent_pack_route_deterministic_camera(
    tmp_path: Path,
):
    plan_manifest = tmp_path / "plan.json"
    plan_manifest.write_text(
        json.dumps(
            {
                "template": "video_control_plan/v1",
                "id": "camera-route",
                "shots": [
                    {
                        "id": "fullframe_push",
                        "intent": {
                            "motion": "none",
                            "camera": "moving",
                            "background": "static",
                            "preserve_reference": True,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    plan = compile_video_control_plan(
        plan_manifest,
        _ready_tool_inventory("deterministic_camera"),
    )
    route = plan["routes"][0]
    assert route["resolved_tool"] == "deterministic_camera"
    assert route["control_mode"] == "free"
    assert "declared_camera_motion" in route["acceptance_checks"]
    assert "camera_constraint" not in route["acceptance_checks"]

    plan_report = tmp_path / "plan.report.json"
    plan_report.write_text(json.dumps(plan), encoding="utf-8")
    comfyui = tmp_path / "AI_vido" / "ComfyUI"
    orchestrator = tmp_path / "ai_douyin"
    pack_manifest = tmp_path / "pack.json"
    pack_manifest.write_text(
        json.dumps(
            {
                "template": "video_agent_pack/v1",
                "id": "camera-pack",
                "namespace": "camera_v1",
                "plan_report": str(plan_report),
                "comfyui_root": str(comfyui),
                "orchestrator_root": str(orchestrator),
                "output_dir": str(orchestrator / "tasks"),
            }
        ),
        encoding="utf-8",
    )

    pack = compile_video_agent_pack(pack_manifest)
    contract = json.loads(
        Path(pack["tasks"][0]["contract"]).read_text(encoding="utf-8")
    )

    assert contract["execution"]["generation_manifest"] == (
        "deterministic_camera/v1"
    )
    assert contract["execution"]["executor"] == (
        r"scripts\deterministic_camera.py"
    )
    assert contract["execution"]["qa_output_flag"] == "--qa-dir"


def test_control_plan_blocks_missing_audio_driver(tmp_path: Path):
    manifest_path = tmp_path / "plan.json"
    manifest_path.write_text(
        json.dumps(
            {
                "template": "video_control_plan/v1",
                "id": "blocked-test",
                "shots": [
                    {
                        "id": "speech",
                        "intent": {
                            "motion": "micro",
                            "framing": "head_shoulders",
                            "audio_driven": True,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    inventory = _ready_tool_inventory("deterministic_2d_compositor")

    report = compile_video_control_plan(manifest_path, inventory)

    assert report["summary"]["blocked_shots"] == ["speech"]
    assert report["routes"][0]["generation_allowed"] is False
    assert report["routes"][0]["resolved_tool"] is None


def test_review_packet_uses_evenly_spaced_frames():
    assert _sample_indices(97, 5) == [0, 24, 48, 72, 96]
    assert _sample_indices(3, 5) == [0, 1, 2]


def test_review_packet_requires_plan_and_shot_together(tmp_path: Path):
    manifest_path = tmp_path / "review.json"
    manifest_path.write_text(
        json.dumps(
            {
                "template": "video_review_packet/v1",
                "id": "review-test",
                "video_path": "candidate.mp4",
                "output_dir": "review",
                "plan_report": "plan.json",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="provided together"):
        VideoReviewPacketManifest.load(manifest_path)


def test_review_packet_loads_route_acceptance_checks(tmp_path: Path):
    report_path = tmp_path / "plan.report.json"
    report_path.write_text(
        json.dumps(
            {
                "template": "video_control_plan_report/v1",
                "routes": [
                    {
                        "id": "phone",
                        "acceptance_checks": ["single_phone", "phone_position"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    route = _load_route_context(report_path, "phone")

    assert route["acceptance_checks"] == ["single_phone", "phone_position"]


def test_review_packet_rejects_required_missing_audio():
    checks = _automatic_checks(
        {
            "audio_present": False,
            "audio_video_duration_delta": None,
        },
        ["audio_track_presence"],
        {"status": "not_configured", "rect": None},
    )

    assert checks["audio_track_presence"]["status"] == "failed"
    assert checks["audio_duration_match"]["status"] == "failed"


def test_audio_mux_defaults_to_pingpong(tmp_path: Path):
    manifest_path = tmp_path / "mux.json"
    manifest_path.write_text(
        json.dumps(
            {
                "template": "video_audio_mux/v1",
                "id": "mux-test",
                "video_path": "portrait.mp4",
                "audio_path": "voice.wav",
                "output_path": "output.mp4",
            }
        ),
        encoding="utf-8",
    )

    manifest = VideoAudioMuxManifest.load(manifest_path)

    assert manifest.loop_mode == "pingpong"
    assert manifest.output_path == tmp_path / "output.mp4"


def test_audio_mux_pingpong_filter_reverses_and_loops():
    filter_complex = _loop_filter(
        "pingpong",
        frame_count=89,
        fps=30.0,
        audio_duration=5.4,
    )

    assert "reverse" in filter_complex
    assert "loop=loop=-1:size=178" in filter_complex
    assert "setpts=N/(30.000000*TB)" in filter_complex


def test_review_decision_rejects_failed_visual_check(tmp_path: Path):
    review_path = tmp_path / "review.json"
    review_path.write_text(
        json.dumps(
            {
                "template": "video_review_packet_report/v1",
                "id": "review-test",
                "video_path": "candidate.mp4",
                "machine_gate": {"passed": True},
                "automatic_checks_passed": True,
                "acceptance_checks": ["identity_consistency", "single_phone"],
            }
        ),
        encoding="utf-8",
    )
    decision_path = tmp_path / "decision.json"
    decision_path.write_text(
        json.dumps(
            {
                "template": "video_review_decision/v1",
                "review_report": str(review_path),
                "output_path": "decision.report.json",
                "reviewer": "codex",
                "decisions": {
                    "identity_consistency": {
                        "status": "passed",
                    },
                    "single_phone": {
                        "status": "failed",
                        "notes": "A duplicate phone appears in the middle frame.",
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    report = finalize_video_review(decision_path)

    assert report["status"] == "rejected"
    assert report["composition_eligible"] is False
    assert report["failed_checks"] == ["single_phone"]


def test_review_decision_requires_machine_gate(tmp_path: Path):
    review_path = tmp_path / "review.json"
    review_path.write_text(
        json.dumps(
            {
                "template": "video_review_packet_report/v1",
                "id": "review-test",
                "video_path": "candidate.mp4",
                "machine_gate": {
                    "status": "not_provided",
                    "passed": None,
                },
                "automatic_checks_passed": True,
                "acceptance_checks": ["identity_consistency"],
            }
        ),
        encoding="utf-8",
    )
    decision_path = tmp_path / "decision.json"
    decision_path.write_text(
        json.dumps(
            {
                "template": "video_review_decision/v1",
                "review_report": str(review_path),
                "output_path": "decision.report.json",
                "reviewer": "codex",
                "decisions": {
                    "identity_consistency": {
                        "status": "passed",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    report = finalize_video_review(decision_path)

    assert report["status"] == "rejected"
    assert report["failed_checks"] == ["machine_gate"]


def test_subject_action_uses_reference_appearance_lock():
    recommendation = recommend_video_control(
        VideoShotIntent(
            motion="subject",
            framing="medium",
            camera="locked",
            background="static",
            preserve_reference=True,
            contains_phone=True,
        )
    )

    assert recommendation.tool == "wan_animate_move"
    assert "reference_appearance_lock" in recommendation.postprocess


def test_manifest_derives_mode_from_intent(tmp_path: Path):
    manifest_path = tmp_path / "control.json"
    manifest_path.write_text(
        json.dumps(
            {
                "template": "video_control/v1",
                "video_path": "candidate.mp4",
                "intent": {
                    "motion": "none",
                    "framing": "medium",
                    "contains_phone": True,
                },
            }
        ),
        encoding="utf-8",
    )

    manifest = VideoControlManifest.load(manifest_path)

    assert manifest.mode == "pixel_locked"
    assert manifest.recommendation is not None
    assert manifest.recommendation.tool == "deterministic_2d_compositor"


def test_manifest_rejects_mode_that_conflicts_with_intent(tmp_path: Path):
    manifest_path = tmp_path / "control.json"
    manifest_path.write_text(
        json.dumps(
            {
                "template": "video_control/v1",
                "video_path": "candidate.mp4",
                "mode": "micro_motion",
                "intent": {
                    "motion": "micro",
                    "framing": "medium",
                    "contains_hands": True,
                    "contains_phone": True,
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="conflicts with intent recommendation pixel_locked"):
        VideoControlManifest.load(manifest_path)


def test_story_manifest_can_require_control_for_every_scene():
    with pytest.raises(ValueError, match="scenes require control manifests: opening"):
        StoryVideoManifest.from_dict(
            {
                "template": "story_video/v1",
                "require_scene_control": True,
                "cast": {"narrator": {"name": "Narrator"}},
                "scenes": [
                    {
                        "id": "opening",
                        "video_path": "opening.mp4",
                        "lines": [{"speaker": "narrator", "text": "Opening"}],
                    }
                ],
            }
        )


def test_story_manifest_resolves_scene_control_manifest(tmp_path: Path):
    manifest_path = tmp_path / "story.json"
    manifest_path.write_text(
        json.dumps(
            {
                "template": "story_video/v1",
                "require_scene_control": True,
                "cast": {"narrator": {"name": "Narrator"}},
                "scenes": [
                    {
                        "id": "opening",
                        "video_path": "opening.mp4",
                        "control_manifest": "opening.control.json",
                        "lines": [{"speaker": "narrator", "text": "Opening"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    manifest = StoryVideoManifest.load(manifest_path)

    assert manifest.require_scene_control is True
    assert manifest.scenes[0].control_manifest == str(tmp_path / "opening.control.json")


def test_story_control_gate_accepts_explicit_user_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    video_path = tmp_path / "candidate.mp4"
    video_path.touch()
    control_path = tmp_path / "candidate.control.json"
    control_path.write_text(
        json.dumps(
            {
                "template": "video_control/v1",
                "video_path": str(video_path),
                "mode": "micro_motion",
            }
        ),
        encoding="utf-8",
    )
    review_path = tmp_path / "candidate.review.json"
    review_path.write_text(
        json.dumps(
            {
                "status": "accepted_by_user_override",
                "video_path": str(video_path),
                "user_override": True,
                "composition_eligible": True,
                "user_override_reason": "Motion is acceptable for this delivery tier.",
                "reviewer": "user",
            }
        ),
        encoding="utf-8-sig",
    )
    rejected = VideoControlReport(path=str(video_path), mode="micro_motion")
    rejected.add_issue("anchor_drift", "anchor moved")
    monkeypatch.setattr(
        VideoControlGate,
        "inspect_manifest",
        lambda self, manifest_path, output_path=None: rejected,
    )
    manifest = StoryVideoManifest(
        title="Test",
        cast={},
        scenes=(
            StoryScene(
                scene_id="opening",
                video_path=str(video_path),
                control_manifest=str(control_path),
                control_review=str(review_path),
                lines=(StoryLine(speaker="narrator", text="Opening"),),
            ),
        ),
        require_scene_control=True,
        allow_user_overrides=True,
    )

    reports = _validate_scene_controls(manifest, tmp_path / "reports")

    assert reports[0].passed is True
    assert reports[0].metadata["strict_gate_passed"] is False
    assert reports[0].issues[0].severity == "warning"


def test_inventory_reports_ready_and_partial_tools(tmp_path: Path):
    comfy = tmp_path / "ComfyUI"
    framepack = tmp_path / "FramePack"
    _asset(comfy / "custom_nodes" / "ComfyUI-WanVideoWrapper" / "__init__.py")
    _asset(comfy / "custom_nodes" / "ComfyUI-segment-anything-2" / "__init__.py")
    _asset(comfy / "models" / "diffusion_models" / "Wan-Animate.safetensors")
    _asset(comfy / "models" / "vae" / "wan2.2_vae.safetensors")
    _asset(comfy / "models" / "text_encoders" / "umt5.safetensors")
    _asset(comfy / "models" / "clip_vision" / "clip.safetensors")
    _asset(framepack / "demo_gradio.py")
    snapshot = (
        framepack
        / "hf_download"
        / "hub"
        / "models--lllyasviel--FramePackI2V_HY"
        / "snapshots"
        / "test"
    )
    _asset(snapshot / "diffusion_pytorch_model-00001-of-00003.safetensors")
    _asset(snapshot / "diffusion_pytorch_model-00003-of-00003.safetensors")

    inventory = scan_video_tool_inventory(
        comfyui_root=comfy,
        framepack_root=framepack,
        liveportrait_root=tmp_path / "LivePortrait",
        sadtalker_root=tmp_path / "SadTalker",
        ffmpeg_path="ffmpeg-test",
    )

    assert inventory.find("deterministic_2d_compositor").status == "ready"
    assert inventory.find("reference_appearance_lock").status == "ready"
    assert inventory.find("lighting_consistency_gate").status == "ready"
    assert inventory.find("wan_animate_move").status == "ready"
    assert inventory.find("sam2_mask").status == "partial"
    assert inventory.find("framepack").status == "ready"
    assert inventory.find("liveportrait").status == "missing"


def test_readiness_returns_installed_fallbacks(tmp_path: Path):
    framepack = tmp_path / "FramePack"
    _asset(framepack / "demo_gradio.py")
    snapshot = (
        framepack
        / "hf_download"
        / "hub"
        / "models--lllyasviel--FramePackI2V_HY"
        / "snapshots"
        / "test"
    )
    _asset(snapshot / "diffusion_pytorch_model-00001-of-00003.safetensors")
    _asset(snapshot / "diffusion_pytorch_model-00003-of-00003.safetensors")
    inventory = scan_video_tool_inventory(
        comfyui_root=tmp_path / "ComfyUI",
        framepack_root=framepack,
        liveportrait_root=tmp_path / "LivePortrait",
        sadtalker_root=tmp_path / "SadTalker",
        ffmpeg_path="ffmpeg-test",
    )

    readiness = recommendation_readiness("liveportrait", inventory)

    assert readiness["selected_tool_status"] == "missing"
    assert readiness["pipeline_status"] == "missing"
    assert readiness["ready_fallbacks"] == [
        "deterministic_2d_compositor",
        "framepack",
    ]


def test_readiness_resolves_free_generation_group():
    inventory = _ready_tool_inventory("ltx_i2v", "color_match_v2")

    readiness = recommendation_readiness("wan_or_ltx_i2v", inventory)

    assert readiness["resolved_tool"] == "ltx_i2v"
    assert readiness["selected_tool_status"] == "virtual_ready"
    assert readiness["pipeline_status"] == "ready"


def test_inventory_detects_comfyui_liveportrait(tmp_path: Path):
    comfy = tmp_path / "ComfyUI"
    _asset(comfy / "custom_nodes" / "ComfyUI-LivePortraitKJ" / "nodes.py")
    model_dir = comfy / "models" / "liveportrait"
    _asset(model_dir / "appearance_feature_extractor.safetensors")
    _asset(model_dir / "motion_extractor.safetensors")
    _asset(model_dir / "warping_module.safetensors")
    _asset(model_dir / "spade_generator.safetensors")
    _asset(model_dir / "stitching_retargeting_module.safetensors")
    _asset(model_dir / "landmark.onnx")

    inventory = scan_video_tool_inventory(
        comfyui_root=comfy,
        framepack_root=tmp_path / "FramePack",
        liveportrait_root=tmp_path / "LivePortrait",
        sadtalker_root=tmp_path / "SadTalker",
        ffmpeg_path="ffmpeg-test",
    )

    assert inventory.find("liveportrait").status == "ready"


def test_inventory_detects_sadtalker_runtime(tmp_path: Path):
    sadtalker = tmp_path / "SadTalker"
    _asset(sadtalker / "inference.py")
    _asset(sadtalker / "checkpoints" / "SadTalker_V0.0.2_256.safetensors")
    _asset(sadtalker / "checkpoints" / "mapping_00229-model.pth.tar")
    _asset(sadtalker / "gfpgan" / "weights" / "alignment_WFLW_4HG.pth")
    _asset(sadtalker / "gfpgan" / "weights" / "detection_Resnet50_Final.pth")

    inventory = scan_video_tool_inventory(
        comfyui_root=tmp_path / "ComfyUI",
        framepack_root=tmp_path / "FramePack",
        liveportrait_root=tmp_path / "LivePortrait",
        sadtalker_root=sadtalker,
        ffmpeg_path="ffmpeg-test",
    )

    assert inventory.find("sadtalker").status == "ready"


def test_inventory_reports_sonic_partial_without_weights(tmp_path: Path):
    comfy = tmp_path / "ComfyUI"
    (comfy / "custom_nodes" / "ComfyUI_Sonic").mkdir(parents=True)
    _asset(comfy / "models" / "checkpoints" / "svd_xt_1_1.safetensors")

    inventory = scan_video_tool_inventory(
        comfyui_root=comfy,
        framepack_root=tmp_path / "FramePack",
        liveportrait_root=tmp_path / "LivePortrait",
        sadtalker_root=tmp_path / "SadTalker",
        ffmpeg_path="ffmpeg-test",
    )

    sonic = inventory.find("sonic")
    assert sonic.status == "partial"
    assert "Sonic UNet" in sonic.missing
    assert "Sonic Whisper" in sonic.missing


def test_inventory_detects_core_rife_interpolation(tmp_path: Path):
    comfy = tmp_path / "ComfyUI"
    _asset(comfy / "comfy_extras" / "nodes_frame_interpolation.py")
    _asset(
        comfy
        / "models"
        / "frame_interpolation"
        / "rife_v4.26.safetensors"
    )

    inventory = scan_video_tool_inventory(
        comfyui_root=comfy,
        framepack_root=tmp_path / "FramePack",
        liveportrait_root=tmp_path / "LivePortrait",
        sadtalker_root=tmp_path / "SadTalker",
        ffmpeg_path="ffmpeg-test",
    )

    assert inventory.find("rife").status == "ready"


def test_wan_pipeline_is_partial_without_sam2_model(tmp_path: Path):
    comfy = tmp_path / "ComfyUI"
    _asset(comfy / "custom_nodes" / "ComfyUI-WanVideoWrapper" / "__init__.py")
    _asset(comfy / "custom_nodes" / "ComfyUI-segment-anything-2" / "__init__.py")
    _asset(comfy / "custom_nodes" / "ComfyUI-KJNodes" / "__init__.py")
    (
        comfy / ".venv" / "Lib" / "site-packages" / "color_matcher"
    ).mkdir(parents=True)
    _asset(comfy / "models" / "diffusion_models" / "Wan-Animate.safetensors")
    _asset(comfy / "models" / "vae" / "wan2.2_vae.safetensors")
    _asset(comfy / "models" / "text_encoders" / "umt5.safetensors")
    _asset(comfy / "models" / "clip_vision" / "clip.safetensors")
    inventory = scan_video_tool_inventory(
        comfyui_root=comfy,
        framepack_root=tmp_path / "FramePack",
        liveportrait_root=tmp_path / "LivePortrait",
        sadtalker_root=tmp_path / "SadTalker",
        ffmpeg_path="ffmpeg-test",
    )

    readiness = recommendation_readiness("wan_animate_move", inventory)

    assert readiness["selected_tool_status"] == "ready"
    assert readiness["pipeline_status"] == "partial"
    assert readiness["missing"] == ["sam2_mask: SAM2 model"]


def test_refine_subject_mask_fills_internal_holes():
    mask = Image.new("L", (15, 15), 0)
    for x in range(3, 12):
        for y in range(3, 12):
            mask.putpixel((x, y), 255)
    for x in range(6, 9):
        for y in range(6, 9):
            mask.putpixel((x, y), 0)

    refined = refine_subject_mask(mask)

    assert refined.getpixel((7, 7)) == 255
    assert refined.getpixel((0, 0)) == 0


def test_refine_subject_mask_can_grow_and_feather():
    mask = Image.new("L", (15, 15), 0)
    mask.putpixel((7, 7), 255)

    refined = refine_subject_mask(mask, grow=2, feather=1.0)

    assert refined.getpixel((7, 7)) > refined.getpixel((4, 7)) > 0
    assert refined.getpixel((0, 0)) == 0


def test_transfer_reference_appearance_anchors_static_frame():
    generated = Image.new("RGB", (4, 4), (180, 80, 60))
    reference = Image.new("RGB", (4, 4), (80, 100, 140))
    mask = Image.new("L", (4, 4), 255)

    result = transfer_reference_appearance(
        generated,
        generated,
        reference,
        mask,
    )

    assert result.getpixel((2, 2)) == reference.getpixel((2, 2))


def test_transfer_reference_appearance_preserves_masked_background():
    anchor = Image.new("RGB", (4, 4), (100, 100, 100))
    generated = Image.new("RGB", (4, 4), (120, 90, 100))
    reference = Image.new("RGB", (4, 4), (50, 60, 70))
    mask = Image.new("L", (4, 4), 0)
    mask.putpixel((2, 2), 255)

    result = transfer_reference_appearance(
        generated,
        anchor,
        reference,
        mask,
        motion_gain=0.5,
    )

    assert result.getpixel((0, 0)) == (50, 60, 70)
    assert result.getpixel((2, 2)) == (60, 55, 70)


def test_video_recipe_compiles_normalized_regions(tmp_path: Path):
    payload = _video_recipe_payload(tmp_path)
    manifest_path = tmp_path / "recipe.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    recipe = VideoRecipe.load(manifest_path)

    assert recipe.gate_mode == "subject_only"
    assert recipe.gate_regions["background"]["rect"] == [0, 0, 176, 250]
    assert recipe.gate_regions["subject"]["rect"] == [0, 250, 704, 998]
    assert recipe.recommendation.tool == "wan_animate_move"


def test_video_recipe_requires_mask_for_appearance_lock(tmp_path: Path):
    payload = _video_recipe_payload(tmp_path)
    del payload["inputs"]["subject_mask"]
    manifest_path = tmp_path / "recipe.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="subject_mask is required"):
        VideoRecipe.load(manifest_path)


def test_video_recipe_dry_run_returns_executable_plan(tmp_path: Path):
    payload = _video_recipe_payload(tmp_path)
    manifest_path = tmp_path / "recipe.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    plan = run_video_recipe(manifest_path, dry_run=True)

    assert plan["template"] == "video_recipe_plan/v1"
    assert plan["appearance_lock"]["motion_gain"] == 0.55
    assert plan["recommendation"]["tool"] == "wan_animate_move"


def _asset(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"asset")


def _ready_tool_inventory(*tools: str) -> VideoToolInventory:
    return VideoToolInventory(
        comfyui_root="ComfyUI",
        framepack_root="FramePack",
        liveportrait_root="LivePortrait",
        sadtalker_root="SadTalker",
        capabilities=tuple(
            VideoToolCapability(
                tool=tool,
                status="ready",
                detected=(f"{tool}: ready",),
                missing=(),
                modes=("micro_motion", "subject_only", "free", "pixel_locked"),
            )
            for tool in tools
        ),
    )


def _video_recipe_payload(tmp_path: Path) -> dict[str, object]:
    generated = tmp_path / "generated.mp4"
    reference = tmp_path / "reference.png"
    mask = tmp_path / "mask.png"
    for path in (generated, reference, mask):
        _asset(path)
    return {
        "template": "video_recipe/v1",
        "id": "recipe_test",
        "intent": {
            "motion": "subject",
            "framing": "medium",
            "camera": "locked",
            "background": "static",
            "preserve_reference": True,
            "contains_phone": True,
        },
        "inputs": {
            "generated_video": str(generated),
            "reference_image": str(reference),
            "subject_mask": str(mask),
        },
        "appearance_lock": {"enabled": True, "motion_gain": 0.55},
        "smoothing": {"interpolation": "minterpolate"},
        "output": {
            "path": str(tmp_path / "final.mp4"),
            "width": 704,
            "height": 1248,
            "fps": 30,
        },
        "gate": {
            "regions": {
                "background": {
                    "rect_normalized": [0.0, 0.0, 0.25, 0.2],
                    "motion": "static",
                    "reference_lock": True,
                },
                "subject": {
                    "rect_normalized": [0.0, 0.2, 1.0, 0.8],
                    "motion": "dynamic",
                },
            }
        },
    }
