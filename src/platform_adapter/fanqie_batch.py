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

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from src.scheduler.models import FanqieBatchBook, FanqieBatchStatus
from src.shared.database import SessionLocal


logger = logging.getLogger(__name__)


# ──  Modal dismissal helpers (Arco Design informational modals) ─────

_SAFE_MODAL_DISMISS_TEXTS = (
    "关闭",
    "我知道了",
    "取消",
    "Close",
    "Cancel",
    "Dismiss",
)

_MODAL_CLOSE_ICON_SELECTORS = (
    ".arco-modal-close-icon",
    'button[aria-label="Close"]',
    ".arco-modal-close-btn",
)

_BUSINESS_MODAL_MARKERS = (
    "申请推广",
    "推广别名",
    "确认申请",
    "提交申请",
    "回填发文",
    "绑定视频",
    "确认发布",
)

_AUTH_MODAL_MARKERS = (
    "欢迎登录番茄达人",
    "验证码登录",
    "密码登录",
    "获取验证码",
    "登录/注册",
    "身份验证",
    "安全验证",
)


def _dismiss_known_modal(page) -> str:
    """Try to safely dismiss one visible Arco informational/announcement modal.

    Only clicks explicit close/cancel controls (close-icon buttons or safe
    dismiss-text buttons like "我知道了"/"关闭"/"取消").  Never touches
    confirm/submit/apply buttons.

    Returns:
        "none"   -- no Arco modal detected
        "closed" -- modal was safely dismissed

    Raises RuntimeError with diagnostic (visible text) when a modal is
    present but cannot be safely closed.
    """
    modal_sel = 'div[role="dialog"].arco-modal:visible'

    modal_count = page.locator(modal_sel).count()
    if modal_count == 0:
        return "none"
    if modal_count != 1:
        raise RuntimeError(f"Cannot safely close modal: {modal_count} visible dialogs")

    modal_text = ""
    try:
        modal_text = page.locator(modal_sel).first().inner_text() or ""
    except Exception:
        pass

    button_sel = f"{modal_sel} button, {modal_sel} .arco-btn"
    try:
        button_texts = [item.inner_text().strip() for item in page.locator(button_sel).all()]
    except Exception:
        button_texts = []

    if any(marker in modal_text for marker in _AUTH_MODAL_MARKERS):
        raise RuntimeError(
            "Fanqie authentication required; refusing to dismiss login modal. "
            f"Modal text: {modal_text[:200]!r}; buttons: {button_texts!r}"
        )

    if any(marker in modal_text for marker in _BUSINESS_MODAL_MARKERS):
        raise RuntimeError(
            "Refusing to close business modal. "
            f"Modal text: {modal_text[:200]!r}; buttons: {button_texts!r}"
        )

    for close_sel in _MODAL_CLOSE_ICON_SELECTORS:
        scoped_sel = f"{modal_sel} {close_sel}"
        if page.locator(scoped_sel).count() > 0:
            try:
                page.locator(scoped_sel).first().click()
                page.wait_for_timeout(500)
                if page.locator(modal_sel).count() == 0:
                    return "closed"
            except Exception:
                continue

    safe_indexes = [
        index
        for index, text in enumerate(button_texts)
        if text in _SAFE_MODAL_DISMISS_TEXTS
    ]
    if len(safe_indexes) == 1:
        try:
            page.locator(button_sel).nth(safe_indexes[0]).click()
            page.wait_for_timeout(500)
            if page.locator(modal_sel).count() == 0:
                return "closed"
        except Exception:
            pass

    raise RuntimeError(
        "Cannot safely close modal. "
        f"Modal text: {modal_text[:200]!r}; buttons: {button_texts!r}"
    )


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
    """加书到 DB 清单（自动去重）。"""
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
        row.last_fetched_at = datetime.utcnow()
        sess.commit()


