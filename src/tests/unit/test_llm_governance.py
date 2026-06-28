# -*- coding: utf-8 -*-
"""
Tests for I-4 LLM 成本与限流治理。

覆盖：
  - token_counter: 计量 + 成本估算（含未知模型降级）
  - llm_cache: key 稳定性 + 命中 + TTL + 开关
  - rate_limiter: 默认 QPS + 环境变量 + exempt 名单
  - record_usage: 写库成功 + 写库失败返回 -1
  - async chat_completion_async: cache miss → call → log; cache hit → no call
"""

import asyncio
import os
from unittest.mock import patch, MagicMock

import pytest

from src.shared.token_counter import count_tokens, estimate_cost, is_local_model, PRICE_TABLE
from src.shared.llm_cache import make_key, get_cached, set_cached, clear_all, stats, is_enabled
from src.shared.rate_limiter import (
    get_current_qps,
    reset_limiter,
    is_exempt,
    EXEMPT_CALLERS,
)
from src.shared.llm_usage_log_model import record_usage, LlmUsageLog


# ---------------------------------------------------------------------------
# token_counter
# ---------------------------------------------------------------------------


class TestTokenCounter:
    def test_count_tokens_basic(self):
        n = count_tokens("gpt-4o", "hello world")
        assert n == 2

    def test_count_tokens_chinese(self):
        n = count_tokens("gpt-4o", "你好世界")
        assert n > 0  # 中文至少 1 个 token / 字

    def test_count_tokens_empty(self):
        assert count_tokens("gpt-4o", "") == 0

    def test_count_tokens_unknown_model_falls_back(self):
        """未知模型应降级到 cl100k_base 而不抛异常。"""
        n = count_tokens("totally-unknown-model-xyz", "hello")
        assert n > 0

    def test_estimate_cost_known_model(self):
        # gpt-4o: 0.005/1K input, 0.015/1K output
        cost = estimate_cost("gpt-4o", prompt_tokens=1000, completion_tokens=1000)
        assert abs(cost - (0.005 + 0.015)) < 1e-6

    def test_estimate_cost_unknown_model_zero(self):
        assert estimate_cost("local-ollama-llama3", 1000, 1000) == 0.0

    def test_is_local_model(self):
        assert is_local_model("local-llama3") is True
        assert is_local_model("gpt-4o") is False

    def test_price_table_has_common_models(self):
        for m in ("gpt-4o", "gpt-4o-mini", "deepseek-chat"):
            assert m in PRICE_TABLE


# ---------------------------------------------------------------------------
# llm_cache
# ---------------------------------------------------------------------------


class TestLLMCache:
    def setup_method(self):
        clear_all()
        os.environ.pop("LLM_DISABLE_CACHE", None)

    def teardown_method(self):
        clear_all()

    def test_make_key_stable_for_same_input(self):
        messages = [{"role": "user", "content": "hi"}]
        k1 = make_key("gpt-4o", messages, 0.7, False)
        k2 = make_key("gpt-4o", messages, 0.7, False)
        assert k1 == k2
        # length 64 (sha256 hex)
        assert len(k1) == 64

    def test_make_key_differs_on_model(self):
        messages = [{"role": "user", "content": "hi"}]
        k1 = make_key("gpt-4o", messages, 0.7, False)
        k2 = make_key("gpt-4o-mini", messages, 0.7, False)
        assert k1 != k2

    def test_make_key_differs_on_temperature(self):
        messages = [{"role": "user", "content": "hi"}]
        k1 = make_key("gpt-4o", messages, 0.5, False)
        k2 = make_key("gpt-4o", messages, 0.9, False)
        assert k1 != k2

    def test_make_key_differs_on_message_order(self):
        m1 = [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}]
        m2 = [{"role": "user", "content": "b"}, {"role": "user", "content": "a"}]
        k1 = make_key("gpt-4o", m1, 0.7, False)
        k2 = make_key("gpt-4o", m2, 0.7, False)
        # sort_keys=True 让 JSON dict 顺序固定；但 list 顺序不固定
        assert k1 != k2

    def test_get_set_cache(self):
        key = make_key("test", [{"role": "user", "content": "hi"}], 0.7, False)
        assert get_cached(key) is None
        set_cached(key, "response text", ttl_seconds=60)
        assert get_cached(key) == "response text"

    def test_disable_cache(self, monkeypatch):
        key = make_key("test", [{"role": "user", "content": "hi"}], 0.7, False)
        monkeypatch.setenv("LLM_DISABLE_CACHE", "1")
        assert is_enabled() is False
        set_cached(key, "x")  # 关闭时 set 不写
        assert get_cached(key) is None  # 关闭时 get 不读

    def test_clear_all(self):
        set_cached("k1", "v1")
        set_cached("k2", "v2")
        assert stats()["size"] >= 2
        n = clear_all()
        assert n >= 2
        assert stats()["size"] == 0


# ---------------------------------------------------------------------------
# rate_limiter
# ---------------------------------------------------------------------------


