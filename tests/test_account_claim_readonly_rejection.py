"""No-op account admission must not contend for SQLite's writer reservation."""
import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def ar(monkeypatch):
    backend = load('isolated_readonly_claim_backend', 'src/scheduler/account_refresh.py')
    playback = load('isolated_readonly_claim_playback', 'src/scheduler/account_playback.py')
    monkeypatch.setitem(sys.modules, 'src.scheduler.account_playback', playback)
    return backend


def configure(ar, db):
    ar.set_playback_policy('A', 'a', True, authorization_reference='user-test', path=db)


def trace_connections(ar, monkeypatch):
    statements = []
    original_connect = sqlite3.connect
    def connect(*args, **kwargs):
        kwargs['timeout'] = 0.05
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection
    monkeypatch.setattr(ar.sqlite3, 'connect', connect)
    return original_connect, statements


def assert_no_writes(statements):
    assert not any(sql.lstrip().upper().startswith(('BEGIN', 'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'COMMIT'))
                   for sql in statements)


def test_paused_three_claims_remain_read_only_with_another_reserved_writer(ar, tmp_path, monkeypatch):
    db = tmp_path / 'admission.db'
    configure(ar, db)
    ar.pause_account('A', 'a', 'original incident', path=db)
    before = ar.snapshot(db)
    original_connect, statements = trace_connections(ar, monkeypatch)
    with original_connect(db) as holder:
        holder.execute('BEGIN IMMEDIATE')
        assert ar.claim('A', 'a', path=db) is None
        assert ar.claim_smart('A', 'a', path=db) is None
        assert ar.claim_playback('A', 'a', path=db) is None
        assert ar._claim_recovery('A', 'a', path=db) is None
    assert_no_writes(statements)
    assert ar.snapshot(db) == before


@pytest.mark.parametrize('state', [None, 'active', 'paused'])
def test_absent_recovery_request_does_not_reserve_writer(ar, tmp_path, monkeypatch, state):
    db = tmp_path / 'admission.db'
    ar.snapshot(db)
    if state is not None:
        with ar.connect(db) as connection:
            ar._ensure_control(connection, 'A', 'a', 100)
            connection.execute('UPDATE account_controls SET state=?', (state,))
    before = ar.snapshot(db)
    original_connect, statements = trace_connections(ar, monkeypatch)
    with original_connect(db) as holder:
        holder.execute('BEGIN IMMEDIATE')
        assert ar._claim_recovery('A', 'a', path=db) is None
    assert_no_writes(statements)
    assert ar.snapshot(db) == before


@pytest.mark.parametrize('claim_name', ['claim', 'claim_smart', 'claim_playback'])
def test_pause_after_read_precheck_is_still_enforced_by_atomic_gate(ar, tmp_path, monkeypatch, claim_name):
    db = tmp_path / 'admission.db'
    configure(ar, db)
    with ar.connect(db) as connection:
        ar._ensure_control(connection, 'A', 'a', 100)
    original_check = ar._account_already_paused
    checked = []
    def pause_after_check(connection, account_uuid, account_key):
        result = original_check(connection, account_uuid, account_key)
        assert result is False
        checked.append(account_key)
        ar.pause_account('A', 'a', 'paused after read check', path=db)
        return result
    monkeypatch.setattr(ar, '_account_already_paused', pause_after_check)
    assert getattr(ar, claim_name)('A', 'a', path=db) is None
    state = ar.snapshot(db)
    assert checked == ['a']
    assert state['controls'][0]['state'] == 'paused'
    assert state['controls'][0]['reason'] == 'paused after read check'
    assert not state['runs'] and not state['smart_runs'] and not state['playback_runs']


@pytest.mark.parametrize('claim_name', ['claim', 'claim_smart', 'claim_playback'])
def test_mismatched_account_key_does_not_use_paused_readonly_shortcut(ar, tmp_path, monkeypatch, claim_name):
    db = tmp_path / 'admission.db'
    configure(ar, db)
    ar.pause_account('A', 'a', 'original pause', path=db)
    _, statements = trace_connections(ar, monkeypatch)
    assert getattr(ar, claim_name)('A', 'wrong-key', path=db) is None
    assert any(sql.lstrip().upper().startswith('BEGIN IMMEDIATE') for sql in statements)
    if claim_name != 'claim_playback':
        assert ar.snapshot(db)['controls'][0]['error_code'] == 'account_uuid_mismatch'


@pytest.mark.parametrize('state', ['active', 'paused', 'recovering'])
def test_expired_original_recovery_token_still_uses_transaction_and_unknown_gate(ar, tmp_path, monkeypatch, state):
    db = tmp_path / 'admission.db'
    with ar.connect(db) as connection:
        ar._ensure_control(connection, 'A', 'a', 100)
        connection.execute('UPDATE account_controls SET state=?,recovery_token=?,recovery_lease_until=50', (state, 'original-token'))
    _, statements = trace_connections(ar, monkeypatch)
    assert ar._claim_recovery('A', 'a', now=100, path=db) is None
    assert any(sql.lstrip().upper().startswith('BEGIN IMMEDIATE') for sql in statements)
    current = ar.snapshot(db)
    assert current['controls'][0]['state'] == 'paused'
    assert current['controls'][0]['error_code'] == 'recovery_outcome_unknown'
    with ar.connect(db) as connection:
        assert connection.execute('SELECT recovery_token FROM account_controls').fetchone()[0] == 'original-token'


def test_active_expired_business_run_keeps_original_unknown_flow(ar, tmp_path):
    db = tmp_path / 'admission.db'
    original_id = ar.claim('A', 'a', now=100, path=db)
    assert original_id
    assert ar.claim_smart('A', 'a', now=5000, path=db) is None
    state = ar.snapshot(db)
    assert state['controls'][0]['error_code'] == 'outcome_unknown'
    assert state['runs'][0]['run_id'] == original_id
    assert state['runs'][0]['status'] == 'outcome_unknown'
    assert state['accounts'][0]['run_id'] == original_id
