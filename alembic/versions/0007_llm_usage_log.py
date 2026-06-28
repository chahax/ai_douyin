"""llm_usage_logs table — I-4 LLM 成本与限流治理

Revision ID: 0007_llm_usage_log
Revises: 0006_comfy_task_failures
Create Date: 2026-06-28 15:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0007_llm_usage_log"
down_revision: Union[str, None] = "0006_comfy_task_failures"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llm_usage_logs",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        # 模型与成本
        sa.Column("model", sa.String(length=64), nullable=True, index=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        # 性能 + 调用方
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("caller", sa.String(length=64), nullable=True, index=True),
        # 标志位（缓存命中 / 被限流）
        sa.Column("cache_hit", sa.Boolean(), nullable=True, default=False),
        sa.Column("rate_limited", sa.Boolean(), nullable=True, default=False),
        # 时间
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True, index=True),
    )


def downgrade() -> None:
    op.drop_table("llm_usage_logs")
