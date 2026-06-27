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
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
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

    def __init__(self, session: Optional[Session] = None):
        self._own_session = session is None
        self._session = session or SessionLocal()

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

        # 创建执行记录
        execution = TaskExecution(
            execution_uuid=uuid.uuid4().hex,
            task_id=task_id,
            skill_params_snapshot=skill_params or task.skill_params or {},
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
        """Worker 调用：抢下一个 pending 任务（SELECT FOR UPDATE SKIP LOCKED）"""
        row = (
            self._session.query(TaskExecution)
            .filter(
                TaskExecution.status == TaskStatus.PENDING.value,
                TaskExecution.task_id.in_(
                    self._session.query(ScheduledTask.id).filter(
                        ScheduledTask.enabled == True,
                        ScheduledTask.status != TaskStatus.CANCELLED.value,
                    )
                ),
            )
            .order_by(TaskExecution.created_at.asc())
            .with_for_update(skip_locked=True)
            .first()
        )
        return row

    def mark_running(self, execution: TaskExecution) -> None:
        execution.status = TaskStatus.RUNNING.value
        execution.started_at = datetime.utcnow()
        self._session.commit()

    def mark_completed(
        self,
        execution: TaskExecution,
        result: dict,
        result_summary: str = "",
    ) -> None:
        execution.status = TaskStatus.COMPLETED.value
        execution.result = result
        execution.result_summary = result_summary
        execution.completed_at = datetime.utcnow()
        execution.duration_seconds = int(
            (execution.completed_at - execution.started_at).total_seconds()
        )
        self._session.commit()

    def mark_failed(
        self,
        execution: TaskExecution,
        error: str,
        should_retry: bool = False,
    ) -> None:
        task = execution.task
        # should_retry 已经由调用方根据「attempt <= max_retries」算出，这里只负责写状态
        if should_retry and execution.attempt <= task.max_retries:
            # 延迟重试（Phase 3 实现 retry_delay_seconds）
            from datetime import timedelta
            delay = task.retry_delay_seconds or 60
            execution.status = TaskStatus.PENDING.value
            execution.is_retry = True
            execution.attempt += 1
            execution.next_retry_at = datetime.utcnow() + timedelta(seconds=delay)
            execution.error_message = error
            self._session.commit()
            logger.info(
                f"任务 {execution.execution_uuid} 失败，{delay}s 后第 {execution.attempt} 次重试"
            )
        else:
            execution.status = TaskStatus.FAILED.value
            execution.error_message = error
            execution.completed_at = datetime.utcnow()
            if execution.started_at:
                execution.duration_seconds = int(
                    (execution.completed_at - execution.started_at).total_seconds()
                )
            self._session.commit()
            logger.error(f"任务 {execution.execution_uuid} 最终失败: {error}")

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
            # 从 registry 获取 Skill 并执行
            from src.agent.registry import SkillRegistry

            registry = SkillRegistry()
            result = registry.call(skill_name, params)

            if result.get("success"):
                summary = self._summarize_result(skill_name, result)
                self.mark_completed(execution, result, summary)
                log.info(f"任务完成: {execution.execution_uuid}")
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
        while True:
            if stop_event and stop_event.is_set():
                logger.info("TaskQueue Worker 收到停止信号，退出")
                break

            with SessionLocal() as sess:
                row = (
                    sess.query(TaskExecution)
                    .filter(TaskExecution.status == TaskStatus.PENDING.value)
                    # Phase 3: next_retry_at 过滤（retry_delay_seconds 生效）
                    .join(ScheduledTask)
                    .filter(ScheduledTask.enabled == True)
                    .filter(ScheduledTask.status != TaskStatus.CANCELLED.value)
                    .filter(
                        (TaskExecution.next_retry_at.is_(None))
                        | (TaskExecution.next_retry_at <= datetime.utcnow())
                    )
                    .order_by(TaskExecution.created_at.asc())
                    .with_for_update(skip_locked=True)
                    .first()
                )

                if not row:
                    time.sleep(poll_interval)
                    continue

                # 重新加载 task 关系
                sess.refresh(row)
                self._session = sess
                self.mark_running(row)
                self._execute_sync(row, sess)

            time.sleep(1)

    def _execute_sync(self, execution: TaskExecution, sess: Session) -> None:
        """在指定 session 中同步执行（避免 session 跨线程问题）

        Phase 3 改造：
          1. result.success=False 分支末尾 fire-and-forget ErrorReviewer
          2. except 分支修 retry 语义（与 success=False 分支一致）
          3. except 分支末尾 fire-and-forget ErrorReviewer
        """
        from datetime import timedelta
        from src.agent.registry import SkillRegistry

        task = execution.task
        skill_name = task.skill_name
        params = execution.skill_params_snapshot
        delay = task.retry_delay_seconds or 60

        try:
            registry = SkillRegistry()
            result = registry.call(skill_name, params)

            if result.get("success"):
                summary = self._summarize_result(skill_name, result)
                execution.status = TaskStatus.COMPLETED.value
                execution.result = result
                execution.result_summary = summary
                execution.completed_at = datetime.utcnow()
                if execution.started_at:
                    execution.duration_seconds = int(
                        (execution.completed_at - execution.started_at).total_seconds()
                    )
                sess.commit()
            else:
                should_retry = execution.attempt <= task.max_retries
                error_msg = result.get("error", "未知错误")
                if should_retry:
                    execution.status = TaskStatus.PENDING.value
                    execution.is_retry = True
                    execution.attempt += 1
                    execution.next_retry_at = datetime.utcnow() + timedelta(
                        seconds=delay
                    )
                else:
                    execution.status = TaskStatus.FAILED.value
                    execution.completed_at = datetime.utcnow()
                    if execution.started_at:
                        execution.duration_seconds = int(
                            (execution.completed_at - execution.started_at).total_seconds()
                        )
                execution.error_message = error_msg
                sess.commit()
                # fire-and-forget 错误诊断（仅最终失败触发，避免重试期间风暴）
                if not should_retry:
                    self._fire_error_review(execution, error_msg, result)
        except Exception as exc:
            # Phase 3 修复：except 分支也要走 should_retry 判定
            should_retry = execution.attempt <= task.max_retries
            error_msg = str(exc)
            if should_retry:
                execution.status = TaskStatus.PENDING.value
                execution.is_retry = True
                execution.attempt += 1
                execution.next_retry_at = datetime.utcnow() + timedelta(
                    seconds=delay
                )
            else:
                execution.status = TaskStatus.FAILED.value
                execution.completed_at = datetime.utcnow()
                if execution.started_at:
                    execution.duration_seconds = int(
                        (execution.completed_at - execution.started_at).total_seconds()
                    )
            execution.error_message = error_msg
            sess.commit()
            logger.exception(f"Worker 执行异常: {execution.execution_uuid}")
            # fire-and-forget 错误诊断
            if not should_retry:
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
            return f"回复 {result.get('replied', 0)} 条"
        if skill_name == "douyin_warmup":
            return f"养号完成，观看 {result.get('videos_seen', 0)} 个视频"
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
        return dict(total=total, pending=pending, running=running, completed=completed, failed=failed)
