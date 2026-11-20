"""Offline authorization, source routing and immutable natural-director fixtures."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

from scripts import run_natural_director_v10 as cli
from src.web import natural_director_panel_v10 as panel


@pytest.fixture
def runtime(monkeypatch):
    import src.content_factory as package
    module = ModuleType("src.content_factory.natural_director_pipeline_v10")
    module.calls = []
    module.report = {"schema": "natural_director_pipeline/v10", "status": "prepared", "stage": "natural_director",
                     "dispatch_blocked": False, "blockers": [], "pending_call": None,
                     "automatic_media_submit": False}
    for name in ("prepare", "execute", "preview", "inspect", "recover_projection", "prepare_source",
                 "execute_source", "execute_writer_only", "preview_source", "inspect_source"):
        def call(*args, _name=name, **kwargs):
            module.calls.append((_name, args, kwargs))
            return dict(module.report)
        setattr(module, name, call)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(package, "natural_director_pipeline_v10", module, raising=False)
    coordinator = ModuleType("src.content_factory.natural_director_source_runner_v11")
    coordinator.execute_source = module.execute_source
    monkeypatch.setitem(sys.modules, coordinator.__name__, coordinator)
    monkeypatch.setattr(package, "natural_director_source_runner_v11", coordinator, raising=False)
    return module


@pytest.fixture
def authorization(tmp_path):
    path = tmp_path / "AUTHORIZATION.json"
    path.write_text('{"schema":"offline-entrypoint-fixture","human_authorization":"fixture only"}', encoding="utf-8")
    return path


def test_prepare_requires_an_authorization_file_argument():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["prepare", "--run-dir", "child", "--parent-run", "parent"])


def test_prepare_does_not_call_runtime_without_actual_authorization(runtime, tmp_path, capsys):
    assert cli.main(["prepare", "--run-dir", "child", "--parent-run", "parent",
                     "--authorization-path", str(tmp_path / "missing.json")]) == 1
    assert "授权" in json.loads(capsys.readouterr().out)["error"]
    assert not runtime.calls


@pytest.mark.parametrize("body", ["[]", "null", '{"a":1,"a":2}', '{"a":NaN}', '{"nested":{"a":1,"a":2}}'])
def test_authorization_file_requires_strict_complete_json_object(body, runtime, tmp_path, capsys):
    path = tmp_path / "authorization.json"
    path.write_text(body, encoding="utf-8")
    assert cli.main(["prepare", "--run-dir", "new", "--parent-run", "old", "--authorization-path", str(path)]) == 1
    capsys.readouterr()
    assert not runtime.calls


def test_prepare_forwards_only_exact_parent_authorization_and_new_run(runtime, authorization, capsys):
    assert cli.main(["prepare", "--run-dir", "new", "--parent-run", "old", "--authorization-path", str(authorization)]) == 0
    capsys.readouterr()
    assert runtime.calls == [("prepare", (), {"run_dir": Path("new"), "parent_run": Path("old"),
                                              "authorization_path": authorization})]


@pytest.mark.parametrize("command", ["prepare", "source-prepare", "source-execute"])
@pytest.mark.parametrize("override", ["--max-calls", "--max-total-tokens", "--max-rounds", "--registry-dir", "--skip-review", "--submit-video"])
def test_no_budget_round_registry_or_review_override(command, override, authorization):
    argv = [command, "--authorization-path", str(authorization)]
    if command == "prepare":
        argv += ["--run-dir", "new", "--parent-run", "old"]
    elif command == "source-prepare":
        argv += ["--source-run-dir", "source", "--source-path", "text.txt"]
    else:
        argv += ["--source-run-dir", "source", "--run-dir", "natural"]
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args([*argv, override, "100"])


@pytest.mark.parametrize("command,method", [("execute", "execute"), ("preview", "preview"),
                                            ("inspect", "inspect"), ("recover", "recover_projection")])
def test_existing_run_commands_are_single_thin_runtime_action(command, method, runtime, capsys):
    assert cli.main([command, "--run-dir", "run"]) == 0
    capsys.readouterr()
    assert runtime.calls == [(method, (), {"run_dir": Path("run")})]


@pytest.mark.parametrize("status", sorted(cli.FAILURE_STATUSES))
def test_failed_run_exits_once_without_retry(status, runtime, capsys):
    runtime.report["status"] = status
    assert cli.main(["execute", "--run-dir", "run"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == status
    assert len(runtime.calls) == 1


@pytest.mark.parametrize("kind", ["novel", "original"])
def test_new_source_cli_uses_writer_only_bound_backend(kind, runtime, authorization, capsys):
    assert cli.main(["source-prepare", "--source-run-dir", "writer", "--authorization-path", str(authorization),
                     "--source-kind", kind, "--source-path", "source.txt", "--scope", "全文"]) == 0
    capsys.readouterr()
    method, args, kwargs = runtime.calls[0]
    assert method == "prepare_source" and args == (Path("writer"),) and kwargs["source_kind"] == kind
    from src.content_factory.visual_storytelling_v1 import profile
    assert kwargs["brief"]["visual_storytelling"] == profile()
    assert "brief_json" not in kwargs


def test_original_source_cannot_use_novel_acquisition_receipt(runtime, authorization, capsys):
    assert cli.main(["source-prepare", "--source-run-dir", "writer", "--authorization-path", str(authorization),
                     "--source-kind", "original", "--acquisition-receipt", "receipt.json"]) == 1
    capsys.readouterr()
    assert not runtime.calls


def test_source_execute_calls_one_shared_coordinator_not_a_ui_stage_loop(runtime, authorization, capsys):
    assert cli.main(["source-execute", "--source-run-dir", "writer", "--run-dir", "natural",
                     "--authorization-path", str(authorization)]) == 0
    capsys.readouterr()
    assert runtime.calls == [("execute_source", (), {"source_run_dir": Path("writer"), "run_dir": Path("natural"),
                                                     "authorization_path": authorization})]


@pytest.mark.parametrize("command,method", [("source-inspect", "inspect_source"), ("source-preview", "preview_source")])
def test_source_read_actions_use_route_verifying_backend(command, method, runtime, capsys):
    assert cli.main([command, "--source-run-dir", "writer"]) == 0
    capsys.readouterr()
    assert runtime.calls == [(method, (), {"source_run_dir": Path("writer")})]


def test_unknown_error_is_reported_without_second_call(runtime, capsys):
    def fail(**kwargs):
        runtime.calls.append(("execute_failed", (), kwargs))
        raise RuntimeError("result unknown")
    runtime.execute = fail
    assert cli.main(["execute", "--run-dir", "run"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["automatic_retry"] is False and result["automatic_media_submit"] is False
    assert len(runtime.calls) == 1


def _spawns(monkeypatch):
    monkeypatch.setattr(panel, "get_current_role", lambda: "editor")
    calls = []
    def popen(argv, **kwargs):
        assert kwargs["creationflags"] == getattr(panel.subprocess, "CREATE_NO_WINDOW", 0)
        assert kwargs["stdin"] == panel.subprocess.DEVNULL
        assert kwargs["cwd"] == panel.ROOT
        calls.append(argv)
        return SimpleNamespace(pid=511)
    monkeypatch.setattr(panel.subprocess, "Popen", popen)
    return calls


def test_web_prepare_is_local_and_uses_same_source_backend(runtime, authorization, tmp_path, monkeypatch):
    spawns = _spawns(monkeypatch)
    panel.prepare_source(tmp_path / "writer", authorization_path=authorization, source_path=tmp_path / "source.txt",
                         source_kind="original", title="新故事", scope="全文", brief={"target_duration_seconds": 120})
    assert runtime.calls[0][0] == "prepare_source" and not spawns
    assert runtime.calls[0][2]["authorization_path"] == authorization


def test_web_launch_runs_one_full_natural_source_cli_and_retains_guard(runtime, authorization, tmp_path, monkeypatch):
    spawns = _spawns(monkeypatch)
    source = tmp_path / "writer"
    source.mkdir()
    receipt = panel.launch_source(source, tmp_path / "natural", authorization_path=authorization)
    assert receipt["automatic_media_submit"] is False and receipt["automatic_retry"] is False
    assert spawns[0][2] == "source-execute" and Path(spawns[0][1]).name == "run_natural_director_v10.py"
    assert [row[0] for row in runtime.calls] == ["inspect_source", "inspect_source", "preview_source"]
    with pytest.raises(RuntimeError, match="已提交"):
        panel.launch_source(source, tmp_path / "natural", authorization_path=authorization)
    assert len(spawns) == 1 and (source / ".natural_web_launch.lock").exists()


@pytest.mark.parametrize("change", [{"pending_call": 1}, {"dispatch_blocked": True}, {"blockers": ["stop"]},
                                    {"status": "needs_attention"}, {"status": "text_ready_for_production"}, {"status": "unknown"}])
def test_web_stop_or_unknown_status_never_starts(change, runtime, authorization, tmp_path, monkeypatch):
    spawns = _spawns(monkeypatch)
    source = tmp_path / "writer"
    source.mkdir()
    runtime.report.update(change)
    with pytest.raises(RuntimeError):
        panel.launch_source(source, tmp_path / "natural", authorization_path=authorization)
    assert not spawns and not (source / ".natural_web_launch.lock").exists()


def test_web_pending_after_lock_wins_blocks_start(runtime, authorization, tmp_path, monkeypatch):
    spawns = _spawns(monkeypatch)
    source = tmp_path / "writer"
    source.mkdir()
    reports = iter([runtime.report, {**runtime.report, "pending_call": 1}])
    runtime.inspect_source = lambda *_: next(reports)
    with pytest.raises(RuntimeError):
        panel.launch_source(source, tmp_path / "natural", authorization_path=authorization)
    assert not spawns and not (source / ".natural_web_launch.lock").exists()


def test_web_post_spawn_receipt_error_keeps_duplicate_guard(runtime, authorization, tmp_path, monkeypatch):
    spawns = _spawns(monkeypatch)
    source = tmp_path / "writer"
    source.mkdir()
    original = Path.open
    def fail(path, *args, **kwargs):
        if path.name == "NATURAL_LAST_LAUNCH.json":
            raise OSError("disk failure")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", fail)
    with pytest.raises(OSError):
        panel.launch_source(source, tmp_path / "natural", authorization_path=authorization)
    assert len(spawns) == 1 and (source / ".natural_web_launch.lock").exists()


def test_viewer_cannot_prepare_or_launch(runtime, authorization, tmp_path, monkeypatch):
    monkeypatch.setattr(panel, "get_current_role", lambda: "viewer")
    with pytest.raises(PermissionError):
        panel.prepare_source(tmp_path / "writer", authorization_path=authorization, source_path="source.txt")
    with pytest.raises(PermissionError):
        panel.launch_source(tmp_path / "writer", tmp_path / "natural", authorization_path=authorization)
    assert not runtime.calls


def test_presentation_files_include_natural_and_review_not_native_envelopes(tmp_path):
    for name in ("NATURAL_DIRECTOR_001.md", "EXTRACT_002.json", "FINAL_REVIEW_003.json", "RESPONSE_001.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    assert {p.name for p in panel.artifact_files(tmp_path)} == {
        "NATURAL_DIRECTOR_001.md", "EXTRACT_002.json", "FINAL_REVIEW_003.json"}


@pytest.mark.parametrize("kind,title", [("novel", "小说改编"), ("original", "原创剧情")])
def test_source_pages_use_natural_route_without_low_level_budget_fields(kind, title, runtime, tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setattr(panel, "get_current_role", lambda: "editor")
    runtime.report["status"] = "unprepared"
    app = AppTest.from_string(f"from src.web.natural_director_panel_v10 import page_story_workflow\npage_story_workflow('{kind}')")
    app.session_state["natural_director_v10_" + kind + "_workspace"] = str(tmp_path / "workspace")
    app.run()
    assert not app.exception and app.title[0].value == title
    assert any("MiniMax自然导演" in item.value for item in app.caption)
    assert not any("预算" in item.label or "max-calls" in item.label or "schema" in item.label for item in app.text_input)
    assert all(row[0] in {"inspect", "inspect_source"} for row in runtime.calls)


def test_actual_app_new_novel_and_original_routes_use_natural_source_backend():
    tree = ast.parse((panel.ROOT / "src/web/app.py").read_text(encoding="utf-8-sig"))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    for name, imported in (("page_novel_adaptation", "page_novel_adaptation"),
                           ("page_creative_workflow", "page_original_story")):
        imports = [node for node in ast.walk(functions[name]) if isinstance(node, ast.ImportFrom)]
        assert [(node.module, node.names[0].name) for node in imports] == [("src.web.natural_director_panel_v10", imported)]
    legacy = [node for node in ast.walk(functions["page_legacy_creative_records"]) if isinstance(node, ast.ImportFrom)]
    assert [(node.module, node.names[0].name) for node in legacy] == [("src.web.novel_agent_panel_v9", "page_legacy_creative_records")]


FIXTURES = Path(__file__).parent / "fixtures/natural_director_v10"
HOLDOUT = Path(__file__).parent / "fixtures/natural_director_v10_holdout"


@pytest.mark.parametrize("folder", [FIXTURES, HOLDOUT])
def test_fresh_natural_and_new_holdout_freezes_are_intact(folder):
    freeze = json.loads((folder / "FROZEN_MANIFEST.json").read_text(encoding="utf-8"))
    assert freeze["semantic_service_validation"] == "not_run"
    for name, expected in freeze["files_sha256"].items():
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == expected


def test_five_fresh_cases_cover_distinct_interaction_modes():
    value = json.loads((FIXTURES / "fresh_cases.json").read_text(encoding="utf-8"))
    assert value["fixture_origin"] == "locally_authored_offline_contract_examples"
    assert {row["category"] for row in value["cases"]} == {
        "two_person_family", "three_person_workplace", "walking_prop", "silence_averted_gaze", "phone_offscreen"}
    assert all((FIXTURES / row["path"]).is_file() for row in value["cases"])


def test_two_long_projection_cases_require_semantic_review_not_self_declared_pass():
    value = json.loads((FIXTURES / "projection_cases.json").read_text(encoding="utf-8"))
    assert len(value["cases"]) == 2
    for case in value["cases"]:
        assert hashlib.sha256((FIXTURES / case["natural_path"]).read_bytes()).hexdigest() == case["source_sha256"]
        assert case["expected_positive_verdict"] == "pass" and case["expected_negative_verdict"] == "revise"
        assert case["positive_projection"]["verdict"] == case["negative_projection"]["verdict"] == "pass"
        assert case["positive_projection"] != case["negative_projection"] and case["negative_reasons"]


def test_new_workplace_holdout_is_not_old_office_renamed():
    freeze = json.loads((HOLDOUT / "FROZEN_MANIFEST.json").read_text(encoding="utf-8"))
    assert freeze["used_for_prompt_tuning"] is False and freeze["old_office_unresolved_preserved"] is True
    text = (HOLDOUT / "team_shift_source.txt").read_text(encoding="utf-8")
    old = (Path(__file__).parent / "fixtures/narrative_quality_v8/holdout_office_source.txt").read_text(encoding="utf-8")
    assert text != old and "扫码器" not in text and "托管" in text and "临时加单" in text
