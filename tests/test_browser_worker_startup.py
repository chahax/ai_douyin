from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.platform_adapter import browser_session as module
from src.platform_adapter.models import BrowserSessionConfig


def _session(tmp_path):
    return module.BrowserSession(BrowserSessionConfig(base_url="http://127.0.0.1",
        home_url="http://127.0.0.1", user_data_dir=str(tmp_path / "isolated_profile"),
        storage_state_path=str(tmp_path / "state.json"), headless=True, timeout_ms=100))


class _Process:
    def __init__(self, response=b'{"status":"ready"}\n', stderr=b""):
        self.stdin, self.stdout, self.stderr = io.BytesIO(), io.BytesIO(response), io.BytesIO(stderr)
        self.kills, self.waits = 0, []
    def kill(self):
        self.kills += 1
    def wait(self, timeout=None):
        self.waits.append(timeout)
        return 0


@pytest.mark.parametrize('extra,expected', [({'supervision_protocol':1},1), ({},0)])
def test_real_bytes_ready_receipt_decoded_before_protocol_read(tmp_path, monkeypatch, extra, expected):
    session = _session(tmp_path)
    response = json.dumps(dict(status='ready', default_tab_id='original-tab', **extra)).encode()+b'\n'
    process = _Process(response=response)
    calls = []
    monkeypatch.setattr(module.subprocess, 'Popen', lambda *a, **k:calls.append(a[0]) or process)
    try:
        session._start()
        assert session.active and session._worker_stage == 'ready'
        assert session._supervision_protocol == expected and session._default_tab_id == 'original-tab'
        assert len(calls) == 1 and process.kills == 0
    finally:
        session.stop()


@pytest.mark.parametrize('response', [b'[]\n', b'{"status":"ready","supervision_protocol":true}\n',
    b'{"status":"ready","supervision_protocol":"1"}\n', b'{"status":"ready","supervision_protocol":2}\n'])
def test_invalid_ready_object_or_protocol_fails_closed_without_retry(tmp_path, monkeypatch, response):
    session = _session(tmp_path)
    process = _Process(response=response)
    calls = []
    monkeypatch.setattr(module.subprocess, 'Popen', lambda *a, **k:calls.append(a[0]) or process)
    with pytest.raises(module.BrowserWorkerStartupError):
        session._start()
    assert len(calls) == 1 and process.kills == 1 and session._proc is None and not session.active


def test_worker_bootstrap_skips_site_and_has_explicit_dependencies(tmp_path, monkeypatch):
    session, calls = _session(tmp_path), []
    process = _Process()
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: calls.append((a, k)) or process)
    monkeypatch.setenv("PYTHONPATH", "unrelated-site-hook-directory")
    session._start()
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[0][:2] == [sys.executable, "-S"] and len(args[0]) == 3
    assert Path(args[0][2]).read_bytes() == module._PW_SCRIPT.encode('utf-8')
    env = kwargs["env"]
    assert env["PYTHONNOUSERSITE"] == "1" and env["PYDANTIC_DISABLE_PLUGINS"] == "__all__"
    assert "unrelated-site-hook-directory" not in env["PYTHONPATH"]
    root = Path(__file__).resolve().parents[1]
    assert env['TEMP'] == env['TMP'] == env['TMPDIR']
    assert Path(env['TEMP']).is_relative_to(root / 'data/browser_runtime/temporary')
    assert Path(env['TEMP']).is_dir()
    if sys.platform == 'win32':
        assert Path(env['PLAYWRIGHT_NODEJS_PATH']) == root / '.venv/Lib/site-packages/playwright/driver/node.exe'
    init = json.loads(process.stdin.getvalue())
    root = Path(__file__).resolve().parents[1]
    assert str(root) in init["python_paths"]
    assert str(root / ".venv" / "Lib" / "site-packages") in init["python_paths"]
    assert session.active and session._worker_stage == "ready"
    session.stop()


