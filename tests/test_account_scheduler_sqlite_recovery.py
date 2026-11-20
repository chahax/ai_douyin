"""Local SQLite scan contention handling and explicit offline WAL initialization."""
import importlib.util
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = 'src.scheduler'
    spec.loader.exec_module(module)
    return module


def sqlite_error(code):
    error = sqlite3.OperationalError('local sqlite error')
    error.sqlite_errorcode = code
    return error


@pytest.fixture
def backend():
    return load('isolated_sqlite_recovery_backend', 'src/scheduler/account_refresh.py')


def fake_cron(monkeypatch, refresh, playback, update, completions=None):
    import src.scheduler as scheduler_package
    from src.scheduler import deployment_maintenance
    monkeypatch.setattr(scheduler_package, 'runner', SimpleNamespace(_worker_failed=False, _worker_thread=None), raising=False)
    class Scheduler:
        running = False
        def __init__(self, **kwargs):
            self.jobs = {}
        def add_job(self, function, *args, **kwargs):
            function._qa_job_options = kwargs
            self.jobs[kwargs['id']] = function
        def start(self):
            self.running = True
    replacements = {
        'src.scheduler.deployment_maintenance': SimpleNamespace(resume_pending=lambda: None,
            has_active_hold=deployment_maintenance.has_active_hold),
        'apscheduler.schedulers.background': SimpleNamespace(BackgroundScheduler=Scheduler),
        'apscheduler.triggers.cron': SimpleNamespace(CronTrigger=object),
        'apscheduler.triggers.interval': SimpleNamespace(IntervalTrigger=object),
        'src.scheduler.models': SimpleNamespace(ScheduledTask=object, TriggerType=object),
        'src.scheduler.queue': SimpleNamespace(TaskQueue=object),
        'src.shared.database': SimpleNamespace(SessionLocal=object),
        'src.scheduler.account_refresh': SimpleNamespace(refresh_due_accounts=refresh, update_service_status=update,
            recover_requested_accounts=completions or (lambda **kwargs: None)),
        'src.scheduler.account_playback': SimpleNamespace(dispatch_due_accounts=playback),
    }
    monkeypatch.setattr(scheduler_package, 'account_refresh', replacements['src.scheduler.account_refresh'], raising=False)
    for name, value in replacements.items():
        monkeypatch.setitem(sys.modules, name, value)
    cron = load('isolated_sqlite_recovery_cron', 'src/scheduler/cron.py')
    scheduler = cron.CronScheduler()
    monkeypatch.setattr(scheduler, 'sync_from_db', lambda: None)
    scheduler.start()
    return scheduler._scheduler.jobs


def test_human_completion_has_own_two_second_lane_without_running_other_scans(monkeypatch):
    calls=[]
    forbidden=lambda **kwargs: (_ for _ in ()).throw(AssertionError('must not dispatch business'))
    jobs=fake_cron(monkeypatch,forbidden,forbidden,lambda *args,**kwargs:None,
                   completions=lambda **kwargs:calls.append(kwargs))
    job=jobs['account_human_completion']
    assert job._qa_job_options['seconds']==2 and job._qa_job_options['max_instances']==1
    job()
    assert calls==[{'requested_only':True}]


def test_automatic_platform_window_scan_is_wired_without_a_frontend_click(monkeypatch):
    calls,statuses=[],[]
    monkeypatch.setitem(sys.modules,'src.scheduler.account_manual_windows',SimpleNamespace(
        dispatch_human_windows=lambda:calls.append('scan')))
    jobs=fake_cron(monkeypatch,lambda **k:None,lambda **k:None,
        lambda component,status,**kwargs:statuses.append((component,status)))
    assert 'account_manual_windows' in jobs
    jobs['account_manual_windows']()
    assert calls==['scan'] and statuses[-1]==('manual_windows','healthy')


