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


def stop_scheduler():
    """停止调度器"""
    global scheduler_instance
    if scheduler_instance:
        scheduler_instance.stop()
        scheduler_instance = None
