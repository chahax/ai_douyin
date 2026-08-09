"""
Tests for fanqie closed-loop P0: models, migration, state machine, P0-A probe,
repositories, import service, reconcile service, write-through, publish service,
cross-DB validation, transaction isolation, and CLI.

Usage:
  pytest tests/test_novel_promotion_p0.py -v
  pytest tests/test_novel_promotion_p0.py -v -k "test_p0a"
  pytest tests/test_novel_promotion_p0.py -v -k "test_migration"
"""

import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.shared.database import Base
from src.novel_promotion.models import (
    FanqieBook, FanqieChapter, FanqiePromotionTask, FanqiePromotionTaskAlias,
    FanqieDouyinAccount, FanqiePublishRecord, FanqieOperationEvent, FanqieBinding,
    TaskStatus, EventType, PublishStatus, BookMaterialStatus,
)
from src.novel_promotion.state_machine import (
    can_transition, must_transition, is_terminal, map_old_status,
    OLD_STATUS_MAP, is_non_terminal_for_alias,
)
from src.novel_promotion.repositories import (
    BookRepository, PromotionTaskRepository, DouyinAccountRepository,
    PublishRecordRepository, DouyinLegacyVideoRepository,
)
from src.novel_promotion.task_service import TaskService
from src.novel_promotion.import_service import (
    ImportService, normalize_book_id, BookIdReport, _parse_valid_range,
)
from src.novel_promotion.publish_service import NovelPromotionPublishSyncService
from src.novel_promotion.reconcile_service import ReconcileService, ReconcileEntry
from src.novel_promotion.p0a_probe import (
    parse_list_items, desensitize_text,
    run_probe_from_raw_data, parse_row, _normalize_headers,
)
from src.novel_promotion.write_through import (
    sync_book_fetch_result, sync_promotion_apply_result,
    sync_promotion_list_result, DEPRECATION_MAP,
)

try:
    from alembic.config import Config as AlembicConfig
    from alembic import command as alembic_command
    HAS_ALEMBIC = True
except ImportError:
    HAS_ALEMBIC = False


# ── Helpers ────────────────────────────────────────────────────────────────

def _now():
    return datetime.now(timezone.utc)


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(eng)
    with eng.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
    return eng


@pytest.fixture
def db(engine):
    session = Session(engine)
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def book_repo(db):
    return BookRepository(db)


@pytest.fixture
def task_repo(db):
    return PromotionTaskRepository(db)


@pytest.fixture
def task_service(db):
    return TaskService(db)


@pytest.fixture
def sample_book(book_repo):
    return book_repo.upsert_by_fanqie_id(
        "7577735918904151065", book_name="synthetic_test_book",
        author="测试作者",
    )


@pytest.fixture
def sample_task(task_repo, sample_book):
    return task_repo.create(
        book_id=sample_book.id, promotion_alias="synthetic_test_alias",
        publish_type="AI数字人", created_by="test",
        status=TaskStatus.ACTIVE,
    )


@pytest.fixture
def p0a_fixture():
    path = Path(__file__).parent / "fixtures" / "p0a_sample_list.json"
    return json.loads(path.read_text(encoding="utf-8"))


# ── P0-A Probe Tests ───────────────────────────────────────────────────────

class TestP0ADesensitization:
    def test_desensitize_alias(self):
        r = desensitize_text("synthetic_alias_alpha", "alias")
        assert r.startswith("<alias_")
        assert "synthetic_alias_alpha" not in r

    def test_desensitize_book_name(self):
        r = desensitize_text("synthetic_novel_one", "book_name")
        assert r.startswith("<book_name_")

    def test_desensitize_empty(self):
        assert desensitize_text("", "alias") == ""

    def test_desensitize_preserves_status_keywords(self):
        assert desensitize_text("未填写", "fill") == "未填写"
        assert desensitize_text("生效中", "status") == "生效中"

    def test_desensitize_stable_hash(self):
        a1 = desensitize_text("synthetic_alias_alpha", "alias")
        a2 = desensitize_text("synthetic_alias_alpha", "alias")
        assert a1 == a2

    def test_desensitize_url(self):
        r = desensitize_text("https://example.com/video/12345?token=s", "fill")
        assert r.startswith("<url_")
        assert "token" not in r

    def test_desensitize_non_url_fill(self):
        r = desensitize_text("some_unknown_value", "fill")
        assert r.startswith("<fill_")