def clear_all_books(*, status_filter: str | None = None) -> dict:
    """清空清单。

    Args:
        status_filter: 可选，只清指定状态（pending/running/done/failed/skipped）。None=全清。

    Returns:
        {"deleted": N, "kept": M}
    """
    with SessionLocal() as sess:
        q = sess.query(FanqieBatchBook)
        if status_filter:
            q = q.filter(FanqieBatchBook.status == status_filter)
        # 先 count，再 delete（避免 SQLAlchemy expired 对象问题）
        deleted = q.count()
        if status_filter:
            sess.query(FanqieBatchBook).filter(FanqieBatchBook.status == status_filter).delete()
        else:
            sess.query(FanqieBatchBook).delete()
        sess.commit()
        kept = sess.query(FanqieBatchBook).count()
    logger.info(f"[fanqie_batch] clear_all_books deleted={deleted} kept={kept} filter={status_filter}")
    return {"deleted": deleted, "kept": kept}


# ── 进度写盘（AI 助手页面 + 批量抓取页面共用）─────────
PROGRESS_FILE = Path("./data/fanqie_batch_progress.json")


def _write_progress(
    *,
    running: bool,
    phase: str = "",          # "scan" / "fetch" / "idle"
    current: int = 0,
    total: int = 0,
    current_book: str = "",
    succeeded: int = 0,
    failed: int = 0,
    headful: bool = False,
    extra: dict | None = None,
    event: str | None = None,    # P3：追加一行事件日志（"开始抓 X", "抓完第 N 章"）
) -> None:
    """写一个进度文件，给 Streamlit 页面做实时显示。

    失败也不抛——只是 UI 没进度，不影响主流程。

    P3 增量：每次调用可选 `event` 参数，自动 push 到 events 列表，
    streamlit 上面板显示最近 N 行"操作流水"（"开始扫榜"、"抓第 3 章
    2024 chars"等）。events 列表上限 80 条，超出 pop front。
    """
    try:
        PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
        # 先读旧文件，把 events 续上
        prior_events: list[dict] = []
        if PROGRESS_FILE.exists():
            try:
                prior = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
                prior_events = prior.get("events", [])
            except Exception:
                prior_events = []

        if event is not None:
            prior_events.append({
                "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "text": event,
            })
            if len(prior_events) > 80:
                prior_events = prior_events[-80:]

        payload = {
            "running": running,
            "phase": phase,
            "current": current,
            "total": total,
            "current_book": current_book,
            "succeeded": succeeded,
            "failed": failed,
            "headful": headful,
            "updated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "events": prior_events,
        }
        if extra:
            payload.update(extra)
        PROGRESS_FILE.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass  # 进度写盘失败不致命


def clear_progress() -> None:
    """Skill 完成（或失败）后清掉进度文件。"""
    try:
        if PROGRESS_FILE.exists():
            PROGRESS_FILE.unlink()
    except Exception:
        pass


def read_progress() -> dict | None:
    """Streamlit 页面读进度。文件不存在或损坏返回 None。"""
    if not PROGRESS_FILE.exists():
        return None
    try:
        return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


# ── 抓取执行（核心）───────────────────────────────────────────

