"""
src/novel_promotion/reconcile_service.py — 文件与数据库差异巡检

fanqie-task-reconcile 的实现：对比文件系统和数据库，
报告 file_only / db_only / hash_mismatch / status_mismatch。
不自动覆盖冲突。
"""

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from .repositories import BookRepository, PromotionTaskRepository
from .import_service import normalize_book_id

logger = logging.getLogger(__name__)


@dataclass
class ReconcileEntry:
    type: str  # file_only, db_only, hash_mismatch, status_mismatch
    source: str = ""
    file_status: Optional[str] = None
    db_status: Optional[str] = None
    file_alias: Optional[str] = None
    db_alias: Optional[str] = None
    file_book_id: Optional[str] = None
    db_book_id: Optional[str] = None
    file_hash: Optional[str] = None
    db_hash: Optional[str] = None
    detail: str = ""


@dataclass
class ReconcileReport:
    entries: list[ReconcileEntry] = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    def add(self, entry: ReconcileEntry):
        self.entries.append(entry)

    def finalize(self):
        counts = {}
        for e in self.entries:
            counts[e.type] = counts.get(e.type, 0) + 1
        self.summary = counts


class ReconcileService:
    """Compare file-system tasks with database records.

    Uses fanqie_book_id (external) + promotion_alias as the matching key
    so that file and DB are compared by the same external identifier.
    """

    def __init__(self, db: Session, data_root: str = "data/fanqie_promotion"):
        self.db = db
        self.data_root = Path(data_root)
        self.book_repo = BookRepository(db)
        self.task_repo = PromotionTaskRepository(db)

    def reconcile(self) -> ReconcileReport:
        """Run full reconciliation between files and DB.

        Returns a ReconcileReport with all discrepancies.
        Does NOT auto-fix any conflicts.
        """
        report = ReconcileReport()

        # 1) Build a fanqie_book_id → book lookup
        db_books = self.book_repo.list_all()
        db_book_by_fanqie_id: dict[str, any] = {}
        db_book_by_pk: dict[int, any] = {}
        for b in db_books:
            if b.fanqie_book_id:
                db_book_by_fanqie_id[b.fanqie_book_id] = b
            db_book_by_pk[b.id] = b

        # 2) Index DB tasks by (fanqie_book_id, promotion_alias)
        db_tasks = self.task_repo.list_all()
        db_index: dict[str, list] = {}
        for t in db_tasks:
            # Resolve book's external fanqie_book_id from book_id FK
            fanqie_id = None
            if t.book_id and t.book_id in db_book_by_pk:
                fanqie_id = db_book_by_pk[t.book_id].fanqie_book_id
            key = f"{fanqie_id or ''}:{t.promotion_alias or ''}"
            db_index.setdefault(key, []).append(t)

        # 3) Scan file-system tasks
        tasks_dir = self.data_root / "tasks"
        file_task_keys: set[str] = set()
        if tasks_dir.exists():
            for entry in sorted(tasks_dir.iterdir()):
                if not entry.is_dir():
                    continue
                task_path = entry / "task.json"
                if not task_path.exists():
                    continue
                try:
                    raw_content = task_path.read_text(encoding="utf-8")
                    data = json.loads(raw_content)
                except Exception:
                    report.add(ReconcileEntry(
                        type="file_only",
                        source=str(task_path),
                        detail="json_parse_error",
                    ))
                    continue

                # Compute file content hash
                file_hash = hashlib.sha256(raw_content.encode()).hexdigest()[:16]

                raw_book_id = data.get("book_id") or data.get("fanqie_book_id") or ""
                fanqie_book_id = normalize_book_id(str(raw_book_id)) if raw_book_id else None
                file_alias = data.get("promotion_alias", "")
                file_status = data.get("apply_status", "")

                key = f"{fanqie_book_id or ''}:{file_alias or ''}"
                file_task_keys.add(key)

                if key in db_index:
                    db_tasks_for_key = db_index[key]
                    matched = False
                    for db_task in db_tasks_for_key:
                        from .state_machine import map_old_status
                        mapped_file_status = map_old_status(file_status)

                        # Resolve db_task's external book ID from its book FK
                        db_fanqie_id = None
                        if db_task.book_id and db_task.book_id in db_book_by_pk:
                            db_fanqie_id = db_book_by_pk[db_task.book_id].fanqie_book_id

                        # Status comparison
                        if db_task.status != mapped_file_status:
                            report.add(ReconcileEntry(
                                type="status_mismatch",
                                source=str(task_path),
                                file_status=mapped_file_status,
                                db_status=db_task.status,
                                file_alias=file_alias,
                                db_alias=db_task.promotion_alias,
                                file_book_id=fanqie_book_id,
                                db_book_id=db_fanqie_id,
                                file_hash=file_hash,
                                detail=f"File: {file_status}→{mapped_file_status}, DB: {db_task.status}",
                            ))
                        else:
                            # Status matches — check hash if available
                            # DB doesn't store task.json hash directly, but we can compare
                            # against application_snapshot_path content hash
                            db_hash = None
                            if db_task.application_snapshot_path:
                                try:
                                    db_raw = Path(db_task.application_snapshot_path).read_text(encoding="utf-8")
                                    db_hash = hashlib.sha256(db_raw.encode()).hexdigest()[:16]
                                except Exception:
                                    pass

                            if db_hash and file_hash and db_hash != file_hash:
                                report.add(ReconcileEntry(
                                    type="hash_mismatch",
                                    source=str(task_path),
                                    file_status=mapped_file_status,
                                    db_status=db_task.status,
                                    file_alias=file_alias,
                                    db_alias=db_task.promotion_alias,
                                    file_book_id=fanqie_book_id,
                                    db_book_id=db_fanqie_id,
                                    file_hash=file_hash,
                                    db_hash=db_hash,
                                    detail=f"File hash: {file_hash}, DB snapshot hash: {db_hash}",
                                ))

                        matched = True
                        break
                    if not matched:
                        report.add(ReconcileEntry(
                            type="file_only",
                            source=str(task_path),
                            file_status=mapped_file_status,
                            file_alias=file_alias,
                            file_book_id=fanqie_book_id,
                            detail="no_matching_db_record",
                        ))
                else:
                    report.add(ReconcileEntry(
                        type="file_only",
                        source=str(task_path),
                        file_status=file_status,
                        file_alias=file_alias,
                        file_book_id=fanqie_book_id,
                        file_hash=file_hash,
                        detail="not_in_db",
                    ))

        # 4) Find db_only tasks
        for key, db_tasks_for_key in db_index.items():
            if key not in file_task_keys:
                for db_task in db_tasks_for_key:
                    fanqie_id = None
                    if db_task.book_id and db_task.book_id in db_book_by_pk:
                        fanqie_id = db_book_by_pk[db_task.book_id].fanqie_book_id
                    report.add(ReconcileEntry(
                        type="db_only",
                        source=f"db:task:{db_task.id}",
                        db_status=db_task.status,
                        db_alias=db_task.promotion_alias,
                        db_book_id=fanqie_id,
                        detail="not_in_filesystem",
                    ))

        report.finalize()
        return report
