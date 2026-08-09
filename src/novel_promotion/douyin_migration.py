"""
douyin.db videos account_key 幂等兼容迁移工具

为 douyin.db:videos 增加 account_key 列（幂等），
带备份提示和 rollback，不破坏旧库。

使用：
  python -m src.novel_promotion.douyin_migration upgrade   # 添加列
  python -m src.novel_promotion.douyin_migration downgrade # 移除列（需确认）
  python -m src.novel_promotion.douyin_migration check     # 检查当前状态
"""

import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# douyin.db location relative to project root
_DOUYIN_DB = Path("data/douyin.db")


def _find_db() -> Path:
    """Find douyin.db from project root or CWD."""
    for base in [Path.cwd(), Path(__file__).resolve().parent.parent.parent]:
        candidate = base / _DOUYIN_DB
        if candidate.exists():
            return candidate
    # Check absolute
    if _DOUYIN_DB.is_absolute() and _DOUYIN_DB.exists():
        return _DOUYIN_DB
    return Path("data/douyin.db")


def _backup_path(db_path: Path) -> Path:
    """Generate a timestamped backup path."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return db_path.parent / f"douyin_backup_{ts}.db"


def check_account_key(db_path: Path) -> dict:
    """Check whether account_key column exists in douyin.db:videos."""
    if not db_path.exists():
        return {"exists": False, "has_column": False, "error": f"DB not found: {db_path}"}

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(videos)")
    columns = {row[1] for row in cursor.fetchall()}
    if not columns:
        # Table doesn't exist or has no columns
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='videos'"
        )
        if not cursor.fetchone():
            conn.close()
            return {
                "exists": True,
                "has_column": False,
                "error": "videos table not found in douyin.db",
                "db_path": str(db_path),
            }
    has = "account_key" in columns
    total = cursor.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
    null_count = 0
    if has:
        null_count = cursor.execute(
            "SELECT COUNT(*) FROM videos WHERE account_key IS NULL OR account_key = ''"
        ).fetchone()[0]
    conn.close()
    return {
        "exists": True,
        "has_column": has,
        "total_videos": total,
        "null_account_key": null_count,
        "db_path": str(db_path),
    }


def upgrade_account_key(db_path: Path, *, dry_run: bool = False) -> dict:
    """Add account_key column to douyin.db:videos (idempotent).

    Steps:
    1. Check if column exists → skip if already present
    2. Back up the DB file (unless dry_run)
    3. ALTER TABLE ADD COLUMN

    Args:
        db_path: Path to douyin.db.
        dry_run: If True, only report what would be done.

    Returns:
        dict with status info.
    """
    status = check_account_key(db_path)
    if status.get("error"):
        return {"success": False, **status}

    if status["has_column"]:
        return {
            "success": True,
            "action": "skip",
            "message": "account_key column already exists",
            **status,
        }

    # Backup
    backup = None
    if not dry_run:
        backup = _backup_path(db_path)
        shutil.copy2(str(db_path), str(backup))

    if dry_run:
        return {
            "success": True,
            "action": "would_upgrade",
            "message": f"Would add account_key column to {db_path}. Backup would be at {_backup_path(db_path)}",
            "backup_needed": True,
            **status,
        }

    # Add column
    conn = sqlite3.connect(str(db_path))
    conn.execute("ALTER TABLE videos ADD COLUMN account_key TEXT DEFAULT ''")
    conn.commit()
    conn.close()

    return {
        "success": True,
        "action": "upgraded",
        "message": "Added account_key column to douyin.db:videos",
        "backup_path": str(backup) if backup else None,
        **check_account_key(db_path),
    }


def downgrade_account_key(db_path: Path, *, confirm: bool = False) -> dict:
    """Remove account_key column from douyin.db:videos.

    SQLite doesn't support DROP COLUMN directly in older versions,
    so we use the safe approach: only proceed on SQLite >= 3.35.0.

    Args:
        db_path: Path to douyin.db.
        confirm: Must be True to actually run.

    Returns:
        dict with status info.
    """
    status = check_account_key(db_path)
    if status.get("error"):
        return {"success": False, **status}

    if not status["has_column"]:
        return {
            "success": True,
            "action": "skip",
            "message": "account_key column does not exist; nothing to downgrade",
            **status,
        }

    if not confirm:
        return {
            "success": False,
            "action": "needs_confirm",
            "message": (
                "Downgrade requires --confirm flag. "
                "This will DROP the account_key column from douyin.db:videos. "
                "Make sure you have a backup first."
            ),
            "backup_tip": f"cp {db_path} {_backup_path(db_path)}",
            **status,
        }

    # Backup first
    backup = _backup_path(db_path)
    shutil.copy2(str(db_path), str(backup))

    # Use SQLite ALTER TABLE DROP COLUMN (requires SQLite >= 3.35.0)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("ALTER TABLE videos DROP COLUMN account_key")
        conn.commit()
        conn.close()
        return {
            "success": True,
            "action": "downgraded",
            "message": "Removed account_key column from douyin.db:videos",
            "backup_path": str(backup),
            **check_account_key(db_path),
        }
    except sqlite3.OperationalError as e:
        conn.close()
        return {
            "success": False,
            "action": "error",
            "message": (
                f"DROP COLUMN failed: {e}. "
                "Your SQLite version may be too old (< 3.35.0). "
                f"Restore from backup: cp {backup} {db_path}"
            ),
            "backup_path": str(backup),
        }


def update_account_key(
    db_path: Path,
    video_id: str,
    account_key: str,
) -> dict:
    """Update a specific video's account_key. Requires prior upgrade."""
    if not db_path.exists():
        return {"success": False, "error": f"DB not found: {db_path}"}

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Ensure column exists — must have been upgraded first
    cursor.execute("PRAGMA table_info(videos)")
    columns = {row[1] for row in cursor.fetchall()}
    if "account_key" not in columns:
        conn.close()
        return {
            "success": False,
            "error": (
                "account_key column does not exist in douyin.db:videos. "
                "Run `fanqie-douyin-migrate upgrade` first."
            ),
        }

    cursor.execute(
        "UPDATE videos SET account_key = ? WHERE video_id = ?",
        (account_key, video_id),
    )
    updated = cursor.rowcount
    conn.commit()
    conn.close()

    return {
        "success": True,
        "video_id": video_id,
        "account_key": account_key,
        "rows_updated": updated,
    }


