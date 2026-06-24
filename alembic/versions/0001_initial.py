"""initial schema — agent / memory / scheduler tables

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-15 12:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── User profile (src/memory/models.py: UserProfile) ─────────────
    op.create_table(
        "user_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=True),
        sa.Column("default_video_mode", sa.String(length=64), nullable=True),
        sa.Column("default_tts_provider", sa.String(length=32), nullable=True),
        sa.Column("default_voice", sa.String(length=255), nullable=True),
        sa.Column("default_character", sa.String(length=128), nullable=True),
        sa.Column("default_character_position", sa.String(length=32), nullable=True),
        sa.Column("default_character_size", sa.String(length=16), nullable=True),
        sa.Column("default_bgm_volume", sa.String(length=8), nullable=True),
        sa.Column("preferred_topics", sa.JSON(), nullable=True),
        sa.Column("douyin_uid", sa.String(length=128), nullable=True),
        sa.Column("douyin_nickname", sa.String(length=255), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_user_profiles_user_id", "user_profiles", ["user_id"])

    # ── Conversation session (src/memory/models.py: ConversationSession) ─
    op.create_table(
        "conversation_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("pending_plan", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_conversation_sessions_user_id", "conversation_sessions", ["user_id"])

    # ── Conversation message (src/memory/models.py: ConversationMessage) ─
    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("skill_name", sa.String(length=128), nullable=True),
        sa.Column("tool_success", sa.Boolean(), nullable=True),
        sa.Column("tool_error", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["session_id"], ["conversation_sessions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_conversation_messages_session_id", "conversation_messages", ["session_id"]
    )
    op.create_index("ix_conversation_messages_role", "conversation_messages", ["role"])

    # ── Conversation memory (src/memory/problem_memory.py: ConversationMemory) ─
    op.create_table(
        "conversation_memory",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("memory_type", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_conversation_memory_session_id", "conversation_memory", ["session_id"]
    )

    # ── User memory (src/memory/problem_memory.py: UserMemory) ──────────
    op.create_table(
        "user_memory",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=True),
        sa.Column("memory_type", sa.String(length=64), nullable=True),
        sa.Column("key", sa.String(length=255), nullable=True),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("source_session_id", sa.Integer(), nullable=True),
        sa.Column("source_message_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_memory_user_id", "user_memory", ["user_id"])
    op.create_index("ix_user_memory_memory_type", "user_memory", ["memory_type"])

    # ── Problem memory (src/memory/problem_memory.py: ProblemMemory) ─────
    op.create_table(
        "problem_memory",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=True),
        sa.Column("problem_text", sa.Text(), nullable=True),
        sa.Column("problem_tags", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("solution", sa.Text(), nullable=True),
        sa.Column("solution_session_id", sa.Integer(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("investigation_count", sa.Integer(), nullable=True),
        sa.Column("last_investigated_at", sa.DateTime(), nullable=True),
        sa.Column("last_investigation_note", sa.Text(), nullable=True),
        sa.Column("context_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_problem_memory_user_id", "problem_memory", ["user_id"])
    op.create_index("ix_problem_memory_status", "problem_memory", ["status"])

    # ── Scheduled task (src/scheduler/models.py: ScheduledTask) ─────────
    op.create_table(
        "scheduled_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_uuid", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("task_type", sa.String(length=32), nullable=True),
        sa.Column("skill_name", sa.String(length=128), nullable=True),
        sa.Column("skill_params", sa.JSON(), nullable=True),
        sa.Column("preferences_override", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=True),
        sa.Column("trigger_type", sa.String(length=32), nullable=True),
        sa.Column("trigger_config", sa.JSON(), nullable=True),
        sa.Column("max_retries", sa.Integer(), nullable=True),
        sa.Column("retry_delay_seconds", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("next_run_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_uuid"),
    )
    op.create_index("ix_scheduled_tasks_id", "scheduled_tasks", ["id"])
    op.create_index("ix_scheduled_tasks_task_uuid", "scheduled_tasks", ["task_uuid"])
    op.create_index("ix_scheduled_tasks_name", "scheduled_tasks", ["name"])
    op.create_index("ix_scheduled_tasks_status", "scheduled_tasks", ["status"])
    op.create_index("ix_scheduled_tasks_enabled", "scheduled_tasks", ["enabled"])
    op.create_index("ix_scheduled_tasks_next_run_at", "scheduled_tasks", ["next_run_at"])

    # ── Task execution (src/scheduler/models.py: TaskExecution) ─────────
    op.create_table(
        "task_executions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("execution_uuid", sa.String(length=64), nullable=True),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("skill_params_snapshot", sa.JSON(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=True),
        sa.Column("is_retry", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["scheduled_tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("execution_uuid"),
    )
    op.create_index("ix_task_executions_id", "task_executions", ["id"])
    op.create_index(
        "ix_task_executions_execution_uuid", "task_executions", ["execution_uuid"]
    )
    op.create_index("ix_task_executions_task_id", "task_executions", ["task_id"])
    op.create_index("ix_task_executions_status", "task_executions", ["status"])


def downgrade() -> None:
    op.drop_table("task_executions")
    op.drop_table("scheduled_tasks")
    op.drop_table("problem_memory")
    op.drop_table("user_memory")
    op.drop_table("conversation_memory")
    op.drop_table("conversation_messages")
    op.drop_table("conversation_sessions")
    op.drop_table("user_profiles")
