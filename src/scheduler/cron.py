"""
src/scheduler/cron.py — 定时调度器

基于 APScheduler，支持 cron / interval 两种调度模式。
定时扫描 scheduled_tasks 表，将到期的任务入队（enqueue）。
真正的执行由 TaskQueue.worker_loop() 的 worker 负责。
"""

import logging
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
import traceback
import uuid
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.scheduler.models import ScheduledTask, TriggerType
from src.scheduler.queue import TaskQueue
from src.shared.database import SessionLocal

logger = logging.getLogger(__name__)
SCAN_DIAGNOSTIC_DIR = Path(__file__).resolve().parents[2] / 'data/logs/automation_scan_diagnostics'
_KNOWN_SCAN_KEYS = frozenset({'account_uuid','account_key','command_id','run_id','state','status','enabled',
    'interval_seconds','revision','profile_json','seed','boot_time','recovery_token','updated_at',
    'finished_at','error_code','message','mode','options_json','policy_snapshot','platform_identity_key'})


def _write_scan_failure(exc, component):
    """Save structural stack locations only, never messages, lines or locals."""
    root = Path(__file__).resolve().parents[2]
    frames = []
    for frame in traceback.extract_tb(exc.__traceback__):
        path = Path(frame.filename).resolve()
        filename = str(path.relative_to(root)) if path.is_relative_to(root) and path.is_file() and path.suffix.lower()=='.py' else '<external-source>'
        name = frame.name if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}',frame.name) else '<module-or-generated>'
        frames.append(dict(file=filename,line=frame.lineno,function=name))
    value = dict(schema='automation_scan_failure/v1',observed_at=time.time(),component=component,
        error_type=type(exc).__name__,frames=frames,exception_message_saved=False,locals_saved=False,
        original_task_replayed=False)
    if isinstance(exc,KeyError) and exc.args:
        key=exc.args[0]
        if isinstance(key,str):
            value['missing_key']={'identifier':key} if key in _KNOWN_SCAN_KEYS else {
                'sha256':hashlib.sha256(key.encode('utf8',errors='replace')).hexdigest()}
        else:value['missing_key']={'type':type(key).__name__}
    directory=Path(SCAN_DIAGNOSTIC_DIR).resolve()
    if not directory.is_relative_to(root):raise ValueError('scan_diagnostic_project_directory_required')
    directory.mkdir(parents=True,exist_ok=True)
    # The component is a fixed caller label, not a file path from an exception.
    label=component if re.fullmatch(r'[a-z][a-z0-9_]{0,63}',component) else 'unknown_component'
    path=directory/(label+'_'+uuid.uuid4().hex+'.json')
    raw=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf8')
    with path.open('xb') as out:out.write(raw)
    return dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest())


