from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from src.content_factory.presenter.background_resolver import BackgroundResolver, RETRY_PRESETS
from src.content_factory.presenter.models import PresenterSegment
from src.content_factory.presenter.presenter_composer import PresenterComposer
from src.content_factory.presenter.exceptions import ComfyOOMError
from src.content_factory.video_enhancer import VideoEnhancer
from src.content_factory.video_quality import available_quality_profiles, resolve_quality_profile
from src.content_factory.video_quality_gate import VideoQualityGate, VideoQualityReport
from src.content_factory.triple_panel import (
    TriplePanelManifest,
    compose_triple_panel_video,
    triple_panel_regions,
)
from src.content_factory.story_video import StoryVideoManifest, compose_story_video
from src.content_factory import story_video as story_video_module


def _probe(width: int = 1080, height: int = 1920, fps: str = "30/1", bit_rate: int = 800_000) -> dict:
    return {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": width,
                "height": height,
                "avg_frame_rate": fps,
                "pix_fmt": "yuv420p",
                "bit_rate": str(bit_rate),
            },
            {"codec_type": "audio", "codec_name": "aac"},
        ],
        "format": {"duration": "5.0"},
    }


def test_quality_profiles_expose_documented_profiles_and_arguments():
    assert available_quality_profiles() == ("preview", "publish", "master")
    publish = resolve_quality_profile("publish")
    assert (publish.width, publish.height, publish.fps, publish.crf, publish.preset) == (1080, 1920, 30, 19, "medium")
    encoding_args = publish.video_encoding_args()
    assert ["-profile:v", "high"] == encoding_args[encoding_args.index("-profile:v"):encoding_args.index("-profile:v") + 2]
    assert ["-colorspace", "bt709"] == encoding_args[encoding_args.index("-colorspace"):encoding_args.index("-colorspace") + 2]
    assert ["-b:v", "3000000"] == encoding_args[encoding_args.index("-b:v"):encoding_args.index("-b:v") + 2]
    assert ["-x264-params", "nal-hrd=cbr:colorprim=bt709:transfer=bt709:colormatrix=bt709"] == encoding_args[encoding_args.index("-x264-params"):encoding_args.index("-x264-params") + 2]
    assert publish.muxing_args() == ["-movflags", "+faststart"]


def test_unknown_quality_profile_is_rejected():
    with pytest.raises(ValueError, match="未知视频质量档位"):
        resolve_quality_profile("cinema")


def test_enhancer_uses_lanczos_and_target_fps():
    enhancer = VideoEnhancer("publish")
    assert "flags=lanczos" in enhancer.cover_filter()
    assert "fps=30" in enhancer.cover_filter()
    assert "pad=1080:1920" in enhancer.fit_filter()


def test_quality_gate_rejects_wrong_publish_specification():
    profile = resolve_quality_profile("publish")
    report = VideoQualityReport(path="video.mp4", profile=profile.name)
    VideoQualityGate.evaluate_probe(report, _probe(width=540, height=960, fps="16/1", bit_rate=120_000), profile)
    error_codes = {issue.code for issue in report.issues if issue.severity == "error"}
    warning_codes = {issue.code for issue in report.warnings}
    assert {"dimensions_mismatch", "fps_mismatch"}.issubset(error_codes)
    assert "low_bitrate" in warning_codes
    assert not report.passed


def test_quality_gate_detects_black_and_static_frames():
    gate = VideoQualityGate()
    report = VideoQualityReport(path="video.mp4", profile="publish")
    black = Image.new("RGB", (540, 960), "black")
    metric = gate.frame_metrics(black, 1.0)
    gate._evaluate_frame(report, metric)
    gate._evaluate_static_frames(report, [(1.0, black), (2.0, black.copy())], duration=5.0)
    codes = {issue.code for issue in report.issues}
    assert "black_frame" in codes
    assert "static_video" in codes


def test_quality_gate_enforces_declared_panel_motion():
    gate = VideoQualityGate()
    report = VideoQualityReport(path="video.mp4", profile="publish")
    first = Image.new("RGB", (120, 120), "red")
    second = first.copy()
    second.paste("blue", (0, 40, 120, 80))
    gate._evaluate_panel_motion(
        report,
        [(1.0, first), (2.0, second)],
        {"top": "static", "middle": "dynamic", "bottom": "static"},
        {
            "top": (0, 0, 120, 40),
            "middle": (0, 40, 120, 40),
            "bottom": (0, 80, 120, 40),
        },
    )

    codes = {issue.code for issue in report.issues}
    assert "static_panel_motion_detected" not in codes
    assert "dynamic_panel_motion_missing" not in codes
    assert report.metadata["panel_motion"]["middle"]["max_frame_distance"] > 1.2


