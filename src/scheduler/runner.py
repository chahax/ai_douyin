"""
src/scheduler/runner.py — 调度系统全局单例

在 app.py 启动时创建并启动，放在模块全局避免循环导入。
"""

import threading

from src.scheduler.cron import CronScheduler
from src.scheduler.queue import TaskQueue

# 全局单例
scheduler_instance: CronScheduler | None = None
_worker_thread: threading.Thread | None = None


def start_scheduler():
    """启动调度器 + 后台 Worker"""
    global scheduler_instance, _worker_thread

    if scheduler_instance is None:
        scheduler_instance = CronScheduler()

    scheduler_instance.start()

    # 启动后台 Worker
    if _worker_thread is None or not _worker_thread.is_alive():
        q = TaskQueue()
        _worker_thread = threading.Thread(
            target=q.worker_loop,
            args=(5,),
            daemon=True,
            name="TaskQueueWorker",
        )
        _worker_thread.start()

    _seed_builtin_tasks()


def _seed_builtin_tasks() -> None:
    """Create built-in schedules once without coupling them to UI reruns."""
    try:
        from src.scheduler.models import (
            ScheduledTask,
            TaskStatus,
            TaskType,
            TriggerType,
        )
        from src.shared.database import SessionLocal

        with SessionLocal() as session:
            exists = (
                session.query(ScheduledTask)
                .filter_by(name="investigate_problems_daily")
                .first()
            )
            if exists:
                return
            session.add(
                ScheduledTask(
                    name="investigate_problems_daily",
                    description="每日扫描未解决问题，调用 LLM 生成调查摘要",
                    task_type=TaskType.SCHEDULED.value,
                    skill_name="investigate_problems",
                    skill_params={"limit": 20},
                    trigger_type=TriggerType.CRON.value,
                    trigger_config={"expression": "37 9 * * *"},
                    status=TaskStatus.PENDING.value,
                    enabled=True,
                    max_retries=1,
                    retry_delay_seconds=300,
                )
            )
            session.commit()
    except Exception:
        # Scheduling is auxiliary; startup and page rendering must stay available.
        return


def stop_scheduler():
    """停止调度器"""
    global scheduler_instance
    if scheduler_instance:
        scheduler_instance.stop()
        scheduler_instance = None
