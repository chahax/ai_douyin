"""
sync_history_service.py — 同步历史记录服务
"""

from typing import Optional

from src.services.database import get_db


def record_sync(
    sync_type: str,
    total: int,
    new_count: int,
    started_at: str,
    finished_at: str,
    status: str,
) -> int:
    """
    记录同步历史。

    Args:
        sync_type: 同步类型（videos / comments / stats）
        total: 本次处理总数
        new_count: 本次新增数
        started_at: 开始时间（ISO 格式字符串）
        finished_at: 结束时间（ISO 格式字符串）
        status: 状态（success / failed / partial）

    Returns:
        本条记录的 id
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO sync_history
                (sync_type, total_count, new_count, started_at, finished_at, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (sync_type, total, new_count, started_at, finished_at, status))
        conn.commit()
        return cursor.lastrowid


def get_sync_history(
    sync_type: Optional[str] = None,
    limit: int = 20,
) -> list[dict]:
    """
    查询同步历史。

    Args:
        sync_type: 筛选同步类型（None 表示全部）
        limit: 返回条数

    Returns:
        同步历史字典列表
    """
    with get_db() as conn:
        cursor = conn.cursor()
        if sync_type:
            cursor.execute("""
                SELECT * FROM sync_history
                WHERE sync_type = ?
                ORDER BY id DESC
                LIMIT ?
            """, (sync_type, limit))
        else:
            cursor.execute("""
                SELECT * FROM sync_history
                ORDER BY id DESC
                LIMIT ?
            """, (limit,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def get_last_sync(sync_type: str) -> Optional[dict]:
    """获取某类型最后一次同步记录"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM sync_history
            WHERE sync_type = ?
            ORDER BY id DESC
            LIMIT 1
        """, (sync_type,))
        row = cursor.fetchone()
        return dict(row) if row else None
