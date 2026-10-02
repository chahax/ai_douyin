from __future__ import annotations

import pytest

from src.operations_accounts import (
    AccountBindingConflict,
    AccountBindingRepository,
    AccountOAuthStateError,
    AccountProfile,
    AccountProfileRepository,
    AccountRuntimeUnavailable,
    DouyinIdentity,
    stable_account_uuid,
)


def _profile(key: str) -> AccountProfile:
    return AccountProfile(
        account_uuid=stable_account_uuid(key),
        account_key=key,
        display_name=key,
        domain_strategy_id="legal_services",
        seed_keywords=["法律"],
        domain_config={"practice_areas": ["婚姻家事"]},
    )


def _identity(uid: str) -> DouyinIdentity:
    return DouyinIdentity(
        nickname=f"账号-{uid}",
        public_uid=uid,
        sec_uid=f"sec-{uid}",
        verification_source="page_verified",
    )


def test_binding_enforces_account_browser_and_identity_uniqueness(tmp_path) -> None:
    db_path = tmp_path / "accounts.db"
    profiles = AccountProfileRepository(db_path)
    first = profiles.save(_profile("account01"))
    second = profiles.save(_profile("account02"))
    bindings = AccountBindingRepository(db_path)

    saved = bindings.bind(
        first,
        _identity("uid-01"),
        browser_environment_key="browser-01",
        browser_profile_dir=str(tmp_path / "browser-01"),
        storage_state_path=str(tmp_path / "state-01.json"),
        confirmed_by="admin",
    )

    assert saved.account_uuid == first.account_uuid
    assert saved.public_uid == "uid-01"
    assert saved.status == "active"

    with pytest.raises(AccountBindingConflict):
        bindings.bind(
            second,
            _identity("uid-01"),
            browser_environment_key="browser-02",
            browser_profile_dir=str(tmp_path / "browser-02"),
            storage_state_path=str(tmp_path / "state-02.json"),
            confirmed_by="admin",
        )

    with pytest.raises(AccountBindingConflict):
        bindings.bind(
            second,
            _identity("uid-02"),
            browser_environment_key="browser-01",
            browser_profile_dir=str(tmp_path / "browser-01"),
            storage_state_path=str(tmp_path / "state-01.json"),
            confirmed_by="admin",
        )


def test_runtime_lock_enforces_mutex_quota_cooldown_and_circuit_breaker(tmp_path) -> None:
    db_path = tmp_path / "accounts.db"
    profiles = AccountProfileRepository(db_path)
    profile = profiles.save(_profile("account01"))
    bindings = AccountBindingRepository(db_path)

    bindings.acquire_runtime(
        profile.account_uuid,
        owner="daily:first",
        daily_limit=5,
        cooldown_seconds=0,
    )
    with pytest.raises(AccountRuntimeUnavailable) as locked:
        bindings.acquire_runtime(
            profile.account_uuid,
            owner="daily:second",
            daily_limit=5,
            cooldown_seconds=0,
        )
    assert locked.value.code == "locked"
    bindings.release_runtime(
        profile.account_uuid,
        owner="daily:first",
        success=True,
    )

    with pytest.raises(AccountRuntimeUnavailable) as cooldown:
        bindings.acquire_runtime(
            profile.account_uuid,
            owner="daily:cooldown",
            daily_limit=5,
            cooldown_seconds=3600,
        )
    assert cooldown.value.code == "cooldown"

    bindings.acquire_runtime(
        profile.account_uuid,
        owner="failure:1",
        daily_limit=10,
        cooldown_seconds=0,
    )
    bindings.release_runtime(profile.account_uuid, owner="failure:1", success=False)
    bindings.acquire_runtime(
        profile.account_uuid,
        owner="failure:2",
        daily_limit=10,
        cooldown_seconds=0,
    )
    bindings.release_runtime(profile.account_uuid, owner="failure:2", success=False)
    bindings.acquire_runtime(
        profile.account_uuid,
        owner="failure:3",
        daily_limit=10,
        cooldown_seconds=0,
    )
    state = bindings.release_runtime(
        profile.account_uuid,
        owner="failure:3",
        success=False,
    )
    assert state.circuit_open_until
    with pytest.raises(AccountRuntimeUnavailable) as circuit:
        bindings.acquire_runtime(
            profile.account_uuid,
            owner="after-circuit",
            daily_limit=10,
            cooldown_seconds=0,
        )
    assert circuit.value.code == "circuit_open"


def test_oauth_state_survives_new_session_and_is_consumed_once(tmp_path) -> None:
    db_path = tmp_path / "accounts.db"
    profiles = AccountProfileRepository(db_path)
    profiles.save(_profile("account01"))
    bindings = AccountBindingRepository(db_path)

    raw_state = bindings.create_oauth_attempt(
        "account01",
        requested_by="admin",
    )
    attempt = bindings.consume_oauth_attempt(raw_state)

    assert attempt["account_key"] == "account01"
    assert attempt["requested_by"] == "admin"
    with pytest.raises(AccountOAuthStateError):
        bindings.consume_oauth_attempt(raw_state)