class TestRateLimiter:
    def setup_method(self):
        reset_limiter()
        os.environ.pop("LLM_RATE_LIMIT_QPS", None)

    def test_default_qps_is_10(self):
        assert get_current_qps() == 10

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("LLM_RATE_LIMIT_QPS", "25")
        reset_limiter()
        assert get_current_qps() == 25

    def test_invalid_env_falls_back(self, monkeypatch):
        monkeypatch.setenv("LLM_RATE_LIMIT_QPS", "abc")
        reset_limiter()
        assert get_current_qps() == 10

    def test_zero_clamped_to_one(self, monkeypatch):
        monkeypatch.setenv("LLM_RATE_LIMIT_QPS", "0")
        reset_limiter()
        assert get_current_qps() == 1

    def test_is_exempt_agent_chat(self):
        assert is_exempt("agent_chat") is True
        assert is_exempt("agent_chat_confirm") is True
        assert is_exempt("script_gen") is False
        assert is_exempt("scene_plan") is False

    def test_exempt_callers_constant(self):
        """EXEMPT_CALLERS 必须包含 agent_chat（核心交互路径）。"""
        assert "agent_chat" in EXEMPT_CALLERS

    @pytest.mark.asyncio
    async def test_acquire_exempt_does_not_block(self):
        """exempt caller 立即返回，不阻塞。"""
        from src.shared.rate_limiter import acquire
        t0 = asyncio.get_event_loop().time()
        await acquire("agent_chat")  # 不应该等令牌
        elapsed = asyncio.get_event_loop().time() - t0
        assert elapsed < 0.05

    @pytest.mark.asyncio
    async def test_acquire_non_exempt_returns(self):
        """非 exempt caller 也能 acquire（不抛异常），只是会阻塞等令牌。"""
        from src.shared.rate_limiter import acquire
        # 第一次 acquire 应该立即通过
        await acquire("script_gen")


# ---------------------------------------------------------------------------
# record_usage (DB 写库)
# ---------------------------------------------------------------------------


class TestRecordUsage:
    def test_record_usage_db_error_returns_negative(self, monkeypatch):
        """写库失败不应抛异常，应返回 -1。"""
        from src.shared import database as db_mod

        class FakeSessCtx:
            def __enter__(self):
                raise RuntimeError("DB down")

            def __exit__(self, *a):
                return False

        def fake_session_local():
            return FakeSessCtx()

        monkeypatch.setattr(db_mod, "SessionLocal", fake_session_local)
        result = record_usage(
            model="gpt-4o",
            prompt_tokens=10,
            completion_tokens=20,
            cost_usd=0.0001,
            latency_ms=100,
            caller="unit_test",
        )
        assert result == -1

    def test_record_usage_success(self):
        """成功路径返回新记录 id（≥1）。"""
        result = record_usage(
            model="gpt-4o-mini",
            prompt_tokens=50,
            completion_tokens=100,
            cost_usd=0.0001,
            latency_ms=200,
            caller="unit_test_success",
        )
        assert result >= 1


# ---------------------------------------------------------------------------
# async chat_completion_async (cache + log)
# ---------------------------------------------------------------------------


class TestAsyncChatCompletion:
    """mock provider 行为，验证 cache miss → 调 → 记录；cache hit → 不调 → 记录 0 token。"""

    def setup_method(self):
        clear_all()

    def teardown_method(self):
        clear_all()

    @pytest.mark.asyncio
    async def test_cache_miss_calls_provider_and_logs(self):
        from src.shared.llm_client import llm_client
        from src.shared.database import SessionLocal
        from src.shared.llm_usage_log_model import LlmUsageLog

        # 替换底层 provider 返回固定字符串
        with patch.object(llm_client.provider, "chat_completion", return_value="mock-response-A"):
            r = await llm_client.chat_completion_async(
                messages=[{"role": "user", "content": "hello"}],
                caller="unit_async_miss",
                use_cache=True,
            )
        assert r == "mock-response-A"

        # 验证 llm_usage_logs 多了一条 cache_hit=False 的记录
        with SessionLocal() as s:
            log = s.query(LlmUsageLog).filter(LlmUsageLog.caller == "unit_async_miss").order_by(LlmUsageLog.id.desc()).first()
            assert log is not None
            assert log.cache_hit is False
            assert log.prompt_tokens > 0
            assert log.completion_tokens > 0
            # latency 用 mock provider 时可能 < 1ms（被 time.time() 取整为 0），用 >= 0 容忍
            assert log.latency_ms is not None and log.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_cache_hit_skips_provider_and_logs_zero_tokens(self):
        from src.shared.llm_client import llm_client
        from src.shared.database import SessionLocal
        from src.shared.llm_usage_log_model import LlmUsageLog

        # 用 unique caller 隔离历史记录
        import uuid
        caller = f"unit_async_hit_{uuid.uuid4().hex[:8]}"
        messages = [{"role": "user", "content": "cache test query"}]

        # 第 1 次：cache miss
        with patch.object(llm_client.provider, "chat_completion", return_value="cached-value"):
            r1 = await llm_client.chat_completion_async(messages, caller=caller)
        assert r1 == "cached-value"

        # 第 2 次：cache hit → provider 不被调
        with patch.object(llm_client.provider, "chat_completion") as mock_provider:
            r2 = await llm_client.chat_completion_async(messages, caller=caller)
            # provider.chat_completion 不应被调用
            assert mock_provider.call_count == 0
        assert r2 == "cached-value"

        # 验证：本测试 caller 下有 2 条记录
        with SessionLocal() as s:
            logs = (
                s.query(LlmUsageLog)
                .filter(LlmUsageLog.caller == caller)
                .order_by(LlmUsageLog.id.asc())
                .all()
            )
            assert len(logs) == 2
            assert logs[0].cache_hit is False  # 第一次 miss
            assert logs[1].cache_hit is True   # 第二次 hit
            assert logs[1].prompt_tokens == 0
            assert logs[1].completion_tokens == 0
            assert logs[1].cost_usd == 0.0
            assert logs[1].latency_ms == 0