class TestP0AHeaderParsing:
    def test_normalize_headers_current(self):
        r = _normalize_headers({"alias": "x", "book_name": "y", "book_id": "z"})
        assert r["alias"] == "x"

    def test_normalize_headers_legacy(self):
        r = _normalize_headers({"promotion_alias": "x", "novel_name": "y"})
        assert r["alias"] == "x"
        assert r["book_name"] == "y"

    def test_normalize_headers_unknown_ignored(self):
        r = _normalize_headers({"alias": "a", "unknown_field": "ignored"})
        assert "unknown_field" not in r

    def test_parse_row_basic(self):
        row = {"alias": "test", "book_name": "book", "book_id": "1" * 19,
               "content_type": "小说", "publish_type": "AI数字人",
               "alias_status": "已失效", "book_status": "正常",
               "fill_status": "未填写", "has_fill_link": False,
               "created_at": "2026-01-15", "valid_range": "2026-01-15 ~ 2026-07-15"}
        e = parse_row(row, 0)
        assert e.row_index == 0
        assert e.alias.startswith("<alias_")
        assert len(e.book_id_hash) == 12
        assert e.internal_status == "expired"

    def test_parse_row_fill_status_url_desensitized(self):
        row = {"alias": "t", "book_name": "t", "book_id": "1",
               "content_type": "小说", "publish_type": "AI数字人",
               "alias_status": "生效中", "book_status": "正常",
               "fill_status": "https://v.douyin.com/abc/",
               "has_fill_link": True, "created_at": "", "valid_range": ""}
        e = parse_row(row, 0)
        assert e.fill_status.startswith("<url_")
        assert "douyin.com" not in e.fill_status

    def test_parse_row_missing_fields(self):
        e = parse_row({"alias": "minimal_row"}, 0)
        assert e.content_type == ""
        assert e.internal_status == "unknown"

    def test_parse_row_column_reorder(self):
        row = {"valid_range": "2026-01-01 ~ 2026-06-01",
               "fill_status": "未填写", "alias": "reorder_test",
               "book_name": "reorder_book", "book_id": "9" * 19,
               "content_type": "小说", "publish_type": "AIGC",
               "alias_status": "审核中", "book_status": "正常",
               "has_fill_link": False, "created_at": "2026-01-01"}
        e = parse_row(row, 0)
        assert e.valid_range == "2026-01-01 ~ 2026-06-01"
        assert e.internal_status == "under_review"

    def test_parse_row_legacy_header_names(self):
        row = {"promotion_alias": "legacy_alias", "novel_name": "legacy_book",
               "novel_id": "8" * 19, "content": "小说", "pub_type": "AIGC",
               "task_status": "已失效", "novel_status": "正常",
               "fill_url": "未填写", "has_link": False,
               "apply_time": "2026-01-01", "date_range": ""}
        e = parse_row(row, 0)
        assert e.content_type == "小说"
        assert e.publish_type == "AIGC"
        assert e.alias_status == "已失效"


class TestP0AProbe:
    def test_parse_4_items_partially_verified(self, p0a_fixture):
        report = parse_list_items(p0a_fixture)
        assert report.total_scanned == 4
        assert report.conclusion == "partially_verified"

    def test_three_expired_one_rejected(self, p0a_fixture):
        report = parse_list_items(p0a_fixture)
        expired = [e for e in report.entries if e.alias_status == "已失效"]
        rejected = [e for e in report.entries if e.alias_status == "审核不通过"]
        assert len(expired) == 3
        assert len(rejected) == 1

    def test_no_active_entries(self, p0a_fixture):
        report = parse_list_items(p0a_fixture)
        active = [e for e in report.entries if e.internal_status == "active"]
        assert len(active) == 0

    def test_desensitized_aliases(self, p0a_fixture):
        report = parse_list_items(p0a_fixture)
        for e in report.entries:
            assert e.alias.startswith("<alias_")

    def test_no_real_ids_in_fixture(self, p0a_fixture):
        for item in p0a_fixture:
            bid = item.get("book_id", "")
            assert bid.endswith("1") or bid.endswith("2") or bid.endswith("3") or bid.endswith("4")

    def test_empty_fixture(self):
        report = parse_list_items([])
        assert report.total_scanned == 0
        assert report.conclusion == "partially_verified"

    def test_run_probe_from_raw_data(self, p0a_fixture):
        result = run_probe_from_raw_data(p0a_fixture)
        data = json.loads(result)
        assert data["conclusion"] == "partially_verified"
        assert data["total_scanned"] == 4

    def test_conclusion_never_verified(self):
        items = [{"alias": "t", "book_name": "t", "book_id": "1" * 19,
                  "content_type": "小说", "publish_type": "AI数字人",
                  "alias_status": "生效中", "book_status": "正常",
                  "fill_status": "https://example.com/video",
                  "has_fill_link": True, "created_at": "", "valid_range": ""}]
        report = parse_list_items(items)
        assert report.conclusion == "partially_verified"


# ── State Machine Tests ────────────────────────────────────────────────────

class TestStateMachine:
    def test_valid_transition(self):
        assert can_transition(TaskStatus.APPLYING, TaskStatus.UNDER_REVIEW).allowed

    def test_invalid_transition(self):
        assert not can_transition(TaskStatus.APPLYING, TaskStatus.BOUND).allowed

    def test_noop_same_status(self):
        c = can_transition(TaskStatus.ACTIVE, TaskStatus.ACTIVE)
        assert c.allowed
        assert "no-op" in c.reason

    def test_must_transition_raises(self):
        with pytest.raises(ValueError, match="Invalid transition"):
            must_transition(TaskStatus.APPLYING, TaskStatus.BOUND)

    def test_must_transition_ok(self):
        must_transition(TaskStatus.ACTIVE, TaskStatus.SCRIPTING)

    def test_terminal_statuses(self):
        for s in [TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.EXPIRED,
                  TaskStatus.REJECTED, TaskStatus.STOPPED]:
            assert is_terminal(s)

    def test_non_terminal_statuses(self):
        for s in [TaskStatus.APPLYING, TaskStatus.ACTIVE, TaskStatus.BOUND]:
            assert not is_terminal(s)

    def test_map_old_status(self):
        assert map_old_status("started") == TaskStatus.APPLYING
        assert map_old_status("pending_review") == TaskStatus.UNDER_REVIEW
        assert map_old_status("active") == TaskStatus.ACTIVE
        assert map_old_status("bogus") == TaskStatus.MANUAL_INTERVENTION
        assert map_old_status("") == TaskStatus.MANUAL_INTERVENTION

    def test_is_non_terminal_for_alias(self):
        assert is_non_terminal_for_alias(TaskStatus.APPLYING)
        assert not is_non_terminal_for_alias(TaskStatus.COMPLETED)


# ── Model Tests ────────────────────────────────────────────────────────────