@pytest.mark.parametrize('headless', [True, False])
@pytest.mark.skipif(sys.platform != 'win32', reason='Windows worker console flag')
def test_windows_worker_console_is_hidden_without_changing_browser_mode(tmp_path, monkeypatch, headless):
    session, calls = _session(tmp_path), []
    session.config.headless = headless
    process = _Process()
    monkeypatch.setattr(module.subprocess, 'Popen', lambda *a, **k:calls.append(k) or process)
    session._start()
    assert calls[0]['creationflags'] == subprocess.CREATE_NO_WINDOW
    assert json.loads(process.stdin.getvalue())['headless'] is headless
    session.stop()


@pytest.mark.parametrize('headless', [True, False])
def test_actual_worker_launch_mutes_only_background_browser(tmp_path, monkeypatch, headless):
    from types import ModuleType
    launched, closed = [], []
    context = SimpleNamespace(pages=[object()], set_default_timeout=lambda _:None,
        close=lambda:closed.append('context'))
    def launch(**kwargs):
        launched.append(kwargs)
        return context
    pw = SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=launch),
        stop=lambda:closed.append('driver'))
    fake_api = ModuleType('playwright.sync_api')
    fake_api.sync_playwright = lambda:SimpleNamespace(start=lambda:pw)
    monkeypatch.setitem(sys.modules, 'playwright.sync_api', fake_api)
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps(dict(user_data_dir=str(tmp_path),
        headless=headless, slow_mo=0, channel='chrome')) + '\n' + '{"action":"stop"}\n'))
    output = io.StringIO()
    monkeypatch.setattr(sys, 'stdout', output)
    monkeypatch.setattr(sys, 'stderr', io.StringIO())
    namespace = {'__name__':'worker_fixture'}
    exec(compile(module._PW_SCRIPT, '<real-worker>', 'exec'), namespace)
    namespace['main']()
    assert len(launched) == 1 and launched[0]['headless'] is headless
    assert launched[0]['user_data_dir'] == str(tmp_path) and launched[0]['channel'] == 'chrome'
    assert ('--mute-audio' in launched[0].get('args', [])) is headless
    assert json.loads(output.getvalue().splitlines()[0])['status'] == 'ready'
    assert closed == ['context', 'driver']


def test_lean_state_helpers_import_without_platform_settings_or_clients(tmp_path):
    root = Path(__file__).resolve().parents[1]
    script = ("import sys; sys.path.insert(0," + repr(str(root)) + "); "
        "from src.shared.browser_worker_state import missing_snapshot_cookies, checkpoint_open_login_pages; "
        "assert not any(k.startswith('src.platform_adapter') for k in sys.modules); "
        "assert 'src.shared.config' not in sys.modules; assert 'pydantic' not in sys.modules; "
        "assert 'src.shared.logger' not in sys.modules; print('isolated')")
    result = subprocess.run([sys.executable, "-S", "-c", script], capture_output=True, timeout=20)
    assert result.returncode == 0 and result.stdout.strip() == b"isolated"


def test_restore_and_manual_checkpoint_do_not_import_platform_package():
    startup = module._PW_SCRIPT.split("# 主循环")[0]
    assert "from src.platform_adapter" not in startup
    for action, next_action in (("save_state", "save_visible_state"), ("save_visible_state", "wait_for_close"), ("wait_for_close", "api_download")):
        branch = module._PW_SCRIPT.split(f'elif action == "{action}":')[1].split(f'elif action == "{next_action}":')[0]
        assert "from src.platform_adapter" not in branch
        assert "from src.shared.browser_worker_state" in branch
    assert module._missing_snapshot_cookies.__module__ == "src.shared.browser_worker_state"
    compile(module._PW_SCRIPT, "<browser-worker>", "exec")


def test_start_timeout_has_specific_stage_cleans_worker_and_never_retries(tmp_path, monkeypatch):
    session, calls = _session(tmp_path), []
    process = _Process()
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: calls.append(a[0]) or process)
    def timeout(seconds, *, label):
        assert seconds == 45 and label == "start"
        session._worker_stage = "launching_browser"
        raise TimeoutError("private transport payload")
    monkeypatch.setattr(session, "_read_child_line", timeout)
    with pytest.raises(module.BrowserWorkerStartupTimeout) as error:
        session._start()
    assert error.value.code == "browser_start_timeout" and error.value.stage == "launching_browser"
    assert "45" in str(error.value) and "private transport payload" not in str(error.value)
    assert len(calls) == 1 and process.kills == 1 and process.waits == [5]
    assert process.stdin.closed and process.stdout.closed and process.stderr.closed
    assert session._proc is None and not session.active


