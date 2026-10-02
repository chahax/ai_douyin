# -*- coding: utf-8 -*-
"""P3 多轮 tool loop 单元测试（mock LLM + registry，不碰 DB / 网络）。

验证 _iter_agent_loop：
  T1 多步推理：LLM 连调两个工具后给最终回复 → messages 结构正确 + 最终文本对
  T2 结果回灌：工具结果作为 role=tool 消息进入 messages（P3 核心）
  T3 P4 叙述：执行过程 yield 出"🔧 调用 X…"进度行
  T4 确认门在循环内：requires_confirmation 工具 → 整轮挂起，存 loop_messages
  T5 迭代上限：LLM 一直调工具 → 到 MAX_LOOP_ITERS 停下，不无限自调
  T6 失败结果也回灌：success=false 的结果照样喂回，模型可据此重试（agent 层 retry）
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agent import agent as agent_mod
from src.agent.agent import Agent, AgentResponse, MAX_LOOP_ITERS
from src.shared.llm_client import ChatResponse, ToolCall


class FakeMM:
    """最小 MemoryManager 替身：只记录 append_message / save_pending_plan。"""

    def __init__(self):
        self.messages = []
        self.pending = "UNSET"

    def append_message(self, session_id, role, content, **kw):
        self.messages.append({"role": role, "content": content, **kw})

    def save_pending_plan(self, session_id, data):
        self.pending = data


def make_agent(script, requires_confirm=(), call_impl=None):
    """构造 Agent 并 mock 掉 LLM 与 registry。"""
    ag = Agent(user_id="test")

    seq = list(script)

    def fake_llm(messages, tools, caller="", temperature=0.3, tool_choice="auto"):
        assert tool_choice == "auto", "多轮 loop 必须 tool_choice=auto，否则永不收敛"
        return seq.pop(0)

    # 打补丁：agent 模块里的 llm_client 单例
    agent_mod.llm_client.chat_completion_with_tools = fake_llm

    if call_impl is None:
        def call_impl(name, kwargs):
            return {"success": True, "summary": f"{name} 完成"}
    ag.registry.call = call_impl

    def fake_requires_confirmation(name):
        return name in requires_confirm
    ag._requires_confirmation = fake_requires_confirmation
    return ag


def run(ag, messages, mm):
    items = list(ag._iter_agent_loop(messages, 1, mm))
    finals = [x for x in items if isinstance(x, AgentResponse)]
    narration = [x for x in items if isinstance(x, str)]
    assert len(finals) == 1, f"应恰好 yield 一个 AgentResponse，实际 {len(finals)}"
    # AgentResponse 必须是最后一个元素
    assert isinstance(items[-1], AgentResponse), "AgentResponse 必须最后 yield"
    return finals[0], narration


# ── T1 + T2 + T3：多步 + 回灌 + 叙述 ──────────────────────────
print("=== T1/T2/T3 多步推理 + 结果回灌 + P4 叙述 ===")
script = [
    ChatResponse(content="", tool_calls=[ToolCall(name="fetch", args={"n": 5}, id="c1")]),
    ChatResponse(content="", tool_calls=[ToolCall(name="make_video", args={}, id="c2")]),
    ChatResponse(content="都搞定啦！", tool_calls=[]),
]
ag = make_agent(script)
messages = [{"role": "user", "content": "抓5本再生成视频"}]
mm = FakeMM()
final, narration = run(ag, messages, mm)

assert final.text == "都搞定啦！", final.text
assert not final.needs_confirmation
# messages 结构：user, assistant(tool_calls), tool, assistant(tool_calls), tool
roles = [m["role"] for m in messages]
assert roles == ["user", "assistant", "tool", "assistant", "tool"], roles
# T2：工具结果回灌
assert messages[2]["role"] == "tool" and "fetch 完成" in messages[2]["content"]
assert messages[4]["role"] == "tool" and "make_video 完成" in messages[4]["content"]
# assistant tool_calls 消息 shape 正确
assert messages[1]["tool_calls"][0]["function"]["name"] == "fetch"
# T3：P4 叙述行
assert any("fetch" in s and "🔧" in s for s in narration), narration
assert any("✅" in s for s in narration), narration
# 最终回复落库
assert mm.messages[-1]["content"] == "都搞定啦！"
print("  PASS: 两步工具链 + 结果回灌 + 叙述行都正确")


# ── T4：确认门在循环内 ────────────────────────────────────────
print("\n=== T4 确认门在循环内（整轮挂起 + 存 loop 状态）===")
script = [
    ChatResponse(content="", tool_calls=[ToolCall(name="publish", args={"id": 9}, id="c1")]),
]
ag = make_agent(script, requires_confirm={"publish"})
messages = [{"role": "user", "content": "发布"}]
mm = FakeMM()
final, _ = run(ag, messages, mm)

assert final.needs_confirmation, "需确认工具应挂起"
assert final.pending_plan is not None
assert mm.pending not in (None, "UNSET"), "应存 pending_plan"
assert mm.pending["pending_tool_calls"][0]["name"] == "publish"
assert "loop_messages" in mm.pending, "必须存 loop_messages 供确认后恢复续跑"
# 挂起时不应真的执行工具（messages 里没有 role=tool）
assert not any(m["role"] == "tool" for m in messages), "确认前不得执行工具"
print("  PASS: 挂起、未执行、loop 状态已持久化")


# ── T5：迭代上限 ─────────────────────────────────────────────
print("\n=== T5 迭代上限（防无限自调）===")
script = [
    ChatResponse(content="", tool_calls=[ToolCall(name="foo", args={}, id=f"c{i}")])
    for i in range(MAX_LOOP_ITERS + 3)
]
ag = make_agent(script)
messages = [{"role": "user", "content": "转圈"}]
mm = FakeMM()
final, _ = run(ag, messages, mm)

assert not final.needs_confirmation
assert "上限" in final.text, final.text
tool_msgs = [m for m in messages if m["role"] == "tool"]
assert len(tool_msgs) == MAX_LOOP_ITERS, f"应恰好执行 {MAX_LOOP_ITERS} 轮，实际 {len(tool_msgs)}"
print(f"  PASS: 到 {MAX_LOOP_ITERS} 轮上限停下")


# ── T6：失败结果也回灌，模型据此重试 ─────────────────────────
print("\n=== T6 失败结果回灌 → agent 层 retry ===")
calls = {"n": 0}


def flaky_call(name, kwargs):
    calls["n"] += 1
    if calls["n"] == 1:
        return {"success": False, "code": "bad_param", "message": "ranking 非法"}
    return {"success": True, "summary": "重试成功"}


script = [
    ChatResponse(content="", tool_calls=[ToolCall(name="fetch", args={"ranking": "x"}, id="c1")]),
    # 模型看到失败结果 → 改参重试
    ChatResponse(content="", tool_calls=[ToolCall(name="fetch", args={"ranking": "爆款榜"}, id="c2")]),
    ChatResponse(content="修正参数后成功了", tool_calls=[]),
]
ag = make_agent(script, call_impl=flaky_call)
messages = [{"role": "user", "content": "抓书"}]
mm = FakeMM()
final, narration = run(ag, messages, mm)

assert final.text == "修正参数后成功了"
# 第一次失败结果确实回灌了（messages 里能看到 bad_param）
assert any("bad_param" in m.get("content", "") for m in messages if m["role"] == "tool")
assert any("⚠️" in s for s in narration), "失败应有叙述"
assert calls["n"] == 2, "应重试一次"
print("  PASS: 失败结果回灌，模型改参重试成功")


print("\n=== ALL AGENT LOOP TESTS PASSED ===")
