"""Local SQLite/fake-service checks; never contact a platform or paid provider."""
import importlib.util
import json
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

# Loading the isolated module avoids unrelated queue/platform imports in core state tests.
spec = importlib.util.spec_from_file_location('isolated_account_refresh', Path(__file__).parents[1] / 'src/scheduler/account_refresh.py')
ar = importlib.util.module_from_spec(spec)
ar.__package__ = 'src.scheduler'
spec.loader.exec_module(ar)


def control(db):
    return ar.snapshot(db)['controls'][0]


def test_pause_persists_and_blocks_both_plans(tmp_path):
    db = tmp_path / 'refresh.db'
    ar.pause_account('A', 'a', '人工处理', path=db)
    assert control(db)['state'] == 'paused'
    assert ar.claim('A', 'a', now=100, path=db) is None
    assert ar.claim_smart('A', 'a', now=100, path=db) is None
    assert ar.claim('B', 'b', now=100, path=db)


def test_migrated_snapshot_needs_no_write_lock_or_schema_ddl(tmp_path, monkeypatch):
    db = tmp_path / 'refresh.db'
    ar.snapshot(db)
    statements = []
    original_connect = sqlite3.connect
    def traced_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection
    monkeypatch.setattr(ar.sqlite3, 'connect', traced_connect)
    with original_connect(db) as writer:
        writer.execute('BEGIN IMMEDIATE')
        assert ar.snapshot(db)['controls'] == []
        assert not any(statement.lstrip().upper().startswith(('BEGIN', 'CREATE', 'INSERT', 'UPDATE', 'DELETE')) for statement in statements)


def test_existing_malformed_schema_fails_explicitly(tmp_path):
    db = tmp_path / 'malformed.db'
    with sqlite3.connect(db) as connection:
        connection.execute('CREATE TABLE refresh_policy(id INTEGER PRIMARY KEY, enabled INTEGER)')
    with pytest.raises(sqlite3.DatabaseError, match='refresh_policy missing interval_seconds'):
        ar.snapshot(db)


def test_missing_default_policy_row_is_repaired_without_replacing_history(tmp_path):
    db = tmp_path / 'refresh.db'
    run = ar.claim('A', 'a', now=100, path=db)
    ar.finish(run, 'completed', {}, now=110, path=db)
    with sqlite3.connect(db) as connection:
        connection.execute('DELETE FROM smart_policy WHERE id=1')
    result = ar.snapshot(db)
    assert result['smart_policy']['enabled'] == 1
    assert result['runs'][0]['run_id'] == run


@pytest.mark.parametrize('status,code', [('blocked', ''), ('failed', 'identity_unavailable'), ('completed', 'human_required'), ('failed', 'login_expired'), ('failed', 'identity_mismatch')])
def test_structured_identity_blocks_pause_immediately(tmp_path, status, code):
    db = tmp_path / 'refresh.db'
    run = ar.claim_smart('A', 'a', now=100, path=db)
    ar.finish_smart(run, status, {'error_code': code}, now=110, path=db)
    assert control(db)['state'] == 'paused'
    assert ar.claim('A', 'a', now=100000, path=db) is None


def test_transient_failures_shared_and_bounded_not_message_guessing(tmp_path):
    db = tmp_path / 'refresh.db'
    for index in range(3):
        claim = ar.claim if index % 2 == 0 else ar.claim_smart
        finish = ar.finish if index % 2 == 0 else ar.finish_smart
        run = claim('A', 'a', now=100 + index * 2000, path=db)
        assert run
        finish(run, 'failed', {'message': '验证码不是结构错误码', 'error_code': 'network_error'}, now=110 + index * 2000, path=db)
        assert control(db)['consecutive_failures'] == index + 1
        assert control(db)['state'] == ('paused' if index == 2 else 'active')
    assert ar.claim_smart('A', 'a', now=100000, path=db) is None


def test_inflight_success_cannot_undo_operator_pause_or_duplicate_receipt(tmp_path):
    db = tmp_path / 'refresh.db'
    run = ar.claim('A', 'a', now=100, path=db)
    ar.pause_account('A', 'a', '检查账号', path=db)
    ar.finish(run, 'completed', {}, now=110, path=db)
    ar.finish(run, 'failed', {'error_code': 'network_error'}, now=120, path=db)
    assert control(db)['state'] == 'paused'
    assert control(db)['consecutive_failures'] == 0
    assert ar.snapshot(db)['runs'][0]['status'] == 'completed'


