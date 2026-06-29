# -*- coding: utf-8 -*-
"""
src/platform_adapter/fanqie_batch.py — 番茄批量抓取（DB 清单驱动）

Harness Engineering Layer 5: 批量抓取**不允许**用户传任意 book_names。

工作流（两阶段）：
  1. fanqie_batch_add(book_name)      → DB 入库，status='pending'
  2. fanqie_batch_run()                 → 读 DB pending 状态的书 → 抓 → mark_done

好处：
  - 用户 / Agent 不能任意抓书（受控清单）
  - 抓取列表可版本控制（git track batch_books.yaml 种子）
  - 失败的书保留在清单（status='failed'），可手动重试
  - 调度任务能定期扫 DB 跑（cron）
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from src.scheduler.models import FanqieBatchBook, FanqieBatchStatus
from src.shared.database import SessionLocal


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
    skipped: int = 0
    interval_s: float = 30.0
    total_duration_ms: int = 0
    results: list[BookFetchResult] = field(default_factory=list)


def _summarize_report(report: BatchFetchReport) -> dict:
    return {
        "total": report.total,
        "succeeded": report.succeeded,
        "failed": report.failed,
        "skipped": report.skipped,
        "interval_s": report.interval_s,
        "total_duration_ms": report.total_duration_ms,
        "results": [asdict(r) for r in report.results],
    }


# ── 清单管理 ─────────────────────────────────────────────────────

def add_books(
    book_names: list[str],
    *,
    chapters: int = 5,
    interval_s: int = 30,
    note: str = "",
) -> dict:
    """加书到 DB 清单（自动去重）。

    Args:
        book_names: 要加的书名列表
        chapters: 每本抓几章
        interval_s: 间隔秒数
        note: 备注

    Returns:
        {"total": N, "added": M, "skipped": K, "added_ids": [...]}
    """
    if not book_names:
        return {"total": 0, "added": 0, "skipped": 0, "added_ids": []}

    added_ids = []
    added = 0
    skipped = 0
    with SessionLocal() as sess:
        for name in book_names:
            name = (name or "").strip()
            if not name:
                continue
            # 去重：同名 status='pending'/'running' 跳过
            existing = (
                sess.query(FanqieBatchBook)
                .filter(
                    FanqieBatchBook.book_name == name,
                    FanqieBatchBook.status.in_([
                        FanqieBatchStatus.PENDING.value,
                        FanqieBatchStatus.RUNNING.value,
                    ]),
                )
                .first()
            )
            if existing:
                skipped += 1
                logger.info(f"[batch-add] 跳过（已在清单）: {name}")
                continue
            row = FanqieBatchBook(
                book_name=name,
                status=FanqieBatchStatus.PENDING.value,
                chapters=chapters,
                interval_s=interval_s,
                note=note,
            )
            sess.add(row)
            sess.commit()
            sess.refresh(row)
            added += 1
            added_ids.append(row.id)
            logger.info(f"[batch-add] 加书 #{row.id}: {name}")

    return {
        "total": len(book_names),
        "added": added,
        "skipped": skipped,
        "added_ids": added_ids,
    }


def list_books(
    *,
    status: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """列 DB 清单。

    Args:
        status: 过滤（pending/running/done/failed/skipped）
        limit: 最多返回条数
    """
    with SessionLocal() as sess:
        q = sess.query(FanqieBatchBook).order_by(
            FanqieBatchBook.added_at.desc()
        )
        if status:
            q = q.filter(FanqieBatchBook.status == status)
        rows = q.limit(limit).all()
        out = []
        for r in rows:
            out.append({
                "id": r.id,
                "book_name": r.book_name,
                "status": r.status,
                "chapters": r.chapters,
                "interval_s": r.interval_s,
                "book_id": r.book_id,
                "chapters_fetched": r.chapters_fetched,
                "total_chapters_seen": r.total_chapters_seen,
                "duration_ms": r.duration_ms,
                "paywall_hit": r.paywall_hit,
                "material_path": r.material_path,
                "error_message": r.error_message,
                "added_at": r.added_at.isoformat() if r.added_at else "",
                "last_fetched_at": r.last_fetched_at.isoformat() if r.last_fetched_at else None,
                "attempt_count": r.attempt_count,
                "note": r.note,
            })
        return out


def mark_done(
    book_id: int,
    *,
    success: bool,
    result: BookFetchResult | None = None,
    error_message: str = "",
) -> None:
    """标记清单状态（done / failed / skipped）。"""
    with SessionLocal() as sess:
        row = sess.query(FanqieBatchBook).filter_by(id=book_id).first()
        if not row:
            return
        if success and result:
            row.status = FanqieBatchStatus.DONE.value
            row.book_id = result.book_id
            row.chapters_fetched = result.chapters_fetched
            row.total_chapters_seen = result.total_chapters_seen
            row.paywall_hit = result.paywall_hit
            row.material_path = result.material_path
            row.error_message = ""
            row.duration_ms = result.duration_ms
        else:
            row.status = FanqieBatchStatus.FAILED.value
            row.error_message = (error_message or "")[:2000]
            row.attempt_count += 1
        row.last_fetched_at = datetime.utcnow()
        sess.commit()


# ── 抓取执行（核心）───────────────────────────────────────────

def _fetch_one(book_id: int) -> BookFetchResult:
    """抓清单中一条 book。更新 DB 状态。"""
    from src.platform_adapter.fanqie_promotion import FanqiePromotionService

    with SessionLocal() as sess:
        row = sess.query(FanqieBatchBook).filter_by(id=book_id).first()
        if not row:
            return BookFetchResult(
                book_name=f"<id={book_id}>",
                success=False,
                error_code="not_found",
                error_message="DB 中找不到该清单条目",
            )
        # 标记 running
        row.status = FanqieBatchStatus.RUNNING.value
        row.attempt_count += 1
        sess.commit()
        book_name = row.book_name
        chapters = row.chapters
        book_id_str = row.book_id or ""  # 保存原 book_id

    service = FanqiePromotionService()
    book_start = time.time()
    try:
        result = service.fetch_book(
            book_name=book_name, chapters=chapters, headless=True,
        )
        elapsed = int((time.time() - book_start) * 1000)
        book_result = BookFetchResult(
            book_name=book_name,
            success=True,
            book_id=result.book_id,
            chapters_fetched=len(result.chapters),
            total_chapters_seen=len(result.chapters),
            paywall_hit=False,
            material_path=result.material_path,
            duration_ms=elapsed,
        )
        mark_done(book_id, success=True, result=book_result)
        return book_result
    except Exception as exc:
        elapsed = int((time.time() - book_start) * 1000)
        err_msg = f"{type(exc).__name__}: {exc}"[:300]
        book_result = BookFetchResult(
            book_name=book_name,
            success=False,
            error_code="skill_error",
            error_message=err_msg,
            duration_ms=elapsed,
        )
        mark_done(book_id, success=False, error_message=err_msg)
        return book_result


def batch_fetch_sync(
    *,
    interval_s: float = 30.0,
    max_count: int = 10,
) -> BatchFetchReport:
    """从 DB 读 status='pending' 的书，**同步阻塞**循环抓。

    Args:
        interval_s: 每本之间 sleep 秒数（覆盖 DB 设置）
        max_count: 本次最多抓几本（防止调度失控）

    Returns:
        BatchFetchReport
    """
    from src.platform_adapter.fanqie_promotion import FanqiePromotionService

    start = time.time()
    # 1) 查 DB pending
    with SessionLocal() as sess:
        rows = (
            sess.query(FanqieBatchBook)
            .filter(FanqieBatchBook.status == FanqieBatchStatus.PENDING.value)
            .order_by(FanqieBatchBook.added_at.asc())
            .limit(max_count)
            .all()
        )
        # 取 (id, interval_s) — interval_s 在 DB 里（用户加书时设的）
        targets = [(r.id, r.interval_s, r.book_name) for r in rows]

    if not targets:
        return BatchFetchReport(
            total=0, succeeded=0, failed=0,
            interval_s=interval_s, total_duration_ms=0,
        )

    service = FanqiePromotionService()
    results: list[BookFetchResult] = []
    succeeded = 0
    failed = 0

    for idx, (row_id, row_interval, name) in enumerate(targets, start=1):
        # 用 DB 里的 interval_s（除非调用方强制覆盖）
        actual_interval = interval_s if interval_s > 0 else row_interval
        logger.info(
            f"[batch-run] [{idx}/{len(targets)}] 开始抓 #{row_id}: {name} "
            f"(interval={actual_interval}s)"
        )
        book_result = _fetch_one(row_id)
        results.append(book_result)
        if book_result.success:
            succeeded += 1
            logger.info(
                f"[batch-run] [{idx}/{len(targets)}] OK #{row_id}: {name} "
                f"({book_result.duration_ms}ms)"
            )
        else:
            failed += 1
            logger.warning(
                f"[batch-run] [{idx}/{len(targets)}] FAIL #{row_id}: {name} "
                f"({book_result.error_message})"
            )

        # 间隔（最后一本不 sleep）
        if idx < len(targets) and actual_interval > 0:
            logger.debug(f"[batch-run] sleeping {actual_interval}s before next book")
            time.sleep(actual_interval)

    total_ms = int((time.time() - start) * 1000)
    report = BatchFetchReport(
        total=len(targets),
        succeeded=succeeded,
        failed=failed,
        interval_s=interval_s,
        total_duration_ms=total_ms,
        results=results,
    )
    logger.info(
        f"[batch-run] done: {succeeded}/{len(targets)} succeeded, "
        f"{failed} failed, {total_ms}ms total"
    )
    return report


def batch_enqueue_pending() -> dict:
    """把 DB pending 状态的书入队 TaskQueue，Worker 异步跑。

    Returns:
        {total, queued, skipped, execution_uuids, task_ids}
    """
    from src.scheduler.queue import TaskQueue
    from src.scheduler.models import (
        ScheduledTask, TaskStatus, TaskType, TriggerType,
    )

    with SessionLocal() as sess:
        rows = (
            sess.query(FanqieBatchBook)
            .filter(FanqieBatchBook.status == FanqieBatchStatus.PENDING.value)
            .all()
        )
        targets = [(r.id, r.book_name, r.chapters, r.interval_s) for r in rows]

    if not targets:
        return {
            "total": 0, "queued": 0, "skipped": 0,
            "execution_uuids": [], "task_ids": [],
        }

    results = {
        "total": len(targets),
        "queued": 0,
        "skipped": 0,
        "execution_uuids": [],
        "task_ids": [],
    }
    with SessionLocal() as sess:
        queue = TaskQueue(sess)
        for idx, (row_id, name, chapters, interval_s) in enumerate(targets, start=1):
            task = ScheduledTask(
                name=f"fanqie-batch-#{row_id}-{name}",
                description=f"批量抓取 #{row_id}: {name} ({chapters} 章)",
                task_type=TaskType.QUEUE.value,
                skill_name="fanqie_batch_run",
                skill_params={
                    "row_id": row_id,
                    "interval_s": float(interval_s),
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
            enqueue_result = queue.enqueue_now(
                skill_name="fanqie_batch_run",
                skill_params={
                    "row_id": row_id,
                    "interval_s": float(interval_s),
                },
                name=f"fanqie-batch-#{row_id}-{name}-{idx}",
            )
            if enqueue_result.success:
                results["queued"] += 1
                results["task_ids"].append(task.id)
                if enqueue_result.execution_uuid:
                    results["execution_uuids"].append(enqueue_result.execution_uuid)
                logger.info(
                    f"[batch-enqueue] [{idx}/{len(targets)}] queued #{row_id}: {name} "
                    f"(task_id={task.id})"
                )
            else:
                results["skipped"] += 1
                logger.warning(
                    f"[batch-enqueue] [{idx}/{len(targets)}] 入队失败 #{row_id}: "
                    f"{enqueue_result.message}"
                )

    return results


def seed_from_yaml(yaml_path: str = "config/fanqie_batch_books.yaml") -> dict:
    """从 YAML 种子清单导入到 DB（首次启动时调用）。

    YAML 格式：
        books:
          - name: "我的6个超级奶爸"
            chapters: 5
            interval_s: 30
            note: "KOL 推荐 Top 1"
    """
    import yaml

    path = Path(yaml_path)
    if not path.exists():
        return {"yaml_exists": False, "imported": 0, "skipped": 0}

    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as exc:
        logger.warning(f"[seed] YAML 解析失败: {exc}")
        return {"yaml_exists": True, "imported": 0, "skipped": 0, "error": str(exc)}

    books = data.get("books") or []
    if not books:
        return {"yaml_exists": True, "imported": 0, "skipped": 0}

    names = [b.get("name", "").strip() for b in books if b.get("name")]
    # 取第一个 book 的 chapters/interval 当默认
    first = books[0] if books else {}
    chapters = int(first.get("chapters", 5))
    interval_s = int(first.get("interval_s", 30))
    note = first.get("note", "")

    add_result = add_books(names, chapters=chapters, interval_s=interval_s, note=note)
    return {
        "yaml_exists": True,
        "yaml_path": str(path),
        "imported": add_result["added"],
        "skipped": add_result["skipped"],
        "added_ids": add_result["added_ids"],
    }