@pytest.mark.parametrize('code', [sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_BUSY | (2 << 8)])
@pytest.mark.parametrize('job_id', ['account_information_refresh', 'account_automatic_playback'])
def test_known_sqlite_contention_waits_for_next_scheduled_scan_without_immediate_retry(monkeypatch, job_id, code):
    calls = []
    statuses = []
    def scan(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise sqlite_error(code)
    jobs = fake_cron(monkeypatch, scan, scan, lambda component, status, **kwargs: statuses.append((component, status, kwargs)))
    jobs[job_id]()
    assert len(calls) == 1
    assert statuses[-1][1] == 'degraded' and statuses[-1][2]['error_code'] == 'scheduler_database_busy'
    jobs[job_id]()  # Simulate only the next regular timer invocation.
    assert len(calls) == 2
    assert calls[0]['reason'] == 'startup_catchup' and calls[1]['reason'] == 'periodic'
    assert not any(status == 'manual_required' for _, status, _ in statuses)


@pytest.mark.parametrize('error', [RuntimeError('ordinary failure'), sqlite_error(sqlite3.SQLITE_IOERR),
                                 sqlite3.OperationalError('database is locked')])
def test_unclassified_or_other_errors_remain_latched(monkeypatch, error):
    calls = []
    statuses = []
    def scan(**kwargs):
        calls.append(kwargs)
        raise error
    jobs = fake_cron(monkeypatch, scan, scan, lambda component, status, **kwargs: statuses.append((component, status, kwargs)))
    jobs['account_automatic_playback']()
    jobs['account_automatic_playback']()
    assert len(calls) == 1
    assert statuses[-1][1] == 'manual_required'


def test_error_status_write_failure_has_local_evidence_and_busy_scan_can_run_later(monkeypatch, caplog):
    scans = []
    status_attempts = []
    def scan(**kwargs):
        scans.append(kwargs)
        if len(scans) == 1:
            raise sqlite_error(sqlite3.SQLITE_BUSY)
    def status(component, state, **kwargs):
        status_attempts.append((component, state))
        raise sqlite_error(sqlite3.SQLITE_BUSY)
    jobs = fake_cron(monkeypatch, scan, scan, status)
    jobs['account_automatic_playback']()
    assert scans and len(scans) == 1
    assert status_attempts == [('playback_schedule', 'degraded')]
    assert 'Automation status not saved' in caplog.text and 'Local SQLite contention' in caplog.text
    jobs['account_automatic_playback']()
    assert len(scans) == 2
    jobs['automation_heartbeat']()
    assert 'Automation status not saved' in caplog.text


def test_failed_status_persistence_does_not_unlatch_nonbusy_failure(monkeypatch):
    scans = []
    def scan(**kwargs):
        scans.append(kwargs)
        raise RuntimeError('fatal scan failure')
    def status(*args, **kwargs):
        raise sqlite_error(sqlite3.SQLITE_LOCKED)
    jobs = fake_cron(monkeypatch, scan, scan, status)
    jobs['account_information_refresh']()
    jobs['account_information_refresh']()
    assert len(scans) == 1


def test_later_scan_retains_unknown_original_run_instead_of_redispatch(backend, tmp_path, monkeypatch):
    ar = backend
    db = tmp_path / 'schedule.db'
    original = ar.claim('A', 'a', now=100, path=db)
    calls = []
    def scan(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise sqlite_error(sqlite3.SQLITE_BUSY)
        try:
            assert ar.claim('A', 'a', now=5000, path=db) is None
        except ImportError as exc:
            pytest.fail('Isolated scan dependency was not prepared: '+str(exc))
    jobs = fake_cron(monkeypatch, scan, scan, lambda *args, **kwargs: None)
    jobs['account_information_refresh']()
    jobs['account_information_refresh']()
    state = ar.snapshot(db)
    assert len(state['runs']) == 1
    assert state['runs'][0]['run_id'] == original and state['runs'][0]['status'] == 'outcome_unknown'
    assert state['accounts'][0]['run_id'] == original


def test_offline_wal_initializer_is_explicit_idempotent_and_preserves_business_state(backend, tmp_path, monkeypatch):
    ar = backend
    db = tmp_path / 'schedule.db'
    ar.pause_account('A', 'a', 'original incident', path=db)
    before = ar.snapshot(db)
    with pytest.raises(ValueError, match='空闲'):
        ar.initialize_wal_storage(path=db)
    report = ar.initialize_wal_storage(path=db, idle_confirmed=True)
    assert report['previous_journal_mode'] == 'delete' and report['journal_mode'] == 'wal' and report['changed']
    second = ar.initialize_wal_storage(path=db, idle_confirmed=True)
    assert second['journal_mode'] == 'wal' and not second['changed']
    assert ar.snapshot(db) == before
    statements = []
    original_connect = sqlite3.connect
    def traced(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection
    monkeypatch.setattr(ar.sqlite3, 'connect', traced)
    ar.snapshot(db)
    ar.snapshot(db)
    assert not any('JOURNAL_MODE=' in sql.replace(' ', '').upper() for sql in statements)


@pytest.mark.parametrize('pending', ['run', 'token', 'requested', 'recovering'])
def test_offline_wal_initializer_refuses_pending_original_operations(backend, tmp_path, pending):
    ar = backend
    db = tmp_path / 'schedule.db'
    if pending == 'run':
        ar.claim('A', 'a', now=100, path=db)
    else:
        ar.pause_account('A', 'a', 'original incident', path=db)
        with ar.connect(db) as connection:
            if pending == 'token':
                connection.execute("UPDATE account_controls SET recovery_token='original'")
            else:
                connection.execute('UPDATE account_controls SET state=?', ('recovery_requested' if pending == 'requested' else 'recovering',))
    with pytest.raises(RuntimeError, match='原'):
        ar.initialize_wal_storage(path=db, idle_confirmed=True)
    with sqlite3.connect(db) as connection:
        assert connection.execute('PRAGMA journal_mode').fetchone()[0] == 'delete'


def test_wal_allows_commit_during_read_transaction_but_does_not_remove_writer_mutex(backend, tmp_path):
    ar = backend
    db = tmp_path / 'schedule.db'
    ar.snapshot(db)
    reader = sqlite3.connect(db)
    writer = sqlite3.connect(db, timeout=0.03)
    try:
        reader.execute('BEGIN')
        reader.execute('SELECT COUNT(*) FROM automation_service').fetchone()
        writer.execute("INSERT INTO automation_service VALUES('offline','healthy','','',1)")
        with pytest.raises(sqlite3.OperationalError) as busy:
            writer.commit()
        assert busy.value.sqlite_errorcode == sqlite3.SQLITE_BUSY
        writer.rollback()
    finally:
        reader.rollback()
        reader.close()
        writer.close()
    ar.initialize_wal_storage(path=db, idle_confirmed=True)
    reader = sqlite3.connect(db)
    writer = sqlite3.connect(db, timeout=0.03)
    other_writer = sqlite3.connect(db, timeout=0.03)
    try:
        reader.execute('BEGIN')
        assert reader.execute('SELECT COUNT(*) FROM automation_service').fetchone()[0] == 0
        writer.execute("INSERT INTO automation_service VALUES('offline','healthy','','',1)")
        writer.commit()  # The live reader no longer blocks this commit.
        assert reader.execute('SELECT COUNT(*) FROM automation_service').fetchone()[0] == 0
        writer.execute('BEGIN IMMEDIATE')
        with pytest.raises(sqlite3.OperationalError) as busy:
            other_writer.execute('BEGIN IMMEDIATE')
        assert busy.value.sqlite_errorcode == sqlite3.SQLITE_BUSY
    finally:
        reader.rollback()
        reader.close()
        writer.rollback()
        writer.close()
        other_writer.close()