class TestModels:
    def test_fanqie_book_creation(self, db, sample_book):
        assert sample_book.id is not None
        assert sample_book.fanqie_book_id == "7577735918904151065"
        assert len(sample_book.book_uuid) == 32

    def test_fanqie_book_unique(self, db, book_repo):
        from sqlalchemy import exc
        book_repo.upsert_by_fanqie_id("uq_test_1", book_name="First")
        db.flush()
        b2 = FanqieBook(fanqie_book_id="uq_test_1", book_name="Second")
        db.add(b2)
        with pytest.raises(exc.IntegrityError):
            db.flush()

    def test_task_creation(self, db, sample_task):
        assert sample_task.task_uuid is not None
        assert sample_task.status == TaskStatus.ACTIVE
        assert sample_task.version == 1

    def test_operation_event(self, db, task_repo, sample_task):
        ev = task_repo.append_event(
            sample_task.id, EventType.STATUS_CHANGE,
            from_status=TaskStatus.APPLYING, to_status=TaskStatus.ACTIVE)
        assert ev.id is not None
        assert ev.event_uuid is not None

    def test_event_null_task_id(self, db):
        ev = FanqieOperationEvent(
            task_id=None, event_type=EventType.IMPORT,
            payload_json={"issue": "test"})
        db.add(ev)
        db.flush()
        assert ev.id is not None
        assert ev.task_id is None

    def test_publish_record_unique_douyin_video_id(self, db, sample_task):
        from sqlalchemy import exc
        repo = PublishRecordRepository(db)
        repo.create(task_id=sample_task.id, douyin_video_id="uvid_1")
        db.flush()
        r2 = FanqiePublishRecord(task_id=sample_task.id,
                                 douyin_video_id="uvid_1",
                                 publish_uuid="test_uuid_2")
        db.add(r2)
        with pytest.raises(exc.IntegrityError):
            db.flush()

    def test_fanqie_binding_creation(self, db, sample_task):
        repo = PublishRecordRepository(db)
        rec = repo.create(task_id=sample_task.id)
        db.flush()
        b = FanqieBinding(task_id=sample_task.id, publish_id=rec.id,
                          status="binding")
        db.add(b)
        db.flush()
        assert b.id is not None
        assert b.binding_uuid is not None

    def test_chapter_unique_index(self, db, sample_book):
        from sqlalchemy import exc
        db.add(FanqieChapter(book_id=sample_book.id, chapter_index=1,
                             chapter_title="c1"))
        db.flush()
        db.add(FanqieChapter(book_id=sample_book.id, chapter_index=1,
                             chapter_title="dup"))
        with pytest.raises(exc.IntegrityError):
            db.flush()

    def test_bindings_unique_on_publish_id(self, db, sample_task):
        repo = PublishRecordRepository(db)
        rec = repo.create(task_id=sample_task.id)
        db.flush()
        db.add(FanqieBinding(task_id=sample_task.id, publish_id=rec.id,
                             status="binding"))
        db.flush()
        from sqlalchemy import exc
        db.add(FanqieBinding(task_id=sample_task.id, publish_id=rec.id,
                             status="binding", binding_uuid="b2"))
        with pytest.raises(exc.IntegrityError):
            db.flush()


# ── Optimistic Lock Tests ──────────────────────────────────────────────────

class TestOptimisticLock:
    def test_successful(self, db, task_repo, sample_task):
        ok = task_repo.transition_status(
            sample_task, TaskStatus.SCRIPTING,
            expected_version=1, expected_status=TaskStatus.ACTIVE)
        assert ok is True
        assert sample_task.status == TaskStatus.SCRIPTING
        assert sample_task.version == 2

    def test_version_mismatch(self, db, task_repo, sample_task):
        ok = task_repo.transition_status(
            sample_task, TaskStatus.SCRIPTING,
            expected_version=999, expected_status=TaskStatus.ACTIVE)
        assert ok is False

    def test_status_mismatch(self, db, task_repo, sample_task):
        ok = task_repo.transition_status(
            sample_task, TaskStatus.SCRIPTING,
            expected_version=1, expected_status="wrong")
        assert ok is False

    def test_event_created_on_transition(self, db, task_repo, sample_task):
        task_repo.transition_status(
            sample_task, TaskStatus.SCRIPTING,
            expected_version=1, expected_status=TaskStatus.ACTIVE)
        events = task_repo.get_events(sample_task.id)
        assert len(events) >= 1
        assert events[-1].event_type == EventType.STATUS_CHANGE

    def test_wrong_state_raises(self, db, task_repo, sample_task):
        with pytest.raises(ValueError, match="Invalid transition"):
            task_repo.transition_status(sample_task, TaskStatus.BOUND)

    def test_concurrent_conflict(self, db, task_repo, sample_task):
        ok1 = task_repo.transition_status(
            sample_task, TaskStatus.SCRIPTING,
            expected_version=1, expected_status=TaskStatus.ACTIVE)
        assert ok1 is True
        ok2 = task_repo.transition_status(
            sample_task, TaskStatus.SCRIPTING,
            expected_version=1, expected_status=TaskStatus.ACTIVE)
        assert ok2 is False


# ── Transaction Tests ──────────────────────────────────────────────────────

class TestTransactionIsolation:
    def test_event_in_same_txn(self, db, task_repo, sample_task):
        n = len(task_repo.get_events(sample_task.id))
        task_repo.transition_status(
            sample_task, TaskStatus.SCRIPTING,
            expected_version=1, expected_status=TaskStatus.ACTIVE)
        assert len(task_repo.get_events(sample_task.id)) == n + 1

    def test_value_error_preserves_state(self, db, task_repo, sample_task):
        orig = sample_task.status
        with pytest.raises(ValueError):
            task_repo.transition_status(sample_task, TaskStatus.BOUND)
        assert sample_task.status == orig

    def test_rollback_restores_state(self, db, engine):
        session = Session(engine)
        try:
            br = BookRepository(session)
            tr = PromotionTaskRepository(session)
            book = br.upsert_by_fanqie_id("rb_test_1", book_name="t")
            task = tr.create(book_id=book.id, promotion_alias="rb_task",
                             status=TaskStatus.ACTIVE)
            session.commit()

            tr.transition_status(task, TaskStatus.SCRIPTING,
                                 expected_version=1,
                                 expected_status=TaskStatus.ACTIVE)
            session.rollback()

            s2 = Session(engine)
            t2 = s2.query(FanqiePromotionTask).filter_by(id=task.id).first()
            assert t2.status == TaskStatus.ACTIVE
            assert t2.version == 1
            s2.close()
        finally:
            session.rollback()
            session.close()


