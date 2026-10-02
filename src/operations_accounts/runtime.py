"""Unified runtime context for every operation performed as a Douyin account."""

from __future__ import annotations

import hashlib
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from src.platform_adapter.browser_session import BrowserSession
from src.platform_adapter.douyin_identity import (
    DouyinIdentityVerificationError,
    DouyinPageIdentityVerifier,
)
from src.platform_adapter.douyin_warmup import DouyinWarmupService

from .models import AccountBinding, AccountProfile, DouyinIdentity
from .repository import (
    AccountBindingNotFound,
    AccountBindingRepository,
    AccountProfileRepository,
)


class AccountRuntimeError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(slots=True)
class RuntimeIdentityCheck:
    healthy: bool
    status: str
    message: str
    expected: AccountBinding
    actual: DouyinIdentity | None = None


@dataclass(slots=True)
class AccountRuntimeContext:
    profile: AccountProfile
    binding: AccountBinding
    browser_environment_key: str
    browser_profile_dir: str
    storage_state_path: str

    @property
    def account_key(self) -> str:
        return self.profile.account_key

    @property
    def account_uuid(self) -> str:
        return self.profile.account_uuid

    @property
    def identity_label(self) -> str:
        return self.binding.display_identity

    def create_browser_session(self, *, headless: bool = False) -> BrowserSession:
        return DouyinWarmupService().build_browser_session(
            self.account_key,
            headless=headless,
        )


@dataclass(slots=True)
class PreparedBrowserEnvironment:
    profile: AccountProfile
    browser_environment_key: str
    browser_profile_dir: str
    storage_state_path: str

    def create_browser_session(self, *, headless: bool = False) -> BrowserSession:
        return DouyinWarmupService().build_browser_session(
            self.profile.account_key,
            headless=headless,
        )


