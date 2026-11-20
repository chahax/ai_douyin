from __future__ import annotations

import json
import sqlite3
from pathlib import Path


DATABASES = (
    Path(r"D:\IT\ai_douyin\data\fanqie_closed_loop_p0.db"),
    Path(r"D:\IT\ai_douyin\data\wisdom_ai.db"),
)


def _rows(connection: sqlite3.Connection, query: str) -> list[dict]:
    return [dict(row) for row in connection.execute(query)]


def audit_database(path: Path) -> dict:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        result = {
            "path": str(path),
            "exists": path.is_file(),
            "table_count": len(tables),
            "alembic_versions": (
                [row[0] for row in connection.execute(
                    "SELECT version_num FROM alembic_version"
                )]
                if "alembic_version" in tables
                else []
            ),
        }
        for table in (
            "fanqie_promotion_tasks",
            "fanqie_video_jobs",
            "fanqie_publish_records",
            "fanqie_bindings",
            "scheduled_tasks",
            "scheduled_task_executions",
        ):
            if table in tables:
                result[f"{table}_count"] = connection.execute(
                    f"SELECT count(*) FROM {table}"
                ).fetchone()[0]

        if "fanqie_promotion_tasks" in tables:
            result["tasks"] = _rows(
                connection,
                "SELECT id, task_uuid, promotion_alias, publish_type, status, version "
                "FROM fanqie_promotion_tasks ORDER BY id",
            )
        if "fanqie_video_jobs" in tables:
            result["video_jobs"] = _rows(
                connection,
                "SELECT id, job_uuid, task_id, status, video_mode, output_path, "
                "output_sha256 FROM fanqie_video_jobs ORDER BY id",
            )
        if "fanqie_publish_records" in tables:
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(fanqie_publish_records)"
                )
            }
            selected = [
                name
                for name in (
                    "id", "task_id", "status", "douyin_video_id",
                    "canonical_url", "review_check_count", "last_poll_at",
                )
                if name in columns
            ]
            result["publish_records"] = _rows(
                connection,
                f"SELECT {', '.join(selected)} FROM fanqie_publish_records ORDER BY id",
            )
        if "fanqie_bindings" in tables:
            result["bindings"] = _rows(
                connection,
                "SELECT id, task_id, status FROM fanqie_bindings ORDER BY id",
            )
        if "scheduled_tasks" in tables:
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(scheduled_tasks)")
            }
            selected = [
                name
                for name in (
                    "id", "name", "task_type", "enabled", "status",
                    "schedule_type", "handler",
                )
                if name in columns
            ]
            result["schedules"] = _rows(
                connection,
                f"SELECT {', '.join(selected)} FROM scheduled_tasks ORDER BY id",
            )
        return result
    finally:
        connection.close()


def main() -> int:
    result = {str(path): audit_database(path) for path in DATABASES if path.is_file()}
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
