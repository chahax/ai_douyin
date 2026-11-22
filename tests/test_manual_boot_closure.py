from copy import deepcopy
from types import SimpleNamespace as NS

import pytest

from src.operations_accounts import manual_boot_closure as closure
from src.operations_accounts.browser_control import BrowserControlRejected, BrowserControlStore
from src.operations_accounts.browser_control_runtime import _manual_public


@pytest.fixture
def original(tmp_path, monkeypatch):
    clock = [1000.0]
    store = BrowserControlStore(tmp_path / 'browser.db', clock=lambda: clock[0])
    owner = store.acquire_owner('a', 'binding', 'backend:111:abc123')
    command = store.submit('a', 'binding', 'manual', 'original', {'account_key': 'key', 'account_uuid': 'a'})
    store.claim_next('a', 'binding', owner['owner_id'], owner['generation'])
    store.transition(command['command_id'], owner['owner_id'], owner['generation'], 'waiting_human',
                     result={'tab_id': 'original-tab', 'current_verification': {'surface_state': 'clear'}})
    queued = store.submit('a', 'binding', 'maintenance', 'queued', {'account_key': 'key'})
    clock[0] = 2200
    evidence = {'boot_time': 2000.0, 'backend_pid': 222, 'backend_create_time': 2100.0}
    monkeypatch.setattr(closure, '_boot_evidence', lambda: dict(evidence))
    return NS(store=store, clock=clock, command_id=command['command_id'], queued_id=queued['command_id'], evidence=evidence)


def plan(run):
    return closure.preview(run.store, 'a', 'key', run.command_id, 'binding')


def apply(run, proof):
    return closure.settle(run.store, 'a', 'key', run.command_id, 'binding', proof, 'fixture-admin')


def test_preview_is_ro_and_explicit_closure_keeps_old_evidence_and_queued_identity(original):
    store = original.store
    before = deepcopy(store.manual_status_snapshot('a'))
    queued = store.get(original.queued_id)
    proof = plan(original)
    assert store.manual_status_snapshot('a') == before
    with store._db() as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (closure.TABLE,)).fetchone()
    result = apply(original, proof['proof_sha'])
    assert result == {'status': 'settled', 'identity_verified': False, 'account_resumed': False}
    assert store.get(original.queued_id) == queued
    saved = store.get(original.command_id)
    assert saved['state'] == 'succeeded' and not saved['result']['identity_verified']
    public = _manual_public(saved)
    assert public['state'] == 'closed' and public['phase'] == 'closed_by_previous_boot'
    assert public['session_saved'] is False
    with store._db() as db:
        row = db.execute(f'SELECT * FROM {closure.TABLE}').fetchone()
        import json
        assert json.loads(row['original_command']) == before['commands'][0]
        assert json.loads(row['proof'])['owner'] == before['owner']
    assert apply(original, proof['proof_sha']) == {'status': 'already_settled'}


@pytest.mark.parametrize('change', ['owner', 'generation', 'binding', 'request', 'recent', 'future_boot',
    'invalid_boot', 'newer_backend', 'unknown_business', 'running_business', 'paused_business',
    'not_manual', 'manual_unknown', 'wrong_uuid', 'wrong_key', 'proof_changed'])
