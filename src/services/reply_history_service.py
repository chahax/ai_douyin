"""
reply_history_service.py — 回复历史 CRUD
"""

from datetime import datetime, timedelta
from typing import List

from src.services.database import get_db


def save_reply_history(
    user_nickname: str,
    video_id: str,
    comment_id: str,
    reply_content: str,
    auto_generated: bool = True,
    model_used: str = "",
) -> int:
    """保存一条回复历史，返回新记录 ID"""
    now = datetime.now().isoformat()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO reply_history
                (user_nickname, video_id, comment_id, reply_content, auto_generated, model_used, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_nickname, video_id, comment_id, reply_content, int(auto_generated), model_used, now))
        conn.commit()
        return cursor.lastrowid


def get_reply_history(limit: int = 100, offset: int = 0) -> List[dict]:
    """获取回复历史列表"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, user_nickname, video_id, comment_id, reply_content,
                   auto_generated, model_used, created_at
            FROM reply_history
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """, (limit, offset))
        return [dict(row) for row in cursor.fetchall()]


def count_replied_comments() -> int:
    """统计已回复的评论数"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM comments WHERE is_replied = 1")
        return cursor.fetchone()[0]


def get_recent_reply_stats(days: int = 7) -> List[dict]:
    """
    获取最近 N 天每天的回复数量。
    返回格式: [{"日期": "2026-04-21", "回复数": 5}, ...]
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT DATE(created_at) as date, COUNT(*) as cnt
            FROM reply_history
            WHERE created_at >= ?
            GROUP BY DATE(created_at)
            ORDER BY date ASC
        """, ((datetime.now() - timedelta(days=days)).isoformat(),))
        return [{"日期": row[0], "回复数": row[1]} for row in cursor.fetchall()]


def delete_reply_history(id: int) -> bool:
    """删除指定回复历史"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM reply_history WHERE id = ?", (id,))
        conn.commit()
        return cursor.rowcount > 0
