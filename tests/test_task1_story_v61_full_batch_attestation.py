from __future__ import annotations

import importlib.util
import inspect
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts/validate_task1_story_v61_full_batch_attestation.py"


def _module():
    spec = importlib.util.spec_from_file_location("v61_batch_attestation", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture(tmp_path: Path):
    module = _module()
    plan = tmp_path / "plan.json"
    plan.write_text("reviewed-plan", encoding="utf-8")
    plans = []
    shots = []
    reviewed_ids = {
        "beat_00", "beat_02", "beat_03", "beat_04",
        "beat_05", "beat_06", "beat_07",
    }
    module.smoke.FAILED_SHOT_IDS = tuple(reviewed_ids)
    for index in range(19):
        scene_id = f"beat_{index:02d}"
        plans.append(SimpleNamespace(scene_id=scene_id))
        video = tmp_path / f"{scene_id}.mp4"
        video.write_bytes(f"{scene_id}-video".encode())
        audio = tmp_path / f"{scene_id}.wav"
        audio.write_bytes(f"{scene_id}-audio".encode())
        shots.append({
            "position": index + 1, "scene_id": scene_id,
            "source": (
                "frontend_human_approved_smoke_candidate" if scene_id in reviewed_ids
                else "new_full_batch_render"
            ),
            "missing": [],
            "assets": [{
                "scene_id": scene_id, "video_path": str(video),
                "metadata": {
                    "final_sha256": module._sha256(video),
                    "dialogue_audio_path": str(audio),
                    "dialogue_audio_sha256": module._sha256(audio),
                },
            }],
        })
    progress_path = tmp_path / "progress.json"
    receipt_path = module.full_batch._render_attestation_receipt_path(progress_path)
    now = datetime.now(timezone.utc)
    progress = {
        "schema_version": "fanqie_v61_full_batch_progress/v2",
        "task_id": 1, "scope": "full_19_beat_render",
        "result": module.full_batch.EXPECTED_RESULT,
        "plan_path": str(plan),
        "render_signer_id": "renderer@example",
        "render_attestation_receipt_path": str(receipt_path),
        "render_attestation_namespace": module.full_batch.RENDER_ATTESTATION_NAMESPACE,
        "render_attestation_required": True,
        "render_attestation_completed": True,
        "finished_at": (now - timedelta(seconds=1)).isoformat(),
        "forbidden_side_effects": {
            "database_writes": 0,
            "browser_operations": 0,
            "douyin_uploads": 0,
            "fanqie_backfills": 0,
        },
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
    progress_path.write_text(json.dumps(progress), encoding="utf-8")
    receipt = {
        "schema_version": module.RECEIPT_SCHEMA,
        "created_at": now.isoformat(),
        "task_id": 1,
        "scope": "full_19_beat_render",
        "result": module.full_batch.EXPECTED_RESULT,
        "receipt_path": str(receipt_path.resolve()),
        "progress_path": str(progress_path.resolve()),
        "progress_sha256": module._sha256(progress_path),
        "renderer_id": "renderer@example",
        "plan_path": str(plan.resolve()),
        "plan_sha256": module.smoke.EXPECTED_PLAN_SHA256,
        "shot_count": 19,
    }
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    original_sha = module._sha256
    module._sha256 = lambda path: (
        module.smoke.EXPECTED_PLAN_SHA256 if Path(path) == plan else original_sha(Path(path))
    )
    module.smoke._load_structured_scene_plan = lambda *args, **kwargs: plans
    return module, progress_path, progress


def _refresh_receipt(module, progress_path: Path) -> None:
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    receipt_path = Path(progress["render_attestation_receipt_path"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["progress_sha256"] = module._sha256(progress_path)
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")


def test_accepts_machine_render_provenance_but_keeps_later_gates_closed(tmp_path: Path) -> None:
    module, progress_path, _ = _fixture(tmp_path)
    certificate = module.validate_attestation(progress_path)
    assert certificate["accepted"] is True
    assert certificate["shot_count"] == 19
    assert certificate["gates"]["render_provenance_attested"] is True
    assert certificate["gates"]["full_video_human_review_passed"] is False
    assert certificate["gates"]["douyin_upload_allowed"] is False
    assert certificate["gates"]["fanqie_backfill_allowed"] is False
    receipt_path = Path(certificate["attestation_receipt_path"])
    assert receipt_path.is_file()
    assert certificate["attestation_receipt_schema"] == module.RECEIPT_SCHEMA
    assert certificate["attestation_receipt_sha256"] == module._sha256(receipt_path)
    assert certificate["attestation_namespace"] == module.full_batch.RENDER_ATTESTATION_NAMESPACE


def test_rejects_wrong_new_shot_source(tmp_path: Path) -> None:
    module, progress_path, progress = _fixture(tmp_path)
    progress["shots"][8]["source"] = "frontend_human_approved_smoke_candidate"
    progress_path.write_text(json.dumps(progress), encoding="utf-8")
    _refresh_receipt(module, progress_path)
    with pytest.raises(ValueError, match="render source mismatch"):
        module.validate_attestation(progress_path)


def test_rejects_changed_video_after_progress_hash_record(tmp_path: Path) -> None:
    module, progress_path, progress = _fixture(tmp_path)
    Path(progress["shots"][10]["assets"][0]["video_path"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="video SHA mismatch"):
        module.validate_attestation(progress_path)


def test_machine_attestation_does_not_require_openssh(tmp_path: Path) -> None:
    module, progress_path, progress = _fixture(tmp_path)
    certificate = module.validate_attestation(progress_path)
    assert certificate["accepted"] is True
    assert certificate["attestation_receipt_path"] == progress["render_attestation_receipt_path"]
    assert certificate["attestation_namespace"] == module.full_batch.RENDER_ATTESTATION_NAMESPACE


def test_attestation_api_has_no_signature_callback() -> None:
    module = _module()
    parameters = inspect.signature(module.validate_attestation).parameters
    assert "verify_signature" not in parameters


def test_rejects_missing_render_receipt(tmp_path: Path) -> None:
    module, progress_path, progress = _fixture(tmp_path)
    Path(progress["render_attestation_receipt_path"]).unlink()
    with pytest.raises(ValueError, match="JSON file not found"):
        module.validate_attestation(progress_path)


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("schema_version", "wrong/v1", "receipt schema mismatch"),
        ("renderer_id", "other@example", "receipt renderer mismatch"),
        ("plan_sha256", "0" * 64, "receipt plan SHA mismatch"),
        ("shot_count", 18, "receipt shot_count mismatch"),
    ],
)
def test_rejects_tampered_render_receipt_fields(
    tmp_path: Path, field: str, value, error: str,
) -> None:
    module, progress_path, progress = _fixture(tmp_path)
    receipt_path = Path(progress["render_attestation_receipt_path"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt[field] = value
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ValueError, match=error):
        module.validate_attestation(progress_path)


def test_rejects_progress_changed_after_receipt(tmp_path: Path) -> None:
    module, progress_path, _ = _fixture(tmp_path)
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    progress["tampered"] = True
    progress_path.write_text(json.dumps(progress), encoding="utf-8")
    with pytest.raises(ValueError, match="receipt progress SHA mismatch"):
        module.validate_attestation(progress_path)


@pytest.mark.parametrize("mutation", ["missing", "extra", "nonzero"])
def test_rejects_invalid_forbidden_side_effect_boundary(
    tmp_path: Path, mutation: str,
) -> None:
    module, progress_path, progress = _fixture(tmp_path)
    if mutation == "missing":
        progress["forbidden_side_effects"].pop("douyin_uploads")
    elif mutation == "extra":
        progress["forbidden_side_effects"]["tts_calls"] = 0
    else:
        progress["forbidden_side_effects"]["browser_operations"] = 1
    progress_path.write_text(json.dumps(progress), encoding="utf-8")
    _refresh_receipt(module, progress_path)
    with pytest.raises(ValueError, match="side effects must remain zero"):
        module.validate_attestation(progress_path)


def test_rejects_non_deterministic_receipt_path(tmp_path: Path) -> None:
    module, progress_path, progress = _fixture(tmp_path)
    original_receipt = Path(progress["render_attestation_receipt_path"])
    alternate = tmp_path / "alternate_receipt.json"
    receipt = json.loads(original_receipt.read_text(encoding="utf-8"))
    progress["render_attestation_receipt_path"] = str(alternate)
    progress_path.write_text(json.dumps(progress), encoding="utf-8")
    receipt["receipt_path"] = str(alternate.resolve())
    receipt["progress_sha256"] = module._sha256(progress_path)
    alternate.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ValueError, match="path is not deterministic"):
        module.validate_attestation(progress_path)


@pytest.mark.parametrize("target", ["progress", "receipt"])
def test_cli_cannot_overwrite_source_evidence(
    target: str, tmp_path: Path,
) -> None:
    module, progress_path, progress = _fixture(tmp_path)
    receipt_path = Path(progress["render_attestation_receipt_path"])
    output = progress_path if target == "progress" else receipt_path
    original = output.read_bytes()
    assert module.main(["--progress", str(progress_path), "--output", str(output)]) == 2
    assert output.read_bytes() == original
