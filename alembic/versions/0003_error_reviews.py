"""error_reviews table

Revision ID: 0003_error_reviews
Revises: 0002_humane_metadata
Create Date: 2026-06-15 15:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0003_error_reviews"
down_revision: Union[str, None] = "0002_humane_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "error_reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=True),
        sa.Column("location", sa.String(length=128), nullable=True),
        sa.Column("error_type", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=1000), nullable=True),
        sa.Column("traceback_snippet", sa.Text(), nullable=True),
        sa.Column("severity", sa.String(length=16), nullable=True),
        sa.Column("category", sa.String(length=32), nullable=True),
        sa.Column("summary", sa.String(length=300), nullable=True),
        sa.Column("root_cause", sa.String(length=500), nullable=True),
        sa.Column("suggested_fix", sa.String(length=500), nullable=True),
        sa.Column("cluster_key", sa.String(length=128), nullable=True),
        sa.Column("is_recurring", sa.Boolean(), nullable=True),
        sa.Column("signature", sa.String(length=64), nullable=True),
        sa.Column("context_extra", sa.Text(), nullable=True),
        sa.Column("occurrence_count", sa.Integer(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_error_reviews_source", "error_reviews", ["source"])
    op.create_index("ix_error_reviews_location", "error_reviews", ["location"])
    op.create_index("ix_error_reviews_severity", "error_reviews", ["severity"])
    op.create_index("ix_error_reviews_category", "error_reviews", ["category"])
    op.create_index("ix_error_reviews_cluster_key", "error_reviews", ["cluster_key"])
    op.create_index("ix_error_reviews_signature", "error_reviews", ["signature"])


def downgrade() -> None:
    op.drop_index("ix_error_reviews_signature", table_name="error_reviews")
    op.drop_index("ix_error_reviews_cluster_key", table_name="error_reviews")
    op.drop_index("ix_error_reviews_category", table_name="error_reviews")
    op.drop_index("ix_error_reviews_severity", table_name="error_reviews")
    op.drop_index("ix_error_reviews_location", table_name="error_reviews")
    op.drop_index("ix_error_reviews_source", table_name="error_reviews")
    op.drop_table("error_reviews")
