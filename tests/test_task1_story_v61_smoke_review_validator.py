from __future__ import annotations

import importlib.util
import inspect
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts/validate_task1_story_v61_smoke_review.py"


def _module():
    spec = importlib.util.spec_from_file_location("v61_review_validator", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture(tmp_path: Path):
    module = _module()
    now = datetime.now(timezone.utc)
    contact = tmp_path / "contact.png"
    contact.write_bytes(b"contact-sheet")
    progress_shots = []
    review_shots = []
    packet_candidates = []
    for scene_id, duration in module.SHOT_DURATIONS.items():
        clip = tmp_path / f"{scene_id}.mp4"
        clip.write_bytes((scene_id + "-candidate").encode())
        sha = module._sha256(clip)
        audio = tmp_path / f"{scene_id}.wav"
        audio.write_bytes((scene_id + "-dialogue-audio").encode())
        audio_sha = module._sha256(audio)
        musetalk = tmp_path / f"{scene_id}-musetalk.mp4"
        musetalk.write_bytes((scene_id + "-musetalk-stage").encode())
        musetalk_sha = module._sha256(musetalk)
        progress_shots.append({
            "scene_id": scene_id,
            "assets": [{
                "scene_id": scene_id,
                "video_path": str(clip),
                "duration_s": duration,
                "metadata": {
                    "final_sha256": sha,
                    "has_presenter": False,
                    "musetalk_used": True,
                    "dialogue_audio_path": str(audio),
                    "dialogue_audio_sha256": audio_sha,
                    "musetalk_sha256": musetalk_sha,
                    "musetalk_artifact_path": str(musetalk),
                    "per_stage_sha256": {
                        "dialogue_audio_sha256": audio_sha,
                        "musetalk_sha256": musetalk_sha,
                        "rife_sha256": sha,
                    },
                    "rife_fps": 50.0,
                },
            }],
            "missing": [],
        })
        review_shots.append({
            "scene_id": scene_id,
            "expected_duration_seconds": duration,
            "candidate_path": str(clip),
            "candidate_sha256": sha,
            **{key: True for key in module.SHOT_REVIEW_CHECKS},
            "decision": "approved",
            "notes": "reviewed",
        })
        frames = []
        for frame_index in range(1, 4):
            frame = tmp_path / f"{scene_id}_{frame_index}.png"
            frame.write_bytes(f"{scene_id}-frame-{frame_index}".encode())
            frames.append({
                "position": frame_index,
                "fraction": (0.15, 0.50, 0.85)[frame_index - 1],
                "timestamp_seconds": round(
                    duration * (0.15, 0.50, 0.85)[frame_index - 1], 4
                ),
                "path": str(frame),
                "sha256": module._sha256(frame),
            })
        packet_candidates.append({
            "scene_id": scene_id,
            "video_path": str(clip),
            "video_sha256": sha,
            "dialogue_audio_path": str(audio),
            "dialogue_audio_sha256": audio_sha,
            "musetalk_sha256": musetalk_sha,
            "musetalk_artifact_path": str(musetalk),
            "frames": frames,
        })
    progress = {
        "schema_version": module.PROGRESS_SCHEMA,
        "task_id": 1,
        "scope": "failed_scene_smoke",
        "expected_plan_sha256": module.EXPECTED_PLAN_SHA256,
        "selected_shot_ids": list(module.SHOT_IDS),
        "result": "FAILED_SCENE_SMOKE_RENDERED_AWAITING_HUMAN_REVIEW",
        "finished_at": (now - timedelta(minutes=1)).isoformat(),
        "gates": {
            "static_validation_passed": True,
            "audio_prepared": True,
            "runtime_preflight_passed": True,
            "failed_scene_smoke_rendered": True,
            "human_video_approval_obtained": False,
            "matching_fanqie_task_confirmed": False,
            "publish_allowed": False,
            "fanqie_backfill_allowed": False,
        },
        "shots": progress_shots,
    }
    progress_path = tmp_path / "progress.json"
    progress_path.write_text(json.dumps(progress), encoding="utf-8")
    machine_packet = {
        "schema_version": module.MACHINE_PACKET_SCHEMA,
        "task_id": 1,
        "scope": "failed_scene_smoke",
        "plan_sha256": module.EXPECTED_PLAN_SHA256,
        "source_progress_sha256": module._sha256(progress_path),
        "contact_sheet_sha256": module._sha256(contact),
        "candidate_count": 7,
        "frames_per_candidate": 3,
        "machine_gate_scope": "file_integrity_and_pipeline_provenance_only",
        "human_visual_and_audio_semantic_review_required": True,
        "machine_gate_passed": True,
        "human_review_completed": False,
        "full_19_shot_generation_allowed": False,
        "douyin_upload_allowed": False,
        "fanqie_backfill_allowed": False,
        "candidates": packet_candidates,
        "downstream_source_contract": module.current_downstream_source_contract(),
    }
    machine_packet_path = tmp_path / "machine_review_packet.json"
    machine_packet_path.write_text(json.dumps(machine_packet), encoding="utf-8")
    confirmation_keys = {
        *(f"shot:{scene_id}" for scene_id in module.SHOT_IDS),
        *(f"global:{key}" for key in module.GLOBAL_REVIEW_CHECKS),
    }
    playback_started = now - timedelta(seconds=30)
    playback_finished = now - timedelta(seconds=10)
    review = {
        "schema_version": module.SCHEMA,
        "task_id": 1,
        "scope": "failed_scene_smoke",
        "plan_sha256": module.EXPECTED_PLAN_SHA256,
        "review_status": "approved",
        "decision_source": "authenticated_streamlit_frontend",
        "reviewer": "人工审核员",
        "reviewer_id": "reviewer@example",
        "reviewed_at": now.isoformat(),
        "playback_started_at": playback_started.isoformat(),
        "playback_finished_at": playback_finished.isoformat(),
        "source_progress_path": str(progress_path),
        "reviewed_progress_sha256": module._sha256(progress_path),
        "machine_review_packet_path": str(machine_packet_path),
        "machine_review_packet_sha256": module._sha256(machine_packet_path),
        "candidate_contact_sheet": str(contact),
        "candidate_contact_sheet_sha256": module._sha256(contact),
        "global_gates": {key: True for key in module.GLOBAL_REVIEW_CHECKS},
        "shots": review_shots,
        "frontend_attestation": {
            "confirmations": {key: True for key in confirmation_keys},
            "required_checks": sorted(confirmation_keys),
            "all_required_checks_confirmed": True,
            "video_sha256s": [item["candidate_sha256"] for item in review_shots],
            "machine_packet_sha256": module._sha256(machine_packet_path),
            "required_playback_seconds": sum(module.SHOT_DURATIONS.values()),
            "actual_playback_seconds": (
                playback_finished - playback_started
            ).total_seconds(),
        },
    }
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
    return module, progress_path, review_path, progress, review


def _probe_for(module):
    return lambda path: {
        "duration_seconds": module.SHOT_DURATIONS[path.stem],
        "fps": 50.0,
    }


def test_sadtalker_rife_binding_rejects_wrong_output_sha(tmp_path: Path) -> None:
    module = _module()
    spoken = tmp_path / "spoken.mp4"
    binding_path = tmp_path / "rife_binding.json"
    spoken.write_bytes(b"spoken")
    spoken_sha = module._sha256(spoken)
    binding_path.write_text(json.dumps({
        "schema": "fanqie_sadtalker_fullframe/rife_binding/v1",
        "source_sha256": spoken_sha,
        "output_sha256": "0" * 64,
        "rife_model": "rife47.pth",
        "rife_multiplier": 2,
        "delivery_fps": 50,
    }), encoding="utf-8")
    metadata = {
        "rife_binding_path": str(binding_path),
        "rife_binding_sha256": module._sha256(binding_path),
    }
    packet = {
        "rife_binding_path": str(binding_path),
        "rife_binding_sha256": module._sha256(binding_path),
    }
    spoken_evidence = {
        "renderer": "sadtalker_fullframe",
        "artifact_sha256": spoken_sha,
    }
    with pytest.raises(ValueError, match="RIFE source/output binding contract failed"):
        module._validate_rife_binding(
            metadata, packet, spoken_evidence, "F" * 64, "b01_boast"
        )


def test_accepts_only_complete_bound_review(tmp_path: Path) -> None:
    module, progress_path, review_path, _, _ = _fixture(tmp_path)
    certificate = module.validate_review(
        review_path, progress_path=progress_path, probe_video=_probe_for(module)
    )
    assert certificate["accepted"] is True
    assert certificate["schema_version"] == "fanqie_v61_smoke_review_certificate/v2"
    assert certificate["approval_source"] == "authenticated_streamlit_frontend"
    assert len(certificate["candidates"]) == 7
    assert certificate["gates"]["full_19_shot_generation_allowed"] is True
    assert certificate["gates"]["douyin_upload_allowed"] is False
    assert certificate["gates"]["fanqie_backfill_allowed"] is False


def test_rejects_downstream_source_changed_after_frontend_packet(tmp_path: Path) -> None:
    module, progress_path, review_path, _, _ = _fixture(tmp_path)
    machine_path = Path(json.loads(review_path.read_text(encoding="utf-8"))["machine_review_packet_path"])
    machine = json.loads(machine_path.read_text(encoding="utf-8"))
    machine["downstream_source_contract"]["full_batch_runner"]["sha256"] = "0" * 64
    machine_path.write_text(json.dumps(machine), encoding="utf-8")
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["machine_review_packet_sha256"] = module._sha256(machine_path)
    review_path.write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(ValueError, match="source changed after smoke review"):
        module.validate_review(
            review_path, progress_path=progress_path,
            probe_video=_probe_for(module),
        )


def test_rejects_progress_changed_after_human_review(tmp_path: Path) -> None:
    module, progress_path, review_path, progress, _ = _fixture(tmp_path)
    progress["tampered"] = True
    progress_path.write_text(json.dumps(progress), encoding="utf-8")
    with pytest.raises(ValueError, match="reviewed_progress_sha256"):
        module.validate_review(
            review_path, progress_path=progress_path, probe_video=_probe_for(module)
        )


def test_rejects_review_without_authenticated_frontend_source(tmp_path: Path) -> None:
    module, progress_path, review_path, _, review = _fixture(tmp_path)
    review["decision_source"] = "manual_json_edit"
    review_path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="authenticated frontend"):
        module.validate_review(
            review_path,
            progress_path=progress_path,
            probe_video=_probe_for(module),
        )


