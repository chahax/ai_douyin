"""Alembic migration helpers.

`ensure_migrated()` checks whether the database has been initialized via
Alembic. If not, it logs a clear error and (optionally) exits.

Usage in app startup:

    from src.shared.migration import ensure_migrated
    if not ensure_migrated():
        sys.exit(1)
"""

import os
import re
from pathlib import Path

from sqlalchemy import inspect, text

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
        current = {
            row[0] for row in conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).all()
        }
    if not current:
        return False
    try:
        versions_dir = Path(__file__).resolve().parent.parent.parent / "alembic" / "versions"
        heads = _migration_heads(versions_dir)
        if not heads:
            return True  # no migrations — nothing pending
        return current == heads
    except Exception:
        # Conservative: if we can't tell, assume pending
        return False


def _migration_heads(versions_dir: Path) -> set[str]:
    """Resolve graph heads from revision/down_revision declarations."""
    revision_pattern = re.compile(
        r'^\s*revision(?:\s*:\s*[^=]+)?\s*=\s*["\']([^"\']+)["\']',
        re.MULTILINE,
    )
    down_pattern = re.compile(
        r'^\s*down_revision(?:\s*:\s*[^=]+)?\s*=\s*["\']([^"\']+)["\']',
        re.MULTILINE,
    )
    revisions: set[str] = set()
    parents: set[str] = set()
    for path in Path(versions_dir).glob("*.py"):
        if path.name.startswith("_"):
            continue
        source = path.read_text(encoding="utf-8")
        revision = revision_pattern.search(source)
        if revision:
            revisions.add(revision.group(1))
        parent = down_pattern.search(source)
        if parent:
            parents.add(parent.group(1))
    return revisions - parents


def ensure_migrated(*, strict: bool = True) -> bool:
    """
    Returns True if the DB is at the head migration. False otherwise.

    In `strict=True` (default), logs a clear error and returns False.
    In `strict=False`, only logs a warning.

    Development fallback requires both ``strict=False`` and the explicit
    ``ALLOW_DEV_MIGRATION_FALLBACK=1`` flag. Production/strict startup never
    bypasses Alembic validation.
    """
    fallback = os.environ.get("ALLOW_DEV_MIGRATION_FALLBACK") == "1"
    if fallback:
        if strict:
            logger.error(
                "ALLOW_DEV_MIGRATION_FALLBACK is forbidden in strict startup."
            )
            return False
        logger.warning(
            "ALLOW_DEV_MIGRATION_FALLBACK=1 — development-only migration bypass."
        )
        return True

    if not _alembic_version_table_exists():
        msg = (
            "Database is not Alembic-managed. Run:\n"
            "  alembic upgrade head        # 全新环境\n"
            "  alembic stamp head          # 已有 DB，先标记基线再升级\n"
            "Development-only bypass requires ALLOW_DEV_MIGRATION_FALLBACK=1 "
            "and ensure_migrated(strict=False)."
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
