"""Local automatic-playback admission and bounded dispatch, using only fake maintenance."""
import importlib.util
import json
import sqlite3
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def modules(monkeypatch):
    ar = load('isolated_playback_backend', 'src/scheduler/account_refresh.py')
    ap = load('isolated_playback_dispatch', 'src/scheduler/account_playback.py')
    monkeypatch.setitem(sys.modules, 'src.scheduler.account_playback', ap)
    monkeypatch.setattr(ap, '_backend', lambda: ar)
    return ar, ap


def configure(ar, db, uuid='A', key='a', **kwargs):
    ar.set_playback_policy(uuid, key, True, authorization_reference='user-request-20261018', path=db, **kwargs)


def fake_result(**kwargs):
    values = dict(status='completed', error_code='', message='verified', run_id='maintenance-original',
                  playback_verified_videos=2, actual_watch_seconds=99.5, likes_performed=0, comments_sent=0)
    values.update(kwargs)
    return SimpleNamespace(**values)


def fake_service(monkeypatch, run):
    monkeypatch.setitem(sys.modules, 'src.operations_accounts.maintenance', SimpleNamespace(
        AccountMaintenanceService=lambda: SimpleNamespace(run=run)))
    monkeypatch.setitem(sys.modules, 'src.platform_adapter.douyin_playback', SimpleNamespace(
        PlaybackOptions=lambda **kwargs: SimpleNamespace(**kwargs)))


def wait_workers(ap):
    deadline = time.monotonic() + 5
    while ap._active_workers and time.monotonic() < deadline:
        time.sleep(0.01)
    assert ap._active_workers == 0


def test_policy_defaults_opt_in_persistence_and_authorization(modules, tmp_path):
    ar, ap = modules
    db = tmp_path / 'playback.db'
    assert ar.snapshot(db)['playback_policies'] == []
    assert ar.claim_playback('A', 'a', now=100, path=db) is None
    with pytest.raises(ValueError, match='授权来源'):
        ar.set_playback_policy('A', 'a', True, path=db)
    configure(ar, db)
    policy = ar.snapshot(db)['playback_policies'][0]
    assert policy['options'] == ap.DEFAULT_OPTIONS
    assert policy['interval_seconds'] == 86400 and policy['enabled'] == 1
    assert policy['authorization_reference'] == 'user-request-20261018'
    assert ar.snapshot(db)['playback_accounts'][0]['next_due'] == 0
    assert ar.claim_playback('B', 'b', now=100, path=db) is None
    with pytest.raises(ValueError, match='绑定不一致'):
        configure(ar, db, 'A', 'different')


@pytest.mark.parametrize('options', [{'auto_like': True}, {'auto_comment': True}, {'auto_like': 1},
    {'auto_comment': 'false'}, {'max_videos': 0}, {'total_minutes': 121}, {'min_relevance_score': float('nan')},
    {'unknown_permission': True}])
def test_interaction_and_invalid_option_rejected_before_persistence(modules, tmp_path, options):
    ar, _ = modules
    db = tmp_path / 'playback.db'
    with pytest.raises(ValueError):
        configure(ar, db, options=options)
    assert ar.snapshot(db)['playback_policies'] == []


def test_interval_respects_existing_daily_quota_and_same_save_is_noop(modules, tmp_path):
    ar, _ = modules
    db = tmp_path / 'playback.db'
    with pytest.raises(ValueError, match='8小时'):
        configure(ar, db, interval_seconds=3600)
    configure(ar, db, interval_seconds=28800)
    first = ar.snapshot(db)
    configure(ar, db, interval_seconds=28800)
    assert ar.snapshot(db) == first


def test_three_plans_share_pause_mutex_and_unknown_original_id(modules, tmp_path):
    ar, _ = modules
    db = tmp_path / 'playback.db'
    configure(ar, db)
    run = ar.claim_playback('A', 'a', now=100, path=db)
    assert run
    assert ar.claim('A', 'a', now=101, path=db) is None
    assert ar.claim_smart('A', 'a', now=101, path=db) is None
    assert ar.claim_playback('A', 'a', now=101, path=db) is None
    assert ar.claim_smart('A', 'a', now=5000, path=db) is None
    state = ar.snapshot(db)
    assert state['playback_runs'][0]['status'] == 'outcome_unknown'
    assert state['playback_accounts'][0]['run_id'] == run
    assert ar.request_account_recovery('A', 'a', path=db)
    assert ar._claim_recovery('A', 'a', path=db) is None
    assert ar.claim('B', 'b', now=5001, path=db)


