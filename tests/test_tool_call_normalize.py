"""_normalize_tool_call 跨供应商回归测试。

依据：docs/LANGGRAPH_REFACTOR_PLAN.md §12.2
  - P0 native tool calling 改动：从 LLM 取 tool_calls，归一化字段
  - _normalize_tool_call 集中归一化在 src/shared/llm_client.py
  - 必须覆盖 6 个 shape（每个新供应商 / SDK 升级前都要重跑）：
    T1 OpenAI 正常 dict 形态（top-level name/args）
    T2 OpenAI 深一层（function.{name, arguments}）
    T3 MiniMax JSON-string arguments
    T4 Ollama object 形态
    T5 损坏 JSON 字符串
    T6 缺字段（无 name）

失败补救：fix 完先把当前供应商跑通，下次再接新供应商前重跑。
"""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ── 1. 纯归一化逻辑（无网络、无 provider）───────────────────────
print("=== _normalize_tool_call 跨供应商形状 ===")
from src.shared.llm_client import (
    _normalize_tool_call, _normalize_tool_calls, ToolCall,
)


def assert_eq(label, actual, expected):
    """对比 actual ToolCall / dict 与 expected dict。"""
    if isinstance(actual, ToolCall):
        # ToolCall dataclass → dict
        actual = {"name": actual.name, "args": actual.args}
    if isinstance(expected, ToolCall):
        expected = {"name": expected.name, "args": expected.args}

    if not isinstance(actual, dict):
        print(f"  ❌ {label}: actual 不是 dict，实际类型 {type(actual).__name__}")
        raise AssertionError(label)

    for key in ("name", "args"):
        if key not in expected:
            continue  # 期望不含这个字段就不比
        if actual.get(key) != expected.get(key):
            print(f"  ❌ {label}: 字段 {key!r} 不匹配")
            print(f"     actual:  {actual}")
            print(f"     expect:  {expected}")
            raise AssertionError(label)
    print(f"  ✅ {label}")


# ── T1: OpenAI / DeepSeek 正常 top-level 形态 ──
tc = _normalize_tool_call({
    "id": "call_abc123",
    "type": "function",
    "function": {
        "name": "fanqie_batch_fetch_filtered",
        "arguments": '{"ranking": "爆款榜", "target_count": 10}',
    },
    # 顶层直接有的 name + args（部分 SDK 简化形态）
    "name": "fanqie_batch_fetch_filtered",
    "args": {"ranking": "爆款榜", "target_count": 10},
})
assert_eq(
    "T1 OpenAI top-level dict",
    tc,
    {"name": "fanqie_batch_fetch_filtered", "args": {"ranking": "爆款榜", "target_count": 10}},
)
assert tc.id == "call_abc123"


# ── T2: 部分小厂只给 function.{name, arguments}，arguments 是 JSON string ──
tc = _normalize_tool_call({
    "function": {
        "name": "fanqie_batch_enqueue_filtered",
        "arguments": '{"ranking":"阅读榜","target_count":5}',
    }
})
assert_eq(
    "T2 function-name-only",
    tc,
    {"name": "fanqie_batch_enqueue_filtered", "args": {"ranking": "阅读榜", "target_count": 5}},
)


# ── T3: arguments 是 JSON string 但带空格/换行 ──
tc = _normalize_tool_call({
    "function": {
        "name": "douyin_upload_video",
        "arguments": '{\n  "video_path": "data/x.mp4",\n  "title": "测试"\n}',
    }
})
assert_eq(
    "T3 JSON-string with whitespace",
    tc,
    {"name": "douyin_upload_video", "args": {"video_path": "data/x.mp4", "title": "测试"}},
)


# ── T4: Ollama langchain-ollama 返回 object 形态 ──
class FakeFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments

class FakeToolCall:
    def __init__(self, name, arguments, tc_id="ollama_id_001"):
        self.function = FakeFunction(name, arguments)
        self.id = tc_id

tc = _normalize_tool_call(FakeToolCall("auto_reply", '{"video_id": "v123", "reply": "好"}'))
assert_eq(
    "T4 Ollama object",
    tc,
    {"name": "auto_reply", "args": {"video_id": "v123", "reply": "好"}},
)


