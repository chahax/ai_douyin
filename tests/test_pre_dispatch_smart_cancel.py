"""Three decisive real-SQLite cases; shared minimal seed, no grant/browser imports."""
from datetime import datetime, timezone
import json
import shutil
import sqlite3
from types import SimpleNamespace as NS

import pytest

from src.operations_accounts import pre_dispatch_smart_cancel as cancel
from src.operations_accounts import publication_unknown_closure as closure
from src.operations_accounts.browser_control import BrowserControlStore, BrowserControlRejected, _json
from src.scheduler import account_refresh

BASE = datetime(2026, 10, 19, 6, tzinfo=timezone.utc).timestamp()
ACCOUNT = 'acct:smart'
RUN = '2' * 32


def row(path, query):
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        value = db.execute(query).fetchone()
        return dict(value) if value else None


@pytest.fixture(scope='module')
def seed(tmp_path_factory):
    root = tmp_path_factory.mktemp('minimal_smart_seed')
    data = root / 'data'
    data.mkdir()
    store = BrowserControlStore(data / 'account_browser_control.db', clock=lambda: BASE)
    payload = {'account_uuid': ACCOUNT, 'account_key': 'smart', 'mode': 'smart-operations', 'options': {
        'authorization_reference': 'user-authorized-smart-operations-2026-09-21',
        'headless': True, 'playback_options': None, 'research_keywords': ['装修合同', '租房押金']}}
    command = store.submit(ACCOUNT, 'binding-smart', 'maintenance', 'original-smart-command', payload)
    manual = store.submit(ACCOUNT, 'binding-smart', 'manual', 'original-manual', {}, priority=200)
    store.acquire_owner(ACCOUNT, 'binding-smart', 'original-owner')
    with account_refresh.connect(data / 'account_refresh.db') as db:
        db.execute('INSERT INTO smart_accounts VALUES(?,?,?,?,?)', (ACCOUNT, 'smart', BASE - 100, BASE + 3600, RUN))
        db.execute('INSERT INTO smart_runs VALUES(?,?,?,?,?,?,?,?)',
            (RUN, ACCOUNT, 'smart', 'periodic', BASE - 3, None, 'running', '{}'))
        db.execute("INSERT INTO account_controls(account_uuid,account_key,state,consecutive_failures,updated_at,revision) VALUES(?,?,'active',2,?,42)",
            (ACCOUNT, 'smart', BASE - 100))
    with sqlite3.connect(data / 'douyin.db') as db:
        db.execute('CREATE TABLE account_runtime_state(account_uuid TEXT PRIMARY KEY,day_key TEXT,daily_runs INTEGER,last_run_at TEXT,lock_owner TEXT,lock_expires_at TEXT,consecutive_failures INTEGER,circuit_open_until TEXT,updated_at TEXT)')
        db.execute('INSERT INTO account_runtime_state VALUES(?,?,?,?,?,?,?,?,?)',
            (ACCOUNT, '2026-10-19', 26, '2026-10-19T05:00:00+00:00', '', '', 0, '', 'original'))
    return NS(root=root, command=command, manual=manual)


@pytest.fixture
def prepared(seed, tmp_path, monkeypatch):
    data = tmp_path / 'data'
    data.mkdir()
    for name in ('account_browser_control.db', 'account_refresh.db', 'douyin.db'):
        shutil.copyfile(seed.root / 'data' / name, data / name)
    monkeypatch.setattr(cancel, 'ROOT', tmp_path)
    monkeypatch.setattr(closure, 'ROOT', tmp_path)
    monkeypatch.setattr(cancel, 'COMMAND_ID', seed.command['command_id'])
    monkeypatch.setattr(cancel, 'RUN_ID', RUN)
    monkeypatch.setattr(cancel, 'OWNER_ID', 'original-owner')
    monkeypatch.setattr(cancel, 'GENERATION', 1)
    store = BrowserControlStore(data / 'account_browser_control.db', clock=lambda: BASE + 10)

    def write(name, value):
        path = data / name
        path.write_text(_json(value), encoding='utf-8')
        return closure.file_reference(path)

    snapshot = {'command': store.get(seed.command['command_id']),
        'run': row(data / 'account_refresh.db', 'SELECT * FROM smart_runs'),
        'account': row(data / 'account_refresh.db', 'SELECT * FROM smart_accounts'),
        'policy': row(data / 'account_refresh.db', 'SELECT * FROM smart_policy'),
        'control': row(data / 'account_refresh.db', 'SELECT * FROM account_controls'),
        'runtime': row(data / 'douyin.db', 'SELECT * FROM account_runtime_state')}
    snapshot_ref = write('BEFORE.json', snapshot)
    monkeypatch.setattr(cancel, 'SNAPSHOT_SHA256', snapshot_ref['sha256'])
    authorization = write('APPROVAL.json', {'schema': 'publication_fast_upload_retry_user_authorization/20261019/v1',
        'decision_source': 'explicit_user_statement', 'user_statement': '允许', 'approval_question': '是否允许部署修复后继续？',
        'deployment_authorized': True, 'baseline_daily_runs': 26, 'max_daily_runs': 27, 'active_control_revision': 42,
        'additional_recovery_runs': 0, 'account_uuid': ACCOUNT, 'account_key': 'smart', 'utc_day': '2026-10-19'})
    monkeypatch.setattr(cancel, 'AUTHORIZATION_SHA256', authorization['sha256'])
    kwargs = dict(owner_id='original-owner', generation=1, authorization=authorization,
        snapshot=snapshot_ref, audit_dir=data / 'audit', now=BASE + 10)
    return NS(root=tmp_path, data=data, store=store, kwargs=kwargs, seed=seed, snapshot=snapshot, write=write)


