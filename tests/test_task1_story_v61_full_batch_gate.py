from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts/run_task1_story_v61_full_batch.py"


def _module():
    spec = importlib.util.spec_from_file_location("v61_full_batch", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pending_review_blocks_before_plan_tts_and_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _module()
    monkeypatch.setattr(
        module.review_gate, "validate_review",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("review pending")),
    )
    monkeypatch.setattr(
        module.smoke, "_load_structured_scene_plan",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("plan must not load")),
    )
    progress = tmp_path / "blocked.json"
    rc = module.main([
        "--review", str(tmp_path / "review.json"),
        "--smoke-progress", str(tmp_path / "smoke.json"),
        "--progress-path", str(progress),
    ])
    report = json.loads(progress.read_text(encoding="utf-8"))
    assert rc == 3
    assert report["result"] == "SMOKE_REVIEW_GATE_REJECTED"
    assert all(not value for key, value in report["gates"].items() if key not in {
        "full_video_human_review_required",
    })
    assert report["gates"]["full_video_human_review_required"] is True


def test_execute_requires_explicit_confirmation(tmp_path: Path) -> None:
    module = _module()
    rc = module.main([
        "--execute", "--confirm-execution", "wrong",
        "--progress-path", str(tmp_path / "must_not_exist.json"),
    ])
    assert rc == 2
    assert not (tmp_path / "must_not_exist.json").exists()


@pytest.mark.parametrize("mode", ["--prepare-audio", "--execute"])
def test_mutating_mode_fails_closed_if_execution_policy_is_forced_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: str,
) -> None:
    module = _module()
    monkeypatch.setattr(module.smoke, "_execution_window", lambda: {
        "open": False,
        "observed_at": "2026-08-13T23:00:00+08:00",
        "not_before": None,
        "remaining_seconds": 0.0,
        "policy": "test_forced_closed",
    })
    progress = tmp_path / "must_not_exist.json"
    args = [mode, "--progress-path", str(progress)]
    if mode == "--execute":
        args.extend([
            "--confirm-execution", module.EXECUTION_CONFIRMATION,
            "--render-signer-id", "renderer@example",
        ])
    assert module.main(args) == 2
    assert not progress.exists()


def test_execute_never_overwrites_existing_shot_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    module = _module()
    monkeypatch.setattr(module.smoke, "_execution_window", lambda: {"open": True})
    progress = tmp_path / "rendered.json"
    original = {"shots": [{"scene_id": "b01"}], "result": "partial"}
    progress.write_text(json.dumps(original), encoding="utf-8")
    rc = module.main([
        "--execute", "--confirm-execution", module.EXECUTION_CONFIRMATION,
        "--progress-path", str(progress),
    ])
    assert rc == 2
    assert json.loads(progress.read_text(encoding="utf-8")) == original