# ── Book ID Tests ──────────────────────────────────────────────────────────

class TestBookIdNormalization:
    def test_pure_digits(self):
        assert normalize_book_id("7577735918904151065") == "7577735918904151065"

    def test_url_parsing(self):
        assert normalize_book_id(
            "https://fanqienovel.com/page/7577735918904151065"
        ) == "7577735918904151065"

    def test_text_with_id(self):
        assert normalize_book_id("book 7577735918904151065") == "7577735918904151065"

    def test_invalid(self):
        assert normalize_book_id("12345") is None
        assert normalize_book_id("") is None
        assert normalize_book_id("not_a_book_id") is None
        assert normalize_book_id(None) is None
        assert normalize_book_id("   ") is None


class TestParseValidRange:
    def test_standard(self):
        vf, vu = _parse_valid_range("2026-06-29 ~ 2026-12-26")
        assert vf is not None and vu is not None
        assert vf.month == 6 and vu.month == 12

    def test_hyphen_not_split(self):
        vf, vu = _parse_valid_range("2026-06-29 ~ 2026-12-26")
        assert vf.day == 29

    def test_empty(self):
        assert _parse_valid_range("") == (None, None)

    def test_chinese_tilde(self):
        vf, vu = _parse_valid_range("2026-01-01 ～ 2026-12-31")
        assert vf is not None and vu is not None


# ── TaskService Tests ──────────────────────────────────────────────────────

class TestTaskService:
    def test_create(self, db, task_service, sample_book):
        t = task_service.create_task(book_id=sample_book.id,
                                     promotion_alias="新任务",
                                     created_by="test_user")
        assert t.status == TaskStatus.APPLYING

    def test_duplicate_rejected(self, db, task_service, sample_book):
        task_service.create_task(book_id=sample_book.id,
                                 promotion_alias="唯")
        with pytest.raises(ValueError, match="already exists"):
            task_service.create_task(book_id=sample_book.id,
                                     promotion_alias="唯")

    def test_create_no_alias(self, db, task_service, sample_book):
        t = task_service.create_task(book_id=sample_book.id)
        assert t.promotion_alias == ""

    def test_set_status(self, db, task_service, sample_task):
        t = task_service.set_status(sample_task.id, TaskStatus.SCRIPTING)
        assert t.status == TaskStatus.SCRIPTING
        events = task_service.get_events(t.id)
        assert any(e.event_type == EventType.STATUS_CHANGE for e in events)

    def test_not_found(self, db, task_service):
        with pytest.raises(ValueError, match="not found"):
            task_service.set_status(99999, TaskStatus.ACTIVE)

    def test_list_by_status(self, db, task_service, sample_task):
        tasks = task_service.list_tasks(status=TaskStatus.ACTIVE)
        assert all(t.status == TaskStatus.ACTIVE for t in tasks)

    def test_optimistic_lock_conflict(self, db, task_service, sample_task):
        task_service.set_status(sample_task.id, TaskStatus.SCRIPTING,
                                expected_version=1,
                                expected_status=TaskStatus.ACTIVE)
        with pytest.raises(ValueError, match="Optimistic lock conflict"):
            task_service.set_status(sample_task.id, TaskStatus.SCRIPTING,
                                    expected_version=1,
                                    expected_status=TaskStatus.ACTIVE)


# ── Publish Service Tests ──────────────────────────────────────────────────

class TestPublishService:
    def test_no_account(self, db, sample_task):
        svc = NovelPromotionPublishSyncService(db)
        r = svc.sync_by_account_and_video_id(account_key="no",
                                             douyin_video_id="123")
        assert r["success"] is False
        assert r["action"] == "manual_intervention"

    def test_get_by_douyin_video_id(self, db, sample_task):
        repo = PublishRecordRepository(db)
        rec = repo.create(task_id=sample_task.id,
                          douyin_video_id="sv123",
                          status=PublishStatus.PUBLISHED)
        db.flush()
        found = repo.get_by_douyin_video_id("sv123")
        assert found.id == rec.id

    def test_update_sync_info(self, db, sample_task):
        repo = PublishRecordRepository(db)
        rec = repo.create(task_id=sample_task.id,
                          status=PublishStatus.PUBLISH_PENDING_SYNC)
        db.flush()
        ok = repo.update_sync_info(rec.id, "nvid",
                                   "https://www.douyin.com/video/nvid")
        assert ok is True
        db.refresh(rec)
        assert rec.douyin_video_id == "nvid"


# ── Cross-DB Tests ─────────────────────────────────────────────────────────

