"""
src/novel_promotion/import_service.py — 幂等导入旧 JSON/文件数据到数据库

扫描 data/fanqie_promotion/books/*/meta.json 和 tasks/*/task.json，
导入到 fanqie_books 和 fanqie_promotion_tasks。

规则：
- 支持纯数字 book_id、含 ID 文本、番茄 URL 三种格式
- 无法解析写 reconcile 问题，不猜测
- 重复导入不重复任务/事件
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from .models import (
    FanqieBook,
    FanqiePromotionTask,
    FanqiePromotionTaskAlias,
    BookMaterialStatus,
    TaskStatus,
    EventType,
)
from .repositories import BookRepository, PromotionTaskRepository
from .state_machine import map_old_status

logger = logging.getLogger(__name__)


@dataclass
class ImportReport:
    books_created: int = 0
    books_updated: int = 0
    books_skipped: int = 0
    tasks_created: int = 0
    tasks_skipped: int = 0
    # Reconcile issues
    issues: list[dict] = field(default_factory=list)


# book_id normalization regex
_BOOK_ID_FROM_URL = re.compile(r'(?:book_id|/page/)(\d{10,24})')
_PURE_DIGITS = re.compile(r'^\d{10,24}$')
_DIGITS_IN_TEXT = re.compile(r'\b(\d{10,24})\b')


def normalize_book_id(raw: str) -> Optional[str]:
    """Parse book_id from raw input.

    Returns:
        Normalized book_id string, or None if unparseable.
    """
    if not raw or not raw.strip():
        return None
    raw = raw.strip()

    # 1) Pure digits
    if _PURE_DIGITS.match(raw):
        return raw

    # 2) URL parsing (e.g. https://fanqienovel.com/page/7577735918904151065)
    url_match = _BOOK_ID_FROM_URL.search(raw)
    if url_match:
        return url_match.group(1)

    # 3) Text containing a digit ID (e.g. "book 7577735918904151065")
    digit_match = _DIGITS_IN_TEXT.search(raw)
    if digit_match:
        return digit_match.group(1)

    # Cannot parse — return None for manual reconciliation
    return None


class BookIdReport:
    """Track book_id format classification."""

    def __init__(self):
        self.valid_numeric: list[str] = []
        self.empty: list[str] = []
        self.parsed_from_url: list[tuple[str, str]] = []  # (raw, parsed)
        self.invalid_format: list[str] = []
        self.ambiguous: list[str] = []

    def classify(self, raw: str) -> Optional[str]:
        if not raw or not raw.strip():
            self.empty.append(raw or "")
            return None
        raw_s = raw.strip()

        if _PURE_DIGITS.match(raw_s):
            self.valid_numeric.append(raw_s)
            return raw_s

        url_match = _BOOK_ID_FROM_URL.search(raw_s)
        if url_match:
            bid = url_match.group(1)
            self.parsed_from_url.append((raw_s, bid))
            return bid

        digit_match = _DIGITS_IN_TEXT.search(raw_s)
        if digit_match:
            bid = digit_match.group(1)
            self.ambiguous.append(raw_s)
            return bid  # parsed but flagged as ambiguous

        self.invalid_format.append(raw_s)
        return None

    def to_dict(self) -> dict:
        return {
            "valid_numeric_count": len(self.valid_numeric),
            "empty_count": len(self.empty),
            "parsed_from_url_count": len(self.parsed_from_url),
            "parsed_from_url": [{"raw": r, "parsed": p} for r, p in self.parsed_from_url],
            "invalid_format_count": len(self.invalid_format),
            "invalid_format": self.invalid_format[:20],
            "ambiguous_count": len(self.ambiguous),
            "ambiguous": self.ambiguous[:20],
        }


class ImportService:
    """Idempotent import of old file-based data into database tables."""

    def __init__(self, db: Session, data_root: str = "data/fanqie_promotion"):
        self.db = db
        self.data_root = Path(data_root)
        self.book_repo = BookRepository(db)
        self.task_repo = PromotionTaskRepository(db)

    def scan_book_id_formats(self) -> BookIdReport:
        """Scan all meta.json files and classify book_id formats.

        Must be run BEFORE import so operators can review the report.
        """
        report = BookIdReport()
        books_dir = self.data_root / "books"
        if not books_dir.exists():
            return report

        for entry in sorted(books_dir.iterdir()):
            if not entry.is_dir():
                continue
            meta_path = entry / "meta.json"
            if not meta_path.exists():
                continue
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            raw = meta.get("book_id", "")
            report.classify(str(raw) if raw else "")

        return report

    def dry_run(self) -> ImportReport:
        """Preview import without writing to DB.

        Returns counts of what would be created/updated/skipped.
        Checks existing DB records to provide accurate counts.
        """
        report = ImportReport()
        # Books
        books_dir = self.data_root / "books"
        if books_dir.exists():
            for entry in sorted(books_dir.iterdir()):
                if not entry.is_dir():
                    continue
                meta_path = entry / "meta.json"
                if not meta_path.exists():
                    continue
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:
                    continue

                fanqie_id = normalize_book_id(str(meta.get("book_id", "")))
                if not fanqie_id:
                    report.issues.append({
                        "source": str(meta_path),
                        "issue": "unparseable_book_id",
                        "raw_book_id": meta.get("book_id", ""),
                    })
                    continue

                existing = self.book_repo.get_by_fanqie_book_id(fanqie_id)
                if existing:
                    report.books_updated += 1
                else:
                    report.books_created += 1

        # Tasks
        tasks_dir = self.data_root / "tasks"
        if tasks_dir.exists():
            for entry in sorted(tasks_dir.iterdir()):
                if not entry.is_dir():
                    continue
                task_path = entry / "task.json"
                if not task_path.exists():
                    continue
                try:
                    data = json.loads(task_path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                old_task_id = data.get("task_id") or entry.name
                task_uuid = _task_id_to_uuid(old_task_id)
                existing_task = self.task_repo.get_by_uuid(task_uuid)
                if existing_task:
                    report.tasks_skipped += 1
                else:
                    report.tasks_created += 1

        return report

    def import_all(self) -> ImportReport:
        """Idempotent import of books and tasks from file system.

        - Books: upsert by fanqie_book_id
        - Tasks: create by task_uuid (old task_id → task_uuid)
        - Backfills fanqie_batch_books.fanqie_book_pk
        - Writes auditable events for all issues, not just in-process report
        - Does NOT modify original files
        - Duplicate imports are no-ops
        """
        report = ImportReport()

        # 1) Import books from meta.json
        book_map: dict[str, FanqieBook] = {}  # fanqie_book_id → book
        books_dir = self.data_root / "books"
        if books_dir.exists():
            for entry in sorted(books_dir.iterdir()):
                if not entry.is_dir():
                    continue
                meta_path = entry / "meta.json"
                if not meta_path.exists():
                    continue
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:
                    report.issues.append({
                        "source": str(meta_path),
                        "issue": "json_parse_error",
                    })
                    # Write auditable event for import issue
                    self._write_issue_event(
                        event_type=EventType.IMPORT,
                        payload={
                            "source": str(meta_path),
                            "issue": "json_parse_error",
                        },
                    )
                    continue

                fanqie_id = normalize_book_id(str(meta.get("book_id", "")))
                if not fanqie_id:
                    report.issues.append({
                        "source": str(meta_path),
                        "issue": "unparseable_book_id",
                        "raw_book_id": meta.get("book_id", ""),
                    })
                    self._write_issue_event(
                        event_type=EventType.IMPORT,
                        payload={
                            "source": str(meta_path),
                            "issue": "unparseable_book_id",
                            "raw_book_id": str(meta.get("book_id", "")),
                        },
                    )
                    continue

                existing = self.book_repo.get_by_fanqie_book_id(fanqie_id)
                if existing:
                    changed = False
                    # Update fields that may have changed (only when previously empty)
                    if meta.get("book_name") and not existing.book_name:
                        existing.book_name = meta["book_name"]
                        changed = True
                    if meta.get("author") and not existing.author:
                        existing.author = meta["author"]
                        changed = True
                    if meta.get("abstract") and not existing.abstract:
                        existing.abstract = meta["abstract"]
                        changed = True
                    if meta.get("categories"):
                        existing.categories_json = meta["categories"]
                        changed = True
                    if meta.get("tags"):
                        existing.tags_json = meta["tags"]
                        changed = True
                    if meta.get("total_chapters_seen"):
                        existing.word_count = existing.word_count or meta["total_chapters_seen"]
                        changed = True
                    if meta.get("material_status"):
                        existing.material_status = BookMaterialStatus.MATERIAL_READY
                        changed = True
                    if str(entry) != (existing.material_root or ""):
                        existing.material_root = str(entry)
                        changed = True
                    # Only touch updated_at when something actually changed
                    if changed:
                        existing.updated_at = datetime.now(timezone.utc)
                        report.books_updated += 1
                    else:
                        report.books_skipped += 1
                    book_map[fanqie_id] = existing
                else:
                    book = self.book_repo.upsert_by_fanqie_id(
                        fanqie_id,
                        book_name=meta.get("book_name", ""),
                        author=meta.get("author", ""),
                        abstract=meta.get("abstract", ""),
                        categories_json=meta.get("categories", []),
                        tags_json=meta.get("tags", []),
                        serial_status=meta.get("serial_status", ""),
                        word_count=meta.get("total_chapters_seen", 0),
                        material_status=BookMaterialStatus.MATERIAL_READY,
                        material_root=str(entry),
                    )
                    book_map[fanqie_id] = book
                    report.books_created += 1

        self.db.flush()

        # 1b) Backfill fanqie_batch_books.fanqie_book_pk
        _backfill_batch_book_pks(self.db, book_map)

        # 2) Import tasks from task.json
        tasks_dir = self.data_root / "tasks"
        if tasks_dir.exists():
            for entry in sorted(tasks_dir.iterdir()):
                if not entry.is_dir():
                    continue
                task_path = entry / "task.json"
                if not task_path.exists():
                    continue
                try:
                    data = json.loads(task_path.read_text(encoding="utf-8"))
                except Exception:
                    report.issues.append({
                        "source": str(task_path),
                        "issue": "json_parse_error",
                    })
                    self._write_issue_event(
                        event_type=EventType.IMPORT,
                        payload={
                            "source": str(task_path),
                            "issue": "json_parse_error",
                        },
                    )
                    continue

                old_task_id = data.get("task_id") or entry.name

                # Check idempotent — use task_uuid derived from old_task_id
                task_uuid = _task_id_to_uuid(old_task_id)
                existing_task = self.task_repo.get_by_uuid(task_uuid)
                if existing_task:
                    report.tasks_skipped += 1
                    continue

                # Map book reference
                raw_book_id = data.get("book_id") or data.get("fanqie_book_id") or ""
                fanqie_book_id = normalize_book_id(str(raw_book_id)) if raw_book_id else None
                book_pk = None
                if fanqie_book_id and fanqie_book_id in book_map:
                    book_pk = book_map[fanqie_book_id].id
                elif fanqie_book_id:
                    book = self.book_repo.get_by_fanqie_book_id(fanqie_book_id)
                    if book:
                        book_pk = book.id

                # Map status
                old_status = data.get("apply_status", "unknown")
                new_status = map_old_status(old_status)

                # Parse valid_range → valid_from / valid_until
                valid_from, valid_until = _parse_valid_range(
                    data.get("valid_range", "")
                )

                task = self.task_repo.create(
                    task_uuid=task_uuid,
                    book_id=book_pk,
                    platform_task_id=data.get("platform_task_id") or old_task_id,
                    promotion_alias=data.get("promotion_alias", ""),
                    publish_type=data.get("publish_type", ""),
                    status=new_status,
                    valid_from=valid_from,
                    valid_until=valid_until,
                    application_snapshot_path=str(task_path),
                    created_by=data.get("created_by", "import"),
                    created_at=_parse_iso(data.get("created_at")),
                )

                # Add alias record
                alias = data.get("promotion_alias", "")
                if alias:
                    self.db.add(FanqiePromotionTaskAlias(
                        task_id=task.id,
                        alias=alias,
                        is_current=True,
                    ))

                # Import event
                self.task_repo.append_event(
                    task.id,
                    EventType.IMPORT,
                    from_status=None,
                    to_status=new_status,
                    actor_type="import",
                    payload={
                        "source_file": str(task_path),
                        "old_task_id": old_task_id,
                        "old_status": old_status,
                    },
                )

                report.tasks_created += 1

        self.db.commit()
        return report

    def _write_issue_event(self, event_type: str, payload: dict) -> None:
        """Write an auditable operation event for an import issue.

        task_id is NULL because the issue may occur before a task exists.
        """
        from .models import FanqieOperationEvent
        event = FanqieOperationEvent(
            task_id=None,
            event_type=event_type,
            actor_type="import",
            payload_json=payload,
        )
        self.db.add(event)
        self.db.flush()


def _backfill_batch_book_pks(db: Session, book_map: dict[str, FanqieBook]) -> None:
    """Backfill fanqie_batch_books.fanqie_book_pk for newly imported books.

    Matches fanqie_batch_books.book_id (which stores the fanqie_book_id string)
    against imported fanqie_books.fanqie_book_id. Also tries URL parsing.
    """
    from src.scheduler.models import FanqieBatchBook
    batch_books = db.query(FanqieBatchBook).filter(
        FanqieBatchBook.fanqie_book_pk.is_(None)
    ).all()

    for bb in batch_books:
        raw = (bb.book_id or "").strip()
        if not raw:
            continue

        # Direct match: pure numeric fanqie_book_id
        matched_book = book_map.get(raw)
        if not matched_book:
            # Try URL parsing
            normalized = normalize_book_id(raw)
            if normalized:
                matched_book = book_map.get(normalized)

        if matched_book:
            bb.fanqie_book_pk = matched_book.id
    db.flush()


def _task_id_to_uuid(old_task_id: str) -> str:
    """Derive a stable UUID from old task_id for idempotent import."""
    import hashlib
    return hashlib.md5(f"fanqie_task:{old_task_id}".encode()).hexdigest()


def _parse_valid_range(range_str: str) -> tuple:
    """Parse valid_range like '2026-06-29 ~ 2026-12-26' into two datetimes.

    The separator is ' ~ ' (space-tilde-space). We must NOT split on hyphens
    inside dates like '2026-06-29'.
    """
    from datetime import datetime, timezone
    valid_from = None
    valid_until = None
    if not range_str:
        return valid_from, valid_until

    # Only split on ~ or ～ (with optional surrounding whitespace). Never on hyphen.
    parts = re.split(r'\s*[~～]\s*', range_str.strip(), maxsplit=1)
    fmt = "%Y-%m-%d"
    if len(parts) >= 1 and parts[0]:
        try:
            valid_from = datetime.strptime(parts[0].strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    if len(parts) >= 2 and parts[1]:
        try:
            valid_until = datetime.strptime(parts[1].strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return valid_from, valid_until


def _parse_iso(s: Optional[str]):
    """Parse ISO datetime string."""
    from datetime import datetime, timezone
    if not s:
        return datetime.now(timezone.utc)
    try:
        from dateutil.parser import parse as dateparse
        dt = dateparse(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.now(timezone.utc)
