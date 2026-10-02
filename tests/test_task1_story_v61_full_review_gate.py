from __future__ import annotations

import importlib.util
import inspect
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image
import pytest


ROOT = Path(__file__).parents[1]
PREPARE = ROOT / "scripts/prepare_task1_story_v61_full_review_packet.py"
VALIDATE = ROOT / "scripts/validate_task1_story_v61_full_review.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prepare_fixture(tmp_path: Path):
    module = _load("v61_full_packet", PREPARE)
    root = tmp_path / "candidate"
    root.mkdir()
    video = root / "candidate.mp4"
    video.write_bytes(b"whole-video")
    manifest = root / "story_manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    subtitle = root / "candidate.srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nline", encoding="utf-8")
    progress = root / "full_batch_progress.json"
    progress.write_text("render-progress", encoding="utf-8")
    receipt = root / "full_batch_progress.json.render_attestation.json"
    receipt.write_text(json.dumps({
        "schema_version": "fanqie_v61_render_attestation_receipt/v1",
        "progress_path": str(progress.resolve()),
        "renderer_id": "renderer@example",
    }), encoding="utf-8")
    receipt_sha = module._sha256(receipt)
    audit = {
        "schema_version": module.AUDIT_SCHEMA,
        "task_id": 1, "scope": "full_19_beat_candidate",
        "plan_sha256": module.EXPECTED_PLAN_SHA256,
        "shot_count": 19, "machine_composition_gate_passed": True,
        "human_full_video_review_completed": False,
        "matching_fanqie_task_confirmed": False,
        "douyin_upload_allowed": False, "fanqie_backfill_allowed": False,
        "candidate_path": str(video), "candidate_sha256": module._sha256(video),
        "story_manifest_path": str(manifest), "story_manifest_sha256": module._sha256(manifest),
        "subtitle_path": str(subtitle), "subtitle_sha256": module._sha256(subtitle),
        "source_progress_path": str(progress),
        "source_progress_sha256": module._sha256(progress),
        "render_attestation_signer_id": "renderer@example",
        "render_attestation_receipt_schema": "fanqie_v61_render_attestation_receipt/v1",
        "render_attestation_receipt_path": str(receipt.resolve()),
        "render_attestation_receipt_sha256": receipt_sha,
        "smoke_review_path": str(tmp_path / "smoke_review.json"),
        "smoke_review_sha256": "A" * 64,
        "smoke_progress_path": str(tmp_path / "smoke_progress.json"),
        "smoke_progress_sha256": "B" * 64,
        "smoke_review_candidates": [
            {"scene_id": f"beat_{index:02d}", "path": str(tmp_path / f"beat_{index:02d}.mp4"), "sha256": "D" * 64}
            for index in range(7)
        ],
        "shots": [
            {
                "scene_id": f"beat_{index:02d}",
                "source": "frontend_human_approved_smoke_candidate" if index < 7 else "new_full_batch_render",
                "video_path": str(tmp_path / f"beat_{index:02d}.mp4"),
                "video_sha256": "D" * 64 if index < 7 else "E" * 64,
            }
            for index in range(19)
        ],
    }
    (root / "candidate_audit.json").write_text(json.dumps(audit), encoding="utf-8")
    return module, root, video


def _probe(path: Path):
    return {
        "duration_seconds": 40.8, "fps": 50.0, "width": 1080,
        "height": 1920, "audio_present": True,
        "audio_sample_rate": 48000, "audio_channels": 2,
    }


def _extract(video: Path, output: Path, timestamp: float) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    color = int(timestamp * 10) % 255
    Image.new("RGB", (64, 96), (color, 40, 100)).save(output)


def _contact(items, output: Path) -> None:
    assert len(items) == 11
    output.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (320, 568), (20, 20, 20)).save(output)


def test_prepares_pending_frontend_review_and_keeps_platform_closed(tmp_path: Path) -> None:
    module, candidate_root, _ = _prepare_fixture(tmp_path)
    output = tmp_path / "packet"
    review = tmp_path / "review.json"
    result = module.prepare_packet(
        candidate_root=candidate_root, output_root=output, review_path=review,
        probe_video=_probe, extract_frame=_extract, build_contact=_contact,
    )
    packet = json.loads(Path(result["packet_path"]).read_text(encoding="utf-8"))
    draft = json.loads(review.read_text(encoding="utf-8"))
    assert packet["machine_gate_passed"] is True
    assert packet["human_full_video_review_completed"] is False
    assert packet["douyin_upload_allowed"] is False
    assert packet["fanqie_backfill_allowed"] is False
    assert len(packet["frames"]) == 11
    assert draft["review_status"] == "pending_review"
    assert "signature_path" not in draft
    assert draft["decision"] == "pending"
    assert all(value is None for value in draft["checks"].values())