def test_sync_inflight_blocks_playback_and_completion_coalesces_offline_backlog(modules, tmp_path):
    ar, _ = modules
    db = tmp_path / 'playback.db'
    configure(ar, db)
    sync = ar.claim('A', 'a', now=100, path=db)
    assert ar.claim_playback('A', 'a', now=101, path=db) is None
    ar.finish(sync, 'completed', {}, now=110, path=db)
    first = ar.claim_playback('A', 'a', now=111, path=db)
    ar.finish_playback(first, 'completed', {}, now=120, path=db)
    assert ar.claim_playback('A', 'a', now=121, path=db) is None
    second = ar.claim_playback('A', 'a', now=1000000, reason='startup_catchup', path=db)
    ar.finish_playback(second, 'completed', {}, now=1000010, path=db)
    assert ar.claim_playback('A', 'a', now=1000011, path=db) is None
    assert len(ar.snapshot(db)['playback_runs']) == 2


@pytest.mark.parametrize('change', ['pause', 'disable', 'options'])
def test_thread_admission_rechecks_pause_enablement_and_configuration(modules, tmp_path, monkeypatch, change):
    ar, ap = modules
    db = tmp_path / 'playback.db'
    configure(ar, db)
    run = ar.claim_playback('A', 'a', path=db)
    if change == 'pause':
        ar.pause_account('A', 'a', 'before dispatch', path=db)
    elif change == 'disable':
        ar.set_playback_policy('A', 'a', False, path=db)
    else:
        configure(ar, db, options={'max_videos': 10})
    fake_service(monkeypatch, lambda *args, **kwargs: pytest.fail('must not invoke platform'))
    ap._run_playback(run, path=db)
    state = ar.snapshot(db)
    assert state['playback_runs'][0]['status'] == 'cancelled'
    assert state['playback_runs'][0]['dispatched_at'] is None
    assert state['playback_accounts'][0]['run_id'] is None
    assert state['controls'][0]['consecutive_failures'] == 0


def test_real_service_call_uses_frozen_options_authorization_and_preserves_inflight_disable(modules, tmp_path, monkeypatch):
    ar, ap = modules
    db = tmp_path / 'playback.db'
    configure(ar, db, options={'max_videos': 7, 'per_video_seconds': 35, 'total_minutes': 11})
    run = ar.claim_playback('A', 'a', path=db)
    calls = []
    def maintenance(key, mode, **kwargs):
        calls.append((key, mode, kwargs))
        ar.set_playback_policy('A', 'a', False, path=db)
        ar.pause_account('A', 'a', 'operator paused inflight', path=db)
        return fake_result()
    fake_service(monkeypatch, maintenance)
    ap._run_playback(run, path=db)
    key, mode, kwargs = calls[0]
    assert key == 'a' and mode == 'playback' and kwargs['headless'] is True
    assert kwargs['authorization_reference'] == 'user-request-20261018'
    assert kwargs['playback_options'].max_videos == 7
    assert kwargs['playback_options'].per_video_seconds == 35
    assert kwargs['playback_options'].total_minutes == 11
    assert kwargs['playback_options'].auto_like is False and kwargs['playback_options'].auto_comment is False
    state = ar.snapshot(db)
    assert state['playback_runs'][0]['status'] == 'completed'
    assert state['controls'][0]['state'] == 'paused'
    frozen = json.loads(state['playback_runs'][0]['policy_snapshot'])
    assert frozen['enabled'] == 1 and frozen['options']['max_videos'] == 7
    assert state['playback_policies'][0]['enabled'] == 0
    assert json.loads(state['playback_runs'][0]['detail'])['playback_verified_videos'] == 2


def test_reasonable_empty_candidate_skip_waits_full_interval_without_failure(modules, tmp_path):
    ar, _ = modules
    db = tmp_path / 'playback.db'
    configure(ar, db)
    run = ar.claim_playback('A', 'a', now=100, path=db)
    ar.finish_playback(run, 'skipped', {'error_code': 'no_playback_candidates', 'playback_verified_videos': 0}, now=110, path=db)
    state = ar.snapshot(db)
    assert state['controls'][0]['state'] == 'active'
    assert state['controls'][0]['consecutive_failures'] == 0
    assert state['playback_accounts'][0]['next_due'] == 110 + 86400
    assert state['playback_runs'][0]['status'] == 'skipped'
    assert not state['issues']