def _fetch_one(book_id: int, headless: bool = True, service=None, session=None) -> BookFetchResult:
    """抓清单中一条 book。更新 DB 状态。

    Args:
        book_id: DB ID
        headless: 浏览器无头
        service: 共享 FanqiePromotionService（多本批量用同一实例）
        session: 共享 BrowserSession（多本批量用同一浏览器；None=自己开）
    """
    from src.platform_adapter.fanqie_promotion import FanqiePromotionService

    with SessionLocal() as sess:
        row = sess.query(FanqieBatchBook).filter_by(id=book_id).first()
        if not row:
            # 清单条目被删了（用户点过"清空清单"），不是真错。
            # 返回 success=True + skipped 标记，Worker 当作静默跳过。
            logger.warning(
                f"[batch-run] book_id={book_id} 在 DB 已不存在（已被清空？），跳过"
            )
            return BookFetchResult(
                book_name=f"<id={book_id} 已删除>",
                success=True,           # 让 Worker 当 OK 处理
                error_code="skipped",
                error_message="清单已被清理",
                duration_ms=0,
            )
        if row.status in {
            FanqieBatchStatus.DONE.value,
            FanqieBatchStatus.SKIPPED.value,
        }:
            logger.info(
                "[batch-run] book_id=%s 已是终态 %s，跳过重复执行",
                book_id,
                row.status,
            )
            return BookFetchResult(
                book_name=row.book_name,
                success=True,
                book_id=row.book_id or "",
                chapters_fetched=row.chapters_fetched or 0,
                total_chapters_seen=row.total_chapters_seen or 0,
                paywall_hit=bool(row.paywall_hit),
                error_code="skipped",
                error_message=f"清单已是终态 {row.status}",
                duration_ms=row.duration_ms or 0,
                material_path=row.material_path or "",
            )
        # 标记 running
        row.status = FanqieBatchStatus.RUNNING.value
        row.attempt_count += 1
        sess.commit()
        book_name = row.book_name
        chapters = row.chapters
        book_id_str = row.book_id or ""  # 保存原 book_id

    if service is None:
        service = FanqiePromotionService()
    book_start = time.time()
    try:
        result = service.fetch_book(
            book_name=book_name,
            chapters=chapters,
            headless=headless,
            session=session,  # 共享 BrowserSession（不重启浏览器）
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
    headless: bool = True,
) -> BatchFetchReport:
    """从 DB 读 status='pending' 的书，**同步阻塞**循环抓。

    Args:
        interval_s: 每本之间 sleep 秒数（覆盖 DB 设置）
        max_count: 本次最多抓几本（防止调度失控）
        headless: 浏览器无头模式（默认 True，加 --headful 可视化）

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

    # 进度写盘 — 让 AI 助手/批量抓取页面能实时显示
    _write_progress(
        running=True,
        phase="fetch",
        current=0,
        total=len(targets),
        current_book="准备中…",
        succeeded=0,
        failed=0,
        headful=not headless,
        event=f"📋 准备开始抓 {len(targets)} 本"
    )

    # 共享一个 BrowserSession：多本时只开一次浏览器，page.goto 切详情页
    session = service._open_browser_cache_session(headless=headless)
    try:
        for idx, (row_id, row_interval, name) in enumerate(targets, start=1):
            actual_interval = interval_s if interval_s > 0 else row_interval
            logger.info(
                f"[batch-run] [{idx}/{len(targets)}] 开始抓 #{row_id}: {name} "
                f"(interval={actual_interval}s, headless={headless})"
            )
            _write_progress(
                running=True, phase="fetch",
                current=idx - 1, total=len(targets),
                current_book=name, succeeded=succeeded, failed=failed,
                headful=not headless,
                extra={"status_text": f"抓第 {idx}/{len(targets)} 本: {name[:30]}"},
                event=f"▶️ [{idx}/{len(targets)}] 开始 #{row_id} {name[:30]}",
            )
            book_result = _fetch_one(row_id, headless=headless, service=service, session=session)
            results.append(book_result)
            if book_result.success:
                succeeded += 1
                logger.info(
                    f"[batch-run] [{idx}/{len(targets)}] OK #{row_id}: {name} "
                    f"({book_result.duration_ms}ms)"
                )
                _write_progress(
                    running=True, phase="fetch",
                    current=idx, total=len(targets),
                    current_book=name, succeeded=succeeded, failed=failed,
                    headful=not headless,
                    event=f"✅ [{idx}/{len(targets)}] 完成 #{row_id} {name[:25]} "
                          f"({book_result.duration_ms}ms, "
                          f"{book_result.chapters_fetched} 章)",
                )
            else:
                failed += 1
                logger.warning(
                    f"[batch-run] [{idx}/{len(targets)}] FAIL #{row_id}: {name} "
                    f"({book_result.error_message})"
                )
                _write_progress(
                    running=True, phase="fetch",
                    current=idx, total=len(targets),
                    current_book=name, succeeded=succeeded, failed=failed,
                    headful=not headless,
                    event=f"❌ [{idx}/{len(targets)}] 失败 #{row_id} {name[:25]} "
                          f"({book_result.error_code or '?'}: "
                          f"{(book_result.error_message or '')[:60]})",
                )

            # 抓完一本后再写一次进度，反映 succeeded/failed 计数
            _write_progress(
                running=True, phase="fetch",
                current=idx, total=len(targets),
                current_book=name, succeeded=succeeded, failed=failed,
                headful=not headless,
                extra={"status_text": f"{idx}/{len(targets)} 完成（{succeeded} 成功 / {failed} 失败）"},
            )

            if idx < len(targets) and actual_interval > 0:
                logger.debug(f"[batch-run] sleeping {actual_interval}s before next book")
                time.sleep(actual_interval)
    finally:
        session.stop()

    # 写终态（再保留 30 秒给 UI 看）
    _write_progress(
        running=True, phase="fetch",
        current=len(targets), total=len(targets),
        current_book="", succeeded=succeeded, failed=failed,
        headful=not headless,
        extra={"status_text": f"全部完成: {succeeded} 成功 / {failed} 失败", "completed": True},
        event=f"🏁 全部完成: {succeeded} 成功 / {failed} 失败 (共 {len(targets)} 本)"
    )

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
        ScheduledTask, TaskExecution, TaskStatus, TaskType, TriggerType,
    )

    results = {
        "total": 0,
        "queued": 0,
        "skipped": 0,
        "execution_uuids": [],
        "task_ids": [],
        "mappings": [],
    }
    with SessionLocal() as sess:
        rows = (
            sess.query(FanqieBatchBook)
            .filter(FanqieBatchBook.status == FanqieBatchStatus.PENDING.value)
            .order_by(FanqieBatchBook.added_at.asc())
            .all()
        )
        targets = [(r.id, r.book_name, r.chapters, r.interval_s) for r in rows]
        results["total"] = len(targets)

        # A second click while the first enqueue is still pending must not create
        # another task for the same book. Inspect the immutable execution
        # snapshots because they are the actual work items consumed by Worker.
        active_executions = (
            sess.query(TaskExecution)
            .join(ScheduledTask, TaskExecution.task_id == ScheduledTask.id)
            .filter(ScheduledTask.skill_name == "fanqie_batch_run")
            .filter(TaskExecution.status.in_([
                TaskStatus.PENDING.value,
                TaskStatus.RUNNING.value,
            ]))
            .all()
        )
        active_row_ids: set[int] = set()
        for execution in active_executions:
            snapshot = execution.skill_params_snapshot or {}
            try:
                active_row_ids.add(int(snapshot.get("row_id")))
            except (TypeError, ValueError):
                continue

        queue = TaskQueue(sess)
        for idx, (row_id, name, chapters, interval_s) in enumerate(targets, start=1):
            if row_id in active_row_ids:
                results["skipped"] += 1
                logger.info(
                    "[batch-enqueue] [%s/%s] #%s 已有 pending/running 执行，跳过",
                    idx,
                    len(targets),
                    row_id,
                )
                continue

            skill_params = {
                "row_id": row_id,
                "interval_s": float(interval_s),
            }
            task = ScheduledTask(
                name=f"fanqie-batch-#{row_id}-{name}",
                description=f"批量抓取 #{row_id}: {name} ({chapters} 章)",
                task_type=TaskType.QUEUE.value,
                skill_name="fanqie_batch_run",
                skill_params=skill_params,
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
            # Enqueue the ScheduledTask we just created. enqueue_now() creates
            # a different task row and was the source of the mapping bug.
            enqueue_result = queue.enqueue(task.id, skill_params)
            if enqueue_result.success:
                results["queued"] += 1
                results["task_ids"].append(task.id)
                results["mappings"].append({
                    "row_id": row_id,
                    "task_id": task.id,
                    "execution_uuid": enqueue_result.execution_uuid or "",
                })
                active_row_ids.add(row_id)
                if enqueue_result.execution_uuid:
                    results["execution_uuids"].append(enqueue_result.execution_uuid)
                logger.info(
                    f"[batch-enqueue] [{idx}/{len(targets)}] queued #{row_id}: {name} "
                    f"(task_id={task.id})"
                )
            else:
                # This definition belongs exclusively to the failed enqueue;
                # remove the orphan so the UI cannot show a task that never runs.
                sess.delete(task)
                sess.commit()
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


# ── 达人中心 list 扫描（Harness L5: 自动入库的辅助）─────────────

def _click_ranking_tab(page, idx):
    """Click a ranking-tab item, handling Arco modal interception.

    When a Playwright click on a ranking tab times out because an Arco
    informational modal overlays the page, this function inspects the modal,
    attempts safe dismissal, and retries the click exactly once.

    Does NOT use DOM force-click.  Raises immediately if no modal is found
    or if the modal cannot be safely dismissed.
    """
    selector = ".task-menu-second .task-menu-second-item"

    try:
        page.locator(selector).nth(idx).click()
        return
    except RuntimeError as exc:
        click_error = exc

    result = _dismiss_known_modal(page)
    if result == "none":
        raise click_error

    # Retry once after safe modal dismissal.
    try:
        page.locator(selector).nth(idx).click()
    except RuntimeError:
        raise RuntimeError(
            f"Click on ranking tab #{idx} failed after safe modal dismissal"
        ) from click_error


def _wait_for_active_ranking(page, expected: str, attempts: int = 20) -> None:
    """Require the page's visible active tab to match the requested ranking."""
    js = """
    () => {
      const tabs = Array.from(document.querySelectorAll(
        '.task-menu-second .task-menu-second-item'
      ));
      const active = tabs.find(element => element.classList.contains('active'));
      return active ? (active.innerText || active.textContent || '').trim() : '';
    }
    """
    last_active = ""
    for _attempt in range(max(1, attempts)):
        last_active = str(page.locator("").evaluate(js) or "").strip()
        if last_active == expected:
            return
        page.wait_for_timeout(250)
    # A login/business/unknown modal may appear only after the tab click.
    # Surface that stronger diagnosis instead of reporting a generic mismatch.
    modal_result = _dismiss_known_modal(page)
    if modal_result == "closed":
        raise RuntimeError(
            "Ranking switch not confirmed after safely closing an informational modal: "
            f"expected={expected!r}, active={last_active!r}"
        )
    raise RuntimeError(
        f"Ranking switch not confirmed: expected={expected!r}, active={last_active!r}"
    )