def test_quality_gate_detects_localized_dynamic_panel_motion():
    gate = VideoQualityGate()
    report = VideoQualityReport(path="video.mp4", profile="publish")
    first = Image.new("RGB", (540, 312), "black")
    second = first.copy()
    second.paste("white", (200, 140, 236, 156))
    gate._evaluate_panel_motion(
        report,
        [(1.0, first), (2.0, second)],
        {"middle": "dynamic"},
        {"middle": (0, 0, 540, 312)},
    )

    motion = report.metadata["panel_motion"]["middle"]
    assert motion["max_frame_distance"] < 1.2
    assert motion["max_active_pixel_ratio"] >= 0.002
    assert not any(issue.code == "dynamic_panel_motion_missing" for issue in report.issues)


def test_panel_motion_requires_frame_sampling(monkeypatch, tmp_path: Path):
    gate = VideoQualityGate()
    video = tmp_path / "unreadable.mp4"
    video.write_bytes(b"placeholder")
    monkeypatch.setattr(gate, "_probe", lambda path: _probe())
    monkeypatch.setattr(gate, "_sample_frames", lambda path, duration: (_ for _ in ()).throw(OSError("decode failed")))

    report = gate.inspect(
        video,
        "publish",
        panel_motion_policy={"middle": "dynamic"},
        panel_regions={"middle": (0, 0, 1080, 1920)},
    )

    assert not report.passed
    assert any(issue.code == "frame_scan_unavailable" and issue.severity == "error" for issue in report.issues)


def test_panel_sampling_avoids_fixed_loop_phase():
    timestamps = VideoQualityGate(sample_count=5)._sample_timestamps(30.0)
    phases = {round(timestamp % 5, 3) for timestamp in timestamps}
    assert len(phases) > 1