# ── CLI ──────────────────────────────────────────────────────────────────────

def _cli():
    import argparse
    parser = argparse.ArgumentParser(
        description="douyin.db videos account_key migration tool"
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("check", help="Check account_key column status")

    up = sub.add_parser("upgrade", help="Add account_key column (idempotent)")
    up.add_argument("--dry-run", action="store_true", help="Preview only")

    down = sub.add_parser("downgrade", help="Remove account_key column")
    down.add_argument("--confirm", action="store_true", required=True,
                      help="Confirm downgrade (DESTRUCTIVE)")

    set_key = sub.add_parser("set", help="Set account_key for a specific video_id")
    set_key.add_argument("--video-id", type=str, required=True)
    set_key.add_argument("--account-key", type=str, required=True)

    parser.add_argument("--db-path", type=str, default="",
                        help="Path to douyin.db (auto-detected if omitted)")

    args = parser.parse_args()
    db_path = Path(args.db_path) if args.db_path else _find_db()

    if args.command == "check":
        result = check_account_key(db_path)
    elif args.command == "upgrade":
        result = upgrade_account_key(db_path, dry_run=args.dry_run)
    elif args.command == "downgrade":
        result = downgrade_account_key(db_path, confirm=args.confirm)
    elif args.command == "set":
        result = update_account_key(db_path, args.video_id, args.account_key)
    else:
        parser.print_help()
        sys.exit(1)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _cli()
