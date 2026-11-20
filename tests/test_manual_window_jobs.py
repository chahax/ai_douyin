"""Synthetic manual-window workers; no real browser/platform, UI or production data."""
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def jobs(monkeypatch):
    # These tests exercise the legacy worker, independent of local live settings.
    monkeypatch.setenv('AI_DOUYIN_BROWSER_CONTROL', '0')
    module = load('isolated_manual_window_jobs', 'src/operations_accounts/manual_window_jobs.py')
    yield module
    with module._registry_lock:
        threads = list(module._registry.values())
    for thread in threads:
        thread.join(timeout=6)
        assert not thread.is_alive()


def helper(monkeypatch, function):
    monkeypatch.setitem(sys.modules, 'src.operations_accounts.manual_handling', SimpleNamespace(open_bound_manual_handling_window=function))


def terminal(jobs, db, uuid='A', key='a'):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        result = jobs.get_manual_window_job(uuid, key, path=db)
        if result and result['state'] in {'closed', 'failed', 'outcome_unknown'}:
            return result
        time.sleep(0.01)
    pytest.fail('fake manual-window worker failed to settle')


def seed(jobs, db, *, state='running', owner_pid=None, owner_nonce=None, uuid='A', key='a', job_id='original'):
    with jobs._connection(db, create=True) as connection:
        connection.execute('INSERT OR IGNORE INTO manual_window_accounts VALUES(?,?)', (uuid, key))
        connection.execute('''INSERT INTO manual_window_jobs(job_id,account_uuid,account_key,requested_by,state,phase,
            owner_pid,owner_nonce,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)''',
            (job_id, uuid, key, 'original-admin', state, 'window_open_waiting_close',
             jobs._PID if owner_pid is None else owner_pid, jobs._SESSION_NONCE if owner_nonce is None else owner_nonce, 100, 100))


def test_click_returns_before_window_closes_progress_polls_and_closed_waits_for_helper_cleanup(jobs, tmp_path, monkeypatch):
    db = tmp_path / 'windows.db'
    # Measure request/worker decoupling separately from cold schema/WAL setup.
    with jobs._connection(db, create=True):
        pass
    opened, release, closing, cleaned = (threading.Event() for _ in range(4))
    calls = []
    runtime = object()
    def window(uuid, key, *, runtime, on_progress):
        calls.append((uuid, key, runtime))
        on_progress('validating')
        on_progress('window_open_waiting_close')
        opened.set()
        assert release.wait(5)
        on_progress('closed')
        closing.set()
        assert cleaned.wait(5)
        return SimpleNamespace(closed=True)
    helper(monkeypatch, window)
    started = time.monotonic()
    receipt = jobs.start_manual_window_job('A', 'a', 'admin', runtime=runtime, path=db)
    try:
        assert time.monotonic() - started < 1
        assert opened.wait(2)
        running = jobs.get_manual_window_job('A', 'a', path=db)
        assert running['state'] == 'running' and running['phase'] == 'window_open_waiting_close'
        assert jobs.has_pending_manual_window_job('A', 'a', path=db)
        for _ in range(3):
            assert jobs.get_manual_window_job('A', 'a', path=db)['job_id'] == receipt['job_id']
        release.set()
        assert closing.wait(2)
        not_closed = jobs.get_manual_window_job('A', 'a', path=db)
        assert not_closed['state'] == 'running' and not_closed['phase'] == 'closing'
        assert jobs.has_pending_manual_window_job('A', 'a', path=db)
    finally:
        release.set()
        cleaned.set()
    result = terminal(jobs, db)
    assert result['state'] == 'closed' and result['finished_at'] is not None
    assert not jobs.has_pending_manual_window_job('A', 'a', path=db)
    assert calls == [('A', 'a', runtime)]
    assert 'owner_pid' not in result and 'owner_nonce' not in result
    assert jobs.get_manual_window_job('A', 'a', path=db)['state'] == 'closed'
    assert len(calls) == 1  # Polling never opens another window.