def test_triple_panel_manifest_requires_generated_middle_source(tmp_path: Path):
    manifest_path = tmp_path / "invalid.json"
    manifest_path.write_text(
        json.dumps(
            {
                "template": "triple_panel/v1",
                "duration_seconds": 20,
                "panels": {
                    "top": {"source": None, "motion": "static"},
                    "middle": {"source": None, "motion": "generated"},
                    "bottom": {"source": None, "motion": "static"},
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="generated source video"):
        TriplePanelManifest.load(manifest_path)

    Image.new("RGB", (64, 64), "red").save(tmp_path / "middle.png")
    manifest_path.write_text(
        json.dumps(
            {
                "template": "triple_panel/v1",
                "duration_seconds": 20,
                "panels": {
                    "top": {"source": None, "motion": "static"},
                    "middle": {"source": "middle.png", "motion": "generated"},
                    "bottom": {"source": None, "motion": "static"},
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must be a video"):
        compose_triple_panel_video(manifest_path, tmp_path / "invalid.mp4")

    with pytest.raises(ValueError, match="either both be provided or both be omitted"):
        TriplePanelManifest.from_dict(
            {
                "template": "triple_panel/v1",
                "duration_seconds": 20,
                "panels": {
                    "top": {"source": "top.png", "motion": "static"},
                    "middle": {"source": "middle.mp4", "motion": "generated"},
                    "bottom": {"source": None, "motion": "static"},
                },
            }
        )


def test_story_video_manifest_requires_declared_speakers():
    with pytest.raises(ValueError, match="undeclared cast"):
        StoryVideoManifest.from_dict(
            {
                "template": "story_video/v1",
                "cast": {"narrator": {"name": "旁白"}},
                "scenes": [
                    {
                        "id": "opening",
                        "video_path": "opening.mp4",
                        "lines": [{"speaker": "student", "text": "你好"}],
                    }
                ],
            }
        )


def test_story_video_manifest_accepts_hold_last_fit_mode():
    manifest = StoryVideoManifest.from_dict(
        {
            "template": "story_video/v1",
            "video_fit_mode": "hold_last",
            "cast": {"narrator": {"name": "旁白"}},
            "scenes": [
                {
                    "id": "opening",
                    "video_path": "opening.mp4",
                    "lines": [{"speaker": "narrator", "text": "你好"}],
                }
            ],
        }
    )

    assert manifest.video_fit_mode == "hold_last"
    assert manifest.to_dict()["video_fit_mode"] == "hold_last"


def test_story_video_manifest_accepts_output_fps_override():
    manifest = StoryVideoManifest.from_dict(
        {
            "template": "story_video/v1",
            "output_fps": 50,
            "cast": {"narrator": {"name": "narrator"}},
            "scenes": [
                {
                    "id": "opening",
                    "video_path": "opening.mp4",
                    "lines": [{"speaker": "narrator", "text": "hello"}],
                }
            ],
        }
    )

    assert manifest.output_fps == 50
    assert manifest.to_dict()["output_fps"] == 50


@pytest.mark.parametrize("output_fps", [0, 121, 30.0, True])
def test_story_video_manifest_rejects_invalid_output_fps(output_fps):
    with pytest.raises(ValueError, match="output_fps"):
        StoryVideoManifest.from_dict(
            {
                "template": "story_video/v1",
                "output_fps": output_fps,
                "cast": {"narrator": {"name": "narrator"}},
                "scenes": [
                    {
                        "id": "opening",
                        "video_path": "opening.mp4",
                        "lines": [{"speaker": "narrator", "text": "hello"}],
                    }
                ],
            }
        )


def test_story_video_hold_last_fit_does_not_loop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    commands: list[list[str]] = []
    monkeypatch.setattr(
        story_video_module,
        "_run_ffmpeg",
        lambda command, purpose: commands.append(command),
    )

    story_video_module._compose_scene(
        "scene.mp4",
        tmp_path / "audio.wav",
        tmp_path / "output.mp4",
        4.5,
        resolve_quality_profile("preview"),
        "hold_last",
    )

    command = commands[0]
    filter_value = command[command.index("-filter_complex") + 1]
    assert "-stream_loop" not in command
    assert "tpad=stop_mode=clone:stop_duration=4.500" in filter_value
    assert "trim=duration=4.500" in filter_value


def test_story_video_composes_narrator_and_character_audio(tmp_path: Path):
    video = tmp_path / "scene.mp4"
    narrator_audio = tmp_path / "narrator.wav"
    character_audio = tmp_path / "character.wav"
    manifest_path = tmp_path / "story.json"
    output = tmp_path / "story.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=540x960:r=24:d=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    for audio_path, frequency in ((narrator_audio, "440"), (character_audio, "660")):
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={frequency}:duration=0.45",
                str(audio_path),
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )
    manifest_path.write_text(
        json.dumps(
            {
                "template": "story_video/v1",
                "title": "配音验收",
                "quality_profile": "preview",
                "responsibilities": {
                    "storyboard": "hermes",
                    "animation": "claude_code",
                    "assembly": "codex",
                },
                "cast": {
                    "narrator": {"name": "旁白", "voice": "zh-CN-XiaoxiaoNeural"},
                    "student": {"name": "阿宁", "voice": "zh-CN-YunxiNeural"},
                },
                "scenes": [
                    {
                        "id": "opening",
                        "video_path": "scene.mp4",
                        "lines": [
                            {
                                "speaker": "narrator",
                                "text": "深夜，阿宁收到一条消息。",
                                "audio_path": "narrator.wav",
                                "pause_after_seconds": 0.1,
                            },
                            {
                                "speaker": "student",
                                "text": "这是真的吗？",
                                "audio_path": "character.wav",
                            },
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = compose_story_video(manifest_path, output)

    assert result == str(output)
    report = json.loads(output.with_suffix(".quality.json").read_text(encoding="utf-8"))
    timeline = json.loads(output.with_suffix(".timeline.json").read_text(encoding="utf-8"))
    assert report["passed"] is True
    assert report["metadata"]["width"] == 540
    assert [line["speaker"] for line in timeline["lines"]] == ["narrator", "student"]
    assert timeline["lines"][0]["end"] <= timeline["lines"][1]["start"]


def test_triple_panel_regions_scale_with_quality_profile():
    regions = triple_panel_regions("preview")
    assert regions["top"] == (0, 0, 540, 312)
    assert regions["middle"] == (0, 324, 540, 312)
    assert regions["bottom"] == (0, 648, 540, 312)


def test_character_asset_gate_reports_hard_alpha_edges(tmp_path: Path):
    asset_path = tmp_path / "character.png"
    image = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    for x in range(8, 24):
        for y in range(8, 24):
            image.putpixel((x, y), (255, 120, 30, 255))
    image.save(asset_path)

    report = VideoQualityGate().inspect_character_asset(asset_path, "static")
    assert report.passed
    assert report.metadata["transparent_ratio"] > 0
    assert any(issue.code == "hard_alpha_edge" for issue in report.warnings)


def test_presenter_preview_layout_scales_with_profile():
    composer = PresenterComposer("preview")
    assert (composer.width, composer.height, composer.fps) == (540, 960, 24)
    assert composer._role_width("medium") == 220
    assert composer._role_position("right_bottom") == ("W-w-21", "H-h-43")


def test_presenter_concat_keeps_faststart(monkeypatch, tmp_path: Path):
    composer = PresenterComposer("publish")
    commands: list[list[str]] = []
    monkeypatch.setattr(composer, "_run", lambda command, timeout=600: commands.append(command))
    monkeypatch.setattr(composer, "_verify_final_video", lambda *args, **kwargs: None)

    composer.concatenate(
        [PresenterSegment(index=0, text="test", clip_path=str(tmp_path / "segment.mp4"))],
        tmp_path / "final.mp4",
    )

    command = commands[0]
    assert command[command.index("-movflags") + 1] == "+faststart"


def test_quality_report_writes_diagnostic_json(tmp_path: Path):
    report = VideoQualityReport(path="video.mp4", profile="publish")
    report.add_issue("low_bitrate", "too low", severity="warning")
    target = tmp_path / "video.quality.json"
    report.write_json(target)
    saved = json.loads(target.read_text(encoding="utf-8"))
    assert saved["passed"] is True
    assert saved["issues"][0]["code"] == "low_bitrate"


def test_compose_video_uses_profile_encoding_and_quality_gate(monkeypatch, tmp_path: Path):
    from src.content_factory import video_composer

    captured: list[list[str]] = []
    monkeypatch.setattr(video_composer, "get_duration", lambda path: 3.0 if path.endswith("clip.mp4") else 6.0)
    monkeypatch.setattr(video_composer, "_run_ffmpeg", lambda command: captured.append(command) or True)
    monkeypatch.setattr(video_composer, "_verify_final_output", lambda *args, **kwargs: True)

    output = video_composer.compose_video(
        "clip.mp4",
        "voice.wav",
        output_dir=str(tmp_path),
        output_name="publish",
        quality_profile="publish",
    )

    assert output.endswith("publish.mp4")
    command = captured[0]
    assert "flags=lanczos" in command[command.index("-filter_complex") + 1]
    assert command[command.index("-b:v") + 1] == "3000000"
    assert command[command.index("-preset") + 1] == "medium"
    assert command[command.index("-movflags") + 1] == "+faststart"


def test_comfy_retry_passes_active_preset_to_generation(monkeypatch, tmp_path: Path):
    resolver = BackgroundResolver()
    received = []

    def fake_create(**kwargs):
        received.append(kwargs["preset"])
        if len(received) == 1:
            raise ComfyOOMError("oom")
        return True

    monkeypatch.setattr(resolver, "_create_comfy_background", fake_create)
    monkeypatch.setattr("src.content_factory.presenter.background_resolver.sample_gpu_memory", lambda: (None, None))
    result = resolver._create_comfy_background_with_retry(
        prompt="test",
        output_path=tmp_path / "background.png",
        seed=7,
    )

    assert result == tmp_path / "background.png"
    assert received == RETRY_PRESETS[:2]


def test_quality_gate_runs_against_a_real_preview_video(tmp_path: Path):
    output = tmp_path / "preview.mp4"
    command = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=red:s=540x960:r=24:d=1",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=48000:cl=stereo",
        "-shortest",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        str(output),
    ]
    subprocess.run(command, check=True, capture_output=True, timeout=60)

    report = VideoQualityGate().inspect(output, "preview", expected_duration=1.0)
    assert report.passed
    assert report.metadata["width"] == 540
    assert report.metadata["fps"] == 24.0


def test_compose_video_real_publish_pipeline_writes_quality_report(tmp_path: Path):
    clip = tmp_path / "clip.mp4"
    audio = tmp_path / "voice.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=540x960:r=30:d=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(clip),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(audio)],
        check=True,
        capture_output=True,
        timeout=60,
    )

    from src.content_factory.video_composer import compose_video

    output = compose_video(
        str(clip),
        str(audio),
        output_dir=str(tmp_path),
        output_name="publish_output",
        quality_profile="publish",
    )

    assert output.endswith("publish_output.mp4")
    report_path = tmp_path / "publish_output.quality.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["passed"] is True
    assert report["metadata"]["width"] == 1080
    assert report["metadata"]["height"] == 1920
    assert report["metadata"]["fps"] == 30.0


def test_compose_triple_panel_writes_manifest_and_motion_report(tmp_path: Path):
    top = tmp_path / "top.png"
    bottom = tmp_path / "bottom.png"
    middle = tmp_path / "middle.mp4"
    audio = tmp_path / "voice.wav"
    manifest_path = tmp_path / "triple_panel.json"
    output = tmp_path / "triple_panel.mp4"
    Image.new("RGB", (540, 312), "red").save(top)
    Image.new("RGB", (540, 312), "blue").save(bottom)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=540x312:r=24:d=1.2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(middle),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1.2", str(audio)],
        check=True,
        capture_output=True,
        timeout=60,
    )
    manifest_path.write_text(
        json.dumps(
            {
                "template": "triple_panel/v1",
                "duration_seconds": 1.2,
                "quality_profile": "preview",
                "audio_path": "voice.wav",
                "panels": {
                    "top": {"source": "top.png", "motion": "static"},
                    "middle": {"source": "middle.mp4", "motion": "generated"},
                    "bottom": {"source": "bottom.png", "motion": "static"},
                },
            }
        ),
        encoding="utf-8",
    )

    result = compose_triple_panel_video(manifest_path, output)

    assert result == str(output)
    report = json.loads(output.with_suffix(".quality.json").read_text(encoding="utf-8"))
    resolved_manifest = json.loads(output.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    assert report["passed"] is True
    assert report["metadata"]["layout_mode"] == "triple_panel"
    assert report["metadata"]["panel_motion"]["top"]["max_frame_distance"] <= 1.2
    assert report["metadata"]["panel_motion"]["middle"]["max_frame_distance"] > 1.2
    assert report["metadata"]["panel_motion"]["bottom"]["max_frame_distance"] <= 1.2
    assert Path(resolved_manifest["panels"]["middle"]["source"]).is_absolute()


def test_triple_panel_quality_failure_keeps_existing_output(tmp_path: Path):
    middle = tmp_path / "static_middle.mp4"
    manifest_path = tmp_path / "static_middle.json"
    output = tmp_path / "accepted.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=yellow:s=540x312:r=24:d=1.2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(middle),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    manifest_path.write_text(
        json.dumps(
            {
                "template": "triple_panel/v1",
                "duration_seconds": 1.2,
                "quality_profile": "preview",
                "panels": {
                    "top": {"source": None, "motion": "static"},
                    "middle": {"source": "static_middle.mp4", "motion": "generated"},
                    "bottom": {"source": None, "motion": "static"},
                },
            }
        ),
        encoding="utf-8",
    )
    output.write_bytes(b"previously-accepted-output")

    with pytest.raises(RuntimeError, match="quality gate failed"):
        compose_triple_panel_video(manifest_path, output)

    report = json.loads(output.with_suffix(".quality.json").read_text(encoding="utf-8"))
    assert output.read_bytes() == b"previously-accepted-output"
    assert not output.with_name("accepted.pending.mp4").exists()
    assert report["metadata"]["layout_mode"] == "single_scene"
    assert set(report["metadata"]["panel_motion"]) == {"middle"}
    assert any(issue["code"] == "dynamic_panel_motion_missing" for issue in report["issues"])


def test_looped_middle_video_passes_nonuniform_motion_sampling(tmp_path: Path):
    middle = tmp_path / "loop_source.mp4"
    manifest_path = tmp_path / "looped.json"
    output = tmp_path / "looped.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=540x312:r=24:d=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(middle),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    manifest_path.write_text(
        json.dumps(
            {
                "template": "triple_panel/v1",
                "duration_seconds": 6,
                "quality_profile": "preview",
                "panels": {
                    "top": {"source": None, "motion": "static"},
                    "middle": {"source": "loop_source.mp4", "motion": "generated"},
                    "bottom": {"source": None, "motion": "static"},
                },
            }
        ),
        encoding="utf-8",
    )

    compose_triple_panel_video(manifest_path, output)

    report = json.loads(output.with_suffix(".quality.json").read_text(encoding="utf-8"))
    assert report["passed"] is True
    assert report["metadata"]["layout_mode"] == "single_scene"
    assert set(report["metadata"]["panel_motion"]) == {"middle"}
    assert report["metadata"]["panel_motion"]["middle"]["max_active_pixel_ratio"] >= 0.002


def test_quality_document_matches_implemented_defaults():
    document = Path("docs/VIDEO_QUALITY_ARCHITECTURE_RECOMMENDATIONS_2026-07-21.md").read_text(encoding="utf-8")
    publish = resolve_quality_profile("publish")

    assert "doc_status: implemented-initial-phase" in document
    assert f"`{publish.width}x{publish.height}`" in document
    assert f"CRF {publish.crf}" in document
    assert f"preset {publish.preset}" in document
    for preset in RETRY_PRESETS:
        assert f"{preset.width}x{preset.height}, {preset.steps} steps" in document
    for module_name in ("video_quality.py", "video_enhancer.py", "video_quality_gate.py"):
        assert module_name in document
