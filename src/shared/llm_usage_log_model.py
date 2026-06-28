# -*- coding: utf-8 -*-
"""
src/shared/llm_usage_log_model.py — LlmUsageLog SQLAlchemy 模型

I-4 LLM 成本与限流：每次 LLM 调用 1 条记录（缓存命中也记录，cost=0）。

字段：
  - 模型与成本：model / prompt_tokens / completion_tokens / cost_usd
  - 性能：latency_ms
  - 调用方：caller（agent_chat / scene_plan / script_gen / tag / ...）
  - 标志：cache_hit / rate_limited
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
)

from src.shared.database import Base


class LlmUsageLog(Base):
    """LLM 调用记录。"""

    __tablename__ = "llm_usage_logs"

    id = Column(Integer, primary_key=True, index=True)

    # 模型与成本
    model = Column(String(64), index=True, nullable=True)
    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)
    cost_usd = Column(Float, nullable=True)

    # 性能 + 调用方
    latency_ms = Column(Integer, nullable=True)
    caller = Column(String(64), index=True, nullable=True)

    # 标志
    cache_hit = Column(Boolean, default=False, nullable=True)
    rate_limited = Column(Boolean, default=False, nullable=True)

    # 时间
    created_at = Column(DateTime, default=datetime.utcnow, index=True, nullable=True)


def record_usage(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: float,
    latency_ms: int,
    caller: str,
    *,
    cache_hit: bool = False,
    rate_limited: bool = False,
) -> int:
    """
    写入一条 LLM 调用记录。

    Returns:
        新插入记录的 id；写库失败返回 -1（不掩盖原始 LLM 异常）。
    """
    from src.shared.database import SessionLocal

    try:
        with SessionLocal() as session:
            log = LlmUsageLog(
                model=model[:64] if model else None,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=cost_usd,
                latency_ms=latency_ms,
                caller=caller[:64] if caller else None,
                cache_hit=cache_hit,
                rate_limited=rate_limited,
            )
            session.add(log)
            session.commit()
            session.refresh(log)
            return log.id or -1
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(f"record_usage 写库失败: {exc}")
        return -1
