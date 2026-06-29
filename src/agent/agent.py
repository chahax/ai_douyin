# -*- coding: utf-8 -*-
"""
src/agent/agent.py — Agent 核心类

职责：
  - 接收用户消息，返回 AI 回复
  - 管理 Skill 调用规划 + 用户确认拦截
  - 维护对话上下文（通过 MemoryManager）
  - LLM 调用通过 llm_client
"""

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from src.agent.prompts import build_system_prompt, build_user_context, format_style_preferences, format_creation_preferences
from src.agent.registry import SkillRegistry
from src.memory import MemoryManager
from src.memory.problem_memory import MemoryLayerManager
from src.shared.llm_client import llm_client
from src.shared.logger import logger


# 失败兜底回复：保证 UI 永远拿到 text 字段，不会因为 LLM 异常冒到 Streamlit
FALLBACK_REPLY = "抱歉，我现在处理这条消息时遇到了点问题（{reason}），请稍后再试或换个说法。"


class ConfirmStatus(Enum):
    NONE = "none"           # 无待确认计划
    AWAITING = "awaiting"   # 等待用户确认
    CONFIRMED = "confirmed"  # 用户已确认，执行中


@dataclass
class AgentResponse:
    """Agent 对单条用户消息的响应"""
    text: str                          # AI 回复文本（展示给用户）
    pending_plan: Optional[dict] = None  # 如果有计划等待确认
    needs_confirmation: bool = False     # 是否需要用户确认
    skill_result: Optional[dict] = None  # Skill 执行结果（如有）
    error: str = ""


@dataclass
class ExecutionPlan:
    """Agent 生成的执行计划"""
    steps: list[str]
    target_skill: str
    skill_kwargs: dict
    goal: str
    estimated_time: str = "1-3 分钟"


