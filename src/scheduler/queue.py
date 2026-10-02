# -*- coding: utf-8 -*-
"""
src/scheduler/queue.py — 任务队列核心

职责：
  - 入队：创建 TaskExecution 记录
  - 轮询：从数据库捞 pending 任务，分配给 worker
  - 执行：调 Agent/Skill，捕获结果
  - 重试：根据配置重试失败任务
  - 查询：任务状态 / 历史
"""

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from src.memory import MemoryManager
from src.scheduler.models import ScheduledTask, TaskExecution, TaskStatus, TaskType
from src.shared.database import SessionLocal
from src.shared.logger import logger

log = logging.getLogger(__name__)


@dataclass
class EnqueueResult:
    success: bool
    execution_uuid: str = ""
    message: str = ""


class TaskQueue:
    """
    任务队列管理器。

    负责：
    1. 将任务加入执行队列（创建 TaskExecution）
    2. Worker 轮询并执行
    3. 重试逻辑
    """

    def __init__(
        self,
        session: Optional[Session] = None,
        *,
        owner_id: str | None = None,
        lease_seconds: int = 120,
    ):
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        self._own_session = session is None
        self._session = session or SessionLocal()
        self._owner_id = owner_id or f"worker-{uuid.uuid4().hex}"
        self._lease_seconds = lease_seconds

    def close(self):
        if self._own_session:
            self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # -------------------------------------------------------------------------
    # 入队
    # -------------------------------------------------------------------------

    def enqueue(self, task_id: int, skill_params: Optional[dict] = None) -> EnqueueResult:
        """将任务加入执行队列。返回 execution_uuid。"""
        task = self._session.query(ScheduledTask).filter_by(id=task_id).first()
        if not task:
            return EnqueueResult(success=False, message=f"任务 {task_id} 不存在")

        if task.status == TaskStatus.CANCELLED.value:
            return EnqueueResult(success=False, message="任务已取消，无法入队")

        from src.operations_accounts.task_scope import freeze_task_scope
        try:
            params = freeze_task_scope(skill_params if skill_params is not None else task.skill_params or {})
        except (ValueError, KeyError) as exc:
            return EnqueueResult(success=False, message=str(exc))
        # 创建执行记录
        execution = TaskExecution(
            execution_uuid=uuid.uuid4().hex,
            task_id=task_id,
            skill_params_snapshot=params,
            status=TaskStatus.PENDING.value,
            attempt=1,
        )
        self._session.add(execution)
        self._session.commit()
        self._session.refresh(execution)

        logger.info(f"任务入队: task_id={task_id}, execution_uuid={execution.execution_uuid}")
        return EnqueueResult(
            success=True,
            execution_uuid=execution.execution_uuid,
            message=f"任务已加入队列: {execution.execution_uuid}",
        )

    def enqueue_now(self, skill_name: str, skill_params: dict, name: str = "临时任务") -> EnqueueResult:
        """
        快速入队：直接创建一次性任务并立即执行（不持久化到 scheduled_tasks）。
        用于 immediate 类型的任务。
        """
        task = ScheduledTask(
            task_uuid=uuid.uuid4().hex,
            name=name,
            skill_name=skill_name,
            skill_params=skill_params,
            task_type=TaskType.QUEUE.value,
            status=TaskStatus.PENDING.value,
            enabled=True,
            trigger_type="immediate",
        )
        self._session.add(task)
        self._session.commit()
        self._session.refresh(task)
        return self.enqueue(task.id, skill_params)

    # -------------------------------------------------------------------------
    # Worker：抢任务并执行
    # -------------------------------------------------------------------------

    def claim_next(self) -> Optional[TaskExecution]:
        """Atomically claim one pending execution, including on SQLite.

        Candidate selection may race, but the conditional ``pending ->
        running`` update cannot be won by two workers. The loser returns no
        work and polls again; it never executes the same row.
        """
        now = datetime.utcnow()
        candidate = (
            self._session.query(TaskExecution)
            .filter(
                TaskExecution.status == TaskStatus.PENDING.value,
                (TaskExecution.next_retry_at.is_(None))
                | (TaskExecution.next_retry_at <= now),
                TaskExecution.task_id.in_(
                    self._session.query(ScheduledTask.id).filter(
                        ScheduledTask.enabled == True,
                        ScheduledTask.status != TaskStatus.CANCELLED.value,
                    )
                ),
            )
            .order_by(TaskExecution.created_at.asc())
            .with_entities(TaskExecution.id)
            .first()
        )
        candidate_id = candidate[0] if candidate is not None else None
        if candidate_id is None:
            return None
        claimed = (
            self._session.query(TaskExecution)
            .filter(
                TaskExecution.id == candidate_id,
                TaskExecution.status == TaskStatus.PENDING.value,
            )
            .update(
                {
                    TaskExecution.status: TaskStatus.RUNNING.value,
                    TaskExecution.started_at: now,
                    TaskExecution.claim_owner: self._owner_id,
                    TaskExecution.heartbeat_at: now,
                    TaskExecution.lease_expires_at: now + timedelta(
                        seconds=self._lease_seconds
                    ),
                },
                synchronize_session=False,
            )
        )
        if claimed != 1:
            self._session.rollback()
            return None
        self._session.commit()
        return self._session.get(TaskExecution, candidate_id)

    def mark_running(self, execution: TaskExecution) -> None:
        """Claim a directly supplied row or refresh this worker's lease."""
        now = datetime.utcnow()
        if execution.status == TaskStatus.RUNNING.value:
            renewed = (
                self._session.query(TaskExecution)
                .filter(
                    TaskExecution.id == execution.id,
                    TaskExecution.status == TaskStatus.RUNNING.value,
                    TaskExecution.claim_owner == self._owner_id,
                    TaskExecution.lease_expires_at >= now,
                )
                .update({
                    TaskExecution.heartbeat_at: now,
                    TaskExecution.lease_expires_at: now + timedelta(seconds=self._lease_seconds),
                }, synchronize_session=False)
            )
            if renewed != 1:
                self._session.rollback()
                raise RuntimeError("execution lease is expired or owned by another worker")
            self._session.commit()
            self._session.refresh(execution)
            return
        claimed = (
            self._session.query(TaskExecution)
            .filter(
                TaskExecution.id == execution.id,
                TaskExecution.status == TaskStatus.PENDING.value,
            )
            .update(
                {
                    TaskExecution.status: TaskStatus.RUNNING.value,
                    TaskExecution.started_at: now,
                    TaskExecution.claim_owner: self._owner_id,
                    TaskExecution.heartbeat_at: now,
                    TaskExecution.lease_expires_at: now + timedelta(
                        seconds=self._lease_seconds
                    ),
                },
                synchronize_session=False,
            )
        )
        if claimed != 1:
            self._session.rollback()
            raise RuntimeError("execution could not be claimed")
        self._session.commit()
        self._session.refresh(execution)

    def heartbeat(self, execution: TaskExecution) -> None:
        """Extend a lease only when this queue still owns the running row."""
        now = datetime.utcnow()
        updated = (
            self._session.query(TaskExecution)
            .filter(
                TaskExecution.id == execution.id,
                TaskExecution.status == TaskStatus.RUNNING.value,
                TaskExecution.claim_owner == self._owner_id,
                TaskExecution.lease_expires_at >= now,
            )
            .update(
                {
                    TaskExecution.heartbeat_at: now,
                    TaskExecution.lease_expires_at: now + timedelta(
                        seconds=self._lease_seconds
                    ),
                },
                synchronize_session=False,
            )
        )
        if updated != 1:
            self._session.rollback()
            raise RuntimeError("execution lease is no longer owned by this worker")
        self._session.commit()
        self._session.refresh(execution)

    def _transition_owned(
        self,
        sess: Session,
        execution: TaskExecution,
        values: dict,
    ) -> bool:
        """Persist a result only while this worker still owns a live lease."""
        now = datetime.utcnow()
        updates = {
            **values,
            TaskExecution.claim_owner: None,
            TaskExecution.lease_expires_at: None,
            TaskExecution.heartbeat_at: None,
        }
        changed = (
            sess.query(TaskExecution)
            .filter(
                TaskExecution.id == execution.id,
                TaskExecution.status == TaskStatus.RUNNING.value,
                TaskExecution.claim_owner == self._owner_id,
                TaskExecution.lease_expires_at >= now,
            )
            .update(updates, synchronize_session=False)
        )
        if changed != 1:
            sess.rollback()
            return False
        sess.commit()
        sess.expire(execution)
        return True

    def _call_with_lease_heartbeat(
        self,
        registry,
        skill_name: str,
        params: dict,
        execution: TaskExecution,
    ) -> tuple[dict, bool]:
        """Run a skill while a separate DB session renews the worker lease."""
        stop = threading.Event()
        lease_lost = threading.Event()
        interval = max(0.05, min(self._lease_seconds / 3, 5.0))

        def maintain_lease() -> None:
            while not stop.wait(interval):
                try:
                    with SessionLocal() as heartbeat_session:
                        current = heartbeat_session.get(TaskExecution, execution.id)
                        if current is None:
                            raise RuntimeError("execution disappeared during skill call")
                        heartbeat_queue = TaskQueue(
                            heartbeat_session,
                            owner_id=self._owner_id,
                            lease_seconds=self._lease_seconds,
                        )
                        heartbeat_queue.heartbeat(current)
                except Exception:
                    lease_lost.set()
                    logger.exception(
                        "Worker 心跳失败，放弃迟到结果: %s",
                        execution.execution_uuid,
                    )
                    return

        heartbeat_thread = threading.Thread(
            target=maintain_lease,
            name=f"lease-heartbeat-{execution.execution_uuid[:8]}",
            daemon=True,
        )
        heartbeat_thread.start()
        try:
            result = registry.call(skill_name, params)
            return result, lease_lost.is_set()
        finally:
            stop.set()
            heartbeat_thread.join(timeout=max(1.0, interval * 2))

    def recover_expired_leases(
        self,
        *,
        now: datetime | None = None,
        legacy_stale_minutes: int = 30,
    ) -> int:
        """Stop expired work without assuming its external outcome is failure."""
        now = now or datetime.utcnow()
        legacy_threshold = now - timedelta(minutes=legacy_stale_minutes)
        stale = (
            self._session.query(TaskExecution)
            .filter(TaskExecution.status == TaskStatus.RUNNING.value)
            .filter(
                ((TaskExecution.lease_expires_at != None)  # noqa: E711
                 & (TaskExecution.lease_expires_at < now))
                | ((TaskExecution.lease_expires_at == None)  # noqa: E711
                   & (TaskExecution.started_at != None)  # noqa: E711
                   & (TaskExecution.started_at < legacy_threshold))
            )
            .with_entities(
                TaskExecution.id,
                TaskExecution.lease_expires_at,
                TaskExecution.started_at,
            )
            .all()
        )
        recovered = 0
        for execution_id, lease_expiry, started_at in stale:
            stale_filter = [
                TaskExecution.id == execution_id,
                TaskExecution.status == TaskStatus.RUNNING.value,
            ]
            if lease_expiry is not None:
                stale_filter.extend([
                    TaskExecution.lease_expires_at == lease_expiry,
                    TaskExecution.lease_expires_at < now,
                ])
            else:
                stale_filter.extend([
                    TaskExecution.lease_expires_at.is_(None),
                    TaskExecution.started_at == started_at,
                    TaskExecution.started_at < legacy_threshold,
                ])
            recovered += self._session.query(TaskExecution).filter(*stale_filter).update({
                TaskExecution.status: TaskStatus.OUTCOME_UNKNOWN.value,
                TaskExecution.error_message: (
                    "Worker 租约已失效；原操作可能仍有外部结果，"
                    "必须按原请求核对后再决定是否重试。"
                ),
                TaskExecution.claim_owner: None,
                TaskExecution.lease_expires_at: None,
                TaskExecution.heartbeat_at: None,
            }, synchronize_session=False)
        if recovered:
            self._session.commit()
        else:
            self._session.rollback()
        return recovered

    def mark_completed(
        self,
        execution: TaskExecution,
        result: dict,
        result_summary: str = "",
    ) -> bool:
        completed_at = datetime.utcnow()
        duration = int((completed_at - execution.started_at).total_seconds()) if execution.started_at else None
        return self._transition_owned(self._session, execution, {
            TaskExecution.status: TaskStatus.COMPLETED.value,
            TaskExecution.result: result,
            TaskExecution.result_summary: result_summary,
            TaskExecution.completed_at: completed_at,
            TaskExecution.duration_seconds: duration,
        })

    def mark_outcome_unknown(self, execution: TaskExecution, error: str) -> bool:
        """Persist an unresolved side effect without scheduling a retry."""
        return self._transition_owned(self._session, execution, {
            TaskExecution.status: TaskStatus.OUTCOME_UNKNOWN.value,
            TaskExecution.error_message: error,
        })

    def mark_awaiting_verification(
        self,
        execution: TaskExecution,
        result: dict,
    ) -> bool:
        """Persist a submitted external action that is not finally verified."""
        return self._transition_owned(self._session, execution, {
            TaskExecution.status: TaskStatus.AWAITING_VERIFICATION.value,
            TaskExecution.result: result,
            TaskExecution.result_summary: "平台已接受提交，等待发布后核验；保留提交锁",
        })

    @staticmethod
    def _awaits_verification(result: dict) -> bool:
        status = result.get("status")
        if status is None and isinstance(result.get("data"), dict):
            status = result["data"].get("status")
        return status == "post_publish_verification_pending"

    def mark_failed(
        self,
        execution: TaskExecution,
        error: str,
        should_retry: bool = False,
    ) -> bool:
        task = execution.task
        # should_retry 已经由调用方根据「attempt <= max_retries」算出，这里只负责写状态
        if should_retry and execution.attempt <= task.max_retries:
            # 延迟重试（Phase 3 实现 retry_delay_seconds）
            from datetime import timedelta
            delay = task.retry_delay_seconds or 60
            saved = self._transition_owned(self._session, execution, {
                TaskExecution.status: TaskStatus.PENDING.value,
                TaskExecution.is_retry: True,
                TaskExecution.attempt: execution.attempt + 1,
                TaskExecution.next_retry_at: datetime.utcnow() + timedelta(seconds=delay),
                TaskExecution.error_message: error,
            })
            if saved:
                logger.info(
                    f"任务 {execution.execution_uuid} 失败，{delay}s 后安排第 {execution.attempt + 1} 次重试"
                )
            return saved
        else:
            completed_at = datetime.utcnow()
            duration = int((completed_at - execution.started_at).total_seconds()) if execution.started_at else None
            saved = self._transition_owned(self._session, execution, {
                TaskExecution.status: TaskStatus.FAILED.value,
                TaskExecution.error_message: error,
                TaskExecution.completed_at: completed_at,
                TaskExecution.duration_seconds: duration,
            })
            if not saved:
                return False
            logger.error(f"任务 {execution.execution_uuid} 最终失败: {error}")
            return True

    # -------------------------------------------------------------------------
    # 执行单个任务
    # -------------------------------------------------------------------------

    def execute_one(self, execution: TaskExecution) -> None:
        """同步执行单个任务（由 Worker 调用）"""
        self.mark_running(execution)

        task = execution.task
        skill_name = task.skill_name
        params = execution.skill_params_snapshot

        # 如果任务有用户偏好覆盖，先应用
        if task.preferences_override:
            self._apply_preferences(task.preferences_override)

        try:
            from src.operations_accounts.task_scope import validate_task_scope
            try:
                params = validate_task_scope(params)
            except (ValueError, KeyError) as exc:
                self.mark_failed(execution, str(exc), should_retry=False)
                return
            # 从 registry 获取 Skill 并执行
            from src.agent.registry import SkillRegistry

            registry = SkillRegistry()
            result, lease_lost = self._call_with_lease_heartbeat(
                registry, skill_name, params, execution,
            )

            if lease_lost:
                self.mark_outcome_unknown(
                    execution,
                    "执行期间无法确认租约仍由本 Worker 持有；丢弃迟到结果并按原请求核对。",
                )
                return

            if result.get("success") and self._awaits_verification(result):
                self.mark_awaiting_verification(execution, result)
            elif result.get("success"):
                summary = self._summarize_result(skill_name, result)
                self.mark_completed(execution, result, summary)
                log.info(f"任务完成: {execution.execution_uuid}")
            elif result.get("code") == "outcome_unknown":
                self.mark_outcome_unknown(
                    execution,
                    result.get("message") or "外部操作结果待确认",
                )
            else:
                task_obj = task
                should_retry = execution.attempt <= task_obj.max_retries
                self.mark_failed(
                    execution,
                    result.get("error", "未知错误"),
                    should_retry=should_retry,
                )
        except Exception as exc:
            should_retry = execution.attempt <= task.max_retries
            self.mark_failed(execution, str(exc), should_retry=should_retry)
            logger.exception(f"任务执行异常: {execution.execution_uuid}")

    # -------------------------------------------------------------------------
    # Worker 循环
    # -------------------------------------------------------------------------

    def worker_loop(self, poll_interval: int = 5, stop_event=None):
        """
        后台 Worker 主循环。

        :param poll_interval: 轮询间隔（秒）
        :param stop_event: threading.Event，可选用于优雅停止
        """
        logger.info("TaskQueue Worker 启动")

        # 自愈：Worker 启动时扫一次，把超期还卡在 running 的执行强制 mark failed
        # 避免上次进程崩了导致 dashboard 上一直挂着假"运行中"任务
        try:
            with SessionLocal() as sess:
                recovered = TaskQueue(
                    sess,
                    owner_id=self._owner_id,
                    lease_seconds=self._lease_seconds,
                ).recover_expired_leases()
                if recovered:
                    logger.warning(
                        f"[worker_loop 自愈] 标记 {recovered} 条超期 running → outcome_unknown"
                    )
        except Exception:
            logger.exception("[worker_loop 自愈] 失败（不影响主循环）")

        while True:
            if stop_event and stop_event.is_set():
                logger.info("TaskQueue Worker 收到停止信号，退出")
                break

            with SessionLocal() as sess:
                self._session = sess
                row = self.claim_next()

                if not row:
                    time.sleep(poll_interval)
                    continue

                self._execute_sync(row, sess)

            time.sleep(1)

    def _execute_sync(self, execution: TaskExecution, sess: Session) -> None:
        """在指定 session 中同步执行（避免 session 跨线程问题）

        Phase 3 改造：
          1. result.success=False 分支末尾 fire-and-forget ErrorReviewer
          2. except 分支修 retry 语义（与 success=False 分支一致）
          3. except 分支末尾 fire-and-forget ErrorReviewer
        """
        from src.agent.registry import SkillRegistry

        task = execution.task
        skill_name = task.skill_name
        params = execution.skill_params_snapshot
        delay = task.retry_delay_seconds or 60

        try:
            registry = SkillRegistry()
            result, lease_lost = self._call_with_lease_heartbeat(
                registry, skill_name, params, execution,
            )

            if lease_lost:
                self._transition_owned(sess, execution, {
                    TaskExecution.status: TaskStatus.OUTCOME_UNKNOWN.value,
                    TaskExecution.error_message: (
                        "执行期间无法确认租约仍由本 Worker 持有；"
                        "丢弃迟到结果并按原请求核对。"
                    ),
                })
                return

            if result.get("success") and self._awaits_verification(result):
                self._transition_owned(sess, execution, {
                    TaskExecution.status: TaskStatus.AWAITING_VERIFICATION.value,
                    TaskExecution.result: result,
                    TaskExecution.result_summary: "平台已接受提交，等待发布后核验；保留提交锁",
                })
            elif result.get("success"):
                summary = self._summarize_result(skill_name, result)
                completed_at = datetime.utcnow()
                duration = int((completed_at - execution.started_at).total_seconds()) if execution.started_at else None
                self._transition_owned(sess, execution, {
                    TaskExecution.status: TaskStatus.COMPLETED.value,
                    TaskExecution.result: result,
                    TaskExecution.result_summary: summary,
                    TaskExecution.completed_at: completed_at,
                    TaskExecution.duration_seconds: duration,
                })
            elif result.get("code") == "outcome_unknown":
                self._transition_owned(sess, execution, {
                    TaskExecution.status: TaskStatus.OUTCOME_UNKNOWN.value,
                    TaskExecution.error_message: result.get("message") or "外部操作结果待确认",
                })
            else:
                should_retry = execution.attempt <= task.max_retries
                error_msg = result.get("error", "未知错误")
                if should_retry:
                    values = {
                        TaskExecution.status: TaskStatus.PENDING.value,
                        TaskExecution.is_retry: True,
                        TaskExecution.attempt: execution.attempt + 1,
                        TaskExecution.next_retry_at: datetime.utcnow() + timedelta(seconds=delay),
                    }
                else:
                    completed_at = datetime.utcnow()
                    values = {
                        TaskExecution.status: TaskStatus.FAILED.value,
                        TaskExecution.completed_at: completed_at,
                        TaskExecution.duration_seconds: (
                            int((completed_at - execution.started_at).total_seconds())
                            if execution.started_at else None
                        ),
                    }
                values[TaskExecution.error_message] = error_msg
                saved = self._transition_owned(sess, execution, values)
                # fire-and-forget 错误诊断（仅最终失败触发，避免重试期间风暴）
                if saved and not should_retry:
                    self._fire_error_review(execution, error_msg, result)
        except Exception as exc:
            should_retry = execution.attempt <= task.max_retries
            error_msg = str(exc)
            if should_retry:
                values = {
                    TaskExecution.status: TaskStatus.PENDING.value,
                    TaskExecution.is_retry: True,
                    TaskExecution.attempt: execution.attempt + 1,
                    TaskExecution.next_retry_at: datetime.utcnow() + timedelta(seconds=delay),
                    TaskExecution.error_message: error_msg,
                }
            else:
                completed_at = datetime.utcnow()
                values = {
                    TaskExecution.status: TaskStatus.FAILED.value,
                    TaskExecution.completed_at: completed_at,
                    TaskExecution.duration_seconds: (
                        int((completed_at - execution.started_at).total_seconds())
                        if execution.started_at else None
                    ),
                    TaskExecution.error_message: error_msg,
                }
            saved = self._transition_owned(sess, execution, values)
            logger.exception(f"Worker 执行异常: {execution.execution_uuid}")
            # fire-and-forget 错误诊断
            if saved and not should_retry:
                self._fire_error_review(execution, error_msg, None, exc)

    def _fire_error_review(
        self,
        execution: TaskExecution,
        error_msg: str,
        result: dict | None,
        exc: Exception | None = None,
    ) -> None:
        """Phase 3: 触发 ErrorReviewer 异步诊断 worker 失败。"""
        try:
            from src.agent.error_reviewer import error_reviewer
            from src.shared.async_runner import fire_and_forget

            task = execution.task
            if exc is None:
                # 用 result.get("error") 字符串构造伪 exc
                exc = RuntimeError(error_msg)
            fire_and_forget(
                error_reviewer.review_and_store_async(
                    source="worker_task",
                    location=f"task:{execution.execution_uuid}",
                    exc=exc,
                    context_extra={
                        "skill_name": task.skill_name,
                        "skill_params": execution.skill_params_snapshot,
                        "attempt": execution.attempt,
                        "result": result,
                    },
                ),
                name="worker-error-review",
            )
        except Exception:
            logger.exception("fire worker error_reviewer 失败")

    # -------------------------------------------------------------------------
    # 工具
    # -------------------------------------------------------------------------

    def _apply_preferences(self, prefs: dict) -> None:
        """临时应用用户偏好覆盖（当前会话有效）"""
        try:
            with MemoryManager() as mm:
                current = mm.get_preferences()
                for key, value in prefs.items():
                    if hasattr(current, key) and value:
                        setattr(current, key, value)
                mm.update_preferences(current)
        except Exception:
            pass

    def _summarize_result(self, skill_name: str, result: dict) -> str:
        """从 Skill 返回值提取简短摘要"""
        if not result.get("success"):
            return f"失败: {result.get('error', '未知')}"
        if skill_name == "generate_presenter_video":
            return f"视频生成: {result.get('video_path', '')}"
        if skill_name == "publish_douyin":
            return f"发布成功: {result.get('publish_url', result.get('post_id', ''))}"
        if skill_name == "rag_search":
            return f"检索到 {result.get('count', 0)} 条"
        if skill_name == "sync_douyin_videos":
            return f"同步 {result.get('count', 0)} 个视频"
        if skill_name == "auto_reply_comments":
            return "外部互动已停用，需逐条人工确认"
        if skill_name in {"douyin_maintenance", "douyin_warmup"}:
            return (
                "账号维护完成，相关去重内容 "
                f"{result.get('unique_relevant_videos', 0)} 条，"
                f"验证播放 {result.get('playback_verified_videos', 0)} 条，"
                f"互动 {result.get('interaction_actions', 0)} 次，"
                f"同步作品 {result.get('synced_videos', 0)} 条"
            )
        return json.dumps(result, ensure_ascii=False)[:200]

    # -------------------------------------------------------------------------
    # 查询
    # -------------------------------------------------------------------------

    def get_execution(self, execution_uuid: str) -> Optional[TaskExecution]:
        return (
            self._session.query(TaskExecution)
            .filter_by(execution_uuid=execution_uuid)
            .first()
        )

    def get_task_executions(
        self,
        task_id: int,
        limit: int = 20,
    ) -> list[TaskExecution]:
        return (
            self._session.query(TaskExecution)
            .filter_by(task_id=task_id)
            .order_by(TaskExecution.created_at.desc())
            .limit(limit)
            .all()
        )

    def get_recent_executions(self, limit: int = 50) -> list[TaskExecution]:
        return (
            self._session.query(TaskExecution)
            .order_by(TaskExecution.created_at.desc())
            .limit(limit)
            .all()
        )

    def get_queue_stats(self) -> dict:
        """返回队列统计"""
        total = self._session.query(TaskExecution).count()
        pending = self._session.query(TaskExecution).filter_by(status=TaskStatus.PENDING.value).count()
        running = self._session.query(TaskExecution).filter_by(status=TaskStatus.RUNNING.value).count()
        completed = self._session.query(TaskExecution).filter_by(status=TaskStatus.COMPLETED.value).count()
        failed = self._session.query(TaskExecution).filter_by(status=TaskStatus.FAILED.value).count()
        outcome_unknown = self._session.query(TaskExecution).filter_by(
            status=TaskStatus.OUTCOME_UNKNOWN.value
        ).count()
        awaiting_verification = self._session.query(TaskExecution).filter_by(
            status=TaskStatus.AWAITING_VERIFICATION.value
        ).count()
        return dict(total=total, pending=pending, running=running,
                    completed=completed, failed=failed,
                    outcome_unknown=outcome_unknown,
                    awaiting_verification=awaiting_verification)
