"""Supervised handoff script in a fully isolated tree; no process is stopped."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys

import psutil
import pytest

from src.operations_accounts.browser_control import BrowserControlStore


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    source = Path(__file__).parents[1] / 'scripts/handoff_idle_browser_control.py'
    spec = importlib.util.spec_from_file_location('isolated_idle_handoff', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    (tmp_path / 'data/logs').mkdir(parents=True)
    (tmp_path / 'data/logs/streamlit_web.pid').write_text('4321')
    store = BrowserControlStore(tmp_path / 'data/account_browser_control.db')
    store.acquire_owner('review:A', 'binding-v1', 'backend:4321:original-nonce')
    original = store.submit('review:A', 'binding-v1', 'publish', 'original-publication', {'original': True}, 100)
    with sqlite3.connect(tmp_path / 'data/douyin.db') as db:
        db.execute('CREATE TABLE account_runtime_state(lock_owner TEXT)')
        db.execute("INSERT INTO account_runtime_state VALUES('')")
    with sqlite3.connect(tmp_path / 'data/account_refresh.db') as db:
        db.execute('CREATE TABLE account_controls(account_uuid TEXT,state TEXT)')
        db.execute("INSERT INTO account_controls VALUES('review:A','paused')")
        db.execute('CREATE TABLE account_handling_requests(status TEXT)')
        for kind in ('refresh', 'smart', 'playback'):
            db.execute(f'CREATE TABLE {kind}_accounts(run_id TEXT,lease_until REAL)')
            db.execute(f'INSERT INTO {kind}_accounts VALUES(NULL,0)')
            db.execute(f'CREATE TABLE {kind}_runs(status TEXT,finished_at REAL)')
            db.execute(f"INSERT INTO {kind}_runs VALUES('blocked',100)")
    class Process:
        terminated = 0
        wait_error = None
        terminate_error = None
        started = 123.5
        child = False
        def create_time(self): return self.started
        def is_running(self): return True
        def cwd(self): return str(tmp_path)
        def cmdline(self): return ['python.exe', str(tmp_path / 'scripts/run_streamlit_web.py')]
        def children(self, recursive): return [object()] if self.child else []
        def terminate(self):
            self.terminated += 1
            if self.terminate_error:
                raise self.terminate_error
        def wait(self, timeout):
            if self.wait_error:
                raise self.wait_error
            return 0
    process = Process()
    monkeypatch.setattr(module.psutil, 'Process', lambda pid: process)
    args = ['handoff', '--pid', '4321', '--process-create-time', '123.5',
            '--owner-id', 'backend:4321:original-nonce', '--generation', '1',
            '--account-id', 'review:A', '--evidence', str(tmp_path / 'handoff.json')]
    monkeypatch.setattr(sys, 'argv', args)
    return module, process, store, original, args, tmp_path


def test_known_queued_only_service_handoff_preserves_original_command_and_api_release(isolated):
    module, process, store, original, _, root = isolated
    module.main()
    evidence = json.loads((root / 'handoff.json').read_text())
    assert process.terminated == 1
    assert evidence['stopped'] and evidence['released']
    assert evidence['stop_outcome'] == 'confirmed_dead'
    assert store.snapshot('review:A')['owner']['state'] == 'released'
    assert store.get(original['command_id']) == original


@pytest.mark.parametrize('argument,value', [('--owner-id', 'backend:4321:other-nonce'),
    ('--generation', '2'), ('--account-id', 'other-account'), ('--process-create-time', '123.4')])
def test_exact_original_process_and_owner_fields_are_required(isolated, argument, value):
    module, process, store, _, args, _ = isolated
    args[args.index(argument) + 1] = value
    with pytest.raises(RuntimeError):
        module.main()
    assert process.terminated == 0
    assert store.snapshot('review:A')['owner']['state'] == 'active'


@pytest.mark.parametrize('change', ['referenced-run', 'unknown-run', 'unfinished-run', 'lease-only', 'legacy-window'])
def test_unknown_or_unfinished_original_background_blocks_termination(isolated, change):
    module, process, store, _, _, root = isolated
    with sqlite3.connect(root / 'data/account_refresh.db') as db:
        if change == 'referenced-run':
            db.execute("UPDATE smart_accounts SET run_id='original',lease_until=0")
        elif change == 'lease-only':
            db.execute('UPDATE smart_accounts SET run_id=NULL,lease_until=1000')
        elif change == 'legacy-window':
            with sqlite3.connect(root / 'data/account_manual_windows.db') as manual:
                manual.execute('CREATE TABLE manual_window_jobs(state TEXT)')
                manual.execute("INSERT INTO manual_window_jobs VALUES('outcome_unknown')")
        elif change == 'unknown-run':
            db.execute("UPDATE playback_runs SET status='outcome_unknown'")
        else:
            db.execute('UPDATE refresh_runs SET finished_at=NULL')
    with pytest.raises(RuntimeError):
        module.main()
    assert process.terminated == 0
    assert store.snapshot('review:A')['owner']['state'] == 'active'


@pytest.mark.parametrize('failure', ['wait', 'terminate'])
def test_unconfirmed_termination_records_unknown_and_never_releases_owner(isolated, failure):
    module, process, store, original, _, root = isolated
    if failure == 'wait':
        process.wait_error = psutil.TimeoutExpired(5, pid=4321)
    else:
        process.terminate_error = psutil.AccessDenied(pid=4321)
    with pytest.raises((psutil.TimeoutExpired, psutil.AccessDenied)):
        module.main()
    evidence = json.loads((root / 'handoff.json').read_text())
    assert evidence['phase'] == 'termination_unconfirmed'
    assert evidence['termination_requested'] is True
    assert evidence['stop_outcome'] == 'unknown'
    assert evidence['stopped'] is False and evidence['released'] is False
    assert evidence['error_type']
    assert store.snapshot('review:A')['owner']['state'] == 'active'
    assert store.get(original['command_id']) == original


def test_child_process_prevents_service_termination(isolated):
    module, process, store, _, _, _ = isolated
    process.child = True
    with pytest.raises(RuntimeError):
        module.main()
    assert process.terminated == 0
    assert store.snapshot('review:A')['owner']['state'] == 'active'
