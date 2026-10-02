from __future__ import annotations

import importlib.util
import inspect
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts/prepare_task1_story_v61_window_packet.py"


def _module():
    spec = importlib.util.spec_from_file_location("v61_window_packet", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stub(monkeypatch, module, tmp_path: Path, *, window_open: bool):
    monkeypatch.setattr(module.smoke, "_execution_window", lambda now=None: {
        "open": window_open, "observed_at": "now", "not_before": "boundary",
        "remaining_seconds": 0 if window_open else 10,
    })
    plans = [SimpleNamespace(scene_id=scene_id) for scene_id in module.smoke.FAILED_SHOT_IDS]
    monkeypatch.setattr(module.smoke, "_load_structured_scene_plan", lambda *a, **k: plans)
    monkeypatch.setattr(module.smoke, "_select_plans", lambda *a, **k: plans)
    monkeypatch.setattr(module.smoke, "_validate_static", lambda **k: {"ok": True})
    monkeypatch.setattr(module.smoke, "_provider", lambda *a, **k: SimpleNamespace(
        preflight=lambda *a, **k: {"ok": True, "status": "ok"},
    ))
    monkeypatch.setattr(module.shutil, "disk_usage", lambda path: SimpleNamespace(
        free=200 * 1024 ** 3,
    ))
    monkeypatch.setattr(module, "_gpu_readiness", lambda: {
        "ready": True,
        "error": "",
        "minimum_free_mib": module.MINIMUM_GPU_FREE_MIB,
        "maximum_utilization_percent": module.MAXIMUM_GPU_UTILIZATION_PERCENT,
        "devices": [{"index": 0, "memory_free_mib": 12000, "utilization_percent": 5}],
    })
    paths = {key: tmp_path / value.name for key, value in module._paths("20260818_204001").items()}
    monkeypatch.setattr(module, "_paths", lambda run_id: paths)


def test_closed_window_never_emits_executable_command(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    _stub(monkeypatch, module, tmp_path, window_open=False)
    packet = module.prepare(
        run_id="20260818_204001",
        now=datetime(2026, 8, 18, 12, 39, tzinfo=timezone.utc),
    )
    assert packet["smoke_execution_allowed"] is False
    assert packet["commands"]["render_seven_shot_smoke"] == ""
    assert "execution_window_open" in packet["blockers"]
    assert all(value == 0 for value in packet["forbidden_side_effects"].values())


def test_frontend_review_is_not_a_render_prerequisite(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    _stub(monkeypatch, module, tmp_path, window_open=True)
    packet = module.prepare(run_id="20260818_204001")
    assert packet["smoke_execution_allowed"] is True
    assert "trusted_human_reviewer_ready" not in packet["prerequisites"]
    assert packet["review_workflow"]["mode"] == "streamlit_pending_review"
    assert packet["review_workflow"]["signature_required"] is False


def test_ready_packet_contains_only_smoke_and_review_commands(
    monkeypatch, tmp_path: Path,
) -> None:
    module = _module()
    _stub(monkeypatch, module, tmp_path, window_open=True)
    packet = module.prepare(run_id="20260818_204001")
    assert packet["smoke_execution_allowed"] is True
    assert "TASK1-V61-FAILED-SMOKE" in packet["commands"]["render_seven_shot_smoke"]
    assert packet["smoke_runner_source_contract"]["sha256"] in (
        packet["commands"]["render_seven_shot_smoke"]
    )
    assert packet["commands"]["prepare_human_review_packet_after_success"]
    assert packet["commands"]["full_batch_render"] == ""
    assert packet["commands"]["douyin_publish"] == ""
    assert packet["commands"]["fanqie_backfill"] == ""
    assert packet["mandatory_stop"]["after"] == "prepare_human_review_packet_after_success"
    assert packet["runtime_preflight"]["dialogue_audio_deferred"] is True


def test_window_packet_static_gate_requires_creative_contract(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    _stub(monkeypatch, module, tmp_path, window_open=True)
    monkeypatch.setattr(module.smoke, "_validate_static", lambda **kwargs: {
        "ok": False,
        "errors": ["Creative contract: explanatory narration must be forbidden"],
        "creative_contract_audit": {"passed": False},
    })
    packet = module.prepare(run_id="20260818_204001")
    assert packet["smoke_execution_allowed"] is False
    assert packet["commands"]["render_seven_shot_smoke"] == ""
    assert "static_inputs_ready" in packet["blockers"]


def test_busy_gpu_never_emits_executable_command(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    _stub(monkeypatch, module, tmp_path, window_open=True)
    monkeypatch.setattr(module, "_gpu_readiness", lambda: {
        "ready": False,
        "error": "GPU is already busy",
        "minimum_free_mib": module.MINIMUM_GPU_FREE_MIB,
        "maximum_utilization_percent": module.MAXIMUM_GPU_UTILIZATION_PERCENT,
        "devices": [{"index": 0, "memory_free_mib": 12000, "utilization_percent": 99}],
    })
    packet = module.prepare(run_id="20260818_204001")
    assert packet["smoke_execution_allowed"] is False
    assert packet["commands"]["render_seven_shot_smoke"] == ""
    assert packet["gpu"]["devices"][0]["utilization_percent"] == 99
    assert "gpu_resource_ready" in packet["blockers"]


def test_gpu_telemetry_is_read_only_and_shell_free(monkeypatch) -> None:
    module = _module()
    observed = {}

    def fake_run(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        return SimpleNamespace(stdout="0, RTX 5070 Ti, 16303, 12000, 9, 42\n")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    report = module._gpu_readiness()
    assert report["ready"] is True
    assert observed["command"][0] == "nvidia-smi"
    assert observed["kwargs"]["shell"] is False


def test_invalid_run_id_fails_closed() -> None:
    module = _module()
    with pytest.raises(ValueError, match="YYYYMMDD_HHMMSS"):
        module.prepare(run_id="latest")


def test_window_packet_has_no_allowed_signers_dependency(tmp_path: Path) -> None:
    module = _module()
    assert not hasattr(module, "_trusted_signers")
    parameters = inspect.signature(module.prepare).parameters
    assert "allowed_signers" not in parameters
    assert "reviewer_proof" not in parameters


def test_window_packet_has_no_legacy_reviewer_readiness_hook() -> None:
    module = _module()
    assert not hasattr(module, "_reviewer_readiness")


def test_window_packet_write_is_exclusive(tmp_path: Path) -> None:
    module = _module()
    output = tmp_path / "packet.json"
    module._write_new(output, {"first": True})
    with pytest.raises(ValueError, match="refusing to overwrite"):
        module._write_new(output, {"first": False})
    assert json.loads(output.read_text(encoding="utf-8")) == {"first": True}


def test_unreviewed_preflight_provider_source_fails_before_provider_call(
    monkeypatch, tmp_path: Path,
) -> None:
    module = _module()
    changed = tmp_path / "provider.py"
    changed.write_text("# changed provider\n", encoding="utf-8")
    monkeypatch.setattr(module, "P0_PROVIDER_SOURCE", changed)
    with pytest.raises(RuntimeError, match="unreviewed ComfyUI preflight provider"):
        module._assert_reviewed_read_only_preflight_source()


def test_unreviewed_smoke_runner_fails_before_command_emission(
    monkeypatch, tmp_path: Path,
) -> None:
    module = _module()
    changed = tmp_path / "runner.py"
    changed.write_text("# changed runner\n", encoding="utf-8")
    monkeypatch.setattr(module, "SMOKE_RUNNER_SOURCE", changed)
    with pytest.raises(RuntimeError, match="unreviewed smoke runner"):
        module._assert_reviewed_smoke_runner_source()


def test_main_returns_closed_json_envelope_for_prepare_runtime_error(
    monkeypatch, tmp_path: Path, capsys,
) -> None:
    module = _module()
    output = tmp_path / "must-not-exist.json"
    monkeypatch.setattr(
        module,
        "prepare",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("synthetic runtime gate")),
    )
    rc = module.main([
        "--run-id", "20260818_204001", "--output", str(output),
    ])
    envelope = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert envelope == {"success": False, "error": "synthetic runtime gate"}
    assert not output.exists()
