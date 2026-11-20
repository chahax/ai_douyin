"""Original manual/recovery quota gates before handlers; no platform transport."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pytest

from src.operations_accounts import browser_control_runtime as bridge
from src.operations_accounts.browser_control import BrowserControlActor, BrowserControlStore
from src.operations_accounts.repository import AccountRuntimeUnavailable
from src.operations_accounts.runtime import AccountRuntimeService


@pytest.fixture
def setup_actor(tmp_path, monkeypatch):
    binding = NS(account_uuid='account:one', account_key='one', status='blocked',
        platform_identity_key='public:original', browser_environment_key='env:one',
        browser_profile_dir='profile/one', storage_state_path='state/one',
        confirmed_by='user', created_at='2026')
    context = NS(account_uuid='account:one', account_key='one', binding=binding,
        profile=NS(status='active', profile_version=1))
    state = NS(lock_owner='', day_key=datetime.now(timezone.utc).date().isoformat(),
        daily_runs=20, circuit_open_until='')
    runtime = NS(resolve=lambda *a, **k: context,
        bindings=NS(get_runtime_state=lambda *a: state))
    resource = NS(runtime=runtime, account_key='one', context=context, manual_tasks={})
    monkeypatch.setattr(bridge, '_legacy_manual_gate', lambda *a: None)
    monkeypatch.setattr(bridge, '_controls', lambda *a: pytest.fail('manual/recovery must retain pause exception'))
    store = BrowserControlStore(tmp_path / 'control.db')
    actors = []
    def create(kind, handler):
        version = bridge.binding_version(context)
        command = store.submit('account:one', version, kind, kind + ':once', {'account_key': 'one'})
        actor = BrowserControlActor(store, 'account:one', version, 'original-owner',
            {kind: handler}, admission=bridge._admission, context=resource)
        actors.append(actor)
        return actor, command
    yield state, runtime, store, create
    for actor in actors:
        actor.stop_heartbeat()


@pytest.mark.parametrize('kind', ['manual', 'recovery'])
def test_full_daily_quota_waits_before_handler_with_original_id(setup_actor, kind):
    state, runtime, store, create = setup_actor
    actor, command = create(kind, lambda *a: pytest.fail('no browser or handler dispatch at 20/day'))
    outcome = actor.run_next()
    assert outcome['state'] == 'queued' and outcome['error_code'] == 'daily_quota_exceeded'
    assert outcome['cursor'] is None and outcome['result'] is None
    assert state.daily_runs == 20 and state.lock_owner == ''
    again = store.submit('account:one', command['binding_version'], kind, kind + ':once', {'account_key': 'one'})
    assert again['command_id'] == command['command_id']


@pytest.mark.parametrize('kind', ['manual', 'recovery'])
def test_previous_utc_day_does_not_block_original_pending_request(setup_actor, kind):
    state, runtime, store, create = setup_actor
    state.day_key = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
    calls = []
    actor, command = create(kind, lambda *a: calls.append(kind) or {'known': True})
    assert actor.run_next()['state'] == 'succeeded'
    assert calls == [kind] and state.daily_runs == 20  # No quota counter reset by preflight.


@pytest.mark.parametrize('kind,expected', [('manual', 'succeeded'), ('recovery', 'queued')])
def test_original_manual_circuit_exception_and_recovery_circuit_gate(setup_actor, kind, expected):
    state, runtime, store, create = setup_actor
    state.daily_runs = 19
    state.circuit_open_until = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    calls = []
    actor, command = create(kind, lambda *a: calls.append(kind) or {'known': True})
    outcome = actor.run_next()
    assert outcome['state'] == expected
    assert calls == (['manual'] if kind == 'manual' else [])
    if kind == 'recovery':
        assert outcome['error_code'] == 'circuit_open'


@pytest.mark.parametrize('kind', ['manual', 'recovery'])
def test_after_handler_exception_still_unknown_not_requeued(setup_actor, kind):
    state, runtime, store, create = setup_actor
    state.daily_runs = 19
    def handler(*args):
        raise AccountRuntimeUnavailable('lock_owner_mismatch', 'Known type is not proof of no prior UI')
    actor, command = create(kind, handler)
    outcome = actor.run_next()
    assert outcome['state'] == 'outcome_unknown'
    assert outcome['error_code'] == 'handler_exception:AccountRuntimeUnavailable'


@pytest.mark.parametrize('kind', ['manual', 'recovery'])
def test_original_transactional_lease_rechecks_racing_quota(setup_actor, kind):
    state, runtime, store, create = setup_actor
    state.daily_runs = 19
    checks = []
    service = object.__new__(AccountRuntimeService)
    def acquire(account_uuid, **options):
        checks.append(options)
        # Another admitted operation consumed the final slot after preflight.
        state.daily_runs = 20
        raise AccountRuntimeUnavailable('daily_quota_exceeded', 'original transactional refusal')
    service.bindings = NS(acquire_runtime=acquire,
        release_runtime=lambda *a, **k: pytest.fail('lease was never acquired'))
    def handler(ctx, payload):
        options = {'allow_manual_verification': True} if kind == 'manual' else {}
        with service.operation_lease(ctx.resource.context,
                operation='manual-session' if kind == 'manual' else 'identity-recovery',
                daily_limit=20, cooldown_seconds=0, **options):
            pytest.fail('no page may be created before original transactional lease succeeds')
    actor, command = create(kind, handler)
    outcome = actor.run_next()
    assert outcome['state'] == 'outcome_unknown'
    assert outcome['error_code'] == 'handler_exception:AccountRuntimeUnavailable'
    assert checks[0]['daily_limit'] == 20 and checks[0]['cooldown_seconds'] == 0
    assert checks[0].get('allow_manual_verification', False) == (kind == 'manual')


@pytest.fixture(autouse=True)
def legacy_daily_cap_policy(monkeypatch):
    """Keep historical cap regressions explicit; production now defaults off."""
    monkeypatch.setenv("AI_DOUYIN_ENFORCE_DAILY_RUN_LIMIT", "1")
