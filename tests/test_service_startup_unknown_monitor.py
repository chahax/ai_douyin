"""The monitor sees unresolved outcomes without writing or exposing payloads."""
import hashlib

import pytest

from scripts import check_service_startup as monitor
from src.operations_accounts.browser_control import BrowserControlStore


def test_readonly_monitor_keeps_unknown_and_ignores_terminal_commands(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, 'ROOT', tmp_path)
    path = tmp_path / 'data/account_browser_control.db'
    store = BrowserControlStore(path)
    unknown = store.submit('test', 'binding', 'maintenance', 'unknown', {'private':'secret'})
    owner = store.acquire_owner('test', 'binding', 'owner')
    store.claim_next('test', 'binding', 'owner', owner['generation'])
    store.transition(unknown['command_id'], 'owner', owner['generation'], 'outcome_unknown')
    queued = store.submit('test', 'binding', 'maintenance', 'queued', {})
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    rows = monitor.read_unresolved_commands()
    assert {r['command_id'] for r in rows} == {unknown['command_id'], queued['command_id']}
    assert {r['state'] for r in rows} == {'outcome_unknown', 'queued'}
    assert all('payload' not in r for r in rows)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_missing_database_is_not_created_or_reported_as_healthy(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, 'ROOT', tmp_path)
    with pytest.raises(Exception):
        monitor.read_unresolved_commands()
    assert not (tmp_path / 'data/account_browser_control.db').exists()
