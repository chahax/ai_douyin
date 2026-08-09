"""
src/novel_promotion/models.py — 番茄推书闭环 SQLAlchemy 模型

Tables (all in wisdom_ai.db):
  fanqie_books, fanqie_chapters, fanqie_promotion_tasks,
  fanqie_promotion_task_aliases, fanqie_script_versions, fanqie_video_jobs,
  fanqie_douyin_accounts, fanqie_publish_records, fanqie_reviews,
  fanqie_operation_events, fanqie_performance_daily
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean, ForeignKey, JSON, Float, Index,
)
from sqlalchemy.orm import relationship

from src.shared.database import Base


def _utcnow():
    """Return current UTC datetime (no deprecated utcnow)."""
    return datetime.now(timezone.utc)


def _new_uuid() -> str:
    return uuid.uuid4().hex


# ── Enums as module-level constants ──────────────────────────────────────────

class BookMaterialStatus:
    CANDIDATE = "candidate"
    SELECTED = "selected"
    FETCHING = "fetching"
    MATERIAL_READY = "material_ready"
    FETCH_FAILED = "fetch_failed"


class TaskStatus:
    APPLYING = "applying"
    UNDER_REVIEW = "under_review"
    ACTIVE = "active"
    REJECTED = "rejected"
    EXPIRED = "expired"
    APPLICATION_FAILED = "application_failed"
    MANUAL_INTERVENTION = "manual_intervention"
    CANCELLED = "cancelled"
    # Post-active states
    SCRIPTING = "scripting"
    SCRIPT_REVIEW = "script_review"
    SCRIPT_APPROVED = "script_approved"
    SCRIPT_REJECTED = "script_rejected"
    REVISION_REQUIRED = "revision_required"
    VIDEO_QUEUED = "video_queued"
    GENERATING = "generating"
    QUALITY_CHECK = "quality_check"
    REVIEW_REQUIRED = "review_required"
    APPROVED = "approved"
    REJECTED_REVIEW = "rejected_review"
    PUBLISH_QUEUED = "publish_queued"
    PUBLISHING = "publishing"
    PUBLISH_PENDING_SYNC = "publish_pending_sync"
    PUBLISHED = "published"
    PUBLISH_FAILED = "publish_failed"
    PUBLISHED_UNBOUND = "published_unbound"
    BINDING = "binding"
    BOUND = "bound"
    BINDING_FAILED = "binding_failed"
    MONITORING = "monitoring"
    COMPLETED = "completed"
    STOPPED = "stopped"

    # Non-terminal statuses for alias uniqueness check
    NON_TERMINAL = {
        APPLYING, UNDER_REVIEW, ACTIVE, APPLICATION_FAILED, MANUAL_INTERVENTION,
        SCRIPTING, SCRIPT_REVIEW, SCRIPT_APPROVED, SCRIPT_REJECTED, REVISION_REQUIRED,
        VIDEO_QUEUED, GENERATING, QUALITY_CHECK, REVIEW_REQUIRED, APPROVED, REJECTED_REVIEW,
        PUBLISH_QUEUED, PUBLISHING, PUBLISH_PENDING_SYNC, PUBLISHED, PUBLISH_FAILED, PUBLISHED_UNBOUND,
        BINDING, BINDING_FAILED, MONITORING,
    }


class VideoJobStatus:
    QUEUED = "queued"
    GENERATING = "generating"
    QUALITY_CHECK = "quality_check"
    REVIEW_REQUIRED = "review_required"
    GENERATION_FAILED = "generation_failed"
    QUALITY_FAILED = "quality_failed"


class ReviewDecision:
    APPROVED = "approved"
    REJECTED = "rejected"
    REVISION_REQUIRED = "revision_required"
    APPROVED_WITH_OVERRIDE = "approved_with_override"


class PublishStatus:
    PUBLISH_QUEUED = "publish_queued"
    PUBLISHING = "publishing"
    PUBLISH_PENDING_SYNC = "publish_pending_sync"
    PUBLISHED = "published"
    PUBLISH_FAILED = "publish_failed"
    PUBLISHED_UNBOUND = "published_unbound"


class BindingStatus:
    BINDING = "binding"
    BOUND = "bound"
    BINDING_FAILED = "binding_failed"
    MANUAL_INTERVENTION = "manual_intervention"


class EventType:
    STATUS_CHANGE = "status_change"
    IMPORT = "import"
    RECONCILE = "reconcile"
    PUBLISH_SYNC = "publish_sync"
    BINDING = "binding"
    MANUAL_ACTION = "manual_action"
    ERROR = "error"


# ── SQLAlchemy Models ────────────────────────────────────────────────────────


class FanqieBook(Base):
    """番茄小说主数据。一本番茄小说一条记录。"""
    __tablename__ = "fanqie_books"

    id = Column(Integer, primary_key=True, index=True)
    book_uuid = Column(String(64), unique=True, nullable=False, default=_new_uuid, index=True)
    fanqie_book_id = Column(String(64), unique=True, nullable=True)
    book_name = Column(String(255), nullable=False, default="")
    author = Column(String(255), nullable=False, default="")
    abstract = Column(Text, default="")
    categories_json = Column(JSON, default=list)
    tags_json = Column(JSON, default=list)
    serial_status = Column(String(32), default="")
    word_count = Column(Integer, default=0)
    source_ranking = Column(String(128), default="")
    selection_filters_json = Column(JSON, default=dict)
    selection_reason = Column(Text, default="")
    selected_by = Column(String(64), default="")
    material_status = Column(String(32), default=BookMaterialStatus.CANDIDATE)
    material_root = Column(String(512), default="")
    material_hash = Column(String(128), default="")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        Index("ix_fanqie_books_fanqie_book_id", "fanqie_book_id"),
    )


class FanqieChapter(Base):
    """章节元数据。正文保存在文件系统。"""
    __tablename__ = "fanqie_chapters"

    id = Column(Integer, primary_key=True, index=True)
    book_id = Column(Integer, ForeignKey("fanqie_books.id"), nullable=False, index=True)
    chapter_index = Column(Integer, nullable=False)
    chapter_title = Column(String(255), default="")
    source_url = Column(String(512), default="")
    content_path = Column(String(512), default="")
    content_hash = Column(String(128), default="")
    char_count = Column(Integer, default=0)
    is_paywalled = Column(Boolean, default=False)
    fetched_at = Column(DateTime, default=_utcnow)

    __table_args__ = (
        Index("uq_fanqie_chapters_book_idx", "book_id", "chapter_index", unique=True),
    )


class FanqiePromotionTask(Base):
    """番茄推广任务主表。闭环主入口。"""
    __tablename__ = "fanqie_promotion_tasks"

    id = Column(Integer, primary_key=True, index=True)
    task_uuid = Column(String(64), unique=True, nullable=False, default=_new_uuid, index=True)
    book_id = Column(Integer, ForeignKey("fanqie_books.id"), nullable=True, index=True)
    platform_task_id = Column(String(128), nullable=True)
    promotion_alias = Column(String(255), nullable=True)
    publish_type = Column(String(64), default="")
    status = Column(String(32), default=TaskStatus.APPLYING, index=True)
    failure_stage = Column(String(32), nullable=True)
    version = Column(Integer, default=1, nullable=False)
    valid_from = Column(DateTime, nullable=True)
    valid_until = Column(DateTime, nullable=True)
    application_snapshot_path = Column(String(512), default="")
    last_error = Column(Text, default="")
    manual_reason = Column(Text, default="")
    created_by = Column(String(64), default="")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    # SQLite partial unique index: same book+alias not allowed in non-terminal statuses.
    # The partial index is created in Alembic migration (SQLAlchemy doesn't support it declaratively).
    __table_args__ = ()


class FanqiePromotionTaskAlias(Base):
    """推广任务别名历史。"""
    __tablename__ = "fanqie_promotion_task_aliases"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("fanqie_promotion_tasks.id"), nullable=False, index=True)
    alias = Column(String(255), nullable=False)
    is_current = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)

    # task_id already indexed via index=True on Column


class FanqieScriptVersion(Base):
    """脚本版本。一个推广任务可有多个脚本版本。"""
    __tablename__ = "fanqie_script_versions"

    id = Column(Integer, primary_key=True, index=True)
    script_uuid = Column(String(64), unique=True, nullable=False, default=_new_uuid)
    task_id = Column(Integer, ForeignKey("fanqie_promotion_tasks.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    parent_script_id = Column(Integer, nullable=True)
    chapter_range = Column(String(128), default="")
    hook = Column(Text, default="")
    script_text = Column(Text, default="")
    title = Column(String(255), default="")
    description = Column(Text, default="")
    hashtags_json = Column(JSON, default=list)
    cta = Column(String(255), default="")
    spoiler_level = Column(String(32), default="low")
    model_name = Column(String(128), default="")
    prompt_version = Column(String(64), default="")
    generation_params_json = Column(JSON, default=dict)
    status = Column(String(32), default="draft")
    content_hash = Column(String(128), default="")
    created_at = Column(DateTime, default=_utcnow)

    __table_args__ = (
        Index("uq_fanqie_scripts_task_version", "task_id", "version", unique=True),
    )


class FanqieVideoJob(Base):
    """视频生成任务。每个视频候选一条记录。"""
    __tablename__ = "fanqie_video_jobs"

    id = Column(Integer, primary_key=True, index=True)
    job_uuid = Column(String(64), unique=True, nullable=False, default=_new_uuid, index=True)
    task_id = Column(Integer, ForeignKey("fanqie_promotion_tasks.id"), nullable=False, index=True)
    script_id = Column(Integer, ForeignKey("fanqie_script_versions.id"), nullable=False, index=True)
    video_mode = Column(String(64), default="presenter_anime")
    quality_profile = Column(String(32), default="standard")
    status = Column(String(32), default=VideoJobStatus.QUEUED, index=True)
    failure_stage = Column(String(32), nullable=True)
    error_message = Column(Text, default="")
    request_path = Column(String(512), default="")
    manifest_path = Column(String(512), default="")
    output_path = Column(String(512), default="")
    quality_report_path = Column(String(512), default="")
    review_packet_path = Column(String(512), default="")
    output_sha256 = Column(String(128), default="")
    runtime_json = Column(JSON, default=dict)
    duration_ms = Column(Integer, default=0)
    cost_json = Column(JSON, default=dict)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    # task_id, script_id, status, job_uuid already indexed via index=True on Column


class FanqieDouyinAccount(Base):
    """抖音多账号运营主数据表。"""
    __tablename__ = "fanqie_douyin_accounts"

    id = Column(Integer, primary_key=True, index=True)
    account_uuid = Column(String(64), unique=True, nullable=False, default=_new_uuid)
    account_key = Column(String(128), unique=True, nullable=False, index=True)
    display_name = Column(String(255), default="")
    masked_login_name = Column(String(64), default="")
    status = Column(String(32), default="active")
    profile_dir = Column(String(512), default="")
    platform_uid = Column(String(128), default="")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class FanqiePublishRecord(Base):
    """抖音发布记录。"""
    __tablename__ = "fanqie_publish_records"

    id = Column(Integer, primary_key=True, index=True)
    publish_uuid = Column(String(64), unique=True, nullable=False, default=_new_uuid, index=True)
    task_id = Column(Integer, ForeignKey("fanqie_promotion_tasks.id"), nullable=False, index=True)
    video_job_id = Column(Integer, ForeignKey("fanqie_video_jobs.id"), nullable=True, index=True)
    douyin_account_id = Column(Integer, ForeignKey("fanqie_douyin_accounts.id"), nullable=True, index=True)
    status = Column(String(32), default=PublishStatus.PUBLISH_QUEUED, index=True)
    title_snapshot = Column(String(255), default="")
    description_snapshot = Column(Text, default="")
    hashtags_json = Column(JSON, default=list)
    douyin_video_id = Column(String(128), nullable=True, unique=True)
    douyin_video_url = Column(String(512), nullable=True, unique=True)
    published_at = Column(DateTime, nullable=True)
    synced_at = Column(DateTime, nullable=True)
    platform_response_path = Column(String(512), default="")
    last_error = Column(Text, default="")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    # douyin_video_id already unique=True on Column (auto-indexed)
    # task_id, video_job_id, douyin_account_id, status, publish_uuid already indexed


class FanqieReview(Base):
    """人工审核记录。"""
    __tablename__ = "fanqie_reviews"

    id = Column(Integer, primary_key=True, index=True)
    review_uuid = Column(String(64), unique=True, nullable=False, default=_new_uuid)
    video_job_id = Column(Integer, ForeignKey("fanqie_video_jobs.id"), nullable=False, index=True)
    decision = Column(String(32), nullable=False, default=ReviewDecision.APPROVED)
    reviewer = Column(String(64), default="")
    reviewed_at = Column(DateTime, default=_utcnow)
    issues_json = Column(JSON, default=list)
    comment = Column(Text, default="")
    machine_gate_passed = Column(Boolean, default=False)
    override_reason = Column(Text, default="")
    approved_sha256 = Column(String(128), default="")
    created_at = Column(DateTime, default=_utcnow)


class FanqieOperationEvent(Base):
    """操作事件表。追加写，不更新不删除。"""
    __tablename__ = "fanqie_operation_events"

    id = Column(Integer, primary_key=True, index=True)
    event_uuid = Column(String(64), unique=True, nullable=False, default=_new_uuid)
    task_id = Column(Integer, ForeignKey("fanqie_promotion_tasks.id"), nullable=True, index=True)
    event_type = Column(String(32), nullable=False, default=EventType.STATUS_CHANGE, index=True)
    from_status = Column(String(32), nullable=True)
    to_status = Column(String(32), nullable=True)
    actor_type = Column(String(32), default="system")
    actor_id = Column(String(64), default="")
    payload_json = Column(JSON, default=dict)
    artifact_path = Column(String(512), default="")
    created_at = Column(DateTime, default=_utcnow, index=True)

    # task_id, event_type, created_at already indexed via index=True on Column


class FanqiePerformanceDaily(Base):
    """每日效果数据快照。"""
    __tablename__ = "fanqie_performance_daily"

    id = Column(Integer, primary_key=True, index=True)
    publish_id = Column(Integer, ForeignKey("fanqie_publish_records.id"), nullable=False, index=True)
    snapshot_date = Column(String(10), nullable=False)  # YYYY-MM-DD
    views = Column(Integer, default=0)
    likes = Column(Integer, default=0)
    comments = Column(Integer, default=0)
    shares = Column(Integer, default=0)
    completion_rate = Column(Float, nullable=True)
    fanqie_clicks = Column(Integer, default=0)
    conversions = Column(Integer, default=0)
    revenue = Column(Float, default=0.0)
    raw_snapshot_path = Column(String(512), default="")
    collected_at = Column(DateTime, default=_utcnow)

    __table_args__ = (
        Index("uq_fanqie_perf_daily", "publish_id", "snapshot_date", unique=True),
    )


class FanqieBinding(Base):
    """番茄回填绑定记录 (Section 5.8)。"""
    __tablename__ = "fanqie_bindings"

    id = Column(Integer, primary_key=True, index=True)
    binding_uuid = Column(String(64), unique=True, nullable=False, default=_new_uuid, index=True)
    task_id = Column(Integer, ForeignKey("fanqie_promotion_tasks.id"), nullable=False, index=True)
    publish_id = Column(Integer, ForeignKey("fanqie_publish_records.id"), nullable=False, index=True)
    status = Column(String(32), default=BindingStatus.BINDING, index=True)
    attempt_count = Column(Integer, default=0)
    submitted_url = Column(String(512), default="")
    response_snapshot_path = Column(String(512), default="")
    screenshot_path = Column(String(512), default="")
    bound_at = Column(DateTime, nullable=True)
    last_attempt_at = Column(DateTime, nullable=True)
    operator = Column(String(64), default="")
    last_error = Column(Text, default="")
    created_at = Column(DateTime, default=_utcnow)

    __table_args__ = (
        # One successful binding per publish_id
        Index("uq_fanqie_bindings_publish_success", "publish_id", unique=True,
              postgresql_where=None),  # SQLite partial handled in migration
    )
