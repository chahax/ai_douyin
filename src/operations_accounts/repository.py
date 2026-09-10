"""SQLite persistence for account identities and immutable strategy versions."""

from __future__ import annotations

import json
import os
import hashlib
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from .models import (
    AccountBinding,
    AccountProfile,
    AccountRuntimeState,
    DouyinIdentity,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "douyin.db"


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS douyin_accounts (
    account_uuid TEXT PRIMARY KEY,
    account_key TEXT NOT NULL UNIQUE,
    platform TEXT NOT NULL DEFAULT 'douyin',
    display_name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS account_strategy_versions (
    account_uuid TEXT NOT NULL,
    profile_version INTEGER NOT NULL,
    domain_strategy_id TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    profile_json TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    PRIMARY KEY (account_uuid, profile_version),
    FOREIGN KEY (account_uuid) REFERENCES douyin_accounts(account_uuid)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_account_strategy_active
ON account_strategy_versions(account_uuid)
WHERE is_active = 1;

CREATE INDEX IF NOT EXISTS idx_douyin_accounts_status
ON douyin_accounts(status, account_key);

CREATE TABLE IF NOT EXISTS account_runtime_bindings (
    account_uuid TEXT PRIMARY KEY,
    account_key TEXT NOT NULL UNIQUE,
    platform TEXT NOT NULL DEFAULT 'douyin',
    browser_environment_key TEXT NOT NULL UNIQUE,
    browser_profile_dir TEXT NOT NULL,
    storage_state_path TEXT NOT NULL,
    platform_identity_key TEXT NOT NULL,
    nickname TEXT NOT NULL,
    avatar_url TEXT NOT NULL DEFAULT '',
    public_uid TEXT NOT NULL DEFAULT '',
    open_id TEXT NOT NULL DEFAULT '',
    union_id TEXT NOT NULL DEFAULT '',
    sec_uid TEXT NOT NULL DEFAULT '',
    verification_source TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    verified_at TEXT NOT NULL,
    last_health_at TEXT NOT NULL DEFAULT '',
    auth_expires_at TEXT NOT NULL DEFAULT '',
    last_error TEXT NOT NULL DEFAULT '',
    confirmed_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(platform, platform_identity_key),
    FOREIGN KEY (account_uuid) REFERENCES douyin_accounts(account_uuid)
);

CREATE TABLE IF NOT EXISTS account_runtime_state (
    account_uuid TEXT PRIMARY KEY,
    day_key TEXT NOT NULL DEFAULT '',
    daily_runs INTEGER NOT NULL DEFAULT 0,
    last_run_at TEXT NOT NULL DEFAULT '',
    lock_owner TEXT NOT NULL DEFAULT '',
    lock_expires_at TEXT NOT NULL DEFAULT '',
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    circuit_open_until TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    FOREIGN KEY (account_uuid) REFERENCES douyin_accounts(account_uuid)
);

CREATE TABLE IF NOT EXISTS account_oauth_attempts (
    state_hash TEXT PRIMARY KEY,
    account_uuid TEXT NOT NULL,
    account_key TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (account_uuid) REFERENCES douyin_accounts(account_uuid)
);

CREATE INDEX IF NOT EXISTS idx_account_oauth_attempts_account
ON account_oauth_attempts(account_uuid, expires_at);
"""


class AccountProfileConflict(RuntimeError):
    pass


class AccountProfileNotFound(KeyError):
    pass


class AccountBindingConflict(RuntimeError):
    pass


class AccountBindingNotFound(KeyError):
    pass


class AccountOAuthStateError(RuntimeError):
    pass


class AccountRuntimeUnavailable(RuntimeError):
    def __init__(self, code: str, message: str, *, retry_at: str = ""):
        super().__init__(message)
        self.code = code
        self.retry_at = retry_at


class AccountProfileRepository:
    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        domain_registry=None,
    ):
        self.db_path = Path(
            db_path or os.getenv("ACCOUNT_PROFILE_DB_PATH") or DEFAULT_DB_PATH
        ).resolve()
        self.domain_registry = domain_registry
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.executescript(SCHEMA_SQL)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def save(self, profile: AccountProfile, *, activate: bool = True) -> AccountProfile:
        registry = self.domain_registry
        if registry is None:
            # Lazy import avoids a package cycle: domain contracts consume
            # AccountProfile while this repository validates active plugins.
            from src.trend_intelligence.domain import get_default_domain_registry

            registry = get_default_domain_registry()
        registry.resolve(profile)
        payload = json.dumps(
            asdict(profile),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        now = _utc_now()
        with self.connection() as conn:
            by_key = conn.execute(
                "SELECT account_uuid FROM douyin_accounts WHERE account_key = ?",
                (profile.account_key,),
            ).fetchone()
            if by_key is not None and by_key["account_uuid"] != profile.account_uuid:
                raise AccountProfileConflict(
                    f"account_key {profile.account_key!r} already belongs to another UUID"
                )
            by_uuid = conn.execute(
                "SELECT account_key FROM douyin_accounts WHERE account_uuid = ?",
                (profile.account_uuid,),
            ).fetchone()
            if by_uuid is not None and by_uuid["account_key"] != profile.account_key:
                raise AccountProfileConflict(
                    f"account_uuid {profile.account_uuid!r} already belongs to another key"
                )

            conn.execute(
                """
                INSERT INTO douyin_accounts (
                    account_uuid, account_key, platform, display_name,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_uuid) DO UPDATE SET
                    platform = excluded.platform,
                    display_name = excluded.display_name,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (
                    profile.account_uuid,
                    profile.account_key,
                    profile.platform,
                    profile.display_name,
                    profile.status,
                    now,
                    now,
                ),
            )

            existing = conn.execute(
                """
                SELECT profile_json
                FROM account_strategy_versions
                WHERE account_uuid = ? AND profile_version = ?
                """,
                (profile.account_uuid, profile.profile_version),
            ).fetchone()
            if existing is not None and existing["profile_json"] != payload:
                raise AccountProfileConflict(
                    "account strategy versions are immutable; create a new profile_version"
                )
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO account_strategy_versions (
                        account_uuid, profile_version, domain_strategy_id,
                        strategy_version, profile_json, is_active, created_at
                    ) VALUES (?, ?, ?, ?, ?, 0, ?)
                    """,
                    (
                        profile.account_uuid,
                        profile.profile_version,
                        profile.domain_strategy_id,
                        profile.strategy_version,
                        payload,
                        now,
                    ),
                )
            if activate:
                conn.execute(
                    "UPDATE account_strategy_versions SET is_active = 0 WHERE account_uuid = ?",
                    (profile.account_uuid,),
                )
                conn.execute(
                    """
                    UPDATE account_strategy_versions
                    SET is_active = 1
                    WHERE account_uuid = ? AND profile_version = ?
                    """,
                    (profile.account_uuid, profile.profile_version),
                )
        return profile

    def get(
        self,
        account_key: str,
        *,
        profile_version: int | None = None,
    ) -> AccountProfile:
        with self.connection() as conn:
            if profile_version is None:
                row = conn.execute(
                    """
                    SELECT v.profile_json
                    FROM douyin_accounts a
                    JOIN account_strategy_versions v
                      ON v.account_uuid = a.account_uuid
                    WHERE a.account_key = ? AND v.is_active = 1
                    """,
                    (account_key,),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT v.profile_json
                    FROM douyin_accounts a
                    JOIN account_strategy_versions v
                      ON v.account_uuid = a.account_uuid
                    WHERE a.account_key = ? AND v.profile_version = ?
                    """,
                    (account_key, int(profile_version)),
                ).fetchone()
        if row is None:
            version_label = "active" if profile_version is None else str(profile_version)
            raise AccountProfileNotFound(f"account profile not found: {account_key}/{version_label}")
        return AccountProfile(**json.loads(row["profile_json"]))

    def list_active(self, *, status: str | None = "active") -> list[AccountProfile]:
        query = """
            SELECT v.profile_json
            FROM douyin_accounts a
            JOIN account_strategy_versions v
              ON v.account_uuid = a.account_uuid
            WHERE v.is_active = 1
        """
        params: list[object] = []
        if status is not None:
            query += " AND a.status = ?"
            params.append(status)
        query += " ORDER BY a.account_key"
        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [AccountProfile(**json.loads(row["profile_json"])) for row in rows]

    def next_profile_version(self, account_key: str) -> int:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT MAX(v.profile_version) AS version
                FROM douyin_accounts a
                JOIN account_strategy_versions v
                  ON v.account_uuid = a.account_uuid
                WHERE a.account_key = ?
                """,
                (account_key,),
            ).fetchone()
        return int(row["version"] or 0) + 1

    def activate(self, account_key: str, profile_version: int) -> AccountProfile:
        profile = self.get(account_key, profile_version=profile_version)
        with self.connection() as conn:
            conn.execute(
                "UPDATE account_strategy_versions SET is_active = 0 WHERE account_uuid = ?",
                (profile.account_uuid,),
            )
            cursor = conn.execute(
                """
                UPDATE account_strategy_versions
                SET is_active = 1
                WHERE account_uuid = ? AND profile_version = ?
                """,
                (profile.account_uuid, profile.profile_version),
            )
            if cursor.rowcount != 1:
                raise AccountProfileNotFound(
                    f"account profile not found: {account_key}/{profile_version}"
                )
        return profile

    def get_by_uuid(self, account_uuid: str) -> AccountProfile:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT v.profile_json
                FROM account_strategy_versions v
                WHERE v.account_uuid = ? AND v.is_active = 1
                """,
                (account_uuid,),
            ).fetchone()
        if row is None:
            raise AccountProfileNotFound(
                f"active account profile not found: {account_uuid}"
            )
        return AccountProfile(**json.loads(row["profile_json"]))