class TestCrossDB:
    @pytest.fixture
    def temp_douyin_db(self, tmp_path):
        p = tmp_path / "douyin.db"
        c = sqlite3.connect(str(p))
        c.execute("CREATE TABLE videos (id INTEGER PRIMARY KEY, video_id TEXT, "
                  "title TEXT, account_key TEXT DEFAULT '', cover_url TEXT DEFAULT '')")
        c.execute("INSERT INTO videos VALUES (1,'v001','T1','dk1','')")
        c.execute("INSERT INTO videos VALUES (2,'v002','T2','','')")
        c.execute("INSERT INTO videos VALUES (3,'v003','T3','dk2','')")
        c.commit(); c.close()
        return p

    def test_get_by_video_id(self, temp_douyin_db):
        v = DouyinLegacyVideoRepository(str(temp_douyin_db)).get_by_video_id("v001")
        assert v["title"] == "T1"

    def test_get_by_video_id_not_found(self, temp_douyin_db):
        v = DouyinLegacyVideoRepository(str(temp_douyin_db)).get_by_video_id("nope")
        assert v is None

    def test_get_by_account_and_video_id(self, temp_douyin_db):
        v = DouyinLegacyVideoRepository(str(temp_douyin_db)) \
            .get_by_account_and_video_id("dk1", "v001")
        assert v is not None

    def test_account_mismatch(self, temp_douyin_db):
        v = DouyinLegacyVideoRepository(str(temp_douyin_db)) \
            .get_by_account_and_video_id("dk1", "v003")
        assert v is None

    def test_list_videos(self, temp_douyin_db):
        vs = DouyinLegacyVideoRepository(str(temp_douyin_db)).list_videos()
        assert len(vs) == 3

    def test_list_with_account_key(self, temp_douyin_db):
        vs = DouyinLegacyVideoRepository(str(temp_douyin_db)).list_with_account_key()
        assert len(vs) == 2

    def test_nonexistent_db_returns_none(self):
        # get_by_video_id catches FileNotFoundError and returns None
        v = DouyinLegacyVideoRepository("nope.db").get_by_video_id("a")
        assert v is None

    def test_sync_success(self, db, sample_task, temp_douyin_db):
        a = DouyinAccountRepository(db).upsert_by_key("dk1")
        db.flush()
        PublishRecordRepository(db).create(
            task_id=sample_task.id, douyin_account_id=a.id,
            status=PublishStatus.PUBLISH_PENDING_SYNC)
        db.flush()
        svc = NovelPromotionPublishSyncService(db, str(temp_douyin_db))
        r = svc.sync_by_account_and_video_id("dk1", "v001")
        assert r["success"] is True
        assert r["action"] == "synced"

    def test_account_mismatch_sync(self, db, sample_task, temp_douyin_db):
        DouyinAccountRepository(db).upsert_by_key("dk1")
        db.flush()
        svc = NovelPromotionPublishSyncService(db, str(temp_douyin_db))
        r = svc.sync_by_account_and_video_id("dk1", "v003")
        assert r["success"] is False
        assert "Account mismatch" in r["reason"]

    def test_video_no_account_key(self, db, sample_task, temp_douyin_db):
        DouyinAccountRepository(db).upsert_by_key("dk1")
        db.flush()
        svc = NovelPromotionPublishSyncService(db, str(temp_douyin_db))
        r = svc.sync_by_account_and_video_id("dk1", "v002")
        assert r["success"] is False
        assert "no account_key" in r["reason"].lower()

    def test_multiple_candidates(self, db, sample_task, temp_douyin_db):
        a = DouyinAccountRepository(db).upsert_by_key("dk1")
        db.flush()
        repo = PublishRecordRepository(db)
        repo.create(task_id=sample_task.id, douyin_account_id=a.id,
                     status=PublishStatus.PUBLISH_PENDING_SYNC)
        repo.create(task_id=sample_task.id, douyin_account_id=a.id,
                     status=PublishStatus.PUBLISH_PENDING_SYNC)
        db.flush()
        svc = NovelPromotionPublishSyncService(db, str(temp_douyin_db))
        r = svc.sync_by_account_and_video_id("dk1", "v001")
        assert r["success"] is False
        assert "Multiple" in r["reason"]

    def test_video_not_found(self, db, sample_task, tmp_path):
        DouyinAccountRepository(db).upsert_by_key("dk1")
        db.flush()
        p = tmp_path / "e.db"
        c = sqlite3.connect(str(p))
        c.execute("CREATE TABLE videos (id INTEGER PRIMARY KEY, video_id TEXT, "
                  "account_key TEXT DEFAULT '')")
        c.commit(); c.close()
        svc = NovelPromotionPublishSyncService(db, str(p))
        r = svc.sync_by_account_and_video_id("dk1", "n")
        assert r["success"] is False
        assert "not found" in r["reason"].lower()

    def test_schema_error_not_swallowed(self, tmp_path):
        p = tmp_path / "bad.db"
        c = sqlite3.connect(str(p))
        c.execute("CREATE TABLE other (id INTEGER)")
        c.commit(); c.close()
        with pytest.raises(Exception):
            DouyinLegacyVideoRepository(str(p)).get_by_video_id("a")


# ── Import Service Tests ───────────────────────────────────────────────────