def add_books_from_kol_list(
    *,
    chapters: int = 5,
    interval_s: int = 30,
    note_prefix: str = "KOL 推荐池",
    target_count: int = 40,
    headful: bool = False,
) -> dict:
    """扫番茄达人中心 /page/content?tab_type=2 拿 ~40 本 unique（**默认**参数）。

    策略（**纯浏览器自动化**，不用 search API）：
      1. 打开 tab_type=2 默认页面（task-menu-second 默认"爆款榜"，filter 默认"全部"）
      2. click task-menu-second 切 4 个榜单（爆款/阅读/潜力/全部内容）
      3. 每个榜单 click 后等 2.5s + 收 10 本 unique
      4. 去重入库（4 × 10 ≈ 40 本）

    Returns:
        {
            "scanned": M,            # 总书数（含重复）
            "unique": N,             # 去重后
            "added": K,               # 新增到 DB
            "skipped": L,             # 已存在
            "added_books": [{"id", "book_name"}, ...],
            "rankings_visited": [...],
        }

    **若想自定义筛选**（gender/category/days/word_count 等），用 `add_books_from_kol_filtered(KolFilterArgs(...))`。
    """
    from src.platform_adapter.fanqie_promotion import FanqiePromotionService
    from src.platform_adapter.fanqie_kol_filter import KolFilterArgs
    from src.shared.logger import logger

    args = KolFilterArgs(
        ranking="爆款榜",  # 默认起点（实际会遍历 4 个）
        target_count=target_count,
    )

    service = FanqiePromotionService()
    session = service._open_browser_cache_session(headless=not headful)
    all_titles: list[str] = []
    rankings_visited: list[str] = []
    try:
        # 默认 URL（task-menu 默认"网文+爆款榜"）
        page = session.open_page(
            "https://kol.fanqieopen.com/page/content?tab_type=2&top_tab_genre=-1"
        )
        try:
            page.wait_for_selector(".book-hQ7GYr", timeout=10_000)
        except Exception:
            logger.warning("[batch-from-kol] 等 .book-hQ7GYr 超时")
        page.wait_for_timeout(2000)
        _dismiss_known_modal(page)

        # 4 个榜单 = 爆款榜 / 阅读榜 / 潜力榜 / 全部内容
        for idx, ranking in enumerate(KolFilterArgs._ALLOWED_RANKING):
            _click_ranking_tab(page, idx)
            _wait_for_active_ranking(page, ranking)
            page.wait_for_timeout(2500)
            tab_titles = _collect_kol_titles(page)
            rankings_visited.append(ranking)
            logger.info(f"[batch-from-kol] {ranking}: {len(tab_titles)} books")
            all_titles.extend(tab_titles)
            if len(set(all_titles)) >= target_count:
                logger.info(
                    f"[batch-from-kol] reached target_count={target_count}, stop"
                )
                break
    finally:
        session.stop()

    return _finalize_kol_scan(all_titles, rankings_visited, args, chapters, interval_s, note_prefix)


