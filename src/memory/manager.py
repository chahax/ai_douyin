"""
src/memory/manager.py — 记忆系统核心管理器

职责：
  - 用户画像读写（偏好、账号绑定）
  - 对话消息追加与历史查询
  - 会话生命周期（创建/归档/摘要）
  - RAG 友好格式导出（供 Agent 上下文注入）
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from src.memory.models import UserProfile, ConversationSession, ConversationMessage
from src.shared.database import SessionLocal


# ---------------------------------------------------------------------------
# 简单值对象
# ---------------------------------------------------------------------------

@dataclass
class UserPreferences:
    """用户创作偏好（从 UserProfile 映射）"""
    default_video_mode: str = "presenter_anime"
    default_tts_provider: str = "edge"
    default_voice: str = ""
    default_character: str = "sonic_fox"
    default_character_position: str = "right_bottom"
    default_character_size: str = "medium"
    default_bgm_volume: float = 0.2
    preferred_topics: list = field(default_factory=list)
    douyin_uid: str = ""
    douyin_nickname: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class ChatMessage:
    """单条聊天消息"""
    role: str          # user / assistant / system / tool
    content: str
    skill_name: str = ""
    tool_success: bool = True
    tool_error: str = ""
    created_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# MemoryManager
# ---------------------------------------------------------------------------

class MemoryManager:
    """
    记忆系统核心类，提供：

    1. 用户画像（profile）
       - get_preferences() / update_preferences()

    2. 对话消息
       - append_message()      追加一条消息
       - get_recent_messages() 最近 N 条（不含 system/tool）
       - get_all_messages()    完整消息链（用于构建 Agent 上下文）
       - get_messages_for_rag() 以 \n\n 拼接成字符串，方便注入 prompt

    3. 会话
       - create_session()      新建会话，返回 session_id
       - archive_session()     归档会话
       - get_active_session()  获取当前活跃会话
       - update_session_summary()  由 Agent 调用，写入摘要

    所有数据库操作通过 SessionLocal（SQLite）完成。
    """

    def __init__(self, session: Optional[Session] = None):
        self._own_session = session is None
        self.session = session or SessionLocal()

    def close(self):
        if self._own_session:
            self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # -------------------------------------------------------------------------
    # 用户画像
    # -------------------------------------------------------------------------

    def get_user_profile(self, user_id: str = "default") -> UserProfile:
        """获取用户画像，不存在则创建空画像。"""
        profile = self.session.query(UserProfile).filter_by(user_id=user_id).first()
        if not profile:
            profile = UserProfile(user_id=user_id)
            self.session.add(profile)
            self.session.commit()
            self.session.refresh(profile)
        return profile

    def get_preferences(self, user_id: str = "default") -> UserPreferences:
        """以 dataclass 形式返回用户偏好。"""
        p = self.get_user_profile(user_id)
        return UserPreferences(
            default_video_mode=p.default_video_mode or "presenter_anime",
            default_tts_provider=p.default_tts_provider or "edge",
            default_voice=p.default_voice or "",
            default_character=p.default_character or "sonic_fox",
            default_character_position=p.default_character_position or "right_bottom",
            default_character_size=p.default_character_size or "medium",
            default_bgm_volume=float(p.default_bgm_volume or "0.2"),
            preferred_topics=p.preferred_topics or [],
            douyin_uid=p.douyin_uid or "",
            douyin_nickname=p.douyin_nickname or "",
            extra=p.extra or {},
        )

    def update_preferences(
        self,
        preferences: UserPreferences,
        user_id: str = "default",
    ) -> UserPreferences:
        """全量更新用户偏好（只更新传入的字段）。"""
        p = self.get_user_profile(user_id)
        p.default_video_mode = preferences.default_video_mode
        p.default_tts_provider = preferences.default_tts_provider
        p.default_voice = preferences.default_voice
        p.default_character = preferences.default_character
        p.default_character_position = preferences.default_character_position
        p.default_character_size = preferences.default_character_size
        p.default_bgm_volume = str(preferences.default_bgm_volume)
        p.preferred_topics = preferences.preferred_topics
        p.douyin_uid = preferences.douyin_uid
        p.douyin_nickname = preferences.douyin_nickname
        p.extra = preferences.extra
        p.updated_at = datetime.utcnow()
        self.session.commit()
        self.session.refresh(p)
        return self.get_preferences(user_id)

    def update_preference(self, key: str, value, user_id: str = "default") -> None:
        """
        部分更新单个偏好字段。

        key 必须是 UserPreferences 中存在的属性名。
        示例：update_preference("default_tts_provider", "gpt_sovits")
        """
        p = self.get_user_profile(user_id)
        if not hasattr(p, key):
            raise ValueError(f"Unknown preference key: {key}")
        setattr(p, key, value)
        p.updated_at = datetime.utcnow()
        self.session.commit()

    # -------------------------------------------------------------------------
    # 对话消息
    # -------------------------------------------------------------------------

    def append_message(
        self,
        session_id: int,
        role: str,
        content: str,
        skill_name: str = "",
        tool_success: bool = True,
        tool_error: str = "",
    ) -> ConversationMessage:
        """追加一条消息到指定会话。"""
        msg = ConversationMessage(
            session_id=session_id,
            role=role,
            content=content,
            skill_name=skill_name,
            tool_success=tool_success,
            tool_error=tool_error,
        )
        self.session.add(msg)
        self.session.commit()
        self.session.refresh(msg)
        return msg

    def get_recent_messages(
        self,
        session_id: int,
        limit: int = 20,
        include_system: bool = False,
    ) -> list[ChatMessage]:
        """
        返回最近 limit 条消息。

        - include_system=False 时，默认只返回 user / assistant（用于展示给用户）
        - include_system=True 时，返回所有角色
        """
        q = self.session.query(ConversationMessage).filter_by(session_id=session_id)
        if not include_system:
            q = q.filter(ConversationMessage.role.in_(["user", "assistant"]))
        q = q.order_by(ConversationMessage.created_at.desc()).limit(limit)
        rows = q.all()
        rows.reverse()  # 从旧到新
        return [self._row_to_dto(r) for r in rows]

    def get_all_messages(self, session_id: int) -> list[ChatMessage]:
        """返回会话的全部消息（按时间顺序）。"""
        rows = (
            self.session.query(ConversationMessage)
            .filter_by(session_id=session_id)
            .order_by(ConversationMessage.created_at)
            .all()
        )
        return [self._row_to_dto(r) for r in rows]

    def get_messages_for_context(
        self,
        session_id: int,
        max_messages: int = 50,
    ) -> str:
        """
        将最近消息格式化为字符串，供注入到 Agent prompt 上下文。

        格式：
        [user] 你好
        [assistant] 你好，有什么可以帮你？
        [tool:rag] ...
        [assistant] 根据 RAG 结果...
        """
        msgs = self.get_recent_messages(session_id, limit=max_messages, include_system=True)
        lines = []
        for m in msgs:
            prefix = m.role
            if m.role == "tool":
                prefix = f"tool({m.skill_name})"
            lines.append(f"[{prefix}] {m.content}")
        return "\n".join(lines)

    def get_user_messages_only(self, session_id: int, limit: int = 10) -> list[str]:
        """只返回用户消息文本（供 Agent 做摘要/回顾用）。"""
        rows = (
            self.session.query(ConversationMessage)
            .filter_by(session_id=session_id, role="user")
            .order_by(ConversationMessage.created_at.desc())
            .limit(limit)
            .all()
        )
        rows.reverse()
        return [r.content for r in rows]

    # -------------------------------------------------------------------------
    # 会话管理
    # -------------------------------------------------------------------------

    def create_session(self, user_id: str = "default", title: str = "新会话") -> ConversationSession:
        """创建新会话（自动将之前的 active 会话归档）。"""
        # 先归档现有的 active 会话
        self.session.query(ConversationSession).filter_by(
            user_id=user_id, status="active"
        ).update({"status": "archived", "archived_at": datetime.utcnow()})

        sess = ConversationSession(user_id=user_id, title=title, status="active")
        self.session.add(sess)
        self.session.commit()
        self.session.refresh(sess)
        return sess

    def get_active_session(self, user_id: str = "default") -> Optional[ConversationSession]:
        """返回当前活跃会话，没有则返回 None。"""
        return self.session.query(ConversationSession).filter_by(
            user_id=user_id, status="active"
        ).first()

    def get_or_create_active_session(self, user_id: str = "default") -> ConversationSession:
        """返回活跃会话，没有则创建新的。"""
        sess = self.get_active_session(user_id)
        if not sess:
            sess = self.create_session(user_id)
        return sess

    def archive_session(self, session_id: int) -> None:
        """将会话标记为归档。"""
        self.session.query(ConversationSession).filter_by(id=session_id).update(
            {"status": "archived", "archived_at": datetime.utcnow()}
        )
        self.session.commit()

    def update_session_summary(
        self,
        session_id: int,
        title: str = "",
        summary: str = "",
    ) -> None:
        """由 Agent 调用：更新会话标题和摘要。"""
        updates = {}
        if title:
            updates["title"] = title
        if summary:
            updates["summary"] = summary
        if updates:
            updates["updated_at"] = datetime.utcnow()
            self.session.query(ConversationSession).filter_by(id=session_id).update(updates)
            self.session.commit()

    def save_pending_plan(self, session_id: int, plan: dict) -> None:
        """暂存 Agent 生成的待确认计划。"""
        self.session.query(ConversationSession).filter_by(id=session_id).update(
            {"pending_plan": plan, "updated_at": datetime.utcnow()}
        )
        self.session.commit()

    def get_pending_plan(self, session_id: int) -> Optional[dict]:
        """获取暂存的待确认计划。"""
        sess = self.session.query(ConversationSession).filter_by(id=session_id).first()
        return sess.pending_plan if sess else None

    def clear_pending_plan(self, session_id: int) -> None:
        """用户确认/取消计划后清除。"""
        self.session.query(ConversationSession).filter_by(id=session_id).update(
            {"pending_plan": None, "updated_at": datetime.utcnow()}
        )
        self.session.commit()

    def get_session_history(
        self,
        user_id: str = "default",
        limit: int = 10,
        status: str = "archived",
    ) -> list[ConversationSession]:
        """获取历史会话列表（用于展示给用户选择加载）。"""
        q = self.session.query(ConversationSession).filter_by(user_id=user_id)
        if status:
            q = q.filter_by(status=status)
        return q.order_by(ConversationSession.updated_at.desc()).limit(limit).all()

    # -------------------------------------------------------------------------
    # 内部工具
    # -------------------------------------------------------------------------

    def _row_to_dto(self, row: ConversationMessage) -> ChatMessage:
        return ChatMessage(
            role=row.role,
            content=row.content,
            skill_name=row.skill_name or "",
            tool_success=row.tool_success,
            tool_error=row.tool_error or "",
            created_at=row.created_at,
        )