def test_concurrent_and_cross_session_clicks_return_original_active_job(jobs, tmp_path, monkeypatch):
    db = tmp_path / 'windows.db'
    release = threading.Event()
    calls = []
    def window(uuid, key, *, runtime, on_progress):
        calls.append(key)
        on_progress('window_open_waiting_close')
        assert release.wait(5)
        return SimpleNamespace(closed=True)
    helper(monkeypatch, window)
    barrier = threading.Barrier(3)
    def click(index):
        barrier.wait()
        return jobs.start_manual_window_job('A', 'a', 'admin-' + str(index), path=db)
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            responses = list(pool.map(click, range(3)))
        assert len({row['job_id'] for row in responses}) == 1
        assert sum(not row['reused'] for row in responses) == 1
        assert jobs.start_manual_window_job('A', 'a', 'another-session', path=db)['reused']
    finally:
        release.set()
    terminal(jobs, db)
    assert calls == ['a']


@pytest.mark.parametrize('error,expected', [(TimeoutError('Cookie: secret-value'), 'manual_window_timeout'),
                                         (RuntimeError('https://private/?token=secret-value'), 'manual_window_failed')])
def test_worker_failure_is_safe_and_polling_does_not_rerun(jobs, tmp_path, monkeypatch, error, expected):
    db = tmp_path / 'windows.db'
    calls = []
    def window(*args, **kwargs):
        calls.append(1)
        raise error
    helper(monkeypatch, window)
    receipt = jobs.start_manual_window_job('A', 'a', 'admin', path=db)
    result = terminal(jobs, db)
    assert result['state'] == 'failed' and result['error_code'] == expected
    assert result['job_id'] == receipt['job_id'] and 'secret-value' not in json.dumps(result)
    for _ in range(3):
        assert jobs.get_manual_window_job('A', 'a', path=db)['state'] == 'failed'
    assert calls == [1]
    assert not jobs.has_pending_manual_window_job('A', 'a', path=db)


def test_unknown_closed_result_blocks_new_job_and_preserves_id(jobs, tmp_path, monkeypatch):
    db = tmp_path / 'windows.db'
    calls = []
    def window(*args, **kwargs):
        calls.append(1)
        return SimpleNamespace(closed=False)
    helper(monkeypatch, window)
    original = jobs.start_manual_window_job('A', 'a', 'admin', path=db)
    result = terminal(jobs, db)
    assert result['state'] == 'outcome_unknown'
    again = jobs.start_manual_window_job('A', 'a', 'admin', path=db)
    assert again['job_id'] == original['job_id'] and again['reused']
    assert calls == [1]


@pytest.mark.parametrize('ownership', ['foreign_pid', 'foreign_nonce', 'missing_registry'])
def test_orphan_projection_is_read_only_and_explicit_click_persists_unknown_without_requeue(jobs, tmp_path, monkeypatch, ownership):
    db = tmp_path / 'windows.db'
    if ownership == 'foreign_pid':
        monkeypatch.setattr(jobs, '_owner_process_running', lambda pid: False)
    seed(jobs, db, owner_pid=os.getpid() + 1 if ownership == 'foreign_pid' else None,
         owner_nonce='old-nonce' if ownership == 'foreign_nonce' else None)
    helper(monkeypatch, lambda *args, **kwargs: pytest.fail('orphan must not relaunch'))
    before = db.read_bytes()
    result = jobs.get_manual_window_job('A', 'a', path=db)
    assert result['state'] == 'outcome_unknown' and result['job_id'] == 'original'
    assert db.read_bytes() == before
    assert jobs.has_pending_manual_window_job('A', 'a', path=db)
    original = jobs.start_manual_window_job('A', 'a', 'new-admin', path=db)
    assert original['state'] == 'outcome_unknown' and original['job_id'] == 'original' and original['reused']
    with sqlite3.connect(db) as connection:
        assert connection.execute('SELECT COUNT(*) FROM manual_window_jobs').fetchone()[0] == 1
        assert connection.execute('SELECT state FROM manual_window_jobs').fetchone()[0] == 'outcome_unknown'


