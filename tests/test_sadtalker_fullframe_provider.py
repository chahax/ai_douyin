from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw


ROOT = Path(r"D:\IT\ai_douyin")
P0_ROOT = Path(r"D:\IT\ai_douyin_p0")
for value in (ROOT / "scripts", P0_ROOT):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

import sadtalker_fullframe_provider as module
from src.novel_promotion.scene_provider import SceneAsset, SceneAssetResult, ScenePlan


class _FakeLTX:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self._rife_model = "rife47.pth"
        self._rife_multiplier = 2
        self.rife_calls: list[dict[str, str]] = []

    def provide_scenes(self, plans, output_dir):
        self.calls.append([plan.scene_id for plan in plans])
        return SceneAssetResult(assets=[SceneAsset(
            scene_id=plans[0].scene_id,
            video_path=str(Path(output_dir) / f"{plans[0].scene_id}.mp4"),
            duration_s=plans[0].estimated_duration_s,
            provider_name="comfyui_ltx_i2v",
            metadata={"has_presenter": False},
        )])

    def _run_rife(self, source_path: Path, output_dir: Path, shot_id: str) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        destination = output_dir / f"{shot_id}_rife50.mp4"
        destination.write_bytes(source_path.read_bytes() + b"-fresh-rife")
        self.rife_calls.append({
            "source_path": str(source_path),
            "output_path": str(destination),
            "shot_id": shot_id,
        })


def _provider(tmp_path: Path, fake_ltx=None) -> module.HybridLiveActionV61Provider:
    wrapper = tmp_path / "wrapper.py"
    wrapper.write_text("print('wrapper')\n", encoding="utf-8")
    python = tmp_path / "python.exe"
    python.write_bytes(b"python")
    root = tmp_path / "SadTalker"
    root.mkdir()
    (root / "inference.py").write_text("# inference\n", encoding="utf-8")
    checkpoints = root / "checkpoints"
    checkpoints.mkdir()
    comfy_input = tmp_path / "input"
    comfy_output = tmp_path / "output"
    comfy_input.mkdir()
    comfy_output.mkdir()
    return module.HybridLiveActionV61Provider(
        base_url="http://127.0.0.1:8190",
        comfy_input=str(comfy_input),
        comfy_output=str(comfy_output),
        evidence_root=str(tmp_path / "evidence"),
        timeout_seconds=30,
        sadtalker_python=str(python),
        sadtalker_root=str(root),
        sadtalker_checkpoint_dir=str(checkpoints),
        sadtalker_wrapper=str(wrapper),
        ltx_provider=fake_ltx or _FakeLTX(),
    )


