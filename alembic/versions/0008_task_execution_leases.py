"""add atomic worker lease metadata

Revision ID: 0008_task_execution_leases
Revises: 5cb67ecb2df3
Create Date: 2026-10-02 00:00:00+08:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0008_task_execution_leases"
down_revision: Union[str, None] = "5cb67ecb2df3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "task_executions",
        sa.Column("claim_owner", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "task_executions",
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "task_executions",
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_task_executions_claim_owner",
        "task_executions",
        ["claim_owner"],
    )
    op.create_index(
        "ix_task_executions_lease_expires_at",
        "task_executions",
        ["lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_task_executions_lease_expires_at",
        table_name="task_executions",
    )
    op.drop_index(
        "ix_task_executions_claim_owner",
        table_name="task_executions",
    )
    op.drop_column("task_executions", "heartbeat_at")
    op.drop_column("task_executions", "lease_expires_at")
    op.drop_column("task_executions", "claim_owner")
