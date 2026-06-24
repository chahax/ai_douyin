"""humane metadata columns on conversation_messages / conversation_memory

Revision ID: 0002_humane_metadata
Revises: 0001_initial
Create Date: 2026-06-15 14:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0002_humane_metadata"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ConversationMessage humane metadata
    op.add_column(
        "conversation_messages",
        sa.Column("intent", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "conversation_messages",
        sa.Column("sentiment", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "conversation_messages",
        sa.Column("topics", sa.JSON(), nullable=True),
    )
    op.add_column(
        "conversation_messages",
        sa.Column("entities", sa.JSON(), nullable=True),
    )
    op.add_column(
        "conversation_messages",
        sa.Column("humane_summary", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "conversation_messages",
        sa.Column("needs_followup", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "conversation_messages",
        sa.Column("classification_source", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "conversation_messages",
        sa.Column("classified_at", sa.DateTime(), nullable=True),
    )

    # ConversationMemory: also track classification source + timestamp
    op.add_column(
        "conversation_memory",
        sa.Column("classification_source", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "conversation_memory",
        sa.Column("classified_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversation_memory", "classified_at")
    op.drop_column("conversation_memory", "classification_source")

    op.drop_column("conversation_messages", "classified_at")
    op.drop_column("conversation_messages", "classification_source")
    op.drop_column("conversation_messages", "needs_followup")
    op.drop_column("conversation_messages", "humane_summary")
    op.drop_column("conversation_messages", "entities")
    op.drop_column("conversation_messages", "topics")
    op.drop_column("conversation_messages", "sentiment")
    op.drop_column("conversation_messages", "intent")
