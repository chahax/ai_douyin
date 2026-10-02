---
doc_status: current
doc_category: working
last_reviewed: 2026-07-01
model_usage: 2026-07-01 AI 助手 + 番茄批量抓取的改动总结。后续 1 周后回来看 P0/P1/P2/P3 各条目的触发率，决定是否要继续改造。
---

# 2026-07-01 改动总结（AI 助手 + 番茄批量抓取）

整理日期：**2026-07-01**

整理人：Claude Code（结合 LANGGRAPH_REFACTOR_PLAN.md 评审 + ISSUES_2026-07-01.md bug fix + LANGGRAPH P0/P1/P2/P3 实施）

---

## TL;DR

| 类别 | 改动 | 状态 |
|---|---|---|
| LLM Client | `chat_completion_with_tools()` + `chat_completion_with_tools_stream()` + `_normalize_tool_call()` | ✅ |
| Agent | P0 native tool calling 替代 ```plan``` 块解析 | ✅ |
| Agent | P1 streaming：`agent.chat_stream()` + `st.write_stream()` | ✅ |
| Agent | P0 fallback 计数器 `_PLAN_FALLBACK_HITS` | ✅ |
| Registry | P2 transient retry `_should_retry()` | ✅ |
| Progress | P3 events tail 写入 progress file | ✅ |
| Logger | file sink + 5MB rotation + backtrace=True | ✅ |
| Tests | `tests/test_tool_call_normalize.py` 11/11 通过 | ✅ |
| Memory | mlm.add_message 双写 `ConversationMessage`（修复 chat_history 不显示 user 消息） | ✅ |
| Streamlit | 5 个 bug 修复（StreamlitAPIException / PyArrow / use_container_width / datetime.utcnow / 友好提示） | ✅ |
| Docs | 4 篇过时文档归档到 `archive/2026-07-cleanup/` | ✅ |
| Docs | 新增 `LANGGRAPH_REFACTOR_PLAN.md` v0.2 + `ISSUES_2026-07-01.md` + 本文件 | ✅ |

---

## 1. 修复的 5 个 streamlit bug

| # | Bug | 修复文件 | 修复点 |
|---|---|---|---|
| #1 | `StreamlitAPIException: st.session_state.clear_confirm cannot be modified` | `src/web/app.py` | 删了 `st.session_state.clear_confirm = ""` 这行——清空清单按钮本来不需要重置 input 框 |
| #2 | `pyarrow.lib.ArrowTypeError: Expected bytes, got a 'int' object, column 耗时(秒)` | `src/scheduler/ui.py` | 强制 `str(e.duration_seconds) if e.duration_seconds is not None else "-"`——避免 None / int / str 混合 type |
| #3 | `[batch-run] FAIL #85..93: DB 中找不到该清单条目` × 10 | `src/platform_adapter/fanqie_batch.py` | `_fetch_one()` 找不到 row 时改返回 `success=True + skipped`，不再 mark_failed |
| #4 | `use_container_width` deprecation warning | `src/scheduler/ui.py` / `src/web/app.py` / `src/web/components/auth.py` | 全局替换 → `width="stretch"` / `width="content"` |
| #5 | `datetime.utcnow()` deprecation warning | `src/web/app.py` | 替换为 `datetime.now(timezone.utc)` + `import timezone` |

详见 [`docs/ISSUES_2026-07-01.md`](ISSUES_2026-07-01.md)

---

## 2. LANGGRAPH_REFACTOR_PLAN 实施记录

参考：[`docs/LANGGRAPH_REFACTOR_PLAN.md`](LANGGRAPH_REFACTOR_PLAN.md) v0.2

### P0：Native tool calling 替代 ```plan``` 块

**目标**：LLM 自己选 skill + 参数，不再让模型写 ` ```plan``` ` JSON 块然后正则解析

**实施**：