def test_packet_rejects_candidate_changed_during_frames(tmp_path: Path) -> None:
    module, candidate_root, video = _prepare_fixture(tmp_path)
    changed = False

    def mutate(candidate: Path, output: Path, timestamp: float) -> None:
        nonlocal changed
        _extract(candidate, output, timestamp)
        if not changed:
            video.write_bytes(video.read_bytes() + b"tampered")
            changed = True

    with pytest.raises(ValueError, match="changed during frame extraction"):
        module.prepare_packet(
            candidate_root=candidate_root, output_root=tmp_path / "packet",
            review_path=tmp_path / "review.json", probe_video=_probe,
            extract_frame=mutate, build_contact=_contact,
        )


def _validated_fixture(tmp_path: Path):
    prep, candidate_root, _ = _prepare_fixture(tmp_path)
    packet_root = tmp_path / "packet"
    review_path = tmp_path / "review.json"
    prep.prepare_packet(
        candidate_root=candidate_root, output_root=packet_root, review_path=review_path,
        probe_video=_probe, extract_frame=_extract, build_contact=_contact,
    )
    validator = _load("v61_full_validator", VALIDATE)
    machine_path = packet_root / "machine_review_packet.json"
    machine = json.loads(machine_path.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    machine["created_at"] = (now - timedelta(minutes=2)).isoformat()
    machine_path.write_text(json.dumps(machine), encoding="utf-8")
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["review_status"] = "approved"
    review["decision"] = "approved"
    review["decision_source"] = "authenticated_streamlit_frontend"
    review["reviewer"] = "human-reviewer"
    review["reviewer_id"] = "reviewer@example"
    review["reviewed_at"] = now.isoformat()
    review["playback_started_at"] = (now - timedelta(seconds=55)).isoformat()
    review["playback_finished_at"] = (now - timedelta(seconds=5)).isoformat()
    review["machine_review_packet_sha256"] = validator._sha256(machine_path)
    review["checks"] = {key: True for key in validator.packet_module.GLOBAL_CHECKS}
    confirmation_keys = {
        f"check:{key}" for key in validator.packet_module.GLOBAL_CHECKS
    }
    review["frontend_attestation"] = {
        "confirmations": {key: True for key in confirmation_keys},
        "required_checks": sorted(confirmation_keys),
        "all_required_checks_confirmed": True,
        "video_sha256s": [review["candidate_sha256"]],
        "machine_packet_sha256": review["machine_review_packet_sha256"],
        "required_playback_seconds": 40.8,
        "actual_playback_seconds": 50.0,
    }
    review_path.write_text(json.dumps(review), encoding="utf-8")
    return validator, review_path, review


def _render_attestation(validator, review):
    machine = json.loads(
        Path(review["machine_review_packet_path"]).read_text(encoding="utf-8")
    )
    audit = json.loads(
        Path(machine["candidate_audit_path"]).read_text(encoding="utf-8")
    )
    receipt_path = Path(audit["render_attestation_receipt_path"])
    return lambda *args, **kwargs: {
        "accepted": True,
        "signer_id": "renderer@example",
        "progress_sha256": audit["source_progress_sha256"],
        "attestation_receipt_schema": validator.render_attestation_gate.RECEIPT_SCHEMA,
        "attestation_receipt_path": str(receipt_path.resolve()),
        "attestation_receipt_sha256": audit["render_attestation_receipt_sha256"],
    }


def _validate(validator, review_path: Path, review: dict, **kwargs):
    machine = json.loads(Path(review["machine_review_packet_path"]).read_text(encoding="utf-8"))
    audit = json.loads(Path(machine["candidate_audit_path"]).read_text(encoding="utf-8"))
    smoke_certificate = {
        "schema_version": "fanqie_v61_smoke_review_certificate/v2",
        "approval_source": "authenticated_streamlit_frontend",
        "review_path": audit["smoke_review_path"],
        "review_sha256": audit["smoke_review_sha256"],
        "progress_path": audit["smoke_progress_path"],
        "progress_sha256": audit["smoke_progress_sha256"],
        "candidates": audit["smoke_review_candidates"],
    }
    return validator.validate_review(
        review_path,
        probe_video=_probe,
        extract_frame=_extract,
        build_contact=_contact,
        validate_render_attestation=kwargs.pop(
            "validate_render_attestation", _render_attestation(validator, review)
        ),
        validate_smoke_review=kwargs.pop("validate_smoke_review", lambda *a, **k: smoke_certificate),
        **kwargs,
    )


def test_frontend_full_review_still_requires_matching_fanqie_task(tmp_path: Path) -> None:
    validator, review_path, review = _validated_fixture(tmp_path)
    certificate = _validate(validator, review_path, review)
    assert certificate["accepted"] is True
    assert certificate["schema_version"] == "fanqie_v61_full_review_certificate/v2"
    assert certificate["approval_source"] == "authenticated_streamlit_frontend"
    assert certificate["gates"]["full_video_human_review_passed"] is True
    assert certificate["gates"]["matching_fanqie_task_required"] is True
    assert certificate["gates"]["matching_fanqie_task_confirmed"] is False
    assert certificate["gates"]["douyin_upload_allowed"] is False
    assert certificate["gates"]["fanqie_backfill_allowed"] is False


def test_full_review_rejects_non_frontend_decision_source(tmp_path: Path) -> None:
    validator, review_path, review = _validated_fixture(tmp_path)
    review["decision_source"] = "manual_json_edit"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(ValueError, match="authenticated frontend"):
        _validate(validator, review_path, review)


def test_full_review_rejects_incomplete_frontend_attestation(tmp_path: Path) -> None:
    validator, review_path, review = _validated_fixture(tmp_path)
    key = next(iter(review["frontend_attestation"]["confirmations"]))
    review["frontend_attestation"]["confirmations"].pop(key)
    review_path.write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(ValueError, match="confirmation boundary"):
        _validate(validator, review_path, review)


def test_full_review_rejects_render_receipt_binding_mismatch(tmp_path: Path) -> None:
    validator, review_path, review = _validated_fixture(tmp_path)
    attestation = _render_attestation(validator, review)()
    attestation["attestation_receipt_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="render receipt binding mismatch"):
        _validate(
            validator,
            review_path,
            review,
            validate_render_attestation=lambda *args, **kwargs: attestation,
        )


def test_validator_rejects_one_unapproved_whole_video_check(tmp_path: Path) -> None:
    validator, review_path, review = _validated_fixture(tmp_path)
    review["checks"]["pace_is_tight_without_slow_motion_or_long_holds"] = False
    review_path.write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(ValueError, match="pace_is_tight"):
        _validate(validator, review_path, review)


def test_validator_rejects_candidate_tampering(tmp_path: Path) -> None:
    validator, review_path, review = _validated_fixture(tmp_path)
    Path(review["candidate_path"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="candidate SHA mismatch"):
        _validate(validator, review_path, review)


def test_validator_rejects_subtitle_tampering(tmp_path: Path) -> None:
    validator, review_path, review = _validated_fixture(tmp_path)
    packet = json.loads(
        Path(review["machine_review_packet_path"]).read_text(encoding="utf-8")
    )
    Path(packet["subtitle_path"]).write_text("changed subtitle", encoding="utf-8")
    with pytest.raises(ValueError, match="subtitle SHA mismatch"):
        _validate(validator, review_path, review)


def test_validator_api_has_no_human_signature_parameters() -> None:
    validator = _load("v61_full_validator", VALIDATE)
    parameters = inspect.signature(validator.validate_review).parameters
    assert "verify_signature" not in parameters
    assert "allowed_signers_path" not in parameters


def test_validator_rejects_incomplete_playback_interval(tmp_path: Path) -> None:
    validator, review_path, review = _validated_fixture(tmp_path)
    reviewed_at = datetime.fromisoformat(review["reviewed_at"])
    review["playback_started_at"] = (reviewed_at - timedelta(seconds=20)).isoformat()
    review_path.write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(ValueError, match="complete candidate duration"):
        _validate(validator, review_path, review)


def test_frontend_reviewer_must_differ_from_renderer_identity(tmp_path: Path) -> None:
    validator, review_path, review = _validated_fixture(tmp_path)
    review["reviewer_id"] = "renderer@example"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    with pytest.raises(ValueError, match="must be different identities"):
        _validate(validator, review_path, review)


def test_final_review_independently_revalidates_frontend_smoke_review(
    tmp_path: Path,
) -> None:
    validator, review_path, review = _validated_fixture(tmp_path)
    calls: list[tuple[Path, Path]] = []

    def reject(review_file, *, progress_path, **kwargs):
        calls.append((Path(review_file), Path(progress_path)))
        raise ValueError("original seven-shot frontend review rejected")

    with pytest.raises(ValueError, match="seven-shot frontend review rejected"):
        _validate(
            validator, review_path, review,
            validate_smoke_review=reject,
        )
    assert len(calls) == 1


def test_final_review_has_no_signature_tool_dependency(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    validator, review_path, review = _validated_fixture(tmp_path)
    certificate = _validate(validator, review_path, review)
    assert certificate["accepted"] is True
    assert certificate["must_revalidate_frontend_review"] is True
    assert "signature_path" not in certificate