def test_missing_or_changed_proof_never_releases_any_task(original, change):
    store = original.store
    proof = plan(original)['proof_sha']
    with store._db(write=True) as db:
        if change in {'owner', 'generation', 'binding'}:
            column = {'owner': 'owner_id', 'generation': 'generation', 'binding': 'binding_version'}[change]
            db.execute(f'UPDATE browser_control_owners SET {column}=?', (99 if column == 'generation' else 'changed',))
        elif change == 'request':
            db.execute("UPDATE browser_control_commands SET payload='{}' WHERE command_id=?", (original.command_id,))
        elif change == 'recent':
            db.execute('UPDATE browser_control_owners SET heartbeat=2050')
        elif change in {'not_manual', 'manual_unknown'}:
            column, value = ('kind', 'publish') if change == 'not_manual' else ('state', 'outcome_unknown')
            db.execute(f'UPDATE browser_control_commands SET {column}=? WHERE command_id=?', (value, original.command_id))
        elif change in {'wrong_uuid', 'wrong_key'}:
            import json
            payload = json.loads(db.execute('SELECT payload FROM browser_control_commands WHERE command_id=?',
                                           (original.command_id,)).fetchone()[0])
            payload['account_uuid' if change == 'wrong_uuid' else 'account_key'] = 'changed'
            db.execute('UPDATE browser_control_commands SET payload=? WHERE command_id=?',
                       (json.dumps(payload), original.command_id))
    if change in {'unknown_business', 'running_business', 'paused_business'}:
        other = store.submit('a', 'binding', 'publish', 'other', {})
        state = {'unknown_business': 'outcome_unknown', 'running_business': 'running', 'paused_business': 'paused'}[change]
        with store._db(write=True) as db:
            db.execute('UPDATE browser_control_commands SET state=? WHERE command_id=?', (state, other['command_id']))
    elif change == 'future_boot':
        original.evidence['boot_time'] = 3000
    elif change == 'invalid_boot':
        original.evidence['boot_time'] = float('nan')
    elif change == 'newer_backend':
        original.evidence['backend_create_time'] = 3000
    elif change == 'proof_changed':
        proof = '0' * 64
    before = store.snapshot('a')
    with pytest.raises(BrowserControlRejected):
        apply(original, proof)
    assert store.snapshot('a') == before
    with store._db() as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (closure.TABLE,)).fetchone()


def test_readers_cannot_forge_another_account_acknowledgement(original):
    proof = plan(original)['proof_sha']
    apply(original, proof)
    with pytest.raises(BrowserControlRejected):
        closure.settle(original.store, 'a', 'foreign-key', original.command_id, 'binding', proof, 'fixture-admin')


def test_same_boot_restart_rechecks_processes_before_settlement(original, tmp_path, monkeypatch):
    original.evidence['boot_time'] = 900
    profile = tmp_path / 'profile'
    monkeypatch.setattr(closure, '_bound_profile', lambda *args:profile)
    gone = [True]
    def exited(pid, directory, opened_at):
        assert (pid, directory, opened_at) == (111, profile, 1000)
        return gone[0]
    monkeypatch.setattr(closure, '_previous_backend_gone', exited)
    args = (original.store, 'a', 'key', original.command_id, 'binding')
    preview = closure.preview(*args)
    assert preview['reason'] == 'proven_previous_backend_exit'
    gone[0] = False
    with pytest.raises(BrowserControlRejected):
        closure.settle(*args, preview['proof_sha'], 'admin')
    assert original.store.get(original.command_id)['state'] == 'waiting_human'
    gone[0] = True
    closure.settle(*args, preview['proof_sha'], 'admin')
    public = _manual_public(original.store.get(original.command_id))
    assert public['phase'] == 'closed_by_previous_backend' and public['state'] == 'closed'
    assert original.store.get(original.queued_id)['state'] == 'queued'


def test_same_boot_proof_requires_absent_processes(tmp_path, monkeypatch):
    import psutil
    from pathlib import Path
    profile = tmp_path / 'profile'
    monkeypatch.setattr(psutil, 'WINDOWS', True)
    monkeypatch.setattr(psutil,'pid_exists',lambda pid: True)
    assert not closure._previous_backend_gone(111,profile,1000)
    monkeypatch.setattr(psutil,'pid_exists',lambda pid: False)
    workers = []
    monkeypatch.setattr(psutil,'process_iter',lambda: iter(workers))
    for args in (['chrome.exe','--user-data-dir='+str(profile)], ['chrome.exe','--user-data-dir',str(profile)]):
        workers[:] = [NS(name=lambda:'chrome.exe', cmdline=lambda:args)]
        assert not closure._previous_backend_gone(111,profile,1000)
    cache = Path(closure.__file__).resolve().parents[2]/'data/browser_worker_cache'
    workers[:] = [NS(name=lambda:'pythonw.exe',create_time=lambda:990,cmdline=lambda:['pythonw',str(cache/'worker.py')])]
    assert not closure._previous_backend_gone(111,profile,1000)
    def denied(): raise psutil.AccessDenied(123)
    workers[:] = [NS(name=lambda:'chrome.exe',cmdline=denied)]
    assert not closure._previous_backend_gone(111,profile,1000)
    workers.clear()
    assert closure._previous_backend_gone(111,profile,1000)
