"""Exact queued-browser boundary: real SQLite; no platform, quotas, or service actions."""
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sqlite3
from types import SimpleNamespace as NS

import pytest

from src.operations_accounts import pre_dispatch_playback_cancel as cancel
from src.operations_accounts import publication_unknown_closure as closure
from src.operations_accounts.browser_control import BrowserControlStore, BrowserControlRejected, _json
from src.platform_adapter.douyin_playback import PlaybackOptions
from src.scheduler import account_refresh
from src.scheduler.account_playback import normalize_options


BASE = datetime(2026, 10, 19, 6, tzinfo=timezone.utc).timestamp()
ACCOUNT = 'acct:one'
RUN = '1' * 32


def row(path, sql, args=()):
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        found = db.execute(sql, args).fetchone()
        return dict(found) if found else None


@pytest.fixture(scope='module')
def seed(tmp_path_factory):
    # One schema setup; each case copies closed DBs instead of dozens of durable commits.
    root = tmp_path_factory.mktemp('pre_dispatch_seed')
    data = root / 'data'
    data.mkdir()
    store = BrowserControlStore(data / 'account_browser_control.db', clock=lambda: BASE)
    options = normalize_options()
    payload = {'account_uuid': ACCOUNT, 'account_key': 'one', 'mode': 'playback', 'options': {
        'authorization_reference': 'original-frozen-playback', 'headless': True,
        'research_keywords': None, 'playback_options': asdict(PlaybackOptions(**options))}}
    command = store.submit(ACCOUNT, 'binding-one', 'maintenance', 'original-playback', payload)
    manual = store.submit(ACCOUNT, 'binding-one', 'manual', 'original-manual', {}, priority=200)
    owner = store.acquire_owner(ACCOUNT, 'binding-one', 'original-owner')
    policy = dict(account_uuid=ACCOUNT, account_key='one', enabled=1, interval_seconds=86400,
        options_json=_json(options), authorization_reference='original-frozen-playback', updated_at=BASE - 100, revision=2)
    frozen = account_refresh._playback_policy_dict(policy)
    with account_refresh.connect(data / 'account_refresh.db') as db:
        db.execute('INSERT INTO playback_policies VALUES(?,?,?,?,?,?,?,?)', tuple(policy.values()))
        db.execute('INSERT INTO playback_accounts VALUES(?,?,?,?,?)', (ACCOUNT, 'one', BASE - 100, BASE + 3600, RUN))
        db.execute('INSERT INTO playback_runs VALUES(?,?,?,?,?,?,?,?,?,?)',
            (RUN, ACCOUNT, 'one', 'periodic', BASE - .2, None, 'running', '{}', _json(frozen), BASE - .1))
        db.execute("INSERT INTO account_controls(account_uuid,account_key,state,consecutive_failures,updated_at,revision) VALUES(?,?,'active',1,?,42)",
            (ACCOUNT, 'one', BASE - 10))
    with sqlite3.connect(data / 'douyin.db') as db:
        db.execute('CREATE TABLE account_runtime_state(account_uuid TEXT PRIMARY KEY,day_key TEXT,daily_runs INTEGER,last_run_at TEXT,lock_owner TEXT,lock_expires_at TEXT,consecutive_failures INTEGER,circuit_open_until TEXT,updated_at TEXT)')
        db.execute('INSERT INTO account_runtime_state VALUES(?,?,?,?,?,?,?,?,?)',
            (ACCOUNT, '2026-10-19', 25, '2026-10-19T05:00:00+00:00', '', '', 0, '', 'original'))
    return NS(root=root, command=command, manual=manual, owner=owner)