def _is_sqlite_contention(exc):
    code = getattr(exc, 'sqlite_errorcode', None)
    return (isinstance(exc, sqlite3.Error) and isinstance(code, int)
            and code & 0xFF in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED})


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
        from src.scheduler.account_refresh import refresh_due_accounts, update_service_status
        def record_status(component, status, *, message='', error_code=''):
            try:
                update_service_status(component, status, message=message, error_code=error_code)
                return True
            except Exception as exc:
                # The same SQLite outage can prevent recording its own alert.
                # Keep a local diagnostic; old DB health timestamps remain old.
                logger.error('Automation status not saved: component=%s state=%s error=%s sqlite_contention=%s',
                             component, status, type(exc).__name__, _is_sqlite_contention(exc))
                return False

        def scan_failed(exc, blocked, component, code, message):
            if _is_sqlite_contention(exc):
                logger.warning('Local SQLite contention: component=%s; waiting for next scheduled scan; no immediate task retry', component)
                record_status(component, 'degraded', error_code='scheduler_database_busy',
                              message='本地数据库暂时繁忙；等待下次定时扫描，原任务ID和未知结果门保持。')
            else:
                blocked['value'] = True
                logger.error('Automation scan stopped: component=%s error=%s', component, type(exc).__name__)
                try:
                    evidence = _write_scan_failure(exc, component)
                    logger.error('Automation scan structural evidence: %s', evidence['path'])
                except (OSError, ValueError, TypeError) as diagnostic_error:
                    logger.error('Automation scan evidence not saved: component=%s error=%s',
                                 component,type(diagnostic_error).__name__)
                record_status(component, 'manual_required', error_code=code, message=message)
        try:
            self.sync_from_db()
        except Exception as exc:
            # The account scheduler is independent of legacy queue/schema failures.
            logger.error('Cron task sync failed (%s)', type(exc).__name__)
            record_status('task_schedule', 'manual_required',
                                  message='通用定时任务读取失败，请人工检查数据库迁移。',
                                  error_code='task_schedule_unavailable')
        # Durable due times handle long shutdowns. Only one missed refresh is run.
        startup = {'first': True}
        refresh_blocked = {'value': False}
        def refresh():
            if refresh_blocked['value']:
                return
            reason = 'startup_catchup' if startup['first'] else 'periodic'
            startup['first'] = False
            try:
                from src.scheduler.deployment_maintenance import resume_pending
                resume_pending()
                refresh_due_accounts(reason=reason)
            except Exception as exc:
                scan_failed(exc, refresh_blocked, 'account_refresh', 'account_refresh_unavailable',
                            '账号后台调度异常并已停止派发，请人工检查本地日志。')
        def heartbeat():
            if not record_status('scheduler', 'healthy', message='后台调度心跳正常'):
                return
            # Report the worker's actual thread, without reviving a failed worker.
            from src.scheduler import runner
            worker = runner._worker_thread
            if not runner._worker_failed and worker is not None:
                record_status('worker', 'running' if worker.is_alive() else 'stopped',
                                      message='任务队列线程运行中' if worker.is_alive() else '任务队列线程已停止')
        playback_startup = {'first': True}
        playback_blocked = {'value': False}
        def playback():
            if playback_blocked['value']:
                return
            playback_reason = 'startup_catchup' if playback_startup['first'] else 'periodic'
            playback_startup['first'] = False
            try:
                from src.scheduler.account_playback import dispatch_due_accounts
                dispatch_due_accounts(reason=playback_reason)
            except Exception as exc:
                scan_failed(exc, playback_blocked, 'playback_schedule', 'playback_schedule_unavailable',
                            '自动播放扫描异常，已停止新派发；请人工检查本地日志。')
        def manual_windows():
            try:
                from src.scheduler.account_manual_windows import dispatch_human_windows
                dispatch_human_windows()
                record_status('manual_windows', 'healthy', message='平台验证异常自动窗口扫描完成；同一异常只自动打开一次。')
            except Exception as exc:
                logger.error('Automatic repair-window scan failed (%s)', type(exc).__name__)
                record_status('manual_windows', 'degraded', error_code='manual_window_scan_unavailable',
                              message='异常自动窗口扫描失败，请检查原任务；未清锁或重派窗口。')
        def browser_control():
            try:
                from src.operations_accounts.browser_control_runtime import enabled, pump_pending, pump_status
                if enabled():
                    pump_pending()
                    blocked = pump_status()['blocked_accounts']
                    if blocked:
                        record_status('browser_control', 'degraded', error_code='browser_owner_recovery_blocked',
                            message=f'队列扫描正常；{len(blocked)}个账号的旧执行者或原任务尚未核对，账号业务未恢复。')
                    else:
                        record_status('browser_control', 'healthy', message='浏览器队列扫描正常；账号暂停、身份核验和实际业务结果请查看各账号状态。')
            except Exception as exc:
                logger.error('Account browser control scan failed (%s)', type(exc).__name__)
                record_status('browser_control', 'degraded', error_code='browser_control_unavailable',
                              message='账号浏览器管控扫描失败；原任务、未知结果及锁保持。')
        from src.scheduler.handling_fast_lane import run_registered_requests
        self._scheduler.add_job(run_registered_requests, 'interval', seconds=2,
                                id='account_human_completion', replace_existing=True,
                                next_run_time=datetime.now(), coalesce=True, max_instances=1,
                                misfire_grace_time=2)
        self._scheduler.add_job(browser_control, 'interval', seconds=5,
                                id='account_browser_control', replace_existing=True,
                                next_run_time=datetime.now(), coalesce=True, max_instances=1,
                                misfire_grace_time=5)
        self._scheduler.add_job(manual_windows, 'interval', seconds=15,
                                id='account_manual_windows', replace_existing=True,
                                next_run_time=datetime.now(), coalesce=True, max_instances=1,
                                misfire_grace_time=15)
        self._scheduler.add_job(heartbeat, 'interval', seconds=30,
                                id='automation_heartbeat', replace_existing=True,
                                next_run_time=datetime.now(), coalesce=True, max_instances=1)
        self._scheduler.add_job(refresh, 'interval', seconds=60,
                                id='account_information_refresh', replace_existing=True,
                                next_run_time=datetime.now(), coalesce=True, max_instances=1,
                                misfire_grace_time=60)
        self._scheduler.add_job(playback, 'interval', seconds=60,
                                id='account_automatic_playback', replace_existing=True,
                                next_run_time=datetime.now(), coalesce=True, max_instances=1,
                                misfire_grace_time=60)
        self._scheduler.start()
        logger.info("CronScheduler 已启动")

    def stop(self) -> None:
        if not self._scheduler.running:
            return
        self._scheduler.shutdown(wait=True)
        from src.scheduler.account_refresh import update_service_status
        update_service_status('scheduler', 'stopped', message='后台调度已停止')
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
