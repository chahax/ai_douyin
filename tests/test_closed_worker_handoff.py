"""The opt-in close confirmation cannot permit a browser or arbitrary child."""
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('handoff_closed_worker', ROOT / 'scripts/handoff_idle_browser_control.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
from src.platform_adapter.browser_session import _PW_SCRIPT


class Process:
    def __init__(self, pid, parent, name, cmd=(), executable=None):
        self.pid, self.parent, self.label = pid, parent, name
        self.command, self.executable = list(cmd), executable
        self.started = 1000.0 + pid
        self.descendants = []
    def create_time(self):
        return self.started
    def ppid(self):
        return self.parent
    def name(self):
        return self.label
    def cmdline(self):
        return self.command
    def exe(self):
        return self.executable
    def children(self, recursive=True):
        return self.descendants


def fixture():
    proc = Process(1, 0, 'pythonw.exe')
    driver = ROOT / '.local_py/site-packages/playwright/driver'
    pycmd = [str(ROOT / '.venv/Scripts/pythonw.exe'), '-S', '-c', _PW_SCRIPT]
    proc.descendants = [Process(2, 1, 'pythonw.exe', pycmd), Process(3, 2, 'pythonw.exe', pycmd),
        Process(4, 3, 'node.exe', [str(driver / 'node.exe'), str(driver / 'package/cli.js'), 'run-driver']),
        Process(5, 4, 'conhost.exe', executable=str(Path(os.environ['SystemRoot']) / 'System32/conhost.exe'))]
    now = datetime.now(timezone.utc)
    confirm = {'user_statement': '已关闭项目窗口', 'service_pid': 1, 'process_create_time': proc.create_time(),
        'confirmed_at': now.isoformat(), 'worker_script_sha256': hashlib.sha256(_PW_SCRIPT.encode()).hexdigest(),
        'observed_children': [{'pid': p.pid, 'create_time': p.create_time()} for p in proc.descendants]}
    return proc, confirm, now


def test_exact_closed_worker_family_and_already_exited_children_are_allowed():
    proc, confirm, now = fixture()
    children, evidence = module.closed_worker_children(proc, confirm, now=now)
    assert [p.pid for p in children] == [2, 3, 4, 5]
    assert [p['ppid'] for p in evidence] == [1, 2, 3, 4]
    proc.descendants = []
    assert module.closed_worker_children(proc, confirm, now=now) == ([], [])


@pytest.mark.parametrize('variant', ['valid', 'modified', 'outside', 'wrong_exe', 'wrong_sha'])
def test_closed_file_worker_checks_actual_cache_and_original_family(tmp_path, monkeypatch, variant):
    from src.platform_adapter.browser_session import _worker_script_path
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    proc, confirm, now = fixture()
    cache = _worker_script_path(tmp_path / 'data/browser_worker_cache')
    for child in proc.descendants[:2]:
        child.command = [str(tmp_path/'.venv/Scripts/pythonw.exe'), '-S', str(cache)]
    driver = tmp_path/'.local_py/site-packages/playwright/driver'
    proc.descendants[2].command = [str(driver/'node.exe'), str(driver/'package/cli.js'), 'run-driver']
    if variant == 'modified': cache.write_bytes(b'pass')
    if variant == 'outside':
        other=tmp_path/cache.name
        other.write_bytes(cache.read_bytes())
        proc.descendants[0].command[2]=str(other)
    if variant == 'wrong_exe': proc.descendants[0].command[0]=str(tmp_path/'other.exe')
    if variant == 'wrong_sha': confirm['worker_script_sha256']='0'*64
    if variant == 'valid':
        children, evidence=module.closed_worker_children(proc, confirm, now=now)
        assert [p.pid for p in children]==[2,3,4,5]
        assert [p['ppid'] for p in evidence]==[1,2,3,4]
    else:
        with pytest.raises(RuntimeError): module.closed_worker_children(proc, confirm, now=now)


@pytest.mark.parametrize('kind', ['browser', 'script', 'node', 'reuse', 'unexpected_child', 'parent', 'console',
                                 'old_confirmation', 'wrong_pid', 'wrong_statement', 'wrong_script', 'old_child'])
def test_unproven_family_is_rejected_without_process_action(kind):
    proc, confirm, now = fixture()
    if kind == 'browser':
        proc.descendants[-1].label = 'chrome.exe'
    elif kind == 'script':
        proc.descendants[0].command = [str(ROOT / '.venv/Scripts/pythonw.exe'), '-S', '-c', 'different code']
    elif kind == 'node':
        proc.descendants[2].command[-1] = 'different-driver'
    elif kind == 'reuse':
        proc.descendants[0].started += 1
    elif kind == 'unexpected_child':
        proc.descendants[0].pid = 999
    elif kind == 'parent':
        proc.descendants[2].parent = 1
    elif kind == 'console':
        proc.descendants[-1].executable = str(ROOT / 'conhost.exe')
    elif kind == 'old_confirmation':
        confirm['confirmed_at'] = (now - timedelta(minutes=31)).isoformat()
    elif kind == 'wrong_pid':
        confirm['service_pid'] = 99
    elif kind == 'wrong_statement':
        confirm['user_statement'] = 'still open'
    elif kind == 'wrong_script':
        confirm['worker_script_sha256'] = '0' * 64
    elif kind == 'old_child':
        proc.descendants[0].started = proc.create_time() - 1
        confirm['observed_children'][0]['create_time'] = proc.descendants[0].started
    with pytest.raises(RuntimeError):
        module.closed_worker_children(proc, confirm, now=now)