def add_books_from_kol_filtered(
    args,
    *,
    chapters: int = 5,
    interval_s: int = 30,
    note_prefix: str = "KOL 筛选",
    headful: bool = False,
) -> dict:
    """用 KolFilterArgs 拉 N 本。

    流程：
      1. validate 入参
      2. 跳达人中心 + 应用 ranking + 6 类 filter click
      3. 滚到底 + 拉够 target_count 本 unique
      4. 入库

    Returns:
        {
            "scanned": M,
            "unique": N,
            "added": K,
            "skipped": L,
            "added_books": [{"id", "book_name"}, ...],
            "filter_args": {...},         # 应用的筛选条件
        }
    """
    from src.platform_adapter.fanqie_promotion import FanqiePromotionService
    from src.platform_adapter.fanqie_kol_filter import apply_filters, scroll_to_load_books
    from src.shared.logger import logger

    args.validate()  # 失败抛 FilterValidationError

    service = FanqiePromotionService()
    session = service._open_browser_cache_session(headless=not headful)
    try:
        page = session.open_page(
            "https://kol.fanqieopen.com/page/content?tab_type=2&top_tab_genre=-1"
        )
        try:
            page.wait_for_selector(".book-hQ7GYr", timeout=10_000)
        except Exception:
            raise RuntimeError("达人中心书卡未渲染")
        page.wait_for_timeout(2000)

        # 进度：scan 阶段开始
        _write_progress(
            running=True, phase="scan",
            current=0, total=args.target_count,
            current_book=f"打开达人中心 + 应用 {args.ranking} 筛选",
            succeeded=0, failed=0,
            headful=headful,
            extra={"status_text": f"扫坂：{args.ranking}（目标 {args.target_count} 本）"},
            event=f"🔍 打开番茄达人中心 + 应用 {args.ranking} 筛选（目标 {args.target_count} 本）",
        )

        # 应用筛选（ranking + 6 类 filter click）
        apply_filters(page, args)
        _write_progress(
            running=True, phase="scan",
            current=0, total=args.target_count,
            current_book="筛选已应用，开始滚到底拉书",
            succeeded=0, failed=0,
            headful=headful,
            event="▶️ 筛选已应用，开始滚到底拉书",
        )

        # 滚到底 + 拉够 N 本
        unique_titles = scroll_to_load_books(
            page, target_count=args.target_count, max_scroll=30,
        )
        # 进度：scan 完成
        _write_progress(
            running=True, phase="scan",
            current=len(unique_titles), total=args.target_count,
            current_book=f"扫坂完成：{len(unique_titles)} 本 unique",
            succeeded=0, failed=0,
            headful=headful,
            extra={"status_text": f"扫坂完成 unique={len(unique_titles)}"},
            event=f"✅ 扫坂完成：{args.ranking} 拿到 {len(unique_titles)} 本 unique",
        )
    finally:
        session.stop()

    return _finalize_kol_scan(unique_titles, [args.ranking], args, chapters, interval_s, note_prefix)


def _collect_kol_titles(page) -> list[str]:
    """收当前页所有书卡书名（去重）。"""
    from src.platform_adapter.fanqie_kol_filter import _collect_book_titles
    return _collect_book_titles(page)


def _finalize_kol_scan(
    titles: list[str],
    rankings_visited: list[str],
    args,
    chapters: int,
    interval_s: int,
    note_prefix: str,
) -> dict:
    """收尾：去重 + 入库 + 返回。"""
    from src.shared.logger import logger

    unique = list(dict.fromkeys(titles))
    logger.info(
        f"[batch-from-kol] total scanned: {len(titles)}, unique: {len(unique)}"
    )

    if not unique:
        return {
            "scanned": 0, "unique": 0, "added": 0, "skipped": 0,
            "added_books": [],
            "rankings_visited": rankings_visited,
            "filter_args": args.describe(),
        }

    result = add_books(
        unique, chapters=chapters, interval_s=interval_s, note=note_prefix,
    )
    result["scanned"] = len(titles)
    result["unique"] = len(unique)
    result["rankings_visited"] = rankings_visited
    result["filter_args"] = args.describe()
    return result