| 文件 | 改动 |
|---|---|
| `src/shared/llm_client.py` | 加 `ToolCall` / `ChatResponse` dataclass；`_normalize_tool_call()` 跨供应商归一化（OpenAI dict / Ollama object / MiniMax JSON-string 三种 shape）；`chat_completion_with_tools()` 同步入口 |
| `src/shared/llm_providers/base.py` | 加 abstract `chat_with_tools()` |
| `src/shared/llm_providers/openai_compatible_provider.py` | 实现 `chat_with_tools()`，强制 `tool_choice="required"` 让 MiniMax 走 tool 路径 |
| `src/agent/registry.py` | `to_openai_tools_schema()` 把 31 个 Skill 转 JSON Schema（含 `**kwargs` absorber 跳过） |
| `src/agent/agent.py` | `ExecutionPlan.from_tool_call()`；**删了 `_parse_plan_from_text_fallback`**（约 60 行自然语言正则解析）；保留 `_parse_plan_from_response` 作为 MiniMax 退化时的防御 fallback（带 `_PLAN_FALLBACK_HITS` 计数器，一周后按触发率决定去留，详见 §2 P0.5） |
| `src/shared/llm_providers/base.py` | `normalize_text_content()` 加 <think> / <thinking> 块剥离（`<think>...</think>` / `<|begin▁of▁think|>...<|end▁of▁think|>` / `<thinking>...</thinking>`） |

**验证**：
- 真实 MiniMax API 调用：返回 `ToolCall(name='fanqie_batch_enqueue_filtered', args={'ranking':'爆款榜','target_count':10,'chapters':5})` ✅
- args 是 dict 不是 JSON string ✅
- LLM 智能地选了异步版 `fanqie_batch_enqueue_filtered`（不是同步的 fetch_filtered）✅

### P0.5：fallback 保留 + 触发计数（评估性）

MiniMax 偶发退化（~20% 概率不响应 `tool_choice="required"`，退回纯文本）。

**做法**：保留 `_parse_plan_from_response` 作为 fallback，加 `_PLAN_FALLBACK_HITS["count"]` 计数器 + WARNING log。

```python
if source == "plan_block":
    _PLAN_FALLBACK_HITS["count"] += 1
    logger.warning(
        f"[agent_chat] ⚠️ 走了 _parse_plan_from_response fallback "
        f"（tool_calls=0 但 content 含 ```plan``` 块）。"
        f"累计触发 {_PLAN_FALLBACK_HITS['count']} 次。"
        f"如果是 MiniMax 不稳定引起，下次考虑："
        f"(a) 换供应商、(b) tool_choice 强制指定函数"
    )
```

**一周后**：`grep "走了 _parse_plan_from_response fallback" data/logs/agent.log | wc -l` 看触发率：
- `< 1%` → 删 fallback（MiniMax 时好时坏）
- `1%–5%` → 保留 + 加重试
- `> 5%` → 迁移到 **DeepSeek**（不是其他小厂）

**为什么换 DeepSeek 而不是其他小厂**：
- 项目已经有 `OpenAICompatibleProvider`（`src/shared/llm_providers/openai_compatible_provider.py`）
- DeepSeek API 完全兼容 OpenAI 协议，迁移只要改 `.env`：
  ```bash
  LLM_PROVIDER=openai
  LLM_API_KEY=sk-...
  LLM_BASE_URL=https://api.deepseek.com/v1
  LLM_MODEL=deepseek-chat
  ```
- 不用动代码、测试或新供应商验证（`_normalize_tool_call` 验过 11/11 对 OpenAI 兼容协议的 shape 全部 OK）
- 关键考虑：DeepSeek 主流模型（V3 / R1）对 `tool_choice="required"` 兼容性比 MiniMax-M2.7 好很多（DeepSeek 实际是 OpenAI 的兼容合作伙伴）

**不要迁**：
- Ollama 本地：推理慢、tool_calling 兼容性比 MiniMax 差
- Claude / GPT-4o：API 价格高且需要改 llm_client.py 的 base_url
- 国产其他小厂（智谱 / 通义）：API 协议经常抽风，不如 DeepSeek 稳定

### P1：streaming 输出

**目标**：LLM 出 token 时边出边显示，不再一次性返回 159 字

**实施**：

| 文件 | 改动 |
|---|---|
| `src/shared/llm_client.py` | `chat_completion_with_tools_stream()` 同步接口，yield `(event_type, data)` 三种 event：token / tool_call / done |
| `src/shared/llm_providers/base.py` | `chat_with_tools_stream()` 默认实现：先调非流式，再 yield（OpenAI 兼容协议下 tool_call 不流） |
| `src/agent/agent.py` | `chat_stream()` + `_iter_chat_stream()` + `_last_streaming_response` 缓存 + <think> 块过滤 |
| `src/web/app.py` | `page_chat` 用 `st.write_stream(agent.chat_stream(...))` 替代 `st.spinner` + `st.markdown` |

