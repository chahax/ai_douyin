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
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from src.agent.prompts import build_system_prompt, build_user_context, format_style_preferences, format_creation_preferences
from src.agent.registry import SkillRegistry
from src.memory import MemoryManager
from src.memory.problem_memory import MemoryLayerManager
from src.shared.llm_client import llm_client, ChatResponse, ToolCall, _normalize_tool_calls
from src.shared.logger import logger


# 失败兜底回复：保证 UI 永远拿到 text 字段，不会因为 LLM 异常冒到 Streamlit
FALLBACK_REPLY = "抱歉，我现在处理这条消息时遇到了点问题（{reason}），请稍后再试或换个说法。"

# P3 多轮 tool loop 上限：一次用户消息内最多自动推进多少轮 LLM↔工具往返。
# 到顶后停下让用户接手，避免模型陷入无限自调。
MAX_LOOP_ITERS = 6

# 回灌给 LLM 的单条 tool 结果最大字符数。抓到的章节正文/大 JSON 原样回灌会爆
# token，这里截断（模型只需要摘要级信息判断下一步，不需要全文）。
_TOOL_RESULT_MAX_CHARS = 4000


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

    @classmethod
    def from_tool_call(cls, tool_call, registry=None) -> "ExecutionPlan":
        """从 LLM 选好的 ToolCall 构造 ExecutionPlan。

        Args:
            tool_call: llm_client.ToolCall（归一化后）
            registry: 用于查 skill.description 拿 goal 模板
        """
        skill_name = tool_call.name
        skill_kwargs = dict(tool_call.args or {})

        # 找 skill 描述作为 goal
        goal = ""
        if registry is not None:
            sk = registry.get(skill_name)
            if sk is not None:
                goal = sk.description[:120]
        if not goal:
            goal = f"调用 {skill_name}"

        return cls(
            steps=[f"执行 {skill_name}({skill_kwargs})"],
            target_skill=skill_name,
            skill_kwargs=skill_kwargs,
            goal=goal,
            estimated_time="1-5 分钟",
        )


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
        self._tools_schema = self.registry.to_openai_tools_schema()
        # P1：缓存最近一次 chat_stream 的完整 AgentResponse，供 streamlit 在
        # write_stream 结束后取 pending_plan 渲染 ✅/❌ 按钮
        self._last_streaming_response: Optional[AgentResponse] = None

    @property
    def last_streaming_response(self) -> Optional[AgentResponse]:
        return self._last_streaming_response

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
    # P1 streaming 版本
    # -------------------------------------------------------------------------

    def chat_stream(self, user_message: str, session_id: int):
        """P1 streaming 入口。

        Yield token 字符串（content 增量），供 streamlit 的 st.write_stream
        实时注入气泡。结束流后会自动调用 _chat_impl 走完业务逻辑
        （plan save / DB 写入）。最终 AgentResponse 缓存在
        self._last_streaming_response。

        注意：tool_call OpenAI 协议下不流式（一次性给出），所以
        "纯聊天"分支才有 token 流；"调 Skill"分支其实只流 thinking content，
        真正的 tool_call 收尾后整段出现。
        """
        # 1) 复用 _chat_impl 内部逻辑，单独给 streaming 路径
        #    这里先取一个基本的消息组装与 LLM 调用路径
        return self._iter_chat_stream(user_message, session_id)

    def _iter_chat_stream(self, user_message: str, session_id: int):
        """内部生成器，yield content token 到 caller。

        策略（兼顾 UX 与正确性）：
          1. 有待确认计划 → 走 _handle_confirmation（可能触发多轮 loop 续跑），
             一次性 yield 最终文本。
          2. 首轮用流式 LLM（tool_choice=auto）：
             - 只有 token、没有 tool_call → 纯聊天，逐 token 流出（保留原 UX）。
             - 出现 tool_call → 首轮结果作为 seed 交给非流式 _run_agent_loop 续跑，
               yield 一个进度提示 + 最终自然语言回复。
        """
        with MemoryLayerManager() as mlm:
            classification = mlm.add_message(
                session_id, role="user", content=user_message, user_id=self.user_id
            )
            if classification.get("memory_type") not in ("discarded",):
                self._fire_enrichment(session_id, user_message)

            with MemoryManager() as mm:
                sess = mm.get_or_create_active_session(self.user_id)

                pending = mm.get_pending_plan(sess.id)
                if pending:
                    # 有 plan 在等确认：不走 streaming，直接走确认/续跑路径
                    self._last_streaming_response = self._handle_confirmation(
                        user_message, pending, sess.id, mm
                    )
                    yield getattr(self._last_streaming_response, "text", "")
                    return

                messages = self._build_messages(user_message, sess.id, mm, mlm)

                # 首轮流式
                accumulated_content = ""
                tool_call_payloads = []
                provider = llm_client.provider
                for event_type, data in llm_client.chat_completion_with_tools_stream(
                    messages,
                    tools=self._tools_schema,
                    caller="agent_chat_stream",
                    temperature=0.3,
                    tool_choice="auto",
                ):
                    if event_type == "token":
                        cleaned = provider.normalize_text_content(data) or data
                        accumulated_content += cleaned
                        yield cleaned
                    elif event_type == "tool_call":
                        tool_call_payloads.append(data)
                    elif event_type == "done":
                        pass

                seed_calls = _normalize_tool_calls(tool_call_payloads)
                if not seed_calls:
                    # 纯聊天：已逐 token 流完，落库收尾
                    content = accumulated_content.strip() or "（AI 助手无回复）"
                    mm.append_message(sess.id, role="assistant", content=content)
                    self._last_streaming_response = AgentResponse(text=content)
                    return

                # 有 tool_call → 交给多轮 loop（非流式）续跑，并把每步叙述流给 UI（P4）
                seed = ChatResponse(content=accumulated_content, tool_calls=seed_calls)
                final = None
                for item in self._iter_agent_loop(messages, sess.id, mm, seed_response=seed):
                    if isinstance(item, AgentResponse):
                        final = item
                    else:
                        # 进度叙述行（"🔧 调用 X…"）实时注入气泡
                        yield item
                self._last_streaming_response = final or AgentResponse(text="（AI 助手无回复）")
                # loop 的最终文本（确认拦截时是计划文本；否则是自然语言总结）
                if final and final.text:
                    yield "\n" + final.text

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

                # 3. 构建上下文并进入多轮 tool loop
                messages = self._build_messages(user_message, sess.id, mm, mlm)
                return self._run_agent_loop(messages, sess.id, mm)

    def _build_messages(self, user_message: str, session_id: int, mm, mlm) -> list[dict]:
        """组装本轮 LLM 的 messages（system prompt + 用户上下文 + 当前消息）。

        _chat_impl 与 _iter_chat_stream 共用，避免重复。
        """
        prefs = mm.get_preferences(self.user_id)
        user_memories = mlm.get_user_memories(self.user_id)
        recent_msgs = mlm.get_recent_messages(session_id, limit=20)

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
        return [
            {"role": "system", "content": self._system_prompt},
            {"role": "system", "content": user_context},
            {"role": "user", "content": user_message},
        ]

    # -------------------------------------------------------------------------
    # P3：多轮 tool loop（Claude Code 式 agent 循环）
    # -------------------------------------------------------------------------

    def _run_agent_loop(
        self,
        messages: list[dict],
        session_id: int,
        mm: MemoryManager,
        seed_response: Optional[ChatResponse] = None,
        persist_final: bool = True,
    ) -> AgentResponse:
        """多轮 loop 的非流式包装：跑完 _iter_agent_loop，丢弃叙述行，返回最终 AgentResponse。

        供 _chat_impl / _handle_confirmation 使用。流式入口直接迭代 _iter_agent_loop
        以便把叙述行实时 yield 给 UI（P4）。
        """
        result: Optional[AgentResponse] = None
        for item in self._iter_agent_loop(
            messages, session_id, mm,
            seed_response=seed_response, persist_final=persist_final,
        ):
            if isinstance(item, AgentResponse):
                result = item
        return result if result is not None else AgentResponse(text="（AI 助手无回复）")

    def _iter_agent_loop(
        self,
        messages: list[dict],
        session_id: int,
        mm: MemoryManager,
        seed_response: Optional[ChatResponse] = None,
        persist_final: bool = True,
    ):
        """多轮 LLM↔工具循环的生成器（单一事实来源）。

        yield：
          - str            —— 给用户看的进度叙述行（P4 推理可见性），如"🔧 调用 X…"
          - AgentResponse  —— 最终结果，**且一定是最后一个 yield 的元素**

        每一轮：
          1. LLM(tool_choice=auto) 看当前 messages（含历史 tool 结果）。
          2. 无 tool_call → 这就是最终回复（模型已看过所有结果，P1/P2 的
             "把结果翻译成人话 + 判断是否合理"在这里自然发生）→ 结束。
          3. 有 tool_call：
             - 若本轮存在需要确认的工具 → 整轮挂起（存 loop 状态到 pending_plan），
               yield needs_confirmation 结果，交给 UI 弹确认按钮。用户确认后由
               _handle_confirmation 恢复 messages 续跑本循环。
             - 否则执行本轮全部工具 → 把结果作为 role=tool 消息回灌 → 进入下一轮。
               失败的结果也照样回灌，模型能据此改参重试 / 换工具（agent 层 retry）。

        Args:
            seed_response: 首轮结果（来自 streaming 首轮），提供则跳过该轮 LLM 调用。
            persist_final: 是否把最终自然语言回复落库。confirm 续跑时置 False，
                由调用方补一条带 tool_success/tool_error 标记的消息。
        """
        pending_resp = seed_response
        for _ in range(MAX_LOOP_ITERS):
            if pending_resp is not None:
                resp = pending_resp
                pending_resp = None
            else:
                resp = llm_client.chat_completion_with_tools(
                    messages,
                    tools=self._tools_schema,
                    caller="agent_chat",
                    temperature=0.3,
                    tool_choice="auto",
                )

            if not resp.tool_calls:
                # 最终自然语言回复
                content = (resp.content or "").strip() or "（AI 助手无回复）"
                if persist_final:
                    mm.append_message(session_id, role="assistant", content=content)
                yield AgentResponse(text=content)
                return

            # 给每个 tool_call 落实 id（部分供应商不返回 id；确保 assistant/tool 配对）
            for i, tc in enumerate(resp.tool_calls):
                if not tc.id:
                    tc.id = f"call_{i}"

            # 追加"助手发起工具调用"这一轮到 messages（OpenAI 协议要求）
            messages.append(self._assistant_tool_calls_msg(resp))

            # 需要确认？整轮 gate（避免同一 assistant 轮内 tool_call 与结果不成对）
            need_confirm = [tc for tc in resp.tool_calls if self._requires_confirmation(tc.name)]
            if need_confirm:
                display_text = self._format_turn_plan(resp.tool_calls)
                first = resp.tool_calls[0]
                plan = ExecutionPlan.from_tool_call(first, registry=self.registry)
                mm.save_pending_plan(session_id, {
                    "plan": {
                        "steps": plan.steps,
                        "goal": plan.goal,
                        "estimated_time": plan.estimated_time,
                        "target_skill": plan.target_skill,
                        "skill_kwargs": plan.skill_kwargs,
                    },
                    "response_text": display_text,
                    # P3：把整个 loop 状态存下来，确认后从这里恢复续跑
                    "loop_messages": messages,
                    "pending_tool_calls": [self._tc_to_dict(tc) for tc in resp.tool_calls],
                })
                mm.append_message(session_id, role="assistant", content=display_text)
                yield AgentResponse(
                    text=display_text, pending_plan=plan, needs_confirmation=True,
                )
                return

            # 全部无需确认 → 执行，结果回灌（P4：每步叙述给用户）
            for tc in resp.tool_calls:
                yield self._narrate_call(tc)
                result = self.registry.call(tc.name, dict(tc.args or {}))
                yield self._narrate_result(result)
                messages.append(self._tool_result_msg(tc.id, tc.name, result))

        # 到达迭代上限仍未收敛
        text = (
            "这个任务步骤较多，已到本轮自动执行上限。我可以继续，"
            "请回复「继续」，或告诉我下一步怎么做。"
        )
        if persist_final:
            mm.append_message(session_id, role="assistant", content=text)
        yield AgentResponse(text=text)

    # ── loop 用到的消息/工具辅助 ────────────────────────────────

    @staticmethod
    def _narrate_call(tc: ToolCall) -> str:
        """P4：工具调用前的进度行。"""
        kw = ", ".join(f"{k}={v}" for k, v in (tc.args or {}).items())
        return f"\n🔧 调用 `{tc.name}`（{kw or '无参数'}）…\n"

    @staticmethod
    def _narrate_result(result: dict) -> str:
        """P4：工具返回后的进度行（成功/失败一句话）。"""
        if result.get("success"):
            s = result.get("summary") or result.get("message") or "完成"
            return f"　↳ ✅ {str(s)[:120]}\n"
        code = result.get("code", "error")
        msg = result.get("message") or "执行失败"
        return f"　↳ ⚠️ [{code}] {str(msg)[:120]}\n"

    def _requires_confirmation(self, skill_name: str) -> bool:
        sk = self.registry.get(skill_name)
        return bool(sk and getattr(sk, "requires_confirmation", False))

    @staticmethod
    def _tc_to_dict(tc: ToolCall) -> dict:
        return {"id": tc.id, "name": tc.name, "args": dict(tc.args or {})}

    @staticmethod
    def _assistant_tool_calls_msg(resp: ChatResponse) -> dict:
        """把 ChatResponse 的 tool_calls 渲染成 OpenAI assistant 消息。"""
        return {
            "role": "assistant",
            "content": resp.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.args or {}, ensure_ascii=False),
                    },
                }
                for tc in resp.tool_calls
            ],
        }

    @staticmethod
    def _assistant_tool_calls_msg_from_dicts(tc_dicts: list[dict]) -> dict:
        return {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": d.get("id") or f"call_{i}",
                    "type": "function",
                    "function": {
                        "name": d.get("name", ""),
                        "arguments": json.dumps(d.get("args") or {}, ensure_ascii=False),
                    },
                }
                for i, d in enumerate(tc_dicts)
            ],
        }

    @classmethod
    def _tool_result_msg(cls, tool_call_id: str, name: str, result: dict) -> dict:
        """把 skill 结果渲染成 OpenAI role=tool 消息（截断大结果）。"""
        try:
            payload = json.dumps(result, ensure_ascii=False)
        except (TypeError, ValueError):
            payload = str(result)
        if len(payload) > _TOOL_RESULT_MAX_CHARS:
            payload = payload[:_TOOL_RESULT_MAX_CHARS] + "…（结果过长已截断）"
        return {"role": "tool", "tool_call_id": tool_call_id, "name": name, "content": payload}

    def _format_turn_plan(self, tool_calls: list[ToolCall]) -> str:
        """把待确认的一轮（可能多个）工具调用渲染成给用户看的计划文本。"""
        if len(tool_calls) == 1:
            return self._format_plan_for_user(
                ExecutionPlan.from_tool_call(tool_calls[0], registry=self.registry)
            )
        lines = ["**计划**：我准备依次执行以下操作（需要你确认）：", ""]
        for i, tc in enumerate(tool_calls, 1):
            kw = "、".join(f"{k}={v}" for k, v in (tc.args or {}).items()) or "无参数"
            lines.append(f"{i}. `{tc.name}`（{kw}）")
        lines.append("")
        lines.append("输入「确认」开始执行，或「取消」终止。")
        return "\n".join(lines)

    # -------------------------------------------------------------------------
    # 规则短路：高频 + 参数明确的请求直接走 Python 解析，跳过 LLM
    # -------------------------------------------------------------------------

    # 已知的规则模式：(compiled regex, target_skill, kwarg extractor)
    # 仅匹配意图明确、参数可从消息里取出的请求；其它情况回落到 LLM。
    _FAST_DISPATCH_RULES: list = []

    @classmethod
    def _build_fast_dispatch_rules(cls):
        """懒构建：第一次匹配时再 compile regex（避免 import 期开销）。"""
        if cls._FAST_DISPATCH_RULES:
            return cls._FAST_DISPATCH_RULES
        import re

        # 番茄抓 N 本 X 榜：[抓|来]?[\s]*[取|拿|抓]?[\d]+[\s]*本?[\s]*(.+?)[\s]*的书
        # 例：抓 10 本爆款榜的书 / 抓 5 本阅读榜 / 来 10 本潜力榜
        rules = [
            {
                "name": "fanqie_batch_fetch_filtered",
                "pattern": re.compile(
                    r"(?:抓|来)?\s*(\d+)\s*本?\s*(爆款榜|阅读榜|潜力榜|全部内容)",
                    re.IGNORECASE,
                ),
                "skill": "fanqie_batch_fetch_filtered",
                "build_kwargs": lambda m: {
                    "ranking": m.group(2),
                    "target_count": int(m.group(1)),
                    "chapters": 40,
                    "headful": True,    # 默认让浏览器可见，看得到活动
                    "auto_run": True,   # 默认一次完成（扫榜 → 入库 → 抓章节 → 写文件）
                },
                "plan_template": lambda kw: (
                    f"**计划**：从番茄达人中心 **{kw.get('ranking')}** 扫榜拉 **{kw.get('target_count', 0)} 本**书入库，然后**直接抓取章节**写文件（一次性完成）。\n\n"
                    f"**Skill**：`fanqie_batch_fetch_filtered`\n\n"
                    f"**参数**：\n"
                    f"- ranking: {kw.get('ranking')}\n"
                    f"- target_count: {kw.get('target_count', 0)}\n"
                    f"- chapters: {kw.get('chapters', 5)}\n"
                    f"- headful: {kw.get('headful', True)}（headful=True 浏览器可见，False 无窗口）\n"
                    f"- auto_run: {kw.get('auto_run', True)}（True 一次性完成；False 只入库不抓）\n\n"
                    f"输入「确认」开始执行，或「取消」终止。"
                ),
            },
            {
                "name": "fanqie_batch_run",
                # 触发词：开始跑 / 开始抓 / 跑一下 / 执行抓书 / 继续抓 / run
                "pattern": re.compile(
                    r"(?:开始|继续|再)?\s*(?:跑|执行|开始|run|抓取?)?\s*(?:抓|跑)?\s*取?\s*(?:刚才)?(?:\d+\s*本?)?\s*(?:书|抓取|批量|待办|pending)?",
                ),  # 主匹配下方再精修；以更精确的子句驱动
                "skill": "fanqie_batch_run",
                "build_kwargs": lambda m: {"interval_s": 5, "max_count": 10},
                # 用 match_any 模式：匹配任意一种触发词
                "match_any": [
                    re.compile(r"开始(?:跑|抓|执行)?\s*(?:抓|跑)?\s*(?:书|批量|pending)?", re.IGNORECASE),
                    re.compile(r"继续(?:抓|跑)", re.IGNORECASE),
                    re.compile(r"(?:现在|立刻|马上)?\s*(?:跑|执行)\s*抓", re.IGNORECASE),
                    re.compile(r"(?:现在|立刻|马上)?\s*批量抓", re.IGNORECASE),
                    re.compile(r"run\s*(?:batch|抓书)?", re.IGNORECASE),
                    re.compile(r"(?:跑下|执行下|跑一下)\s*抓", re.IGNORECASE),
                ],
                "plan_template": lambda kw: (
                    "**计划**：从 DB 里读 `pending` 状态的书，逐本抓 5 章正文 + 元数据，"
                    "写入 `data/fanqie_promotion/books/<id>_<书名>/`。\n\n"
                    f"**Skill**：`fanqie_batch_run`\n\n"
                    "**参数**：\n"
                    f"- interval_s: {kw.get('interval_s', 5)} 秒（每本之间间隔）\n"
                    f"- max_count: {kw.get('max_count', 10)} 本（本次上限）\n\n"
                    "预计耗时 **5-15 分钟**（取决于本数 + 间隔 + 是否需要登录）。\n\n"
                    "输入「确认」开始执行，或「取消」终止。"
                ),
            },
        ]
        cls._FAST_DISPATCH_RULES = rules
        return rules

    def _try_fast_dispatch(self, user_message: str):
        """
        规则短路：识别参数明确的高频请求，**跳过 LLM** 直接构造 plan dict。
        返回 None 表示没匹配上，让后续 LLM 流程接管。

        每条 rule 支持两种匹配方式：
        - `pattern`：单一 regex
        - `match_any`：多个 regex，**任一命中即触发**（用于 fanqie_batch_run 这种多触发词的）
        """
        rules = self._build_fast_dispatch_rules()
        msg = (user_message or "").strip()
        for rule in rules:
            # 多触发词模式（任一命中）
            matched = False
            if "match_any" in rule:
                for sub_re in rule["match_any"]:
                    if sub_re.search(msg):
                        matched = True
                        break
            elif rule["pattern"].search(msg):
                matched = True
            if not matched:
                continue

            # 当 match_any 命中但 pattern 没匹配时，build_kwargs 拿不到 m
            # 解决：补一个 dummy match
            kw_source = rule["pattern"].search(msg) or rule["pattern"].search(" ")
            kw = rule["build_kwargs"](kw_source)

            plan_template = rule.get("plan_template")
            if plan_template:
                response_text = plan_template(kw)
            else:
                # 兜底：极简展示
                response_text = (
                    f"**计划**：调用 `{rule['skill']}`\n\n"
                    f"**参数**：{kw}\n\n"
                    f"输入「确认」开始执行，或「取消」终止。"
                )

            return {
                "plan": {
                    "steps": list(rule.get("steps", ["调用 Skill"])),
                    "target_skill": rule["skill"],
                    "skill_kwargs": kw,
                    "goal": rule.get("goal", f"调用 {rule['skill']}"),
                    "estimated_time": rule.get("estimated_time", "1-5 分钟"),
                },
                "response_text": response_text,
            }
        return None

    # -------------------------------------------------------------------------
    # 失败兜底
    # -------------------------------------------------------------------------

    def _handle_chat_failure(self, user_message: str, session_id: int, exc: Exception) -> AgentResponse:
        """
        chat() 内部任何异常都被这里接住：
          1. 写完整堆栈到文件（data/logs/agent.log，含 backtrace）
          2. 写兜底回复进对话历史
          3. 显式写 ProblemMemory（修潜在 bug：之前用 mlm.add_message("[chat_error]...") 被规则分类为 normal）
          4. fire-and-forget ErrorReviewer 异步写结构化诊断
          5. 返回兜底 AgentResponse，不让 UI 看到红色 traceback
        """
        # 完整堆栈写文件（保留 backtrace=True），stdout 只打一行 summary
        logger.error(
            f"[agent_chat] 失败: session_id={session_id} user={self.user_id} "
            f"exc_type={type(exc).__name__} exc_msg={str(exc)[:300]!r}"
        )
        logger.opt(exception=True).debug("完整 traceback 见 data/logs/agent.log")
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

    def _format_plan_for_user(self, plan: ExecutionPlan) -> str:
        """把 ExecutionPlan 渲染成用户在 chat 里看到的可读计划。"""
        kw_lines = "\n".join(
            f"  - `{k}`: `{v}`" for k, v in plan.skill_kwargs.items()
        ) or "  - (无参数)"
        steps_lines = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(plan.steps))
        return (
            f"**计划**：{plan.goal}\n\n"
            f"**Skill**：`{plan.target_skill}`\n\n"
            f"**步骤**：\n{steps_lines}\n\n"
            f"**参数**：\n{kw_lines}\n\n"
            f"输入「确认」开始执行，或「取消」终止。"
        )

    def _handle_confirmation(
        self,
        user_message: str,
        pending: dict,
        session_id: int,
        mm: MemoryManager,
    ) -> AgentResponse:
        """
        用户对上一个待确认计划的回复（P3：确认后恢复 loop 续跑）。

        分支：
          1. 取消词 → 清 pending_plan，回复"已取消"
          2. 确认词 / 短消息（≤5 字符）→ 执行被挂起的工具，把结果回灌，
             恢复多轮 loop 让 LLM 看结果、判断是否重试/换工具、总结成人话。
          3. 长消息 → 视为修改需求：清 pending_plan，走 _chat_impl 重新规划。
        """
        plan_data = (pending or {}).get("plan", {})
        target_skill = plan_data.get("target_skill", "")
        skill_kwargs = plan_data.get("skill_kwargs", {}) or {}

        normalized = (user_message or "").strip().lower()
        confirm_words = {"确认", "ok", "好的", "是", "yes", "y", "执行", "继续", "开始", "干吧", "好", "yep", "go"}
        cancel_words = {"取消", "不要了", "算了", "no", "n", "cancel", "停止", "不", "停"}

        is_cancel = any(w in normalized for w in cancel_words)
        # 短消息（≤5 字符且不是取消）默认当 confirm
        # 解决"用户卡在'请告诉我要修改哪里'反复输入"的循环
        is_short = len(user_message or "") <= 5 and not is_cancel

        if is_cancel:
            mm.save_pending_plan(session_id, None)
            text = "已取消，未执行任何操作。"
            mm.append_message(session_id, role="assistant", content=text)
            return AgentResponse(text=text)

        if any(w in normalized for w in confirm_words) or is_short:
            # 确认 → 执行被挂起的工具并恢复 loop。
            # 注：registry.call 内部已完成参数校验/重试/超时/auto-save 错误诊断，
            # 永远返回 SkillResult dict（不抛异常），所以不需要 try 包裹。
            mm.save_pending_plan(session_id, None)

            loop_messages = (pending or {}).get("loop_messages")
            pending_tool_calls = (pending or {}).get("pending_tool_calls") or []
            if not pending_tool_calls:
                # 老式 pending（无 loop 上下文）：从 plan 合成单个工具调用
                pending_tool_calls = [
                    {"id": "call_0", "name": target_skill, "args": skill_kwargs}
                ]

            if isinstance(loop_messages, list) and loop_messages:
                messages = loop_messages
            else:
                # 无 loop 上下文 → 重建最小上下文，让续跑 loop 能挂 tool 结果并反思
                messages = [
                    {"role": "system", "content": self._system_prompt},
                    {"role": "user", "content": (
                        f"我已确认执行 {target_skill}。请在拿到结果后用中文简洁说明"
                        f"结果并建议下一步。"
                    )},
                    self._assistant_tool_calls_msg_from_dicts(pending_tool_calls),
                ]

            # 执行被确认的每个工具，结果（含失败）回灌 messages
            any_failed = False
            last_error = ""
            for tc in pending_tool_calls:
                name = tc.get("name") or target_skill
                args = tc.get("args") or {}
                result = self.registry.call(name, args)
                success = result.get("success")
                if not success:
                    any_failed = True
                    code = result.get("code", "skill_error")
                    err_msg = result.get("message") or "Skill 执行失败"
                    last_error = f"{code}: {err_msg}"
                    # 写 ProblemMemory（这里有 session_id 上下文，registry 层没有）
                    try:
                        with MemoryLayerManager() as mlm:
                            mlm._add_problem(
                                session_id=session_id,
                                user_id=self.user_id,
                                content=f"[skill_failure] {name}: {code}: {err_msg}",
                                memory_type="problem",
                                tags=["skill_failure", name, code],
                            )
                    except Exception:
                        logger.exception("skill_failure 写 ProblemMemory 失败")
                messages.append(
                    self._tool_result_msg(tc.get("id") or "call_0", name, result)
                )

            # P1/P2 + agent 层 retry：续跑 loop，让 LLM 看结果自己决定
            # 重试/换工具/总结成自然语言。
            resp = self._run_agent_loop(
                messages, session_id, mm, persist_final=False,
            )

            # 最终回复落库，并打上工具成败标记（telemetry）。
            # 若续跑又撞到新的确认拦截，loop 内部已落库计划文本，这里不重复写。
            if not resp.needs_confirmation:
                mm.append_message(
                    session_id, role="assistant",
                    content=resp.text,
                    skill_name=target_skill,
                    tool_success=(not any_failed),
                    tool_error=last_error,
                )
            return resp

        # 长消息 → 视为 modify：清 pending_plan，走 _chat_impl 让 LLM 重新规划
        # 解决"用户换 ranking / 改 target_count / 完全新需求" 走不通的循环
        mm.save_pending_plan(session_id, None)
        logger.info(
            f"[agent_chat] 长消息改判为 modify: {user_message[:80]!r} "
            f"原 plan.skill={target_skill!r}"
        )
        return self._chat_impl(user_message, session_id)

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



