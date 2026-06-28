# -*- coding: utf-8 -*-
"""
src/shared/rate_limiter.py — I-4 LLM 限流

默认 10 QPS，CLI 覆盖：LLM_RATE_LIMIT_QPS=20

Agent 交互路径（agent_chat）通过 EXEMPT_CALLERS 豁免，保持低延迟。
V4 pipeline 后台调用（script_gen / scene_plan / tag）走限流路径。

调用方式（async）：
    from src.shared.rate_limiter import acquire, is_exempt

    async def call_llm(...):
        await acquire(caller="scene_plan")
        return provider.chat_completion(...)
"""

import os
from typing import Optional

from aiolimiter import AsyncLimiter


# 默认 10 QPS
_DEFAULT_QPS = 10


def _get_qps() -> int:
    """从环境变量 LLM_RATE_LIMIT_QPS 读取覆盖值。"""
    try:
        v = int(os.getenv("LLM_RATE_LIMIT_QPS", str(_DEFAULT_QPS)))
        return max(1, v)
    except (TypeError, ValueError):
        return _DEFAULT_QPS


# 全局限流器（懒初始化以读取最新 env）
_limiter: Optional[AsyncLimiter] = None


def _get_limiter() -> AsyncLimiter:
    global _limiter
    if _limiter is None:
        qps = _get_qps()
        _limiter = AsyncLimiter(max_rate=qps, time_period=1.0)
    return _limiter


def reset_limiter() -> None:
    """测试用：重置限流器到新 QPS。"""
    global _limiter
    _limiter = None


# Agent 交互路径不参与限流（要求低延迟）
EXEMPT_CALLERS: set[str] = {
    "agent_chat",
    "agent_chat_confirm",
    "agent_skill_decorator",
}


def is_exempt(caller: str) -> bool:
    return caller in EXEMPT_CALLERS


async def acquire(caller: str = "unknown") -> None:
    """
    调用前 await acquire(caller) 获取令牌。
    豁免 caller 直接返回，不阻塞。
    """
    if is_exempt(caller):
        return
    await _get_limiter().acquire()


def get_current_qps() -> int:
    """当前生效的 QPS（诊断用）。"""
    return _get_qps()