def test_routes_spoken_to_fullframe_and_silent_to_ltx(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeLTX()
    provider = _provider(tmp_path, fake)
    spoken = ScenePlan("spoken", estimated_duration_s=1.0, metadata={"spoken_closeup": True})
    silent = ScenePlan("silent", estimated_duration_s=1.0, metadata={"spoken_closeup": False})
    monkeypatch.setattr(provider, "_generate_spoken", lambda plan, output: SceneAsset(
        scene_id=plan.scene_id, video_path=str(output / "spoken.mp4"),
        duration_s=1.0, provider_name=provider.name,
        metadata={"spoken_renderer": module.SPOKEN_RENDERER, "musetalk_used": False},
    ))
    result = provider.provide_scenes([spoken, silent], tmp_path / "render")
    assert [asset.scene_id for asset in result.assets] == ["spoken", "silent"]
    assert fake.calls == [["silent"]]
    assert result.assets[0].metadata["spoken_renderer"] == "sadtalker_fullframe"
    assert result.assets[0].metadata["musetalk_used"] is False


def test_spoken_fingerprint_binds_wrapper_and_audio(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    plan = ScenePlan("shot", estimated_duration_s=2.8, metadata={"spoken_closeup": True})
    first = provider._fingerprint(plan=plan, anchor_sha="A" * 64, audio_sha="B" * 64)
    second = provider._fingerprint(plan=plan, anchor_sha="A" * 64, audio_sha="C" * 64)
    assert first != second
    provider._wrapper.write_text("print('changed')\n", encoding="utf-8")
    third = provider._fingerprint(plan=plan, anchor_sha="A" * 64, audio_sha="B" * 64)
    assert first != third


def test_cache_requires_bound_wrapper_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _provider(tmp_path)
    fingerprint = "D" * 64
    cache = provider._cache_dir(fingerprint)
    cache.mkdir(parents=True)
    clip = cache / "rife_clip.mp4"
    spoken = cache / "sadtalker_fullframe_clip.mp4"
    audit = cache / "sadtalker_fullframe.audit.json"
    rife_binding = cache / "rife_binding.json"
    clip.write_bytes(b"final")
    spoken.write_bytes(b"spoken")
    audit.write_text(json.dumps({
        "schema": module.WRAPPER_AUDIT_SCHEMA,
        "source_image_sha256": "A" * 64,
        "dialogue_audio_sha256": "B" * 64,
        "output_sha256": module._sha256(spoken),
        "plate_preservation": {"passed": True},
    }), encoding="utf-8")
    rife_binding.write_text(json.dumps({
        "schema": module.RIFE_BINDING_SCHEMA,
        "source_sha256": module._sha256(spoken),
        "output_sha256": module._sha256(clip),
        "rife_model": provider._ltx._rife_model,
        "rife_multiplier": provider._ltx._rife_multiplier,
    }), encoding="utf-8")
    meta = {
        "schema": module.SPOKEN_CACHE_SCHEMA,
        "fingerprint": fingerprint,
        "shot_anchor_sha256": "A" * 64,
        "dialogue_audio_sha256": "B" * 64,
        "spoken_renderer": module.SPOKEN_RENDERER,
        "final_sha256": module._sha256(clip),
        "spoken_renderer_sha256": module._sha256(spoken),
        "spoken_renderer_audit_sha256": module._sha256(audit),
        "rife_binding_sha256": module._sha256(rife_binding),
        "runtime_manifest": provider._runtime_manifest(),
        "delivery_fps": 50,
    }
    (cache / "audit_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    monkeypatch.setattr(module, "_ffprobe_duration", lambda _: 2.8)
    monkeypatch.setattr(module, "_ffprobe_fps", lambda _: 50.0)
    monkeypatch.setattr(module, "_ffprobe_has_audio", lambda _: True)
    assert provider._valid_cache(
        cache_dir=cache, fingerprint=fingerprint, anchor_sha="A" * 64,
        audio_sha="B" * 64, target_duration=2.8,
    ) == meta
    audit.write_text("{}", encoding="utf-8")
    assert provider._valid_cache(
        cache_dir=cache, fingerprint=fingerprint, anchor_sha="A" * 64,
        audio_sha="B" * 64, target_duration=2.8,
    ) is None


def test_fingerprint_fails_closed_without_rife_binding(tmp_path: Path) -> None:
    fake = _FakeLTX()
    del fake._rife_model
    provider = _provider(tmp_path, fake)
    plan = ScenePlan("shot", estimated_duration_s=2.8, metadata={"spoken_closeup": True})
    with pytest.raises(RuntimeError, match="RIFE model binding unavailable"):
        provider._fingerprint(plan=plan, anchor_sha="A" * 64, audio_sha="B" * 64)


def test_runtime_manifest_recursively_binds_nested_checkpoint(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    nested = provider._checkpoint_dir / "gfpgan" / "weights.pth"
    nested.parent.mkdir()
    nested.write_bytes(b"weights-v1")
    first = provider._runtime_manifest()
    key = str(nested.resolve()).replace("\\", "/")
    assert first[key] == module._sha256(nested)
    provider._runtime_manifest_cache = None
    nested.write_bytes(b"weights-v2")
    second = provider._runtime_manifest()
    assert second[key] != first[key]


def test_fresh_rife_job_is_uniquely_bound_to_current_spoken_clip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeLTX()
    provider = _provider(tmp_path, fake)
    anchor = tmp_path / "anchor.png"
    audio = tmp_path / "dialogue.wav"
    anchor.write_bytes(b"reviewed-anchor")
    audio.write_bytes(b"current-dialogue")
    plan = ScenePlan(
        "shot", estimated_duration_s=2.8,
        metadata={
            "spoken_closeup": True,
            "shot_anchor_image": str(anchor),
            "shot_anchor_sha256": module._sha256(anchor),
            "dialogue_audio_path": str(audio),
        },
    )
    output = tmp_path / "render"
    stale = output / "audit" / "shot" / "shot_rife50.mp4"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"stale-rife")

    def fake_subprocess_run(command, **kwargs):
        if command[0] == "ffprobe":
            return subprocess.CompletedProcess(command, 0, stdout="16000\n", stderr="")
        output_path = Path(command[command.index("--output") + 1])
        audit_path = Path(command[command.index("--audit") + 1])
        work_dir = Path(command[command.index("--work-dir") + 1])
        assert not output_path.exists() and not audit_path.exists() and not work_dir.exists()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"current-spoken-clip")
        audit_path.write_text(json.dumps({
            "schema": module.WRAPPER_AUDIT_SCHEMA,
            "source_image_sha256": module._sha256(anchor),
            "dialogue_audio_sha256": module._sha256(audio),
            "output_path": str(output_path.resolve()),
            "output_sha256": module._sha256(output_path),
            "plate_preservation": {"passed": True},
        }), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_subprocess_run)
    monkeypatch.setattr(module, "_ffprobe_duration", lambda path: 2.8)
    monkeypatch.setattr(
        module, "_ffprobe_fps",
        lambda path: 25.0 if Path(path).name.startswith("shot_sadtalker_fullframe") else 50.0,
    )
    monkeypatch.setattr(module, "_ffprobe_has_audio", lambda path: True)
    asset = provider._generate_spoken(plan, output)
    assert fake.rife_calls and fake.rife_calls[0]["shot_id"].startswith("shot_")
    assert fake.rife_calls[0]["shot_id"] != "shot"
    assert Path(fake.rife_calls[0]["source_path"]).read_bytes() == b"current-spoken-clip"
    assert Path(asset.video_path).read_bytes() != stale.read_bytes()
    binding_path = Path(asset.metadata["rife_binding_path"])
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    spoken_path = Path(asset.metadata["spoken_renderer_artifact_path"])
    assert binding["source_sha256"] == module._sha256(spoken_path)
    assert binding["output_sha256"] == asset.metadata["final_sha256"]
    assert asset.metadata["rife_binding_sha256"] == module._sha256(binding_path)


def test_asset_metadata_never_claims_musetalk(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    plan = ScenePlan("shot", estimated_duration_s=2.8, metadata={"spoken_closeup": True})
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "rife_clip.mp4").write_bytes(b"final")
    (cache / "sadtalker_fullframe_clip.mp4").write_bytes(b"spoken")
    (cache / "sadtalker_fullframe.audit.json").write_bytes(b"audit")
    (cache / "rife_binding.json").write_bytes(b"rife-binding")
    meta = {
        "fingerprint": "F" * 64,
        "shot_anchor_sha256": "A" * 64,
        "dialogue_audio_path": str(tmp_path / "audio.wav"),
        "dialogue_audio_sha256": "B" * 64,
        "spoken_renderer_sha256": module._sha256(cache / "sadtalker_fullframe_clip.mp4"),
        "spoken_renderer_audit_sha256": module._sha256(cache / "sadtalker_fullframe.audit.json"),
        "rife_fps": 50,
        "rife_binding_sha256": module._sha256(cache / "rife_binding.json"),
        "final_sha256": module._sha256(cache / "rife_clip.mp4"),
        "per_stage_sha256": {},
    }
    asset = provider._asset_from_cache(
        plan=plan, cache_dir=cache, meta=meta, output_dir=tmp_path / "out", cached=True
    )
    assert asset.provider_name == "hybrid_live_action_v61"
    assert asset.metadata["spoken_renderer"] == "sadtalker_fullframe"
    assert asset.metadata["musetalk_used"] is False


def test_wrapper_helpers_are_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = ROOT / "scripts" / "run_sadtalker_fullframe.py"
    spec = importlib.util.spec_from_file_location("run_sadtalker_fullframe_test", path)
    wrapper = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(wrapper)
    audit = tmp_path / "audit.json"
    wrapper._write_json_new(audit, {"ok": True})
    with pytest.raises(RuntimeError, match="Refusing to replace"):
        wrapper._write_json_new(audit, {"ok": False})
    runs = tmp_path / "runs"
    runs.mkdir()
    with pytest.raises(RuntimeError, match="exactly one fresh"):
        wrapper._newest_result(runs, 0)

    monkeypatch_payload = subprocess.CompletedProcess(
        args=[], returncode=0,
        stdout=json.dumps({
            "streams": [{
                "codec_type": "video", "avg_frame_rate": "0/0",
                "width": 704, "height": 1248,
            }],
            "format": {"duration": "1.0"},
        }),
        stderr="",
    )
    original_run = wrapper._run
    wrapper._run = lambda *args, **kwargs: monkeypatch_payload
    try:
        with pytest.raises(RuntimeError, match="Invalid video frame rate"):
            wrapper._probe(tmp_path / "invalid.mp4")
    finally:
        wrapper._run = original_run
    monkeypatch.delenv("NUMBA_DISABLE_JIT", raising=False)
    env = wrapper._sadtalker_environment(tmp_path / "isolated-temp")
    assert env["NUMBA_DISABLE_JIT"] == "1"
    assert env["TEMP"] == str(tmp_path / "isolated-temp")
    assert env["TMP"] == str(tmp_path / "isolated-temp")
    assert "NUMBA_DISABLE_JIT" not in os.environ


def test_wrapper_does_not_publish_when_plate_validation_raises(
    tmp_path: Path,
) -> None:
    path = ROOT / "scripts" / "run_sadtalker_fullframe.py"
    spec = importlib.util.spec_from_file_location("run_sadtalker_publish_test", path)
    wrapper = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(wrapper)
    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    temporary = tmp_path / "temporary.mp4"
    temporary.write_bytes(b"video")
    output = tmp_path / "output.mp4"
    original = wrapper._plate_preservation_metrics
    wrapper._plate_preservation_metrics = lambda *args, **kwargs: (_ for _ in ()).throw(
        RuntimeError("synthetic plate failure")
    )
    try:
        with pytest.raises(RuntimeError, match="synthetic plate failure"):
            wrapper._publish_validated_output(
                source=source,
                temporary_output=temporary,
                output=output,
                face_crop_quad=(0, 0, 1, 1),
            )
    finally:
        wrapper._plate_preservation_metrics = original
    assert not temporary.exists()
    assert not output.exists()


def test_wrapper_removes_published_output_when_audit_receipt_fails(
    tmp_path: Path,
) -> None:
    path = ROOT / "scripts" / "run_sadtalker_fullframe.py"
    spec = importlib.util.spec_from_file_location("run_sadtalker_audit_test", path)
    wrapper = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(wrapper)
    output = tmp_path / "published.mp4"
    output.write_bytes(b"published-video")
    audit = tmp_path / "audit.json"
    unrelated = tmp_path / "unrelated.mp4"
    unrelated.write_bytes(b"keep-me")
    original = wrapper._write_json_new
    wrapper._write_json_new = lambda *args, **kwargs: (_ for _ in ()).throw(
        OSError("synthetic audit failure")
    )
    try:
        with pytest.raises(OSError, match="synthetic audit failure"):
            wrapper._write_audit_or_remove_output(
                output=output, audit_path=audit, payload={"ok": True}
            )
    finally:
        wrapper._write_json_new = original
    assert not output.exists()
    assert not audit.exists()
    assert unrelated.read_bytes() == b"keep-me"


def test_input_hash_failure_happens_before_output_publication(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    path = ROOT / "scripts" / "run_sadtalker_fullframe.py"
    spec = importlib.util.spec_from_file_location("run_sadtalker_hash_order_test", path)
    wrapper = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(wrapper)
    source = tmp_path / "source.png"
    audio = tmp_path / "audio.wav"
    crop = tmp_path / "crop.mp4"
    pasted = tmp_path / "pasted.mp4"
    temporary = tmp_path / "temporary.mp4"
    output = tmp_path / "published.mp4"
    audit = tmp_path / "audit.json"
    unrelated = tmp_path / "unrelated.txt"
    for artifact in (source, audio, crop, pasted, temporary):
        artifact.write_bytes(artifact.name.encode("utf-8"))
    unrelated.write_bytes(b"keep-me")
    original_sha256 = wrapper._sha256
    publish_calls = []

    def fail_on_pasted(artifact: Path) -> str:
        if artifact.resolve() == pasted.resolve():
            raise OSError("synthetic pre-publication hash failure")
        return original_sha256(artifact)

    monkeypatch.setattr(wrapper, "_sha256", fail_on_pasted)
    monkeypatch.setattr(
        wrapper,
        "_publish_validated_output",
        lambda **kwargs: publish_calls.append(kwargs),
    )
    with pytest.raises(OSError, match="synthetic pre-publication hash failure"):
        wrapper._publish_with_audit_receipt(
            source=source,
            audio=audio,
            crop_video=crop,
            pasted=pasted,
            temporary_output=temporary,
            output=output,
            audit_path=audit,
            face_crop_quad=(1, 1, 2, 2),
            payload_context={},
        )
    assert publish_calls == []
    assert not output.exists()
    assert not audit.exists()
    assert unrelated.read_bytes() == b"keep-me"


def test_plate_preservation_rejects_replaced_background(tmp_path: Path) -> None:
    path = ROOT / "scripts" / "run_sadtalker_fullframe.py"
    spec = importlib.util.spec_from_file_location("run_sadtalker_plate_test", path)
    wrapper = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(wrapper)
    anchor = tmp_path / "anchor.png"
    image = Image.new("RGB", (176, 312), "#9ec5e8")
    ImageDraw.Draw(image).rectangle((60, 30, 115, 100), fill="#d8a078")
    image.save(anchor)
    preserved = tmp_path / "preserved.mp4"
    face_motion = tmp_path / "face_motion.mp4"
    replaced = tmp_path / "replaced.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(anchor),
        "-t", "0.4", "-r", "25", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(preserved),
    ], check=True)
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(anchor),
        "-vf", "drawbox=x=60:y=30:w=56:h=71:color=red:t=fill",
        "-t", "0.4", "-r", "25", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(face_motion),
    ], check=True)
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
        "color=c=red:s=176x312:r=25", "-t", "0.4", "-c:v", "libx264",
        "-pix_fmt", "yuv420p", str(replaced),
    ], check=True)
    face_quad = (60, 30, 116, 101)
    preserved_metrics = wrapper._plate_preservation_metrics(
        anchor, preserved, face_quad
    )
    motion_metrics = wrapper._plate_preservation_metrics(
        anchor, face_motion, face_quad
    )
    replaced_metrics = wrapper._plate_preservation_metrics(
        anchor, replaced, face_quad
    )
    assert preserved_metrics["passed"] is True
    assert motion_metrics["passed"] is True
    assert preserved_metrics["face_blend_margin_fraction"] == 0.025
    assert (
        motion_metrics["samples"][0]["animated_face_region"]
        ["mean_absolute_difference"]
        > motion_metrics["samples"][0]["background_region"]
        ["mean_absolute_difference"]
    )
    assert replaced_metrics["passed"] is False