def test_conflicting_account_keys_and_empty_actor_cannot_hijack_existing_task(jobs, tmp_path):
    db = tmp_path / 'windows.db'
    seed(jobs, db, state='outcome_unknown')
    for uuid, key in [('A', 'other'), ('B', 'a')]:
        with pytest.raises(ValueError, match='绑定'):
            jobs.start_manual_window_job(uuid, key, 'admin', path=db)
        with pytest.raises(ValueError, match='绑定'):
            jobs.get_manual_window_job(uuid, key, path=db)
    with pytest.raises(ValueError, match='操作者'):
        jobs.start_manual_window_job('A', 'a', ' ', path=db)
    assert jobs.get_manual_window_job('A', 'a', path=db)['job_id'] == 'original'


def test_known_thread_start_failure_is_failed_not_unknown_and_does_not_call_helper(jobs, tmp_path, monkeypatch):
    db = tmp_path / 'windows.db'
    helper(monkeypatch, lambda *args, **kwargs: pytest.fail('thread never started'))
    monkeypatch.setattr(jobs.threading, 'Thread', lambda **kwargs: SimpleNamespace(
        start=lambda: (_ for _ in ()).throw(RuntimeError('private payload')), is_alive=lambda: False))
    result = jobs.start_manual_window_job('A', 'a', 'admin', path=db)
    assert result['state'] == 'failed' and result['error_code'] == 'worker_start_failed'
    assert not jobs.has_pending_manual_window_job('A', 'a', path=db)
    assert 'private payload' not in json.dumps(result)


def test_ro_poll_does_not_create_database_and_unreadable_state_is_not_no_pending(jobs, tmp_path):
    db = tmp_path / 'missing.db'
    assert jobs.get_manual_window_job('A', 'a', path=db) is None
    assert not jobs.has_pending_manual_window_job('A', 'a', path=db)
    assert not db.exists()
    db.write_text('this is not sqlite', encoding='utf-8')
    with pytest.raises(sqlite3.DatabaseError):
        jobs.has_pending_manual_window_job('A', 'a', path=db)


@pytest.mark.parametrize('state', ['starting', 'running', 'outcome_unknown', 'closed', 'failed'])
def test_account_completion_and_legacy_probe_share_sibling_job_store_gate(jobs, tmp_path, state):
    account_db = tmp_path / 'account_refresh.db'
    windows_db = tmp_path / 'account_manual_windows.db'
    backend = load('isolated_manual_window_account_gate', 'src/scheduler/account_refresh.py')
    backend.pause_account('A', 'a', 'original cause', path=account_db)
    seed(jobs, windows_db, state=state)
    expected_pending = state not in {'closed', 'failed'}
    assert jobs.has_pending_manual_window_job('A', 'a', path=windows_db) is expected_pending
    result = backend.complete_account_handling('A', 'a', handled_by='admin', path=account_db)
    assert result['accepted'] is not expected_pending
    if expected_pending:
        assert result['state'] == 'manual_window_pending'
        assert backend.request_account_recovery('A', 'a', path=account_db)
        assert backend._claim_recovery('A', 'a', path=account_db) is None
    else:
        assert backend._claim_recovery('A', 'a', path=account_db)


def test_window_store_failure_blocks_complete_without_mutating_original_control(jobs, tmp_path):
    account_db = tmp_path / 'account_refresh.db'
    windows_db = tmp_path / 'account_manual_windows.db'
    backend = load('isolated_manual_window_failed_store_gate', 'src/scheduler/account_refresh.py')
    backend.pause_account('A', 'a', 'original cause', path=account_db)
    before = backend.snapshot(account_db)
    windows_db.write_text('invalid database', encoding='utf-8')
    with pytest.raises(sqlite3.DatabaseError):
        backend.complete_account_handling('A', 'a', handled_by='admin', path=account_db)
    assert backend.snapshot(account_db) == before


def test_manual_window_starting_after_probe_claim_cannot_restore_account(jobs, tmp_path):
    account_db = tmp_path / 'account_refresh.db'
    windows_db = tmp_path / 'account_manual_windows.db'
    backend = load('isolated_manual_window_late_gate', 'src/scheduler/account_refresh.py')
    backend.pause_account('A', 'a', 'original cause', path=account_db)
    assert backend.request_account_recovery('A', 'a', path=account_db)
    token = backend._claim_recovery('A', 'a', path=account_db)
    seed(jobs, windows_db, state='running')
    assert not backend._finish_recovery('A', 'a', token, healthy=True, status='active', path=account_db)
    assert backend.snapshot(account_db)['controls'][0]['state'] == 'paused'


