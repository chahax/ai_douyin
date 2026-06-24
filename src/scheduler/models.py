"""
src/scheduler/models.py — 调度系统的 SQLAlchemy 模型

表结构：
  scheduled_tasks    定时/触发/队列任务的定义
  task_executions   每次执行的记录（状态/结果/耗时）
  task_triggers     触发器配置（条件表达式）
"""

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, JSON, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import relationship

from src.shared.database import Base


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskType(str, Enum):
    SCHEDULED = "scheduled"   # 定时任务（cron）
    QUEUE = "queue"            # 手动提交队列
    TRIGGERED = "triggered"     # 触发型任务


class TriggerType(str, Enum):
    CRON = "cron"                    # 定时（APScheduler cron 表达式）
    INTERVAL = "interval"            # 间隔（every N minutes/hours）
    COMMENT_THRESHOLD = "comment_threshold"  # 评论数超过阈值
    VIDEO_PUBLISHED = "video_published"        # 新视频发布后
    MANUAL = "manual"                        # 手动触发


class ScheduledTask(Base):
    """
    任务定义表。

    一条记录 = 一个可执行的 Skill 任务。
    """
    __tablename__ = "scheduled_tasks"

    id = Column(Integer, primary_key=True, index=True)
    task_uuid = Column(String(64), unique=True, default=lambda: uuid.uuid4().hex, index=True)
    name = Column(String(255), index=True)
    description = Column(Text, default="")

    # 任务类型
    task_type = Column(String(32), default=TaskType.SCHEDULED.value)

    # 关联的 Skill 名称
    skill_name = Column(String(128))

    # Skill 调用的参数（JSON）
    skill_params = Column(JSON, default=dict)

    # 用户偏好覆盖（可选）
    preferences_override = Column(JSON, default=dict)

    # 状态
    status = Column(String(32), default=TaskStatus.PENDING.value, index=True)

    # 是否启用
    enabled = Column(Boolean, default=True, index=True)

    # 触发器类型
    trigger_type = Column(String(32), default=TriggerType.CRON.value)

    # 触发器配置（JSON，触发器类型不同格式不同）
    # cron: {"expression": "0 9 * * *"}
    # interval: {"minutes": 60}
    # comment_threshold: {"video_id": "...", "threshold": 50}
    # video_published: {"account_id": "..."}
    trigger_config = Column(JSON, default=dict)

    # 重试配置
    max_retries = Column(Integer, default=0)
    retry_delay_seconds = Column(Integer, default=60)

    # 元数据
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_run_at = Column(DateTime, nullable=True)
    next_run_at = Column(DateTime, nullable=True, index=True)

    executions = relationship(
        "TaskExecution",
        back_populates="task",
        order_by="TaskExecution.created_at.desc()",
        cascade="all, delete-orphan",
    )


class TaskExecution(Base):
    """
    任务执行记录表。

    每次调用 Skill 产生一条记录。
    """
    __tablename__ = "task_executions"

    id = Column(Integer, primary_key=True, index=True)
    execution_uuid = Column(String(64), unique=True, default=lambda: uuid.uuid4().hex, index=True)

    task_id = Column(Integer, ForeignKey("scheduled_tasks.id"), index=True)
    task = relationship("ScheduledTask", back_populates="executions")

    # 执行状态
    status = Column(String(32), default=TaskStatus.PENDING.value, index=True)

    # 执行的输入参数（快照）
    skill_params_snapshot = Column(JSON, default=dict)

    # 执行结果
    result = Column(JSON, default=dict)       # Skill 返回的完整结果
    result_summary = Column(Text, default="")  # 简短摘要（用于展示）
    error_message = Column(Text, default="")

    # 性能
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Integer, nullable=True)

    # 重试
    attempt = Column(Integer, default=1)
    is_retry = Column(Boolean, default=False)
    next_retry_at = Column(DateTime, nullable=True)  # Phase 3: retry_delay_seconds 实现

    created_at = Column(DateTime, default=datetime.utcnow)