def test_expired_business_lease_preserves_original_identity(tmp_path):
    db = tmp_path / 'refresh.db'
    run = ar.claim('A', 'a', now=100, path=db)
    assert ar.claim_smart('A', 'a', now=5000, path=db) is None
    assert ar.snapshot(db)['runs'][0]['run_id'] == run
    assert ar.snapshot(db)['runs'][0]['status'] == 'outcome_unknown'
    assert ar.request_account_recovery('A', 'a', path=db)
    assert ar._claim_recovery('A', 'a', now=6000, path=db) is None
    ar.finish(run, 'completed', {}, now=6001, path=db)
    assert ar._claim_recovery('A', 'a', now=6002, path=db)


def test_atomic_claim_across_schedules_and_connections(tmp_path):
    db = tmp_path / 'refresh.db'
    ar.snapshot(db)
    with ThreadPoolExecutor(max_workers=8) as pool:
        runs = list(pool.map(lambda index: (ar.claim if index % 2 else ar.claim_smart)('A', 'a', now=100, path=db), range(8)))
    assert sum(bool(run) for run in runs) == 1


def test_one_recovery_probe_lease_and_identity_mismatch(tmp_path):
    db = tmp_path / 'refresh.db'
    ar.pause_account('A', 'a', '登录后核验', path=db)
    assert ar.request_account_recovery('A', 'a', path=db)
    assert not ar.request_account_recovery('A', 'a', path=db)
    token = ar._claim_recovery('A', 'a', now=100, path=db)
    assert token and ar._claim_recovery('A', 'a', now=101, path=db) is None
    assert ar.claim('A', 'a', now=100, path=db) is None
    assert not ar._finish_recovery('A', 'a', token, healthy=False, status='identity_mismatch', path=db)
    assert control(db)['state'] == 'paused'
    assert ar.request_account_recovery('A', 'a', path=db)
    token = ar._claim_recovery('A', 'a', path=db)
    assert ar._finish_recovery('A', 'a', token, healthy=True, status='active', path=db)
    assert control(db)['state'] == 'active'
    assert all(issue['status'] == 'resolved' for issue in ar.snapshot(db)['issues'])


def test_pause_during_recovery_preserves_lease_and_invalidates_activation(tmp_path):
    db = tmp_path / 'refresh.db'
    ar.pause_account('A', 'a', '检查', path=db)
    ar.request_account_recovery('A', 'a', path=db)
    token = ar._claim_recovery('A', 'a', now=100, path=db)
    ar.pause_account('A', 'a', '暂不恢复', path=db)
    assert not ar.request_account_recovery('A', 'a', path=db)
    assert not ar._finish_recovery('A', 'a', token, healthy=True, status='active', path=db)
    assert control(db)['state'] == 'paused'
    assert ar.request_account_recovery('A', 'a', path=db)


def test_expired_recovery_never_blindly_redispatches(tmp_path):
    db = tmp_path / 'refresh.db'
    ar.pause_account('A', 'a', '检查', path=db)
    ar.request_account_recovery('A', 'a', path=db)
    token = ar._claim_recovery('A', 'a', now=100, path=db)
    assert ar._claim_recovery('A', 'a', now=5000, path=db) is None
    assert control(db)['error_code'] == 'recovery_outcome_unknown'
    assert not ar.request_account_recovery('A', 'a', path=db)
    count = len(ar.snapshot(db)['issues'])
    assert ar._claim_recovery('A', 'a', now=6000, path=db) is None
    assert len(ar.snapshot(db)['issues']) == count
    assert not ar._finish_recovery('A', 'a', token, healthy=True, status='active', path=db)


def test_service_state_and_reason_do_not_store_credentials(tmp_path):
    db = tmp_path / 'refresh.db'
    ar.update_service_status('worker', 'manual_required', message='Authorization: Bearer private-value', error_code='schema_missing', path=db)
    ar.pause_account('A', 'a', 'Cookie: sessionid=private-value', path=db)
    assert 'private-value' not in json.dumps(ar.snapshot(db))
    assert ar.snapshot(db)['service']['worker']['status'] == 'manual_required'


