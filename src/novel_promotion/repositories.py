"""
src/novel_promotion/repositories.py — 番茄推书闭环数据访问层

封装查询、幂等写入和乐观锁更新。
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from .models import (
    FanqieBook,
    FanqieChapter,
    FanqiePromotionTask,
    FanqiePromotionTaskAlias,
    FanqieScriptVersion,
    FanqieVideoJob,
    FanqieDouyinAccount,
    FanqiePublishRecord,
    FanqieReview,
    FanqieOperationEvent,
    FanqiePerformanceDaily,
    TaskStatus,
    EventType,
    _utcnow,
    _new_uuid,
)
from .state_machine import can_transition, is_non_terminal_for_alias
from src.scheduler.models import FanqieBatchBook


def _now():
    return datetime.now(timezone.utc)


# ── FanqieBook ───────────────────────────────────────────────────────────────


class BookRepository:
    def __init__(self, db: Session):
        self.db = db

    def upsert_by_fanqie_id(self, fanqie_book_id: str, **fields) -> FanqieBook:
        """Insert or update a book by its fanqie_book_id. Returns the book."""
        if not fanqie_book_id:
            raise ValueError("fanqie_book_id is required for upsert")
        book = self.db.query(FanqieBook).filter(
            FanqieBook.fanqie_book_id == fanqie_book_id
        ).first()
        if book:
            for k, v in fields.items():
                if v is not None and hasattr(book, k):
                    setattr(book, k, v)
            book.updated_at = _now()
        else:
            book = FanqieBook(fanqie_book_id=fanqie_book_id, **fields)
            self.db.add(book)
        self.db.flush()
        return book

    def get_by_id(self, book_id: int) -> Optional[FanqieBook]:
        return self.db.query(FanqieBook).filter(FanqieBook.id == book_id).first()

    def get_by_fanqie_book_id(self, fanqie_book_id: str) -> Optional[FanqieBook]:
        return self.db.query(FanqieBook).filter(
            FanqieBook.fanqie_book_id == fanqie_book_id
        ).first()

    def find_or_create(self, fanqie_book_id: str, book_name: str = "") -> FanqieBook:
        """Find by fanqie_book_id or create a minimal record."""
        if fanqie_book_id:
            book = self.get_by_fanqie_book_id(fanqie_book_id)
            if book:
                if book_name and not book.book_name:
                    book.book_name = book_name
                    book.updated_at = _now()
                    self.db.flush()
                return book
        book = FanqieBook(
            fanqie_book_id=fanqie_book_id or None,
            book_name=book_name,
        )
        self.db.add(book)
        self.db.flush()
        return book

    def list_all(self) -> list[FanqieBook]:
        return self.db.query(FanqieBook).order_by(FanqieBook.id).all()


# ── FanqiePromotionTask ──────────────────────────────────────────────────────


class PromotionTaskRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **fields) -> FanqiePromotionTask:
        task = FanqiePromotionTask(
            task_uuid=fields.pop('task_uuid', _new_uuid()),
            **fields,
        )
        self.db.add(task)
        self.db.flush()
        return task

    def get_by_id(self, task_id: int) -> Optional[FanqiePromotionTask]:
        return self.db.query(FanqiePromotionTask).filter(
            FanqiePromotionTask.id == task_id
        ).first()

    def get_by_uuid(self, task_uuid: str) -> Optional[FanqiePromotionTask]:
        return self.db.query(FanqiePromotionTask).filter(
            FanqiePromotionTask.task_uuid == task_uuid
        ).first()

    def list_by_status(self, status: str) -> list[FanqiePromotionTask]:
        return self.db.query(FanqiePromotionTask).filter(
            FanqiePromotionTask.status == status
        ).order_by(FanqiePromotionTask.updated_at.desc()).all()

    def list_all(self) -> list[FanqiePromotionTask]:
        return self.db.query(FanqiePromotionTask).order_by(
            FanqiePromotionTask.id
        ).all()

    def find_by_alias(self, book_id: int, alias: str) -> Optional[FanqiePromotionTask]:
        """Find a non-terminal task by book_id + alias."""
        return self.db.query(FanqiePromotionTask).filter(
            FanqiePromotionTask.book_id == book_id,
            FanqiePromotionTask.promotion_alias == alias,
            FanqiePromotionTask.status.in_(TaskStatus.NON_TERMINAL),
        ).first()

    def transition_status(
        self,
        task: FanqiePromotionTask,
        to_status: str,
        *,
        expected_version: Optional[int] = None,
        expected_status: Optional[str] = None,
        actor_type: str = "system",
        actor_id: str = "",
        payload: Optional[dict] = None,
    ) -> bool:
        """Atomically transition task status with optimistic locking.

        Returns True on success, False on version/status mismatch.
        Side effect: appends an operation event on success.
        """
        from_status = task.status
        check = can_transition(from_status, to_status)
        if not check.allowed:
            raise ValueError(check.reason)

        ver = expected_version if expected_version is not None else task.version
        exp_status = expected_status if expected_status is not None else from_status

        result = (
            self.db.query(FanqiePromotionTask)
            .filter(
                FanqiePromotionTask.id == task.id,
                FanqiePromotionTask.version == ver,
                FanqiePromotionTask.status == exp_status,
            )
            .update(
                {
                    FanqiePromotionTask.status: to_status,
                    FanqiePromotionTask.version: ver + 1,
                    FanqiePromotionTask.updated_at: _now(),
                },
                synchronize_session=False,
            )
        )
        if result == 0:
            return False

        # Update the in-memory object
        task.status = to_status
        task.version = ver + 1
        task.updated_at = _now()

        # Append event
        event = FanqieOperationEvent(
            task_id=task.id,
            event_type=EventType.STATUS_CHANGE,
            from_status=from_status,
            to_status=to_status,
            actor_type=actor_type,
            actor_id=actor_id,
            payload_json=payload or {},
        )
        self.db.add(event)
        self.db.flush()
        return True

    def get_events(self, task_id: int) -> list[FanqieOperationEvent]:
        return (
            self.db.query(FanqieOperationEvent)
            .filter(FanqieOperationEvent.task_id == task_id)
            .order_by(FanqieOperationEvent.created_at.asc())
            .all()
        )

    def append_event(
        self,
        task_id: int,
        event_type: str,
        *,
        from_status: Optional[str] = None,
        to_status: Optional[str] = None,
        actor_type: str = "system",
        actor_id: str = "",
        payload: Optional[dict] = None,
        artifact_path: str = "",
    ) -> FanqieOperationEvent:
        event = FanqieOperationEvent(
            task_id=task_id,
            event_type=event_type,
            from_status=from_status,
            to_status=to_status,
            actor_type=actor_type,
            actor_id=actor_id,
            payload_json=payload or {},
            artifact_path=artifact_path,
        )
        self.db.add(event)
        self.db.flush()
        return event


# ── DouyinAccountRepository ──────────────────────────────────────────────────


class DouyinAccountRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_key(self, account_key: str) -> Optional[FanqieDouyinAccount]:
        return self.db.query(FanqieDouyinAccount).filter(
            FanqieDouyinAccount.account_key == account_key
        ).first()

    def upsert_by_key(self, account_key: str, **fields) -> FanqieDouyinAccount:
        acct = self.get_by_key(account_key)
        if acct:
            for k, v in fields.items():
                if v is not None and hasattr(acct, k):
                    setattr(acct, k, v)
            acct.updated_at = _now()
        else:
            acct = FanqieDouyinAccount(account_key=account_key, **fields)
            self.db.add(acct)
        self.db.flush()
        return acct

    def list_active(self) -> list[FanqieDouyinAccount]:
        return self.db.query(FanqieDouyinAccount).filter(
            FanqieDouyinAccount.status == "active"
        ).all()


# ── PublishRecordRepository ──────────────────────────────────────────────────


class PublishRecordRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **fields) -> FanqiePublishRecord:
        rec = FanqiePublishRecord(
            publish_uuid=fields.pop('publish_uuid', _new_uuid()),
            **fields,
        )
        self.db.add(rec)
        self.db.flush()
        return rec

    def get_by_douyin_video_id(self, video_id: str) -> Optional[FanqiePublishRecord]:
        return self.db.query(FanqiePublishRecord).filter(
            FanqiePublishRecord.douyin_video_id == video_id
        ).first()

    def update_sync_info(
        self,
        record_id: int,
        douyin_video_id: str,
        douyin_video_url: str = "",
        synced_at: Optional[datetime] = None,
    ) -> bool:
        """Update sync info. Returns True if updated."""
        result = (
            self.db.query(FanqiePublishRecord)
            .filter(FanqiePublishRecord.id == record_id)
            .update(
                {
                    FanqiePublishRecord.douyin_video_id: douyin_video_id,
                    FanqiePublishRecord.douyin_video_url: douyin_video_url,
                    FanqiePublishRecord.synced_at: synced_at or _now(),
                    FanqiePublishRecord.status: "published",
                    FanqiePublishRecord.updated_at: _now(),
                },
                synchronize_session=False,
            )
        )
        self.db.flush()
        return result > 0


# ── DouyinLegacyVideoRepository (read-only, douyin.db) ──────────────────────


class DouyinLegacyVideoRepository:
    """Read-only access to douyin.db:videos for cross-DB sync.

    SQLite does not support cross-database foreign keys.
    This repository only reads; NovelPromotionPublishSyncService is the sole
    writer for fanqie_publish_records.douyin_video_id.
    """

    def __init__(self, douyin_db_path: str):
        import sqlite3
        self.db_path = douyin_db_path

    def _connect(self):
        import sqlite3
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def _safe_connect(self):
        """Connect with error propagation — never swallows schema/DB errors."""
        import sqlite3
        if not self.db_path or not Path(self.db_path).exists():
            raise FileNotFoundError(f"douyin.db not found: {self.db_path}")
        return self._connect()

    def get_by_account_and_video_id(self, account_key: str, video_id: str) -> Optional[dict]:
        """Get a single video by account_key + video_id."""
        conn = self._safe_connect()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM videos WHERE account_key = ? AND video_id = ?",
                (account_key, video_id),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def list_videos(self) -> list[dict]:
        """List all videos from douyin.db (read-only)."""
        try:
            conn = self._safe_connect()
        except FileNotFoundError:
            return []
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM videos ORDER BY id")
            return [dict(r) for r in cursor.fetchall()]
        except Exception:
            raise
        finally:
            conn.close()

    def get_by_video_id(self, video_id: str) -> Optional[dict]:
        """Get a single video by douyin video_id."""
        try:
            conn = self._safe_connect()
        except FileNotFoundError:
            return None
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM videos WHERE video_id = ?", (video_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception:
            raise
        finally:
            conn.close()

    def list_with_account_key(self) -> list[dict]:
        """List videos that have an account_key (for cross-DB sync)."""
        try:
            conn = self._safe_connect()
        except FileNotFoundError:
            return []
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM videos WHERE account_key IS NOT NULL AND account_key != ''"
            )
            return [dict(r) for r in cursor.fetchall()]
        except Exception:
            raise
        finally:
            conn.close()
