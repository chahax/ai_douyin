---
doc_status: current
doc_category: design
last_reviewed: 2026-07-01
model_usage: AI 助手改造方案（v0.2）。聚焦 P0/P1/P2 三件该做的事；v0.1 LangGraph 全量重构计划驳回。
---

# AI 助手改造：三件该做的事 + 一件不该做的（LangGraph）

> 状态：**v0.2** · 2026-07-01 · 更新于 critique 之后
>
> 修定：v0.1 提议"全量 LangGraph 重构（2 周）"——已被评审驳回，本版本聚焦于 **3 天能改完的 P0/P1/P2**。

---

## TL;DR

**不做**：全量用 LangGraph 重构 AI 助手控制流（14 天 ROI 太低；老 agent.py 质量尚可；portfolio 价值稀释）。

**做**：3 件独立、可回滚的小改进——

| | 改了什么 | 解决了什么 | 时间 |
|---|---|---|---|
| **P0** | LLM 用 `bind_tools` 走 native tool calling，删 ```plan``` 解析 + fallback | LLM 不按格式输出（这次踩的） | 1-2 天 |
| **P1** | streaming 输出 + `st.write_stream` | AI 助手一次返回 159 字，不流畅 | 1 天 |
| **P2** | `registry.call()` 失败自动 retry 一次（**限定瞬时错误**） | 长任务失败没有兜底 | 半天 |

合计 **3-4 天**——改善 80% 的用户能感知的痛点，**不破坏现有架构**。

### 0.1 P0 / P2 的两个坑（先看再写）

**P0 跨供应商格式差**：v0.1 §5.2 挖过这个——不同供应商 `tool_calls[].function.arguments` shape 不一样（MiniMax 有时给 JSON string，Ollama 给 object，DeepSeek/OpenAI 给 dict）。**`_normalize_tool_call()` 必须放在 `llm_client.py` 集中实现**，不能扔给各 provider 自己搞；否则每接一个新供应商就改一遍代码。

**P2 retry 范围**：v0.2 之前一句"失败时让 LLM 重新生成 kwargs"是错的——参数本身错（比如用户传的书名拼错了），重新调 LLM 也修不了。**retry 只做同参数重试，针对瞬时错误（超时、5xx、`connection reset`、`请重试`模式）。参数级错误（NotFound、validation_error、ParamError）一律不重试**，直接走 failure 路径给用户。

---

## 1. 病理（来自这次 debug）

不是修 bug 的清单，是**理解为什么这么改**。

### 1.1 用户体验层面

| Bug | 现象 | 证据 |
|---|---|---|
| LLM 不按 ```plan``` 格式输出 | user 说"抓 10 本" 但没 plan 落库 | 加 `_parse_plan_from_text_fallback` 兜底 |
| WebSocket 断 | chat_input 提交后无响应 | streamlit stderr 多次 `DetachedInstanceError` |
| Skill 失败被吞 | UI 只看到 `[code] xxx`，看不到 traceback | `registry.call()` 内部一锅 catch |
| 长任务阻塞 | streamlit 5-10 分钟 spinner 不转 | `fetch_filtered` 用 `batch_fetch_sync` 同步阻塞 |
| Pending plan 卡 DB | 上一会话失败残留 | 手动清脏才能继续 |

### 1.2 跟 Claude Code 差什么

不是全部要补。**只关心影响用户体验的部分**：

| Claude Code 优势 | 当前痛点相关性 | 优先级 |
|---|---|---|
| Native tool calling + JSON schema | LLM 不按格式 → **P0 解决** | 高 |
| Streaming 输出（SSE） | AI 助手一次返 159 字 → **P1 解决** | 中 |
| 错误重试 + 退避 | registry.call 一次失败就放弃 → **P2 解决** | 中 |
| 多步迭代（连续 tool_use） | 用户说"加 5 本" 之后再说"换成 10 本"——目前断流 | 低（不修） |
| 子 Agent | 暂时不需要 | 跳过 |
| Checkpoint / Trace | 调试靠翻 streamlit stderr | 低（**观测先于建设**） |

---

## 2. P0：Native tool calling（**今天最重要的一步**）

### 2.1 改动

