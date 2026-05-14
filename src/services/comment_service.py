"""
comment_service.py — 评论数据服务

提供评论的 upsert / 查询 / 标记已回复操作
"""

from datetime import datetime
from typing import Optional

from src.platform_adapter.models import CommentRecord
from src.services.database import get_db


def _now_iso() -> str:
    return datetime.now().isoformat()


def save_comment(comment: CommentRecord, video_id: str) -> bool:
    """
    Upsert 评论：已存在则跳过，不存在则插入。

    Returns:
        True 表示插入成功，False 表示已存在或失败
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO comments (
                comment_id, video_id, user_nickname, user_avatar,
                content, like_count, is_top, reply_count,
                created_at, is_replied, replied_at, reply_content
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(comment_id) DO NOTHING
        """, (
            comment.comment_id,
            video_id,
            comment.author_name,
            "",  # user_avatar 暂未采集
            comment.content,
            0,   # like_count 暂未采集
            0,   # is_top 暂未采集
            0,   # reply_count 暂未采集
            comment.created_at,
            0,   # is_replied
            None,  # replied_at
            None,  # reply_content
        ))
        conn.commit()
        return cursor.rowcount > 0


def get_comments(
    video_id: Optional[str] = None,
    is_replied: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """
    分页查询评论列表，支持视频ID和回复状态筛选。

    Args:
        video_id: 筛选视频ID（None 表示全部）
        is_replied: 筛选回复状态（0=未回复, 1=已回复, None=全部）
        limit: 每页数量
        offset: 跳过数量

    Returns:
        评论字典列表
    """
    with get_db() as conn:
        cursor = conn.cursor()
        conditions = []
        params = []
        if video_id is not None:
            conditions.append("video_id = ?")
            params.append(video_id)
        if is_replied is not None:
            conditions.append("is_replied = ?")
            params.append(is_replied)

        where = " AND ".join(conditions) if conditions else "1=1"
        cursor.execute(f"""
            SELECT * FROM comments
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """, (*params, limit, offset))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def mark_comment_replied(comment_id: str, reply_content: str) -> bool:
    """
    标记评论已回复，记录回复内容和时间。
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE comments
            SET is_replied = 1, replied_at = ?, reply_content = ?
            WHERE comment_id = ?
        """, (_now_iso(), reply_content, comment_id))
        conn.commit()
        return cursor.rowcount > 0


def count_comments(
    video_id: Optional[str] = None,
    is_replied: Optional[int] = None,
) -> int:
    """统计评论数量"""
    with get_db() as conn:
        cursor = conn.cursor()
        conditions = []
        params = []
        if video_id is not None:
            conditions.append("video_id = ?")
            params.append(video_id)
        if is_replied is not None:
            conditions.append("is_replied = ?")
            params.append(is_replied)

        where = " AND ".join(conditions) if conditions else "1=1"
        cursor.execute(f"SELECT COUNT(*) FROM comments WHERE {where}", params)
        return cursor.fetchone()[0]


def count_replied_comments() -> int:
    """统计已回复的评论数"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM comments WHERE is_replied = 1")
        return cursor.fetchone()[0]


def get_reply_rate() -> float:
    """
    计算评论回复率。

    Returns:
        0.0 ~ 1.0 的回复率
    """
    total = count_comments()
    if total == 0:
        return 0.0
    replied = count_comments(is_replied=1)
    return replied / total
