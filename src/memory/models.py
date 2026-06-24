"""
src/memory/models.py — Agent 记忆系统的 SQLAlchemy 模型

表结构：
  user_profiles          用户画像（偏好、账号绑定、默认设置）
  conversation_sessions  会话（每轮对话一个 session_id，含摘要和状态）
  conversation_messages  消息（role / content / timestamp）
"""

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, JSON
from sqlalchemy.orm import relationship
from datetime import datetime

from src.shared.database import Base


class UserProfile(Base):
    """
    用户画像表。

    存放：
    - 用户偏好（默认视频风格、TTS 音色、是否自动发布）
    - 绑定的抖音账号信息
    - 其他持久化上下文，供 Agent 跨会话使用。
    """
    __tablename__ = "user_profiles"

    id = Column(Integer, primary_key=True, index=True)
    # 单用户场景下 user_id 固定为 "default"，未来可扩展多用户
    user_id = Column(String(64), unique=True, index=True, default="default")

    # --- 创作偏好 ---
    default_video_mode = Column(String(64), default="presenter_anime")
    default_tts_provider = Column(String(32), default="edge")
    default_voice = Column(String(255), default="")
    default_character = Column(String(128), default="sonic_fox")
    default_character_position = Column(String(32), default="right_bottom")
    default_character_size = Column(String(16), default="medium")
    default_bgm_volume = Column(String(8), default="0.2")
    preferred_topics = Column(JSON, default=list)   # ["励志", "职场", "情感"]

    # --- 平台账号 ---
    douyin_uid = Column(String(128), default="")
    douyin_nickname = Column(String(255), default="")

    # --- 扩展字段 ---
    extra = Column(JSON, default=dict)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ConversationSession(Base):
    """
    会话表。每个独立对话轮次（打开聊天 → 结束）生成一条记录。

    用途：
    - 按 session_id 组织和检索消息
    - 存储会话摘要（Agent 在长对话中自动生成），用于快速上下文加载
    - 追踪会话状态（active / archived）
    """
    __tablename__ = "conversation_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(64), index=True, default="default")

    # 会话标题/摘要，由 Agent 在会话结束时或定期生成
    title = Column(String(255), default="新会话")
    summary = Column(Text, default="")

    # 状态：active = 进行中，archived = 已归档
    status = Column(String(32), default="active")

    # Agent 生成的计划，用户尚未确认时缓存于此
    pending_plan = Column(JSON, default=None)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    archived_at = Column(DateTime, nullable=True)

    messages = relationship(
        "ConversationMessage",
        back_populates="session",
        order_by="ConversationMessage.created_at",
        cascade="all, delete-orphan",
    )


class ConversationMessage(Base):
    """
    消息表。每条用户输入 / AI 输出 / 系统消息存一条。

    role:
      - user      用户消息
      - assistant AI 回复
      - system    系统指令 / Skill 调用结果（不展示给用户）
      - tool      Tool 调用结果（如 RAG 查询结果）
    """
    __tablename__ = "conversation_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("conversation_sessions.id"), index=True)

    role = Column(String(32), index=True)   # user / assistant / system / tool
    content = Column(Text)

    # 当 role=tool 时，记录是哪个 skill 返回的
    skill_name = Column(String(128), default="")

    # tool 调用是否成功
    tool_success = Column(Boolean, default=True)
    tool_error = Column(String(512), default="")

    created_at = Column(DateTime, default=datetime.utcnow)

    # ── Phase 2 humane metadata（由 MessageClassifier 异步写入） ─────
    intent = Column(String(64), default="")
    sentiment = Column(String(32), default="")
    topics = Column(JSON, default=list)
    entities = Column(JSON, default=dict)
    humane_summary = Column(String(512), default="")
    needs_followup = Column(Boolean, default=False)
    classification_source = Column(String(16), default="rule")
    classified_at = Column(DateTime, nullable=True)

    session = relationship("ConversationSession", back_populates="messages")
