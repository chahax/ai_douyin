# -*- coding: utf-8 -*-
"""
src/memory/problem_memory.py — 问题记忆系统

三层记忆分类：
  ConversationMemory   最近对话（滑动窗口，会话级）
  UserMemory         用户偏好（跨会话持久化）
  ProblemMemory      问题与解决方案（已知问题/未解决问题）

问题状态：
  unresolved   未解决
  investigating 调查中（定时任务已访问过但未解决）
  resolved    已解决
  discarded  已丢弃（重复无效问题）
"""

from datetime import datetime
from enum import Enum
import re
from typing import Optional

from sqlalchemy import Column, Integer, String, Text, DateTime, JSON
from sqlalchemy.orm import Session

from src.shared.database import Base, SessionLocal


class ProblemStatus(str, Enum):
    UNRESOLVED = "unresolved"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"
    DISCARDED = "discarded"


class ConversationMemory(Base):
    """
    最近对话消息（滑动窗口）。
    只保留最近 N 条，溢出后丢弃。
    """
    __tablename__ = "conversation_memory"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, index=True)

    role = Column(String(32))    # user / assistant
    content = Column(Text)
    # 分类标记
    memory_type = Column(String(32), default="normal")  # normal / preference / problem / discarded
    created_at = Column(DateTime, default=datetime.utcnow)

    # Phase 2: 分类溯源（rule / llm / default）
    classification_source = Column(String(16), default="rule")
    classified_at = Column(DateTime, nullable=True)


class UserMemory(Base):
    """
    用户偏好记忆（跨会话持久化）。
    由 LLM 提取用户对话中的偏好自动入库。
    """
    __tablename__ = "user_memory"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(64), default="default", index=True)

    # 偏好类型：preferred_topics / preferred_style / preferred_workflow / custom
    memory_type = Column(String(64), index=True)
    key = Column(String(255))      # 如 "preferred_topics"
    value = Column(Text)           # 如 "['励志', '职场']"

    # 来源：哪次对话、哪条消息提取的
    source_session_id = Column(Integer, nullable=True)
    source_message_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ProblemMemory(Base):
    """
    问题与解决方案记忆。
    用户提问 + LLM 判断是否有解决方案，持续跟踪。
    """
    __tablename__ = "problem_memory"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(64), default="default", index=True)

    # 问题描述（用户原始问题）
    problem_text = Column(Text)
    # LLM 判断的分类标签
    problem_tags = Column(JSON, default=list)

    # 状态
    status = Column(String(32), default=ProblemStatus.UNRESOLVED.value, index=True)

    # 已有解决方案时的记录
    solution = Column(Text, nullable=True)        # 解决方案描述
    solution_session_id = Column(Integer, nullable=True)  # 哪个 session 解决的
    resolved_at = Column(DateTime, nullable=True)

    # 调查记录
    investigation_count = Column(Integer, default=0)   # 定时任务访问次数
    last_investigated_at = Column(DateTime, nullable=True)
    last_investigation_note = Column(Text, nullable=True)  # 上次调查 LLM 的回复摘要

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 元数据（对话上下文摘要，用于去重判断）
    context_summary = Column(Text, nullable=True)


# ─── 管理器 ───────────────────────────────────────────────

WINDOW_SIZE = 20      # 最近 20 条对话后开始丢弃
SUMMARY_THRESHOLD = 20  # 每 20 条消息生成一次会话摘要


