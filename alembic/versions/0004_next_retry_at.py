"""next_retry_at on task_executions + error_reviews table

Revision ID: 0004_retry_and_errorview
Revises: 0003_error_reviews
Create Date: 2026-06-15 16:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0004_retry_and_errorview"
down_revision: Union[str, None] = "0003_error_reviews"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "task_executions",
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("task_executions", "next_retry_at")