def test_mutating_run_rejects_existing_zero_shot_progress(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    module = _module()
    monkeypatch.setattr(module.smoke, "_execution_window", lambda: {"open": True})
    progress = tmp_path / "reserved.json"
    original = {"shots": [], "result": "FULL_BATCH_PROGRESS_PATH_RESERVED"}
    progress.write_text(json.dumps(original), encoding="utf-8")
    rc = module.main([
        "--prepare-audio", "--progress-path", str(progress),
    ])
    assert rc == 2
    assert json.loads(progress.read_text(encoding="utf-8")) == original


@pytest.mark.parametrize("target", ["progress", "certificate"])
def test_full_batch_outputs_cannot_overwrite_smoke_progress(
    target: str, tmp_path: Path
) -> None:
    module = _module()
    smoke_progress = tmp_path / "smoke.json"
    smoke_progress.write_text("immutable-smoke-evidence", encoding="utf-8")
    args = ["--smoke-progress", str(smoke_progress)]
    args.extend(
        ["--progress-path", str(smoke_progress)]
        if target == "progress"
        else ["--certificate", str(smoke_progress)]
    )
    rc = module.main(args)
    assert rc == 2
    assert smoke_progress.read_text(encoding="utf-8") == "immutable-smoke-evidence"


def test_validate_only_cannot_overwrite_custom_full_render_evidence(
    tmp_path: Path,
) -> None:
    module = _module()
    protected = tmp_path / "custom-full-render.json"
    original = {
        "result": module.EXPECTED_RESULT,
        "shots": [{"scene_id": "b01"}],
    }
    protected.write_text(json.dumps(original), encoding="utf-8")
    assert module.main(["--progress-path", str(protected)]) == 2
    assert json.loads(protected.read_text(encoding="utf-8")) == original


def test_validate_only_cannot_overwrite_zero_shot_reservation(tmp_path: Path) -> None:
    module = _module()
    protected = tmp_path / "reserved.json"
    original = {
        "schema_version": "fanqie_v61_full_batch_progress/v2",
        "result": "FULL_BATCH_PROGRESS_PATH_RESERVED",
        "shots": [],
    }
    protected.write_text(json.dumps(original), encoding="utf-8")
    assert module.main(["--progress-path", str(protected)]) == 2
    assert json.loads(protected.read_text(encoding="utf-8")) == original


def test_failed_receipt_reservation_removes_empty_run_directories(tmp_path: Path) -> None:
    module = _module()
    args = SimpleNamespace(
        output_dir=tmp_path / "video-cleanup-001",
        audio_dir=tmp_path / "audio-cleanup-001",
        evidence_root=tmp_path / "evidence-cleanup-001",
    )
    module._reserve_run_directories(args)
    assert all(path.is_dir() for path in (args.output_dir, args.audio_dir, args.evidence_root))
    module._cleanup_empty_run_directories(args)
    assert all(not path.exists() for path in (args.output_dir, args.audio_dir, args.evidence_root))


def test_approved_gate_validate_only_never_runs_audio_or_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _module()
    certificate = {
        "accepted": True,
        "gates": {"full_19_shot_generation_allowed": True},
        "candidates": [{
            "scene_id": f"b{i:02d}", "path": str(tmp_path / f"b{i:02d}.mp4"),
            "duration_seconds": 2.0, "provider_name": "test", "metadata": {},
        } for i in range(7)],
    }
    monkeypatch.setattr(module.review_gate, "validate_review", lambda *a, **k: certificate)
    monkeypatch.setattr(module.smoke, "_sha256", lambda path: "A" * 64)
    plans = [SimpleNamespace(scene_id=f"b{i:02d}", estimated_duration_s=2.0, metadata={}) for i in range(19)]
    monkeypatch.setattr(module.smoke, "_load_structured_scene_plan", lambda *a, **k: plans)
    monkeypatch.setattr(module.smoke, "_validate_static", lambda **k: {"ok": True})
    monkeypatch.setattr(
        module.smoke, "_synthesize_performance_audio",
        lambda **k: (_ for _ in ()).throw(AssertionError("TTS must not run")),
    )
    monkeypatch.setattr(
        module.smoke, "_provider",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("provider must not run")),
    )
    progress = tmp_path / "validated.json"
    rc = module.main([
        "--review", str(tmp_path / "review.json"),
        "--smoke-progress", str(tmp_path / "smoke.json"),
        "--certificate", str(tmp_path / "certificate.json"),
        "--progress-path", str(progress),
    ])
    report = json.loads(progress.read_text(encoding="utf-8"))
    assert rc == 0
    assert report["result"] == "FULL_BATCH_GATE_VALIDATION_PASSED"
    assert report["gates"]["smoke_human_review_passed"] is True
    assert report["gates"]["publish_allowed"] is False
    assert report["gates"]["fanqie_backfill_allowed"] is False
    assert report["render_attestation_receipt_path"] == ""
    assert report["render_attestation_completed"] is False


