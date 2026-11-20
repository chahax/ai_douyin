"""
src/scheduler/runner.py — 调度系统全局单例

在 app.py 启动时创建并启动，放在模块全局避免循环导入。
"""

import threading

from src.shared.logger import logger
from src.shared.migration import ensure_migrated

from src.scheduler.cron import CronScheduler
from src.scheduler.queue import TaskQueue

# 全局单例
scheduler_instance: CronScheduler | None = None
_worker_thread: threading.Thread | None = None
_start_lock = threading.Lock()
_worker_failed = False
_startup_failed = False


def _service_status(component, status, *, message='', error_code=''):
    """Persist diagnostics without making UI availability depend on SQLite."""
    try:
        from src.scheduler.account_refresh import update_service_status
        update_service_status(component, status, message=message, error_code=error_code)
    except Exception as exc:
        logger.warning('Cannot persist scheduler status: {}', type(exc).__name__)


def _run_worker(queue):
    global _worker_failed
    _service_status('worker', 'running', message='任务队列已启动。')
    try:
        queue.worker_loop(5)
    except Exception as exc:
        _worker_failed = True
        _service_status('worker', 'failed', message='任务队列异常停止；请检查服务日志，处理后重启服务。',
                        error_code=type(exc).__name__)
        logger.error('TaskQueue worker stopped: {}', type(exc).__name__)
    else:
        _worker_failed = True
        _service_status('worker', 'stopped', message='任务队列已退出；核对日志后重启服务。')
    finally:
        try:
            queue.close()
        except Exception as exc:
            _worker_failed = True
            _service_status('worker', 'failed', message='任务队列清理异常；请检查服务日志。',
                            error_code=type(exc).__name__)


def start_scheduler():
    """启动调度器 + 后台 Worker"""
    global scheduler_instance, _worker_thread, _startup_failed
    with _start_lock:
        # A page rerun must not restart a worker that stopped with an unknown
        # external outcome. Preserve its execution records for manual handling.
        if _worker_failed or _startup_failed:
            return False
        try:
            if not ensure_migrated(strict=True):
                _service_status('scheduler', 'blocked', error_code='migration_required',
                                message='数据库迁移未完成，后台未启动；请备份数据库并执行 alembic upgrade head。')
                return False
            if scheduler_instance is None:
                scheduler_instance = CronScheduler()
            scheduler_instance.start()

            if _worker_thread is None or not _worker_thread.is_alive():
                q = TaskQueue()
                _worker_thread = threading.Thread(
                    target=_run_worker,
                    args=(q,),
                    daemon=True,
                    name="TaskQueueWorker",
                )
                _worker_thread.start()
            _seed_builtin_tasks()
            return True
        except Exception as exc:
            _startup_failed = True
            _service_status('scheduler', 'failed', error_code=type(exc).__name__,
                            message='后台启动异常；请检查服务日志并人工处理。')
            logger.error('Scheduler startup failed: {}', type(exc).__name__)
            return False


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