def test_smart_completed_report_reads_structural_maintenance_block(tmp_path):
    log = tmp_path / 'maintenance.json'
    log.write_text(json.dumps({'run_id': 'original', 'error_code': 'human_required'}), encoding='utf8')
    assert ar._smart_error_code({'status': 'completed', 'maintenance_log': str(log), 'maintenance_run_id': 'original'}) == 'human_required'
    assert ar._smart_error_code({'maintenance_log': str(log), 'maintenance_run_id': 'other'}) == ''


def test_recovery_loop_uses_probe_once_and_checks_expected_identity(tmp_path, monkeypatch):
    db = tmp_path / 'refresh.db'
    ar.pause_account('A', 'a', '检查', path=db)
    ar.request_account_recovery('A', 'a', path=db)
    calls = []
    def probe(key, *, headless):
        calls.append(key)
        return SimpleNamespace(healthy=True, status='active', expected=SimpleNamespace(account_uuid='different', account_key='a'))
    monkeypatch.setitem(sys.modules, 'src.operations_accounts.runtime', SimpleNamespace(AccountRuntimeService=lambda: SimpleNamespace(probe_recovery=probe)))
    ar.recover_requested_accounts(path=db)
    ar.recover_requested_accounts(path=db)
    assert calls == ['a']
    assert control(db)['state'] == 'paused'
    assert control(db)['error_code'] == 'account_uuid_mismatch'


@pytest.mark.parametrize('message,visible', [('browser startup timed out', 'browser startup timed out'), ('Cookie: sessionid=private-value', None)])
def test_recovery_exception_diagnostic_is_useful_and_redacted(tmp_path, monkeypatch, message, visible):
    db = tmp_path / 'refresh.db'
    ar.pause_account('A', 'a', '检查', path=db)
    ar.request_account_recovery('A', 'a', path=db)
    class ProbeError(RuntimeError):
        code = 'recovery_probe_failed'
    def fail(*args, **kwargs):
        raise ProbeError(message)
    monkeypatch.setitem(sys.modules, 'src.operations_accounts.runtime', SimpleNamespace(
        AccountRuntimeService=lambda: SimpleNamespace(probe_recovery=fail)))
    ar.recover_requested_accounts(path=db)
    reason = control(db)['reason']
    assert '尚未确认登录过期' in reason
    assert 'private-value' not in str(ar.snapshot(db))
    if visible:
        assert visible in reason


def test_account_exception_isolated_from_other_accounts(tmp_path, monkeypatch):
    db = tmp_path / 'refresh.db'
    profiles = [SimpleNamespace(account_uuid='A', account_key='a'), SimpleNamespace(account_uuid='B', account_key='b')]
    monkeypatch.setitem(sys.modules, 'src.operations_accounts', SimpleNamespace(
        AccountProfileRepository=lambda: SimpleNamespace(db_path='unused', list_active=lambda: profiles),
        AccountBindingRepository=lambda path: SimpleNamespace(get_optional=lambda key: object())))
    monkeypatch.setitem(sys.modules, 'src.operations_accounts.maintenance', SimpleNamespace(AccountMaintenanceService=object))
    monkeypatch.setattr(ar, 'recover_requested_accounts', lambda **kwargs: None)
    visited = []
    def run(profile, *args, **kwargs):
        visited.append(profile.account_key)
        if profile.account_key == 'a':
            raise RuntimeError('Cookie=private-value')
    monkeypatch.setattr(ar, '_refresh_one_account', run)
    ar.refresh_due_accounts(path=db)
    assert visited == ['a', 'b']
    assert control(db)['state'] == 'paused'
    assert 'private-value' not in json.dumps(ar.snapshot(db))


def test_historical_unhealthy_binding_surfaces_without_business_dispatch(tmp_path):
    db = tmp_path / 'refresh.db'
    profile = SimpleNamespace(account_uuid='A', account_key='a')
    bindings = SimpleNamespace(get_optional=lambda key: SimpleNamespace(status='blocked'))
    ar._refresh_one_account(profile, bindings, lambda: pytest.fail('must not dispatch'), reason='periodic', path=db)
    assert control(db)['state'] == 'paused'
    assert control(db)['error_code'] == 'login_unhealthy'
    count = len(ar.snapshot(db)['issues'])
    ar._refresh_one_account(profile, bindings, object, reason='periodic', path=db)
    assert len(ar.snapshot(db)['issues']) == count
    assert not ar.snapshot(db)['runs'] and not ar.snapshot(db)['smart_runs']


