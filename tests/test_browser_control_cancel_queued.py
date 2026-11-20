import pytest

from src.operations_accounts.browser_control import BrowserControlStore, BrowserControlRejected
from src.operations_accounts.known_zero_playback_reconciliation import snapshot_sha256


def test_exact_queued_console_can_be_cancelled_without_dispatch_and_keeps_original_request(tmp_path):
    store = BrowserControlStore(tmp_path / 'cancel.sqlite')
    original = store.submit('review:A', 'binding', 'official_console', 'original-console',
        {'requested_by': 'assistant:original'}, 20)
    cancelled = store.cancel_queued(original['command_id'], snapshot_sha256(original),
        'Operator withdrew its own unused console before deployment', 'assistant:original')
    assert cancelled['state'] == 'failed' and cancelled['error_code'] == 'operator_cancelled_before_dispatch'
    for key in ('payload', 'cursor', 'idempotency_key', 'request_sha', 'owner_id', 'generation'):
        assert cancelled[key] == original[key]
    assert cancelled['result']['requested_by'] == 'assistant:original'
    assert cancelled['result']['cancelled_before_dispatch'] is True
    assert store.submit('review:A', 'binding', 'official_console', 'original-console',
        original['payload'], 20)['command_id'] == original['command_id']
    owner = store.acquire_owner('review:A', 'binding', 'owner')
    assert store.claim_next('review:A', 'binding', 'owner', owner['generation']) is None
    store.release_owner('review:A', 'owner', owner['generation'])


def test_cancellation_rejects_stale_snapshot_and_every_nonqueued_state_without_mutation(tmp_path):
    store = BrowserControlStore(tmp_path / 'reject.sqlite')
    for state in ('queued', 'running', 'paused', 'outcome_unknown', 'succeeded', 'failed'):
        command = store.submit('review:A', 'binding', 'official_console', state, {}, 20)
        if state != 'queued':
            with store._db(write=True) as db:
                db.execute('UPDATE browser_control_commands SET state=? WHERE command_id=?', (state, command['command_id']))
        before = store.get(command['command_id'])
        with pytest.raises(BrowserControlRejected):
            store.cancel_queued(command['command_id'], '0'*64 if state == 'queued' else snapshot_sha256(before),
                'Do not cancel active or changed work', 'operator')
        assert store.get(command['command_id']) == before
