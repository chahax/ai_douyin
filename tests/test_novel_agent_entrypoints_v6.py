"""Offline entrypoint acceptance, with provider and subprocess boundaries replaced."""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

from scripts import run_novel_agent_v6 as cli
from src.web import novel_agent_panel_v6 as panel


@pytest.fixture
def runtimes(monkeypatch):
    import src.content_factory as package
    result = {}
    names = {"v6": "novel_agent_pipeline_v6", "v1": "novel_adaptation_pipeline_v1",
             "v2": "novel_adaptation_production_v2", "v3": "novel_plaintext_pipeline_v3",
             "v5": "novel_agent_pipeline_v5"}
    for version, name in names.items():
        module = ModuleType("src.content_factory." + name)
        module.calls = []
        module.report = {"status": "prepared", "dispatch_blocked": False, "blockers": [],
                         "state": {"stage": "writer", "pending_call": None},
                         "human_approved": False, "automatic_media_submit": False}
        for method in ("prepare", "inspect", "preview", "execute", "prepare_continuation", "recover_projection"):
            def call(*args, _method=method, _module=module, **kwargs):
                _module.calls.append((_method, args, kwargs))
                return dict(_module.report)
            setattr(module, method, call)
        monkeypatch.setitem(sys.modules, module.__name__, module)
        monkeypatch.setattr(package, name, module, raising=False)
        result[version] = module
    return result


def binding(run, version="v6"):
    schemas = {"v6": panel.VERSION, "v1": "novel_adaptation_pipeline/v1",
               "v2": "novel_adaptation_production/v2", "v3": "novel_plaintext_pipeline/v3",
               "v4": "novel_logic_workflow/v4", "v5": "novel_agent_pipeline/v5"}
    run.mkdir(parents=True, exist_ok=True)
    (run / "BINDING.json").write_text(json.dumps({"schema": schemas[version]}), encoding="utf-8")


@pytest.mark.parametrize("command", ["prepare", "preview", "inspect", "execute"])
def test_cli_only_requested_v6_action(command, tmp_path, runtimes, capsys):
    argv = [command, "--run-dir", str(tmp_path / "run")]
    if command == "prepare":
        argv += ["--source-path", str(tmp_path / "chapter.txt"), "--scope", "第一章"]
    assert cli.main(argv) == 0
    assert json.loads(capsys.readouterr().out)["automatic_media_submit"] is False
    assert len(runtimes["v6"].calls) == 1
    name, args, kwargs = runtimes["v6"].calls[0]
    assert name == command and args == () and kwargs["run_dir"] == tmp_path / "run"
    if command == "prepare":
        assert (kwargs["max_calls"], kwargs["max_total_tokens"], kwargs["max_revisions"]) == (20, 500000, 2)
        assert "saved_book_metadata" not in kwargs
    assert all(not module.calls for version, module in runtimes.items() if version != "v6")


def test_cli_source_choices_exclusive():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["prepare", "--run-dir", "run", "--source-path", "s",
                                        "--saved-book-metadata", "meta.json"])


def test_cli_continuation_only_forwards_original_and_new_run(runtimes, capsys):
    assert cli.main(["prepare-continuation", "--run-dir", "new", "--parent-run", "original"]) == 0
    capsys.readouterr()
    assert runtimes["v6"].calls == [
        ("prepare_continuation", (), {"run_dir": Path("new"), "parent_run": Path("original")})]
    assert not runtimes["v5"].calls


@pytest.mark.parametrize("override", ["--max-calls", "--max-total-tokens", "--max-revisions"])
def test_cli_continuation_has_no_budget_override(override):
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["prepare-continuation", "--run-dir", "new", "--parent-run",
                                        "original", override, "100"])


def test_cli_projection_recovery_is_local_action(runtimes, capsys):
    assert cli.main(["recover-projection", "--run-dir", "original"]) == 0
    capsys.readouterr()
    assert runtimes["v6"].calls == [("recover_projection", (), {"run_dir": Path("original")})]


def test_cli_duration_is_frozen_into_brief(runtimes, capsys):
    assert cli.main(["prepare", "--run-dir", "run", "--source-path", "chapter.txt",
                     "--target-duration-seconds", "120"]) == 0
    capsys.readouterr()
    kwargs = runtimes["v6"].calls[0][2]
    assert kwargs["brief"] == {"target_duration_seconds": 120}
    assert "target_duration_seconds" not in kwargs