class MemoryLayerManager:
    """
    三层记忆管理器。

    对话每来一条消息：
      1. 判断 memory_type（preference / problem / discarded / normal）
      2. preference → 提取/更新 UserMemory
      3. problem+unresolved → 存入 ProblemMemory
      4. normal / discarded → 存入 ConversationMemory 滑动窗口
      5. 窗口满 20 条时丢弃最早一条（正常消息）
      6. 满 20 条时生成摘要，存入 ConversationSession.summary
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

    # ── 对话消息入口 ──────────────────────────────────────

    def add_message(
        self,
        session_id: int,
        role: str,
        content: str,
        user_id: str = "default",
    ) -> dict:
        """
        接收一条消息，返回分类结果。
        返回 {"memory_type": "...", "action": "...", "detail": "..."}

        Phase 2 改造：用 MessageClassifier.classify_fast 同步快路径拿
        memory_type，行为兼容老规则。精细分类（intent / sentiment /
        topics / humane_summary / needs_followup）由 Agent 路径
        异步调用 _enrich_message_async 写入。
        """
        # 1. 同步快路径分类（缓存 / 规则 fallback，不阻塞）
        from src.memory.message_classifier import classifier
        result = classifier.classify_fast(role, content)
        memory_type = result["memory_type"]

        if memory_type == "discarded":
            # 不入库
            return {"memory_type": "discarded", "action": "skipped", "detail": "低价值对话已丢弃"}

        if memory_type == "preference":
            # 提取偏好入库（一次可能多条：identity + tone + format 等）
            prefs = self._extract_preference(content)
            if prefs:
                for p in prefs:
                    self._upsert_user_memory(session_id, user_id, p)
            summary = ", ".join(f"{p['memory_type']}={p['value']}" for p in (prefs or []))
            return {"memory_type": "preference", "action": "stored", "detail": f"偏好已记录: {summary}"}

        if memory_type == "problem":
            # 检查是否已有相似问题
            existing = self._find_similar_problem(user_id, content)
            if existing:
                return {"memory_type": "problem", "action": "exists", "detail": f"已知问题 #{existing.id}"}
            self._add_problem(session_id, user_id, content, memory_type, tags=[])
            return {"memory_type": "problem", "action": "new_problem", "detail": "新问题已记录"}

        # normal / 其他
        self._add_conversation_message(session_id, role, content, memory_type)
        # 检查窗口大小，必要时丢弃最老的正常消息
        dropped = self._trim_window(session_id)
        return {"memory_type": memory_type, "action": "stored", "dropped": dropped}

    # Phase 2 新增：异步 enrich（精细分类 metadata 回写）
    async def _enrich_message_async(
        self, message_id: int, role: str, content: str
    ) -> dict | None:
        """
        异步 LLM 分类并把 metadata 写回 ConversationMemory。
        同时检测"快路径是 normal 但 LLM 判定是 problem"的情况，
        自动补建一条 ProblemMemory（修原有潜在 bug）。
        """
        from datetime import datetime
        from src.memory.message_classifier import classifier

        data = await classifier.classify_async(role, content)
        try:
            row = self.session.query(ConversationMemory).filter_by(id=message_id).first()
            if row is None:
                return None
            # 写入精细 metadata（ConversationMemory 现在还没有这些列，
            # 完整 humane metadata 走 ConversationMessage；这里只先更新
            # classification_source 和 memory_type 校正）
            row.classification_source = data.get("classification_source", "llm")
            row.classified_at = datetime.utcnow()
            self.session.commit()

            # 如果 LLM 重新判定为 problem 而快路径是 normal，补建 ProblemMemory
            if data["memory_type"] == "problem":
                # 简单 dedup：LIKE 检查
                existing = self._find_similar_problem(
                    row.session.user_id if hasattr(row.session, "user_id") else "default",
                    content,
                )
                if not existing:
                    self._add_problem(
                        row.session_id,
                        "default",
                        content,
                        "problem",
                        tags=data.get("topics", []),
                    )
            return data
        except Exception:
            logger.exception("_enrich_message_async 失败")
            return None

    # 旧的 _classify_message 保留为私有别名（向后兼容老调用方）
    def _classify_message(self, role: str, content: str) -> str:
        """已弃用：请用 MessageClassifier.classify_fast。仅保留兼容老测试。"""
        from src.memory.message_classifier import classifier
        return classifier.classify_fast(role, content)["memory_type"]

    def _extract_preference(self, content: str) -> Optional[list[dict]]:
        """
        从用户消息中提取偏好，返回 [{memory_type, key, value}, ...] 或 None。

        一次消息可包含多条偏好（如「回复要客观，我是理科生」包含 tone + identity），
        因此返回列表；空列表 / None 时不写入 user_memory。

        memory_type 取值（写入 user_memory.memory_type 字段）：
          identity   用户身份 / 背景（如「我是理科生」）
          tone       回复语气（如「回复要客观」「需要简洁」）
          format     回复格式 / 语言（如「请用中文」「给代码证据」）
          taboo      禁忌项（如「别用 emoji」）
          preferred_style / preferred_topics / preferred_tts  （兼容旧分类）

        返回 None 或 [] 时不写入 user_memory，让对话走 normal 路径。
        """
        content_stripped = content.strip()
        content_lower = content_stripped.lower()
        prefs: list[dict] = []  # 收集本条消息里识别出的所有偏好

        # ── 身份 / 背景 ─────────────────────────────────────
        # 1) 句首：「我是 X」
        identity_match = re.match(
            r"^我[是为](?:一名?|个)?\s*([一-龥A-Za-z0-9·/\-]{2,12})",
            content_stripped,
        )
        # 2) 句中：「我是 X」+ 后面还有内容（如「回复时...我是理科生」）
        if not identity_match:
            identity_match = re.search(
                r"我[是为](?:一名?|个)?\s*([一-龥A-Za-z0-9·/\-]{2,12})",
                content_stripped,
            )
        if identity_match:
            identity = identity_match.group(1).strip()
            # 过滤掉明显非身份词的取值
            if identity not in ("不想", "不", "觉得", "想", "来", "走", "看"):
                prefs.append({
                    "memory_type": "identity",
                    "key": "background",
                    "value": identity,
                })

        # ── 禁忌项（先匹配，因为「不要 X」和「要 X」容易混）──
        taboo_patterns = [
            (r"不要[用加说写]?\s*([一-龥A-Za-z0-9 ·/\-]{2,40})", "不要 X"),
            (r"别[用加说写]?\s*([一-龥A-Za-z0-9 ·/\-]{2,40})", "别 X"),
            (r"禁止\s*([一-龥A-Za-z0-9 ·/\-]{2,40})", "禁止 X"),
        ]
        for pat, _label in taboo_patterns:
            m = re.search(pat, content_stripped)
            if m:
                taboo = m.group(1).strip().rstrip("，。. ")
                if taboo and taboo not in ("用", "加", "说", "写"):
                    prefs.append({
                        "memory_type": "taboo",
                        "key": "avoid",
                        "value": taboo,
                    })

        # ── 语气 / 风格 ─────────────────────────────────────
        tone_keywords = ("客观", "简洁", "详细", "专业", "通俗", "正式", "随意",
                         "严肃", "轻松", "幽默", "严谨", "理性", "感性")
        for kw in tone_keywords:
            if kw in content_stripped:
                prefs.append({
                    "memory_type": "tone",
                    "key": "reply_style",
                    "value": kw,
                })
                break  # 一种语气只记一次，避免重复

        # ── 格式 / 语言 ─────────────────────────────────────
        if re.search(r"用\s*中文|说\s*中文|中文回复", content_stripped):
            prefs.append({"memory_type": "format", "key": "language", "value": "中文"})
        elif re.search(r"用\s*英文|说\s*英文|英文回复", content_stripped):
            prefs.append({"memory_type": "format", "key": "language", "value": "英文"})
        if re.search(r"给.*代码|带.*示例|给.*证据|要.*数据", content_stripped):
            prefs.append({"memory_type": "format", "key": "include", "value": "代码/证据"})
        if re.search(r"不要\s*emoji|别用\s*emoji|不带\s*emoji", content_lower):
            prefs.append({"memory_type": "taboo", "key": "avoid", "value": "emoji"})

        # ── 兼容旧分类：风格 / 话题 / TTS ────────────────────
        if "风格" in content_stripped:
            if "更倾向" in content_lower or "喜欢" in content_lower:
                prefs.append({"memory_type": "preferred_style", "key": "preferred_style", "value": content_stripped[:200]})
        if "话题" in content_stripped or "主题" in content_stripped:
            prefs.append({"memory_type": "preferred_topics", "key": "preferred_topics", "value": content_stripped[:200]})
        if "用" in content_lower and ("tts" in content_lower or "语音" in content_stripped or "配音" in content_stripped):
            if "edge" in content_lower:
                prefs.append({"memory_type": "preferred_tts", "key": "preferred_tts", "value": "edge"})
            if "gpt" in content_lower or "sovits" in content_lower:
                prefs.append({"memory_type": "preferred_tts", "key": "preferred_tts", "value": "gpt_sovits"})

        return prefs or None

    def _find_similar_problem(self, user_id: str, content: str) -> Optional[ProblemMemory]:
        """简单相似度判断：内容重复则视为已有问题"""
        return (
            self.session.query(ProblemMemory)
            .filter(ProblemMemory.user_id == user_id)
            .filter(
                ProblemMemory.status.in_([ProblemStatus.UNRESOLVED.value, ProblemStatus.INVESTIGATING.value]),
            )
            .filter(ProblemMemory.problem_text.like(f"%{content[:50]}%"))
            .first()
        )

    def _add_problem(
        self,
        session_id: int,
        user_id: str,
        content: str,
        memory_type: str,
        tags: list = None,
    ):
        problem = ProblemMemory(
            user_id=user_id,
            problem_text=content[:1000],
            problem_tags=tags or [],
            status=ProblemStatus.UNRESOLVED.value,
            context_summary=content[:200],
        )
        self.session.add(problem)
        self.session.commit()

    def _add_conversation_message(
        self,
        session_id: int,
        role: str,
        content: str,
        memory_type: str,
    ):
        msg = ConversationMemory(
            session_id=session_id,
            role=role,
            content=content[:2000],
            memory_type=memory_type,
        )
        self.session.add(msg)
        self.session.commit()

    def _upsert_user_memory(self, session_id: int, user_id: str, pref: dict):
        existing = (
            self.session.query(UserMemory)
            .filter_by(user_id=user_id, key=pref["key"])
            .first()
        )
        if existing:
            existing.value = pref["value"]
            existing.source_session_id = session_id
            existing.updated_at = datetime.utcnow()
        else:
            memory = UserMemory(
                user_id=user_id,
                memory_type=pref["memory_type"],
                key=pref["key"],
                value=pref["value"],
                source_session_id=session_id,
            )
            self.session.add(memory)
        self.session.commit()

    def _trim_window(self, session_id: int) -> bool:
        """滑动窗口：超过 WINDOW_SIZE 条时删除最早一条 normal 消息"""
        count = (
            self.session.query(ConversationMemory)
            .filter_by(session_id=session_id, memory_type="normal")
            .count()
        )
        if count <= WINDOW_SIZE:
            return False
        oldest = (
            self.session.query(ConversationMemory)
            .filter_by(session_id=session_id, memory_type="normal")
            .order_by(ConversationMemory.created_at.asc())
            .first()
        )
        if oldest:
            self.session.delete(oldest)
            self.session.commit()
        return True

    # ── 查询 ────────────────────────────────────────────

    def get_recent_messages(self, session_id: int, limit: int = 20) -> list[dict]:
        """获取最近 N 条会话消息（不含 discarded）"""
        rows = (
            self.session.query(ConversationMemory)
            .filter(
                ConversationMemory.session_id == session_id,
                ConversationMemory.memory_type != "discarded",
            )
            .order_by(ConversationMemory.created_at.asc())
            .limit(limit)
            .all()
        )
        return [
            {"role": r.role, "content": r.content, "memory_type": r.memory_type}
            for r in rows
        ]

    def get_user_memories(self, user_id: str = "default") -> list[dict]:
        """获取用户所有偏好记忆"""
        rows = (
            self.session.query(UserMemory)
            .filter_by(user_id=user_id)
            .all()
        )
        return [
            {"memory_type": r.memory_type, "key": r.key, "value": r.value}
            for r in rows
        ]

    def get_unresolved_problems(self, limit: int = 50) -> list[dict]:
        """获取未解决的问题（Phase 2 扩展：返回 last_investigation_note）"""
        rows = (
            self.session.query(ProblemMemory)
            .filter(
                ProblemMemory.status.in_([
                    ProblemStatus.UNRESOLVED.value,
                    ProblemStatus.INVESTIGATING.value,
                ])
            )
            .order_by(ProblemMemory.updated_at.asc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": r.id,
                "problem_text": r.problem_text,
                "status": r.status,
                "investigation_count": r.investigation_count,
                "last_investigated_at": r.last_investigated_at.isoformat() if r.last_investigated_at else None,
                "last_investigation_note": r.last_investigation_note or "",
                "solution": r.solution,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

    def resolve_problem(self, problem_id: int, solution: str, session_id: int):
        """标记问题为已解决"""
        problem = self.session.query(ProblemMemory).filter_by(id=problem_id).first()
        if problem:
            problem.status = ProblemStatus.RESOLVED.value
            problem.solution = solution
            problem.resolved_session_id = session_id
            problem.resolved_at = datetime.utcnow()
            self.session.commit()

    def investigate_problem(self, problem_id: int, note: str = ""):
        """记录一次调查"""
        problem = self.session.query(ProblemMemory).filter_by(id=problem_id).first()
        if problem:
            problem.investigation_count += 1
            problem.last_investigated_at = datetime.utcnow()
            problem.last_investigation_note = note[:500]
            problem.status = ProblemStatus.INVESTIGATING.value
            problem.updated_at = datetime.utcnow()
            self.session.commit()

    def discard_problem(self, problem_id: int):
        problem = self.session.query(ProblemMemory).filter_by(id=problem_id).first()
        if problem:
            problem.status = ProblemStatus.DISCARDED.value
            problem.updated_at = datetime.utcnow()
            self.session.commit()
