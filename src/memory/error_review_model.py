# -*- coding: utf-8 -*-
"""
src/memory/error_review_model.py — ErrorReview SQLAlchemy 模型

Phase 3：所有系统错误（agent chat / skill exec / worker task）经
ErrorReviewer 调 LLM 生成的诊断，存到这张表。

字段：
  - source / location: 来源和位置（agent_chat, skill:<name>, task:<uuid>）
  - 原始错误信息（error_type / error_message / traceback_snippet）
  - LLM 诊断（severity / category / summary / root_cause / suggested_fix）
  - 聚类（cluster_key / is_recurring / signature / occurrence_count）
  - 时间（first_seen_at / last_seen_at / resolved_at）
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    Text,
)

from src.shared.database import Base


class ErrorReview(Base):
    """LLM 诊断后的错误记录。"""

    __tablename__ = "error_reviews"

    id = Column(Integer, primary_key=True, index=True)

    # 来源
    source = Column(String(32), index=True)
    """agent_chat / skill_exec / worker_task"""

    location = Column(String(128), index=True)
    """session:<id> / skill:<name> / task:<execution_uuid>"""

    # 原始错误
    error_type = Column(String(64))
    error_message = Column(String(1000))
    traceback_snippet = Column(Text)

    # LLM 诊断
    severity = Column(String(16), index=True)
    """low / medium / high / critical"""

    category = Column(String(32), index=True)
    """transient / config / external_api / logic / resource / auth / data"""

    summary = Column(String(300))
    root_cause = Column(String(500))
    suggested_fix = Column(String(500))

    # 聚类
    cluster_key = Column(String(128), index=True)
    is_recurring = Column(Boolean, default=False)
    signature = Column(String(64), index=True)  # dedup key

    # 上下文
    context_extra = Column(Text)  # JSON

    # 统计
    occurrence_count = Column(Integer, default=1)
    first_seen_at = Column(DateTime, default=datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)