class TestImportService:
    def test_book_id_report(self):
        r = BookIdReport()
        assert r.classify("7577735918904151065") == "7577735918904151065"
        assert r.classify("") is None
        assert len(r.valid_numeric) == 1
        assert len(r.empty) == 1

    def test_book_id_report_to_dict(self):
        r = BookIdReport()
        r.classify("7577735918904151065")
        d = r.to_dict()
        assert d["valid_numeric_count"] == 1

    def test_empty_dirs(self, db):
        svc = ImportService(db, data_root="nope")
        report = svc.dry_run()
        assert report.books_created == 0

    def test_integration_idempotent(self, db):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bd = root / "books" / "tb"
            bd.mkdir(parents=True)
            (bd / "meta.json").write_text(json.dumps({
                "book_id": "1111111111111111111",
                "book_name": "IB", "author": "A"}), encoding="utf-8")
            td2 = root / "tasks" / "t1"
            td2.mkdir(parents=True)
            (td2 / "task.json").write_text(json.dumps({
                "task_id": "T1", "book_id": "1111111111111111111",
                "promotion_alias": "ia", "apply_status": "active",
                "valid_range": "2026-01-01 ~ 2026-12-31",
                "created_at": "2026-01-01T00:00:00Z"}), encoding="utf-8")

            svc = ImportService(db, data_root=str(root))
            r1 = svc.import_all()
            assert r1.books_created == 1
            assert r1.tasks_created == 1

            r2 = svc.import_all()
            assert r2.books_created == 0
            assert r2.tasks_created == 0
            assert r2.tasks_skipped == 1

    def test_dry_run_accurate(self, db):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bd = root / "books" / "db"
            bd.mkdir(parents=True)
            (bd / "meta.json").write_text(json.dumps({
                "book_id": "2222222222222222222", "book_name": "D"}), encoding="utf-8")
            td2 = root / "tasks" / "td"
            td2.mkdir(parents=True)
            (td2 / "task.json").write_text(json.dumps({
                "task_id": "TD", "book_id": "2222222222222222222",
                "promotion_alias": "da", "apply_status": "active"}), encoding="utf-8")

            svc = ImportService(db, data_root=str(root))
            r1 = svc.dry_run()
            assert r1.books_created == 1
            svc.import_all()
            r2 = svc.dry_run()
            assert r2.books_created == 0
            assert r2.tasks_skipped == 1

    def test_backfill(self, db):
        from src.scheduler.models import FanqieBatchBook
        bb = FanqieBatchBook(book_name="BF", book_id="3333333333333333333",
                             status="pending")
        db.add(bb); db.flush()
        assert bb.fanqie_book_pk is None

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bd = root / "books" / "bf"
            bd.mkdir(parents=True)
            (bd / "meta.json").write_text(json.dumps({
                "book_id": "3333333333333333333", "book_name": "BF"}), encoding="utf-8")
            ImportService(db, data_root=str(root)).import_all()
            db.refresh(bb)
            assert bb.fanqie_book_pk is not None

    def test_issues_write_events(self, db):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bd = root / "books" / "bad"
            bd.mkdir(parents=True)
            (bd / "meta.json").write_text(json.dumps({
                "book_id": "not_valid", "book_name": "B"}), encoding="utf-8")
            svc = ImportService(db, data_root=str(root))
            r = svc.import_all()
            assert len(r.issues) >= 1
            evts = db.query(FanqieOperationEvent).filter(
                FanqieOperationEvent.task_id.is_(None)).all()
            assert any(e.event_type == EventType.IMPORT for e in evts)


# ── Reconcile Tests ────────────────────────────────────────────────────────

class TestReconcile:
    def test_empty(self, db):
        r = ReconcileService(db, data_root="nope").reconcile()
        assert r.summary == {}

    def test_file_only(self, db):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            td2 = root / "tasks" / "o"
            td2.mkdir(parents=True)
            (td2 / "task.json").write_text(json.dumps({
                "task_id": "O1", "book_id": "4" * 19,
                "promotion_alias": "oa", "apply_status": "active"}), encoding="utf-8")
            r = ReconcileService(db, data_root=str(root)).reconcile()
            fo = [e for e in r.entries if e.type == "file_only"]
            assert len(fo) >= 1
            json.dumps([{"type": e.type, "source": e.source} for e in r.entries])

    def test_db_only(self, db, sample_task):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "tasks").mkdir(parents=True, exist_ok=True)
            r = ReconcileService(db, data_root=str(root)).reconcile()
            do = [e for e in r.entries if e.type == "db_only"]
            assert len(do) >= 1

    def test_status_mismatch(self, db, book_repo):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            b = book_repo.upsert_by_fanqie_id("5" * 19, book_name="SM")
            db.flush()
            PromotionTaskRepository(db).create(
                book_id=b.id, promotion_alias="sma",
                status=TaskStatus.MANUAL_INTERVENTION)
            db.flush()
            td2 = root / "tasks" / "smt"
            td2.mkdir(parents=True)
            (td2 / "task.json").write_text(json.dumps({
                "task_id": "S1", "book_id": "5" * 19,
                "promotion_alias": "sma",
                "apply_status": "active"}), encoding="utf-8")
            r = ReconcileService(db, data_root=str(root)).reconcile()
            sm = [e for e in r.entries if e.type == "status_mismatch"]
            assert len(sm) >= 1

    def test_hash_mismatch(self, db, book_repo):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            b = book_repo.upsert_by_fanqie_id("6" * 19, book_name="HM")
            db.flush()
            tr = PromotionTaskRepository(db)
            td2 = root / "tasks" / "ht"
            td2.mkdir(parents=True)
            (td2 / "task.json").write_text(json.dumps({
                "task_id": "H1", "book_id": "6" * 19,
                "promotion_alias": "hma",
                "apply_status": "under_review"}), encoding="utf-8")
            sd = root / ".snapshots"
            sd.mkdir(parents=True)
            sp = sd / "snap.json"
            sp.write_text(json.dumps({
                "task_id": "H1", "book_id": "6" * 19,
                "promotion_alias": "hma",
                "apply_status": "under_review",
                "extra": "original"}), encoding="utf-8")
            tr.create(book_id=b.id, promotion_alias="hma",
                      status=TaskStatus.UNDER_REVIEW,
                      application_snapshot_path=str(sp))
            db.flush()
            r = ReconcileService(db, data_root=str(root)).reconcile()
            hm = [e for e in r.entries if e.type == "hash_mismatch"]
            assert len(hm) >= 1


# ── Write-Through Tests ────────────────────────────────────────────────────

