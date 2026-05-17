"""
blocked_words_service.py — 违禁词 CRUD
"""

from datetime import datetime
from typing import List

from src.services.database import get_db


def get_blocked_words() -> List[dict]:
    """获取所有违禁词"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, word, created_at FROM blocked_words ORDER BY created_at DESC")
        return [dict(row) for row in cursor.fetchall()]


def add_blocked_word(word: str) -> bool:
    """添加违禁词（已存在则跳过）"""
    now = datetime.now().isoformat()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO blocked_words (word, created_at) VALUES (?, ?)",
            (word.strip(), now),
        )
        conn.commit()
        return cursor.rowcount > 0


def remove_blocked_word(word_id: int) -> bool:
    """删除违禁词"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM blocked_words WHERE id = ?", (word_id,))
        conn.commit()
        return cursor.rowcount > 0


def add_blocked_words_batch(words: List[str]) -> int:
    """批量添加违禁词，返回成功添加的数量"""
    now = datetime.now().isoformat()
    added = 0
    with get_db() as conn:
        cursor = conn.cursor()
        for word in words:
            cursor.execute(
                "INSERT OR IGNORE INTO blocked_words (word, created_at) VALUES (?, ?)",
                (word.strip(), now),
            )
            if cursor.rowcount > 0:
                added += 1
        conn.commit()
    return added