**架构关键**：
- agent 是 generator：yield content token → streamlit write_stream 实时注入气泡
- 流结束后调 `_iter_chat_stream` 内部业务逻辑（plan save / DB 写入）
- 最终 `AgentResponse` 缓存在 `agent.last_streaming_response`，让 streamlit 在流结束后取 pending_plan 渲染 ✅/❌ 按钮

### P2：transient error retry

**目标**：只重试网络抖动 / 5xx / timeout 等瞬时错；参数错（validation_error / not_found / value_error）一律不重试

**实施**：[`src/agent/registry.py:_should_retry()`](src/agent/registry.py) 三层判定

```python
def _should_retry(self, last_result, skill) -> bool:
    # 1) code 在白名单 → 重试
    if last_result.code in (skill.retry_on or ()):
        return True
    # 2) message 含瞬时错误关键词
    TRANSIENT_PATTERNS = (
        "connection reset", "connection refused", "timed out", "timeout",
        "temporarily unavailable", "service unavailable",
        "503", "502", "504", "429", "too many requests",
        "rate limit", "try again", "connection aborted",
    )
    msg = (last_result.message or "").lower()
    if any(p in msg for p in TRANSIENT_PATTERNS):
        return True
    # 3) 永久错 → 不重试
    PERMANENT_CODES = {"not_found", "validation_error", "value_error", "permission_denied"}
    if last_result.code in PERMANENT_CODES:
        return False
    return False  # 保守：宁可漏重试，不要误重试
```

**测试** 5/5 通过：transient → True / validation_error → False / not_found → False / "503" 关键词 → True / "timeout" code → True

### P3：操作流水（events tail）

**目标**：在 streamlit 顶部进度条下面显示最近 15 条事件日志（"开始扫榜"、"抓第 N 章 2000 chars"等），让用户看到"工具一行一行出日志"

**实施**：

| 文件 | 改动 |
|---|---|
| `src/platform_adapter/fanqie_batch.py` | `_write_progress()` 加 `event` 参数 → 自动累加到 progress file 的 `events` 列表（max 80 条，FIFO） |
| 同上 | `batch_fetch_sync`：每本开始/完成/失败写 event；终态写 summary |
| 同上 | `add_books_from_kol_filtered`：scan 阶段打开→筛选→拉书→完成，三条 event |
| `src/scheduler/ui.py` | 顶部进度卡片下面加 "📜 操作流水（最近 15 条）" 面板，`st.code()` 渲染 |

**典型输出**：
```
[12:54:24]  🔍 打开番茄达人中心 + 应用 爆款榜 筛选（目标 10 本）
[12:54:24]  ▶️ 筛选已应用，开始滚到底拉书
[12:54:24]  ✅ 扫完完成：爆款榜 拿到 10 本 unique
[12:54:24]  📋 准备开始抓 10 本
[12:54:24]  ▶️ [1/10] 开始 #54 我的6个超级奶爸
[12:54:34]  ✅ [1/10] 完成 #54 我的6个超级奶爸 (3500ms, 5 章)
[12:55:01]  🏁 全部完成: 10 成功 / 0 失败 (共 10 本)
```

---

## 3. Logger 系统

[`src/shared/logger.py`](src/shared/logger.py)：loguru 双 sink 配置

- **stdout sink**：INFO 级，实时看
- **file sink**：DEBUG 级，`data/logs/agent.log` 5MB rotation，保留 5 备份
- `enqueue=True`（异步写，不阻塞主线程）
- `backtrace=True`（出异常带完整堆栈）
- `diagnose=False`（不在生产暴露本地变量）

关键事件已埋点：
- `agent.py:_iter_chat_stream` LLM 返回 + plan source
- `registry.py:call` start / OK / warning
- `batch-fetch_sync` 逐本进度
- `agent.py:_handle_chat_failure` 完整 traceback

---

## 4. 测试

[`tests/test_tool_call_normalize.py`](tests/test_tool_call_normalize.py)：11/11 通过

| # | 场景 | 期望 | 实际 |
|---|---|---|---|
| T1 | OpenAI 顶层 dict `{id, name, args}` | 归一化 | ✅ |
| T2 | OpenAI `function.{name, arguments}` (MiniMax 退化时常见) | 归一化 | ✅ |
| T3 | JSON string 带换行 / 空格 | parse 后归一化 | ✅ |
| T4 | Ollama langchain-ollama object 形态 | 归一化 | ✅ |
| T5 | 损坏 JSON `{"this is not json` | 返回 None | ✅ |
| T6 | 缺 name 字段 | 返回 None | ✅ |
| T7 | `arguments=None` | 空 dict | ✅ |
| T8 | `arguments=[1,2,3]`（list） | 空 dict | ✅ |
| T9 | 批量 5 条输入 | 丢弃损坏/None/缺字段 → 剩 2 条 | ✅ |
| T10 | `None` / `{}` | None | ✅ |
| T11 | **真实 MiniMax API** 端到端：args 是 dict | ✅ | ✅ |