class Agent:
    """
    Agent 调度核心。

    接收用户消息，返回 AgentResponse。
    支持"LLM 建议 + 用户确认"模式：requires_confirmation=True 的 Skill
    会先生成计划，等待用户确认后再执行。
    """

    def __init__(self, user_id: str = "default"):
        self.user_id = user_id
        self.registry = SkillRegistry()
        self._skill_descriptions = self.registry.get_skill_descriptions()
        self._system_prompt = build_system_prompt(self._skill_descriptions)

    # -------------------------------------------------------------------------
    # 主入口
    # -------------------------------------------------------------------------

    def chat(self, user_message: str, session_id: int) -> AgentResponse:
        """
        处理单条用户消息。

        流程：
        1. MemoryLayerManager 分类消息（偏好/问题/丢弃）
        2. 检查待确认计划
        3. 构建上下文（用户偏好 + 最近对话）
        4. LLM 分析意图并生成回复/计划

        出错时：记录到日志、记录到 problem_memory（若不是 preference/discarded）、
        返回带 error 的 AgentResponse，绝不抛异常到调用方。
        """
        try:
            return self._chat_impl(user_message, session_id)
        except Exception as exc:
            return self._handle_chat_failure(user_message, session_id, exc)

    # -------------------------------------------------------------------------
    # 内部实现
    # -------------------------------------------------------------------------

    def _chat_impl(self, user_message: str, session_id: int) -> AgentResponse:
        # 1. 分层记忆：自动分类消息入库（偏好/问题/滑动窗口）
        with MemoryLayerManager() as mlm:
            classification = mlm.add_message(
                session_id, role="user", content=user_message, user_id=self.user_id
            )

            # Phase 2: 异步 enrich 精细分类 metadata（不阻塞对话）
            # 只对 user 消息、非 discarded 做 enrich
            if classification.get("memory_type") not in ("discarded",):
                self._fire_enrichment(session_id, user_message)

            with MemoryManager() as mm:
                sess = mm.get_or_create_active_session(self.user_id)

                # 2. 检查待确认计划（用户回复"确认"或"取消"）
                pending = mm.get_pending_plan(sess.id)
                if pending:
                    return self._handle_confirmation(user_message, pending, sess.id, mm)

                # 3. 构建用户上下文
                prefs = mm.get_preferences(self.user_id)
                user_memories = mlm.get_user_memories(self.user_id)
                recent_msgs = mlm.get_recent_messages(sess.id, limit=20)

                style_prefs = format_style_preferences(user_memories)
                creation_prefs = format_creation_preferences(user_memories)
                conv_ctx = "\n".join(f"[{m['role']}] {m['content']}" for m in recent_msgs) or "（无历史对话）"

                user_context = build_user_context(
                    default_video_mode=prefs.default_video_mode,
                    default_tts_provider=prefs.default_tts_provider,
                    default_voice=prefs.default_voice,
                    default_character=prefs.default_character,
                    default_character_position=prefs.default_character_position,
                    default_character_size=prefs.default_character_size,
                    default_bgm_volume=prefs.default_bgm_volume,
                    preferred_topics=prefs.preferred_topics,
                    douyin_uid=prefs.douyin_uid,
                    douyin_nickname=prefs.douyin_nickname,
                    style_preferences=style_prefs,
                    creation_preferences=creation_prefs,
                    conversation_context=conv_ctx,
                )

                messages = [
                    {"role": "system", "content": self._system_prompt},
                    {"role": "system", "content": user_context},
                    {"role": "user", "content": user_message},
                ]

                response_text = llm_client.chat_completion_tracked(
                    messages,
                    temperature=0.3,
                    json_mode=False,
                )
                if not response_text or not str(response_text).strip():
                    # LLM 客户端吞了异常但返回 None / 空串——和真异常一样当成失败处理
                    raise RuntimeError("LLM 返回为空（可能是上游 API 错误，详见日志）")

                plan = self._parse_plan_from_response(response_text)

                if plan:
                    mm.save_pending_plan(sess.id, {
                        "plan": {
                            "steps": plan.steps,
                            "goal": plan.goal,
                            "estimated_time": plan.estimated_time,
                            "target_skill": plan.target_skill,
                            "skill_kwargs": plan.skill_kwargs,
                        },
                        "response_text": self._extract_response_before_plan(response_text),
                    })
                    mm.append_message(sess.id, role="assistant", content=response_text)
                    return AgentResponse(
                        text=self._extract_response_before_plan(response_text),
                        pending_plan=plan,
                        needs_confirmation=True,
                    )
                else:
                    mm.append_message(sess.id, role="assistant", content=response_text)
                    return AgentResponse(text=response_text)

    # -------------------------------------------------------------------------
    # 失败兜底
    # -------------------------------------------------------------------------

    def _handle_chat_failure(self, user_message: str, session_id: int, exc: Exception) -> AgentResponse:
        """
        chat() 内部任何异常都被这里接住：
          1. 写完整堆栈到日志
          2. 写兜底回复进对话历史
          3. 显式写 ProblemMemory（修潜在 bug：之前用 mlm.add_message("[chat_error]...") 被规则分类为 normal）
          4. fire-and-forget ErrorReviewer 异步写结构化诊断
          5. 返回兜底 AgentResponse，不让 UI 看到红色 traceback
        """
        logger.exception("Agent.chat 失败: session_id=%s user=%s", session_id, self.user_id)
        err_summary = f"{type(exc).__name__}: {exc}".strip()[:500]

        # 1. 错误回复文本（写进对话历史 + 展示给用户）
        fallback_text = FALLBACK_REPLY.format(reason=err_summary[:80])
        try:
            with MemoryManager() as mm:
                mm.append_message(
                    session_id,
                    role="assistant",
                    content=f"[ERROR] {fallback_text}",
                )
                # 清理可能残留的 pending_plan，避免下一次正常消息被误拦截
                try:
                    mm.save_pending_plan(session_id, None)
                except Exception as exc:
                    logger.debug(f"清理 pending_plan 失败（session={session_id}）: {exc}")
        except Exception:
            logger.exception("写入失败回退消息失败")

        # 2. 问题记忆：显式写（修潜在 bug：不走规则分类）
        try:
            with MemoryLayerManager() as mlm:
                mlm._add_problem(
                    session_id=session_id,
                    user_id=self.user_id,
                    content=f"[agent_chat_failure] {user_message[:300]}",
                    memory_type="problem",
                    tags=["agent_chat_failure", type(exc).__name__],
                )
        except Exception:
            logger.exception("记录失败到 ProblemMemory 失败")

        # 3. Phase 3: fire-and-forget 异步错误诊断
        try:
            from src.agent.error_reviewer import error_reviewer
            from src.shared.async_runner import fire_and_forget
            fire_and_forget(
                error_reviewer.review_and_store_async(
                    source="agent_chat",
                    location=f"session:{session_id}",
                    exc=exc,
                    context_extra={"user_message": user_message[:200]},
                ),
                name="agent-error-review",
            )
        except Exception:
            logger.exception("fire error_reviewer 启动失败")

        return AgentResponse(text=fallback_text, error=err_summary)

    # -------------------------------------------------------------------------
    # 计划解析 / 确认拦截
    # -------------------------------------------------------------------------

    # LLM 在需要确认时输出 JSON 计划块，前后用 ```plan ... ``` 包裹
    _PLAN_BLOCK_RE = re.compile(r"```plan\s*(\{.*?\})\s*```", re.DOTALL)

    def _parse_plan_from_response(self, response_text: str) -> Optional[ExecutionPlan]:
        """
        从 LLM 回复中抽出 ```plan {...} ``` 块。
        没找到或解析失败 → 返回 None（视为普通回复）。
        """
        if not response_text:
            return None
        m = self._PLAN_BLOCK_RE.search(response_text)
        if not m:
            return None
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            logger.warning("plan 块 JSON 解析失败: %s", m.group(1)[:200])
            return None

        try:
            return ExecutionPlan(
                steps=list(data.get("steps", [])),
                target_skill=str(data.get("target_skill", "")),
                skill_kwargs=dict(data.get("skill_kwargs", {}) or {}),
                goal=str(data.get("goal", "")),
                estimated_time=str(data.get("estimated_time", "1-3 分钟")),
            )
        except Exception:
            logger.exception("plan 字段不合法: %s", data)
            return None

    def _extract_response_before_plan(self, response_text: str) -> str:
        """提取 ```plan ... ``` 之前的自然语言部分。"""
        if not response_text:
            return ""
        m = self._PLAN_BLOCK_RE.search(response_text)
        if not m:
            return response_text
        return response_text[: m.start()].rstrip()

    def _handle_confirmation(
        self,
        user_message: str,
        pending: dict,
        session_id: int,
        mm: MemoryManager,
    ) -> AgentResponse:
        """
        用户对上一个待确认计划的回复。
        确认词：执行 Skill → 把结果作为新一条 assistant 消息写回。
        取消词：清空 pending_plan，回复"已取消"。
        其他：当作修改请求，让 LLM 重新生成计划。
        """
        plan_data = (pending or {}).get("plan", {})
        target_skill = plan_data.get("target_skill", "")
        skill_kwargs = plan_data.get("skill_kwargs", {}) or {}

        normalized = (user_message or "").strip().lower()
        confirm_words = {"确认", "ok", "好的", "是", "yes", "y", "执行", "继续", "开始"}
        cancel_words = {"取消", "不要了", "算了", "no", "n", "cancel", "停止"}

        if any(w in normalized for w in confirm_words):
            # 确认 → 执行 Skill
            # 注：registry.call 内部已完成参数校验/重试/超时/auto-save 错误诊断，
            # 永远返回 SkillResult dict（不抛异常）。
            result = self.registry.call(target_skill, skill_kwargs)
            mm.save_pending_plan(session_id, None)

            if not result.get("success"):
                # 失败：registry 已自动触发 error_reviewer + 写日志
                # 这里只负责清 pending + 写助手消息 + 返回错误
                err_msg = result.get("message") or "Skill 执行失败"
                code = result.get("code", "skill_error")
                # 写 ProblemMemory（这里有 session_id 上下文，registry 层没有）
                try:
                    with MemoryLayerManager() as mlm:
                        mlm._add_problem(
                            session_id=session_id,
                            user_id=self.user_id,
                            content=f"[skill_failure] {target_skill}: {code}: {err_msg}",
                            memory_type="problem",
                            tags=["skill_failure", target_skill, code],
                        )
                except Exception:
                    logger.exception("skill_failure 写 ProblemMemory 失败")

                text = f"执行失败：[{code}] {err_msg}\n请稍后再试或换个方案。"
                mm.append_message(
                    session_id, role="assistant",
                    content=text,
                    skill_name=target_skill,
                    tool_success=False,
                    tool_error=f"{code}: {err_msg}",
                )
                return AgentResponse(text=text, error=f"{code}: {err_msg}")

            # 成功
            summary = (
                result.get("summary")
                or result.get("message")
                or json.dumps(result.get("data", {}), ensure_ascii=False)[:300]
            )
            text = f"✅ 执行完成：{summary}"
            mm.append_message(
                session_id, role="assistant",
                content=text,
                skill_name=target_skill,
                tool_success=True,
            )
            return AgentResponse(text=text, skill_result=result)

        if any(w in normalized for w in cancel_words):
            mm.save_pending_plan(session_id, None)
            text = "已取消，未执行任何操作。"
            mm.append_message(session_id, role="assistant", content=text)
            return AgentResponse(text=text)

        # 其他：当作修改请求 → 重新走 LLM 流程（保留 pending 不变，让用户继续编辑）
        text = "请告诉我要修改哪里（例如：换个标题、换种风格），或者直接说「确认」/「取消」。"
        return AgentResponse(text=text)

    # -------------------------------------------------------------------------
    # Phase 2: 异步 metadata 增强
    # -------------------------------------------------------------------------

    def _fire_enrichment(self, session_id: int, user_message: str) -> None:
        """
        异步调 MessageClassifier.classify_async，回写精细 metadata
        到最近的 ConversationMemory 行。fire-and-forget，不阻塞对话。
        """
        from src.shared.async_runner import fire_and_forget

        async def _do_enrich():
            # 独立 session，避免与主线程的 mlm session 冲突
            from src.shared.database import SessionLocal
            with SessionLocal() as sess:
                mlm = MemoryLayerManager(sess)
                # 找最近一条相同 (session_id, content) 的 ConversationMemory 行
                from src.memory.problem_memory import ConversationMemory
                row = (
                    sess.query(ConversationMemory)
                    .filter_by(session_id=session_id, content=user_message)
                    .order_by(ConversationMemory.created_at.desc())
                    .first()
                )
                if row is None:
                    return
                msg_id = row.id
                await mlm._enrich_message_async(msg_id, "user", user_message)

        try:
            fire_and_forget(_do_enrich(), name="msg-classify")
        except Exception:
            logger.exception("fire_enrichment 启动失败")



