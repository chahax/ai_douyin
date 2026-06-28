# -*- coding: utf-8 -*-
"""Smoke test for I-4 LLM 治理 (async entry + cache + log)."""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.shared.llm_client import llm_client
from src.shared.database import SessionLocal
from src.shared.llm_usage_log_model import LlmUsageLog
from src.shared.llm_cache import clear_all, stats


async def run():
    print("=== Smoke test: I-4 async entry ===")
    print(f"Model: {llm_client.model_name}")
    clear_all()  # ensure cold cache

    messages = [{"role": "user", "content": "你好，I-4 测试"}]

    # Call 1: cache miss
    t0 = time.time()
    r1 = await llm_client.chat_completion_async(messages, caller="smoke_test")
    t1 = time.time()
    print(f"\nCall 1 (cache miss): {(t1-t0)*1000:.0f}ms")
    print(f"  Return: {str(r1)[:80]}...")

    # Call 2: cache hit
    t2 = time.time()
    r2 = await llm_client.chat_completion_async(messages, caller="smoke_test")
    t3 = time.time()
    print(f"\nCall 2 (cache hit): {(t3-t2)*1000:.0f}ms")
    print(f"  Return: {str(r2)[:80]}...")
    print(f"  Cache hit confirmed: {r1 == r2}")


asyncio.run(run())

print("\n=== llm_usage_logs (latest 3) ===")
with SessionLocal() as s:
    for r in s.query(LlmUsageLog).order_by(LlmUsageLog.id.desc()).limit(3).all():
        cost = f"${r.cost_usd:.4f}" if r.cost_usd is not None else "-"
        tokens = f"{r.prompt_tokens or 0}+{r.completion_tokens or 0}"
        print(f"  id={r.id} model={r.model} caller={r.caller} "
              f"tokens={tokens} cost={cost} latency={r.latency_ms}ms "
              f"cache_hit={r.cache_hit}")

print("\n=== Cache stats ===")
for k, v in stats().items():
    print(f"  {k}: {v}")