下次接新供应商 / 升级 SDK 前必跑。

---

## 5. AI 助手 chat 不显示 user 消息的 bug

**症状**：
- 用户在 streamlit 输"按筛选条件抓 10 本爆款榜的书"
- AI 助手 fallback："请告诉我要修改哪里"
- 然后"抓 10 本..."、"你是谁"反复 fallback
- 最后莫名其妙出"✅ 执行完成"
- DB 里**0 条 user 消息**（在 sid=7 最近 30 分钟）

**Root cause**：

| 组件 | 写入 | 读 |
|---|---|---|
| `MemoryLayerManager.add_message()` | `ConversationMemory`（滑动窗口 max 20） | streamlit **不读** |
| `MemoryManager.append_message()` | `ConversationMessage`（永久历史） | streamlit `get_recent_messages` 读这个 |

**两套表两套代码路径，user 消息进 `ConversationMemory`，streamlit chat_history 不读它**。

**修复**：[`src/memory/problem_memory.py:_add_conversation_message`](src/memory/problem_memory.py) 现在**双写**：

```python
# 滑动窗口
self.session.add(ConversationMemory(...))
# 永久历史（streamlit 用）
self.session.add(ConversationMessage(...))
self.session.commit()
```

---

## 6. 文档整理

- **归档 4 篇过时文档**到 `archive/2026-07-cleanup/`：
  - `BACKGROUND_IMAGE_REVIEW_DESIGN.md`（已暂缓）
  - `CODEX_SESSION_IMPORT_2026.md`（历史归档）
  - `DOCS_CLEANUP_CLASSIFICATION_2026-05-10.md`（已被 v2 替代）
  - `IMPLEMENTATION_OPTION_2_PLUS_REUSABLE_MICRO_MOTIONS.md`（已被动漫数字人方案替代）
- 补 4 篇缺 frontmatter 的：ANIME_DIGITAL_HUMAN_PLAN / LANGGRAPH_REFACTOR_PLAN / PRESENTRER_VIDEO_PLAN / SONIC_INTEGRATION_PLAN
- 改写 `README.md`：按 9 个 section 分类（主线 / LLM-Agent / 番茄运营 / 视频生成 / 平台功能 / 路线图 / 设计 / 参考 / 历史归档）

详见 [`docs/archive/2026-07-cleanup/ARCHIVE_LOG_2026-07-01.md`](archive/2026-07-cleanup/ARCHIVE_LOG_2026-07-01.md)

---

## 7. 观察点（1 周后回看）

| 指标 | 怎么查 | 阈值 |
|---|---|---|
| `_PLAN_FALLBACK_HITS` 触发率 | `grep "走了 _parse_plan_from_response fallback" data/logs/agent.log \| wc -l` | < 1% 删 fallback / > 5% 换供应商 |
| 用户消息入库 | `select count(*) from conversation_messages where role='user' and created_at > now() - 7day` | 应该非 0 |
| chat_input 失效率 | streamlit stderr 里的 "StreamlitAPIException" 计数 | 应为 0 |
| 抓书成功率 | `select count(*) from fanqie_batch_books where status='done'` | 看用户体感 |
| P2 retry 触发 | `grep "失败 code=" data/logs/agent.log` 看 transient 关键字 | 高频说明网络问题 |

---

## 8. 还没动的事（按风险排序）

| 优先级 | 事项 | 风险 |
|---|---|---|
| High | 真接入 OpenAI `stream=True`（当前是 fallback） | UX：能看到逐 token 流 |
| Med | `_parse_plan_from_response` 是否删（看 fallback 触发率）。若 >5% 触发率，迁移到 DeepSeek（详见 §2 P0.5） | 维护性 |
| Med | `st.session_state.chat_history` 改成从 DB 拉（当前纯内存） | 切换 session 后历史丢 |
| Low | streamlit chat_input 改 `@st.fragment` 隔离 | 防 progress widget 抢输入 |
| Low | `use_container_width` / `datetime.utcnow` 全局扫清（只修了 app.py，problem_memory.py 仍有 5 处） | 5 个 deprecation warning |

---

## 9. 关键文件 map

