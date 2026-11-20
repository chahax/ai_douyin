from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts/run_task1_story_v61_failed_smoke.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("task1_v61_failed_smoke", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_bound_args(tmp_path: Path, run_id: str = "20260818_204001") -> list[str]:
    module = _load_module()
    return [
        "--run-id", run_id,
        "--progress-path", str(
            tmp_path / f"task1_story_v61_failed_smoke_progress_{run_id}.json"
        ),
        "--audio-dir", str(tmp_path / f"task1_story_v61_failed_smoke_{run_id}"),
        "--output-dir", str(tmp_path / "render" / f"task1_story_v61_failed_smoke_{run_id}"),
        "--evidence-root", str(tmp_path / f"task1_story_v61_{run_id}"),
        "--expected-runner-sha256", module._sha256(module.Path(module.__file__).resolve()),
    ]


def test_failed_shot_boundary_is_exact() -> None:
    module = _load_module()
    assert module.FAILED_SHOT_IDS == (
        "b01_boast",
        "b03_object_question",
        "b04_confused_answer",
        "b05_age_burst",
        "b06_pull_away",
        "b07_protest",
        "b08_offer_one",
    )
    assert "b02_grab_reaction" not in module.FAILED_SHOT_IDS


def test_execution_window_is_immediately_open_and_requires_aware_clock() -> None:
    module = _load_module()
    result = module._execution_window(datetime(2026, 8, 14, tzinfo=timezone.utc))
    assert result["open"] is True
    assert result["not_before"] is None
    assert result["remaining_seconds"] == 0.0
    assert result["policy"] == "immediate_execution_with_frontend_human_review"
    with pytest.raises(ValueError, match="timezone-aware"):
        module._execution_window(datetime(2026, 8, 18, 20, 40))


def test_outside_scope_shot_fails_closed() -> None:
    module = _load_module()
    with pytest.raises(ValueError, match="outside-scope"):
        module._select_plans([], ["b02_grab_reaction"])


def test_execute_requires_exact_confirmation(tmp_path: Path) -> None:
    module = _load_module()
    rc = module.main(
        [
            "--execute",
            "--confirm-execution",
            "wrong-token",
            "--progress-path",
            str(tmp_path / "must_not_exist.json"),
        ]
    )
    assert rc == 2
    assert not (tmp_path / "must_not_exist.json").exists()


@pytest.mark.parametrize("mode", ["--prepare-audio", "--execute"])
def test_mutating_mode_fails_closed_if_execution_policy_is_forced_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: str,
) -> None:
    module = _load_module()
    monkeypatch.setattr(
        module,
        "_execution_window",
        lambda: {
            "open": False,
            "observed_at": "2026-08-13T23:00:00+08:00",
            "not_before": None,
            "remaining_seconds": 0.0,
            "policy": "test_forced_closed",
        },
    )
    monkeypatch.setattr(
        module, "_synthesize_performance_audio",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("TTS must not run")),
    )
    monkeypatch.setattr(
        module, "_provider",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("provider must not run")),
    )
    progress = tmp_path / "must_not_exist.json"
    args = [
        mode,
        "--progress-path", str(progress),
        "--expected-runner-sha256", module._sha256(module.Path(module.__file__).resolve()),
    ]
    if mode == "--execute":
        args.extend(["--confirm-execution", module.EXECUTION_CONFIRMATION])
    assert module.main(args) == 2
    assert not progress.exists()


def test_default_validation_uses_separate_audit_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_module()
    validation_path = tmp_path / "validation.json"
    render_progress_path = tmp_path / "render_progress.json"
    render_progress_path.write_text("render-proof", encoding="utf-8")
    monkeypatch.setattr(module, "DEFAULT_VALIDATION", validation_path)
    monkeypatch.setattr(module, "DEFAULT_PROGRESS", render_progress_path)
    rc = module.main([])
    assert rc == 0
    assert validation_path.is_file()
    assert render_progress_path.read_text(encoding="utf-8") == "render-proof"


def test_validate_only_cannot_target_render_progress_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_module()
    protected = tmp_path / "smoke_progress.json"
    protected.write_text("immutable", encoding="utf-8")
    monkeypatch.setattr(module, "DEFAULT_PROGRESS", protected)
    rc = module.main(["--progress-path", str(protected)])
    assert rc == 2
    assert protected.read_text(encoding="utf-8") == "immutable"


