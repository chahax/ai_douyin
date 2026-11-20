"""Offline-only entrypoint tests, with no provider/browser or account database."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

from scripts import run_novel_adaptation_v1 as cli
from src.content_factory import novel_adaptation_acquisition_v1 as acquisition
from src.web import novel_adaptation_panel_v1 as panel


@pytest.fixture
def fake_pipeline(monkeypatch):
    module = ModuleType("src.content_factory.novel_adaptation_pipeline_v1")
    module.calls = []
    module.report = {"status": "prepared", "dispatch_blocked": False, "blockers": [],
                     "stage": "analysis", "human_approved": False}
    for name in ("prepare", "preview", "inspect", "execute"):
        def call(*args, _name=name, **kwargs):
            module.calls.append((_name, args, kwargs))
            return dict(module.report)
        setattr(module, name, call)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    import src.content_factory as package
    monkeypatch.setattr(package, "novel_adaptation_pipeline_v1", module, raising=False)
    # The legacy CLI remains v1; fresh web tasks now select the v3 API.
    # Version-routing and legacy read-only behavior have dedicated v3 tests.
    monkeypatch.setitem(sys.modules, "src.content_factory.novel_plaintext_pipeline_v3", module)
    monkeypatch.setattr(package, "novel_plaintext_pipeline_v3", module, raising=False)
    return module


@dataclass
class Fetched:
    book_name: str
    book_id: str
    chapters: list
    chapters_dir: str
    material_path: str


class FakeService:
    calls = []

    def __init__(self, *, root_dir):
        self.root = Path(root_dir)

    def fetch_book(self, name, *, chapters, headless, book_id):
        self.calls.append((name, chapters, headless, book_id))
        directory = self.root / "book/chapters"
        directory.mkdir(parents=True)
        path = directory / "001.txt"
        path.write_text("第一章 回家\n" + "她回到房间，看到桌上的信。" * 20, encoding="utf-8")
        return Fetched(name, book_id, [{"title": "第一章 回家", "file": str(path)}],
                       str(directory), str(directory.parent / "material.txt"))


def test_fetch_explicit_service_default_one_chapter_and_native_identity(tmp_path):
    FakeService.calls = []
    result = acquisition.fetch_source(tmp_path / "new", book_name="原书", book_id="123",
                                      service_factory=FakeService)
    assert FakeService.calls == [("原书", 1, False, "123")]
    assert result["status"] == "source_saved"
    assert result["automatic_media_submit"] is False
    row = result["source"]["chapters"][0]
    assert row["sha256"] == hashlib.sha256(Path(row["path"]).read_bytes()).hexdigest()
    assert result["scope"]["acquired_chapters"] == 1
    assert Path(result["receipt_path"]).is_file()
    before = Path(result["receipt_path"]).read_bytes()
    with pytest.raises(FileExistsError):
        acquisition.fetch_source(tmp_path / "new", book_name="原书", service_factory=FakeService)
    assert Path(result["receipt_path"]).read_bytes() == before
    assert len(FakeService.calls) == 1


@pytest.mark.parametrize("error", ["需要登录", "人机验证", "采集失败"])
def test_fetch_failure_receipt_no_retry(tmp_path, error):
    class Service:
        calls = 0
        def __init__(self, **kwargs):
            pass
        def fetch_book(self, *args, **kwargs):
            type(self).calls += 1
            raise RuntimeError(error)
    report = acquisition.fetch_source(tmp_path / "failure", book_name="原书", service_factory=Service)
    assert report["status"] == "acquisition_failed"
    assert report["automatic_retry"] is False
    assert Service.calls == 1
    assert error in Path(report["receipt_path"]).read_text(encoding="utf-8")


@pytest.mark.parametrize("kind", ["empty", "outside", "invalid_utf8", "duplicate", "title_only"])
def test_fetch_invalid_actual_chapter_preserves_failure(tmp_path, kind):
    class Service(FakeService):
        def fetch_book(self, *args, **kwargs):
            result = super().fetch_book(*args, **kwargs)
            path = Path(result.chapters[0]["file"])
            if kind == "empty":
                path.write_text("", encoding="utf-8")
            elif kind == "invalid_utf8":
                path.write_bytes(b"\xff\xfe")
            elif kind == "title_only":
                path.write_text("第一章 回家\n\n", encoding="utf-8")
            elif kind == "outside":
                outside = tmp_path / "outside.txt"
                outside.write_text("真实正文", encoding="utf-8")
                result.chapters[0]["file"] = str(outside)
            else:
                result.chapters.append(dict(result.chapters[0]))
            return result
    report = acquisition.fetch_source(tmp_path / "bad", book_name="原书", service_factory=Service)
    assert report["status"] == "acquisition_failed"
    assert Path(report["receipt_path"]).is_file()


def test_existing_book_bridge_keeps_native_files_and_metadata(tmp_path):
    book = tmp_path / "old"
    (book / "chapters").mkdir(parents=True)
    chapter = book / "chapters/001.txt"
    chapter.write_text("第一章\n原有正文", encoding="utf-8")
    meta = book / "meta.json"
    meta.write_text(json.dumps({"book_name": "原书", "book_id": "10"}), encoding="utf-8")
    before = meta.read_bytes(), chapter.read_bytes()
    result = acquisition.import_saved_book(meta, tmp_path / "bridge")
    assert (meta.read_bytes(), chapter.read_bytes()) == before
    assert result["source"]["metadata_sha256"] == hashlib.sha256(before[0]).hexdigest()
    assert result["source"]["chapters"][0]["path"] == str(chapter.resolve())
    found = acquisition.discover_sources([tmp_path])
    assert {item["kind"] for item in found} == {"metadata", "receipt"}
    assert any(item["title"] == "原书" for item in found)


def test_import_empty_never_creates_success_receipt(tmp_path):
    (tmp_path / "meta.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="没有可用"):
        acquisition.import_saved_book(tmp_path / "meta.json", tmp_path / "new")
    assert not (tmp_path / "new").exists()


@pytest.mark.parametrize("command", ["prepare", "preview", "inspect", "execute"])
def test_cli_calls_only_requested_runtime_api(tmp_path, fake_pipeline, capsys, command):
    argv = [command, "--run-dir", str(tmp_path / "run")]
    if command == "prepare":
        argv.extend(["--source-path", str(tmp_path / "chapter.txt"), "--scope", "第一章"])
    assert cli.main(argv) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "prepared"
    assert len(fake_pipeline.calls) == 1
    name, args, kwargs = fake_pipeline.calls[0]
    assert name == command and kwargs["run_dir"] == tmp_path / "run"
    if command == "prepare":
        assert kwargs["max_revisions"] == 2
        assert kwargs["scope"] == "第一章"


def test_cli_fetch_delegates_explicit_acquisition(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(acquisition, "fetch_source", lambda **kwargs:
                        calls.append(kwargs) or {"status": "source_saved"})
    assert cli.main(["fetch", "--output-dir", str(tmp_path / "new"), "--book-name", "书名"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "source_saved"
    assert calls == [{"output_dir": tmp_path / "new", "book_name": "书名", "chapters": 1, "book_id": ""}]


def test_cli_failure_is_structured_and_no_retry(fake_pipeline, capsys):
    def fail(**kwargs):
        raise RuntimeError("已截断，不能重新派发")
    fake_pipeline.execute = fail
    assert cli.main(["execute", "--run-dir", "failed"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "entry_rejected" and "截断" in result["error"]


def _mock_spawn(monkeypatch):
    calls = []
    monkeypatch.setattr(panel, "get_current_role", lambda: "editor")
    def popen(argv, **kwargs):
        assert kwargs["stdout"] is kwargs["stderr"]
        assert kwargs["stdin"] == panel.subprocess.DEVNULL
        assert kwargs["creationflags"] == getattr(panel.subprocess, "CREATE_NO_WINDOW", 0)
        calls.append(argv)
        return SimpleNamespace(pid=1234)
    monkeypatch.setattr(panel.subprocess, "Popen", popen)
    return calls


def test_panel_text_launch_exclusive_hidden_background(tmp_path, fake_pipeline, monkeypatch):
    calls = _mock_spawn(monkeypatch)
    run = tmp_path / "run"
    run.mkdir()
    result = panel.launch_text(run)
    assert result["pid"] == 1234 and result["automatic_media_submit"] is False
    assert calls[0][-3:] == ["execute", "--run-dir", str(run.resolve())]
    assert (run / "execution.log").is_file()
    assert (run / ".web_launch.lock").is_file()
    with pytest.raises(RuntimeError, match="已经提交"):
        panel.launch_text(run)
    assert len(calls) == 1


@pytest.mark.parametrize("report", [
    {"status": "text_ready_for_director"}, {"status": "needs_attention"},
    {"status": "prepared", "dispatch_blocked": True},
    {"status": "prepared", "pending_call": 2},
    {"status": "prepared", "blockers": ["原任务锁"]},
])
def test_panel_stopped_or_pending_never_spawns(tmp_path, fake_pipeline, monkeypatch, report):
    calls = _mock_spawn(monkeypatch)
    fake_pipeline.report = report
    with pytest.raises(RuntimeError):
        panel.launch_text(tmp_path)
    assert calls == []


def test_panel_permission_guard_for_both_actions(tmp_path, fake_pipeline, monkeypatch):
    calls = _mock_spawn(monkeypatch)
    monkeypatch.setattr(panel, "get_current_role", lambda: "viewer")
    with pytest.raises(PermissionError):
        panel.launch_text(tmp_path)
    with pytest.raises(PermissionError):
        panel.launch_acquisition(tmp_path / "fetch", book_name="书名")
    assert calls == []


def test_panel_fetch_launch_and_duplicate_are_explicit(tmp_path, monkeypatch):
    calls = _mock_spawn(monkeypatch)
    job = tmp_path / "fetch"
    receipt = panel.launch_acquisition(job, book_name="书名", book_id="123", chapters=1)
    assert "fetch" in calls[0] and calls[0][-2:] == ["--book-id", "123"]
    assert receipt["receipt_path"] == str(job.resolve() / "source/RECEIPT.json")
    with pytest.raises(FileExistsError):
        panel.launch_acquisition(job, book_name="书名")
    assert len(calls) == 1


def test_navigation_real_route_independent_of_account_selection():
    source = (panel.ROOT / "src/web/app.py").read_text(encoding="utf-8")
    assert '("novel_adaptation", page_novel_adaptation, "小说改编"' in source
    assert '"editor", "novel-adaptation")' in source
    assert 'if navigation != studio_destinations.get("novel_adaptation"):' in source
    # New tasks route to v7; the frozen v1 panel remains independently available.
    assert "from src.web.novel_agent_panel_v7 import page_novel_adaptation" in source
    page = Path(panel.__file__).read_text(encoding="utf-8")
    assert "AccountProfileRepository" not in page and "TrendRepository" not in page


def test_real_page_prepare_and_completed_reading_copy(tmp_path, fake_pipeline, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setattr(panel, "get_current_role", lambda: "editor")
    monkeypatch.setattr(panel, "discover_sources", lambda roots: [])
    fake_pipeline.report = {"status": "text_ready_for_director", "dispatch_blocked": True,
                            "stage": "complete", "source": {"title": "原书", "scope": "第一章"},
                            "artifacts": {"SCREENPLAY.md": {"path": str(tmp_path / "SCREENPLAY.md")}},
                            "human_approved": False}
    (tmp_path / "SCREENPLAY.md").write_text("# 阅读剧本\n背景和完整事件", encoding="utf-8")
    app = AppTest.from_string("from src.web.novel_adaptation_panel_v1 import page_novel_adaptation\npage_novel_adaptation()")
    app.session_state["novel_adaptation_run"] = str(tmp_path)
    app.run(timeout=10)
    assert not app.exception
    assert any("背景和完整事件" in item.value for item in app.markdown)
    execute = next(item for item in app.button if item.label == "后台生成完整剧本并全文复审")
    assert execute.disabled
    assert all("视频" not in item.label for item in app.button)


def test_real_page_viewer_cannot_prepare_or_acquire(tmp_path, fake_pipeline, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setattr(panel, "get_current_role", lambda: "viewer")
    monkeypatch.setattr(panel, "discover_sources", lambda roots: [])
    fake_pipeline.report = {"status": "unprepared", "dispatch_blocked": True}
    app = AppTest.from_string("from src.web.novel_adaptation_panel_v1 import page_novel_adaptation\npage_novel_adaptation()")
    app.session_state["novel_adaptation_run"] = str(tmp_path / "run")
    app.run(timeout=10)
    assert not app.exception
    for label in ("获取正文（打开采集器窗口）", "准备与冻结输入（不调用模型）"):
        assert next(item for item in app.button if item.label == label).disabled
    assert not any(call[0] in {"prepare", "execute"} for call in fake_pipeline.calls)


def test_real_runtime_accepts_bridge_and_previews_without_clients(tmp_path, monkeypatch):
    from src.content_factory import novel_adaptation_pipeline_v1 as runtime
    monkeypatch.setattr(runtime, "CANONICAL_REGISTRY", tmp_path / "canonical_registry")
    def forbidden_clients():
        raise AssertionError("prepare/preview不得创建模型客户端")
    monkeypatch.setattr(runtime, "CreativeRoleClients", forbidden_clients)
    source = acquisition.fetch_source(tmp_path / "fetch", book_name="入口联调离线书",
                                      service_factory=FakeService)
    run = tmp_path / "run"
    prepared = runtime.prepare(run, acquisition_receipt=source["receipt_path"])
    assert prepared["status"] == "prepared" and prepared["calls_started"] == 0
    preview = runtime.preview(run)
    assert preview["source"]["scope"]["acquired_chapters"] == 1
    assert preview["stages"] == ["analysis", "adaptation_plan", "screenplay", "review"]
    assert preview["human_approved"] is False
    chapter = Path(source["source"]["chapters"][0]["path"])
    chapter.write_text("来源被改动", encoding="utf-8")
    stopped = runtime.inspect(run)
    assert stopped["status"] == "evidence_invalid" and stopped["dispatch_blocked"]
    assert stopped["calls_started"] == 0