@pytest.mark.parametrize('status,detail', [('failed', {'error_code': 'network_error'}),
    ('skipped', {'error_code': 'human_required', 'playback_verified_videos': 0}),
    ('completed', {'error_code': 'human_required'}),
    ('skipped', {'error_code': 'no_playback_candidates', 'playback_verified_videos': 1})])
def test_actual_playback_error_pauses_once_and_is_not_masked_as_empty(modules, tmp_path, status, detail):
    ar, _ = modules
    db = tmp_path / 'playback.db'
    configure(ar, db)
    run = ar.claim_playback('A', 'a', now=100, path=db)
    ar.finish_playback(run, status, detail, now=110, path=db)
    assert ar.snapshot(db)['controls'][0]['state'] == 'paused'
    assert ar.claim_playback('A', 'a', now=1000000, path=db) is None


def test_navigation_timeout_retains_diagnostics_and_does_not_claim_captcha(modules, tmp_path, monkeypatch):
    ar, ap = modules
    db = tmp_path / 'playback.db'
    configure(ar, db)
    run = ar.claim_playback('A', 'a', path=db)
    fake_service(monkeypatch, lambda *a, **k: fake_result(status='blocked',
        error_code='browser_navigation_timeout', failure_stage='research',
        playback_verified_videos=0, actual_watch_seconds=0,
        navigation_evidence=dict(target_matched=False, navigation_committed=False,
            ready_state='loading', url='https://secret.invalid/?token=private')))
    ap._run_playback(run, path=db)
    state = ar.snapshot(db)
    control = state['controls'][0]
    assert control['state'] == 'paused'
    assert control['error_code'] == 'browser_navigation_timeout'
    assert '页面跳转超时' in control['reason']
    assert '退避' not in control['reason']
    detail = json.loads(state['playback_runs'][0]['detail'])
    assert detail['failure_stage'] == 'research'
    assert detail['navigation_evidence']['target_matched'] is False
    assert 'private' not in json.dumps(detail)
    assert ar.claim_playback('A', 'a', path=db) is None


def test_long_lease_and_disable_preserve_original_run(modules, tmp_path):
    ar, ap = modules
    db = tmp_path / 'playback.db'
    configure(ar, db, options={'total_minutes': 120})
    run = ar.claim_playback('A', 'a', now=100, path=db)
    account = ar.snapshot(db)['playback_accounts'][0]
    assert account['lease_until'] == 100 + 120 * 60 + 1800
    assert ap.playback_lease_seconds(20) == 3600
    ar.set_playback_policy('A', 'a', False, path=db)
    assert ar.snapshot(db)['playback_accounts'][0]['run_id'] == run


def test_bounded_workers_do_not_claim_backlog_and_other_account_remains_available(modules, tmp_path, monkeypatch):
    ar, ap = modules
    db = tmp_path / 'playback.db'
    for uuid, key in [('A', 'a'), ('B', 'b'), ('C', 'c')]:
        configure(ar, db, uuid, key)
    entered = []
    entered_lock = threading.Lock()
    both_started = threading.Event()
    release = threading.Event()
    def maintenance(key, mode, **kwargs):
        with entered_lock:
            entered.append(key)
            if len(entered) == 2:
                both_started.set()
        assert release.wait(5)
        return fake_result()
    fake_service(monkeypatch, maintenance)
    try:
        first = ap.dispatch_account('A', 'a', path=db)
        second = ap.dispatch_account('B', 'b', path=db)
        assert both_started.wait(3)
        assert first and second
        assert ap.dispatch_account('C', 'c', path=db) is None
        assert len(ar.snapshot(db)['playback_runs']) == 2
        assert ar.claim('C', 'c', path=db)  # Long playback does not occupy other accounts.
        assert ar.claim('A', 'a', path=db) is None
    finally:
        release.set()
        wait_workers(ap)
    assert all(run['status'] == 'completed' for run in ar.snapshot(db)['playback_runs'])