class AccountRuntimeService:
    def __init__(
        self,
        *,
        profile_repository: AccountProfileRepository | None = None,
        binding_repository: AccountBindingRepository | None = None,
        verifier: DouyinPageIdentityVerifier | None = None,
    ) -> None:
        self.profiles = profile_repository or AccountProfileRepository()
        self.bindings = binding_repository or AccountBindingRepository(
            self.profiles.db_path
        )
        self.verifier = verifier or DouyinPageIdentityVerifier()

    def prepare_browser_environment(
        self, account_key: str
    ) -> PreparedBrowserEnvironment:
        profile = self.profiles.get(account_key)
        if profile.status != 'active':
            raise AccountRuntimeError('account_disabled', '该运营账号已暂停或停用，不能启动浏览器任务。')
        warmup = DouyinWarmupService()
        warmup.update_account(
            profile.account_key,
            display_name=profile.display_name or profile.account_key,
            purpose=profile.domain_strategy_id,
            keywords=profile.seed_keywords,
        )
        session = warmup.build_browser_session(profile.account_key, headless=False)
        profile_dir = str(Path(session.config.user_data_dir).resolve())
        storage_path = str(Path(session.config.storage_state_path).resolve())
        environment_key = _browser_environment_key(profile.account_key, profile_dir)
        return PreparedBrowserEnvironment(
            profile=profile,
            browser_environment_key=environment_key,
            browser_profile_dir=profile_dir,
            storage_state_path=storage_path,
        )

    def resolve(
        self,
        account_key: str,
        *,
        require_healthy: bool = True,
    ) -> AccountRuntimeContext:
        prepared = self.prepare_browser_environment(account_key)
        try:
            binding = self.bindings.get(account_key)
        except AccountBindingNotFound as exc:
            raise AccountRuntimeError(
                "binding_required",
                f"运营账号 {account_key} 尚未绑定真实抖音账号。",
            ) from exc
        if binding.account_uuid != prepared.profile.account_uuid:
            raise AccountRuntimeError(
                "account_uuid_mismatch", "运营账号与身份绑定的 UUID 不一致。"
            )
        if binding.browser_environment_key != prepared.browser_environment_key:
            raise AccountRuntimeError(
                "browser_environment_mismatch",
                "当前浏览器环境与已确认绑定不一致，已拒绝继续。",
            )
        if require_healthy and binding.status != "active":
            raise AccountRuntimeError(
                "login_unhealthy",
                f"账号绑定状态为 {binding.status}，请重新登录并验证。",
            )
        return AccountRuntimeContext(
            profile=prepared.profile,
            binding=binding,
            browser_environment_key=prepared.browser_environment_key,
            browser_profile_dir=prepared.browser_profile_dir,
            storage_state_path=prepared.storage_state_path,
        )

    def confirm_binding(
        self,
        account_key: str,
        identity: DouyinIdentity,
        *,
        confirmed_by: str,
        allow_rebind: bool = False,
    ) -> AccountBinding:
        prepared = self.prepare_browser_environment(account_key)
        return self.bindings.bind(
            prepared.profile,
            identity,
            browser_environment_key=prepared.browser_environment_key,
            browser_profile_dir=prepared.browser_profile_dir,
            storage_state_path=prepared.storage_state_path,
            confirmed_by=confirmed_by,
            allow_rebind=allow_rebind,
        )

    def probe_unbound_identity(
        self,
        account_key: str,
        *,
        headless: bool = False,
    ) -> DouyinIdentity:
        prepared = self.prepare_browser_environment(account_key)
        session = prepared.create_browser_session(headless=headless)
        try:
            return self.verifier.probe(session)
        finally:
            session.stop()

    def verify_identity(
        self,
        context: AccountRuntimeContext,
        *,
        session: BrowserSession | None = None,
    ) -> RuntimeIdentityCheck:
        own_session = session is None
        active_session = session or context.create_browser_session(headless=False)
        try:
            actual = self.verifier.probe(active_session)
        except DouyinIdentityVerificationError as exc:
            status = "expired" if exc.code == "login_expired" else "blocked"
            binding = self.bindings.update_health(
                context.account_key,
                status=status,
                error=str(exc),
            )
            return RuntimeIdentityCheck(
                healthy=False,
                status=exc.code,
                message=str(exc),
                expected=binding,
            )
        finally:
            if own_session:
                active_session.stop()

        if not _identities_match(context.binding, actual):
            binding = self.bindings.update_health(
                context.account_key,
                status="mismatch",
                error=(
                    f"当前登录账号 {actual.nickname} 与绑定账号 "
                    f"{context.binding.nickname} 不一致。"
                ),
            )
            return RuntimeIdentityCheck(
                healthy=False,
                status="identity_mismatch",
                message=binding.last_error,
                expected=binding,
                actual=actual,
            )

        binding = self.bindings.update_health(
            context.account_key,
            status="active",
            identity=actual,
        )
        context.binding = binding
        return RuntimeIdentityCheck(
            healthy=True,
            status="active",
            message=f"当前登录身份已确认：{binding.display_identity}",
            expected=binding,
            actual=actual,
        )

    @contextmanager
    def operation_lease(
        self,
        context: AccountRuntimeContext,
        *,
        operation: str,
        daily_limit: int,
        cooldown_seconds: int,
        lock_seconds: int = 1800,
    ) -> Iterator[str]:
        owner = f"{operation}:{uuid.uuid4().hex}"
        self.bindings.acquire_runtime(
            context.account_uuid,
            owner=owner,
            daily_limit=daily_limit,
            cooldown_seconds=cooldown_seconds,
            lock_seconds=lock_seconds,
        )
        success = False
        try:
            yield owner
            success = True
        finally:
            self.bindings.release_runtime(
                context.account_uuid,
                owner=owner,
                success=success,
            )


def _browser_environment_key(account_key: str, profile_dir: str) -> str:
    digest = hashlib.sha256(
        f"{account_key}|{Path(profile_dir).resolve()}".encode("utf-8")
    ).hexdigest()[:24]
    return f"douyin-browser:{digest}"


def _identities_match(binding: AccountBinding, actual: DouyinIdentity) -> bool:
    """Compare the strongest identity identifier available to both records."""
    pairs = (
        (binding.open_id, actual.open_id),
        (binding.sec_uid, actual.sec_uid),
        (binding.public_uid, actual.public_uid),
    )
    for expected, observed in pairs:
        if expected and observed:
            return expected == observed
    return False
