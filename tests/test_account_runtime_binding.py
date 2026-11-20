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


@pytest.fixture
def recovery_runtime(tmp_path, monkeypatch):
    # Exercise the injected local runtime, never the real managed account.
    monkeypatch.setenv("AI_DOUYIN_BROWSER_CONTROL", "0")
    from types import SimpleNamespace
    from src.operations_accounts.runtime import AccountRuntimeService, AccountRuntimeContext, PreparedBrowserEnvironment

    profiles = AccountProfileRepository(tmp_path / "recovery.db")
    profile = profiles.save(_profile("account01"))
    bindings = AccountBindingRepository(profiles.db_path)
    bindings.bind(profile, _identity("uid-01"), browser_environment_key="browser-01",
                  browser_profile_dir=str(tmp_path / "browser"),
                  storage_state_path=str(tmp_path / "state.json"), confirmed_by="admin")
    session = SimpleNamespace(stops=0, saves=0)
    def stop():
        session.stops += 1
    def save():
        session.saves += 1
    session.stop = stop
    session.save_storage_state = save
    observed = []
    def probe(active):
        observed.append(active)
        return _identity("uid-01")
    verifier = SimpleNamespace(probe=probe)
    runtime = AccountRuntimeService(profile_repository=profiles,
                                    binding_repository=bindings, verifier=verifier)
    monkeypatch.setattr(runtime, "prepare_browser_environment", lambda key: PreparedBrowserEnvironment(
        profile=profile, browser_environment_key="browser-01",
        browser_profile_dir=str(tmp_path / "browser"), storage_state_path=str(tmp_path / "state.json")))
    monkeypatch.setattr(AccountRuntimeContext, "create_browser_session", lambda *a, **k: session)
    return runtime, bindings, profile, session, observed


def test_recovery_navigation_failure_retains_evidence_and_original_binding(recovery_runtime):
    from src.platform_adapter.douyin_identity import DouyinIdentityVerificationError
    runtime, bindings, profile, session, _ = recovery_runtime
    evidence = dict(navigation_committed=False, target_matched=False, ready_state='loading')
    def probe(active):
        raise DouyinIdentityVerificationError('browser_navigation_timeout',
            'Navigation unavailable', navigation_evidence=evidence)
    runtime.verifier.probe = probe
    check = runtime.probe_recovery(profile.account_key)
    assert not check.healthy and check.status == 'browser_navigation_timeout'
    assert check.navigation_evidence == evidence
    assert bindings.get(profile.account_key).public_uid == 'uid-01'
    assert session.saves == 0 and session.stops == 1
    assert not bindings.get_runtime_state(profile.account_uuid).lock_owner


@pytest.mark.parametrize("prior_status", ["blocked", "expired", "mismatch"])
def test_explicit_recovery_checks_original_session_without_bypassing_business_gate(recovery_runtime, prior_status):
    from src.operations_accounts.runtime import AccountRuntimeError
    runtime, bindings, profile, session, observed = recovery_runtime
    bindings.update_health(profile.account_key, status=prior_status, error="old failure")
    with pytest.raises(AccountRuntimeError) as error:
        runtime.resolve(profile.account_key)
    assert error.value.code == "login_unhealthy"
    assert "请重新登录" not in str(error.value)
    check = runtime.probe_recovery(profile.account_key)
    assert check.healthy and check.status == "active"
    assert check.expected.public_uid == "uid-01"
    assert observed == [session] and session.saves == 1 and session.stops == 1
    assert not bindings.get_runtime_state(profile.account_uuid).lock_owner


def test_recovery_different_identity_never_rebinds_or_checkpoints(recovery_runtime):
    runtime, bindings, profile, session, _ = recovery_runtime
    runtime.verifier.probe = lambda active: _identity("uid-other")
    check = runtime.probe_recovery(profile.account_key)
    assert not check.healthy and check.status == "identity_mismatch"
    assert bindings.get(profile.account_key).public_uid == "uid-01"
    assert session.saves == 0 and session.stops == 1
    assert bindings.get_runtime_state(profile.account_uuid).consecutive_failures == 1