def test_plate_preservation_excludes_the_reviewed_25_percent_blend_band(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    path = ROOT / "scripts" / "run_sadtalker_fullframe.py"
    spec = importlib.util.spec_from_file_location("run_sadtalker_blend_band_test", path)
    wrapper = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(wrapper)
    anchor = tmp_path / "anchor.png"
    image = Image.new("RGB", (704, 1248), "#9ec5e8")
    face_quad = (112, 320, 592, 807)
    ImageDraw.Draw(image).rectangle((112, 320, 591, 806), fill="#d8a078")
    image.save(anchor)
    blend_frame = image.copy()
    draw = ImageDraw.Draw(blend_frame)
    # Fill the full 2.5% paste-back ring. At 704x1248 that is 18px horizontal
    # and 31px vertical, large enough to push P95 over 12 with no exclusion.
    draw.rectangle((94, 289, 609, 319), fill="#000000")
    draw.rectangle((94, 807, 609, 837), fill="#000000")
    draw.rectangle((94, 320, 111, 806), fill="#000000")
    draw.rectangle((592, 320, 609, 806), fill="#000000")
    blend_plate = tmp_path / "blend_plate.png"
    blend_frame.save(blend_plate)
    video = tmp_path / "blend_band.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(blend_plate),
        "-t", "0.4", "-r", "25", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(video),
    ], check=True)
    metrics = wrapper._plate_preservation_metrics(anchor, video, face_quad)
    assert metrics["face_blend_margin_fraction"] == 0.025
    assert metrics["background_pixel_fraction"] > 0.60
    assert metrics["passed"] is True
    monkeypatch.setattr(wrapper, "FACE_BLEND_MARGIN_FRACTION", 0.0)
    no_margin = wrapper._plate_preservation_metrics(anchor, video, face_quad)
    assert no_margin["face_blend_margin_fraction"] == 0.0
    assert no_margin["passed"] is False
    assert any(
        sample["difference_percentile_95"] > 12.0
        for sample in no_margin["samples"]
    )


def test_plate_preservation_rejects_crop_that_hides_almost_all_background(
    tmp_path: Path,
) -> None:
    path = ROOT / "scripts" / "run_sadtalker_fullframe.py"
    spec = importlib.util.spec_from_file_location("run_sadtalker_plate_area_test", path)
    wrapper = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(wrapper)
    anchor = tmp_path / "anchor.png"
    Image.new("RGB", (176, 312), "#9ec5e8").save(anchor)
    video = tmp_path / "video.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(anchor),
        "-t", "0.4", "-r", "25", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(video),
    ], check=True)
    with pytest.raises(RuntimeError, match="less than 15%"):
        wrapper._plate_preservation_metrics(anchor, video, (0, 0, 176, 300))