def test_execute_only_after_gate_and_keeps_publish_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _module()
    monkeypatch.setattr(module.smoke, "_execution_window", lambda: {"open": True})
    reviewed_ids = [f"beat_{i:02d}" for i in range(7)]
    for scene_id in reviewed_ids:
        (tmp_path / f"{scene_id}.mp4").write_bytes(b"frontend-reviewed-smoke")
    reused_sha = (
        __import__("hashlib").sha256(b"frontend-reviewed-smoke").hexdigest().upper()
    )
    monkeypatch.setattr(module.review_gate, "validate_review", lambda *a, **k: {
        "accepted": True,
        "candidates": [{
            "scene_id": scene_id,
            "path": str(tmp_path / f"{scene_id}.mp4"),
            "duration_seconds": 2.0,
            "sha256": reused_sha,
            "provider_name": "test",
            "metadata": {"final_sha256": "C" * 64},
        } for scene_id in reviewed_ids],
    })
    original_sha = module.smoke._sha256
    monkeypatch.setattr(
        module.smoke, "_sha256",
        lambda path: "B" * 64 if Path(path).name == "certificate.json" else original_sha(path),
    )
    plans = [SimpleNamespace(scene_id=f"beat_{i:02d}", estimated_duration_s=2.0, metadata={}) for i in range(19)]
    monkeypatch.setattr(module.smoke, "_load_structured_scene_plan", lambda *a, **k: plans)
    monkeypatch.setattr(module.smoke, "_validate_static", lambda **k: {"ok": True})
    monkeypatch.setattr(module.smoke, "_emotion_config", lambda: object())
    monkeypatch.setattr(
        module.smoke, "_synthesize_performance_audio",
        lambda **k: {"success": True, "error": ""},
    )
    rendered: list[str] = []

    class Provider:
        def preflight(self, plans):
            return SimpleNamespace(ok=True, status="ok")

        def provide_scenes(self, plans, output_dir):
            rendered.append(plans[0].scene_id)
            return SimpleNamespace(
                assets=[SimpleNamespace(scene_id=plans[0].scene_id)], missing=[]
            )

    monkeypatch.setattr(module.smoke, "_provider", lambda *a, **k: Provider())
    progress = tmp_path / "rendered.json"
    rc = module.main([
        "--execute", "--confirm-execution", module.EXECUTION_CONFIRMATION,
        "--render-signer-id", "renderer@example",
        "--run-id", "full-run-001",
        "--review", str(tmp_path / "review.json"),
        "--smoke-progress", str(tmp_path / "smoke.json"),
        "--certificate", str(tmp_path / "certificate-full-run-001.json"),
        "--progress-path", str(tmp_path / "rendered-full-run-001.json"),
        "--output-dir", str(tmp_path / "video-full-run-001"),
        "--audio-dir", str(tmp_path / "audio-full-run-001"),
        "--evidence-root", str(tmp_path / "evidence-full-run-001"),
    ])
    progress = tmp_path / "rendered-full-run-001.json"
    report = json.loads(progress.read_text(encoding="utf-8"))
    assert rc == 0
    assert rendered == [plan.scene_id for plan in plans[7:]]
    assert report["reviewed_smoke_shots_reused"] == reviewed_ids
    assert report["shots_to_generate"] == [plan.scene_id for plan in plans[7:]]
    assert len(report["shots"]) == 19
    assert all(
        item["source"] == "frontend_human_approved_smoke_candidate"
        for item in report["shots"][:7]
    )
    assert all(item["source"] == "new_full_batch_render" for item in report["shots"][7:])
    assert report["gates"]["full_19_shots_rendered"] is True
    assert report["gates"]["full_video_human_approval_obtained"] is False
    assert report["gates"]["matching_fanqie_task_confirmed"] is False
    assert report["gates"]["publish_allowed"] is False
    assert report["gates"]["fanqie_backfill_allowed"] is False
    assert report["render_signer_id"] == "renderer@example"
    assert report["render_attestation_required"] is True
    assert report["render_attestation_completed"] is True
    receipt_path = Path(report["render_attestation_receipt_path"])
    assert report["render_attestation_namespace"] == module.RENDER_ATTESTATION_NAMESPACE
    assert receipt_path.is_file()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["schema_version"] == module.RENDER_ATTESTATION_RECEIPT_SCHEMA
    assert receipt["receipt_path"] == str(receipt_path.resolve())
    assert receipt["progress_path"] == str(progress.resolve())
    assert receipt["progress_sha256"] == module.smoke._sha256(progress)
    assert receipt["renderer_id"] == "renderer@example"
    assert receipt["plan_sha256"] == module.smoke.EXPECTED_PLAN_SHA256
    assert receipt["shot_count"] == 19


def test_mutating_review_failure_creates_no_run_artifacts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    module = _module()
    monkeypatch.setattr(module.smoke, "_execution_window", lambda: {"open": True})
    monkeypatch.setattr(
        module.review_gate, "validate_review",
        lambda *a, **k: (_ for _ in ()).throw(ValueError("frontend review rejected")),
    )
    run_id = "review-fail-001"
    paths = {
        "progress": tmp_path / f"progress-{run_id}.json",
        "certificate": tmp_path / f"certificate-{run_id}.json",
        "output": tmp_path / f"video-{run_id}",
        "audio": tmp_path / f"audio-{run_id}",
        "evidence": tmp_path / f"evidence-{run_id}",
    }
    rc = module.main([
        "--prepare-audio", "--run-id", run_id,
        "--progress-path", str(paths["progress"]),
        "--certificate", str(paths["certificate"]),
        "--output-dir", str(paths["output"]),
        "--audio-dir", str(paths["audio"]),
        "--evidence-root", str(paths["evidence"]),
    ])
    assert rc == 3
    assert all(not path.exists() for path in paths.values())


