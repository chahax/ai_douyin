# -*- coding: utf-8 -*-
"""End-to-end verify: I-4 真正生效 — V4 pipeline 的 LLM 调用都走 tracked 路径。

清空 llm_usage_logs 表，运 V4 pipeline，确认有新的 usage 记录入库。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.shared.database import SessionLocal, engine
from src.shared.llm_usage_log_model import LlmUsageLog
from sqlalchemy import func

# 清空已有记录
with SessionLocal() as s:
    n_before = s.query(LlmUsageLog).count()
    s.query(LlmUsageLog).delete()
    s.commit()
    print(f"[i] cleared {n_before} existing llm_usage_logs rows")

# 跑一个用 LLM 的简单流程：wisdom_extractor (topic 短 + 已有 wisdom chunks 时跳过 RAG)
from src.services.generation_service import GenerationService, GenerationRequest
from src.shared.llm_cache import clear_all

clear_all()  # 清缓存确保是真实调用

req = GenerationRequest(
    text="简短测试文本，用于验证 LLM 治理是否生效。I-4 switching verify.",
    tts_provider="edge",
    bgm_volume=0.0,
)

print("\n[i] Running quick_pipeline (text → TTS)...")
service = GenerationService()
result = service.run_quick_pipeline(req)
print(f"  Success: {bool(result)}")
print(f"  Result paths: {result}")

# 检查 llm_usage_logs 是否累计（quick_pipeline 不调 LLM，但 dialog/wisdom 会）
print(f"\n[i] After pipeline: llm_usage_logs has {SessionLocal().query(LlmUsageLog).count()} rows")

# 跑一个真正调 LLM 的路径：直接调 script_generator（会调 LLM）
print("\n[i] Running script_generator (will trigger LLM call)...")
from src.content_factory.script_generator import ScriptGenerator
gen = ScriptGenerator()
script = gen.generate_script(
    wisdom_data={
        "title": "测试",
        "core_message": "坚持就是胜利",
        "quote": "骐骥一跃不能十步,驽马十驾功在不舍",
        "elaboration": "坚持是成功之母",
        "actionable": "每天进步一点点",
    },
)
print(f"  Script: {script[:120] if script else script!r}")

# 检查入库
with SessionLocal() as s:
    rows = s.query(LlmUsageLog).order_by(LlmUsageLog.id.asc()).all()
    print(f"\n=== llm_usage_logs 累计 {len(rows)} 条 ===")
    for r in rows:
        print(f"  id={r.id} caller={r.caller} model={r.model} "
              f"tokens={r.prompt_tokens or 0}+{r.completion_tokens or 0} "
              f"cost=${r.cost_usd or 0:.4f} cache_hit={r.cache_hit} "
              f"latency={r.latency_ms}ms")
