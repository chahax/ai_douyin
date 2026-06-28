"""comfy_task_failures table — I-2 ComfyUI 容错持久化

Revision ID: 0006_comfy_task_failures
Revises: 0004_next_retry_at
Create Date: 2026-06-28 14:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0006_comfy_task_failures"
down_revision: Union[str, None] = "0004_retry_and_errorview"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "comfy_task_failures",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        # 任务上下文
        sa.Column("task_name", sa.String(length=64), nullable=True),         # e.g. "presenter_bg_xxx"
        sa.Column("prompt_id", sa.String(length=64), nullable=True),         # ComfyUI prompt_id
        sa.Column("attempt_no", sa.Integer(), nullable=True),               # 第几次重试
        # 错误信息
        sa.Column("error_class", sa.String(length=32), nullable=True),       # OOM / WORKFLOW / TIMEOUT / UNAVAILABLE
        sa.Column("error_message", sa.String(length=1000), nullable=True),
        sa.Column("stderr_tail", sa.Text(), nullable=True),                 # 最近 stderr（OOM 诊断用）
        # ComfyUI 状态
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("batch_size", sa.Integer(), nullable=True),
        sa.Column("steps", sa.Integer(), nullable=True),
        # GPU 状态（nvidia-smi 采样）
        sa.Column("gpu_mem_used_mb", sa.Integer(), nullable=True),
        sa.Column("gpu_mem_total_mb", sa.Integer(), nullable=True),
        # 性能
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        # 元数据
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
    )
    op.create_index(
        "ix_comfy_task_failures_error_class_created_at",
        "comfy_task_failures",
        ["error_class", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_comfy_task_failures_error_class_created_at", table_name="comfy_task_failures")
    op.drop_table("comfy_task_failures")
