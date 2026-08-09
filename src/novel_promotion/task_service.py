"""
src/novel_promotion/task_service.py — 推广任务事务服务和事件管理

负责:
- 事务边界
- 状态转换 + 事件追加（同事务）
- 任务创建 / 查询 / 状态同步
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from .models import (
    FanqiePromotionTask,
    FanqiePromotionTaskAlias,
    FanqieOperationEvent,
    FanqieBook,
    TaskStatus,
    EventType,
    _utcnow,
)
from .repositories import (
    BookRepository,
    PromotionTaskRepository,
)
from .state_machine import can_transition, map_old_status


def _now():
    return datetime.now(timezone.utc)


class TaskService:
    """Main service for promotion task operations with transaction + events."""

    def __init__(self, db: Session):
        self.db = db
        self.book_repo = BookRepository(db)
        self.task_repo = PromotionTaskRepository(db)

    def create_task(
        self,
        book_id: int,
        promotion_alias: str = "",
        publish_type: str = "",
        created_by: str = "",
        platform_task_id: Optional[str] = None,
    ) -> FanqiePromotionTask:
        """Create a new promotion task within a transaction.

        Checks for duplicate aliases on non-terminal tasks.
        """
        if promotion_alias:
            existing = self.task_repo.find_by_alias(book_id, promotion_alias)
            if existing:
                raise ValueError(
                    f"Active task already exists for book_id={book_id} "
                    f"alias='{promotion_alias}' (task_id={existing.id})"
                )

        task = self.task_repo.create(
            book_id=book_id,
            promotion_alias=promotion_alias,
            publish_type=publish_type,
            created_by=created_by,
            platform_task_id=platform_task_id,
            status=TaskStatus.APPLYING,
        )

        # Add alias record
        if promotion_alias:
            self.db.add(FanqiePromotionTaskAlias(
                task_id=task.id,
                alias=promotion_alias,
                is_current=True,
            ))

        # Append creation event
        self.task_repo.append_event(
            task.id,
            EventType.STATUS_CHANGE,
            from_status=None,
            to_status=TaskStatus.APPLYING,
            actor_type="user" if created_by else "system",
            actor_id=created_by,
        )

        self.db.commit()
        return task

    def set_status(
        self,
        task_id: int,
        new_status: str,
        *,
        actor_type: str = "system",
        actor_id: str = "",
        payload: Optional[dict] = None,
        expected_version: Optional[int] = None,
        expected_status: Optional[str] = None,
    ) -> FanqiePromotionTask:
        """Atomically transition task status with optimistic lock.

        All changes (status + event) happen in one transaction.
        Raises ValueError on invalid transitions or version conflicts.
        """
        task = self.task_repo.get_by_id(task_id)
        if task is None:
            raise ValueError(f"Task not found: id={task_id}")

        success = self.task_repo.transition_status(
            task,
            new_status,
            expected_version=expected_version,
            expected_status=expected_status,
            actor_type=actor_type,
            actor_id=actor_id,
            payload=payload,
        )
        if not success:
            self.db.rollback()
            raise ValueError(
                f"Optimistic lock conflict: task {task_id} was modified "
                f"by another process (expected version={expected_version or task.version}, "
                f"status='{expected_status or task.status}')"
            )

        self.db.commit()
        return task

    def sync_status_from_platform(
        self,
        task_id: int,
        platform_status: str,
        *,
        actor_type: str = "platform_sync",
    ) -> Optional[FanqiePromotionTask]:
        """Map old apply_status to new state and transition if valid."""
        new_status = map_old_status(platform_status)
        task = self.task_repo.get_by_id(task_id)
        if task is None:
            return None

        if new_status == task.status:
            return task

        check = can_transition(task.status, new_status)
        if not check.allowed:
            # If transition not allowed, log a reconcile event instead
            self.task_repo.append_event(
                task.id,
                EventType.ERROR,
                from_status=task.status,
                to_status=new_status,
                actor_type=actor_type,
                payload={"reason": check.reason, "platform_status": platform_status},
            )
            self.db.commit()
            return task

        return self.set_status(
            task_id,
            new_status,
            actor_type=actor_type,
            payload={"platform_status": platform_status},
        )

    def get_task(self, task_id: int) -> Optional[FanqiePromotionTask]:
        return self.task_repo.get_by_id(task_id)

    def get_task_by_uuid(self, task_uuid: str) -> Optional[FanqiePromotionTask]:
        return self.task_repo.get_by_uuid(task_uuid)

    def list_tasks(self, status: Optional[str] = None) -> list[FanqiePromotionTask]:
        if status:
            return self.task_repo.list_by_status(status)
        return self.task_repo.list_all()

    def get_events(self, task_id: int) -> list[FanqieOperationEvent]:
        return self.task_repo.get_events(task_id)

    def add_event(
        self,
        task_id: int,
        event_type: str,
        **kwargs,
    ) -> FanqieOperationEvent:
        event = self.task_repo.append_event(task_id, event_type, **kwargs)
        self.db.commit()
        return event