| 文件 | 改什么 |
|---|---|
| `src/shared/llm_client.py` | 加 `chat_completion_with_tools()` + **`_normalize_tool_call()` 集中在这里**（不分散到 provider） |
| `src/shared/llm_providers/openai_compatible_provider.py` | `chat_with_tools()`：往 OpenAI 兼容 API 透传 `tools` 参数 |
| `src/agent/agent.py` | `_parse_plan_from_response` 和 `_parse_plan_from_text_fallback` **整段删掉**；改成解析 `_normalize_tool_call()` 的输出 |
| `src/agent/registry.py` | 加 `_registry_to_tools_schema()` helper：把 32 个 Skill 包成 OpenAI schema |
| `tests/test_tool_call_normalize.py` | **必加**——每接一个新供应商跑一次 |

### 2.2 关键代码

```python
# llm_client.py — 集中归一化
def _normalize_tool_call(raw_tc) -> dict | None:
    """跨供应商 tool_call 字段归一化。

    已知差异：
      OpenAI / DeepSeek / MiniMax：dict 形态，但 `arguments` 偶尔是 JSON string
      Ollama（含 langchain-ollama）：object 形态，走 `.function.name` `.function.arguments`
      失败 → None（让上层走「LLM 没生成 tool_call」分支）
    """
    if raw_tc is None:
        return None
    if isinstance(raw_tc, dict):
        # 1) 取 name
        name = raw_tc.get("name") or (raw_tc.get("function") or {}).get("name")
        # 2) 取 args——可能是 dict 也可能是 JSON string
        raw_args = raw_tc.get("args") or (raw_tc.get("function") or {}).get("arguments")
        tc_id = raw_tc.get("id")
    elif hasattr(raw_tc, "function"):  # LangChain Object
        name = raw_tc.function.name
        raw_args = raw_tc.function.arguments
        tc_id = getattr(raw_tc, "id", None)
    else:
        return None
    if not name:
        return None
    # 3) 规范化 args
    if isinstance(raw_args, str):
        try:
            args = json.loads(raw_args)
        except json.JSONDecodeError:
            return None  # JSON 损坏让上层走错误分支
    elif isinstance(raw_args, dict):
        args = raw_args
    else:
        args = {}
    return {"name": name, "args": args, "id": tc_id}


@dataclass
class ToolCall:
    name: str
    args: dict
    id: str | None = None

    @classmethod
    def from_raw(cls, raw_tc) -> "ToolCall | None":
        d = _normalize_tool_call(raw_tc)
        return cls(**d) if d else None


class ChatResponse:
    def __init__(self, content: str, tool_calls: list[ToolCall]):
        self.content = content
        self.tool_calls = tool_calls


def chat_completion_with_tools(
    messages, tools: list[dict], caller: str = "unknown",
    temperature: float = 0.3,
) -> ChatResponse:
    """Provider 自己管 raw fetch；归一化在 llm_client 这一层。"""
    raw_resp = self.provider.chat_with_tools(messages, tools, temperature)
    raw_calls = raw_resp.get("tool_calls") or []
    normalized = [ToolCall.from_raw(c) for c in raw_calls]
    normalized = [c for c in normalized if c is not None]   # 丢弃 None
    return ChatResponse(content=raw_resp.get("content", ""), tool_calls=normalized)
```

```python
# agent.py — 替换 _parse_plan*
resp = llm_client.chat_completion_with_tools(
    messages, tools=_registry_to_tools_schema(),
    caller="agent_chat", temperature=0.3,
)
if resp.tool_calls:
    plan = ExecutionPlan.from_tool_call(resp.tool_calls[0])  # 单一调用入口
    mm.save_pending_plan(sess.id, plan.to_dict())
    return AgentResponse(text=plan.summary_preview, pending_plan=plan, needs_confirmation=True)
return AgentResponse(text=resp.content)  # LLM 没生成 tool_call ⇒ 闲聊
```

### 2.3 风险（实现 P0 时盯紧）

| 风险 | 实现时怎么测 |
|---|---|
| MiniMax 把 `arguments` 当 JSON string 而不是 dict | `tests/test_tool_call_normalize.py` 第一测就是：模拟 MiniMax 形状 输入 |
| Ollama 返回 object 形态（`raw.function.name`） | 第二测：mock 一段 LangChain object |
| tool_calls 字段完全缺失（provider 偷字段名） | 第三测：`raw_resp = {}` 不能崩 |
| LLM 选了 skill 但 args 漏字段 | Pydantic schema 校验——schema 收口在 `tools=[...]` 里 |
| LLM 选了不存在的 skill | registry.call 会 NotFound，**不 retry，直接给用户报错** |

