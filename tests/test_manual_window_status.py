"""Real SQLite boundary for stale manual UI; no browser or production writes."""
from copy import deepcopy
from types import SimpleNamespace as NS

import pytest

from src.operations_accounts import browser_control_runtime as bridge
from src.operations_accounts.browser_control import BrowserControlStore


@pytest.mark.parametrize('condition', ['fresh', 'stale', 'future', 'missing', 'inactive',
                                       'owner', 'generation', 'binding', 'old_probe'])
def test_snapshot_never_claims_old_manual_is_current(tmp_path, monkeypatch, condition):
    clock = [1000.0]
    store = BrowserControlStore(tmp_path / 'browser.db', clock=lambda: clock[0])
    owner = store.acquire_owner('a', 'bound', 'original')
    command = store.submit('a', 'bound', 'manual', 'one', {'account_key': 'a'})
    store.claim_next('a', 'bound', 'original', owner['generation'])
    store.transition(command['command_id'], 'original', owner['generation'], 'waiting_human', result={
        'current_verification': {'surface_state': 'clear', 'blocking': False},
        'window_visibility': {'restored': True}})
    clock[0] = 1001
    with store._db(write=True) as db:
        if condition == 'stale':
            clock[0] = 1091
        elif condition == 'future':
            db.execute('UPDATE browser_control_owners SET heartbeat=2000')
        elif condition == 'missing':
            db.execute('DELETE FROM browser_control_owners')
        elif condition == 'inactive':
            db.execute("UPDATE browser_control_owners SET state='released'")
        elif condition in {'owner', 'generation', 'binding'}:
            column = {'owner': 'owner_id', 'generation': 'generation', 'binding': 'binding_version'}[condition]
            db.execute(f'UPDATE browser_control_owners SET {column}=?',
                       (99 if condition == 'generation' else 'changed',))
        elif condition == 'old_probe':
            clock[0] = 1300
            db.execute('UPDATE browser_control_owners SET heartbeat=1300')
    original = deepcopy(store.manual_status_snapshot('a'))
    monkeypatch.setenv('ACCOUNT_BROWSER_CONTROL_DB', str(store.path))
    monkeypatch.setattr(bridge, '_store', lambda: store)
    monkeypatch.setattr(bridge, '_runtime', lambda: NS(profiles=NS(get=lambda key: NS(account_uuid='a'))))
    public = bridge.manual_window_snapshot('a', 'a')
    assert store.manual_status_snapshot('a') == original
    assert public['job_id'] == command['command_id']
    assert public['state'] == 'running'  # Persisted task state is not rewritten.
    if condition == 'fresh':
        assert public['phase'] == 'window_current_no_challenge' and public['handoff_ready']
    elif condition == 'old_probe':
        assert public['phase'] == 'window_observation_stale' and public['handoff_ready']
        assert 'current_verification' not in public
    else:
        assert public['phase'] == 'window_owner_unconfirmed' and not public['handoff_ready']
        assert 'current_verification' not in public


def test_terminal_and_queued_are_not_reinterpreted_as_live_owner():
    from src.operations_accounts.manual_window_status import present_manual_liveness
    for state in ('queued', 'succeeded', 'failed', 'outcome_unknown'):
        public = {'state': state, 'phase': state}
        assert present_manual_liveness(public, {'state': state}, None, now=1000) == public
