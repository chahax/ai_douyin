"""Alembic migration helpers.

`ensure_migrated()` checks whether the database has been initialized via
Alembic. If not, it logs a clear error and (optionally) exits.

Usage in app startup:

    from src.shared.migration import ensure_migrated
    if not ensure_migrated():
        sys.exit(1)
"""

import os
import sys

from sqlalchemy import inspect, text

from src.shared.config import settings
from src.shared.database import engine
from src.shared.logger import logger


def _alembic_version_table_exists() -> bool:
    insp = inspect(engine)
    return "alembic_version" in insp.get_table_names()


def _is_migration_up_to_date() -> bool:
    """Check the alembic_version row matches the latest revision file.

    Returns True if the database is at the same revision as the head
    migration (i.e. nothing pending).
    """
    with engine.connect() as conn:
        row = conn.execute(text("SELECT version_num FROM alembic_version")).first()
    if row is None:
        return False
    current = row[0]
    # Read the head revision from migration files' `revision` variable.
    # This matches what's actually stored in alembic_version.
    try:
        import re
        from pathlib import Path
        versions_dir = Path(__file__).resolve().parent.parent.parent / "alembic" / "versions"
        revs = []
        rev_re = re.compile(r'^\s*revision:\s*str\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)
        for p in versions_dir.glob("*.py"):
            if p.name.startswith("_"):
                continue
            m = rev_re.search(p.read_text(encoding="utf-8"))
            if m:
                revs.append(m.group(1))
        if not revs:
            return True  # no migrations — nothing pending
        head = max(revs)
        return current == head
    except Exception:
        # Conservative: if we can't tell, assume pending
        return False


def ensure_migrated(*, strict: bool = True) -> bool:
    """
    Returns True if the DB is at the head migration. False otherwise.

    In `strict=True` (default), logs a clear error and returns False.
    In `strict=False`, only logs a warning.

    Set the env var `INIT_DB_FALLBACK=1` to bypass the check and let
    `Base.metadata.create_all` create tables (dev convenience only).
    """
    if os.environ.get("INIT_DB_FALLBACK") == "1":
        logger.warning("INIT_DB_FALLBACK=1 — skipping migration check.")
        return True

    if not _alembic_version_table_exists():
        msg = (
            "Database is not Alembic-managed. Run:\n"
            "  alembic upgrade head        # 全新环境\n"
            "  alembic stamp head          # 已有 DB，先标记基线再升级\n"
            "Or set INIT_DB_FALLBACK=1 to skip (dev only)."
        )
        if strict:
            logger.error(msg)
        else:
            logger.warning(msg)
        return False

    if not _is_migration_up_to_date():
        msg = (
            "Database is behind the latest migration. Run `alembic upgrade head`."
        )
        if strict:
            logger.error(msg)
        else:
            logger.warning(msg)
        return False

    logger.info("Database is up to date (Alembic head).")
    return True