def test_validate_only_cannot_overwrite_custom_render_evidence(
    tmp_path: Path,
) -> None:
    module = _load_module()
    protected = tmp_path / "custom-render.json"
    original = {
        "result": "FAILED_SCENE_SMOKE_RENDERED_AWAITING_HUMAN_REVIEW",
        "shots": [{"scene_id": "b01_boast"}],
    }
    protected.write_text(json.dumps(original), encoding="utf-8")
    assert module.main(["--progress-path", str(protected)]) == 2
    assert json.loads(protected.read_text(encoding="utf-8")) == original


def test_mutating_mode_never_overwrites_rendered_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "_execution_window", lambda: {"open": True})
    progress = tmp_path / "rendered.json"
    original = {
        "result": "FAILED_SCENE_SMOKE_RENDERED_AWAITING_HUMAN_REVIEW",
        "shots": [{"scene_id": "b01_boast"}],
    }
    progress.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(
        module, "_load_structured_scene_plan",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must stop before plan")),
    )
    rc = module.main([
        "--prepare-audio", "--progress-path", str(progress),
        "--replace-incomplete-progress",
    ])
    assert rc == 2
    assert json.loads(progress.read_text(encoding="utf-8")) == original


def test_mutating_mode_never_replaces_incomplete_or_concurrently_claimed_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "_execution_window", lambda: {"open": True})
    progress = tmp_path / "incomplete.json"
    original = {"result": "RUN_PATH_RESERVED", "shots": []}
    progress.write_text(json.dumps(original), encoding="utf-8")
    rc = module.main([
        "--prepare-audio", "--progress-path", str(progress),
        "--replace-incomplete-progress",
    ])
    assert rc == 2
    assert json.loads(progress.read_text(encoding="utf-8")) == original

    claimed = tmp_path / "claimed.json"
    module._reserve_render_progress(claimed)
    with pytest.raises(ValueError, match="claimed concurrently"):
        module._reserve_render_progress(claimed)


def test_mutating_directories_are_claimed_exclusively(tmp_path: Path) -> None:
    module = _load_module()
    output = tmp_path / "render"
    audio = tmp_path / "audio"
    evidence = tmp_path / "evidence"
    module._reserve_render_directories(output, audio, evidence)
    assert all(path.is_dir() for path in (output, audio, evidence))
    with pytest.raises(ValueError, match="already exists|claimed concurrently"):
        module._reserve_render_directories(output, tmp_path / "other", tmp_path / "more")


def test_runner_api_has_no_human_review_key_or_proof_parameters() -> None:
    module = _load_module()
    assert not hasattr(module, "verify_reviewer_readiness")
    parser_source = Path(module.__file__).read_text(encoding="utf-8")
    assert "--reviewer-proof" not in parser_source
    assert "--allowed-signers" not in parser_source


def test_run_id_must_bind_every_mutating_artifact_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "_execution_window", lambda: {"open": True})
    args = _run_bound_args(tmp_path)
    args[args.index("--output-dir") + 1] = str(tmp_path / "unbound-render")
    rc = module.main(["--prepare-audio", *args])
    assert rc == 2
    assert not Path(args[args.index("--progress-path") + 1]).exists()


def test_default_mode_is_static_and_keeps_publish_gates_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_module()

    def forbidden(*args, **kwargs):
        raise AssertionError("runtime/TTS provider must not run in default mode")

    monkeypatch.setattr(module, "_synthesize_performance_audio", forbidden)
    monkeypatch.setattr(module, "_provider", forbidden)
    progress_path = tmp_path / "progress.json"
    rc = module.main(["--progress-path", str(progress_path)])
    assert rc == 0
    report = json.loads(progress_path.read_text(encoding="utf-8"))
    assert report["result"] == "STATIC_VALIDATION_PASSED"
    assert report["mode"] == "validate_only"
    assert report["selected_shot_ids"] == list(module.FAILED_SHOT_IDS)
    assert report["static_validation"]["all_beat_count"] == 19
    assert report["static_validation"]["spoken_closeup_count"] == 7
    assert len(report["static_validation"]["master_checks"]) == 2
    assert all(item["ok"] for item in report["static_validation"]["master_checks"])
    assert report["gates"]["publish_allowed"] is False
    assert report["gates"]["fanqie_backfill_allowed"] is False
    assert report["gates"]["human_review_required"] is True
    assert report["forbidden_side_effects"] == {
        "database_writes": 0,
        "browser_operations": 0,
        "douyin_uploads": 0,
        "fanqie_backfills": 0,
    }