@pytest.mark.parametrize("response", [b"", b'{"status":"error","msg":"cookie:secret"}\n', b"invalid-json\n"])
def test_failed_start_receipt_is_not_exposed_or_retried(tmp_path, monkeypatch, response):
    session, calls = _session(tmp_path), []
    process = _Process(response=response, stderr=b"authorization: never-log-this\n")
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: calls.append(a[0]) or process)
    with pytest.raises(module.BrowserWorkerStartupError) as error:
        session._start()
    assert error.value.code == "browser_start_failed" and len(calls) == 1
    assert "secret" not in str(error.value) and "never-log-this" not in str(error.value)
    assert process.kills == 1 and session._proc is None


def test_worker_stage_logs_accept_only_stage_and_elapsed_fields(tmp_path, monkeypatch):
    session, logs = _session(tmp_path), []
    process = _Process(stderr=(b'cookie: never-log-this\n'
        b'{"browser_worker_stage":"evil-private-stage","elapsed_ms":1}\n'
        b'{"browser_worker_stage":"restoring_state","elapsed_ms":7,"cookie":"secret"}\n'))
    session._proc = process
    monkeypatch.setattr(module.logger, "info", lambda *a, **k: logs.append((a, k)))
    session._read_worker_stages(process)
    assert session._worker_stage == "restoring_state" and len(logs) == 1
    assert "secret" not in repr(logs) and "never-log-this" not in repr(logs) and "evil-private-stage" not in repr(logs)


def test_explicit_driver_configuration_is_not_overwritten(tmp_path, monkeypatch):
    session = _session(tmp_path)
    monkeypatch.setenv('PLAYWRIGHT_NODEJS_PATH', 'explicit-driver')
    assert session._build_child_env()['PLAYWRIGHT_NODEJS_PATH'] == 'explicit-driver'


@pytest.fixture
def manual_session(tmp_path, monkeypatch):
    session, events = _session(tmp_path), []
    def start():
        assert session.config.headless is False
        events.append("start")
    def send(command):
        events.append(command["action"])
        return {"status": "ok", "state_saved": True}
    monkeypatch.setattr(session, "_start", start)
    monkeypatch.setattr(session, "_send", send)
    monkeypatch.setattr(session, "stop", lambda: events.append("stop"))
    monkeypatch.setattr(session, "get_state", lambda: SimpleNamespace(authenticated=False))
    return session, events


def test_on_opened_occurs_once_after_real_goto_before_waiting(manual_session):
    session, events = manual_session
    session.open_for_manual_login_until_closed("http://127.0.0.1", timeout_seconds=1,
        on_opened=lambda: events.append("opened"))
    assert events == ["start", "goto", "opened", "wait_for_close", "stop"]


@pytest.mark.parametrize("stage", ["start", "goto"])
def test_failed_start_or_navigation_never_reports_opened_and_stops(manual_session, monkeypatch, stage):
    session, events = manual_session
    original = TimeoutError("local technical failure")
    def fail(*a, **k):
        events.append(stage)
        raise original
    monkeypatch.setattr(session, "_start" if stage == "start" else "_send", fail)
    with pytest.raises(TimeoutError) as error:
        session.open_for_manual_login_until_closed("http://127.0.0.1", on_opened=lambda: events.append("opened"))
    assert error.value is original and "opened" not in events and "wait_for_close" not in events
    assert events[-1] == "stop"


def test_callback_exception_stops_without_entering_wait(manual_session):
    session, events = manual_session
    original = RuntimeError("UI callback failed")
    def callback():
        events.append("opened")
        raise original
    with pytest.raises(RuntimeError) as error:
        session.open_for_manual_login_until_closed("http://127.0.0.1", on_opened=callback)
    assert error.value is original and events == ["start", "goto", "opened", "stop"]
