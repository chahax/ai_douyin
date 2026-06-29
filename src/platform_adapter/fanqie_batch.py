# -*- coding: utf-8 -*-
"""
src/platform_adapter/fanqie_batch.py — 番茄批量抓取

Harness Engineering Layer 4 + 6：批量任务的反馈与持续改进。

提供两个方法（同步 + 异步）：

1. fanqie_batch_fetch_sync(book_names, chapters, interval_s)
   - 同步阻塞跑：循环调 fetch_book，每本之间 sleep 间隔避免反爬
   - 适合 Agent 自然语言触发 / 调试 / 小批量（< 10 本）

2. fanqie_batch_fetch_async(book_names, chapters, interval_s)
   - 每本入队 TaskQueue，Worker 异步拉队列
   - 适合大批量（10+ 本）/ 调度任务 / 跨进程

通用特性：
- 失败不中断：单本失败记录 + 继续下一本
- 反爬保护：interval_s 默认 30s（实测番茄达人中心可承受）
- 进度可观测：每本结束都打日志
- 持久化：每本完成后立刻写 books/（重启不丢）
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, asdict
from typing import Any

from src.platform_adapter.fanqie_promotion import (
    FANQIE_NOVEL_LIST_URL,
    FanqiePromotionService,
)


logger = logging.getLogger(__name__)


@dataclass
class BookFetchResult:
    """单本书抓取结果。"""
    book_name: str
    success: bool
    book_id: str = ""
    chapters_fetched: int = 0
    total_chapters_seen: int = 0
    paywall_hit: bool = False
    error_code: str = ""
    error_message: str = ""
    duration_ms: int = 0
    material_path: str = ""


@dataclass
class BatchFetchReport:
    """批量抓取总报告。"""
    total: int
    succeeded: int
    failed: int
    skipped: int = 0  # 已在 books/ 里的
    interval_s: float = 30.0
    total_duration_ms: int = 0
    results: list[BookFetchResult] = field(default_factory=list)


def _summarize_report(report: BatchFetchReport) -> dict:
    """转 dict 给 SkillResult.data 用。"""
    return {
        "total": report.total,
        "succeeded": report.succeeded,
        "failed": report.failed,
        "skipped": report.skipped,
        "interval_s": report.interval_s,
        "total_duration_ms": report.total_duration_ms,
        "results": [asdict(r) for r in report.results],
    }


def batch_fetch_sync(
    book_names: list[str],
    *,
    chapters: int = 5,
    interval_s: float = 30.0,
    headless: bool = True,
) -> BatchFetchReport:
    """同步批量抓取。循环调 fetch_book，间隔 interval_s 秒。

    Args:
        book_names: 要抓的书名列表
        chapters: 每本抓几章
        interval_s: 每本之间 sleep 秒数（反爬保护，默认 30）
        headless: 浏览器无头模式

    Returns:
        BatchFetchReport
    """
    if not book_names:
        return BatchFetchReport(total=0, succeeded=0, failed=0, interval_s=interval_s)

    start = time.time()
    service = FanqiePromotionService()
    results: list[BookFetchResult] = []
    succeeded = 0
    failed = 0
    skipped = 0

    for idx, name in enumerate(book_names, start=1):
        name = (name or "").strip()
        if not name:
            continue

        logger.info(f"[batch] [{idx}/{len(book_names)}] 开始抓: {name}")
        book_start = time.time()
        try:
            result = service.fetch_book(book_name=name, chapters=chapters, headless=headless)
            elapsed = int((time.time() - book_start) * 1000)
            results.append(BookFetchResult(
                book_name=name,
                success=True,
                book_id=result.book_id,
                chapters_fetched=len(result.chapters),
                total_chapters_seen=result.chapters and len(result.chapters) or 0,
                material_path=result.material_path,
                duration_ms=elapsed,
            ))
            succeeded += 1
            logger.info(f"[batch] [{idx}/{len(book_names)}] OK: {name} ({elapsed}ms)")
        except Exception as exc:
            elapsed = int((time.time() - book_start) * 1000)
            err_msg = f"{type(exc).__name__}: {exc}"[:200]
            logger.warning(f"[batch] [{idx}/{len(book_names)}] FAIL: {name} ({err_msg})")
            results.append(BookFetchResult(
                book_name=name,
                success=False,
                error_code="skill_error",
                error_message=err_msg,
                duration_ms=elapsed,
            ))
            failed += 1

        # 间隔（最后一本书不 sleep）
        if idx < len(book_names) and interval_s > 0:
            logger.debug(f"[batch] sleeping {interval_s}s before next book")
            time.sleep(interval_s)

    total_ms = int((time.time() - start) * 1000)
    report = BatchFetchReport(
        total=len(book_names),
        succeeded=succeeded,
        failed=failed,
        skipped=skipped,
        interval_s=interval_s,
        total_duration_ms=total_ms,
        results=results,
    )
    logger.info(
        f"[batch] done: {succeeded}/{len(book_names)} succeeded, {failed} failed, {total_ms}ms total"
    )
    return report


def batch_fetch_async(
    book_names: list[str],
    *,
    chapters: int = 5,
    interval_s: float = 30.0,
    name_prefix: str = "番茄批量抓取",
) -> dict:
    """异步批量抓取：每本入队 TaskQueue，Worker 异步拉队列。

    Args:
        book_names: 要抓的书名列表
        chapters: 每本抓几章
        interval_s: Worker 执行间隔（写到 skill_params）
        name_prefix: ScheduledTask.name 前缀

    Returns:
        {
            "total": N,
            "queued": M,           # 成功入队的数
            "skipped": K,           # 已存在的（books/ 已有）
            "execution_uuids": [...],
            "task_ids": [...],
        }
    """
    from src.scheduler.queue import TaskQueue
    from src.scheduler.models import ScheduledTask, TaskStatus, TaskType, TriggerType
    from src.shared.database import SessionLocal

    if not book_names:
        return {"total": 0, "queued": 0, "skipped": 0, "execution_uuids": [], "task_ids": []}

    service = FanqiePromotionService()
    results = {
        "total": len(book_names),
        "queued": 0,
        "skipped": 0,
        "execution_uuids": [],
        "task_ids": [],
    }

    with SessionLocal() as sess:
        queue = TaskQueue(sess)
        for idx, name in enumerate(book_names, start=1):
            name = (name or "").strip()
            if not name:
                continue

            # 1) 跳过已抓的（books/ 已有 meta.json）
            if service.list_books():
                # 简单判断：list_books 返回 list，按 name 匹配
                existing = next(
                    (b for b in service.list_books() if b.get("book_name") == name),
                    None,
                )
                if existing:
                    logger.info(f"[batch-async] [{idx}/{len(book_names)}] 跳过（已存在）: {name}")
                    results["skipped"] += 1
                    continue

            # 2) 创建 ScheduledTask
            task = ScheduledTask(
                name=f"{name_prefix}-{name}",
                description=f"批量抓取: {name} ({chapters} 章)",
                task_type=TaskType.QUEUE.value,
                skill_name="fanqie_fetch_book",
                skill_params={
                    "book_name": name,
                    "chapters": chapters,
                    "headless": True,
                },
                trigger_type=TriggerType.MANUAL.value,
                trigger_config={},
                status=TaskStatus.PENDING.value,
                enabled=True,
                max_retries=2,
                retry_delay_seconds=60,
            )
            sess.add(task)
            sess.commit()
            sess.refresh(task)

            # 3) 入队
            enqueue_result = queue.enqueue_now(
                skill_name="fanqie_fetch_book",
                skill_params={
                    "book_name": name,
                    "chapters": chapters,
                    "headless": True,
                },
                name=f"{name_prefix}-{name}-{idx}",
            )
            if enqueue_result.success:
                results["queued"] += 1
                results["task_ids"].append(task.id)
                if enqueue_result.execution_uuid:
                    results["execution_uuids"].append(enqueue_result.execution_uuid)
                logger.info(
                    f"[batch-async] [{idx}/{len(book_names)}] queued: {name} "
                    f"(task_id={task.id}, exec_uuid={enqueue_result.execution_uuid})"
                )
            else:
                logger.warning(
                    f"[batch-async] [{idx}/{len(book_names)}] 入队失败: {name} "
                    f"({enqueue_result.message})"
                )

    return results
