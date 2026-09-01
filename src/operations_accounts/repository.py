"""SQLite persistence for account identities and immutable strategy versions."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .models import AccountProfile


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
"""


class AccountProfileConflict(RuntimeError):
    pass


class AccountProfileNotFound(KeyError):
    pass


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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