@pytest.fixture
def prepared(seed, tmp_path, monkeypatch):
    root = tmp_path
    data = root / 'data'
    data.mkdir()
    for name in ('account_browser_control.db', 'account_refresh.db', 'douyin.db'):
        shutil.copyfile(seed.root / 'data' / name, data / name)
    monkeypatch.setattr(cancel, 'ROOT', root)
    monkeypatch.setattr(closure, 'ROOT', root)
    monkeypatch.setattr(cancel, 'COMMAND_ID', seed.command['command_id'])
    monkeypatch.setattr(cancel, 'RUN_ID', RUN)
    store = BrowserControlStore(data / 'account_browser_control.db', clock=lambda: BASE + 10)

    def write(name, value):
        path = data / name
        path.write_text(_json(value), encoding='utf-8')
        return closure.file_reference(path)

    approval = {'schema': 'publication_single_retry_user_authorization/20261019/v1',
        'decision_source': 'explicit_user_statement', 'user_statement': '可以',
        'approval_question': '是否允许部署修复并继续发布？', 'deployment_authorized': True,
        'baseline_daily_runs': 25, 'max_daily_runs': 26, 'active_control_revision': 42,
        'additional_recovery_runs': 0, 'account_uuid': ACCOUNT, 'account_key': 'one', 'utc_day': '2026-10-19'}
    authorization = write('AUTHORIZATION.json', approval)
    monkeypatch.setattr(cancel, 'AUTHORIZATION_SHA256', authorization['sha256'])
    kwargs = dict(owner_id='original-owner', generation=1, authorization=authorization,
        command_snapshot=write('COMMAND.json', store.get(seed.command['command_id'])),
        run_snapshot=write('RUN.json', row(data / 'account_refresh.db', 'SELECT * FROM playback_runs')),
        account_snapshot=write('ACCOUNT.json', row(data / 'account_refresh.db', 'SELECT * FROM playback_accounts')),
        policy_snapshot=write('POLICY.json', row(data / 'account_refresh.db', 'SELECT * FROM playback_policies')),
        audit_dir=data / 'audit', now=BASE + 10)
    return NS(root=root, data=data, store=store, kwargs=kwargs, seed=seed, write=write)


def test_success_holds_three_fences_and_late_failed_finish_is_ignored(prepared, monkeypatch):
    f = prepared
    before_control = row(f.data / 'account_refresh.db', 'SELECT * FROM account_controls')
    before_usage = row(f.data / 'douyin.db', 'SELECT * FROM account_runtime_state')
    original_write = cancel._write_new

    def verify_fences(path, value):
        if path.name == 'INTENT.json':
            for name in ('account_browser_control.db', 'account_refresh.db', 'douyin.db'):
                with sqlite3.connect(f.data / name, timeout=.01) as observer:
                    with pytest.raises(sqlite3.OperationalError, match='locked'):
                        observer.execute('BEGIN IMMEDIATE')
        original_write(path, value)

    monkeypatch.setattr(cancel, '_write_new', verify_fences)
    ref = cancel.operator_cancel_pre_dispatch_playback(f.store, **f.kwargs)
    receipt = closure._json_ref(ref)
    assert receipt['phase'] == 'completed' and not receipt['cross_database_crash_atomic']
    command = f.store.get(f.seed.command['command_id'])
    assert command['state'] == 'failed' and command['error_code'] == 'operator_cancelled_before_dispatch'
    assert command['result']['before_snapshot'] == f.seed.command
    assert command['owner_id'] is None and command['generation'] is None
    assert f.store.get(f.seed.manual['command_id']) == f.seed.manual
    run = row(f.data / 'account_refresh.db', 'SELECT * FROM playback_runs')
    assert run['status'] == 'cancelled_before_browser_dispatch' and run['finished_at'] == BASE + 10
    assert run['dispatched_at'] == BASE - .1
    account = row(f.data / 'account_refresh.db', 'SELECT * FROM playback_accounts')
    assert account['run_id'] is None and account['lease_until'] == 0 and account['next_due'] == BASE + 10 + 86400
    account_refresh.finish_playback(RUN, 'failed', {'error_code': 'late_original_waiter'}, now=BASE + 20,
        path=f.data / 'account_refresh.db')
    assert row(f.data / 'account_refresh.db', 'SELECT * FROM playback_runs') == run
    assert row(f.data / 'account_refresh.db', 'SELECT * FROM playback_accounts') == account
    assert row(f.data / 'account_refresh.db', 'SELECT * FROM account_controls') == before_control
    assert row(f.data / 'douyin.db', 'SELECT * FROM account_runtime_state') == before_usage