@pytest.mark.parametrize("source_index", range(8))
def test_each_reviewed_runtime_source_change_fails_static_gate_before_tts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, source_index: int
) -> None:
    module = _load_module()
    changed = tmp_path / f"changed_runtime_source_{source_index}.py"
    changed.write_text("# altered runner\n", encoding="utf-8")
    source_files = list(module.SOURCE_FILES)
    source_files[source_index] = changed
    monkeypatch.setattr(module, "SOURCE_FILES", tuple(source_files))
    monkeypatch.setattr(
        module, "_synthesize_performance_audio",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("TTS must not run")),
    )
    progress_path = tmp_path / "changed_source_validation.json"
    rc = module.main(["--progress-path", str(progress_path)])
    report = json.loads(progress_path.read_text(encoding="utf-8"))
    assert rc == 2
    integrity = report["static_validation"]["runtime_source_integrity"]
    assert integrity["ok"] is False
    assert "Reviewed runtime source missing or changed" in " ".join(integrity["errors"])


def test_changed_pinned_source_fails_prepare_audio_before_tts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    module = _load_module()
    changed = tmp_path / "changed_runtime_source.py"
    changed.write_text("# altered runtime source\n", encoding="utf-8")
    source_files = list(module.SOURCE_FILES)
    source_files[0] = changed
    monkeypatch.setattr(module, "SOURCE_FILES", tuple(source_files))
    tts_calls = []
    monkeypatch.setattr(
        module,
        "_synthesize_performance_audio",
        lambda **kwargs: tts_calls.append(kwargs),
    )
    args = _run_bound_args(tmp_path)
    progress = Path(args[args.index("--progress-path") + 1])
    rc = module.main(["--prepare-audio", *args])
    assert rc == 2
    assert tts_calls == []
    assert not progress.exists()


def test_prepare_audio_stops_before_video_generation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "_execution_window", lambda: {"open": True})
    calls = {"audio": 0, "provide": 0}

    def fake_audio(*, scene_plans, emotion_config, output_dir, dry_run=False):
        calls["audio"] += 1
        for plan in scene_plans:
            plan.metadata["dialogue_audio_path"] = str(tmp_path / f"{plan.scene_id}.wav")
        return {"success": True, "error": ""}

    class FakeProvider:
        def preflight(self, plans, require_dialogue_audio=True):
            assert require_dialogue_audio is True
            return SimpleNamespace(ok=True, status="ok", error="", details={})

        def provide_scenes(self, plans, output_dir):
            calls["provide"] += 1
            raise AssertionError("--prepare-audio must never generate video")

    monkeypatch.setattr(module, "_synthesize_performance_audio", fake_audio)
    monkeypatch.setattr(module, "_provider", lambda *args, **kwargs: FakeProvider())
    args = _run_bound_args(tmp_path)
    progress_path = Path(args[args.index("--progress-path") + 1])
    rc = module.main(["--prepare-audio", *args])
    report = json.loads(progress_path.read_text(encoding="utf-8"))
    assert rc == 0
    assert calls == {"audio": 1, "provide": 0}
    assert report["result"] == "AUDIO_AND_RUNTIME_PREFLIGHT_PASSED"
    assert report["gates"]["audio_prepared"] is True
    assert report["gates"]["failed_scene_smoke_rendered"] is False
    assert report["gates"]["publish_allowed"] is False
    assert report["gates"]["fanqie_backfill_allowed"] is False


def test_audio_failure_stops_before_runtime_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "_execution_window", lambda: {"open": True})
    monkeypatch.setattr(
        module,
        "_synthesize_performance_audio",
        lambda **kwargs: {"success": False, "error": "truncated"},
    )
    monkeypatch.setattr(
        module,
        "_provider",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("provider must not be created after TTS failure")
        ),
    )
    args = _run_bound_args(tmp_path)
    progress_path = Path(args[args.index("--progress-path") + 1])
    rc = module.main(["--prepare-audio", *args])
    report = json.loads(progress_path.read_text(encoding="utf-8"))
    assert rc == 3
    assert report["result"] == "AUDIO_PREPARATION_FAILED"
    assert report["gates"]["publish_allowed"] is False


