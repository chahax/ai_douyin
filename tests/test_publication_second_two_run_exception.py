"""Second explicit 23->25 grant, immutable first registration and control41/42."""
from copy import deepcopy
import json
from types import SimpleNamespace as NS

import pytest

from src.operations_accounts import publication_two_run_authorization as quota
from src.operations_accounts.browser_control import BrowserControlRejected
from src.scheduler import account_refresh
from test_publication_two_run_exception import (frozen, sha, context_for,
    test_real_scheduler_recovery_and_publish_consume_only_two_original_counted_leases as exercise_original_flow)


@pytest.fixture
def second(frozen):
    first = frozen
    first_registry = quota.REGISTRY.read_bytes()
    with account_refresh.connect(first.scheduler) as db:
        # Isolated fixture represents this second, already-paused control state.
        db.execute("UPDATE account_controls SET revision=40 WHERE account_uuid='acct:one'")
    value = quota.build_authorization(first.prepared, account_uuid='acct:one', account_key='one',
        recovery_key='second:original-recovery', publish_key='second:original-publish',
        recovery_control_revision=41, user_statement='追加账号核验1次＋本视频发布1次，继续部署发布', version=2)
    path = first.root / 'AUTHORIZATION_V2.json'
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    reference = quota.register_authorization(path, sha(path))
    assert quota.REGISTRY.read_bytes() == first_registry
    return NS(**dict(vars(first), value=value, auth=path, ref=reference),
        first_value=first.value, first_ref=first.ref, first_registry=first_registry)


def test_v2_real_scheduler_actor_two_counted_operations23_to24_to25(second, monkeypatch):
    second.queued_manual_first = True
    exercise_original_flow(second, monkeypatch)
    assert quota.REGISTRY.read_bytes() == second.first_registry


def test_second_registry_prioritized_without_rebinding_first_payload(second):
    f = second
    assert quota.validate_authorization(f.first_ref)['max_daily_runs'] == 22
    assert quota.validate_authorization(f.ref)['max_daily_runs'] == 25
    control = {'account_uuid': 'acct:one', 'account_key': 'one', 'state': 'recovering', 'revision': 41}
    assert quota.registered_recovery('one', control)[0] == f.ref
    # Old valid payloads continue to bind v1, rather than acquiring the v2 cap.
    original = NS(value=f.first_value, ref=f.first_ref)
    old_ctx = context_for(original)
    old_control = dict(control, revision=f.first_value['recovery_control_revision'])
    assert quota.authorized_daily_limit(old_ctx, 'identity-recovery', account_uuid='acct:one', control=old_control) == 22
    with pytest.raises(BrowserControlRejected):
        quota.authorized_daily_limit(old_ctx, 'identity-recovery', account_uuid='acct:one', control=control)
    assert quota.registered_recovery('one', old_control) is None  # No fallback to old successful recovery.


def test_second_registration_exclusive_and_first_bytes_unchanged(second):
    f = second
    assert quota.register_authorization(f.auth, sha(f.auth)) == f.ref
    replacement = f.root / 'REPLACEMENT.json'
    replacement.write_bytes(f.auth.read_bytes())
    with pytest.raises(BrowserControlRejected): quota.register_authorization(replacement, sha(replacement))
    assert quota.REGISTRY.read_bytes() == f.first_registry
    assert json.loads(quota.REGISTRY_V2.read_bytes()) == f.ref


@pytest.mark.parametrize('change', ['baseline', 'cap', 'revision', 'old_key', 'account', 'prepared', 'schema', 'cancel'])
def test_second_grant_has_no_generalized_budget_or_cancellation_permission(second, change):
    f = second
    value = deepcopy(f.value)
    if change == 'baseline': value['baseline_daily_runs'] = 22
    if change == 'cap': value['max_daily_runs'] = 26
    if change == 'revision': value['recovery_control_revision'] = 42
    if change == 'old_key': value['idempotency_keys']['publish'] = f.first_value['idempotency_keys']['recovery']
    if change == 'account': value['account_uuid'] = 'another-account'
    if change == 'prepared':
        replacement = f.root / 'OTHER_PREPARED.json'
        replacement.write_bytes(f.prepared.read_bytes())
        value['prepared'] = {'path': str(replacement), 'sha256': sha(replacement)}
    if change == 'schema': value['schema'] = 'publication_two_run_exception/20261019/v3'
    if change == 'cancel': value['cancel_manual_command_id'] = 'not-authorized-manual'
    candidate = f.root / 'INVALID_V2.json'
    candidate.write_text(json.dumps(value), encoding='utf-8')
    with pytest.raises(BrowserControlRejected):
        quota.validate_authorization({'path': str(candidate), 'sha256': sha(candidate)}, require_registered=False)


def test_changed_second_authorization_fails_closed_without_falling_back_to_v1(second):
    f = second
    f.auth.write_bytes(f.auth.read_bytes() + b' ')
    old_control = {'account_uuid': 'acct:one', 'account_key': 'one', 'state': 'recovering',
        'revision': f.first_value['recovery_control_revision']}
    with pytest.raises(BrowserControlRejected): quota.registered_recovery('one', old_control)
    assert quota.validate_authorization(f.first_ref)['max_daily_runs'] == 22


def test_v2_absent_preserves_original_recovery_selection(frozen):
    f = frozen
    control = {'account_uuid': 'acct:one', 'account_key': 'one', 'state': 'recovering',
        'revision': f.value['recovery_control_revision']}
    assert not quota.REGISTRY_V2.exists()
    assert quota.registered_recovery('one', control)[0] == f.ref