@pytest.mark.parametrize('state', ['running', 'outcome_unknown'])
def test_dispatched_or_unknown_even_with_fresh_snapshot_is_rejected(prepared, state):
    f = prepared
    with f.store._db(write=True) as db:
        db.execute('UPDATE browser_control_commands SET state=?,owner_id=?,generation=1 WHERE command_id=?',
            (state, 'original-owner', f.seed.command['command_id']))
    before = f.store.get(f.seed.command['command_id'])
    f.kwargs['command_snapshot'] = f.write('FRESH_COMMAND.json', before)
    with pytest.raises(BrowserControlRejected):
        cancel.operator_cancel_pre_dispatch_playback(f.store, **f.kwargs)
    assert f.store.get(f.seed.command['command_id']) == before
    assert row(f.data / 'account_refresh.db', 'SELECT * FROM playback_runs')['status'] == 'running'
    assert not f.kwargs['audit_dir'].exists()


def test_changed_snapshot_sha_rejected_without_writes(prepared):
    f = prepared
    Path(f.kwargs['run_snapshot']['path']).write_text('{}', encoding='utf-8')
    with pytest.raises(BrowserControlRejected):
        cancel.operator_cancel_pre_dispatch_playback(f.store, **f.kwargs)
    assert f.store.get(f.seed.command['command_id']) == f.seed.command
    assert not f.kwargs['audit_dir'].exists()


def test_account_binding_mismatch_with_fresh_snapshot_rejected(prepared):
    f = prepared
    with sqlite3.connect(f.data / 'account_refresh.db') as db:
        db.execute("UPDATE playback_runs SET account_key='other'")
    f.kwargs['run_snapshot'] = f.write('OTHER_RUN.json', row(f.data / 'account_refresh.db', 'SELECT * FROM playback_runs'))
    with pytest.raises(BrowserControlRejected):
        cancel.operator_cancel_pre_dispatch_playback(f.store, **f.kwargs)
    assert f.store.get(f.seed.command['command_id']) == f.seed.command
    assert not f.kwargs['audit_dir'].exists()


def test_scheduler_commit_failure_keeps_partial_intent_and_blocks_success(prepared, monkeypatch):
    f = prepared
    original_open = cancel._open_database

    class FailedCommit:
        def __init__(self, db):
            self.db = db

        def __getattr__(self, name):
            return getattr(self.db, name)

        def commit(self):
            raise sqlite3.OperationalError('injected scheduler commit failure')

    monkeypatch.setattr(cancel, '_open_database', lambda path:
        FailedCommit(original_open(path)) if path.name == 'account_refresh.db' else original_open(path))
    with pytest.raises(cancel.PreDispatchPlaybackCancelPartial):
        cancel.operator_cancel_pre_dispatch_playback(f.store, **f.kwargs)
    assert f.store.get(f.seed.command['command_id'])['state'] == 'failed'
    assert row(f.data / 'account_refresh.db', 'SELECT * FROM playback_runs')['status'] == 'running'
    assert row(f.data / 'account_refresh.db', 'SELECT * FROM account_controls')['state'] == 'active'
    stop = json.loads((f.kwargs['audit_dir'] / 'STOP.json').read_text(encoding='utf-8'))
    assert stop['phase'] == 'partial' and stop['core_committed'] and not stop['scheduler_committed']
    assert (f.kwargs['audit_dir'] / 'INTENT.json').is_file()
    assert not (f.kwargs['audit_dir'] / 'RECEIPT.json').exists()