class TestWriteThrough:
    def test_deprecation_map(self):
        assert "fanqie-book-fetch" in DEPRECATION_MAP
        assert "fanqie-promo-apply" in DEPRECATION_MAP
        assert "fanqie-promo-list" in DEPRECATION_MAP
        assert DEPRECATION_MAP["fanqie-book-fetch"] == "fanqie-task-fetch-material"
        assert DEPRECATION_MAP["fanqie-promo-apply"] == "fanqie-task-apply"
        assert DEPRECATION_MAP["fanqie-promo-list"] == "fanqie-task-sync-status"

    def test_sync_book_fetch(self, db, capsys):
        import src.novel_promotion.write_through as wt
        with patch.object(wt, 'SessionLocal', return_value=db):
            r = sync_book_fetch_result("TB", {
                "book_id": "8888888888888888888",
                "book_name": "TB", "author": "TA"})
            assert r["success"] is True
            assert r["action"] == "synced"
            b = db.query(FanqieBook).filter_by(
                fanqie_book_id="8888888888888888888").first()
            assert b is not None
        assert "DEPRECATED" in capsys.readouterr().out

    def test_sync_book_fetch_no_id(self, db):
        import src.novel_promotion.write_through as wt
        with patch.object(wt, 'SessionLocal', return_value=db):
            r = sync_book_fetch_result("T", {"book_name": "T"})
            assert r["action"] == "partial_failure"
            assert "artifact_path" in r

    def test_apply_success(self, db, book_repo):
        import src.novel_promotion.write_through as wt
        book_repo.upsert_by_fanqie_id("9" * 19, book_name="AT")
        db.flush()
        with patch.object(wt, 'SessionLocal', return_value=db):
            r = sync_promotion_apply_result({
                "book_id": "9" * 19, "book_name": "AT",
                "promotion_alias": "aa", "publish_type": "AI数字人"})
            assert r["success"] is True
        t = db.query(FanqiePromotionTask).filter_by(
            promotion_alias="aa").first()
        assert t is not None

    def test_apply_duplicate(self, db, book_repo, task_repo):
        import src.novel_promotion.write_through as wt
        b = book_repo.upsert_by_fanqie_id("1010101010101010101", book_name="DT")
        task_repo.create(book_id=b.id, promotion_alias="da",
                         status=TaskStatus.APPLYING)
        db.flush()
        with patch.object(wt, 'SessionLocal', return_value=db):
            r = sync_promotion_apply_result({
                "book_id": "1010101010101010101", "book_name": "DT",
                "promotion_alias": "da"})
            assert r["action"] == "skipped"

    def test_list_sync(self, db, engine, book_repo, task_repo):
        import src.novel_promotion.write_through as wt
        b = book_repo.upsert_by_fanqie_id("1212121212121212121", book_name="LT")
        # Start with ACTIVE so ACTIVE -> EXPIRED is a valid transition
        t = task_repo.create(book_id=b.id, promotion_alias="la",
                             status=TaskStatus.ACTIVE)
        db.flush()
        # Note: sync_promotion_list_result opens its own session via
        # SessionLocal(). When mocked, the `with` block calls db.__exit__
        # which closes our test session. We re-query afterwards.
        task_id = t.id  # save before session closes
        with patch.object(wt, 'SessionLocal', return_value=db):
            r = sync_promotion_list_result([{
                "book_id": "1212121212121212121", "book_name": "LT",
                "promotion_alias": "la", "apply_status": "expired"}])
            assert r["success"] is True
        # Re-query from a fresh session since the test session was closed
        s2 = Session(engine)
        try:
            t2 = s2.query(FanqiePromotionTask).filter_by(id=task_id).first()
            assert t2.status == TaskStatus.EXPIRED
        finally:
            s2.close()

    def test_db_error_artifact(self):
        import src.novel_promotion.write_through as wt
        mdb = MagicMock()
        mdb.commit.side_effect = RuntimeError("fail")
        mdb.__enter__ = MagicMock(return_value=mdb)
        mdb.__exit__ = MagicMock(return_value=False)
        with patch.object(wt, 'SessionLocal', return_value=mdb):
            r = sync_book_fetch_result("T", {"book_id": "999"})
            assert r["success"] is False
            assert r["action"] == "partial_failure"
            assert "artifact_path" in r


# ── Douyin Account Repo Tests ──────────────────────────────────────────────

class TestDouyinAccountRepo:
    def test_upsert(self, db):
        a = DouyinAccountRepository(db).upsert_by_key("tk", display_name="T")
        assert a.id is not None

    def test_idempotent(self, db):
        r = DouyinAccountRepository(db)
        a1 = r.upsert_by_key("ik", display_name="F")
        a2 = r.upsert_by_key("ik", display_name="U")
        assert a1.id == a2.id
        assert a2.display_name == "U"

    def test_list_active(self, db):
        r = DouyinAccountRepository(db)
        r.upsert_by_key("a1", status="active")
        r.upsert_by_key("p1", status="paused")
        assert len(r.list_active()) == 1


# ── Migration Tests ────────────────────────────────────────────────────────

