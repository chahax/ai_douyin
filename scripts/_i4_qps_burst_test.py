# -*- coding: utf-8 -*-
"""50 QPS burst verification for I-4 rate limiter."""
import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.shared.rate_limiter import acquire, reset_limiter
import os

# 用 10 QPS 限流（默认），发 50 个请求
reset_limiter()


async def one_call(i):
    t0 = time.time()
    await acquire(f"burst_test_{i}")
    elapsed = time.time() - t0
    return i, elapsed


async def main():
    print("=== 50 QPS burst verification ===")
    print(f"LLM_RATE_LIMIT_QPS = {os.getenv('LLM_RATE_LIMIT_QPS', '10 (default)')}")
    print()

    t0 = time.time()
    tasks = [one_call(i) for i in range(50)]
    results = await asyncio.gather(*tasks)
    total_elapsed = time.time() - t0

    # 统计
    wait_times = [r[1] for r in results]
    immediate = sum(1 for w in wait_times if w < 0.01)  # 立即通过
    waited = sum(1 for w in wait_times if w >= 0.01)

    print(f"50 个 acquire 完成，总耗时 {total_elapsed:.2f}s")
    print(f"  立即通过: {immediate}")
    print(f"  等令牌: {waited}")
    print(f"  平均等待: {sum(wait_times)/len(wait_times)*1000:.1f}ms")
    print(f"  最大等待: {max(wait_times)*1000:.0f}ms")
    print()

    # 理论：10 QPS = 100ms/token。50 请求应约 4.9s (49 个等 1 token)
    expected = (50 - 1) / 10.0  # 49 等待时间
    print(f"理论预期: ~{expected:.1f}s（10 QPS 限流下）")
    print()
    print(f"[OK] 限流生效：{waited}/50 个请求等令牌（10 QPS 下预期 ~40 等）"
          if waited >= 40 else
          f"[FAIL] 限流未生效：仅 {waited}/50 等令牌（预期 ~40）")


asyncio.run(main())
