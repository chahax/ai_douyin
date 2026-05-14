"""
reply_context_service.py — 回复上下文服务

管理每个用户-视频组合的对话上下文
"""

from datetime import datetime
from typing import List

from src.services.database import get_db


MAX_CONTEXT_SIZE = 20  # 每组对话保留最近 20 条


def _now() -> str:
    return datetime.now().isoformat()


def get_context(user_nickname: str, video_id: str, limit: int = 10) -> List[dict]:
    """
    获取用户在某视频下的最近 N 条对话上下文。
    返回格式: [{"role": "user", "content": "...", "created_at": "..."}, ...]
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT role, content, created_at
            FROM reply_context
            WHERE user_nickname = ? AND video_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (user_nickname, video_id, limit))
        rows = cursor.fetchall()

    # 保持时间顺序（最老在前）
    result = [dict(row) for row in reversed(rows)]
    return result


def add_user_comment(user_nickname: str, video_id: str, content: str) -> None:
    """追加用户评论到上下文"""
    _add_record(user_nickname, video_id, "user", content)


def add_bot_reply(user_nickname: str, video_id: str, content: str) -> None:
    """追加机器人回复到上下文"""
    _add_record(user_nickname, video_id, "assistant", content)


def _add_record(user_nickname: str, video_id: str, role: str, content: str) -> None:
    """写入上下文记录，并裁剪到最大保留数"""
    with get_db() as conn:
        cursor = conn.cursor()

        # 插入新记录
        cursor.execute("""
            INSERT INTO reply_context (user_nickname, video_id, role, content, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (user_nickname, video_id, role, content, _now()))

        # 裁剪：只保留每组最近 MAX_CONTEXT_SIZE 条
        cursor.execute("""
            DELETE FROM reply_context
            WHERE user_nickname = ? AND video_id = ?
            AND id NOT IN (
                SELECT id FROM reply_context
                WHERE user_nickname = ? AND video_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            )
        """, (user_nickname, video_id, user_nickname, video_id, MAX_CONTEXT_SIZE))
        conn.commit()


def clear_context(user_nickname: str, video_id: str) -> None:
    """清除某组对话上下文"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM reply_context
            WHERE user_nickname = ? AND video_id = ?
        """, (user_nickname, video_id))
        conn.commit()


def build_context_prompt(context: List[dict]) -> str:
    """
    将上下文列表格式化为 Prompt 字符串。
    用于 LLM 生成回复时带入历史对话。
    """
    if not context:
        return ""

    lines = []
    for item in context:
        role = "用户" if item.get("role") == "user" else "助手"
        lines.append(f"{role}：{item.get('content', '')}")
    return "\n".join(lines)


def get_or_create_user(nickname: str) -> dict:
    """
    获取用户配置（兼容 user_profile_service 中的 get_user_config）。
    这里仅返回基本结构供上下文服务使用。
    """
    return {"user_nickname": nickname}