@pytest.mark.skipif(not HAS_ALEMBIC, reason="Alembic not installed")
class TestMigration:
    @pytest.fixture
    def alembic_db_path(self, tmp_path):
        p = tmp_path / "a.db"
        yield p

    def test_upgrade_downgrade(self, alembic_db_path):
        ar = Path(__file__).resolve().parent.parent / "alembic"
        cfg = AlembicConfig()
        cfg.config_file_name = None  # skip fileConfig, no alembic.ini on disk
        cfg.set_main_option("script_location", str(ar))
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{alembic_db_path}")

        # env.py overrides url with settings.DATABASE_URL, so we point it
        # at our temp DB.
        db_url = f"sqlite:///{alembic_db_path}"
        with patch("src.shared.config.settings.DATABASE_URL", db_url):
            alembic_command.upgrade(cfg, "head")

        c = sqlite3.connect(str(alembic_db_path))
        tbls = [r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
        assert "fanqie_books" in tbls
        assert "fanqie_bindings" in tbls
        assert "fanqie_operation_events" in tbls
        idxs = [r[1] for r in c.execute("PRAGMA index_list('fanqie_books')").fetchall()]
        assert any("fanqie_book_id" in (i or "").lower() for i in idxs)
        idxs_pr = [r[1] for r in c.execute("PRAGMA index_list('fanqie_publish_records')").fetchall()]
        assert any("douyin_video_id" in (i or "").lower() for i in idxs_pr)
        c.close()

        with patch("src.shared.config.settings.DATABASE_URL", db_url):
            alembic_command.downgrade(cfg, "5cb67ecb2df3")
        c2 = sqlite3.connect(str(alembic_db_path))
        tbls2 = [r[0] for r in c2.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
        assert "fanqie_books" not in tbls2
        assert "fanqie_bindings" not in tbls2
        c2.close()

        with patch("src.shared.config.settings.DATABASE_URL", db_url):
            alembic_command.upgrade(cfg, "head")

    def test_head_detection(self, alembic_db_path):
        ar = Path(__file__).resolve().parent.parent / "alembic"
        cfg = AlembicConfig()
        cfg.config_file_name = None  # skip fileConfig, no alembic.ini on disk
        cfg.set_main_option("script_location", str(ar))
        cfg.set_main_option("sqlalchemy.url", f"sqlite:///{alembic_db_path}")

        db_url = f"sqlite:///{alembic_db_path}"
        with patch("src.shared.config.settings.DATABASE_URL", db_url):
            alembic_command.upgrade(cfg, "head")

        te = create_engine(f"sqlite:///{alembic_db_path}")
        import src.shared.migration as mig_module
        with patch.object(mig_module, 'engine', te):
            assert mig_module._alembic_version_table_exists()
            assert mig_module._is_migration_up_to_date()


# ── Douyin Migration Tests ─────────────────────────────────────────────────

class TestDouyinMigration:
    @pytest.fixture
    def temp_db(self, tmp_path):
        p = tmp_path / "dm.db"
        c = sqlite3.connect(str(p))
        c.execute("CREATE TABLE videos (id INTEGER PRIMARY KEY, video_id TEXT, title TEXT)")
        c.execute("INSERT INTO videos (video_id, title) VALUES ('v1','T1')")
        c.execute("INSERT INTO videos (video_id, title) VALUES ('v2','T2')")
        c.commit(); c.close()
        return p

    def test_check_no_column(self, temp_db):
        from src.novel_promotion.douyin_migration import check_account_key
        r = check_account_key(temp_db)
        assert r["exists"] is True
        assert r["has_column"] is False

    def test_upgrade(self, temp_db):
        from src.novel_promotion.douyin_migration import upgrade_account_key, check_account_key
        r = upgrade_account_key(temp_db)
        assert r["success"] is True
        assert r["action"] == "upgraded"
        assert check_account_key(temp_db)["has_column"] is True

    def test_upgrade_idempotent(self, temp_db):
        from src.novel_promotion.douyin_migration import upgrade_account_key
        r1 = upgrade_account_key(temp_db)
        r2 = upgrade_account_key(temp_db)
        assert r1["action"] == "upgraded"
        assert r2["action"] == "skip"

    def test_downgrade_needs_confirm(self, temp_db):
        from src.novel_promotion.douyin_migration import (
            upgrade_account_key, downgrade_account_key)
        upgrade_account_key(temp_db)
        r = downgrade_account_key(temp_db, confirm=False)
        assert r["success"] is False
        assert r["action"] == "needs_confirm"

    def test_downgrade_removes(self, temp_db):
        from src.novel_promotion.douyin_migration import (
            upgrade_account_key, downgrade_account_key, check_account_key)
        upgrade_account_key(temp_db)
        r = downgrade_account_key(temp_db, confirm=True)
        assert r["success"] is True
        assert not check_account_key(temp_db)["has_column"]

    def test_update_requires_upgrade(self, temp_db):
        from src.novel_promotion.douyin_migration import update_account_key
        r = update_account_key(temp_db, "v1", "dk")
        assert r["success"] is False
        assert "upgrade" in r["error"].lower()

    def test_update_after_upgrade(self, temp_db):
        from src.novel_promotion.douyin_migration import (
            upgrade_account_key, update_account_key)
        upgrade_account_key(temp_db)
        r = update_account_key(temp_db, "v1", "dk")
        assert r["success"] is True
        assert r["rows_updated"] == 1

    def test_no_videos_table(self, tmp_path):
        from src.novel_promotion.douyin_migration import check_account_key
        p = tmp_path / "nv.db"
        c = sqlite3.connect(str(p))
        c.execute("CREATE TABLE other (id INTEGER)")
        c.commit(); c.close()
        assert "error" in check_account_key(p)


# ── CLI Tests ──────────────────────────────────────────────────────────────

class TestCLIQueries:
    def test_task_list_empty(self, db):
        tasks = TaskService(db).list_tasks()
        assert isinstance(tasks, list)

    def test_cli_parser_registration(self):
        import argparse
        p = argparse.ArgumentParser()
        sp = p.add_subparsers(dest="command")
        from src.novel_promotion.cli import add_fanqie_closed_loop_parsers
        add_fanqie_closed_loop_parsers(sp)
        choices = list(sp.choices.keys())
        for cmd in ["fanqie-task-list", "fanqie-task-show", "fanqie-task-events",
                    "fanqie-task-reconcile", "fanqie-task-import",
                    "fanqie-task-sync-douyin", "fanqie-task-p0a-probe",
                    "fanqie-douyin-migrate"]:
            assert cmd in choices, f"Missing: {cmd}"

    def test_auto_generate_title_exists(self):
        mp = Path(__file__).resolve().parent.parent / "main.py"
        content = mp.read_text(encoding="utf-8")
        assert "def _auto_generate_title" in content
        assert "智慧语录" in content

    def test_old_commands_parse(self):
        import argparse
        p = argparse.ArgumentParser()
        sp = p.add_subparsers(dest="command")
        sp.add_parser("fanqie-promo-apply")
        sp.add_parser("fanqie-book-fetch")
        sp.add_parser("fanqie-promo-list")
        for cmd in ["fanqie-promo-apply", "fanqie-book-fetch", "fanqie-promo-list"]:
            assert p.parse_args([cmd]).command == cmd


# ── Cleanup ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _cleanup():
    yield
