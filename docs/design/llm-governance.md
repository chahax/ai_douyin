---
doc_status: planning
doc_category: design
last_reviewed: 2026-06-28
parent_doc: docs/IMPROVEMENT_ROADMAP.md
implements: I-4
estimated_effort: 2d
---

> 文档状态：设计文档，待评审。

# I-4 · LLM 成本与限流治理 — 设计文档

## 一、目标

让 LLM 调用从"黑盒"变成"可观测、可限制、可缓存"：
- **每次调用都有 token 计量 + 成本估算 + 耗时**，落库可查
- **突发 QPS 被限流**，保护 API 配额不被打爆
- **相同输入复用结果**，省钱省时

与 V4（presenter 数字人）解耦 —— 本改进不触碰 presenter 路径，只治理 LLM 调用。

## 二、现状

```python
# src/shared/llm_client.py:64
def chat_completion(self, messages, temperature=0.7, json_mode=False):
    # 直接调用 provider，无 token 计量 / 无成本核算 / 无限流 / 无缓存
```

**问题**：
- 跑 V4 pipeline 时 LLM 调用次数无法统计（场景规划、对话生成、tag 生成等）
- 跑 `run_dialogue_generation(use_rag=True)` 时如果 prompt 错误导致循环，可能 1 小时调 1000+ 次
- 相同 prompt 重跑 pipeline 会重复扣费
- 跨进程 / 跨任务无 QPS 保护

## 三、方案（4 个组件）

### 3.1 Token 计量 + 成本估算

**模块**：[src/shared/token_counter.py](src/shared/token_counter.py)（新增）

```python
import tiktoken

# 模型 → encoding 缓存（启动时构建）
_ENCODINGS: dict[str, tiktoken.Encoding] = {}

def count_tokens(model: str, text: str) -> int:
    """按模型族选 encoding：
       - OpenAI/Anthropic/DeepSeek/MiniMax → cl100k_base
       - 未知模型 → 降级到 cl100k_base（保守估计）"""
    enc = _ENCODINGS.get(model)
    if enc is None:
        try:
            enc = tiktoken.encoding_for_model(model)
        except KeyError:
            enc = tiktoken.get_encoding("cl100k_base")
        _ENCODINGS[model] = enc
    return len(enc.encode(text))

# 模型 → 单价（USD / 1K tokens，2026-06 最新）
PRICE_TABLE = {
    "gpt-4o": {"input": 0.005, "output": 0.015},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "deepseek-chat": {"input": 0.00027, "output": 0.0011},
    "claude-3-5-sonnet-20240620": {"input": 0.003, "output": 0.015},
}

def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """USD 估算。未知模型返回 0（Ollama 本地 / mock）。"""
    price = PRICE_TABLE.get(model, {"input": 0.0, "output": 0.0})
    return (prompt_tokens * price["input"] + completion_tokens * price["output"]) / 1000
```

### 3.2 持久化（alembic 0007_llm_usage_log）

**迁移**：[alembic/versions/0007_llm_usage_log.py](alembic/versions/0007_llm_usage_log.py)

```python
op.create_table(
    "llm_usage_logs",
    sa.Column("id", sa.Integer(), primary_key=True),
    sa.Column("model", sa.String(64), index=True),
    sa.Column("prompt_tokens", sa.Integer()),
    sa.Column("completion_tokens", sa.Integer()),
    sa.Column("cost_usd", sa.Float()),
    sa.Column("latency_ms", sa.Integer()),
    sa.Column("caller", sa.String(64), index=True),     # e.g. "agent_chat", "script_gen"
    sa.Column("cache_hit", sa.Boolean(), default=False),
    sa.Column("rate_limited", sa.Boolean(), default=False),
    sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), index=True),
)
```

**模型**：[src/shared/llm_usage_log_model.py](src/shared/llm_usage_log_model.py)（新增）

```python
class LlmUsageLog(Base):
    __tablename__ = "llm_usage_logs"
    id = Column(Integer, primary_key=True)
    model = Column(String(64), index=True)
    prompt_tokens = Column(Integer)
    completion_tokens = Column(Integer)
    cost_usd = Column(Float)
    latency_ms = Column(Integer)
    caller = Column(String(64), index=True)
    cache_hit = Column(Boolean, default=False)
    rate_limited = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
```

### 3.3 限流（aiolimiter）

**模块**：[src/shared/rate_limiter.py](src/shared/rate_limiter.py)（新增）

```python
import asyncio
from aiolimiter import AsyncLimiter

# 默认 10 QPS（与 V4 高峰期相当）。CLI 覆盖：LLM_RATE_LIMIT_QPS=20
_qps = int(os.getenv("LLM_RATE_LIMIT_QPS", "10"))
_limiter = AsyncLimiter(max_rate=_qps, time_period=1.0)

# 豁免名单：Agent 交互路径不应被限流（低延迟优先）
EXEMPT_CALLERS = {"agent_chat", "agent_chat_confirm"}


def is_exempt(caller: str) -> bool:
    return caller in EXEMPT_CALLERS


async def acquire(caller: str) -> None:
    """同步调用前 await 一次即可。非豁免 caller 等令牌。"""
    if is_exempt(caller):
        return
    await _limiter.acquire()
```

