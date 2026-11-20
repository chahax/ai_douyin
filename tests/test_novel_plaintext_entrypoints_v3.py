"""Offline CLI/UI checks: fake runtimes, no provider, browser or global claims."""
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

from scripts import run_novel_plaintext_v3 as cli
from src.content_factory import novel_adaptation_acquisition_v1 as acquisition
from src.web import novel_adaptation_panel_v1 as panel


@pytest.fixture
def runtimes(monkeypatch):
    import src.content_factory as package
    result = {}
    for version, name in (("v3", "novel_plaintext_pipeline_v3"),
                          ("v1", "novel_adaptation_pipeline_v1"),
                          ("v2", "novel_adaptation_production_v2")):
        module = ModuleType("src.content_factory." + name)
        module.calls = []
        module.report = {"status": "prepared", "dispatch_blocked": False, "blockers": [],
                         "stage": "screenplay", "human_approved": False}
        for method in ("prepare", "preview", "inspect", "execute"):
            def call(*args, _method=method, _module=module, **kwargs):
                _module.calls.append((_method, args, kwargs))
                return dict(_module.report)
            setattr(module, method, call)
        monkeypatch.setitem(sys.modules, module.__name__, module)
        monkeypatch.setattr(package, name, module, raising=False)
        result[version] = module
    return result


def _binding(run, version):
    schemas = {"v1": "novel_adaptation_pipeline/v1", "v2": "novel_adaptation_production/v2",
               "v3": "novel_plaintext_pipeline/v3"}
    run.mkdir(parents=True, exist_ok=True)
    (run / "BINDING.json").write_text(json.dumps({"schema": schemas[version]}), encoding="utf-8")


@pytest.mark.parametrize("command", ["prepare", "preview", "inspect", "execute"])
def test_cli_only_dispatches_requested_v3_method(tmp_path, runtimes, capsys, command):
    argv = [command, "--run-dir", str(tmp_path / "run")]
    if command == "prepare":
        argv += ["--source-path", str(tmp_path / "source.txt"), "--scope", "第一章"]
    assert cli.main(argv) == 0
    assert json.loads(capsys.readouterr().out)["human_approved"] is False
    assert len(runtimes["v3"].calls) == 1
    method, args, kwargs = runtimes["v3"].calls[0]
    assert method == command and not args and kwargs["run_dir"] == tmp_path / "run"
    if command == "prepare":
        assert kwargs["scope"] == "第一章"
        assert (kwargs["max_calls"], kwargs["max_total_tokens"], kwargs["max_revisions"]) == (20, 500000, 2)
    assert not runtimes["v1"].calls and not runtimes["v2"].calls


def test_cli_authorization_is_not_combined_with_new_defaults(tmp_path, runtimes, capsys):
    assert cli.main(["prepare", "--run-dir", str(tmp_path / "run"),
                     "--authorization", str(tmp_path / "AUTH.json")]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "prepared"
    assert runtimes["v3"].calls[0][2] == {
        "run_dir": tmp_path / "run", "authorization": tmp_path / "AUTH.json"}


@pytest.mark.parametrize("option,value", [("--title", "改题"), ("--scope", "全书"),
                                           ("--book-id", "other"), ("--max-calls", "100"),
                                           ("--max-total-tokens", "1000000"), ("--max-revisions", "9")])
def test_cli_authorization_rejects_overrides(tmp_path, runtimes, capsys, option, value):
    assert cli.main(["prepare", "--run-dir", str(tmp_path / "run"), "--authorization",
                     str(tmp_path / "AUTH.json"), option, value]) == 1
    assert "不能" in json.loads(capsys.readouterr().out)["error"]
    assert not runtimes["v3"].calls


def test_cli_source_choices_are_exclusive():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["prepare", "--run-dir", "run", "--source-path", "s",
                                        "--authorization", "a"])


