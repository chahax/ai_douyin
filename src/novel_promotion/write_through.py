"""
src/novel_promotion/write_through.py — 旧命令兼容写入同步

旧命令 (fanqie-book-fetch, fanqie-promo-apply, fanqie-promo-list)
在文件写入成功后同步数据库和事件。同步失败返回 partial_failure/非零，
不得继续宣称成功，并留下可由 reconcile 发现的明确问题产物。
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.shared.database import SessionLocal
from .models import (
    FanqieBook,
    FanqiePromotionTask,
    FanqiePromotionTaskAlias,
    FanqieOperationEvent,
    BookMaterialStatus,
    TaskStatus,
    EventType,
)
from .repositories import BookRepository, PromotionTaskRepository
from .import_service import normalize_book_id
from .state_machine import map_old_status

logger = logging.getLogger(__name__)

# Deprecation mapping: old command → new target command
DEPRECATION_MAP = {
    "fanqie-book-fetch": "fanqie-task-fetch-material",
    "fanqie-promo-apply": "fanqie-task-apply",
    "fanqie-promo-list": "fanqie-task-sync-status",
}


def _deprecation_notice(old_cmd: str) -> str:
    new_cmd = DEPRECATION_MAP.get(old_cmd, "fanqie-task-list")
    return (
        f"[DEPRECATED] '{old_cmd}' 将在未来版本移除。"
        f"推荐使用新命令: {new_cmd}"
    )


def _now():
    return datetime.now(timezone.utc)


def _write_failed_artifact(old_cmd: str, reason: str, detail: dict) -> Path:
    """Write a reconciliation artifact for a failed write-through attempt."""
    import uuid
    ts = _now().strftime("%Y%m%d_%H%M%S_%f")
    uid = uuid.uuid4().hex[:8]
    path = Path("data/fanqie_promotion") / ".reconcile" / f"write_through_failed_{ts}_{uid}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "timestamp": _now().isoformat(),
            "old_command": old_cmd,
            "reason": reason,
            "detail": detail,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def sync_book_fetch_result(book_name: str, result: dict) -> dict:
    """Write-through for fanqie-book-fetch.

    Called after the browser successfully fetches book content.
    Returns {"success": True/False, "action": str, "reason": str}.

    - Missing book_id after file success is partial_failure with artifact
      (not successful skipped), because the file was written but DB could not
      record a master book record.
    - Links matching fanqie_batch_books rows via fanqie_book_pk in the
      same transaction.
    """
    old_cmd = "fanqie-book-fetch"
    deprecation = _deprecation_notice(old_cmd)
    logger.warning(deprecation)
    print(deprecation, flush=True)

    try:
        with SessionLocal() as db:
            repo = BookRepository(db)
            fanqie_id = str(result.get("book_id", ""))
            if not fanqie_id:
                # File success but no book_id → partial_failure
                msg = "book fetch succeeded (file written) but no book_id in result"
                artifact = _write_failed_artifact(old_cmd, msg,
                                                   {"book_name": book_name, "result_keys": list(result.keys())})
                return {
                    "success": False,
                    "action": "partial_failure",
                    "reason": f"{msg}. Reconcile artifact: {artifact}",
                    "artifact_path": str(artifact),
                }

            book = repo.find_or_create(
                fanqie_book_id=fanqie_id,
                book_name=book_name or result.get("book_name", ""),
            )
            if result.get("author"):
                book.author = book.author or result["author"]
            book.material_status = BookMaterialStatus.MATERIAL_READY
            book.updated_at = _now()

            # Append event
            db.add(FanqieOperationEvent(
                task_id=None,
                event_type=EventType.IMPORT,
                actor_type="fanqie-book-fetch",
                payload_json={
                    "book_name": book_name,
                    "fanqie_book_id": fanqie_id,
                    "source": "write_through",
                },
            ))

            # Link matching fanqie_batch_books rows via fanqie_book_pk
            _link_batch_books(db, book, fanqie_id)

            db.commit()
            return {"success": True, "action": "synced", "book_id": book.id}
    except Exception as exc:
        artifact = _write_failed_artifact(old_cmd, str(exc), {"book_name": book_name})
        return {
            "success": False,
            "action": "partial_failure",
            "reason": f"DB write failed: {exc}. Reconcile artifact: {artifact}",
            "artifact_path": str(artifact),
        }


def sync_promotion_apply_result(task_data: dict) -> dict:
    """Write-through for fanqie-promo-apply.

    Called after the browser successfully submits a promotion application.

    Supports the actual ``FanqiePromotionTask`` dataclass contract:
    - ``task_id`` (platform_task_id), ``book_name``, ``book_url``
    - NO ``book_id`` — instead, parse numeric book ID from ``book_url``
      or accept ``fanqie_book_id`` when explicitly supplied.
    - Never create an unidentifiable master book with null external id;
      return partial_failure and write a reconcile artifact.
    """
    old_cmd = "fanqie-promo-apply"
    deprecation = _deprecation_notice(old_cmd)
    logger.warning(deprecation)
    print(deprecation, flush=True)

    try:
        with SessionLocal() as db:
            repo = BookRepository(db)
            task_repo = PromotionTaskRepository(db)

            # Resolve fanqie_book_id: prefer explicit field, else parse from book_url
            fanqie_id = normalize_book_id(str(task_data.get("fanqie_book_id", "") or task_data.get("book_id", "")))
            if not fanqie_id:
                book_url = task_data.get("book_url", "")
                if book_url:
                    fanqie_id = normalize_book_id(str(book_url))

            if not fanqie_id:
                # Cannot create an unidentifiable master book — partial_failure
                msg = "Cannot identify book: no fanqie_book_id and no parseable book_id from book_url"
                artifact = _write_failed_artifact(old_cmd, msg, {
                    "task_data_keys": list(task_data.keys()),
                    "book_url": str(task_data.get("book_url", "")),
                })
                return {
                    "success": False,
                    "action": "partial_failure",
                    "reason": f"{msg}. Reconcile artifact: {artifact}",
                    "artifact_path": str(artifact),
                }

            book = repo.find_or_create(
                fanqie_book_id=fanqie_id,
                book_name=task_data.get("book_name", ""),
            )

            alias = task_data.get("promotion_alias", "")
            if alias:
                existing = task_repo.find_by_alias(book.id, alias)
                if existing:
                    return {
                        "success": True,
                        "action": "skipped",
                        "reason": f"Task already exists for alias '{alias}' (task_id={existing.id})",
                    }

            task = task_repo.create(
                book_id=book.id,
                promotion_alias=alias,
                publish_type=task_data.get("publish_type", ""),
                platform_task_id=task_data.get("platform_task_id") or task_data.get("task_id"),
                status=TaskStatus.APPLYING,
                created_by="fanqie-promo-apply",
            )

            if alias:
                db.add(FanqiePromotionTaskAlias(
                    task_id=task.id,
                    alias=alias,
                    is_current=True,
                ))

            db.add(FanqieOperationEvent(
                task_id=task.id,
                event_type=EventType.STATUS_CHANGE,
                to_status=TaskStatus.APPLYING,
                actor_type="fanqie-promo-apply",
                payload_json={"source": "write_through"},
            ))
            db.commit()
            return {
                "success": True,
                "action": "synced",
                "task_id": task.id,
                "task_uuid": task.task_uuid,
            }
    except Exception as exc:
        artifact = _write_failed_artifact(old_cmd, str(exc), {
            "book_id": str(task_data.get("book_id", "")),
            "alias": task_data.get("promotion_alias", ""),
        })
        return {
            "success": False,
            "action": "partial_failure",
            "reason": f"DB write failed: {exc}. Reconcile artifact: {artifact}",
            "artifact_path": str(artifact),
        }


def sync_promotion_list_result(items: list[dict]) -> dict:
    """Write-through for fanqie-promo-list.

    Called after the browser successfully scans the promotion list.
    Updates task statuses in DB based on the list data.

    - Prefers ``alias_status_internal`` when present (pre-mapped enum).
    - Falls back to mapping Chinese statuses via ``map_old_status``.
    - On per-item sync errors, writes a reconcile artifact describing
      partial commits/errors.
    """
    old_cmd = "fanqie-promo-list"
    deprecation = _deprecation_notice(old_cmd)
    logger.warning(deprecation)
    print(deprecation, flush=True)

    synced = 0
    skipped = 0
    errors = []

    try:
        with SessionLocal() as db:
            repo = BookRepository(db)
            task_repo = PromotionTaskRepository(db)

            for item in items:
                try:
                    fanqie_id = normalize_book_id(str(item.get("book_id", "")))
                    alias = item.get("promotion_alias") or item.get("alias", "")

                    if not alias:
                        skipped += 1
                        continue

                    # Must not create FanqieBook with null/empty external id
                    if not fanqie_id:
                        err_detail = {
                            "item": alias,
                            "error": "Missing or unparseable book_id; cannot identify book",
                            "raw_book_id": str(item.get("book_id", "")),
                            "book_name": item.get("book_name", ""),
                        }
                        errors.append(err_detail)
                        _write_failed_artifact(
                            old_cmd,
                            f"Per-item sync error: no book_id for alias '{alias}'",
                            err_detail,
                        )
                        continue

                    # Prefer pre-mapped internal status, else map from raw
                    raw_status = (
                        item.get("alias_status_internal")
                        or item.get("apply_status")
                        or item.get("alias_status", "")
                    )
                    # map_old_status handles Chinese statuses (生效中→active, etc.)
                    new_status = map_old_status(raw_status)

                    book = repo.find_or_create(
                        fanqie_book_id=fanqie_id,
                        book_name=item.get("book_name", ""),
                    )

                    existing = task_repo.find_by_alias(book.id, alias)
                    if existing:
                        if existing.status != new_status:
                            task_repo.transition_status(
                                existing,
                                new_status,
                                actor_type="fanqie-promo-list",
                                payload={"source": "write_through", "raw_status": raw_status},
                            )
                        synced += 1
                    else:
                        skipped += 1
                except Exception as e:
                    err_detail = {
                        "item": str(item.get("alias", "")),
                        "error": str(e),
                    }
                    errors.append(err_detail)
                    # Write per-item reconcile artifact
                    _write_failed_artifact(
                        old_cmd,
                        f"Per-item sync error: {e}",
                        err_detail,
                    )

            db.commit()
            result = {
                "success": True,
                "action": "synced",
                "synced": synced,
                "skipped": skipped,
                "errors": errors,
            }
            if errors:
                result["success"] = False
                result["action"] = "partial_failure"
                result["reason"] = f"{len(errors)} items had errors during sync; reconcile artifacts written"
            return result
    except Exception as exc:
        artifact = _write_failed_artifact(old_cmd, str(exc), {"item_count": len(items)})
        return {
            "success": False,
            "action": "partial_failure",
            "reason": f"DB write failed: {exc}. Reconcile artifact: {artifact}",
            "artifact_path": str(artifact),
        }


def _link_batch_books(db, book: FanqieBook, fanqie_id: str) -> None:
    """Link matching fanqie_batch_books rows to the imported book via fanqie_book_pk.

    Raises:
        Exception: Propagates all exceptions so the caller can roll back
                   the transaction and return partial_failure. Linking is
                   required in the same transaction.
    """
    from src.scheduler.models import FanqieBatchBook
    batch_books = db.query(FanqieBatchBook).filter(
        FanqieBatchBook.fanqie_book_pk.is_(None),
        FanqieBatchBook.book_id == fanqie_id,
    ).all()
    for bb in batch_books:
        bb.fanqie_book_pk = book.id
    if batch_books:
        db.flush()
