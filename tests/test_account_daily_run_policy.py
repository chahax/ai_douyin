"""Default unlimited runs retain accounting, identity, locks and unknown gates."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pytest

from test_account_playback_runtime_scope import account
from test_browser_control_manual_quota_preflight import setup_actor
from src.operations_accounts import browser_control_runtime as bridge
from src.operations_accounts.repository import AccountRuntimeUnavailable


@pytest.fixture(autouse=True)
def default_policy(monkeypatch):
    monkeypatch.delenv('AI_DOUYIN_ENFORCE_DAILY_RUN_LIMIT', raising=False)


def test_more_than_twenty_runs_preserves_counts_and_original_lock(account):
    repo, uid = account
    with repo.connection() as db:
        db.execute('UPDATE account_runtime_state SET day_key=?,daily_runs=1000 WHERE account_uuid=?',
                   (datetime.now(timezone.utc).date().isoformat(), uid))
    for operation in ['identity-recovery', 'publish', 'manual-session', 'maintenance:daily']:
        owner = operation + ':new'
        repo.acquire_runtime(uid, owner=owner, daily_limit=20, cooldown_seconds=0)
        with pytest.raises(AccountRuntimeUnavailable) as error:
            repo.acquire_runtime(uid, owner='other', daily_limit=20, cooldown_seconds=0)
        assert error.value.code == 'locked'
        repo.release_runtime(uid, owner=owner, success=True)
    assert repo.get_runtime_state(uid).daily_runs == 1004
    with repo.connection() as db:
        db.execute('UPDATE account_runtime_state SET circuit_open_until=? WHERE account_uuid=?',
                   ((datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(), uid))
    with pytest.raises(AccountRuntimeUnavailable) as error:
        repo.acquire_runtime(uid, owner='publish:next', daily_limit=20, cooldown_seconds=0)
    assert error.value.code == 'circuit_open'


@pytest.mark.parametrize('kind', ['manual', 'recovery', 'publish'])
def test_admission_above_old_cap_and_dedup(setup_actor, monkeypatch, kind):
    state, runtime, store, create = setup_actor
    state.daily_runs = 1000
    runtime.resolve().binding.status = 'active'
    monkeypatch.setattr(bridge, '_controls', lambda *a: {'state': 'active'})
    calls = []
    actor, command = create(kind, lambda *a: calls.append(kind) or {'known': True})
    assert actor.run_next()['state'] == 'succeeded'
    again = store.submit('account:one', command['binding_version'], kind, kind+':once', {'account_key':'one'})
    assert again['command_id'] == command['command_id'] and calls == [kind]


def test_paused_publication_stays_queued(setup_actor, monkeypatch):
    state, runtime, store, create = setup_actor
    monkeypatch.setattr(bridge, '_controls', lambda *a: {'state': 'paused'})
    actor, command = create('publish', lambda *a: pytest.fail('paused account must not publish'))
    result = actor.run_next()
    assert result['state'] == 'queued' and result['error_code'] == 'human_required'


def test_nested_publication_counts_without_resetting_parent_lease(account, monkeypatch):
    repo, uid = account
    repo.acquire_runtime(uid, owner='parent', daily_limit=20, cooldown_seconds=0)
    with repo.connection() as db:
        db.execute('UPDATE account_runtime_state SET daily_runs=1000 WHERE account_uuid=?', (uid,))
    resource = NS(account_uuid=uid, runtime=NS(bindings=repo))
    token = bridge._lease.set((uid, 'parent'))
    try:
        with bridge._publication_lease(resource):
            assert repo.get_runtime_state(uid).lock_owner == 'parent'
    finally:
        bridge._lease.reset(token)
    assert repo.get_runtime_state(uid).daily_runs == 1001
