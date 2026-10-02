from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts/compose_task1_story_v61_full_candidate.py"


def _module():
    spec = importlib.util.spec_from_file_location("v61_full_candidate", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture(tmp_path: Path):
    module = _module()
    plan_path = tmp_path / "plan.json"
    plan_path.write_text("reviewed-plan", encoding="utf-8")
    plans = []
    shots = []
    for index in range(19):
        scene_id = f"beat_{index:02d}"
        duration = 2.0 if index < 18 else 4.8
        audio = tmp_path / f"{scene_id}.wav"
        audio.write_bytes(f"{scene_id}-audio".encode())
        video = tmp_path / f"{scene_id}.mp4"
        video.write_bytes(f"{scene_id}-video".encode())
        video_sha = module._sha256(video)
        audio_sha = module._sha256(audio)
        spoken_artifact = tmp_path / f"{scene_id}_sadtalker.mp4"
        spoken_audit = tmp_path / f"{scene_id}_sadtalker.audit.json"
        rife_binding = tmp_path / f"{scene_id}_rife_binding.json"
        spoken_artifact.write_bytes(f"{scene_id}-spoken".encode())
        spoken_audit.write_text(json.dumps({"scene_id": scene_id}), encoding="utf-8")
        rife_binding.write_text(json.dumps({
            "schema": "fanqie_sadtalker_fullframe/rife_binding/v1",
            "source_sha256": module._sha256(spoken_artifact),
            "output_sha256": video_sha,
            "rife_model": "rife47.pth",
            "rife_multiplier": 2,
            "delivery_fps": 50,
        }), encoding="utf-8")
        metadata = {
            "dialogue_audio_path": str(audio),
            "dialogue_audio_sha256": audio_sha,
            "final_sha256": video_sha,
            "has_presenter": False,
            "musetalk_used": False,
            "spoken_renderer": "sadtalker_fullframe",
            "spoken_renderer_used": True,
            "sadtalker_fullframe_used": True,
            "spoken_renderer_artifact_path": str(spoken_artifact),
            "spoken_renderer_sha256": module._sha256(spoken_artifact),
            "spoken_renderer_audit_path": str(spoken_audit),
            "spoken_renderer_audit_sha256": module._sha256(spoken_audit),
            "rife_binding_path": str(rife_binding),
            "rife_binding_sha256": module._sha256(rife_binding),
            "per_stage_sha256": {
                "rife_binding_sha256": module._sha256(rife_binding),
            },
        }
        plans.append(SimpleNamespace(
            scene_id=scene_id, estimated_duration_s=duration,
            metadata={
                "spoken_closeup": True, "dialogue": f"line-{index}",
                "speaker_id": "actor", "dialogue_audio_path": str(audio),
            },
        ))
        shots.append({
            "position": index + 1, "scene_id": scene_id,
            "source": "new_full_batch_render", "missing": [],
            "assets": [{
                "scene_id": scene_id, "video_path": str(video),
                "duration_s": duration, "provider_name": "test",
                "metadata": metadata,
            }],
        })
    progress = {
        "schema_version": module.PROGRESS_SCHEMA,
        "task_id": 1, "scope": "full_19_beat_render",
        "result": module.EXPECTED_RESULT,
        "plan_path": str(plan_path),
        "review_path": str(tmp_path / "smoke_review.json"),
        "smoke_progress_path": str(tmp_path / "smoke_progress.json"),
        "render_signer_id": "renderer@example",
        "render_attestation_receipt_path": str(tmp_path / "render_receipt.json"),
        "render_attestation_namespace": (
            module.render_attestation_gate.full_batch.RENDER_ATTESTATION_NAMESPACE
        ),
        "render_attestation_required": True,
        "render_attestation_completed": True,
        "review_certificate_sha256": "C" * 64,
        "gates": {
            "smoke_machine_gate_passed": True,
            "smoke_human_review_passed": True,
            "full_audio_prepared": True,
            "full_runtime_preflight_passed": True,
            "full_19_shots_rendered": True,
            "full_video_human_review_required": True,
            "full_video_human_approval_obtained": False,
            "matching_fanqie_task_confirmed": False,
            "publish_allowed": False,
            "fanqie_backfill_allowed": False,
        },
        "shots": shots,
    }
    progress_path = tmp_path / "progress.json"
    progress_path.write_text(json.dumps(progress), encoding="utf-8")
    receipt_path = Path(progress["render_attestation_receipt_path"])
    receipt_path.write_text(json.dumps({
        "schema_version": module.render_attestation_gate.RECEIPT_SCHEMA,
        "progress_path": str(progress_path.resolve()),
        "renderer_id": "renderer@example",
    }), encoding="utf-8")
    original_sha = module._sha256

    def hash_with_plan(path: Path) -> str:
        return module.smoke.EXPECTED_PLAN_SHA256 if Path(path) == plan_path else original_sha(Path(path))

    module._sha256 = hash_with_plan
    module.smoke._load_structured_scene_plan = lambda *args, **kwargs: plans
    reviewed = []
    for shot in shots[:7]:
        shot["source"] = "frontend_human_approved_smoke_candidate"
        asset = shot["assets"][0]
        reviewed.append({
            "scene_id": shot["scene_id"], "path": asset["video_path"],
            "sha256": asset["metadata"]["final_sha256"],
        })
    progress_path.write_text(json.dumps(progress), encoding="utf-8")
    module._test_smoke_certificate = {
        "schema_version": "fanqie_v61_smoke_review_certificate/v2",
        "approval_source": "authenticated_streamlit_frontend",
        "review_path": progress["review_path"],
        "review_sha256": "A" * 64,
        "progress_path": progress["smoke_progress_path"],
        "progress_sha256": "B" * 64,
        "candidates": reviewed,
    }
    return module, plan_path, progress_path, plans, progress


def _probe(plans):
    durations = {plan.scene_id: plan.estimated_duration_s for plan in plans}
    return lambda path: {
        "duration_seconds": durations[path.stem], "fps": 50.0,
        "width": 1080, "height": 1920, "audio_present": False,
        "audio_sample_rate": None, "audio_channels": None,
    }


def _smoke_validator(module):
    return lambda *args, **kwargs: module._test_smoke_certificate


def _render_validator(module, progress_path: Path):
    def validate(*args, **kwargs):
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        receipt_path = Path(progress["render_attestation_receipt_path"])
        receipt_sha = module._sha256(receipt_path)
        return {
            "accepted": True,
            "progress_sha256": module._sha256(progress_path),
            "plan_sha256": module._sha256(Path(progress["plan_path"])),
            "signer_id": progress["render_signer_id"],
            "attestation_receipt_schema": module.render_attestation_gate.RECEIPT_SCHEMA,
            "attestation_receipt_path": str(receipt_path.resolve()),
            "attestation_receipt_sha256": receipt_sha,
        }
    return validate


def test_validates_exact_19_shots_and_explicit_audio(tmp_path: Path) -> None:
    module, plan_path, progress_path, plans, _ = _fixture(tmp_path)
    _, loaded_plans, assets, evidence = module._validate_progress(
        progress_path, plan_path, probe_video=_probe(plans),
        validate_smoke_review=_smoke_validator(module),
        validate_render_attestation=_render_validator(module, progress_path),
    )
    assert len(loaded_plans) == len(assets) == len(evidence) == 19
    assert all(Path(item["audio_path"]).is_file() for item in evidence)


def test_rejects_missing_full_render_gate(tmp_path: Path) -> None:
    module, plan_path, progress_path, plans, progress = _fixture(tmp_path)
    progress["gates"]["full_19_shots_rendered"] = False
    progress_path.write_text(json.dumps(progress), encoding="utf-8")
    with pytest.raises(ValueError, match="full_19_shots_rendered"):
        module._validate_progress(
            progress_path, plan_path, probe_video=_probe(plans),
            validate_smoke_review=_smoke_validator(module),
            validate_render_attestation=_render_validator(module, progress_path),
        )


def test_rejects_any_missing_explicit_audio(tmp_path: Path) -> None:
    module, plan_path, progress_path, plans, progress = _fixture(tmp_path)
    progress["shots"][3]["assets"][0]["metadata"]["dialogue_audio_path"] = ""
    progress_path.write_text(json.dumps(progress), encoding="utf-8")
    with pytest.raises(ValueError, match="explicit audio file is missing"):
        module._validate_progress(
            progress_path, plan_path, probe_video=_probe(plans),
            validate_smoke_review=_smoke_validator(module),
            validate_render_attestation=_render_validator(module, progress_path),
        )


def test_rejects_sadtalker_rife_binding_not_matching_final_video(tmp_path: Path) -> None:
    module, plan_path, progress_path, plans, progress = _fixture(tmp_path)
    metadata = progress["shots"][8]["assets"][0]["metadata"]
    binding_path = Path(metadata["rife_binding_path"])
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    binding["output_sha256"] = "0" * 64
    binding_path.write_text(json.dumps(binding), encoding="utf-8")
    metadata["rife_binding_sha256"] = module._sha256(binding_path)
    metadata["per_stage_sha256"]["rife_binding_sha256"] = module._sha256(binding_path)
    progress_path.write_text(json.dumps(progress), encoding="utf-8")
    with pytest.raises(ValueError, match="RIFE source/output binding contract failed"):
        module._validate_progress(
            progress_path, plan_path, probe_video=_probe(plans),
            validate_smoke_review=_smoke_validator(module),
            validate_render_attestation=_render_validator(module, progress_path),
        )


def test_rejects_wrong_silence_audio_sha(tmp_path: Path) -> None:
    module, plan_path, progress_path, plans, progress = _fixture(tmp_path)
    plans[1].metadata["spoken_closeup"] = False
    plans[1].metadata["dialogue"] = ""
    progress["shots"][1]["assets"][0]["metadata"]["musetalk_used"] = False
    progress["shots"][1]["assets"][0]["metadata"]["dialogue_audio_sha256"] = "F" * 64
    progress_path.write_text(json.dumps(progress), encoding="utf-8")
    with pytest.raises(ValueError, match="explicit audio SHA mismatch"):
        module._validate_progress(
            progress_path, plan_path, probe_video=_probe(plans),
            validate_smoke_review=_smoke_validator(module),
            validate_render_attestation=_render_validator(module, progress_path),
        )


def test_rejects_reused_shot_not_bound_to_frontend_smoke_review(tmp_path: Path) -> None:
    module, plan_path, progress_path, plans, _ = _fixture(tmp_path)
    module._test_smoke_certificate["candidates"][0]["sha256"] = "E" * 64
    with pytest.raises(ValueError, match="differs from frontend smoke review"):
        module._validate_progress(
            progress_path, plan_path, probe_video=_probe(plans),
            validate_smoke_review=_smoke_validator(module),
            validate_render_attestation=_render_validator(module, progress_path),
        )


def test_composes_candidate_but_keeps_publish_closed(tmp_path: Path) -> None:
    module, plan_path, progress_path, plans, _ = _fixture(tmp_path)
    output_root = tmp_path / "candidate"

    def build_manifest(**kwargs):
        return {
            "template": "story_video/v1", "scenes": [
                {"id": plan.scene_id, "lines": [{"audio_path": plan.metadata["dialogue_audio_path"]}]}
                for plan in kwargs["scene_plans"]
            ],
        }

    module._build_manifest = build_manifest

    def composer(manifest: Path, raw: Path) -> None:
        raw.write_bytes(b"raw-video")

    def subtitle_burner(raw: Path, subtitles: Path, candidate: Path) -> None:
        candidate.write_bytes(b"full-candidate")

    shot_probe = _probe(plans)

    def probe(path: Path):
        if path.name == "candidate.mp4":
            return {
                "duration_seconds": 40.8, "fps": 50.0, "width": 1080,
                "height": 1920, "audio_present": True,
                "audio_sample_rate": 48000, "audio_channels": 2,
            }
        return shot_probe(path)

    result = module.compose_candidate(
        progress_path=progress_path, plan_path=plan_path,
        output_root=output_root, probe_video=probe,
        composer=composer, subtitle_burner=subtitle_burner,
        validate_smoke_review=_smoke_validator(module),
        validate_render_attestation=_render_validator(module, progress_path),
    )
    assert result["machine_composition_gate_passed"] is True
    assert result["human_full_video_review_completed"] is False
    assert result["douyin_upload_allowed"] is False
    assert result["fanqie_backfill_allowed"] is False
    assert (output_root / "candidate.mp4").is_file()
    manifest = json.loads((output_root / "story_manifest.json").read_text(encoding="utf-8"))
    assert manifest["responsibilities"]["spoken_closeups"] == "sadtalker_fullframe"
    assert "musetalk" not in manifest["responsibilities"]["spoken_closeups"].lower()
    audit = json.loads((output_root / "candidate_audit.json").read_text(encoding="utf-8"))
    receipt_path = Path(audit["render_attestation_receipt_path"])
    assert audit["render_attestation_signer_id"] == "renderer@example"
    assert audit["render_attestation_receipt_schema"] == module.render_attestation_gate.RECEIPT_SCHEMA
    assert receipt_path.is_file()
    assert audit["render_attestation_receipt_sha256"] == module._sha256(receipt_path)


def test_refuses_to_overwrite_candidate_evidence(tmp_path: Path) -> None:
    module, plan_path, progress_path, _, _ = _fixture(tmp_path)
    output_root = tmp_path / "candidate"
    output_root.mkdir()
    with pytest.raises(ValueError, match="Refusing to overwrite"):
        module.compose_candidate(
            progress_path=progress_path, plan_path=plan_path,
            output_root=output_root,
            validate_smoke_review=_smoke_validator(module),
            validate_render_attestation=_render_validator(module, progress_path),
        )


def test_rejects_manifest_with_any_secondary_line_missing_audio(tmp_path: Path) -> None:
    module, plan_path, progress_path, plans, _ = _fixture(tmp_path)
    output_root = tmp_path / "candidate"

    def bad_manifest(**kwargs):
        scenes = [{
            "id": plan.scene_id,
            "lines": [{"audio_path": plan.metadata["dialogue_audio_path"]}],
        } for plan in kwargs["scene_plans"]]
        scenes[0]["lines"].append({"audio_path": ""})
        return {"template": "story_video/v1", "scenes": scenes}

    module._build_manifest = bad_manifest
    with pytest.raises(ValueError, match="line without explicit audio"):
        module.compose_candidate(
            progress_path=progress_path, plan_path=plan_path,
            output_root=output_root, probe_video=_probe(plans),
            validate_smoke_review=_smoke_validator(module),
            validate_render_attestation=_render_validator(module, progress_path),
        )
    assert not output_root.exists()


def test_rejects_missing_render_receipt_binding(tmp_path: Path) -> None:
    module, plan_path, progress_path, plans, _ = _fixture(tmp_path)
    with pytest.raises(ValueError, match="render attestation receipt is invalid"):
        module._validate_progress(
            progress_path,
            plan_path,
            probe_video=_probe(plans),
            validate_smoke_review=_smoke_validator(module),
            validate_render_attestation=lambda *args, **kwargs: {
                "accepted": True,
                "progress_sha256": module._sha256(progress_path),
            },
        )


@pytest.mark.parametrize("tamper_target", ["progress", "receipt"])
def test_composition_rejects_attestation_source_changed_mid_run(
    tmp_path: Path, tamper_target: str,
) -> None:
    module, plan_path, progress_path, plans, progress = _fixture(tmp_path)
    output_root = tmp_path / f"candidate-{tamper_target}"
    module._build_manifest = lambda **kwargs: {
        "template": "story_video/v1",
        "scenes": [
            {"id": plan.scene_id, "lines": [{"audio_path": plan.metadata["dialogue_audio_path"]}]}
            for plan in kwargs["scene_plans"]
        ],
    }

    def composer(manifest: Path, raw: Path) -> None:
        raw.write_bytes(b"raw-video")
        target = (
            progress_path
            if tamper_target == "progress"
            else Path(progress["render_attestation_receipt_path"])
        )
        target.write_bytes(target.read_bytes() + b"tampered")

    def subtitle_burner(raw: Path, subtitles: Path, candidate: Path) -> None:
        candidate.write_bytes(b"full-candidate")

    shot_probe = _probe(plans)

    def probe(path: Path):
        if path.name == "candidate.mp4":
            return {
                "duration_seconds": 40.8,
                "fps": 50.0,
                "width": 1080,
                "height": 1920,
                "audio_present": True,
                "audio_sample_rate": 48000,
                "audio_channels": 2,
            }
        return shot_probe(path)

    with pytest.raises(ValueError, match=f"{tamper_target} changed during composition"):
        module.compose_candidate(
            progress_path=progress_path,
            plan_path=plan_path,
            output_root=output_root,
            probe_video=probe,
            composer=composer,
            subtitle_burner=subtitle_burner,
            validate_smoke_review=_smoke_validator(module),
            validate_render_attestation=_render_validator(module, progress_path),
        )
    assert not output_root.exists()
