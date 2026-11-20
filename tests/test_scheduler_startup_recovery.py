"""Startup failures must be visible and must not restart unknown work."""
from types import SimpleNamespace

from src.scheduler import runner


def _reset(monkeypatch):
    statuses = []
    monkeypatch.setattr(runner, 'scheduler_instance', None)
    monkeypatch.setattr(runner, '_worker_thread', None)
    monkeypatch.setattr(runner, '_worker_failed', False)
    monkeypatch.setattr(runner, '_startup_failed', False)
    monkeypatch.setattr(runner, '_service_status', lambda *a, **kw: statuses.append((a, kw)))
    return statuses


def test_missing_migration_stops_before_scheduler_or_worker(monkeypatch):
    statuses = _reset(monkeypatch)
    monkeypatch.setattr(runner, 'ensure_migrated', lambda **kw: False)
    monkeypatch.setattr(runner, 'CronScheduler', lambda: (_ for _ in ()).throw(AssertionError('must not start')))
    assert runner.start_scheduler() is False
    assert statuses[-1][1]['error_code'] == 'migration_required'
    assert runner._worker_thread is None


def test_startup_does_not_duplicate_threads_on_ui_rerun(monkeypatch):
    _reset(monkeypatch)
    started = []
    monkeypatch.setattr(runner, 'ensure_migrated', lambda **kw: True)
    monkeypatch.setattr(runner, 'CronScheduler', lambda: SimpleNamespace(start=lambda: None))
    monkeypatch.setattr(runner, 'TaskQueue', lambda: object())
    monkeypatch.setattr(runner, '_seed_builtin_tasks', lambda: None)
    monkeypatch.setattr(runner.threading, 'Thread', lambda **kw: SimpleNamespace(
        start=lambda: started.append(kw), is_alive=lambda: True))
    assert runner.start_scheduler() is True
    assert runner.start_scheduler() is True
    assert len(started) == 1


def test_worker_failure_is_latched_and_records_no_exception_secrets(monkeypatch):
    statuses = _reset(monkeypatch)
    closed = []
    def fail(_):
        raise RuntimeError('cookie=secret')
    runner._run_worker(SimpleNamespace(worker_loop=fail, close=lambda: closed.append(True)))
    assert runner._worker_failed is True
    assert closed == [True]
    assert statuses[-1][0] == ('worker', 'failed')
    assert 'secret' not in str(statuses)
    monkeypatch.setattr(runner, 'ensure_migrated', lambda **kw: (_ for _ in ()).throw(AssertionError('must remain stopped')))
    assert runner.start_scheduler() is False


def test_unexpected_worker_exit_is_visible_and_not_restarted(monkeypatch):
    statuses = _reset(monkeypatch)
    runner._run_worker(SimpleNamespace(worker_loop=lambda _: None, close=lambda: None))
    assert runner._worker_failed is True
    assert statuses[-1][0] == ('worker', 'stopped')


def test_partial_startup_failure_requires_manual_service_restart(monkeypatch):
    statuses = _reset(monkeypatch)
    monkeypatch.setattr(runner, 'ensure_migrated', lambda **kw: True)
    def fail():
        raise RuntimeError('private-credential')
    monkeypatch.setattr(runner, 'CronScheduler', fail)
    assert runner.start_scheduler() is False
    assert runner._startup_failed is True
    count = len(statuses)
    assert runner.start_scheduler() is False
    assert len(statuses) == count
    assert 'private-credential' not in str(statuses)