def test_exact_smart_cancel_holds_fences_and_late_failure_preserves_active42_failure2(prepared, monkeypatch):
    f = prepared
    original_write = cancel._write_new

    def check_fences(path, value):
        if path.name == 'INTENT.json':
            for name in ('account_browser_control.db', 'account_refresh.db', 'douyin.db'):
                with sqlite3.connect(f.data / name, timeout=.01) as observer:
                    with pytest.raises(sqlite3.OperationalError, match='locked'):
                        observer.execute('BEGIN IMMEDIATE')
        original_write(path, value)

    monkeypatch.setattr(cancel, '_write_new', check_fences)
    receipt = closure._json_ref(cancel.operator_cancel_pre_dispatch_smart(f.store, **f.kwargs))
    assert receipt['phase'] == 'completed' and receipt['cross_database_crash_atomic'] is False
    command = f.store.get(f.seed.command['command_id'])
    assert command['state'] == 'failed' and command['error_code'] == 'operator_cancelled_before_dispatch'
    assert command['result']['before'] == f.snapshot
    assert f.store.get(f.seed.manual['command_id']) == f.seed.manual
    run = row(f.data / 'account_refresh.db', 'SELECT * FROM smart_runs')
    assert run['status'] == 'cancelled_before_browser_dispatch' and run['finished_at'] == BASE + 10
    assert all(run[k] == f.snapshot['run'][k] for k in ('run_id', 'account_uuid', 'account_key', 'reason', 'started_at'))
    account = row(f.data / 'account_refresh.db', 'SELECT * FROM smart_accounts')
    assert account['run_id'] is None and account['lease_until'] == 0 and account['next_due'] == BASE + 10 + 86400
    account_refresh.finish_smart(RUN, 'failed', {'error_code': 'late_waiting_client_failure'},
        now=BASE + 20, path=f.data / 'account_refresh.db')
    assert row(f.data / 'account_refresh.db', 'SELECT * FROM smart_runs') == run
    assert row(f.data / 'account_refresh.db', 'SELECT * FROM smart_accounts') == account
    assert row(f.data / 'account_refresh.db', 'SELECT * FROM account_controls') == f.snapshot['control']
    assert row(f.data / 'douyin.db', 'SELECT * FROM account_runtime_state') == f.snapshot['runtime']
    assert row(f.data / 'account_refresh.db', 'SELECT * FROM account_issues') is None


def test_running_unknown_fresh_snapshots_and_new_owner_are_rejected(prepared, monkeypatch):
    f = prepared
    with pytest.raises(BrowserControlRejected):
        cancel.operator_cancel_pre_dispatch_smart(f.store, **dict(f.kwargs, owner_id='new-owner'))
    for state in ('running', 'outcome_unknown'):
        with f.store._db(write=True) as db:
            db.execute('UPDATE browser_control_commands SET state=?,owner_id=?,generation=1 WHERE command_id=?',
                (state, 'original-owner', f.seed.command['command_id']))
        before = f.store.get(f.seed.command['command_id'])
        snapshot = dict(f.snapshot, command=before)
        ref = f.write(state + '.json', snapshot)
        monkeypatch.setattr(cancel, 'SNAPSHOT_SHA256', ref['sha256'])
        with pytest.raises(BrowserControlRejected):
            cancel.operator_cancel_pre_dispatch_smart(f.store, **dict(f.kwargs, snapshot=ref))
        assert f.store.get(f.seed.command['command_id']) == before
        assert row(f.data / 'account_refresh.db', 'SELECT * FROM smart_runs') == f.snapshot['run']
    assert not f.kwargs['audit_dir'].exists()


def test_scheduler_commit_partial_stops_without_success_receipt(prepared, monkeypatch):
    f = prepared
    original_open = cancel._open_database

    class CommitFailure:
        def __init__(self, db):
            self.db = db

        def __getattr__(self, name):
            return getattr(self.db, name)

        def commit(self):
            raise sqlite3.OperationalError('injected scheduler commit failure')

    monkeypatch.setattr(cancel, '_open_database', lambda path:
        CommitFailure(original_open(path)) if path.name == 'account_refresh.db' else original_open(path))
    with pytest.raises(cancel.PreDispatchSmartCancelPartial):
        cancel.operator_cancel_pre_dispatch_smart(f.store, **f.kwargs)
    assert f.store.get(f.seed.command['command_id'])['state'] == 'failed'
    assert row(f.data / 'account_refresh.db', 'SELECT * FROM smart_runs') == f.snapshot['run']
    assert row(f.data / 'account_refresh.db', 'SELECT * FROM account_controls') == f.snapshot['control']
    assert row(f.data / 'douyin.db', 'SELECT * FROM account_runtime_state') == f.snapshot['runtime']
    stop = json.loads((f.kwargs['audit_dir'] / 'STOP.json').read_text(encoding='utf-8'))
    assert stop['phase'] == 'partial' and stop['core_committed'] and not stop['scheduler_committed']
    assert (f.kwargs['audit_dir'] / 'INTENT.json').is_file()
    assert not (f.kwargs['audit_dir'] / 'RECEIPT.json').exists()