def test_execute_failure_creates_no_render_receipt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    module = _module()
    monkeypatch.setattr(module.smoke, "_execution_window", lambda: {"open": True})
    monkeypatch.setattr(
        module.review_gate,
        "validate_review",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ValueError("frontend review rejected")
        ),
    )
    run_id = "execute-fail-001"
    progress = tmp_path / f"progress-{run_id}.json"
    receipt = module._render_attestation_receipt_path(progress)
    rc = module.main([
        "--execute", "--confirm-execution", module.EXECUTION_CONFIRMATION,
        "--render-signer-id", "renderer@example",
        "--run-id", run_id,
        "--progress-path", str(progress),
        "--certificate", str(tmp_path / f"certificate-{run_id}.json"),
        "--output-dir", str(tmp_path / f"video-{run_id}"),
        "--audio-dir", str(tmp_path / f"audio-{run_id}"),
        "--evidence-root", str(tmp_path / f"evidence-{run_id}"),
    ])
    assert rc == 3
    assert not progress.exists()
    assert not receipt.exists()


def test_mutating_paths_must_all_be_bound_to_same_run_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    module = _module()
    monkeypatch.setattr(module.smoke, "_execution_window", lambda: {"open": True})
    run_id = "path-bound-001"
    progress = tmp_path / f"progress-{run_id}.json"
    rc = module.main([
        "--prepare-audio", "--run-id", run_id,
        "--progress-path", str(progress),
        "--certificate", str(tmp_path / f"certificate-{run_id}.json"),
        "--output-dir", str(tmp_path / "video-wrong-run"),
        "--audio-dir", str(tmp_path / f"audio-{run_id}"),
        "--evidence-root", str(tmp_path / f"evidence-{run_id}"),
    ])
    assert rc == 2
    assert not progress.exists()


def test_render_receipt_write_is_exclusive(tmp_path: Path) -> None:
    module = _module()
    receipt = tmp_path / "progress-run-001.json.render_attestation.json"
    module._write_json_new(receipt, {"first": True})
    with pytest.raises(ValueError, match="Refusing to overwrite immutable receipt"):
        module._write_json_new(receipt, {"first": False})
    assert json.loads(receipt.read_text(encoding="utf-8")) == {"first": True}


def test_existing_render_receipt_blocks_execute_before_review_or_tts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    module = _module()
    monkeypatch.setattr(module.smoke, "_execution_window", lambda: {"open": True})
    monkeypatch.setattr(
        module.review_gate,
        "validate_review",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("review must not run after receipt collision")
        ),
    )
    run_id = "receipt-collision-001"
    progress = tmp_path / f"progress-{run_id}.json"
    receipt = module._render_attestation_receipt_path(progress)
    receipt.write_text("existing-receipt", encoding="utf-8")
    rc = module.main([
        "--execute", "--confirm-execution", module.EXECUTION_CONFIRMATION,
        "--render-signer-id", "renderer@example",
        "--run-id", run_id,
        "--progress-path", str(progress),
        "--certificate", str(tmp_path / f"certificate-{run_id}.json"),
        "--output-dir", str(tmp_path / f"video-{run_id}"),
        "--audio-dir", str(tmp_path / f"audio-{run_id}"),
        "--evidence-root", str(tmp_path / f"evidence-{run_id}"),
    ])
    assert rc == 2
    assert not progress.exists()
    assert receipt.read_text(encoding="utf-8") == "existing-receipt"


def test_invalid_renderer_identity_blocks_before_review_or_tts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    module = _module()
    monkeypatch.setattr(module.smoke, "_execution_window", lambda: {"open": True})
    monkeypatch.setattr(
        module.review_gate,
        "validate_review",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("review must not run with invalid renderer identity")
        ),
    )
    run_id = "invalid-renderer-001"
    progress = tmp_path / f"progress-{run_id}.json"
    rc = module.main([
        "--execute", "--confirm-execution", module.EXECUTION_CONFIRMATION,
        "--render-signer-id", "x",
        "--run-id", run_id,
        "--progress-path", str(progress),
        "--certificate", str(tmp_path / f"certificate-{run_id}.json"),
        "--output-dir", str(tmp_path / f"video-{run_id}"),
        "--audio-dir", str(tmp_path / f"audio-{run_id}"),
        "--evidence-root", str(tmp_path / f"evidence-{run_id}"),
    ])
    assert rc == 2
    assert not progress.exists()
    assert not module._render_attestation_receipt_path(progress).exists()