class AccountBindingRepository:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(
            db_path or os.getenv("ACCOUNT_PROFILE_DB_PATH") or DEFAULT_DB_PATH
        ).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.executescript(SCHEMA_SQL)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def bind(
        self,
        profile: AccountProfile,
        identity: DouyinIdentity,
        *,
        browser_environment_key: str,
        browser_profile_dir: str,
        storage_state_path: str,
        confirmed_by: str,
        allow_rebind: bool = False,
    ) -> AccountBinding:
        identity.validate()
        environment_key = browser_environment_key.strip()
        if not environment_key:
            raise ValueError("browser_environment_key 不能为空。")
        now = _utc_now()
        with self.connection() as conn:
            existing = conn.execute(
                "SELECT * FROM account_runtime_bindings WHERE account_uuid = ?",
                (profile.account_uuid,),
            ).fetchone()
            if existing is not None:
                same_identity = (
                    existing["platform_identity_key"]
                    == identity.platform_identity_key
                )
                same_environment = (
                    existing["browser_environment_key"] == environment_key
                )
                if not (same_identity and same_environment) and not allow_rebind:
                    raise AccountBindingConflict(
                        "该运营账号已有不同绑定；重新绑定需要管理员明确确认。"
                    )

            identity_owner = conn.execute(
                """
                SELECT account_key FROM account_runtime_bindings
                WHERE platform = 'douyin' AND platform_identity_key = ?
                  AND account_uuid != ?
                """,
                (identity.platform_identity_key, profile.account_uuid),
            ).fetchone()
            if identity_owner is not None:
                raise AccountBindingConflict(
                    f"该抖音账号已绑定运营账号 {identity_owner['account_key']}。"
                )
            environment_owner = conn.execute(
                """
                SELECT account_key FROM account_runtime_bindings
                WHERE browser_environment_key = ? AND account_uuid != ?
                """,
                (environment_key, profile.account_uuid),
            ).fetchone()
            if environment_owner is not None:
                raise AccountBindingConflict(
                    f"该浏览器环境已绑定运营账号 {environment_owner['account_key']}。"
                )

            created_at = existing["created_at"] if existing is not None else now
            conn.execute(
                """
                INSERT INTO account_runtime_bindings (
                    account_uuid, account_key, platform,
                    browser_environment_key, browser_profile_dir,
                    storage_state_path, platform_identity_key, nickname,
                    avatar_url, public_uid, open_id, union_id, sec_uid,
                    verification_source, status, verified_at,
                    last_health_at, auth_expires_at, last_error,
                    confirmed_by, created_at, updated_at
                ) VALUES (?, ?, 'douyin', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          'active', ?, ?, ?, '', ?, ?, ?)
                ON CONFLICT(account_uuid) DO UPDATE SET
                    account_key = excluded.account_key,
                    browser_environment_key = excluded.browser_environment_key,
                    browser_profile_dir = excluded.browser_profile_dir,
                    storage_state_path = excluded.storage_state_path,
                    platform_identity_key = excluded.platform_identity_key,
                    nickname = excluded.nickname,
                    avatar_url = excluded.avatar_url,
                    public_uid = excluded.public_uid,
                    open_id = excluded.open_id,
                    union_id = excluded.union_id,
                    sec_uid = excluded.sec_uid,
                    verification_source = excluded.verification_source,
                    status = 'active',
                    verified_at = excluded.verified_at,
                    last_health_at = excluded.last_health_at,
                    auth_expires_at = excluded.auth_expires_at,
                    last_error = '',
                    confirmed_by = excluded.confirmed_by,
                    updated_at = excluded.updated_at
                """,
                (
                    profile.account_uuid,
                    profile.account_key,
                    environment_key,
                    browser_profile_dir,
                    storage_state_path,
                    identity.platform_identity_key,
                    identity.nickname.strip(),
                    identity.avatar_url.strip(),
                    identity.public_uid.strip(),
                    identity.open_id.strip(),
                    identity.union_id.strip(),
                    identity.sec_uid.strip(),
                    identity.verification_source,
                    identity.verified_at or now,
                    identity.verified_at or now,
                    identity.auth_expires_at,
                    confirmed_by.strip(),
                    created_at,
                    now,
                ),
            )
        return self.get(profile.account_key)

    def get(self, account_key: str) -> AccountBinding:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM account_runtime_bindings WHERE account_key = ?",
                (account_key,),
            ).fetchone()
        if row is None:
            raise AccountBindingNotFound(f"account binding not found: {account_key}")
        return _binding_from_row(row)

    def get_optional(self, account_key: str) -> AccountBinding | None:
        try:
            return self.get(account_key)
        except AccountBindingNotFound:
            return None

    def list_all(self) -> list[AccountBinding]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM account_runtime_bindings ORDER BY account_key"
            ).fetchall()
        return [_binding_from_row(row) for row in rows]

    def create_oauth_attempt(
        self,
        account_key: str,
        *,
        requested_by: str,
        ttl_seconds: int = 600,
    ) -> str:
        """Persist a short-lived OAuth state without storing its raw value."""
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=max(60, int(ttl_seconds)))
        raw_state = secrets.token_urlsafe(32)
        state_hash = _oauth_state_hash(raw_state)
        with self.connection() as conn:
            account = conn.execute(
                "SELECT account_uuid FROM douyin_accounts WHERE account_key = ?",
                (account_key,),
            ).fetchone()
            if account is None:
                raise AccountOAuthStateError(f"运营账号不存在：{account_key}")
            conn.execute(
                "DELETE FROM account_oauth_attempts WHERE expires_at <= ?",
                (now.isoformat(),),
            )
            conn.execute(
                "DELETE FROM account_oauth_attempts WHERE account_uuid = ?",
                (account["account_uuid"],),
            )
            conn.execute(
                """
                INSERT INTO account_oauth_attempts (
                    state_hash, account_uuid, account_key, requested_by,
                    expires_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    state_hash,
                    account["account_uuid"],
                    account_key,
                    requested_by.strip(),
                    expires_at.isoformat(),
                    now.isoformat(),
                ),
            )
        return raw_state

    def consume_oauth_attempt(self, raw_state: str) -> dict[str, str]:
        """Validate and consume OAuth state, including callbacks in a new tab."""
        state_hash = _oauth_state_hash(raw_state)
        now = datetime.now(timezone.utc)
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM account_oauth_attempts WHERE state_hash = ?",
                (state_hash,),
            ).fetchone()
            if row is None:
                raise AccountOAuthStateError(
                    "OAuth state 无效或已使用，请重新发起授权。"
                )
            conn.execute(
                "DELETE FROM account_oauth_attempts WHERE state_hash = ?",
                (state_hash,),
            )
            expires_at = _parse_time(row["expires_at"])
            if expires_at is None or expires_at <= now:
                raise AccountOAuthStateError(
                    "OAuth 授权请求已过期，请重新发起授权。"
                )
        return {
            "account_uuid": str(row["account_uuid"]),
            "account_key": str(row["account_key"]),
            "requested_by": str(row["requested_by"]),
        }

    def update_health(
        self,
        account_key: str,
        *,
        status: str,
        identity: DouyinIdentity | None = None,
        error: str = "",
    ) -> AccountBinding:
        if status not in {"active", "expired", "mismatch", "blocked"}:
            raise ValueError(f"invalid binding health status: {status}")
        now = _utc_now()
        with self.connection() as conn:
            current = conn.execute(
                "SELECT * FROM account_runtime_bindings WHERE account_key = ?",
                (account_key,),
            ).fetchone()
            if current is None:
                raise AccountBindingNotFound(
                    f"account binding not found: {account_key}"
                )
            updates = {
                "status": status,
                "last_health_at": now,
                "last_error": error.strip(),
                "updated_at": now,
                "nickname": current["nickname"],
                "avatar_url": current["avatar_url"],
                "public_uid": current["public_uid"],
                "open_id": current["open_id"],
                "union_id": current["union_id"],
                "sec_uid": current["sec_uid"],
            }
            if identity is not None:
                updates.update(
                    nickname=identity.nickname or current["nickname"],
                    avatar_url=identity.avatar_url or current["avatar_url"],
                    public_uid=identity.public_uid or current["public_uid"],
                    open_id=identity.open_id or current["open_id"],
                    union_id=identity.union_id or current["union_id"],
                    sec_uid=identity.sec_uid or current["sec_uid"],
                )
            conn.execute(
                """
                UPDATE account_runtime_bindings SET
                    status = :status, last_health_at = :last_health_at,
                    last_error = :last_error, updated_at = :updated_at,
                    nickname = :nickname, avatar_url = :avatar_url,
                    public_uid = :public_uid, open_id = :open_id,
                    union_id = :union_id, sec_uid = :sec_uid
                WHERE account_key = :account_key
                """,
                {**updates, "account_key": account_key},
            )
        return self.get(account_key)

    def get_runtime_state(self, account_uuid: str) -> AccountRuntimeState:
        now = _utc_now()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO account_runtime_state (
                    account_uuid, updated_at
                ) VALUES (?, ?)
                """,
                (account_uuid, now),
            )
            row = conn.execute(
                "SELECT * FROM account_runtime_state WHERE account_uuid = ?",
                (account_uuid,),
            ).fetchone()
        return AccountRuntimeState(**dict(row))

    def acquire_runtime(
        self,
        account_uuid: str,
        *,
        owner: str,
        daily_limit: int,
        cooldown_seconds: int,
        lock_seconds: int = 1800,
    ) -> AccountRuntimeState:
        if not owner.strip():
            raise ValueError("runtime lock owner 不能为空。")
        now = datetime.now(timezone.utc)
        now_text = now.isoformat()
        day_key = now.date().isoformat()
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT OR IGNORE INTO account_runtime_state (
                    account_uuid, updated_at
                ) VALUES (?, ?)
                """,
                (account_uuid, now_text),
            )
            row = conn.execute(
                "SELECT * FROM account_runtime_state WHERE account_uuid = ?",
                (account_uuid,),
            ).fetchone()
            state = AccountRuntimeState(**dict(row))
            lock_expires = _parse_time(state.lock_expires_at)
            if (
                state.lock_owner
                and state.lock_owner != owner
                and lock_expires is not None
                and lock_expires > now
            ):
                raise AccountRuntimeUnavailable(
                    "locked",
                    f"账号正在执行其他任务：{state.lock_owner}",
                    retry_at=state.lock_expires_at,
                )
            circuit_until = _parse_time(state.circuit_open_until)
            if circuit_until is not None and circuit_until > now:
                raise AccountRuntimeUnavailable(
                    "circuit_open",
                    "账号连续异常，已进入熔断冷却。",
                    retry_at=state.circuit_open_until,
                )
            daily_runs = state.daily_runs if state.day_key == day_key else 0
            if daily_runs >= max(1, daily_limit):
                raise AccountRuntimeUnavailable(
                    "daily_quota_exceeded",
                    f"账号今日运行次数已达到上限 {daily_limit}。",
                )
            last_run = _parse_time(state.last_run_at)
            next_allowed = (
                last_run + timedelta(seconds=max(0, cooldown_seconds))
                if last_run is not None
                else None
            )
            if next_allowed is not None and next_allowed > now:
                raise AccountRuntimeUnavailable(
                    "cooldown",
                    "账号仍在冷却时间内。",
                    retry_at=next_allowed.isoformat(),
                )
            conn.execute(
                """
                UPDATE account_runtime_state SET
                    day_key = ?, daily_runs = ?, last_run_at = ?,
                    lock_owner = ?, lock_expires_at = ?, updated_at = ?
                WHERE account_uuid = ?
                """,
                (
                    day_key,
                    daily_runs + 1,
                    now_text,
                    owner,
                    (now + timedelta(seconds=max(60, lock_seconds))).isoformat(),
                    now_text,
                    account_uuid,
                ),
            )
        return self.get_runtime_state(account_uuid)

    def release_runtime(
        self,
        account_uuid: str,
        *,
        owner: str,
        success: bool,
        circuit_failure_threshold: int = 3,
        circuit_seconds: int = 21600,
    ) -> AccountRuntimeState:
        now = datetime.now(timezone.utc)
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM account_runtime_state WHERE account_uuid = ?",
                (account_uuid,),
            ).fetchone()
            if row is None:
                raise AccountRuntimeUnavailable(
                    "lock_missing", "账号运行锁不存在。"
                )
            state = AccountRuntimeState(**dict(row))
            if state.lock_owner and state.lock_owner != owner:
                raise AccountRuntimeUnavailable(
                    "lock_owner_mismatch", "不能释放其他任务持有的账号运行锁。"
                )
            failures = 0 if success else state.consecutive_failures + 1
            circuit_until = ""
            if failures >= max(1, circuit_failure_threshold):
                circuit_until = (
                    now + timedelta(seconds=max(60, circuit_seconds))
                ).isoformat()
            conn.execute(
                """
                UPDATE account_runtime_state SET
                    lock_owner = '', lock_expires_at = '',
                    consecutive_failures = ?, circuit_open_until = ?,
                    updated_at = ?
                WHERE account_uuid = ?
                """,
                (failures, circuit_until, now.isoformat(), account_uuid),
            )
        return self.get_runtime_state(account_uuid)


def _binding_from_row(row: sqlite3.Row) -> AccountBinding:
    payload = dict(row)
    payload.pop("platform", None)
    return AccountBinding(**payload)


def _parse_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _oauth_state_hash(raw_state: str) -> str:
    value = str(raw_state or "").strip()
    if not value:
        raise AccountOAuthStateError("OAuth state 不能为空。")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
