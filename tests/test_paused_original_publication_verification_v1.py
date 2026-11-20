"""Paused controls must allow their original-bound observation, never business."""
import sqlite3
from types import SimpleNamespace as NS
import pytest
from test_publication_verification_recovery import incident
from src.operations_accounts import publication_verification_recovery as recovery
from src.operations_accounts.paused_browser_claims import install


def paused(i, tmp_path):
    path = tmp_path / 'paused.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE account_controls(account_uuid TEXT,state TEXT)')
        db.execute("INSERT INTO account_controls VALUES('account:a','paused')")
    install(NS(store=i.store, account_id='account:a'), NS(manual_tasks={}, console_tasks={}), path=path)


def test_original_read_runs_while_unknown_and_paused_without_unpausing(incident, tmp_path):
    i = incident
    verify = recovery.queue_due(i.store, i.context, 'binding')
    ordinary = i.store.submit('account:a', 'binding', 'maintenance', 'ordinary', {}, 1000)
    paused(i, tmp_path)
    actual = i.store.claim_next('account:a', 'binding', 'backend:123:abc', 1)
    assert actual['command_id'] == verify['command_id'] and actual['state'] == 'running'
    assert i.store.get(i.original['command_id']) == i.original
    assert i.store.get(ordinary['command_id']) == ordinary
    with sqlite3.connect(tmp_path/'paused.db') as db:
        assert db.execute('SELECT state FROM account_controls').fetchone()[0] == 'paused'


@pytest.mark.parametrize('kinds', [('read',), ('maintenance',), ()])
def test_explicit_kind_filter_cannot_be_bypassed(incident, kinds):
    i = incident; queued = recovery.queue_due(i.store, i.context, 'binding')
    assert i.store.claim_next('account:a', 'binding', 'backend:123:abc', 1, kinds=kinds) is None
    assert i.store.get(queued['command_id']) == queued


def test_allowed_read_still_requires_original_snapshot(incident, tmp_path):
    i = incident; queued = recovery.queue_due(i.store, i.context, 'binding')
    with i.store._db(write=True) as db:
        db.execute("UPDATE browser_control_commands SET payload=json_set(payload,'$.original_snapshot_sha256','changed') WHERE command_id=?", (queued['command_id'],))
    paused(i, tmp_path)
    assert i.store.claim_next('account:a', 'binding', 'backend:123:abc', 1) is None
