"""Independent v9 entrypoint/fixture verification. No providers or media calls."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

from scripts import run_novel_agent_v9 as cli
from src.web import novel_agent_panel_v9 as panel


@pytest.fixture
def runtime(monkeypatch):
    import src.content_factory as package
    module = ModuleType("src.content_factory.novel_agent_pipeline_v9")
    module.calls = []
    module.report = {"schema": panel.VERSION, "status": "prepared", "dispatch_blocked": False,
                     "blockers": [], "state": {"stage": "writer_full", "pending_call": None},
                     "human_approved": False, "automatic_media_submit": False}
    for name in ("prepare", "prepare_quality_revision", "prepare_known_director_continuation", "inspect", "preview", "execute", "recover_projection"):
        def call(*args, _name=name, **kwargs):
            module.calls.append((_name, args, kwargs))
            return dict(module.report)
        setattr(module, name, call)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(package, "novel_agent_pipeline_v9", module, raising=False)
    return module


def _binding(run, schema=panel.VERSION):
    run.mkdir(parents=True, exist_ok=True)
    (run / "BINDING.json").write_text(json.dumps({"schema": schema}), encoding="utf-8")


def _spawns(monkeypatch):
    monkeypatch.setattr(panel, "get_current_role", lambda: "editor")
    calls = []
    def popen(argv, **kwargs):
        assert kwargs["creationflags"] == getattr(panel.subprocess, "CREATE_NO_WINDOW", 0)
        assert kwargs["cwd"] == panel.ROOT
        assert kwargs["stdin"] == panel.subprocess.DEVNULL
        calls.append(argv)
        return SimpleNamespace(pid=888)
    monkeypatch.setattr(panel.subprocess, "Popen", popen)
    return calls


@pytest.mark.parametrize("kind", ["novel", "original"])
def test_cli_new_sources_use_same_v9_runtime(kind, tmp_path, runtime, capsys):
    assert cli.main(["prepare", "--run-dir", str(tmp_path / "run"), "--source-kind", kind,
                     "--source-path", str(tmp_path / "source.txt"), "--scope", "完整正文",
                     "--target-duration-seconds", "120"]) == 0
    assert json.loads(capsys.readouterr().out)["automatic_media_submit"] is False
    name, args, kwargs = runtime.calls[0]
    assert name == "prepare" and args == () and kwargs["source_kind"] == kind
    assert kwargs["brief"] == {"target_duration_seconds": 120}
    assert "registry_dir" not in kwargs and "saved_book_metadata" not in kwargs


@pytest.mark.parametrize("option", ["--registry-dir", "--skip-review", "--skip-quality", "--submit-video"])
def test_cli_does_not_expose_bypass_options(option):
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["prepare", "--run-dir", "new", "--source-path", "s", option, "x"])


@pytest.mark.parametrize("source_option", ["--acquisition-receipt", "--saved-book-metadata"])
def test_original_cannot_masquerade_as_novel_metadata(source_option, runtime, capsys):
    assert cli.main(["prepare", "--run-dir", "new", "--source-kind", "original", source_option, "x"]) == 1
    assert "原创" in json.loads(capsys.readouterr().out)["error"]
    assert not runtime.calls


@pytest.mark.parametrize("command", ["execute", "preview", "inspect", "recover-projection", "prepare-quality-revision"])
def test_cli_dispatches_only_requested_new_version_action(command, runtime, capsys):
    argv = [command, "--run-dir", "new"]
    if command == "prepare-quality-revision":
        argv += ["--parent-run", "old"]
    assert cli.main(argv) == 0
    capsys.readouterr()
    assert len(runtime.calls) == 1 and runtime.calls[0][0] == command.replace("-", "_")


@pytest.mark.parametrize("option", ["--max-calls", "--max-total-tokens", "--max-revisions", "--registry-dir"])
def test_quality_revision_cannot_override_budget_or_registry(option):
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["prepare-quality-revision", "--run-dir", "new", "--parent-run", "old", option, "100"])


def test_known_director_continuation_is_explicit_local_preparation_only(runtime, capsys):
    assert cli.main(["prepare-known-director-continuation", "--run-dir", "child", "--parent-run", "original"]) == 0
    capsys.readouterr()
    assert runtime.calls == [("prepare_known_director_continuation", (),
                              {"run_dir": Path("child"), "parent_run": Path("original")})]


@pytest.mark.parametrize("option", ["--max-calls", "--max-total-tokens", "--max-revisions", "--registry-dir", "--brief-json", "--source-path", "--target-duration-seconds"])
def test_known_director_continuation_cannot_change_parent_brief_capacity_or_source(option):
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["prepare-known-director-continuation", "--run-dir", "new", "--parent-run", "old", option, "100"])


def test_web_known_continuation_forwards_only_parent_and_new_directory(tmp_path, runtime, monkeypatch):
    spawns = _spawns(monkeypatch)
    panel.prepare_known_director_continuation(tmp_path / "new", parent_run=tmp_path / "old")
    assert runtime.calls == [("prepare_known_director_continuation", (tmp_path / "new",),
                              {"parent_run": tmp_path / "old"})]
    assert not spawns


def test_viewer_cannot_prepare_known_director_continuation(tmp_path, runtime, monkeypatch):
    monkeypatch.setattr(panel, "get_current_role", lambda: "viewer")
    with pytest.raises(PermissionError):
        panel.prepare_known_director_continuation(tmp_path / "new", parent_run=tmp_path / "old")
    assert not runtime.calls


@pytest.mark.parametrize("schema", ["novel_agent_pipeline/v8", "novel_agent_pipeline/v7", "novel_agent_pipeline/v6", "novel_plaintext_pipeline/v3", "future/v9"])
def test_cli_frozen_legacy_never_enters_v9(schema, tmp_path, runtime, capsys):
    _binding(tmp_path, schema)
    before = (tmp_path / "BINDING.json").read_bytes()
    assert cli.main(["execute", "--run-dir", str(tmp_path)]) == 1
    assert "不能迁移" in json.loads(capsys.readouterr().out)["error"]
    assert not runtime.calls and (tmp_path / "BINDING.json").read_bytes() == before


def test_duplicate_binding_fails_closed(tmp_path, runtime, capsys):
    (tmp_path / "BINDING.json").write_text('{"schema":"novel_agent_pipeline/v9","schema":"novel_agent_pipeline/v7"}', encoding="utf-8")
    assert cli.main(["execute", "--run-dir", str(tmp_path)]) == 1
    assert "重复" in json.loads(capsys.readouterr().out)["error"]
    assert not runtime.calls


def test_graph_and_native_share_v9_only(runtime, monkeypatch, capsys):
    module = ModuleType("src.content_factory.novel_agent_graph_v9")
    calls = []
    module.execute_graph = lambda **kw: calls.append(kw) or {"status": "text_ready_for_production"}
    monkeypatch.setitem(sys.modules, module.__name__, module)
    assert cli.main(["execute", "--run-dir", "new", "--engine", "langgraph"]) == 0
    capsys.readouterr()
    assert calls == [{"run_dir": Path("new")}] and not runtime.calls


@pytest.mark.parametrize("command", ["prepare", "prepare-quality-revision"])
def test_cli_brief_json_preserves_complete_requirements(command, tmp_path, runtime, capsys):
    brief = {"source_kind": "original", "target_duration_seconds": 120, "max_duration_seconds": 135,
             "requirements": ["目光有具体对象", "对白动作自然交互"]}
    path = tmp_path / "brief.json"
    path.write_text(json.dumps(brief, ensure_ascii=False), encoding="utf-8")
    argv = [command, "--run-dir", str(tmp_path / "new"), "--brief-json", str(path)]
    if command == "prepare":
        argv += ["--source-kind", "original", "--source-path", "source.txt", "--target-duration-seconds", "120"]
    else:
        argv += ["--parent-run", "old"]
    assert cli.main(argv) == 0
    capsys.readouterr()
    assert runtime.calls[0][2]["brief"] == brief


@pytest.mark.parametrize("body", ['[]', 'null', '{"target":NaN}', '{"a":1,"a":2}', '{"nested":{"a":1,"a":2}}'])
def test_cli_brief_json_is_strict(body, tmp_path, runtime, capsys):
    path = tmp_path / "brief.json"
    path.write_text(body, encoding="utf-8")
    assert cli.main(["prepare-quality-revision", "--run-dir", "new", "--parent-run", "old", "--brief-json", str(path)]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "entry_rejected"
    assert not runtime.calls


@pytest.mark.parametrize("brief", [{"target_duration_seconds": 121}, {"source_kind": "novel"}])
def test_cli_brief_conflicts_do_not_dispatch(brief, tmp_path, runtime, capsys):
    path = tmp_path / "brief.json"
    path.write_text(json.dumps(brief), encoding="utf-8")
    assert cli.main(["prepare", "--run-dir", "new", "--source-kind", "original", "--source-path", "s",
                     "--target-duration-seconds", "120", "--brief-json", str(path)]) == 1
    assert "冲突" in json.loads(capsys.readouterr().out)["error"]
    assert not runtime.calls


@pytest.mark.parametrize("status", sorted(cli.FAILURE_STATUSES))
def test_failure_stops_once_no_retry(status, runtime, capsys):
    runtime.report["status"] = status
    assert cli.main(["execute", "--run-dir", "new"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == status
    assert len(runtime.calls) == 1


@pytest.mark.parametrize("kind", ["novel", "original"])
def test_web_prepare_freezes_same_standard_without_execute(kind, tmp_path, runtime, monkeypatch):
    calls = _spawns(monkeypatch)
    panel.prepare_source(tmp_path / "run", source_kind=kind, source_path=tmp_path / "source.txt",
                         title="跨故事", scope="全文", target_duration_seconds=120)
    assert len(runtime.calls) == 1 and runtime.calls[0][0] == "prepare"
    assert runtime.calls[0][2]["source_kind"] == kind
    assert runtime.calls[0][2]["brief"] == {"target_duration_seconds": 120}
    assert "registry_dir" not in runtime.calls[0][2] and calls == []


def test_web_one_hidden_v9_background_job(tmp_path, runtime, monkeypatch):
    calls = _spawns(monkeypatch)
    result = panel.launch_text(tmp_path)
    assert result["automatic_media_submit"] is False and result["automatic_retry"] is False
    assert Path(calls[0][1]).name == "run_novel_agent_v9.py"
    assert [x[0] for x in runtime.calls] == ["inspect", "inspect", "preview"]
    with pytest.raises(RuntimeError, match="已经提交"):
        panel.launch_text(tmp_path)
    assert len(calls) == 1


@pytest.mark.parametrize("change", [{"status": "director_revision_exhausted"}, {"dispatch_blocked": True},
                                    {"pending_call": {"id": "original"}}, {"blockers": ["stop"]}])
def test_web_stops_never_start_subprocess(change, tmp_path, runtime, monkeypatch):
    calls = _spawns(monkeypatch)
    runtime.report.update(change)
    with pytest.raises(RuntimeError):
        panel.launch_text(tmp_path)
    assert calls == [] and not (tmp_path / ".web_launch.lock").exists()


def test_pending_race_checked_after_lock(tmp_path, runtime, monkeypatch):
    calls = _spawns(monkeypatch)
    answers = iter([runtime.report, {**runtime.report, "pending_call": {"id": "unknown"}}])
    runtime.inspect = lambda *_: next(answers)
    with pytest.raises(RuntimeError, match="未决"):
        panel.launch_text(tmp_path)
    assert not calls and not (tmp_path / ".web_launch.lock").exists()


def test_preview_refusal_cannot_spawn(tmp_path, runtime, monkeypatch):
    calls = _spawns(monkeypatch)
    runtime.preview = lambda *_: {"blockers": ["request_not_reviewed"]}
    with pytest.raises(RuntimeError, match="预览"):
        panel.launch_text(tmp_path)
    assert not calls


def test_failed_receipt_after_spawn_keeps_guard(tmp_path, runtime, monkeypatch):
    calls = _spawns(monkeypatch)
    original = Path.open
    def fail(path, *args, **kwargs):
        if path.name == "LAST_LAUNCH.json":
            raise OSError("disk failure")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", fail)
    with pytest.raises(OSError):
        panel.launch_text(tmp_path)
    assert len(calls) == 1 and (tmp_path / ".web_launch.lock").exists()


def test_legacy_v8_web_view_is_read_only(tmp_path, runtime, monkeypatch):
    _binding(tmp_path, "novel_agent_pipeline/v8")
    calls = _spawns(monkeypatch)
    with pytest.raises(RuntimeError, match="历史版本"):
        panel.launch_text(tmp_path)
    assert not calls and not runtime.calls


@pytest.mark.parametrize("operation", ["prepare", "launch", "revision", "recovery"])
def test_viewer_cannot_mutate(operation, tmp_path, runtime, monkeypatch):
    monkeypatch.setattr(panel, "get_current_role", lambda: "viewer")
    with pytest.raises(PermissionError):
        if operation == "prepare":
            panel.prepare_source(tmp_path, source_kind="original", source_path="brief.txt")
        elif operation == "launch":
            panel.launch_text(tmp_path)
        elif operation == "revision":
            panel.prepare_quality_revision(tmp_path, parent_run="old")
        else:
            panel.recover_projection(tmp_path)
    assert not runtime.calls


def test_legacy_creative_browse_never_imports_or_dispatches_old_runner(tmp_path, monkeypatch):
    monkeypatch.setattr(panel, 'ROOT', tmp_path)
    run = tmp_path / 'data/creative_workflows/fixture'
    run.mkdir(parents=True)
    (run / "state.json").write_text('{"status":"needs_attention","calls_started":12}', encoding="utf-8")
    (run / "SCREENPLAY.md").write_text("历史完整稿", encoding="utf-8")
    monkeypatch.setattr(panel, "_spawn", lambda *_: pytest.fail("read-only"))
    before = {p.name: p.read_bytes() for p in run.iterdir()}
    report = panel.legacy_creative_records(run)
    assert report["status"] == "legacy_read_only" and report["dispatch_blocked"]
    assert report["original_records"]["state.json"]["calls_started"] == 12
    assert run / "SCREENPLAY.md" in report["artifact_files"]
    assert before == {p.name: p.read_bytes() for p in run.iterdir()}


@pytest.mark.parametrize("module_name", ["novel_video_trial_v1", "novel_video_location_variant_v1"])
def test_old_single_trial_media_entry_rejects_v9_before_compilation(module_name, tmp_path, monkeypatch):
    import importlib
    module = importlib.import_module("src.content_factory." + module_name)
    (tmp_path / "BINDING.json").write_text(json.dumps({"schema": panel.VERSION, "source": {}}), encoding="utf-8")
    (tmp_path / "state.json").write_text(json.dumps({"status": "text_ready_for_production", "stage": "complete",
        "calls_started": 0, "known_reported_tokens": 0, "reported_tokens": 0, "pending_call": None}), encoding="utf-8")
    monkeypatch.setattr(module, "compile_prompt", lambda *_: pytest.fail("must not apply historical performance[0] compiler"))
    monkeypatch.setattr(module.seedance, "SeedanceClient", lambda *_a, **_k: pytest.fail("no provider construction"))
    with pytest.raises(ValueError, match="尚未通过"):
        module._source(tmp_path)


def test_app_new_task_routes_use_natural_v10_and_v9_history_is_separate():
    path = panel.ROOT / "src/web/app.py"
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    for name, imported, module in (("page_novel_adaptation", "page_novel_adaptation", "src.web.natural_director_panel_v10"),
                           ("page_creative_workflow", "page_original_story", "src.web.natural_director_panel_v10"),
                           ("page_legacy_creative_records", "page_legacy_creative_records", "src.web.novel_agent_panel_v9")):
        imports = [n for n in ast.walk(functions[name]) if isinstance(n, ast.ImportFrom)]
        assert [(n.module, n.names[0].name) for n in imports] == [(module, imported)]
    source = path.read_text(encoding="utf-8-sig")
    assert '"creative-history"' in source and '"creative-workflow"' in source
    assert "from src.web.creative_workflow_dashboard import" not in source


def _app(monkeypatch, tmp_path, runtime, kind="novel", role="editor"):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setattr(panel, "get_current_role", lambda: role)
    monkeypatch.setattr(panel, "discover_sources", lambda *_: [])
    runtime.report["status"] = "unprepared"
    app = AppTest.from_string(f"from src.web.novel_agent_panel_v9 import page_story_workflow\npage_story_workflow('{kind}')")
    app.session_state["novel_agent_v9_" + kind + "_run"] = str(tmp_path / "run")
    app.session_state["novel_agent_v9_" + kind + "_acquisition"] = str(tmp_path / "acquire")
    return app.run()


@pytest.mark.parametrize("kind,title", [("novel", "小说改编"), ("original", "原创剧情")])
def test_new_pages_render_without_low_level_bypass(kind, title, tmp_path, runtime, monkeypatch):
    app = _app(monkeypatch, tmp_path, runtime, kind)
    assert not app.exception and app.title[0].value == title
    assert all("hash" not in x.label.lower() and "schema" not in x.label.lower() and "registry" not in x.label.lower()
               for x in app.text_input)
    assert any("最终实际提示词" in x.value for x in app.caption)
    assert not any(x[0] == "execute" for x in runtime.calls)


@pytest.mark.parametrize("kind", ["novel", "original"])
def test_page_prepare_and_launch_are_separate(kind, tmp_path, runtime, monkeypatch):
    app = _app(monkeypatch, tmp_path, runtime, kind)
    prefix = "novel_agent_v9_" + kind
    next(x for x in app.text_input if x.key == prefix + "_source").set_value(str(tmp_path / "source.txt"))
    next(x for x in app.text_input if x.key == prefix + "_scope").set_value("完整来源")
    next(x for x in app.button if "准备与冻结" in x.label).click().run()
    assert not app.exception
    prepares = [x for x in runtime.calls if x[0] == "prepare"]
    assert len(prepares) == 1 and prepares[0][2]["source_kind"] == kind
    assert not any(x[0] == "execute" for x in runtime.calls)


def test_page_viewer_has_no_mutations(tmp_path, runtime, monkeypatch):
    app = _app(monkeypatch, tmp_path, runtime, "original", "viewer")
    assert not app.exception
    mutation = [x for x in app.button if "准备" in x.label]
    assert mutation and all(x.disabled for x in mutation)


FIXTURES = Path(__file__).parent / "fixtures/narrative_quality_v8"


def test_cross_story_fixture_freeze_is_intact_and_not_claimed_semantically_passed():
    freeze = json.loads((FIXTURES / "FROZEN_MANIFEST.json").read_text(encoding="utf-8"))
    assert freeze["before_live_quality_revision"] and freeze["semantic_acceptance"] == "not_run"
    for name, expected in freeze["files_sha256"].items():
        assert hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest() == expected
    assert len(freeze["holdout_sources"]) == 2
    for name in freeze["holdout_sources"]:
        source = (FIXTURES / name).read_text(encoding="utf-8")
        assert len(source) > 800 and "周明" not in source and "周禾" not in source


def test_examples_cover_positive_and_negative_interaction_types_without_word_count_gate():
    fixture = json.loads((FIXTURES / "cases.json").read_text(encoding="utf-8"))
    assert {x["id"] for x in fixture["cases"]} == {
        "family_two_people", "office_three_people", "walking_prop_transfer",
        "motivated_silence_and_avoidance", "phone_offscreen_voice"}
    for case in fixture["cases"]:
        assert case["positive"] and case["negative"] and len(case["review_expectations"]) == 4
    assert "not a deterministic semantic classifier" in fixture["purpose"]
