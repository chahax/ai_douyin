"""Independent SQLite integration checks for playback quota and unknown owners."""
from datetime import datetime, timezone

import pytest

from src.operations_accounts import (
    AccountProfile, AccountProfileRepository, AccountBindingRepository,
    AccountRuntimeUnavailable, DouyinIdentity, stable_account_uuid,
)


@pytest.fixture
def account(tmp_path):
    profiles = AccountProfileRepository(tmp_path / 'accounts.db')
    profile = profiles.save(AccountProfile(
        account_uuid=stable_account_uuid('scope-account'), account_key='scope-account',
        display_name='scope account', domain_strategy_id='legal_services', seed_keywords=['法律'],
    ))
    repo = AccountBindingRepository(profiles.db_path)
    repo.bind(profile, DouyinIdentity(nickname='scope', public_uid='scope-uid', verification_source='page_verified'),
              browser_environment_key='scope-browser', browser_profile_dir=str(tmp_path / 'browser'),
              storage_state_path=str(tmp_path / 'state.json'), confirmed_by='test')
    repo.get_runtime_state(profile.account_uuid)
    return repo, profile.account_uuid


def test_global_sync_usage_does_not_spend_playback_quota_and_three_is_still_limit(account):
    repo, uuid = account
    with repo.connection() as db:
        db.execute('UPDATE account_runtime_state SET day_key=?,daily_runs=10 WHERE account_uuid=?',
                   (datetime.now(timezone.utc).date().isoformat(), uuid))
    for index in range(3):
        owner = f'maintenance:playback:independent-{index}'
        repo.acquire_runtime(uuid, owner=owner, daily_limit=3, cooldown_seconds=0, quota_scope='playback')
        repo.release_runtime(uuid, owner=owner, success=True)
    with pytest.raises(AccountRuntimeUnavailable) as failure:
        repo.acquire_runtime(uuid, owner='maintenance:playback:fourth', daily_limit=3,
                             cooldown_seconds=0, quota_scope='playback')
    assert failure.value.code == 'daily_quota_exceeded'
    assert repo.get_runtime_state(uuid).daily_runs == 13
    assert not repo.get_runtime_state(uuid).lock_owner


@pytest.mark.parametrize('expires', ['2000-01-01T00:00:00+00:00', ''])
def test_background_playback_cannot_steal_expired_or_unstamped_unknown_owner(account, expires):
    repo, uuid = account
    with repo.connection() as db:
        db.execute('UPDATE account_runtime_state SET lock_owner=?,lock_expires_at=? WHERE account_uuid=?',
                   ('original-unknown-id', expires, uuid))
    with pytest.raises(AccountRuntimeUnavailable) as failure:
        repo.acquire_runtime(uuid, owner='maintenance:playback:new', daily_limit=3,
                             cooldown_seconds=0, quota_scope='playback')
    assert failure.value.code == 'locked'
    state = repo.get_runtime_state(uuid)
    assert state.lock_owner == 'original-unknown-id' and state.lock_expires_at == expires
    assert state.daily_runs == 0


@pytest.mark.parametrize('owner,limit', [('maintenance:daily:new', 3), ('maintenance:playback:new', 4)])
def test_playback_scope_cannot_be_reused_to_bypass_another_operation_or_expand_limit(account, owner, limit):
    repo, uuid = account
    with pytest.raises(ValueError):
        repo.acquire_runtime(uuid, owner=owner, daily_limit=limit, cooldown_seconds=0, quota_scope='playback')
    assert repo.get_runtime_state(uuid).daily_runs == 0


def test_unlimited_viewing_preserves_usage_and_other_operation_limits(account):
    repo, uuid = account
    for index in range(5):
        owner = f"maintenance:playback:unlimited-{index}"
        repo.acquire_runtime(uuid, owner=owner, daily_limit=0, cooldown_seconds=0,
                             quota_scope="playback", quota_baseline=30)
        repo.release_runtime(uuid, owner=owner, success=True)
    assert repo.get_operation_usage(uuid, "playback")["runs"] == 35
    with pytest.raises(AccountRuntimeUnavailable) as error:
        repo.acquire_runtime(uuid, owner="publish:test", daily_limit=3, cooldown_seconds=0)
    assert error.value.code == "daily_quota_exceeded"
    with pytest.raises(ValueError):
        repo.acquire_runtime(uuid, owner="publish:test", daily_limit=0,
                             cooldown_seconds=0, quota_scope="playback")


def test_unlimited_viewing_still_rejects_unknown_owner(account):
    repo, uuid = account
    with repo.connection() as db:
        db.execute("UPDATE account_runtime_state SET lock_owner='unknown-original' WHERE account_uuid=?", (uuid,))
    with pytest.raises(AccountRuntimeUnavailable) as error:
        repo.acquire_runtime(uuid, owner="maintenance:playback:new", daily_limit=0,
                             cooldown_seconds=0, quota_scope="playback")
    assert error.value.code == "locked"


@pytest.fixture(autouse=True)
def legacy_daily_cap_policy(monkeypatch):
    """Keep historical cap regressions explicit; production now defaults off."""
    monkeypatch.setenv("AI_DOUYIN_ENFORCE_DAILY_RUN_LIMIT", "1")