### 2.4 不做完整 LangGraph 重构的原因（驳回 v0.1）

| 原因 | 解读 |
|---|---|
| ROI 太低 | 14 天改的 80% 用户看不出 |
| 不破坏现有 | Skill 桥接 32 个 × 7 个坑 = 隐藏工作量（async/Optional/Pydantic/$ref/...） |
| Streamlit × LangGraph interrupt 不是天然组合 | interrupt 假设 server 长跑，Streamlit 是 rerun 模型——胶水层本身要写 + 测 |
| portfolio 价值稀释 | 项目已有专用 LangGraph demo，再上一个 LangGraph 版本反而稀释定位 |
| v0.1 文档里的 `_derive_from_signature` 假设过强、async 处理不到、Json string 兼容性都低估了 | 实际工作量比 v0.1 估算翻倍 |

---

## 3. P1：Streaming 输出

### 3.1 改动

| 文件 | 改什么 |
|---|---|
| `src/shared/llm_client.py` | 加 `chat_completion_stream()`：yield token chunks |
| `src/agent/agent.py` | `chat()` 加 `stream=False` 参数；`chat_stream()` 走 aiter |
| `src/web/app.py` | `page_chat()` 用 `st.write_stream()` 把 token 流注入气泡 |

### 3.2 streamlit 端代码

```python
def page_chat():
    # ...
    user_input = st.chat_input("...")
    if user_input:
        with st.chat_message("user"):
            st.markdown(user_input)
        with st.chat_message("assistant"):
            # 流式注入
            response = st.write_stream(_stream_agent(user_input))
        # 然后处理 response.plan / needs_confirmation
```

---

## 4. P2：自动 retry（**限定**瞬时错误）

### 4.1 改动

| 文件 | 改什么 |
|---|---|
| `src/agent/registry.py` | `call(skill, kwargs, retries=1, transient_only=True)`：**同参数**重试一次 |
| `src/agent/agent.py` | 不改 retry 逻辑——只在用户**手动改参数**或**换 skill** 时重跑 LLM |

### 4.2 关键设计原则（避免 LLM 重生成的耦合）

**retry 只覆盖瞬时错误**：
- HTTP 5xx
- Connection reset / 客户端断开
- Service Unavailable
- 错误文本包含 "请重试" / "try again" / "temporarily unavailable"

**retry 不覆盖**：
- `NotFound`（资源不存在）
- `validation_error`（参数 schema 不对）
- `PermissionDenied` / Auth 错
- `ValueError`（用户传的参数本身错——比如书名拼错）
- `user_cancel`

**实现区分**：

```python
def _is_transient_error(error_code: str, error_msg: str) -> bool:
    """瞬时错误判定。
    
    保守原则：宁可漏重试，不要误重试一个永久性错误。
    """
    TRANSIENT_CODES = {"network", "timeout", "service_unavailable", "rate_limit"}
    TRANSIENT_PATTERNS = ("connection reset", "temporarily unavailable", "请重试", "try again")
    if error_code in TRANSIENT_CODES:
        return True
    msg_lower = (error_msg or "").lower()
    return any(p.lower() in msg_lower for p in TRANSIENT_PATTERNS)


def call(skill, kwargs, retries=1):
    last_err = None
    for attempt in range(retries + 1):
        try:
            result = self._invoke_skill_once(skill, kwargs)
        except Exception as exc:
            last_err = f"{type(exc).__name__}: {exc}"
            if attempt < retries and _is_transient_error("network", last_err):
                time.sleep(2 ** attempt)  # 2 秒指数退避
                continue
            break
        # 业务错误：必须明确判断
        if not result.get("success") and _is_transient_error(
            result.get("code", ""), result.get("message", "")
        ):
            time.sleep(2 ** attempt)
            continue
        return result
    return SkillResult.err("transient_retries_exceeded", last_err or "Unknown").to_dict()
```

### 4.3 边界