@pytest.mark.parametrize("code, status", [("human_required", "blocked"), ("login_expired", "expired"), ("identity_unavailable", "blocked")])
def test_recovery_preserves_identity_failure_reason(recovery_runtime, code, status):
    from src.platform_adapter.douyin_identity import DouyinIdentityVerificationError
    runtime, bindings, profile, session, _ = recovery_runtime
    def fail(active):
        raise DouyinIdentityVerificationError(code, "reason")
    runtime.verifier.probe = fail
    check = runtime.probe_recovery(profile.account_key)
    assert not check.healthy and check.status == code
    assert bindings.get(profile.account_key).status == status
    assert session.saves == 0 and session.stops == 1


def test_recovery_network_failure_does_not_claim_login_expired(recovery_runtime):
    from src.operations_accounts.runtime import AccountRuntimeError
    runtime, bindings, profile, session, _ = recovery_runtime
    def fail(active):
        raise TimeoutError("network timed out")
    runtime.verifier.probe = fail
    with pytest.raises(AccountRuntimeError) as error:
        runtime.probe_recovery(profile.account_key)
    assert error.value.code == "recovery_probe_failed"
    assert bindings.get(profile.account_key).status == "active"
    assert session.saves == 0 and session.stops == 1


@pytest.mark.parametrize("expired", [False, True])
def test_recovery_does_not_steal_existing_unknown_lease(recovery_runtime, expired):
    runtime, bindings, profile, session, observed = recovery_runtime
    bindings.acquire_runtime(profile.account_uuid, owner="original-task", daily_limit=20, cooldown_seconds=0)
    if expired:
        with bindings.connection() as conn:
            conn.execute("UPDATE account_runtime_state SET lock_expires_at = ? WHERE account_uuid = ?",
                         ("2000-01-01T00:00:00+00:00", profile.account_uuid))
    with pytest.raises(AccountRuntimeUnavailable) as error:
        runtime.probe_recovery(profile.account_key)
    assert error.value.code == "locked"
    assert not observed and not session.stops
    assert bindings.get_runtime_state(profile.account_uuid).lock_owner == "original-task"


def test_recovery_keeps_daily_quota(recovery_runtime):
    runtime, bindings, profile, session, observed = recovery_runtime
    bindings.acquire_runtime(profile.account_uuid, owner="old", daily_limit=20, cooldown_seconds=0)
    bindings.release_runtime(profile.account_uuid, owner="old", success=True)
    with bindings.connection() as conn:
        conn.execute("UPDATE account_runtime_state SET daily_runs = 20 WHERE account_uuid = ?", (profile.account_uuid,))
    with pytest.raises(AccountRuntimeUnavailable) as error:
        runtime.probe_recovery(profile.account_key)
    assert error.value.code == "daily_quota_exceeded"
    assert not observed and not session.stops


def test_manual_login_holds_profile_mutex_before_binding(recovery_runtime):
    runtime, bindings, profile, _, _ = recovery_runtime
    with bindings.connection() as conn:
        conn.execute("DELETE FROM account_runtime_bindings WHERE account_uuid = ?", (profile.account_uuid,))
    with runtime.manual_browser_environment(profile.account_key) as prepared:
        assert prepared.profile.account_uuid == profile.account_uuid
        assert bindings.get_runtime_state(profile.account_uuid).lock_owner.startswith("manual-session:")
        with pytest.raises(AccountRuntimeUnavailable) as error:
            bindings.acquire_runtime(profile.account_uuid, owner="background", daily_limit=20, cooldown_seconds=0)
        assert error.value.code == "locked"
    assert not bindings.get_runtime_state(profile.account_uuid).lock_owner


def test_manual_login_refuses_unknown_expired_lease(recovery_runtime):
    runtime, bindings, profile, _, _ = recovery_runtime
    bindings.acquire_runtime(profile.account_uuid, owner="unknown-old", daily_limit=20, cooldown_seconds=0)
    with bindings.connection() as conn:
        conn.execute("UPDATE account_runtime_state SET lock_expires_at = ? WHERE account_uuid = ?",
                     ("2000-01-01T00:00:00+00:00", profile.account_uuid))
    with pytest.raises(AccountRuntimeUnavailable) as error:
        with runtime.manual_browser_environment(profile.account_key):
            pytest.fail("must not yield when an old operation remains unknown")
    assert error.value.code == "locked"
    assert bindings.get_runtime_state(profile.account_uuid).lock_owner == "unknown-old"