@pytest.mark.parametrize("target", ["0", "15", "59", "901", "1800"])
def test_cli_duration_outside_range_no_dispatch(target, runtimes, capsys):
    assert cli.main(["prepare", "--run-dir", "run", "--source-path", "chapter.txt",
                     "--target-duration-seconds", target]) == 1
    assert "目标时长" in json.loads(capsys.readouterr().out)["error"]
    assert not runtimes["v6"].calls


@pytest.mark.parametrize("target", ["60", "900"])
def test_cli_duration_inclusive_boundaries_match_runtime(target, runtimes, capsys):
    assert cli.main(["prepare", "--run-dir", "run", "--source-path", "chapter.txt",
                     "--target-duration-seconds", target]) == 0
    capsys.readouterr()
    assert runtimes["v6"].calls[0][2]["brief"] == {"target_duration_seconds": int(target)}


def test_cli_saved_metadata_uses_acquisition_bridge(tmp_path, runtimes, monkeypatch, capsys):
    from src.content_factory import novel_adaptation_acquisition_v1 as acquisition
    calls = []
    monkeypatch.setattr(acquisition, "import_saved_book", lambda path, output:
                        calls.append((path, output)) or {"receipt_path": str(tmp_path / "RECEIPT.json")})
    assert cli.main(["prepare", "--run-dir", str(tmp_path / "run"),
                     "--saved-book-metadata", str(tmp_path / "meta.json")]) == 0
    capsys.readouterr()
    assert len(calls) == 1 and calls[0][0] == tmp_path / "meta.json"
    assert not calls[0][1].is_relative_to(tmp_path / "run")
    assert runtimes["v6"].calls[0][2]["acquisition_receipt"] == tmp_path / "RECEIPT.json"