def test_rejects_frontend_attestation_candidate_hash_mismatch(tmp_path: Path) -> None:
    module, progress_path, review_path, _, review = _fixture(tmp_path)
    review["frontend_attestation"]["video_sha256s"][0] = "0" * 64
    review_path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="candidate hash binding"):
        module.validate_review(
            review_path,
            progress_path=progress_path,
            probe_video=_probe_for(module),
        )


def test_rejects_single_unapproved_visual_check(tmp_path: Path) -> None:
    module, progress_path, review_path, _, review = _fixture(tmp_path)
    review["shots"][3]["anatomy_and_hands_are_plausible"] = False
    review_path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="anatomy_and_hands_are_plausible"):
        module.validate_review(
            review_path, progress_path=progress_path, probe_video=_probe_for(module)
        )


def test_rejects_candidate_file_changed_after_render(tmp_path: Path) -> None:
    module, progress_path, review_path, _, review = _fixture(tmp_path)
    Path(review["shots"][0]["candidate_path"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="candidate SHA"):
        module.validate_review(
            review_path, progress_path=progress_path, probe_video=_probe_for(module)
        )


def test_rejects_musetalk_artifact_changed_after_packet(tmp_path: Path) -> None:
    module, progress_path, review_path, progress, _ = _fixture(tmp_path)
    musetalk_path = Path(
        progress["shots"][0]["assets"][0]["metadata"]["musetalk_artifact_path"]
    )
    musetalk_path.write_bytes(musetalk_path.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="MuseTalk stage artifact SHA mismatch"):
        module.validate_review(
            review_path,
            progress_path=progress_path,
            probe_video=_probe_for(module),
        )


def test_rejects_open_platform_gate(tmp_path: Path) -> None:
    module, progress_path, review_path, progress, review = _fixture(tmp_path)
    progress["gates"]["publish_allowed"] = True
    progress_path.write_text(json.dumps(progress), encoding="utf-8")
    review["reviewed_progress_sha256"] = module._sha256(progress_path)
    review_path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="publish_allowed must remain false"):
        module.validate_review(
            review_path, progress_path=progress_path, probe_video=_probe_for(module)
        )


def test_validator_api_has_no_human_signature_parameters() -> None:
    module = _module()
    parameters = inspect.signature(module.validate_review).parameters
    assert "verify_signature" not in parameters
    assert "allowed_signers_path" not in parameters


def test_review_certificate_uses_json_hash_without_openssh(
    tmp_path: Path,
) -> None:
    module, progress_path, review_path, _, review = _fixture(tmp_path)
    certificate = module.validate_review(
        review_path,
        progress_path=progress_path,
        probe_video=_probe_for(module),
    )
    assert certificate["accepted"] is True
    assert certificate["reviewer_id"] == review["reviewer_id"]
    assert certificate["approval_source"] == "authenticated_streamlit_frontend"
    assert "signature_path" not in certificate