def _open_business_circuit(bindings, profile):
    for index in range(3):
        owner = f"failed-identity:{index}"
        bindings.acquire_runtime(profile.account_uuid, owner=owner, daily_limit=20, cooldown_seconds=0)
        bindings.release_runtime(profile.account_uuid, owner=owner, success=False)
    return bindings.get_runtime_state(profile.account_uuid)


def test_circuit_allows_only_manual_repair_and_preserves_business_health(recovery_runtime):
    runtime, bindings, profile, session, observed = recovery_runtime
    before = _open_business_circuit(bindings, profile)
    with pytest.raises(AccountRuntimeUnavailable) as error:
        runtime.probe_recovery(profile.account_key)
    assert error.value.code == "circuit_open"
    with runtime.manual_browser_environment(profile.account_key):
        during = bindings.get_runtime_state(profile.account_uuid)
        assert during.lock_owner.startswith("manual-session:")
        assert during.consecutive_failures == before.consecutive_failures == 3
        assert during.circuit_open_until == before.circuit_open_until
    after = bindings.get_runtime_state(profile.account_uuid)
    assert not after.lock_owner
    assert after.daily_runs == before.daily_runs + 1
    assert after.consecutive_failures == before.consecutive_failures
    assert after.circuit_open_until == before.circuit_open_until
    with pytest.raises(AccountRuntimeUnavailable) as error:
        runtime.probe_recovery(profile.account_key)
    assert error.value.code == "circuit_open"
    assert not observed and session.stops == 0


@pytest.mark.parametrize("guard", ["quota", "unknown_expired_lock"])
def test_manual_circuit_exception_keeps_quota_and_old_lock(recovery_runtime, guard):
    runtime, bindings, profile, _, _ = recovery_runtime
    before = _open_business_circuit(bindings, profile)
    with bindings.connection() as conn:
        if guard == "quota":
            conn.execute("UPDATE account_runtime_state SET daily_runs = 20 WHERE account_uuid = ?", (profile.account_uuid,))
        else:
            conn.execute("UPDATE account_runtime_state SET lock_owner = ?, lock_expires_at = ? WHERE account_uuid = ?",
                         ("unknown-old", "2000-01-01T00:00:00+00:00", profile.account_uuid))
    with pytest.raises(AccountRuntimeUnavailable) as error:
        with runtime.manual_browser_environment(profile.account_key):
            pytest.fail("manual repair must respect old claims and daily quota")
    assert error.value.code == ("daily_quota_exceeded" if guard == "quota" else "locked")
    after = bindings.get_runtime_state(profile.account_uuid)
    assert after.consecutive_failures == 3
    assert after.circuit_open_until == before.circuit_open_until
    if guard != "quota":
        assert after.lock_owner == "unknown-old"
        # The repository admission must also reject the unknown owner atomically,
        # even when called without the runtime service's earlier precheck.
        with pytest.raises(AccountRuntimeUnavailable) as error:
            bindings.acquire_runtime(profile.account_uuid, owner="manual-session:new", daily_limit=20,
                                     cooldown_seconds=0, allow_manual_verification=True)
        assert error.value.code == "locked"


def test_manual_exception_rejects_automatic_operation_purpose(recovery_runtime):
    runtime, bindings, profile, _, _ = recovery_runtime
    with pytest.raises(ValueError):
        with runtime.operation_lease(runtime.resolve(profile.account_key), operation="identity-recovery",
                                     daily_limit=20, cooldown_seconds=0, allow_manual_verification=True):
            pytest.fail("automatic probe cannot request the manual exception")
    with pytest.raises(ValueError):
        bindings.acquire_runtime(profile.account_uuid, owner="maintenance:background", daily_limit=20,
                                 cooldown_seconds=0, allow_manual_verification=True)


@pytest.fixture(autouse=True)
def legacy_daily_cap_policy(monkeypatch):
    """Keep historical cap regressions explicit; production now defaults off."""
    monkeypatch.setenv("AI_DOUYIN_ENFORCE_DAILY_RUN_LIMIT", "1")
