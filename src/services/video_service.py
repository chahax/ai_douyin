"""
video_service.py — 视频数据服务

提供视频的 upsert / 查询 / 统计操作
"""

from datetime import datetime
from typing import Optional

from src.platform_adapter.models import VideoItem, VideoStats, VideoStatus
from src.services.database import get_db


def _now_iso() -> str:
    return datetime.now().isoformat()


def save_video(video: VideoItem) -> bool:
    """
    Upsert 视频：优先按 local_id 更新，其次按 video_id，
    sync 时按 title 匹配 pending_review 记录补上 video_id，均未找到则插入新记录。

    Returns:
        True 表示插入（或更新）成功
    """
    with get_db() as conn:
        cursor = conn.cursor()

        now = _now_iso()
        status = video.status.value if isinstance(video.status, VideoStatus) else (video.status or "pending_review")
        stats = video.stats
        play_count = stats.play_count if stats else 0
        like_count = stats.like_count if stats else 0
        comment_count = stats.comment_count if stats else 0

        # 匹配优先级：local_id > video_id > title(pending_review)

        # 1. 按 local_id 查找（本地发布记录优先）
        if video.local_id:
            cursor.execute("SELECT id FROM videos WHERE local_id = ?", (video.local_id,))
            row = cursor.fetchone()
            if row:
                cursor.execute("""
                    UPDATE videos SET
                        video_id = COALESCE(?, video_id),
                        title = ?, description = ?, status = ?,
                        publish_time = COALESCE(?, publish_time),
                        cover_url = COALESCE(?, cover_url),
                        stats_views = ?, stats_likes = ?, stats_comments = ?,
                        last_synced_at = ?
                    WHERE local_id = ?
                """, (
                    video.video_id, video.title, video.description, status,
                    video.publish_time, video.cover_url,
                    play_count, like_count, comment_count,
                    now, video.local_id,
                ))
                conn.commit()
                return True

        # 2. 按 video_id 查找（已知抖音 ID 的情况）
        if video.video_id:
            cursor.execute("SELECT id FROM videos WHERE video_id = ?", (video.video_id,))
            row = cursor.fetchone()
            if row:
                cursor.execute("""
                    UPDATE videos SET
                        title = ?, description = ?, status = ?,
                        publish_time = COALESCE(?, publish_time),
                        cover_url = COALESCE(?, cover_url),
                        stats_views = ?, stats_likes = ?, stats_comments = ?,
                        last_synced_at = ?
                    WHERE video_id = ?
                """, (
                    video.title, video.description, status,
                    video.publish_time, video.cover_url,
                    play_count, like_count, comment_count,
                    now, video.video_id,
                ))
                conn.commit()
                return True

        # 3. 按 title 匹配 pending_review 记录（sync 时补 video_id）
        if video.title and video.video_id:
            cursor.execute("""
                SELECT id FROM videos
                WHERE title = ? AND status = 'pending_review'
                LIMIT 1
            """, (video.title,))
            row = cursor.fetchone()
            if row:
                cursor.execute("""
                    UPDATE videos SET
                        video_id = ?,
                        status = 'published',
                        last_synced_at = ?
                    WHERE title = ? AND status = 'pending_review'
                """, (video.video_id, now, video.title))
                conn.commit()
                return True

        # 4. 均未找到，插入新记录
        cursor.execute("""
            INSERT INTO videos (
                local_id, video_id, title, description, status, publish_time,
                cover_url, stats_views, stats_likes, stats_comments,
                last_synced_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            video.local_id,
            video.video_id or None,
            video.title,
            video.description,
            status,
            video.publish_time,
            video.cover_url,
            play_count,
            like_count,
            comment_count,
            now,
            now,
        ))
        conn.commit()
        return True


def get_videos(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """
    分页查询视频列表，支持状态筛选。

    Args:
        status: 筛选状态（published / failed / pending_review / None 表示全部）
        limit: 每页数量
        offset: 跳过数量

    Returns:
        视频字典列表
    """
    with get_db() as conn:
        cursor = conn.cursor()
        if status:
            cursor.execute("""
                SELECT * FROM videos
                WHERE status = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """, (status, limit, offset))
        else:
            cursor.execute("""
                SELECT * FROM videos
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """, (limit, offset))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def get_video_by_id(video_id: str) -> Optional[dict]:
    """根据 video_id 查询单个视频"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM videos WHERE video_id = ?", (video_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def update_video_stats(video_id: str, stats: VideoStats) -> bool:
    """更新视频统计数据"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE videos
            SET stats_views = ?, stats_likes = ?, stats_comments = ?,
                last_synced_at = ?
            WHERE video_id = ?
        """, (stats.play_count, stats.like_count, stats.comment_count, _now_iso(), video_id))
        conn.commit()
        return cursor.rowcount > 0


def count_videos(status: Optional[str] = None) -> int:
    """统计视频数量"""
    with get_db() as conn:
        cursor = conn.cursor()
        if status:
            cursor.execute("SELECT COUNT(*) FROM videos WHERE status = ?", (status,))
        else:
            cursor.execute("SELECT COUNT(*) FROM videos")
        return cursor.fetchone()[0]


def delete_video(video_id: str) -> bool:
    """删除视频"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM videos WHERE video_id = ?", (video_id,))
        conn.commit()
        return cursor.rowcount > 0


def mark_videos_deleted(existing_video_ids: list[str], allow_empty: bool = False) -> int:
    """
    标记在平台上已删除的视频为 failed。

    将 status=published 且 video_id 不在 existing_video_ids 列表中的记录
    更新为 status=failed。

    Args:
        existing_video_ids: 平台返回的当前视频 ID 列表
        allow_empty: 若为 True，当列表为空时视为"平台上已无视频"，将所有
                     published 记录标记为 failed（适用于同步成功但平台
                     返回空列表的情况）。为 False 时列表为空则直接返回 0。

    Returns:
        被标记为删除的视频数量
    """
    if not existing_video_ids:
        if not allow_empty:
            return 0
        # 平台上已无视频：将所有 published 记录标记为 failed
        # 同时清理孤儿 pending_review（video_id=NULL），这些是本地发布失败留下的记录
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                UPDATE videos
                SET status = 'failed', last_synced_at = ?
                WHERE status = 'published' AND video_id IS NOT NULL
            """, (_now_iso(),))
            cursor.execute(f"""
                UPDATE videos
                SET status = 'failed', last_synced_at = ?
                WHERE status IN ('pending_review', 'publishing') AND video_id IS NULL
            """, (_now_iso(),))
            conn.commit()
            return cursor.rowcount

    with get_db() as conn:
        cursor = conn.cursor()
        placeholders = ",".join("?" * len(existing_video_ids))
        cursor.execute(f"""
            UPDATE videos
            SET status = 'failed', last_synced_at = ?
            WHERE status = 'published'
              AND video_id IS NOT NULL
              AND video_id NOT IN ({placeholders})
        """, (_now_iso(), *existing_video_ids))
        conn.commit()
        return cursor.rowcount


def update_video_rag_context(video_id: str, rag_context: str) -> bool:
    """保存视频的 RAG 检索结果（用于自动回复增强）"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE videos SET rag_context = ? WHERE video_id = ?",
            (rag_context, video_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def update_video_status_by_local(local_id: str, status: str) -> bool:
    """根据 local_id 更新视频状态"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE videos SET status = ?, last_synced_at = ? WHERE local_id = ?",
            (status, _now_iso(), local_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def update_video_status_by_video_id(video_id: str, status: str) -> bool:
    """根据 video_id 更新视频状态"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE videos SET status = ?, last_synced_at = ? WHERE video_id = ?",
            (status, _now_iso(), video_id),
        )
        conn.commit()
        return cursor.rowcount > 0