def test_unrecognized_nonterminal_state_is_unknown_and_reuses_original_without_relaunch(jobs, tmp_path, monkeypatch):
    db = tmp_path / 'windows.db'
    seed(jobs, db, state='future_nonterminal_state')
    helper(monkeypatch, lambda *args, **kwargs: pytest.fail('unknown state cannot relaunch'))
    before = db.read_bytes()
    assert jobs.get_manual_window_job('A', 'a', path=db)['state'] == 'outcome_unknown'
    assert db.read_bytes() == before
    assert jobs.has_pending_manual_window_job('A', 'a', path=db)
    receipt = jobs.start_manual_window_job('A', 'a', 'admin', path=db)
    assert receipt['reused'] and receipt['job_id'] == 'original' and receipt['state'] == 'outcome_unknown'
    with sqlite3.connect(db) as connection:
        assert connection.execute('SELECT COUNT(*) FROM manual_window_jobs').fetchone()[0] == 1
        assert connection.execute('SELECT state FROM manual_window_jobs').fetchone()[0] == 'outcome_unknown'


def test_fresh_wal_store_commits_phase_and_closed_while_old_reader_remains_open(jobs, tmp_path, monkeypatch):
    db = tmp_path / 'windows.db'
    opened, advance, closing, cleanup = (threading.Event() for _ in range(4))
    def window(*args, on_progress, **kwargs):
        on_progress('window_open_waiting_close')
        opened.set()
        assert advance.wait(5)
        on_progress('closed')
        closing.set()
        assert cleanup.wait(5)
        return SimpleNamespace(closed=True)
    helper(monkeypatch, window)
    original = jobs.start_manual_window_job('A', 'a', 'admin', path=db)
    reader = sqlite3.connect(db)
    try:
        assert opened.wait(2)
        assert reader.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
        reader.execute('BEGIN')
        assert reader.execute('SELECT state FROM manual_window_jobs').fetchone()[0] == 'running'
        advance.set()
        assert closing.wait(2)  # The phase UPDATE committed despite the held read transaction.
        current = jobs.get_manual_window_job('A', 'a', path=db)
        assert current['phase'] == 'closing' and current['job_id'] == original['job_id']
        cleanup.set()
        closed = terminal(jobs, db)
        assert closed['state'] == 'closed' and closed['job_id'] == original['job_id']
        assert reader.execute('SELECT state FROM manual_window_jobs').fetchone()[0] == 'running'
        assert jobs.get_manual_window_job('A', 'a', path=db)['state'] == 'closed'
    finally:
        advance.set()
        cleanup.set()
        reader.rollback()
        reader.close()


def test_normal_and_readonly_connections_never_repeat_journal_mode_assignment(jobs, tmp_path, monkeypatch):
    db = tmp_path / 'windows.db'
    seed(jobs, db, state='outcome_unknown')
    statements = []
    original_connect = sqlite3.connect
    def traced(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection
    monkeypatch.setattr(jobs.sqlite3, 'connect', traced)
    assert jobs.get_manual_window_job('A', 'a', path=db)['state'] == 'outcome_unknown'
    assert jobs.has_pending_manual_window_job('A', 'a', path=db)
    assert jobs.start_manual_window_job('A', 'a', 'admin', path=db)['job_id'] == 'original'
    assert not any('JOURNAL_MODE=' in sql.replace(' ', '').upper() for sql in statements)


def test_existing_delete_store_with_original_job_is_not_automatically_migrated(jobs, tmp_path):
    db = tmp_path / 'legacy_windows.db'
    seed(jobs, db, state='running')
    connection = sqlite3.connect(db)
    try:
        assert connection.execute('PRAGMA journal_mode=DELETE').fetchone()[0] == 'delete'
    finally:
        connection.close()
    with jobs._connection(db, create=True) as connection:
        assert connection.execute('PRAGMA journal_mode').fetchone()[0] == 'delete'
        row = connection.execute('SELECT job_id,state FROM manual_window_jobs').fetchone()
        assert row['job_id'] == 'original' and row['state'] == 'running'