### 3.4 缓存（diskcache）

**模块**：[src/shared/llm_cache.py](src/shared/llm_cache.py)（新增）

```python
import diskcache
import hashlib
import json

# 缓存目录：./data/llm_cache/（.gitignore 已排除）
cache = diskcache.Cache("./data/llm_cache", size_limit=1 << 30)  # 1 GB

def make_key(model: str, messages: list, temperature: float, json_mode: bool) -> str:
    """基于 model + 完整 messages + 参数算 sha256。"""
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "json_mode": json_mode,
    }, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def get_cached(key: str):
    return cache.get(key)


def set_cached(key: str, value: str, ttl_seconds: int = 86400) -> None:
    cache.set(key, value, expire=ttl_seconds)
```

**TTL 默认 24 小时**（v4 pipeline 重跑当天复用）。

## 四、集成点：llm_client.py 改造

```python
# src/shared/llm_client.py
import time
from src.shared.token_counter import count_tokens, estimate_cost
from src.shared.llm_usage_log_model import record_usage
from src.shared.rate_limiter import acquire as rate_acquire
from src.shared.llm_cache import make_key, get_cached, set_cached


class LLMClient:
    async def chat_completion_async(self, messages, caller: str = "unknown",
                                    temperature: float = 0.7, json_mode: bool = False,
                                    use_cache: bool = True):
        """新增 async 版本，支持限流 + 缓存。"""
        model = self.provider.model if hasattr(self.provider, "model") else settings.LLM_MODEL

        # 1. 缓存查询
        if use_cache:
            key = make_key(model, messages, temperature, json_mode)
            cached = get_cached(key)
            if cached is not None:
                record_usage(model=model, prompt_tokens=0, completion_tokens=0,
                             cost_usd=0.0, latency_ms=0, caller=caller, cache_hit=True)
                return cached

        # 2. 限流（exempt caller 跳过）
        await rate_acquire(caller)

        # 3. 实际调用 + 计时
        t0 = time.time()
        result = self.provider.chat_completion(messages, temperature, json_mode)
        latency_ms = int((time.time() - t0) * 1000)

        # 4. 计量 + 记录
        if result is not None:
            full_text = "".join(
                m.get("content", "") for m in messages if isinstance(m, dict)
            ) + (result if isinstance(result, str) else "")
            prompt_tokens = count_tokens(model, full_text[: len(full_text)//2])
            completion_tokens = count_tokens(model, result if isinstance(result, str) else "")
            cost = estimate_cost(model, prompt_tokens, completion_tokens)
        else:
            prompt_tokens = completion_tokens = 0
            cost = 0.0

        record_usage(model=model, prompt_tokens=prompt_tokens,
                     completion_tokens=completion_tokens, cost_usd=cost,
                     latency_ms=latency_ms, caller=caller)

        # 5. 缓存结果
        if use_cache and result is not None and isinstance(result, str):
            set_cached(make_key(model, messages, temperature, json_mode), result)

        return result

    def chat_completion(self, messages, temperature=0.7, json_mode=False):
        """同步入口（向后兼容）。Agent 高频调用走这里，不限流 + 不缓存。"""
        return self.provider.chat_completion(messages, temperature, json_mode)
```

## 五、待写专题设计文档

- `docs/design/llm-governance.md`（本文档）

## 六、验收

- [x] 设计文档通过评审
- [ ] 4 个新模块通过单测（token 计量 / 限流 / 缓存 / 记录）
- [ ] alembic 0007 双向通过（upgrade + downgrade）
- [ ] 跑一次 V4 pipeline：每条 LLM 调用在 `llm_usage_logs` 表里有对应记录
- [ ] 模拟 50 QPS 突发请求（用 `--rate-limit-test` 模式）：
  - 限流生效：每秒只放过 10 个
  - 任务队列兜底：不丢任务
- [ ] 跑同一 prompt 两次：第二次 cache_hit=True，cost=0
- [ ] Streamlit 后台新增"LLM 用量"页：按日/模型/caller 统计

## 七、风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| tiktoken 模型族映射不准 | 成本估算偏差 | 与 provider 返回的 usage 校核，偏差 > 5% 告警 |
| aiolimiter 全局限流导致 V4 慢 | 性能 | 默认 10 QPS（远高于 V4 峰值），可调；exempt 名单 |
| diskcache 写入阻塞主线程 | 性能 | 用 `cache.set()` 异步语义 |
| 缓存命中错误结果 | 正确性 | TTL 24h + caller 维度可手动清缓存 |
| agent_chat 被限流 | 体验 | 已加入 EXEMPT_CALLERS |

## 八、不在本设计范围

- 多模型同时调度（A/B test）
- 实时成本告警（Streamlit banner）
- 成本预算管理（每月上限）
- 自动降级（Ollama → mock）

这些是 I-4+ 的扩展。
