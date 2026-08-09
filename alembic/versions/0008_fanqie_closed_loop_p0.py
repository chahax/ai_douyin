"""Add fanqie closed-loop P0 tables: books, promotion_tasks, scripts, video_jobs,
douyin_accounts, publish_records, reviews, bindings, operation_events, performance_daily;
extend fanqie_batch_books with fanqie_book_pk FK.

Revision ID: 0008_fanqie_closed_loop_p0
Revises: 5cb67ecb2df3
Create Date: 2026-08-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0008_fanqie_closed_loop_p0'
down_revision: Union[str, None] = '5cb67ecb2df3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── fanqie_books ──
    op.create_table(
        'fanqie_books',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('book_uuid', sa.String(64), nullable=False),
        sa.Column('fanqie_book_id', sa.String(64), nullable=True),
        sa.Column('book_name', sa.String(255), nullable=False, server_default=''),
        sa.Column('author', sa.String(255), nullable=False, server_default=''),
        sa.Column('abstract', sa.Text(), nullable=True),
        sa.Column('categories_json', sa.JSON(), nullable=True),
        sa.Column('tags_json', sa.JSON(), nullable=True),
        sa.Column('serial_status', sa.String(32), nullable=True),
        sa.Column('word_count', sa.Integer(), nullable=True),
        sa.Column('source_ranking', sa.String(128), nullable=True),
        sa.Column('selection_filters_json', sa.JSON(), nullable=True),
        sa.Column('selection_reason', sa.Text(), nullable=True),
        sa.Column('selected_by', sa.String(64), nullable=True),
        sa.Column('material_status', sa.String(32), nullable=True),
        sa.Column('material_root', sa.String(512), nullable=True),
        sa.Column('material_hash', sa.String(128), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('book_uuid'),
        sa.UniqueConstraint('fanqie_book_id'),
    )
    op.create_index('ix_fanqie_books_book_uuid', 'fanqie_books', ['book_uuid'])
    op.create_index('ix_fanqie_books_fanqie_book_id', 'fanqie_books', ['fanqie_book_id'])
    op.create_index('ix_fanqie_books_id', 'fanqie_books', ['id'])

    # ── fanqie_chapters ──
    op.create_table(
        'fanqie_chapters',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('book_id', sa.Integer(), sa.ForeignKey('fanqie_books.id'), nullable=False),
        sa.Column('chapter_index', sa.Integer(), nullable=False),
        sa.Column('chapter_title', sa.String(255), nullable=True),
        sa.Column('source_url', sa.String(512), nullable=True),
        sa.Column('content_path', sa.String(512), nullable=True),
        sa.Column('content_hash', sa.String(128), nullable=True),
        sa.Column('char_count', sa.Integer(), nullable=True),
        sa.Column('is_paywalled', sa.Boolean(), nullable=True),
        sa.Column('fetched_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_fanqie_chapters_book_id', 'fanqie_chapters', ['book_id'])
    op.create_index('ix_fanqie_chapters_id', 'fanqie_chapters', ['id'])
    op.create_index('uq_fanqie_chapters_book_idx', 'fanqie_chapters', ['book_id', 'chapter_index'], unique=True)

    # ── fanqie_promotion_tasks ──
    op.create_table(
        'fanqie_promotion_tasks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('task_uuid', sa.String(64), nullable=False),
        sa.Column('book_id', sa.Integer(), sa.ForeignKey('fanqie_books.id'), nullable=True),
        sa.Column('platform_task_id', sa.String(128), nullable=True),
        sa.Column('promotion_alias', sa.String(255), nullable=True),
        sa.Column('publish_type', sa.String(64), nullable=True),
        sa.Column('status', sa.String(32), nullable=True),
        sa.Column('failure_stage', sa.String(32), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('valid_from', sa.DateTime(), nullable=True),
        sa.Column('valid_until', sa.DateTime(), nullable=True),
        sa.Column('application_snapshot_path', sa.String(512), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('manual_reason', sa.Text(), nullable=True),
        sa.Column('created_by', sa.String(64), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('task_uuid'),
    )
    op.create_index('ix_fanqie_promotion_tasks_book_id', 'fanqie_promotion_tasks', ['book_id'])
    op.create_index('ix_fanqie_promotion_tasks_id', 'fanqie_promotion_tasks', ['id'])
    op.create_index('ix_fanqie_promotion_tasks_status', 'fanqie_promotion_tasks', ['status'])
    op.create_index('ix_fanqie_promotion_tasks_task_uuid', 'fanqie_promotion_tasks', ['task_uuid'])
    # SQLite partial unique index: only enforce alias uniqueness for non-terminal tasks
    op.execute("""
        CREATE UNIQUE INDEX uq_fanqie_task_active_alias
        ON fanqie_promotion_tasks(book_id, promotion_alias)
        WHERE promotion_alias IS NOT NULL
          AND status NOT IN ('rejected', 'expired', 'completed', 'stopped', 'cancelled')
    """)

    # ── fanqie_promotion_task_aliases ──
    op.create_table(
        'fanqie_promotion_task_aliases',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('task_id', sa.Integer(), sa.ForeignKey('fanqie_promotion_tasks.id'), nullable=False),
        sa.Column('alias', sa.String(255), nullable=False),
        sa.Column('is_current', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_fanqie_promotion_task_aliases_id', 'fanqie_promotion_task_aliases', ['id'])
    op.create_index('ix_fanqie_task_aliases_task', 'fanqie_promotion_task_aliases', ['task_id'])

    # ── fanqie_script_versions ──
    op.create_table(
        'fanqie_script_versions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('script_uuid', sa.String(64), nullable=False),
        sa.Column('task_id', sa.Integer(), sa.ForeignKey('fanqie_promotion_tasks.id'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('parent_script_id', sa.Integer(), nullable=True),
        sa.Column('chapter_range', sa.String(128), nullable=True),
        sa.Column('hook', sa.Text(), nullable=True),
        sa.Column('script_text', sa.Text(), nullable=True),
        sa.Column('title', sa.String(255), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('hashtags_json', sa.JSON(), nullable=True),
        sa.Column('cta', sa.String(255), nullable=True),
        sa.Column('spoiler_level', sa.String(32), nullable=True),
        sa.Column('model_name', sa.String(128), nullable=True),
        sa.Column('prompt_version', sa.String(64), nullable=True),
        sa.Column('generation_params_json', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(32), nullable=True),
        sa.Column('content_hash', sa.String(128), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('script_uuid'),
    )
    op.create_index('ix_fanqie_script_versions_id', 'fanqie_script_versions', ['id'])
    op.create_index('ix_fanqie_script_versions_task_id', 'fanqie_script_versions', ['task_id'])
    op.create_index('uq_fanqie_scripts_task_version', 'fanqie_script_versions', ['task_id', 'version'], unique=True)

    # ── fanqie_video_jobs ──
    op.create_table(
        'fanqie_video_jobs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('job_uuid', sa.String(64), nullable=False),
        sa.Column('task_id', sa.Integer(), sa.ForeignKey('fanqie_promotion_tasks.id'), nullable=False),
        sa.Column('script_id', sa.Integer(), sa.ForeignKey('fanqie_script_versions.id'), nullable=False),
        sa.Column('video_mode', sa.String(64), nullable=True),
        sa.Column('quality_profile', sa.String(32), nullable=True),
        sa.Column('status', sa.String(32), nullable=True),
        sa.Column('failure_stage', sa.String(32), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('request_path', sa.String(512), nullable=True),
        sa.Column('manifest_path', sa.String(512), nullable=True),
        sa.Column('output_path', sa.String(512), nullable=True),
        sa.Column('quality_report_path', sa.String(512), nullable=True),
        sa.Column('review_packet_path', sa.String(512), nullable=True),
        sa.Column('output_sha256', sa.String(128), nullable=True),
        sa.Column('runtime_json', sa.JSON(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('cost_json', sa.JSON(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('job_uuid'),
    )
    op.create_index('ix_fanqie_video_jobs_id', 'fanqie_video_jobs', ['id'])
    op.create_index('ix_fanqie_video_jobs_job_uuid', 'fanqie_video_jobs', ['job_uuid'])
    op.create_index('ix_fanqie_video_jobs_script_id', 'fanqie_video_jobs', ['script_id'])
    op.create_index('ix_fanqie_video_jobs_status', 'fanqie_video_jobs', ['status'])
    op.create_index('ix_fanqie_video_jobs_task_id', 'fanqie_video_jobs', ['task_id'])

    # ── fanqie_douyin_accounts ──
    op.create_table(
        'fanqie_douyin_accounts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('account_uuid', sa.String(64), nullable=False),
        sa.Column('account_key', sa.String(128), nullable=False),
        sa.Column('display_name', sa.String(255), nullable=True),
        sa.Column('masked_login_name', sa.String(64), nullable=True),
        sa.Column('status', sa.String(32), nullable=True),
        sa.Column('profile_dir', sa.String(512), nullable=True),
        sa.Column('platform_uid', sa.String(128), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('account_uuid'),
        sa.UniqueConstraint('account_key'),
    )
    op.create_index('ix_fanqie_douyin_accounts_account_key', 'fanqie_douyin_accounts', ['account_key'])
    op.create_index('ix_fanqie_douyin_accounts_id', 'fanqie_douyin_accounts', ['id'])

    # ── fanqie_publish_records ──
    op.create_table(
        'fanqie_publish_records',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('publish_uuid', sa.String(64), nullable=False),
        sa.Column('task_id', sa.Integer(), sa.ForeignKey('fanqie_promotion_tasks.id'), nullable=False),
        sa.Column('video_job_id', sa.Integer(), sa.ForeignKey('fanqie_video_jobs.id'), nullable=True),
        sa.Column('douyin_account_id', sa.Integer(), sa.ForeignKey('fanqie_douyin_accounts.id'), nullable=True),
        sa.Column('status', sa.String(32), nullable=True),
        sa.Column('title_snapshot', sa.String(255), nullable=True),
        sa.Column('description_snapshot', sa.Text(), nullable=True),
        sa.Column('hashtags_json', sa.JSON(), nullable=True),
        sa.Column('douyin_video_id', sa.String(128), nullable=True),
        sa.Column('douyin_video_url', sa.String(512), nullable=True),
        sa.Column('published_at', sa.DateTime(), nullable=True),
        sa.Column('synced_at', sa.DateTime(), nullable=True),
        sa.Column('platform_response_path', sa.String(512), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('publish_uuid'),
        sa.UniqueConstraint('douyin_video_id'),
        sa.UniqueConstraint('douyin_video_url'),
    )
    op.create_index('ix_fanqie_publish_records_douyin_account_id', 'fanqie_publish_records', ['douyin_account_id'])
    op.create_index('ix_fanqie_publish_records_douyin_video_id', 'fanqie_publish_records', ['douyin_video_id'])
    op.create_index('ix_fanqie_publish_records_id', 'fanqie_publish_records', ['id'])
    op.create_index('ix_fanqie_publish_records_publish_uuid', 'fanqie_publish_records', ['publish_uuid'])
    op.create_index('ix_fanqie_publish_records_status', 'fanqie_publish_records', ['status'])
    op.create_index('ix_fanqie_publish_records_task_id', 'fanqie_publish_records', ['task_id'])
    op.create_index('ix_fanqie_publish_records_video_job_id', 'fanqie_publish_records', ['video_job_id'])

    # ── fanqie_reviews ──
    op.create_table(
        'fanqie_reviews',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('review_uuid', sa.String(64), nullable=False),
        sa.Column('video_job_id', sa.Integer(), sa.ForeignKey('fanqie_video_jobs.id'), nullable=False),
        sa.Column('decision', sa.String(32), nullable=False),
        sa.Column('reviewer', sa.String(64), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('issues_json', sa.JSON(), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('machine_gate_passed', sa.Boolean(), nullable=True),
        sa.Column('override_reason', sa.Text(), nullable=True),
        sa.Column('approved_sha256', sa.String(128), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('review_uuid'),
    )
    op.create_index('ix_fanqie_reviews_id', 'fanqie_reviews', ['id'])
    op.create_index('ix_fanqie_reviews_video_job_id', 'fanqie_reviews', ['video_job_id'])

    # ── fanqie_bindings ──
    op.create_table(
        'fanqie_bindings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('binding_uuid', sa.String(64), nullable=False),
        sa.Column('task_id', sa.Integer(), sa.ForeignKey('fanqie_promotion_tasks.id'), nullable=False),
        sa.Column('publish_id', sa.Integer(), sa.ForeignKey('fanqie_publish_records.id'), nullable=False),
        sa.Column('status', sa.String(32), nullable=True),
        sa.Column('attempt_count', sa.Integer(), nullable=True),
        sa.Column('submitted_url', sa.String(512), nullable=True),
        sa.Column('response_snapshot_path', sa.String(512), nullable=True),
        sa.Column('screenshot_path', sa.String(512), nullable=True),
        sa.Column('bound_at', sa.DateTime(), nullable=True),
        sa.Column('last_attempt_at', sa.DateTime(), nullable=True),
        sa.Column('operator', sa.String(64), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('binding_uuid'),
    )
    op.create_index('ix_fanqie_bindings_binding_uuid', 'fanqie_bindings', ['binding_uuid'])
    op.create_index('ix_fanqie_bindings_id', 'fanqie_bindings', ['id'])
    op.create_index('ix_fanqie_bindings_publish_id', 'fanqie_bindings', ['publish_id'])
    op.create_index('ix_fanqie_bindings_status', 'fanqie_bindings', ['status'])
    op.create_index('ix_fanqie_bindings_task_id', 'fanqie_bindings', ['task_id'])
    # SQLite partial unique: only one successful binding per publish_id
    op.execute("""
        CREATE UNIQUE INDEX uq_fanqie_bindings_publish_success
        ON fanqie_bindings(publish_id)
        WHERE status = 'bound'
    """)

    # ── fanqie_operation_events ──
    op.create_table(
        'fanqie_operation_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_uuid', sa.String(64), nullable=False),
        sa.Column('task_id', sa.Integer(), sa.ForeignKey('fanqie_promotion_tasks.id'), nullable=True),
        sa.Column('event_type', sa.String(32), nullable=False),
        sa.Column('from_status', sa.String(32), nullable=True),
        sa.Column('to_status', sa.String(32), nullable=True),
        sa.Column('actor_type', sa.String(32), nullable=True),
        sa.Column('actor_id', sa.String(64), nullable=True),
        sa.Column('payload_json', sa.JSON(), nullable=True),
        sa.Column('artifact_path', sa.String(512), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('event_uuid'),
    )
    op.create_index('ix_fanqie_operation_events_created_at', 'fanqie_operation_events', ['created_at'])
    op.create_index('ix_fanqie_operation_events_event_type', 'fanqie_operation_events', ['event_type'])
    op.create_index('ix_fanqie_operation_events_id', 'fanqie_operation_events', ['id'])
    op.create_index('ix_fanqie_operation_events_task', 'fanqie_operation_events', ['task_id'])

    # ── fanqie_performance_daily ──
    op.create_table(
        'fanqie_performance_daily',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('publish_id', sa.Integer(), sa.ForeignKey('fanqie_publish_records.id'), nullable=False),
        sa.Column('snapshot_date', sa.String(10), nullable=False),
        sa.Column('views', sa.Integer(), nullable=True),
        sa.Column('likes', sa.Integer(), nullable=True),
        sa.Column('comments', sa.Integer(), nullable=True),
        sa.Column('shares', sa.Integer(), nullable=True),
        sa.Column('completion_rate', sa.Float(), nullable=True),
        sa.Column('fanqie_clicks', sa.Integer(), nullable=True),
        sa.Column('conversions', sa.Integer(), nullable=True),
        sa.Column('revenue', sa.Float(), nullable=True),
        sa.Column('raw_snapshot_path', sa.String(512), nullable=True),
        sa.Column('collected_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_fanqie_performance_daily_id', 'fanqie_performance_daily', ['id'])
    op.create_index('ix_fanqie_performance_daily_publish_id', 'fanqie_performance_daily', ['publish_id'])
    op.create_index('uq_fanqie_perf_daily', 'fanqie_performance_daily', ['publish_id', 'snapshot_date'], unique=True)

    # ── Extend fanqie_batch_books with fanqie_book_pk FK ──
    with op.batch_alter_table('fanqie_batch_books') as batch_op:
        batch_op.add_column(sa.Column('fanqie_book_pk', sa.Integer(), nullable=True))
        batch_op.create_index('ix_fanqie_batch_books_book_pk', ['fanqie_book_pk'])
        batch_op.create_foreign_key(
            'fk_fanqie_batch_books_book_pk',
            'fanqie_books',
            ['fanqie_book_pk'],
            ['id'],
        )


def downgrade() -> None:
    # Remove fanqie_book_pk from fanqie_batch_books
    with op.batch_alter_table('fanqie_batch_books') as batch_op:
        batch_op.drop_constraint('fk_fanqie_batch_books_book_pk', type_='foreignkey')
        batch_op.drop_index('ix_fanqie_batch_books_book_pk')
        batch_op.drop_column('fanqie_book_pk')

    op.drop_table('fanqie_performance_daily')
    op.drop_table('fanqie_operation_events')
    op.drop_table('fanqie_bindings')
    op.drop_table('fanqie_reviews')
    op.drop_table('fanqie_publish_records')
    op.drop_table('fanqie_douyin_accounts')
    op.drop_table('fanqie_video_jobs')
    op.drop_table('fanqie_script_versions')
    op.drop_table('fanqie_promotion_task_aliases')
    op.drop_table('fanqie_promotion_tasks')
    op.drop_table('fanqie_chapters')
    op.drop_table('fanqie_books')