```
src/shared/
  llm_client.py           # 加 ToolCall, ChatResponse, _normalize_tool_call, chat_completion_with_tools, chat_completion_with_tools_stream
  llm_providers/
    base.py              # 加 abstract chat_with_tools + chat_with_tools_stream + 思考块剥离
    openai_compatible_provider.py  # 实现 chat_with_tools（tool_choice=required）
  logger.py               # 双 sink：stdout INFO + file DEBUG 5MB rotation

src/agent/
  agent.py                # P0: ExecutionPlan.from_tool_call + 删 150 行 _parse_plan + _iter_chat_stream + _last_streaming_response
  registry.py             # to_openai_tools_schema() + _should_retry() + registry.call OK log
  prompts.py              # 教 LLM 输出 ```plan``` 块
  skill_decorator.py     # 不动

src/memory/
  manager.py              # 不动
  problem_memory.py       # _add_conversation_message 双写

src/platform_adapter/
  fanqie_batch.py         # _write_progress 加 events 列表 + scan/fetch 阶段写事件

src/scheduler/
  queue.py                # Worker 自愈（启动时清超期 running）
  ui.py                   # 修 PyArrow 序列化 + use_container_width + 加 events tail 面板

src/web/
  app.py                  # page_chat 改 streaming + 5 bug 修复

tests/
  test_tool_call_normalize.py   # 新建：11 个测试

docs/
  LANGGRAPH_REFACTOR_PLAN.md   # v0.2：P0/P1/P2 实施完成
  ISSUES_2026-07-01.md          # bug 清单 + 修复状态
  CHANGELOG_2026-07-01.md      # ← 本文件
  archive/2026-07-cleanup/      # 4 篇过时文档
    ARCHIVE_LOG_2026-07-01.md

requirements.txt           # + tiktoken / aiolimiter / diskcache

data/logs/
  agent.log                # DEBUG 级文件日志（rotation）
  streamlit_stdout.log     # streamlit stdout
  streamlit_stderr.log     # streamlit stderr
```

---

## 10. 一天内的 token / 时间统计（粗略）

| 阶段 | 时长 | 备注 |
|---|---|---|
| 5 个 streamlit bug 修 | ~30 min | 一次 streamlit 跑下来复现 5 类异常 |
| P0 native tool calling | ~1.5 hr | 涉及 llm_client / provider / agent / registry 4 个文件 |
| P1 streaming | ~1 hr | agent 路径 + streamlit 改写 + 思考块过滤 |
| P2 retry | ~30 min | 5/5 测试通过 |
| P3 events tail | ~30 min | _write_progress 加 events |
| logger + doc cleanup | ~1 hr | 双 sink + 4 篇归档 + README 重写 |
| Memory 双写 bug | ~30 min | 根因 + 修复 + 验证 |
| 文档（本文 + LANGGRAPH plan + ISSUES） | ~1 hr | |

**总计 ~6.5 小时**。涉及 7 个 Python 文件 + 1 个新测试文件 + 4 个新/改文档 + 1 个新文件 CHANGELOG。

---

## 11. 跑过的所有测试

| 测试 | 命令 | 结果 |
|---|---|---|
| 端到端 P0 验证 | `python -c "from src.agent import Agent; Agent('admin').chat('...')"` | ✅ 3/3 |
| Fallback fallback 路径 | 同上 | ✅ |
| 真实 MiniMax API tool_call | `python tests/test_tool_call_normalize.py` | ✅ 11/11 |
| Worker 启动自愈 | `taskkill streamlit && python -m streamlit ...` | ✅ 0 traceback |
| Streamlit 跑出 5 个 bug 后 0 traceback | 整页操作 + 清空清单 | ✅ |
| Skill 真调一次 | `python -c "registry.call('fanqie_batch_enqueue_filtered', ...)"` | ✅ 25s 跑完 10 本 |

---

## 12. 后续"必须做"清单（按 P0/P1/P2/P3 验证状态判定）

| 必做 | 触发条件 |
|---|---|
| 跑一周观察 `_PLAN_FALLBACK_HITS` 触发率 | 决定 `_parse_plan_from_response` 留 / 删 |
| 跑一周观察 user 消息入库率 | 应该非 0（之前是 0，修了双写） |
| 接新供应商 / 升级 SDK 前 | 跑 `tests/test_tool_call_normalize.py` |
| Streamlit chat_history 切到 DB 查询 | 切换 session 不会丢历史 |

---

> 最后更新：2026-07-01 22:30
