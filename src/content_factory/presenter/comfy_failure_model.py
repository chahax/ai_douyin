# -*- coding: utf-8 -*-
"""
src/content_factory/presenter/comfy_failure_model.py — ComfyTaskFailure SQLAlchemy 模型

I-2 ComfyUI 容错：每次失败的 ComfyUI 任务写入这张表（alembic 0006）。

字段：
  - 任务上下文：task_name, prompt_id, attempt_no
  - 错误：error_class (OOM/WORKFLOW/TIMEOUT/UNAVAILABLE), error_message, stderr_tail
  - ComfyUI 参数：width, height, batch_size, steps
  - GPU 状态：gpu_mem_used_mb, gpu_mem_total_mb (nvidia-smi 采样)
  - 性能：duration_ms
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    String,
    Text,
)

from src.shared.database import Base


class ComfyTaskFailure(Base):
    """ComfyUI 背景生成失败的记录（每次失败 1 条）。"""

    __tablename__ = "comfy_task_failures"

    id = Column(Integer, primary_key=True, index=True)

    # 任务上下文
    task_name = Column(String(64), index=True, nullable=True)
    prompt_id = Column(String(64), nullable=True)
    attempt_no = Column(Integer, nullable=True)

    # 错误
    error_class = Column(String(32), index=True, nullable=True)
    error_message = Column(String(1000), nullable=True)
    stderr_tail = Column(Text, nullable=True)

    # ComfyUI 参数
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    batch_size = Column(Integer, nullable=True)
    steps = Column(Integer, nullable=True)

    # GPU 状态
    gpu_mem_used_mb = Column(Integer, nullable=True)
    gpu_mem_total_mb = Column(Integer, nullable=True)

    # 性能
    duration_ms = Column(Integer, nullable=True)

    # 时间
    created_at = Column(DateTime, default=datetime.utcnow, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<ComfyTaskFailure id={self.id} error_class={self.error_class!r} "
            f"attempts={self.attempt_no} task={self.task_name!r}>"
        )


def record_failure(
    task_name: str,
    error_class: str,
    error_message: str,
    *,
    prompt_id: Optional[str] = None,
    attempt_no: Optional[int] = None,
    stderr_tail: Optional[str] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    batch_size: Optional[int] = None,
    steps: Optional[int] = None,
    duration_ms: Optional[int] = None,
) -> int:
    """
    写入一条失败记录到 comfy_task_failures 表。

    Returns:
        新插入记录的 id。失败时返回 -1（不抛异常以免掩盖原始错误）。
    """
    from src.shared.database import SessionLocal

    try:
        used, total = None, None
        try:
            from src.content_factory.presenter.background_resolver import sample_gpu_memory
            used, total = sample_gpu_memory()
        except Exception:
            pass

        with SessionLocal() as session:
            record = ComfyTaskFailure(
                task_name=task_name,
                prompt_id=prompt_id,
                attempt_no=attempt_no,
                error_class=error_class,
                error_message=error_message[:1000] if error_message else None,
                stderr_tail=stderr_tail or None,
                width=width,
                height=height,
                batch_size=batch_size,
                steps=steps,
                gpu_mem_used_mb=used,
                gpu_mem_total_mb=total,
                duration_ms=duration_ms,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return record.id or -1
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(f"record_failure 写库失败: {exc}")
        return -1
