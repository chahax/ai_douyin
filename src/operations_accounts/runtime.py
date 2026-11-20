"""Unified runtime context for every operation performed as a Douyin account."""

from __future__ import annotations

import hashlib
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
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
    AccountRuntimeUnavailable,
)

_first_binding_scope = ContextVar('first_binding_scope', default=None)


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
    navigation_evidence: dict | None = None


class _RecoveryIdentityFailed(RuntimeError):
    def __init__(self, check: RuntimeIdentityCheck):
        super().__init__(check.message)
        self.check = check


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
        from .browser_control_runtime import borrow_session
        borrowed = borrow_session(self.account_key, headless=headless)
        if borrowed is not None:
            return borrowed
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

    @property
    def account_uuid(self) -> str:
        return self.profile.account_uuid

    def create_browser_session(self, *, headless: bool = False) -> BrowserSession:
        scope = _first_binding_scope.get()
        if scope is not None:
            runtime, prepared, owner = scope
            if (self.account_uuid != prepared.account_uuid or self.profile.account_key != prepared.profile.account_key
                    or self.browser_environment_key != prepared.browser_environment_key
                    or self.browser_profile_dir != prepared.browser_profile_dir or self.storage_state_path != prepared.storage_state_path):
                raise AccountRuntimeError('bootstrap_environment_changed','首次绑定的账号或专属环境已变化。')
            runtime._check_first_binding(prepared, owner)
            session = DouyinWarmupService().build_browser_session(self.profile.account_key,headless=headless)
            if (str(Path(session.config.user_data_dir).resolve()) != self.browser_profile_dir
                    or str(Path(session.config.storage_state_path).resolve()) != self.storage_state_path):
                raise AccountRuntimeError('bootstrap_environment_changed','首次绑定浏览器路径不匹配。')
            return session
        from .browser_control_runtime import borrow_session
        borrowed = borrow_session(self.profile.account_key, headless=headless)
        if borrowed is not None:
            return borrowed
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

    @contextmanager
    def manual_browser_environment(self, account_key: str) -> Iterator[PreparedBrowserEnvironment]:
        """Hold the account mutex across manual login and subsequent probing.

        Uses the profile UUID even before an identity is bound. Callers must
        pause background schedules first for an already bound account.
        Manual repair may enter during a business circuit cooldown; it keeps
        existing failures, circuit, quota and unknown locks. It never resumes
        background business by itself.
        """
        prepared = self.prepare_browser_environment(account_key)
        self._require_no_pending_lease(prepared.profile.account_uuid)
        with self.operation_lease(
            prepared,
            operation="manual-session",
            daily_limit=20,
            cooldown_seconds=0,
            # UI manual windows can remain open for 30 minutes.
            lock_seconds=3600,
            allow_manual_verification=True,
        ) as owner:
            if self.bindings.get_optional(account_key) is not None:
                yield prepared
                return
            self._check_first_binding(prepared,owner)
            token = _first_binding_scope.set((self,replace(prepared),owner))
            try:
                yield prepared
            finally:
                _first_binding_scope.reset(token)

    def _check_first_binding(self, prepared, owner):
        """Only a never-bound account inside its original manual lease may bootstrap."""
        from datetime import datetime, timezone
        import os, sqlite3
        profile=self.profiles.get(prepared.profile.account_key)
        state=self.bindings.get_runtime_state(prepared.account_uuid)
        if (profile.account_uuid != prepared.account_uuid or profile.status != 'active'
                or profile.profile_version != prepared.profile.profile_version
                or self.bindings.get_optional(profile.account_key) is not None
                or not owner.startswith('manual-session:') or state.lock_owner != owner
                or not state.lock_expires_at
                or datetime.fromisoformat(state.lock_expires_at) <= datetime.now(timezone.utc)):
            raise AccountRuntimeError('bootstrap_lease_invalid','首次绑定需有效的原账号人工登录租约，已绑定账号请使用管控入口。')
        from .manual_window_jobs import has_pending_manual_window_job
        account_data = Path(self.profiles.db_path).resolve().parent
        if has_pending_manual_window_job(profile.account_uuid,profile.account_key,path=account_data/'account_manual_windows.db',_legacy_only=True):
            raise AccountRuntimeError('manual_window_pending','原人工窗口仍未结清，未打开新窗口。')
        target=Path(os.environ.get('ACCOUNT_BROWSER_CONTROL_DB',account_data/'account_browser_control.db')).resolve()
        if target.exists():
            with sqlite3.connect(target.as_uri()+'?mode=ro',uri=True,timeout=3) as db:
                if (db.execute("SELECT 1 FROM browser_control_owners WHERE account_id=? AND state!='released'",(profile.account_uuid,)).fetchone()
                        or db.execute("SELECT 1 FROM browser_control_commands WHERE account_id=? AND state IN ('queued','running','paused','waiting_human','outcome_unknown')",(profile.account_uuid,)).fetchone()):
                    raise AccountRuntimeError('bootstrap_control_pending','原管控任务或浏览器尚未结清，未打开新窗口。')

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
                f"账号绑定状态为 {binding.status}，请先探测原会话并核验身份；按实际结果处理登录或安全验证。",
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
            if _identities_match(context.binding, actual):
                # Persist refreshed cookies only after this session proves the
                # original bound identity. Never checkpoint a mismatched login.
                save_state = getattr(active_session, "save_storage_state", None)
                if save_state is not None:
                    save_state()
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
                navigation_evidence=exc.navigation_evidence,
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

    def probe_recovery(
        self, account_key: str, *, headless: bool = True
    ) -> RuntimeIdentityCheck:
        """Check the bound session without bypassing its lease or rebinding it.

        Only this explicit recovery path accepts a stale unhealthy binding.
        A failed identity check counts as a failed lease, while lock, cooldown,
        circuit and quota errors retain their original structured codes.
        """
        from .browser_control_runtime import enabled, is_managed_account, managed_recovery
        if enabled() and not is_managed_account(account_key):
            return managed_recovery(account_key)
        context = self.resolve(account_key, require_healthy=False)
        try:
            self._require_no_pending_lease(context.account_uuid)
            with self.operation_lease(
                context,
                operation="identity-recovery",
                daily_limit=20,
                cooldown_seconds=0,
            ):
                session = context.create_browser_session(headless=headless)
                try:
                    check = self.verify_identity(context, session=session)
                    if not check.healthy:
                        raise _RecoveryIdentityFailed(check)
                    return check
                finally:
                    session.stop()
        except _RecoveryIdentityFailed as exc:
            return exc.check
        except (AccountRuntimeError, AccountRuntimeUnavailable):
            raise
        except Exception as exc:
            # A failed browser/network request supplies no evidence of expiry.
            raise AccountRuntimeError(
                "recovery_probe_failed", f"原会话恢复探测失败：{type(exc).__name__}: {exc}"
            ) from exc

    def _require_no_pending_lease(self, account_uuid: str) -> None:
        state = self.bindings.get_runtime_state(account_uuid)
        if state.lock_owner:
            # Even an expired lease may represent an unknown in-flight browser
            # operation. Recovery/manual login cannot steal that old claim.
            raise AccountRuntimeUnavailable(
                "locked", "原账号任务仍持有运行锁，请核对原任务后再恢复。",
                retry_at=state.lock_expires_at,
            )

    def get_operation_usage(self, context: AccountRuntimeContext, quota_scope: str) -> dict | None:
        return self.bindings.get_operation_usage(context.account_uuid, quota_scope)

    @contextmanager
    def operation_lease(
        self,
        context: AccountRuntimeContext | PreparedBrowserEnvironment,
        *,
        operation: str,
        daily_limit: int,
        cooldown_seconds: int,
        lock_seconds: int = 1800,
        allow_manual_verification: bool = False,
        quota_scope: str = "",
        quota_baseline: int = 0,
        quota_history_sources: tuple[str, ...] = (),
    ) -> Iterator[str]:
        if allow_manual_verification and operation != "manual-session":
            raise ValueError("人工验证例外不能用于后台业务或自动恢复探测。")
        if quota_scope and (quota_scope != "playback" or operation != "maintenance:playback"):
            raise ValueError("独立播放配额不能用于其他运行目的。")
        owner = f"{operation}:{uuid.uuid4().hex}"
        manual_options = {"allow_manual_verification": True} if allow_manual_verification else {}
        quota_options = ({"quota_scope": quota_scope, "quota_baseline": quota_baseline,
                          "quota_history_sources": quota_history_sources} if quota_scope else {})
        from .browser_control_runtime import operation_daily_limit
        daily_limit = operation_daily_limit(operation, daily_limit, context.account_uuid)
        self.bindings.acquire_runtime(
            context.account_uuid,
            owner=owner,
            daily_limit=daily_limit,
            cooldown_seconds=cooldown_seconds,
            lock_seconds=lock_seconds,
            **manual_options,
            **quota_options,
        )
        success = False
        try:
            from .browser_control_runtime import operation_scope
            with operation_scope(context.account_uuid, owner):
                yield owner
            success = True
        finally:
            self.bindings.release_runtime(
                context.account_uuid,
                owner=owner,
                success=success,
                **manual_options,
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