# ── T5: 损坏的 JSON 字符串 ──
tc = _normalize_tool_call({
    "function": {"name": "broken_skill", "arguments": '{"this is not json'}
})
assert tc is None, f"T5 broken JSON 应返回 None，但得到 {tc}"
print("  ✅ T5 损坏 JSON 返回 None（不会让上游崩）")


# ── T6: 缺字段（无 name） ──
tc = _normalize_tool_call({"function": {"arguments": "{}"}})
assert tc is None, f"T6 缺 name 应返回 None，但得到 {tc}"
print("  ✅ T6 缺 name 返回 None")


# ── T7: arguments 是 None ──
tc = _normalize_tool_call({"function": {"name": "fanqie_batch_run", "arguments": None}})
assert_eq(
    "T7 arguments=None 视为空 dict",
    tc,
    {"name": "fanqie_batch_run", "args": {}},
)


# ── T8: arguments 是 list 而非 string/dict ──
tc = _normalize_tool_call({"function": {"name": "weird_skill", "arguments": [1, 2, 3]}})
assert_eq(
    "T8 arguments=list 视为空 dict",
    tc,
    {"name": "weird_skill", "args": {}},
)


# ── T9: 批量归一化 ──
all_calls = _normalize_tool_calls([
    {"function": {"name": "a", "arguments": '{"x": 1}'}},
    {"function": {"name": "b", "arguments": "not-json{"}},
    FakeToolCall("c", '{"y": 2}'),
    None,                                                # None → 跳过
    {"function": {}},                                    # 缺 name → 跳过
])
assert len(all_calls) == 2, f"应保留 2 条 (a, c)，但得到 {len(all_calls)}: {all_calls}"
names = {tc.name for tc in all_calls}
assert names == {"a", "c"}, f"应该只保留 a, c，但得到 {names}"
print(f"  ✅ T9 批量归一化：5 条输入 → 2 条（丢弃损坏/None/缺字段）")


# ── T10: None 输入 ──
tc = _normalize_tool_call(None)
assert tc is None
tc = _normalize_tool_call({})
assert tc is None
print("  ✅ T10 None / 空 dict 安全返回 None")


# ── 2. 端到端：chat_completion_with_tools 走真实 provider ─────────
if __name__ == "__main__":
    # 真实供应商调用是手工 smoke test，不应在离线 pytest 收集阶段执行。
    print("\n=== 端到端 smoke test（真实 MiniMax API）===")
    from src.shared.llm_client import llm_client

    resp = llm_client.chat_completion_with_tools(
        messages=[
            {"role": "system", "content": "你是番茄 AI 助手。"},
            {"role": "user", "content": "抓 5 本爆款榜的书，直接抓取。"},
        ],
        tools=[
            {"type": "function", "function": {
                "name": "fanqie_batch_fetch_filtered",
                "description": "按筛选条件扫榜入库",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ranking": {"type": "string", "enum": ["爆款榜", "阅读榜", "潜力榜"]},
                        "target_count": {"type": "integer", "minimum": 1},
                    },
                    "required": ["ranking", "target_count"],
                },
            }}
        ],
        caller="test_normalize",
        temperature=0.0,
    )
    print(f"  content 长度: {len(resp.content)} (含 think 块)")
    print(f"  content 前 80: {resp.content[:80]!r}")
    print(f"  tool_calls 数: {len(resp.tool_calls)}")
    if resp.tool_calls:
        tc = resp.tool_calls[0]
        print(f"  first tc.name: {tc.name}")
        print(f"  first tc.args: {tc.args}")
        print(f"  first tc.args 类型: {type(tc.args).__name__}")
        assert isinstance(tc.args, dict), f"args 类型错：{type(tc.args)}"
        print("  ✅ T11 MiniMax args 是 dict，不是 JSON string")
    else:
        print("  ⚠️ MiniMax 这次没返 tool_calls（退化到 plan-block / chat-only）")

    print("\n所有 _normalize_tool_call 测试通过 ✅")
