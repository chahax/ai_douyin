"""
src/scheduler/cron.py — 定时调度器

基于 APScheduler，支持 cron / interval 两种调度模式。
定时扫描 scheduled_tasks 表，将到期的任务入队（enqueue）。
真正的执行由 TaskQueue.worker_loop() 的 worker 负责。
"""

import logging
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.scheduler.models import ScheduledTask, TriggerType
from src.scheduler.queue import TaskQueue
from src.shared.database import SessionLocal

logger = logging.getLogger(__name__)


class CronScheduler:
    """
    定时调度器。

    管理 APScheduler 的 job 生命周期：
    - add_task()    添加/更新一个调度任务
    - remove_task()  移除一个调度任务
    - start()        启动调度器（后台线程）
    - stop()        优雅停止

    调度器到期后只是 enqueue（加入队列），不直接执行。
    执行由 Worker 负责。
    """

    def __init__(self):
        self._scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        self._queue = TaskQueue()

    def add_task(self, task: ScheduledTask) -> None:
        """将数据库中的任务注册到 APScheduler。"""
        if not task.enabled or task.trigger_type not in (
            TriggerType.CRON.value,
            TriggerType.INTERVAL.value,
        ):
            return

        trigger_config = task.trigger_config or {}
        job_id = f"task_{task.id}"

        # 移除旧 job（如果存在）
        self.remove_task_by_id(job_id)

        try:
            if task.trigger_type == TriggerType.CRON.value:
                expr = trigger_config.get("expression", "0 9 * * *")
                trigger = CronTrigger.from_crontab(expr, timezone="Asia/Shanghai")

            elif task.trigger_type == TriggerType.INTERVAL.value:
                minutes = trigger_config.get("minutes", 60)
                trigger = IntervalTrigger(minutes=minutes, timezone="Asia/Shanghai")

            else:
                return

            self._scheduler.add_job(
                func=self._enqueue_task,
                trigger=trigger,
                id=job_id,
                args=[task.id],
                replace_existing=True,
                misfire_grace_time=300,  # 5 分钟内的错过触发仍执行
            )
            logger.info(f"Cron 任务注册: {task.name} (id={task.id}, trigger={task.trigger_type})")

        except Exception as exc:
            logger.error(f"注册 Cron 任务失败: {task.name}, {exc}")

    def remove_task(self, task: ScheduledTask) -> None:
        self.remove_task_by_id(f"task_{task.id}")

    def remove_task_by_id(self, job_id: str) -> None:
        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)
            logger.info(f"Cron 任务移除: {job_id}")

    def sync_from_db(self) -> None:
        """
        从数据库同步所有启用状态的定时任务到 APScheduler。
        启动时调用，或外部手动调用强制同步。
        """
        with SessionLocal() as sess:
            tasks = (
                sess.query(ScheduledTask)
                .filter(
                    ScheduledTask.enabled == True,
                    ScheduledTask.trigger_type.in_([
                        TriggerType.CRON.value,
                        TriggerType.INTERVAL.value,
                    ]),
                )
                .all()
            )

        for task in tasks:
            self.add_task(task)

        logger.info(f"Cron 同步完成，{len(tasks)} 个任务已注册")

    def start(self) -> None:
        if self._scheduler.running:
            return
        self.sync_from_db()
        self._scheduler.start()
        logger.info("CronScheduler 已启动")

    def stop(self) -> None:
        if not self._scheduler.running:
            return
        self._scheduler.shutdown(wait=True)
        logger.info("CronScheduler 已停止")

    def _enqueue_task(self, task_id: int) -> None:
        """APScheduler 到期时调用：将任务入队。"""
        try:
            with TaskQueue() as q:
                result = q.enqueue(task_id)
                logger.info(f"Cron 触发入队: task_id={task_id}, result={result.message}")

                # 更新 last_run_at / next_run_at
                with SessionLocal() as sess:
                    task = sess.query(ScheduledTask).filter_by(id=task_id).first()
                    if task:
                        task.last_run_at = datetime.now()
                        # 估算下次执行时间（APScheduler 管理，这里只记录参考）
                        job = self._scheduler.get_job(f"task_{task_id}")
                        if job:
                            task.next_run_at = job.next_run_time
                        sess.commit()
        except Exception as exc:
            logger.exception(f"Cron 触发入队失败: task_id={task_id}, {exc}")

    def get_next_run(self, task_id: int) -> Optional[datetime]:
        job = self._scheduler.get_job(f"task_{task_id}")
        if job:
            return job.next_run_time
        return None

    def get_scheduled_jobs(self) -> list[dict]:
        """返回所有已调度的 job 信息。"""
        jobs = self._scheduler.get_jobs()
        return [
            {
                "id": j.id,
                "next_run": j.next_run_time,
                "trigger": str(j.trigger),
            }
            for j in jobs
        ]
