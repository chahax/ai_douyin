"""add fanqie_batch_books table

Revision ID: 5cb67ecb2df3
Revises: 0007_llm_usage_log
Create Date: 2026-06-29 21:49:02.686380+08:00

注意：autogenerate 误报了其他表的 drop/alter (alembic 缓存问题)，
本 migration 只保留 fanqie_batch_books 表的 create。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '5cb67ecb2df3'
down_revision: Union[str, None] = '0007_llm_usage_log'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'fanqie_batch_books',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('book_name', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=True),
        sa.Column('chapters', sa.Integer(), nullable=True),
        sa.Column('interval_s', sa.Integer(), nullable=True),
        sa.Column('book_id', sa.String(length=64), nullable=True),
        sa.Column('chapters_fetched', sa.Integer(), nullable=True),
        sa.Column('total_chapters_seen', sa.Integer(), nullable=True),
        sa.Column('paywall_hit', sa.Boolean(), nullable=True),
        sa.Column('material_path', sa.String(length=512), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('added_at', sa.DateTime(), nullable=True),
        sa.Column('last_fetched_at', sa.DateTime(), nullable=True),
        sa.Column('attempt_count', sa.Integer(), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_fanqie_batch_books_book_name', 'fanqie_batch_books', ['book_name'])
    op.create_index('ix_fanqie_batch_books_id', 'fanqie_batch_books', ['id'])
    op.create_index('ix_fanqie_batch_books_status', 'fanqie_batch_books', ['status'])


def downgrade() -> None:
    op.drop_index('ix_fanqie_batch_books_status', table_name='fanqie_batch_books')
    op.drop_index('ix_fanqie_batch_books_id', table_name='fanqie_batch_books')
    op.drop_index('ix_fanqie_batch_books_book_name', table_name='fanqie_batch_books')
    op.drop_table('fanqie_batch_books')