def test_cron_heartbeat_survives_task_sync_error_and_refresh_is_bounded(monkeypatch):
    recorded = []
    calls = []
    class Scheduler:
        running = False
        def __init__(self, **kwargs):
            self.jobs = {}
        def add_job(self, function, *args, **kwargs):
            self.jobs[kwargs['id']] = function
        def start(self):
            self.running = True
    def broken_refresh(**kwargs):
        calls.append(kwargs)
        raise RuntimeError('Cookie=private-value')
    runner = SimpleNamespace(_worker_failed=False, _worker_thread=SimpleNamespace(is_alive=lambda: True))
    replacements = {
        'src.scheduler.deployment_maintenance': SimpleNamespace(resume_pending=lambda: None),
        'apscheduler.schedulers.background': SimpleNamespace(BackgroundScheduler=Scheduler),
        'apscheduler.triggers.cron': SimpleNamespace(CronTrigger=object),
        'apscheduler.triggers.interval': SimpleNamespace(IntervalTrigger=object),
        'src.scheduler.models': SimpleNamespace(ScheduledTask=object, TriggerType=object),
        'src.scheduler.queue': SimpleNamespace(TaskQueue=object),
        'src.shared.database': SimpleNamespace(SessionLocal=object),
        'src.scheduler.account_refresh': SimpleNamespace(
            refresh_due_accounts=broken_refresh,
            update_service_status=lambda component, status, **kwargs: recorded.append((component, status, kwargs))),
        'src.scheduler.account_playback': SimpleNamespace(dispatch_due_accounts=lambda **kwargs: recorded.append(('playback_scan', 'called', kwargs))),
        'src.scheduler': SimpleNamespace(runner=runner),
    }
    for name, value in replacements.items():
        monkeypatch.setitem(sys.modules, name, value)
    cron_spec = importlib.util.spec_from_file_location('isolated_cron', Path(__file__).parents[1] / 'src/scheduler/cron.py')
    cron = importlib.util.module_from_spec(cron_spec)
    cron_spec.loader.exec_module(cron)
    scheduler = cron.CronScheduler()
    monkeypatch.setattr(scheduler, 'sync_from_db', lambda: (_ for _ in ()).throw(RuntimeError('schema missing')))
    scheduler.start()
    assert scheduler._scheduler.running
    scheduler._scheduler.jobs['automation_heartbeat']()
    assert any(component == 'worker' and status == 'running' for component, status, _ in recorded)
    runner._worker_failed = True
    count = len(recorded)
    scheduler._scheduler.jobs['automation_heartbeat']()
    assert all(component != 'worker' for component, _, _ in recorded[count:])
    scheduler._scheduler.jobs['account_information_refresh']()
    scheduler._scheduler.jobs['account_information_refresh']()
    assert len(calls) == 1
    assert any(component == 'account_refresh' and status == 'manual_required' for component, status, _ in recorded)
    assert 'private-value' not in json.dumps(recorded)
    # The long-running playback path owns a separate minute scan, unaffected by
    # a stopped legacy account-refresh callback.
    scheduler._scheduler.jobs['account_automatic_playback']()
    assert any(component == 'playback_scan' for component, _, _ in recorded)
    playback_failures = []
    def broken_playback_scan(**kwargs):
        playback_failures.append(kwargs)
        raise RuntimeError('scanner unavailable')
    replacements['src.scheduler.account_playback'].dispatch_due_accounts = broken_playback_scan
    scheduler._scheduler.jobs['account_automatic_playback']()
    scheduler._scheduler.jobs['account_automatic_playback']()
    assert len(playback_failures) == 1
    assert any(component == 'playback_schedule' and status == 'manual_required' for component, status, _ in recorded)


def test_unknown_verification_content_pauses_once_without_claiming_captcha(tmp_path):
    db=tmp_path/'refresh.db'
    run=ar.claim_smart('A','a',now=100,path=db)
    ar.finish_smart(run,'partial',{'error_code':'verification_ui_unconfirmed'},now=110,path=db)
    data=ar.snapshot(db)
    assert control(db)['state']=='paused'
    assert data['issues'][0]['error_code']=='verification_ui_unconfirmed'
    assert '尚未确认可操作验证码' in data['issues'][0]['message']
    assert ar.claim_smart('A','a',now=2000,path=db) is None
    assert ar.claim('A','a',now=2000,path=db) is None