def test_cli_fetch_reuses_existing_acquisition_only(tmp_path, runtimes, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(acquisition, "fetch_source", lambda **kwargs:
                        calls.append(kwargs) or {"status": "source_saved"})
    assert cli.main(["fetch", "--output-dir", str(tmp_path / "f"), "--book-name", "小说"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "source_saved"
    assert calls == [{"output_dir": tmp_path / "f", "book_name": "小说", "book_id": "", "chapters": 1}]
    assert all(not module.calls for module in runtimes.values())


@pytest.mark.parametrize("status", ["needs_attention", "evidence_invalid", "blocked",
                                    "legacy_dispatch_blocked", "content_revision_exhausted",
                                    "incomplete_artifacts"])
def test_cli_terminal_failure_is_nonzero(status, runtimes, capsys):
    runtimes["v3"].report["status"] = status
    assert cli.main(["execute", "--run-dir", "run"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == status
    assert len(runtimes["v3"].calls) == 1


def test_cli_exception_no_retry(runtimes, capsys):
    calls = []
    def fail(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("截断停止")
    runtimes["v3"].execute = fail
    assert cli.main(["execute", "--run-dir", "run"]) == 1
    assert len(calls) == 1
    assert json.loads(capsys.readouterr().out)["automatic_media_submit"] is False


@pytest.mark.parametrize("version", ["v1", "v2", "v3"])
def test_panel_selects_frozen_runtime_without_migration(tmp_path, runtimes, version):
    _binding(tmp_path, version)
    before = (tmp_path / "BINDING.json").read_bytes()
    runtime, legacy = panel._runtime(tmp_path)
    assert runtime is runtimes[version] and legacy is (version != "v3")
    assert (tmp_path / "BINDING.json").read_bytes() == before
    assert all(not module.calls for module in runtimes.values())


@pytest.mark.parametrize("value", [{}, {"schema": "future/v8"}, []])
def test_panel_unknown_binding_rejected(tmp_path, runtimes, value):
    (tmp_path / "BINDING.json").write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError):
        panel._runtime(tmp_path)
    assert all(not module.calls for module in runtimes.values())


def _spawns(monkeypatch):
    calls = []
    monkeypatch.setattr(panel, "get_current_role", lambda: "editor")
    def popen(argv, **kwargs):
        assert kwargs["creationflags"] == getattr(panel.subprocess, "CREATE_NO_WINDOW", 0)
        assert kwargs["stdin"] == panel.subprocess.DEVNULL
        calls.append(argv)
        return SimpleNamespace(pid=123)
    monkeypatch.setattr(panel.subprocess, "Popen", popen)
    return calls


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_panel_legacy_launch_always_refused(tmp_path, runtimes, monkeypatch, version):
    _binding(tmp_path, version)
    calls = _spawns(monkeypatch)
    with pytest.raises(RuntimeError, match="历史版本"):
        panel.launch_text(tmp_path)
    assert calls == []
    assert all(not module.calls for module in runtimes.values())
    assert not (tmp_path / ".web_launch.lock").exists()


def test_panel_new_launch_uses_v3_and_preserves_exclusive_marker(tmp_path, runtimes, monkeypatch):
    calls = _spawns(monkeypatch)
    result = panel.launch_text(tmp_path)
    assert result["automatic_media_submit"] is False
    assert Path(calls[0][1]).name == "run_novel_plaintext_v3.py"
    assert [row[0] for row in runtimes["v3"].calls] == ["inspect", "preview"]
    with pytest.raises(RuntimeError, match="已经提交"):
        panel.launch_text(tmp_path)
    assert len(calls) == 1


@pytest.mark.parametrize("report", [{"status": "needs_attention"},
                                    {"status": "text_ready_for_director"},
                                    {"status": "prepared", "pending_call": 3},
                                    {"status": "prepared", "state": {"pending_call": 3}},
                                    {"status": "prepared", "blockers": ["停点"]}])
def test_panel_pending_or_terminal_no_spawn(tmp_path, runtimes, monkeypatch, report):
    calls = _spawns(monkeypatch)
    runtimes["v3"].report = report
    with pytest.raises(RuntimeError):
        panel.launch_text(tmp_path)
    assert calls == []


def _app(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setattr(panel, "get_current_role", lambda: "editor")
    monkeypatch.setattr(panel, "discover_sources", lambda roots: [])
    app = AppTest.from_string("from src.web.novel_adaptation_panel_v1 import page_novel_adaptation\npage_novel_adaptation()")
    app.session_state["novel_adaptation_run"] = str(tmp_path)
    return app


def test_real_page_new_prepare_uses_plaintext_not_legacy(tmp_path, runtimes, monkeypatch):
    runtimes["v3"].report = {"status": "unprepared", "dispatch_blocked": True}
    app = _app(tmp_path, monkeypatch).run(timeout=15)
    assert not app.exception
    next(item for item in app.text_input if item.key == "novel_adaptation_source_path").set_value(str(tmp_path / "chapter.txt"))
    next(item for item in app.text_input if item.key == "novel_adaptation_scope").set_value("第1章")
    next(item for item in app.button if item.label == "准备与冻结输入（不调用模型）").click()
    app.run(timeout=15)
    assert not app.exception
    assert len([item for item in runtimes["v3"].calls if item[0] == "prepare"]) == 1
    assert not runtimes["v1"].calls and not runtimes["v2"].calls
    assert not any("hash" in item.label.lower() or "哈希" in item.label for item in app.text_input)


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_real_page_legacy_reads_original_and_disables_dispatch(tmp_path, runtimes, monkeypatch, version):
    _binding(tmp_path, version)
    before = (tmp_path / "BINDING.json").read_bytes()
    app = _app(tmp_path, monkeypatch).run(timeout=15)
    assert not app.exception
    assert next(item for item in app.button if item.label == "后台生成完整剧本并全文复审").disabled
    assert [row[0] for row in runtimes[version].calls] == ["inspect", "preview"]
    assert (tmp_path / "BINDING.json").read_bytes() == before
    assert not runtimes["v3"].calls


def test_real_page_shows_complete_native_text_and_deepseek_review(tmp_path, runtimes, monkeypatch):
    screenplay, review = tmp_path / "SCREENPLAY.md", tmp_path / "FULL_TEXT_REVIEW.json"
    screenplay.write_text("# 完整原生稿\n时代背景\n角色选择\n场一：她回到房间。\n结尾：她合上门。", encoding="utf-8")
    review.write_text(json.dumps({"verdict": "pass", "whole_text_reviewed": True}), encoding="utf-8")
    runtimes["v3"].report = {"status": "text_ready_for_director", "dispatch_blocked": True,
                             "source": {"title": "正文来源", "scope": {"acquired_chapters": 1}},
                             "human_approved": False,
                             "legacy_consumption": {"calls_started": 14, "reported_tokens": 228513},
                             "combined_calls_started": 16, "combined_known_reported_tokens": 228553,
                             "artifacts": {"script": {"path": str(screenplay)}, "review": {"path": str(review)}}}
    app = _app(tmp_path, monkeypatch).run(timeout=15)
    assert not app.exception
    assert any("结尾：她合上门。" in item.value for item in app.markdown)
    assert any('"whole_text_reviewed": true' in item.value for item in app.json)
    assert any("人工采用尚未确认" in item.value for item in app.caption)
    assert any("14 次调用、228513 tokens" in item.value for item in app.caption)
    assert any("累计 16 次调用、已确认 228553 tokens" in item.value for item in app.caption)
    assert next(item for item in app.button if item.label == "后台生成完整剧本并全文复审").disabled
    assert all("视频" not in item.label for item in app.button)


def test_real_page_viewer_cannot_dispatch_or_prepare(tmp_path, runtimes, monkeypatch):
    runtimes["v3"].report = {"status": "unprepared"}
    app = _app(tmp_path, monkeypatch)
    monkeypatch.setattr(panel, "get_current_role", lambda: "viewer")
    app.run(timeout=15)
    assert not app.exception
    for label in ("获取正文（打开采集器窗口）", "准备与冻结输入（不调用模型）"):
        assert next(item for item in app.button if item.label == label).disabled
    assert not any(row[0] in {"prepare", "execute"} for row in runtimes["v3"].calls)