def test_runtime_preflight_failure_stops_before_video(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "_execution_window", lambda: {"open": True})
    monkeypatch.setattr(
        module,
        "_synthesize_performance_audio",
        lambda **kwargs: {"success": True, "error": ""},
    )

    class FakeProvider:
        def preflight(self, plans, require_dialogue_audio=True):
            assert require_dialogue_audio is True
            return SimpleNamespace(
                ok=False, status="service_unavailable", error="offline", details={}
            )

        def provide_scenes(self, plans, output_dir):
            raise AssertionError("failed preflight must never generate video")

    monkeypatch.setattr(module, "_provider", lambda *args, **kwargs: FakeProvider())
    args = _run_bound_args(tmp_path)
    progress_path = Path(args[args.index("--progress-path") + 1])
    rc = module.main(["--prepare-audio", *args])
    report = json.loads(progress_path.read_text(encoding="utf-8"))
    assert rc == 4
    assert report["result"] == "RUNTIME_PREFLIGHT_FAILED"
    assert report["gates"]["publish_allowed"] is False


def test_execute_renders_only_selected_shots_and_keeps_platform_gates_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "_execution_window", lambda: {"open": True})
    rendered: list[str] = []
    monkeypatch.setattr(
        module,
        "_synthesize_performance_audio",
        lambda **kwargs: {"success": True, "error": ""},
    )

    class FakeProvider:
        def preflight(self, plans, require_dialogue_audio=True):
            assert require_dialogue_audio is True
            return SimpleNamespace(ok=True, status="ok", error="", details={})

        def provide_scenes(self, plans, output_dir):
            assert len(plans) == 1
            rendered.append(plans[0].scene_id)
            return SimpleNamespace(
                assets=[SimpleNamespace(scene_id=plans[0].scene_id)], missing=[]
            )

    monkeypatch.setattr(module, "_provider", lambda *args, **kwargs: FakeProvider())
    args = _run_bound_args(tmp_path)
    progress_path = Path(args[args.index("--progress-path") + 1])
    rc = module.main([
        "--execute", "--confirm-execution", module.EXECUTION_CONFIRMATION,
        *args,
    ])
    report = json.loads(progress_path.read_text(encoding="utf-8"))
    assert rc == 0
    assert rendered == list(module.FAILED_SHOT_IDS)
    assert report["result"] == "FAILED_SCENE_SMOKE_RENDERED_AWAITING_HUMAN_REVIEW"
    assert report["gates"]["failed_scene_smoke_rendered"] is True
    assert report["gates"]["human_video_approval_obtained"] is False
    assert report["gates"]["matching_fanqie_task_confirmed"] is False
    assert report["gates"]["publish_allowed"] is False
    assert report["gates"]["fanqie_backfill_allowed"] is False


def test_single_shot_diagnostic_is_not_review_eligible(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "_execution_window", lambda: {"open": True})
    monkeypatch.setattr(
        module, "_synthesize_performance_audio",
        lambda **kwargs: {"success": True, "error": ""},
    )

    class FakeProvider:
        def preflight(self, plans, require_dialogue_audio=True):
            return SimpleNamespace(ok=True, status="ok", error="", details={})

        def provide_scenes(self, plans, output_dir):
            return SimpleNamespace(
                assets=[SimpleNamespace(scene_id=plans[0].scene_id)], missing=[]
            )

    monkeypatch.setattr(module, "_provider", lambda *args, **kwargs: FakeProvider())
    args = _run_bound_args(tmp_path)
    progress_path = Path(args[args.index("--progress-path") + 1])
    rc = module.main([
        "--execute", "--confirm-execution", module.EXECUTION_CONFIRMATION,
        "--shot-id", "b01_boast", *args,
    ])
    report = json.loads(progress_path.read_text(encoding="utf-8"))
    assert rc == 0
    assert report["result"] == "DIAGNOSTIC_SHOTS_RENDERED_NOT_REVIEW_ELIGIBLE"
    assert report["gates"]["selected_shots_rendered"] is True
    assert report["gates"]["failed_scene_smoke_rendered"] is False
    assert report["gates"]["publish_allowed"] is False
