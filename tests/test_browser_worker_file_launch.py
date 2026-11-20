"""Content addressed worker startup, isolated local browser only."""
import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

from src.platform_adapter import browser_session as module
from src.platform_adapter.models import BrowserSessionConfig


def test_source_exact_short_argv_and_cache_reuse(tmp_path):
    path = module._worker_script_path(tmp_path)
    assert path.name == hashlib.sha256(module._PW_SCRIPT.encode()).hexdigest()+'.py'
    assert path.read_bytes() == module._PW_SCRIPT.encode('utf-8')
    before = path.stat().st_mtime_ns
    assert module._worker_script_path(tmp_path) == path
    assert path.stat().st_mtime_ns == before
    old = subprocess.list2cmdline([sys.executable,'-S','-c',module._PW_SCRIPT])
    new = subprocess.list2cmdline([sys.executable,'-S',str(path)])
    assert len(old.encode('utf-16-le'))//2 > 32767
    assert len(new.encode('utf-16-le'))//2 < 2048
    compile(path.read_bytes(), str(path), 'exec')


def test_existing_modified_cache_refused_not_repaired(tmp_path):
    path = module._worker_script_path(tmp_path)
    path.write_bytes(b'print("modified")')
    with pytest.raises(RuntimeError, match='integrity_mismatch'):
        module._worker_script_path(tmp_path)
    assert path.read_bytes() == b'print("modified")'


def test_handoff_exact_file_and_legacy_inline_identity(tmp_path, monkeypatch):
    import importlib.util
    source=Path(__file__).resolve().parents[1]/'scripts/handoff_idle_browser_control.py'
    spec=importlib.util.spec_from_file_location('handoff_file_test',source)
    handoff=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(handoff)
    monkeypatch.setattr(handoff,'ROOT',tmp_path)
    path=module._worker_script_path(tmp_path/'data/browser_worker_cache')
    digest=path.stem
    exe=Path(sys.executable).resolve()
    assert handoff.worker_command_matches([str(exe),'-S',str(path)],exe,digest)
    assert handoff.worker_command_matches([str(exe),'-S','-c',module._PW_SCRIPT],exe,digest)
    assert not handoff.worker_command_matches([str(exe),'-S',str(path)],exe,'0'*64)
    assert not handoff.worker_command_matches([str(exe),'-S',str(path)],tmp_path/'wrong.exe',digest)
    other=tmp_path/path.name
    other.write_bytes(path.read_bytes())
    assert not handoff.worker_command_matches([str(exe),'-S',str(other)],exe,digest)
    path.write_bytes(b'pass')
    assert not handoff.worker_command_matches([str(exe),'-S',str(path)],exe,digest)


def test_local_real_worker_ready_and_closed_without_network(tmp_path, monkeypatch):
    assert tmp_path.resolve().is_relative_to(Path('D:/IT/ai_douyin').resolve())
    # Only test delta inserts a context-wide network abort before any page use.
    # Production bootstrap, protocol, file launch, and cleanup remain identical.
    anchor = '    page = context.pages[0] if context.pages else context.new_page()'
    assert module._PW_SCRIPT.count(anchor) == 1
    monkeypatch.setattr(module, '_PW_SCRIPT', module._PW_SCRIPT.replace(anchor,
        "    context.route('**/*', lambda route: route.abort())\n"+anchor))
    helper = module._worker_script_path
    monkeypatch.setattr(module, '_worker_script_path', lambda:helper(tmp_path/'cache'))
    config=BrowserSessionConfig(base_url='about:blank',home_url='about:blank',
        storage_state_path=str(tmp_path/'state.json'),user_data_dir=str(tmp_path/'profile'),
        browser_channel='chrome',headless=True,mute_audio=True,timeout_ms=10000)
    session=module.BrowserSession(config)
    process=None
    try:
        session._start()
        process=session._proc
        assert session.active and session._worker_stage=='ready'
        assert process.poll() is None
        assert len(process.args)==3 and '-c' not in process.args
    finally:
        session.stop()
    assert process is not None and process.poll() is not None
    assert session._proc is None and not session.active