def test_cli_metadata_wont_write_bridge_for_frozen_run(tmp_path, runtimes, monkeypatch, capsys):
    from src.content_factory import novel_adaptation_acquisition_v1 as acquisition
    binding(tmp_path, "v3")
    before = (tmp_path / "BINDING.json").read_bytes()
    monkeypatch.setattr(acquisition, "import_saved_book", lambda *args: pytest.fail("must not import"))
    assert cli.main(["prepare", "--run-dir", str(tmp_path), "--saved-book-metadata", "meta.json"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "entry_rejected"
    assert not runtimes["v6"].calls
    assert (tmp_path / "BINDING.json").read_bytes() == before


@pytest.mark.parametrize("command", ["prepare", "preview", "inspect", "execute"])
def test_cli_rejects_legacy_before_runtime_call(command, tmp_path, runtimes, capsys):
    binding(tmp_path, "v3")
    before = (tmp_path / "BINDING.json").read_bytes()
    argv = [command, "--run-dir", str(tmp_path)]
    if command == "prepare":
        argv += ["--source-path", "chapter.txt"]
    assert cli.main(argv) == 1
    assert "不能迁移" in json.loads(capsys.readouterr().out)["error"]
    assert not runtimes["v6"].calls and (tmp_path / "BINDING.json").read_bytes() == before


def test_cli_fetch_explicit_once(tmp_path, runtimes, monkeypatch, capsys):
    from src.content_factory import novel_adaptation_acquisition_v1 as acquisition
    calls = []
    monkeypatch.setattr(acquisition, "fetch_source", lambda **kwargs:
                        calls.append(kwargs) or {"status": "acquisition_failed"})
    assert cli.main(["fetch", "--output-dir", str(tmp_path), "--book-name", "原书"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "acquisition_failed"
    assert calls == [{"output_dir": tmp_path, "book_name": "原书", "book_id": "", "chapters": 1}]
    assert all(not module.calls for module in runtimes.values())


@pytest.mark.parametrize("status", sorted(cli.FAILURE_STATUSES))
def test_cli_failure_exit_and_no_second_request(status, runtimes, capsys):
    runtimes["v6"].report["status"] = status
    assert cli.main(["execute", "--run-dir", "run"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == status
    assert len(runtimes["v6"].calls) == 1


def test_cli_exception_is_saved_no_retry(runtimes, capsys):
    calls = []
    def fail(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("结果未知")
    runtimes["v6"].execute = fail
    assert cli.main(["execute", "--run-dir", "run"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["automatic_retry"] is False and report["automatic_media_submit"] is False
    assert len(calls) == 1


def test_cli_langgraph_uses_same_runtime_graph_adapter(runtimes, monkeypatch, capsys):
    graph = ModuleType("src.content_factory.novel_agent_graph_v6")
    calls = []
    graph.execute_graph = lambda **kwargs: calls.append(kwargs) or {"status": "text_ready_for_production"}
    monkeypatch.setitem(sys.modules, graph.__name__, graph)
    assert cli.main(["execute", "--run-dir", "original", "--engine", "langgraph"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "text_ready_for_production"
    assert calls == [{"run_dir": Path("original")}]
    assert not runtimes["v6"].calls


def test_cli_native_is_default_and_not_forwarded_to_runtime(runtimes, capsys):
    assert cli.main(["execute", "--run-dir", "run", "--engine", "native"]) == 0
    capsys.readouterr()
    assert runtimes["v6"].calls[0][2] == {"run_dir": Path("run")}


@pytest.mark.parametrize("version", ["v1", "v2", "v3", "v5", "v6"])
def test_runtime_routes_frozen_binding_unchanged(version, tmp_path, runtimes):
    binding(tmp_path, version)
    before = (tmp_path / "BINDING.json").read_bytes()
    module, legacy = panel._runtime(tmp_path)
    assert module is runtimes[version] and legacy is (version != "v6")
    assert (tmp_path / "BINDING.json").read_bytes() == before
    assert all(not module.calls for module in runtimes.values())


def test_v4_diagnostic_is_read_only_without_dispatch_api(tmp_path, runtimes):
    binding(tmp_path, "v4")
    module, legacy = panel._runtime(tmp_path)
    assert legacy and not hasattr(module, "execute")
    assert module.inspect(tmp_path)["status"] == "legacy_read_only"
    assert module.preview(tmp_path)["dispatch_blocked"] is True


@pytest.mark.parametrize("value", ["[]", "{}", '{"schema":"future/v8"}',
                                  '{"schema":"novel_agent_pipeline/v6","schema":"novel_plaintext_pipeline/v3"}'])
def test_unknown_or_ambiguous_binding_fails_closed(value, tmp_path, runtimes):
    (tmp_path / "BINDING.json").write_text(value, encoding="utf-8")
    with pytest.raises(ValueError):
        panel._runtime(tmp_path)
    assert all(not module.calls for module in runtimes.values())


def _spawns(monkeypatch):
    monkeypatch.setattr(panel, "get_current_role", lambda: "editor")
    calls = []
    def popen(argv, **kwargs):
        assert kwargs["creationflags"] == getattr(panel.subprocess, "CREATE_NO_WINDOW", 0)
        assert kwargs["stdin"] == panel.subprocess.DEVNULL
        assert kwargs["cwd"] == panel.ROOT
        calls.append(argv)
        return SimpleNamespace(pid=456)
    monkeypatch.setattr(panel.subprocess, "Popen", popen)
    return calls


def test_launch_unique_hidden_background_process(tmp_path, runtimes, monkeypatch):
    calls = _spawns(monkeypatch)
    receipt = panel.launch_text(tmp_path)
    assert receipt["pid"] == 456 and receipt["automatic_retry"] is False
    assert Path(calls[0][1]).name == "run_novel_agent_v6.py"
    assert [row[0] for row in runtimes["v6"].calls] == ["inspect", "inspect", "preview"]
    with pytest.raises(RuntimeError, match="已经提交"):
        panel.launch_text(tmp_path)
    assert len(calls) == 1 and (tmp_path / ".web_launch.lock").is_file()


@pytest.mark.parametrize("version", ["v1", "v2", "v3", "v4", "v5"])
def test_legacy_never_spawns_or_migrates(version, tmp_path, runtimes, monkeypatch):
    binding(tmp_path, version)
    before = (tmp_path / "BINDING.json").read_bytes()
    calls = _spawns(monkeypatch)
    with pytest.raises(RuntimeError, match="历史版本"):
        panel.launch_text(tmp_path)
    assert calls == [] and all(not module.calls for module in runtimes.values())
    assert (tmp_path / "BINDING.json").read_bytes() == before
    assert not (tmp_path / ".web_launch.lock").exists()


@pytest.mark.parametrize("change", [{"status": "content_revision_exhausted"},
                                    {"dispatch_blocked": True}, {"blockers": ["old_stop"]},
                                    {"pending_call": {"id": "original"}},
                                    {"state": {"pending_call": {"id": "original"}}}])
def test_stops_and_unknown_claims_cannot_respawn(change, tmp_path, runtimes, monkeypatch):
    calls = _spawns(monkeypatch)
    runtimes["v6"].report.update(change)
    with pytest.raises(RuntimeError):
        panel.launch_text(tmp_path)
    assert calls == [] and not (tmp_path / ".web_launch.lock").exists()


def test_pending_appearing_after_lock_blocks_launch(tmp_path, runtimes, monkeypatch):
    calls = _spawns(monkeypatch)
    answers = iter([runtimes["v6"].report,
                    {**runtimes["v6"].report, "pending_call": {"id": "raced"}}])
    runtimes["v6"].inspect = lambda *_: next(answers)
    with pytest.raises(RuntimeError, match="未决"):
        panel.launch_text(tmp_path)
    assert calls == [] and not (tmp_path / ".web_launch.lock").exists()


def test_preview_stop_blocks_before_process(tmp_path, runtimes, monkeypatch):
    calls = _spawns(monkeypatch)
    runtimes["v6"].preview = lambda *_: {"dispatch_blocked": True}
    with pytest.raises(RuntimeError, match="预览"):
        panel.launch_text(tmp_path)
    assert calls == [] and not (tmp_path / ".web_launch.lock").exists()


def test_lock_loser_does_not_preview_or_spawn(tmp_path, runtimes, monkeypatch):
    calls = _spawns(monkeypatch)
    (tmp_path / ".web_launch.lock").write_text("existing", encoding="utf-8")
    with pytest.raises(RuntimeError, match="已经提交"):
        panel.launch_text(tmp_path)
    assert calls == [] and [row[0] for row in runtimes["v6"].calls] == ["inspect"]
    assert (tmp_path / ".web_launch.lock").read_text() == "existing"


def test_pre_spawn_error_allows_safe_correction(tmp_path, runtimes, monkeypatch):
    _spawns(monkeypatch)
    monkeypatch.setattr(panel.subprocess, "Popen", lambda *_args, **_kwargs:
                        (_ for _ in ()).throw(OSError("cannot start")))
    with pytest.raises(OSError):
        panel.launch_text(tmp_path)
    assert not (tmp_path / ".web_launch.lock").exists()
    assert not (tmp_path / "LAST_LAUNCH.json").exists()


def test_receipt_failure_after_spawn_keeps_duplicate_guard(tmp_path, runtimes, monkeypatch):
    _spawns(monkeypatch)
    original = Path.open
    def failing(path, *args, **kwargs):
        if path.name == "LAST_LAUNCH.json":
            raise OSError("receipt disk failure")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", failing)
    with pytest.raises(OSError):
        panel.launch_text(tmp_path)
    assert (tmp_path / ".web_launch.lock").exists()


@pytest.mark.parametrize("action", ["text", "acquire"])
def test_viewer_cannot_mutate(action, tmp_path, runtimes, monkeypatch):
    calls = _spawns(monkeypatch)
    monkeypatch.setattr(panel, "get_current_role", lambda: "viewer")
    with pytest.raises(PermissionError):
        if action == "text":
            panel.launch_text(tmp_path)
        else:
            panel.launch_acquisition(tmp_path / "job", book_name="原书")
    assert calls == [] and all(not module.calls for module in runtimes.values())


def test_explicit_v5_continuation_prepares_once_without_spawn(tmp_path, runtimes, monkeypatch):
    calls = _spawns(monkeypatch)
    parent = tmp_path / "original"
    binding(parent, "v5")
    before = (parent / "BINDING.json").read_bytes()
    result = panel.prepare_continuation(tmp_path / "new", parent_run=parent)
    assert result["status"] == "prepared" and calls == []
    assert runtimes["v6"].calls == [("prepare_continuation", (tmp_path / "new",), {"parent_run": parent})]
    assert (parent / "BINDING.json").read_bytes() == before
    assert not runtimes["v5"].calls


@pytest.mark.parametrize("version", ["v1", "v2", "v3", "v4", "v6"])
def test_continuation_does_not_accept_unrelated_old_tasks(version, tmp_path, runtimes, monkeypatch):
    calls = _spawns(monkeypatch)
    parent = tmp_path / "original"
    binding(parent, version)
    with pytest.raises(ValueError, match="只接受"):
        panel.prepare_continuation(tmp_path / "new", parent_run=parent)
    assert not runtimes["v6"].calls and calls == []


def test_continuation_cannot_overwrite_old_run(tmp_path, runtimes, monkeypatch):
    _spawns(monkeypatch)
    parent, target = tmp_path / "parent", tmp_path / "target"
    binding(parent, "v5")
    binding(target, "v3")
    with pytest.raises(RuntimeError, match="不能覆盖"):
        panel.prepare_continuation(target, parent_run=parent)
    assert not runtimes["v6"].calls


@pytest.mark.parametrize("operation", ["continuation", "projection"])
def test_viewer_cannot_prepare_continuation_or_recover(operation, tmp_path, runtimes, monkeypatch):
    monkeypatch.setattr(panel, "get_current_role", lambda: "viewer")
    with pytest.raises(PermissionError):
        if operation == "continuation":
            panel.prepare_continuation(tmp_path / "new", parent_run=tmp_path / "original")
        else:
            panel.recover_projection(tmp_path)
    assert not runtimes["v6"].calls


def test_projection_recovery_does_not_grant_pending_dispatch(tmp_path, runtimes, monkeypatch):
    calls = _spawns(monkeypatch)
    module = runtimes["v6"]
    module.report.update(status="evidence_invalid", projection_recovery_available=True,
                         dispatch_blocked=True, pending_call={"id": "original-unknown"})
    with pytest.raises(RuntimeError):
        panel.launch_text(tmp_path)
    result = panel.recover_projection(tmp_path)
    assert result["pending_call"]["id"] == "original-unknown"
    assert calls == []
    assert [row[0] for row in module.calls].count("recover_projection") == 1
    assert not any(row[0] == "execute" for row in module.calls)


def test_projection_recovery_requires_verified_flag(tmp_path, runtimes, monkeypatch):
    calls = _spawns(monkeypatch)
    runtimes["v6"].report.update(status="evidence_invalid", dispatch_blocked=True)
    with pytest.raises(RuntimeError, match="没有已核实"):
        panel.recover_projection(tmp_path)
    assert calls == [] and not any(row[0] == "recover_projection" for row in runtimes["v6"].calls)


def test_legacy_projection_is_never_recovered_through_v6(tmp_path, runtimes, monkeypatch):
    _spawns(monkeypatch)
    binding(tmp_path, "v5")
    runtimes["v5"].report["projection_recovery_available"] = True
    with pytest.raises(RuntimeError, match="历史冻结"):
        panel.recover_projection(tmp_path)
    assert not runtimes["v5"].calls and not runtimes["v6"].calls


def test_acquisition_one_attempt_and_receipt(tmp_path, runtimes, monkeypatch):
    calls = _spawns(monkeypatch)
    job = tmp_path / "job"
    result = panel.launch_acquisition(job, book_name="原书", book_id="123", chapters=2)
    assert result["receipt_path"] == str(job / "source/RECEIPT.json")
    assert "fetch" in calls[0] and calls[0][-2:] == ["--book-id", "123"]
    with pytest.raises(FileExistsError):
        panel.launch_acquisition(job, book_name="原书")
    assert len(calls) == 1


def test_artifacts_include_failed_drafts_and_handoff_exclude_native_reasoning(tmp_path):
    for name in ("DRAFT_001.md", "SCREENPLAY.md", "SCENE_LEDGER_002.json", "REVIEW_002.json",
                 "ADJUDICATION_003.json", "GATE_004.json", "DIRECTOR_005.md",
                 "DIRECTOR_REVIEW_006.json", "PRODUCTION_HANDOFF.json", "NATIVE_002.json",
                 "CREDENTIALS.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    names = {path.name for path in panel.artifact_files(tmp_path)}
    assert "DRAFT_001.md" in names and "PRODUCTION_HANDOFF.json" in names
    assert "NATIVE_002.json" not in names and "CREDENTIALS.json" not in names
    assert len(names) == 9


def test_main_navigation_points_to_new_page_only():
    tree = ast.parse((panel.ROOT / "src/web/app.py").read_text(encoding="utf-8-sig"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "page_novel_adaptation")
    imports = [node.module for node in ast.walk(function) if isinstance(node, ast.ImportFrom)]
    # The current default is v7; v6 remains independently covered above.
    assert imports == ["src.web.novel_agent_panel_v7"]


def _app(monkeypatch, tmp_path, runtimes, role="editor"):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setattr(panel, "get_current_role", lambda: role)
    monkeypatch.setattr(panel, "discover_sources", lambda *_: [])
    runtimes["v6"].report["status"] = "unprepared"
    app = AppTest.from_string("from src.web.novel_agent_panel_v6 import page_novel_adaptation\npage_novel_adaptation()")
    app.session_state["novel_agent_v6_run"] = str(tmp_path / "run")
    app.session_state["novel_agent_v6_acquisition"] = str(tmp_path / "acquire")
    return app.run()


def test_page_renders_without_schema_or_hash_inputs(tmp_path, runtimes, monkeypatch):
    app = _app(monkeypatch, tmp_path, runtimes)
    assert not app.exception
    assert app.title[0].value == "小说改编"
    assert all("hash" not in item.label.lower() and "schema" not in item.label.lower()
               and "哈希" not in item.label for item in app.text_input)
    assert any("导演" in item.value for item in app.caption)
    assert not any(row[0] == "execute" for row in runtimes["v6"].calls)


def test_page_prepare_and_launch_are_separate_actions(tmp_path, runtimes, monkeypatch):
    app = _app(monkeypatch, tmp_path, runtimes)
    next(item for item in app.text_input if item.key == "novel_agent_v6_source").set_value(str(tmp_path / "chapter.txt"))
    next(item for item in app.text_input if item.key == "novel_agent_v6_scope").set_value("第一章")
    next(item for item in app.button if "准备与冻结" in item.label).click().run()
    assert not app.exception
    prepares = [row for row in runtimes["v6"].calls if row[0] == "prepare"]
    assert len(prepares) == 1 and prepares[0][2]["scope"] == "第一章"
    assert prepares[0][2]["brief"] == {"target_duration_seconds": 180}
    assert not any(row[0] == "execute" for row in runtimes["v6"].calls)


def test_page_viewer_buttons_disabled(tmp_path, runtimes, monkeypatch):
    app = _app(monkeypatch, tmp_path, runtimes, role="viewer")
    assert not app.exception
    buttons = [item for item in app.button if item.label in {"获取正文", "准备与冻结输入（不调用模型）"}]
    assert buttons and all(item.disabled for item in buttons)


def test_page_continuation_uses_original_without_new_budget_fields(tmp_path, runtimes, monkeypatch):
    parent = tmp_path / "parent"
    binding(parent, "v5")
    app = _app(monkeypatch, tmp_path, runtimes)
    next(item for item in app.text_input if item.key == "novel_agent_v6_parent").set_value(str(parent)).run()
    next(item for item in app.button if item.label == "从原 v5 停点准备 v6（不调用模型）").click().run()
    assert not app.exception
    calls = [row for row in runtimes["v6"].calls if row[0] == "prepare_continuation"]
    assert calls == [("prepare_continuation", (tmp_path / "run",), {"parent_run": parent})]
    assert not any(row[0] == "execute" for row in runtimes["v6"].calls)


def test_page_legacy_failed_text_shows_original_not_launch(tmp_path, runtimes, monkeypatch):
    run = tmp_path / "run"
    binding(run, "v3")
    (run / "DRAFT_005.md").write_text("原完整稿：尚未通过", encoding="utf-8")
    runtimes["v3"].report["status"] = "content_revision_exhausted"
    app = _app(monkeypatch, tmp_path, runtimes)
    assert not app.exception
    assert any("历史冻结" in item.value for item in app.info)
    assert any("原完整稿：尚未通过" in item.value for item in app.markdown)
    launch = next(item for item in app.button if item.label == "后台运行至导演制作交接")
    assert launch.disabled
    assert not any(row[0] == "execute" for module in runtimes.values() for row in module.calls)


def test_actual_prepare_preview_inspect_wire_source_budget_and_brief(tmp_path, monkeypatch, capsys):
    """Exercise the real runtime locally; never register in the production catalog."""
    from src.content_factory import novel_agent_pipeline_v6 as actual
    monkeypatch.setattr(actual, "CANONICAL_REGISTRY", tmp_path / "registry")
    monkeypatch.setattr(actual, "CreativeRoleClients", lambda:
                        pytest.fail("prepare/preview/inspect must not construct provider clients"))
    chapter = tmp_path / "chapter.txt"
    chapter.write_text("入口离线专用故事。妈妈把信放到桌上，女儿读完后合上信。", encoding="utf-8")
    run = tmp_path / "run"
    assert cli.main(["prepare", "--run-dir", str(run), "--source-path", str(chapter),
                     "--title", "入口离线样例", "--scope", "第一章", "--target-duration-seconds", "120"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "prepared" and report["calls_started"] == 0
    binding_value = json.loads((run / "BINDING.json").read_text(encoding="utf-8"))
    assert binding_value["schema"] == panel.VERSION
    assert binding_value["brief"] == {"target_duration_seconds": 120}
    assert binding_value["source"]["text"] == chapter.read_text(encoding="utf-8")
    original = (run / "BINDING.json").read_bytes()
    for command in ("preview", "inspect"):
        assert cli.main([command, "--run-dir", str(run)]) == 0
        view = json.loads(capsys.readouterr().out)
        assert view["calls_started"] == 0 and view["pending_call"] is None
    assert (run / "BINDING.json").read_bytes() == original
    module, legacy = panel._runtime(run)
    assert module is actual and legacy is False


def test_actual_continuation_cli_preserves_parent_and_remaining_capacity(tmp_path, monkeypatch, capsys):
    from src.content_factory import novel_agent_pipeline_v6 as actual
    from src.content_factory import novel_agent_pipeline_v5 as old
    spec = importlib.util.spec_from_file_location("entry_v6_fixtures", Path(__file__).with_name("test_novel_agent_pipeline_v6.py"))
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    canonical = tmp_path / "registry"
    monkeypatch.setattr(actual, "CANONICAL_REGISTRY", canonical)
    monkeypatch.setattr(old, "CANONICAL_REGISTRY", canonical)
    monkeypatch.setattr(actual.core, "_legacy_blocks", lambda *_args, **_kwargs: [])
    source = tmp_path / "chapter.txt"
    source.write_text("第一章\n他站在桌前，答道：我要自己决定。", encoding="utf-8")
    parent = fixtures.stopped_parent((tmp_path, source, canonical))
    before = fixtures.snapshot(parent)
    monkeypatch.setattr(actual, "CreativeRoleClients", lambda:
                        pytest.fail("local continuation must not construct provider clients"))
    child = tmp_path / "v6"
    assert cli.main(["prepare-continuation", "--run-dir", str(child), "--parent-run", str(parent)]) == 0
    view = json.loads(capsys.readouterr().out)
    assert view["stage"] == "director_full" and view["calls_started"] == 0
    assert view["combined_calls_started"] == 2
    assert cli.main(["preview", "--run-dir", str(child)]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["remaining_calls"] == 18 and preview["budget"]["max_total_tokens"] == 499800
    assert fixtures.snapshot(parent) == before
    assert not list(child.glob("REQUEST_*.json"))
    inherited = panel.inherited_draft_file(child, view)
    assert inherited == parent / "DRAFT_001.md"
    assert inherited.read_bytes() == before["DRAFT_001.md"]


def test_inherited_display_rejects_changed_original_or_outside_parent(tmp_path):
    run, parent = tmp_path / "run", tmp_path / "parent"
    run.mkdir()
    parent.mkdir()
    draft = parent / "DRAFT_001.md"
    draft.write_text("原完整创作稿", encoding="utf-8")
    evidence = {"path": str(draft), "sha256": hashlib.sha256(draft.read_bytes()).hexdigest()}
    value = {"continuation": {"parent_run": str(parent), "writer": {"file": evidence}}}
    (run / "BINDING.json").write_text(json.dumps(value), encoding="utf-8")
    report = {"schema": panel.VERSION, "status": "running"}
    assert panel.inherited_draft_file(run, report) == draft
    draft.write_text("被改过", encoding="utf-8")
    with pytest.raises(ValueError, match="内容已变"):
        panel.inherited_draft_file(run, report)
    value["continuation"]["writer"]["file"]["path"] = str(tmp_path / "DRAFT_secret.md")
    (run / "BINDING.json").write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="位置无效"):
        panel.inherited_draft_file(run, report)