- **只 retry 1 次**：避免雪崩
- **退避**：指数退避 (`2^attempt` 秒)，不要固定 sleep 让 LLM 上游 throttle
- **不 retry user-cancel**：取消就是取消
- **不 retry 业务错误**：NotFound / ValidationError / ValueError 一律不重试，**给用户完整错误让他手动改**
- **fail-loud**：超过 retry 仍失败 → 把 traceback 完整 message 推给 AI 助手，让 LLM 总结给用户

---

## 5. 先观测，再决定要不要做别的

朗格图 critique 之后另一个关键洞察：**别在没有数据的时候做架构优化**。

短期应该装的是 `langsmith` 或 `langfuse`（甚至直接打 loguru metric），观测这些：

| 指标 | 怎么测 | 看什么 |
|---|---|---|
| P95 延迟 | loguru 计时 + percentile | 闲聊 vs Skill 路径分桶 |
| fallback 解析触发率 | 在 `_parse_plan_from_text_fallback` 里 `logger.warning` 计数 | LLM 是否常不听话 |
| registry.call 失败率 | result.success 记 log | 哪个 Skill / 哪个 kwargs 常失败 |
| pending_plan 卡 DB 频率 | `get_pending_plan not None AND status = archived` 计数 | 是否需要清脏机制 |
| 用户手动重复输入 | 流图 ↔ "用户重发" 时间差 | 是否真卡顿 |

跑一周后看数据。如果上面 3 个 P0/P1/P2 没覆盖的高频问题出现，再判断是否升级。

---

## 6. 文件级改动总图

```
src/shared/llm_client.py
  + chat_completion_with_tools()       # P0
  + chat_completion_stream()           # P1

src/agent/agent.py
  - _parse_plan_from_response()        # P0
  - _parse_plan_from_text_fallback()   # P0
  + chat(stream=False/True)            # P1
  + skill_executor retry_once          # P2

src/agent/registry.py
  + call() retries=1 默认              # P2
  + description 自动 introspect 或人工    # P0

src/web/app.py
  ~ page_chat() 用 st.write_stream       # P1

src/agent/graph/                        # ← 不做（驳回 v0.1）
```

---

## 7. 验收清单（4 天后）

- [ ] P0：LLM 在 `ranking=中文/枚举` 上 tool_call args 正确
- [ ] P0：删 `_parse_plan_from_response` + `_parse_plan_from_text_fallback`
- [ ] P1：用户能看到气泡逐字展开（不是一次返 159 字）
- [ ] P2：registry.call 失败重试一次仍失败 → 给用户友好错误（包含 traceback hint）
- [ ] 老 `Agent.chat()` 接口 compat（fallback 直接抛 `NotImplementedError` 后才允许重构）
- [ ] 没改 `src/agent/graph/` 这条线（明确驳回）

---

## 8. 附录：完整 LangGraph 重构蓝图（**只作为 future reference，不立刻实施**）

> v0.1 文档的代码草图、技术选型、1.x vs 0.2.x API、跨供应商 tool_call 归一化、interrupt 返回值——这些**都对**，但合起来的工作量超出 4 天 deadline 太多。
>
> 留作以后若真的需要做大规模重构（**别的项目**或**真正的 production-grade 改造**）时翻出来当起点。
>
> 已验证信息：
> - langgraph 1.1.0 + langgraph-checkpoint 4.0.1（`pip show langgraph`）
> - `langgraph.checkpoint.sqlite` 在 1.x 不存在；需要 `pip install langgraph-checkpoint-sqlite`
> - `interrupt(payload)` 1.x 直接返回 resume 的原值（不再是 `{value:...}` 包装）
> - `ChatOpenAI(bind_tools(tools))` 让 LLM 返回 `tool_calls`，跨 OpenAI/DeepSeek/MiniMax 格式略不同——`_normalize_tool_call()` helper 必备
> - Streamlit × LangGraph 的 `interrupt` 拼接需要 thread_id + SqliteSaver 跨 rerun，否则 state 丢失

更长的未来重构 plan（包括状态图、9 个节点职责、`SqliteSaver` 持久化、`Command(resume=...)` 流、`astream_events` 流式 token 输出）参考 [git history: LANGGRAPH_REFACTOR_PLAN.md v0.1](https://github.com/anthropics/claude-code-internal-showcase) 或本仓库 git log 中该文档 v0.1 提交。
