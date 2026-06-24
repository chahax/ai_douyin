# -*- coding: utf-8 -*-
"""
src/memory/humane_recorder.py — 人性化记忆查询

基于 ConversationMessage 上的 Phase 2 metadata 列
（intent / sentiment / topics / humane_summary / needs_followup）。

提供 4 类查询：
  - get_recent_sentiment   情感轨迹
  - get_messages_by_topic  按主题回忆
  - get_recent_context     时间窗口上下文
  - get_followup_reminders "之前提过的事，后来怎么样了"
"""

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import desc, func

from src.memory.models import ConversationMessage
from src.shared.database import SessionLocal


def get_recent_sentiment(
    session_id: int, last_n: int = 10
) -> list[tuple[datetime, str]]:
    """返回最近 last_n 条带 sentiment 的 user 消息（时间 + 情感）。"""
    with SessionLocal() as sess:
        rows = (
            sess.query(ConversationMessage)
            .filter_by(session_id=session_id, role="user")
            .filter(ConversationMessage.sentiment != "")
            .order_by(desc(ConversationMessage.created_at))
            .limit(last_n)
            .all()
        )
        return [(r.created_at, r.sentiment) for r in reversed(rows)]


def get_messages_by_topic(
    user_id: str = "default",
    topic: str = "",
    limit: int = 20,
) -> list[dict]:
    """按主题回忆：topics JSON 数组里包含该 topic 的 user 消息。"""
    if not topic:
        return []
    with SessionLocal() as sess:
        # SQLite JSON LIKE：'%"topic"%'
        pattern = f'%"{topic}"%'
        rows = (
            sess.query(ConversationMessage)
            .filter_by(role="user")
            .filter(ConversationMessage.topics.like(pattern))
            .order_by(desc(ConversationMessage.created_at))
            .limit(limit)
            .all()
        )
        return [
            {
                "id": r.id,
                "content": r.content[:200],
                "humane_summary": r.humane_summary,
                "topics": r.topics,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]


def get_recent_context(
    session_id: int, hours: int = 24, limit: int = 50
) -> list[dict]:
    """时间窗口上下文：最近 N 小时内该 session 的所有消息。"""
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    with SessionLocal() as sess:
        rows = (
            sess.query(ConversationMessage)
            .filter_by(session_id=session_id)
            .filter(ConversationMessage.created_at >= cutoff)
            .order_by(ConversationMessage.created_at)
            .limit(limit)
            .all()
        )
        return [
            {
                "role": r.role,
                "content": r.content,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "intent": r.intent,
                "sentiment": r.sentiment,
            }
            for r in rows
        ]


def get_followup_reminders(
    user_id: str = "default", limit: int = 5
) -> list[dict]:
    """needs_followup=True 且还没被后续消息"消化"掉的 humane summary。"""
    with SessionLocal() as sess:
        rows = (
            sess.query(ConversationMessage)
            .filter_by(role="user")
            .filter(ConversationMessage.needs_followup == True)  # noqa: E712
            .order_by(desc(ConversationMessage.created_at))
            .limit(limit * 3)  # 多取一些，再去重
            .all()
        )
        # 取前 limit 条
        out: list[dict] = []
        for r in rows[:limit]:
            if not r.humane_summary:
                continue
            out.append(
                {
                    "id": r.id,
                    "humane_summary": r.humane_summary,
                    "intent": r.intent,
                    "sentiment": r.sentiment,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
            )
        return out


def get_session_sentiment_summary(session_id: int) -> dict:
    """会话级 sentiment 分布（用于 UI 图表）。"""
    with SessionLocal() as sess:
        rows = (
            sess.query(ConversationMessage.sentiment, func.count(ConversationMessage.id))
            .filter_by(session_id=session_id, role="user")
            .filter(ConversationMessage.sentiment != "")
            .group_by(ConversationMessage.sentiment)
            .all()
        )
        return {sentiment: count for sentiment, count in rows}