def test_activity_db_failure_after_thread_start_cannot_release_or_cancel_live_run(modules, tmp_path, monkeypatch):
    ar, ap = modules
    db = tmp_path / 'playback.db'
    configure(ar, db)
    started = threading.Event()
    release = threading.Event()
    def maintenance(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return fake_result()
    fake_service(monkeypatch, maintenance)
    monkeypatch.setattr(ap, '_publish_activity', lambda path: (_ for _ in ()).throw(sqlite_error()))
    try:
        run = ap.dispatch_account('A', 'a', path=db)
        assert run and started.wait(3)
        assert ap._active_workers == 1
        assert ar.snapshot(db)['playback_runs'][0]['status'] == 'running'
        assert ar.snapshot(db)['playback_accounts'][0]['run_id'] == run
        assert ap._slots.acquire(blocking=False)
        assert not ap._slots.acquire(blocking=False)
        ap._slots.release()
    finally:
        release.set()
        wait_workers(ap)
    assert ar.snapshot(db)['playback_runs'][0]['status'] == 'completed'
    assert ap._slots.acquire(blocking=False) and ap._slots.acquire(blocking=False)
    assert not ap._slots.acquire(blocking=False)
    ap._slots.release()
    ap._slots.release()


def sqlite_error():
    return RuntimeError('local status database unavailable')


def test_thread_birth_failure_is_known_undispatched_cancellation(modules, tmp_path, monkeypatch):
    ar, ap = modules
    db = tmp_path / 'playback.db'
    configure(ar, db)
    monkeypatch.setattr(ap.threading, 'Thread', lambda **kwargs: SimpleNamespace(start=lambda: (_ for _ in ()).throw(RuntimeError('no thread'))))
    with pytest.raises(RuntimeError, match='no thread'):
        ap.dispatch_account('A', 'a', path=db)
    state = ar.snapshot(db)
    assert state['playback_runs'][0]['status'] == 'cancelled'
    assert state['playback_runs'][0]['dispatched_at'] is None
    assert state['playback_accounts'][0]['run_id'] is None
    assert state['controls'][0]['consecutive_failures'] == 0
    assert ap._active_workers == 0


def test_due_scan_isolates_one_account_and_keeps_unconfigured_accounts_opted_out(modules, tmp_path, monkeypatch):
    ar, ap = modules
    db = tmp_path / 'playback.db'
    configure(ar, db, 'B', 'b')
    profiles = [SimpleNamespace(account_uuid=key.upper(), account_key=key) for key in ('a', 'b', 'c')]
    monkeypatch.setitem(sys.modules, 'src.operations_accounts', SimpleNamespace(
        AccountProfileRepository=lambda: SimpleNamespace(db_path='unused', list_active=lambda: profiles),
        AccountBindingRepository=lambda path: SimpleNamespace(get_optional=lambda key: SimpleNamespace(status='active'))))
    visited = []
    original_claim = ar.claim_playback
    def claim(uuid, key, **kwargs):
        visited.append(key)
        if key == 'a':
            raise RuntimeError('a policy is damaged')
        return original_claim(uuid, key, **kwargs)
    monkeypatch.setattr(ar, 'claim_playback', claim)
    fake_service(monkeypatch, lambda *args, **kwargs: fake_result())
    ap.dispatch_due_accounts(path=db)
    wait_workers(ap)
    state = ar.snapshot(db)
    assert visited == ['a', 'b', 'c']
    assert state['service']['playback_schedule']['status'] == 'healthy'
    assert next(item for item in state['controls'] if item['account_uuid'] == 'A')['state'] == 'paused'
    assert len(state['playback_runs']) == 1 and state['playback_runs'][0]['account_key'] == 'b'
    assert state['playback_runs'][0]['status'] == 'completed'


def test_unexpected_interaction_result_is_preserved_and_stops_automatic_account(modules, tmp_path, monkeypatch):
    ar, ap = modules
    db = tmp_path / 'playback.db'
    configure(ar, db)
    fake_service(monkeypatch, lambda *args, **kwargs: fake_result(likes_performed=1))
    run = ar.claim_playback('A', 'a', path=db)
    ap._run_playback(run, path=db)
    state = ar.snapshot(db)
    assert state['controls'][0]['state'] == 'paused'
    assert state['playback_runs'][0]['status'] == 'failed'
    detail = json.loads(state['playback_runs'][0]['detail'])
    assert detail['error_code'] == 'interaction_policy_violation' and detail['likes_performed'] == 1
    assert detail['maintenance_status'] == 'completed'


def test_scanner_failure_is_not_overwritten_when_inflight_worker_finishes(modules, tmp_path, monkeypatch):
    ar, ap = modules
    db = tmp_path / 'playback.db'
    configure(ar, db)
    started = threading.Event()
    release = threading.Event()
    worker_threads = []
    original_thread = ap.threading.Thread
    def tracked_thread(*args, **kwargs):
        worker = original_thread(*args, **kwargs)
        worker_threads.append(worker)
        return worker
    monkeypatch.setattr(ap.threading, 'Thread', tracked_thread)
    def maintenance(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return fake_result()
    fake_service(monkeypatch, maintenance)
    try:
        assert ap.dispatch_account('A', 'a', path=db)
        assert started.wait(3)
        ar.update_service_status('playback_schedule', 'manual_required',
            message='扫描异常，停止新派发', error_code='playback_schedule_unavailable', path=db)
        failed_scan = ar.snapshot(db)['service']['playback_schedule']
    finally:
        release.set()
        wait_workers(ap)
        for worker in worker_threads:
            worker.join(timeout=3)
            assert not worker.is_alive()
    state = ar.snapshot(db)
    assert state['playback_runs'][0]['status'] == 'completed'
    assert state['service']['playback_schedule'] == failed_scan
    assert state['service']['playback']['status'] == 'healthy'


def fake_single_account_repository(monkeypatch):
    profile = SimpleNamespace(account_uuid='A', account_key='a')
    monkeypatch.setitem(sys.modules, 'src.operations_accounts', SimpleNamespace(
        AccountProfileRepository=lambda: SimpleNamespace(db_path='unused', list_active=lambda: [profile]),
        AccountBindingRepository=lambda path: SimpleNamespace(get_optional=lambda key: SimpleNamespace(status='active'))))


def busy_database_error():
    error = sqlite3.OperationalError('database is locked')
    error.sqlite_errorcode = sqlite3.SQLITE_BUSY
    return error


def test_scan_sqlite_error_preserves_existing_human_incident_and_control_revision(modules, tmp_path, monkeypatch):
    ar, ap = modules
    db = tmp_path / 'playback.db'
    configure(ar, db)
    with ar.connect(db) as connection:
        ar._pause(connection, 'A', 'a', '请完成原页面的安全验证', 'human_required', 100)
    before = ar.snapshot(db)
    fake_single_account_repository(monkeypatch)
    fake_service(monkeypatch, lambda *args, **kwargs: pytest.fail('no platform dispatch'))
    monkeypatch.setattr(ap, 'dispatch_account', lambda *args, **kwargs: (_ for _ in ()).throw(busy_database_error()))
    ap.dispatch_due_accounts(path=db)
    after = ar.snapshot(db)
    for key in ('controls', 'issues', 'handling_requests', 'playback_runs', 'playback_accounts'):
        assert after[key] == before[key]
    assert ap._active_workers == 0


def test_scan_error_still_pauses_active_account_with_database_busy_issue(modules, tmp_path, monkeypatch):
    ar, ap = modules
    db = tmp_path / 'playback.db'
    configure(ar, db)
    with ar.connect(db) as connection:
        ar._ensure_control(connection, 'A', 'a', 100)
    fake_single_account_repository(monkeypatch)
    monkeypatch.setattr(ap, 'dispatch_account', lambda *args, **kwargs: (_ for _ in ()).throw(busy_database_error()))
    ap.dispatch_due_accounts(path=db)
    after = ar.snapshot(db)
    assert after['controls'][0]['state'] == 'paused'
    assert after['controls'][0]['error_code'] == 'scheduler_database_busy'
    assert after['issues'][0]['status'] == 'open'
    assert after['issues'][0]['error_code'] == 'scheduler_database_busy'
    assert not after['playback_runs']


def test_unknown_original_run_and_lock_survive_scan_error_without_dispatch(modules, tmp_path, monkeypatch):
    ar, ap = modules
    db = tmp_path / 'playback.db'
    configure(ar, db)
    original_id = ar.claim_playback('A', 'a', now=100, path=db)
    assert ar.claim('A', 'a', now=5000, path=db) is None
    before = ar.snapshot(db)
    assert before['controls'][0]['error_code'] == 'outcome_unknown'
    fake_single_account_repository(monkeypatch)
    fake_service(monkeypatch, lambda *args, **kwargs: pytest.fail('unknown outcome cannot dispatch'))
    monkeypatch.setattr(ap, 'dispatch_account', lambda *args, **kwargs: (_ for _ in ()).throw(busy_database_error()))
    ap.dispatch_due_accounts(path=db)
    after = ar.snapshot(db)
    for key in ('controls', 'issues', 'playback_accounts', 'playback_runs', 'handling_requests'):
        assert after[key] == before[key]
    assert after['playback_accounts'][0]['run_id'] == original_id
    assert after['playback_runs'][0]['dispatched_at'] is None
    assert ap._active_workers == 0
