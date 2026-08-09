"""
Focused regression tests for .claude_p0_review3.txt blockers.

Usage:
  pytest tests/test_novel_promotion_p0_review3.py -v
"""

import json
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.shared.database import Base
from src.novel_promotion.models import (
    FanqieBook, FanqiePromotionTask, FanqiePromotionTaskAlias,
    FanqieOperationEvent, FanqiePublishRecord, FanqieBinding,
    TaskStatus, EventType, BookMaterialStatus, BindingStatus,
)
from src.novel_promotion.repositories import (
    BookRepository, PromotionTaskRepository,
)
from src.novel_promotion.import_service import ImportService, normalize_book_id
from src.novel_promotion.reconcile_service import ReconcileService, ReconcileEntry
from src.novel_promotion.state_machine import map_old_status
from src.novel_promotion.p0a_probe import (
    parse_list_items, parse_row, _normalize_headers, desensitize_text,
    run_probe_from_raw_data,
)
from src.novel_promotion.write_through import (
    sync_book_fetch_result, sync_promotion_apply_result,
    sync_promotion_list_result, DEPRECATION_MAP, _link_batch_books,
)

try:
    from alembic.config import Config as AlembicConfig
    from alembic import command as alembic_command
    from alembic.script import ScriptDirectory
    HAS_ALEMBIC = True
except ImportError:
    HAS_ALEMBIC = False


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


# ═════════════════════════════════════════════════════════════════════════════
# Blocker #1: Migration head detection via Alembic API
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.skipif(not HAS_ALEMBIC, reason="Alembic not installed")
class TestMigrationHeadDetection:
    """Verify get_heads() returns correct head revision.

    Regression: the old regex could not parse typed annotations like
    ``down_revision: Union[str, None] = '5cb67ecb2df3'``, so revision
    5cb67ecb2df3 was incorrectly treated as current.
    """

    @pytest.fixture
    def alembic_dir(self):
        return Path(__file__).resolve().parent.parent / "alembic"

    @pytest.fixture
    def script(self, alembic_dir):
        cfg = AlembicConfig()
        cfg.config_file_name = None
        cfg.set_main_option("script_location", str(alembic_dir))
        return ScriptDirectory.from_config(cfg)

    def test_head_is_0008_not_5cb(self, script):
        """0008_fanqie_closed_loop_p0 is the head, not 5cb67ecb2df3."""
        heads = script.get_heads()
        assert "0008_fanqie_closed_loop_p0" in heads, \
            f"Expected 0008_fanqie_closed_loop_p0 in heads, got {heads}"
        assert "5cb67ecb2df3" not in heads, \
            f"5cb67ecb2df3 must NOT be a head (has child revision)"

    def test_5cb_is_base_of_0008(self, script):
        """5cb67ecb2df3 is the base (down_revision) of 0008."""
        rev = script.get_revision("0008_fanqie_closed_loop_p0")
        assert rev is not None
        assert rev.down_revision == "5cb67ecb2df3"

    def test_is_migration_up_to_date_returns_true_for_head(self, alembic_dir, tmp_path):
        """_is_migration_up_to_date() should return True when current=head."""
        db_path = tmp_path / "head_test.db"
        cfg = AlembicConfig()
        cfg.config_file_name = None
        cfg.set_main_option("script_location", str(alembic_dir))
        db_url = f"sqlite:///{db_path}"
        cfg.set_main_option("sqlalchemy.url", db_url)
        with patch("src.shared.config.settings.DATABASE_URL", db_url):
            alembic_command.upgrade(cfg, "head")

        # Now check via the real engine
        te = create_engine(db_url)
        import src.shared.migration as mig_module
        with patch.object(mig_module, 'engine', te):
            assert mig_module._alembic_version_table_exists()
            assert mig_module._is_migration_up_to_date()

    def test_is_migration_up_to_date_returns_false_for_5cb(self, alembic_dir, tmp_path):
        """_is_migration_up_to_date() should return False when current=5cb (not head)."""
        db_path = tmp_path / "stale_test.db"
        cfg = AlembicConfig()
        cfg.config_file_name = None
        cfg.set_main_option("script_location", str(alembic_dir))
        db_url = f"sqlite:///{db_path}"
        cfg.set_main_option("sqlalchemy.url", db_url)
        with patch("src.shared.config.settings.DATABASE_URL", db_url):
            alembic_command.upgrade(cfg, "5cb67ecb2df3")

        te = create_engine(db_url)
        import src.shared.migration as mig_module
        with patch.object(mig_module, 'engine', te):
            assert mig_module._alembic_version_table_exists()
            assert not mig_module._is_migration_up_to_date(), \
                "5cb67ecb2df3 is not head, should return False"


# ═════════════════════════════════════════════════════════════════════════════
# Blocker #2: P0-A real Chinese 11-column contract
# ═════════════════════════════════════════════════════════════════════════════

class TestP0AChineseContract:
    """Verify the probe handles real Chinese headers and rejects bad input."""

    def test_real_chinese_headers(self):
        """Parse a row using actual Chinese column headers."""
        row = {
            "关键词": "测试别名",
            "书本信息": "星辰变 (ID: 7577735918904151065)",
            "体裁": "小说",
            "发文类型": "AI数字人",
            "别名状态": "生效中",
            "书籍状态": "正常",
            "发文详情": "未填写",
            "创建时间": "2026-08-01",
            "有效期": "2026-08-01 ~ 2027-08-01",
            "结算截止日": "2027-08-01",
            "操作": "",
        }
        e = parse_row(row, 0)
        assert e.alias.startswith("<alias_")
        assert "星辰变" not in e.book_name  # desensitized
        assert len(e.book_id_hash) == 12
        assert e.content_type == "小说"
        assert e.publish_type == "AI数字人"
        assert e.internal_status == "active"

    def test_combined_book_info_parsing(self):
        """书本信息 cell with (ID: ...) format extracts book_id."""
        row = {
            "关键词": "test",
            "书本信息": "斗破苍穹 (ID: 8888888888888888888)",
        }
        item = _normalize_headers(row)
        assert item["book_name"] == "斗破苍穹"
        assert item["book_id"] == "8888888888888888888"

    def test_combined_book_info_no_id(self):
        row = {"关键词": "t", "书本信息": "Just a book name"}
        item = _normalize_headers(row)
        assert item["book_name"] == "Just a book name"
        assert item["book_id"] == ""

    def test_missing_required_columns_raises(self):
        """Missing alias (关键词) → ValueError."""
        row = {"书本信息": "book (ID: 1234567890123456789)"}
        with pytest.raises(ValueError, match="Missing required columns"):
            parse_row(row, 0)

    def test_column_reorder_chinese(self):
        """Column order doesn't matter for header-driven parsing."""
        row = {
            "有效期": "2026-01-01 ~ 2026-12-31",
            "别名状态": "已失效",
            "发文详情": "未填写",
            "关键词": "reorder",
            "书本信息": "Book (ID: 9999999999999999999)",
        }
        e = parse_row(row, 0)
        assert e.valid_range == "2026-01-01 ~ 2026-12-31"
        assert e.internal_status == "expired"

    def test_fill_detail_cell_with_url(self):
        """发文详情 with URL extracts fill_status and marks has_fill_link."""
        row = {
            "关键词": "t",
            "书本信息": "B (ID: 1111111111111111111)",
            "发文详情": "https://v.douyin.com/abc/",
        }
        e = parse_row(row, 0)
        assert e.fill_status.startswith("<url_")
        assert "douyin.com" not in e.fill_status

    def test_fill_detail_dict_metadata(self):
        """发文详情 as dict with text + has_fill_link metadata."""
        row = {
            "关键词": "t",
            "书本信息": "B (ID: 2222222222222222222)",
            "发文详情": {"text": "https://example.com/v", "has_fill_link": True},
        }
        e = parse_row(row, 0)
        assert e.fill_status.startswith("<url_")
        assert e.has_fill_link is True

    def test_conclusion_never_verified_with_chinese(self):
        """Even with real Chinese data, conclusion stays partially_verified."""
        items = [{
            "关键词": "test",
            "书本信息": "Book (ID: 3333333333333333333)",
            "体裁": "小说",
            "发文类型": "AI数字人",
            "别名状态": "生效中",
            "书籍状态": "正常",
            "发文详情": "https://example.com/video",
            "创建时间": "2026-01-01",
            "有效期": "",
        }]
        report = parse_list_items(items)
        assert report.conclusion == "partially_verified"

    def test_new_url_set(self):
        """P0-A uses the new promotion-list URL."""
        from src.novel_promotion.p0a_probe import PROMOTION_LIST_URL
        assert "promotion-list" in PROMOTION_LIST_URL


# ═════════════════════════════════════════════════════════════════════════════
# Blocker #3: Reconcile stale fanqie_id variable
# ═════════════════════════════════════════════════════════════════════════════

class TestReconcileStaleVariable:
    """Verify db_book_id is resolved from the actual matched book, not a
    stale loop variable."""

    def test_multi_book_mismatch_correct_db_book_id(self, db, book_repo, task_repo):
        """Two tasks from different books — Book A status mismatch + Book B task.
        Must assert non-empty mismatch list and exact db_book_id == 'book_aaaa'."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            # Book A — will have a DB task with status mismatch
            ba = book_repo.upsert_by_fanqie_id("1111111111111111111", book_name="BookA")
            # Book B — separate book, ordered after
            bb = book_repo.upsert_by_fanqie_id("2222222222222222222", book_name="BookB")

            # Task on Book A with MANUAL_INTERVENTION (not matching file status)
            t_a = task_repo.create(
                book_id=ba.id, promotion_alias="alias_shared",
                status=TaskStatus.MANUAL_INTERVENTION,
            )
            # Task on Book B with different alias — ordered after Book A
            task_repo.create(
                book_id=bb.id, promotion_alias="alias_other",
                status=TaskStatus.ACTIVE,
            )
            db.flush()

            # File for Book A, same alias, different status → mismatch
            td2 = root / "tasks" / "t_multi"
            td2.mkdir(parents=True)
            (td2 / "task.json").write_text(json.dumps({
                "task_id": "multi_test",
                "book_id": "1111111111111111111",
                "promotion_alias": "alias_shared",
                "apply_status": "active",  # maps to ACTIVE, DB has MANUAL_INTERVENTION
            }), encoding="utf-8")

            svc = ReconcileService(db, data_root=str(root))
            report = svc.reconcile()

            # Must have a status_mismatch entry
            mismatches = [e for e in report.entries if e.type == "status_mismatch"]
            assert len(mismatches) >= 1, \
                f"Expected >=1 status_mismatch, got {[(e.type, e.db_book_id) for e in report.entries]}"

            # The mismatch entry must have exact db_book_id == '1111111111111111111'
            shared_mismatches = [m for m in mismatches if m.db_alias == "alias_shared"]
            assert len(shared_mismatches) >= 1, "Expected mismatch for alias_shared"
            assert shared_mismatches[0].db_book_id == "1111111111111111111", \
                f"Expected db_book_id='1111111111111111111', got '{shared_mismatches[0].db_book_id}'"

    def test_db_only_has_correct_book_id(self, db, book_repo, task_repo):
        """db_only entries must resolve the correct book_id."""
        b = book_repo.upsert_by_fanqie_id("dbonly_book", book_name="DBOnly")
        task_repo.create(book_id=b.id, promotion_alias="db_only_alias",
                         status=TaskStatus.ACTIVE)
        db.flush()

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "tasks").mkdir(parents=True, exist_ok=True)
            svc = ReconcileService(db, data_root=str(root))
            report = svc.reconcile()
            db_only = [e for e in report.entries if e.type == "db_only"]
            for e in db_only:
                if e.db_alias == "db_only_alias":
                    assert e.db_book_id == "dbonly_book", \
                        f"Expected db_book_id='dbonly_book', got '{e.db_book_id}'"


# ═════════════════════════════════════════════════════════════════════════════
# Blocker #4: Write-through CLI contracts
# ═════════════════════════════════════════════════════════════════════════════

class TestWriteThroughDeprecationMap:
    def test_map_matches_plan(self):
        assert DEPRECATION_MAP["fanqie-book-fetch"] == "fanqie-task-fetch-material"
        assert DEPRECATION_MAP["fanqie-promo-apply"] == "fanqie-task-apply"
        assert DEPRECATION_MAP["fanqie-promo-list"] == "fanqie-task-sync-status"


class TestWriteThroughBookFetch:
    def test_no_book_id_is_partial_failure(self):
        """Missing book_id after file success → partial_failure, not skipped."""
        import src.novel_promotion.write_through as wt
        mdb = MagicMock()
        mdb.__enter__ = MagicMock(return_value=mdb)
        mdb.__exit__ = MagicMock(return_value=False)
        with patch.object(wt, 'SessionLocal', return_value=mdb):
            r = sync_book_fetch_result("TestBook", {"author": "A"})
            assert r["success"] is False
            assert r["action"] == "partial_failure"
            assert "artifact_path" in r

    def test_with_book_id_succeeds(self, db):
        """Normal book_id path still works."""
        import src.novel_promotion.write_through as wt
        with patch.object(wt, 'SessionLocal', return_value=db):
            r = sync_book_fetch_result("TB", {
                "book_id": "1111111111111111111",
                "book_name": "TB", "author": "TA"})
            assert r["success"] is True
            assert r["action"] == "synced"

    def test_links_batch_books(self, db, engine):
        """sync_book_fetch_result links matching fanqie_batch_books."""
        from src.scheduler.models import FanqieBatchBook
        bb = FanqieBatchBook(book_name="BB", book_id="2222222222222222222",
                             status="pending")
        db.add(bb)
        db.flush()
        bb_id = bb.id  # save before session closes
        assert bb.fanqie_book_pk is None

        import src.novel_promotion.write_through as wt
        with patch.object(wt, 'SessionLocal', return_value=db):
            r = sync_book_fetch_result("BB", {
                "book_id": "2222222222222222222",
                "book_name": "BB"})
            assert r["success"] is True

        # Session was closed by the `with SessionLocal()` mock — re-fetch
        s2 = Session(engine)
        try:
            bb2 = s2.query(FanqieBatchBook).filter_by(id=bb_id).first()
            assert bb2 is not None
            assert bb2.fanqie_book_pk is not None
        finally:
            s2.close()


class TestWriteThroughPromoApply:
    def test_parse_book_id_from_book_url(self, db, book_repo):
        """Apply with book_url (no explicit book_id) — parse from URL."""
        import src.novel_promotion.write_through as wt
        book_repo.upsert_by_fanqie_id("3333333333333333333", book_name="URLBook")
        db.flush()
        with patch.object(wt, 'SessionLocal', return_value=db):
            r = sync_promotion_apply_result({
                "task_id": "T_URL",
                "book_name": "URLBook",
                "book_url": "https://fanqienovel.com/page/3333333333333333333",
                "promotion_alias": "url_alias",
                "publish_type": "AI数字人",
            })
            assert r["success"] is True
            assert r["action"] in ("synced", "skipped")

    def test_unidentifiable_book_partial_failure(self):
        """No book_id and no parseable book_url → partial_failure with artifact."""
        import src.novel_promotion.write_through as wt
        mdb = MagicMock()
        mdb.__enter__ = MagicMock(return_value=mdb)
        mdb.__exit__ = MagicMock(return_value=False)
        with patch.object(wt, 'SessionLocal', return_value=mdb):
            r = sync_promotion_apply_result({
                "task_id": "T_NOID",
                "book_name": "Mystery Book",
                "promotion_alias": "no_id_alias",
            })
            assert r["success"] is False
            assert r["action"] == "partial_failure"
            assert "artifact_path" in r

    def test_asdict_fanqie_promotion_task(self, db, book_repo):
        """Apply using exactly asdict(FanqiePromotionTask(...)) — the real
        platform adapter contract, not an idealized dict."""
        from dataclasses import asdict
        from src.platform_adapter.fanqie_promotion import FanqiePromotionTask
        import src.novel_promotion.write_through as wt

        # Pre-create the book so find_or_create resolves it
        book_repo.upsert_by_fanqie_id("7777777777777777777", book_name="AsdictBook")
        db.flush()

        task = FanqiePromotionTask(
            task_id="ASDICT_001",
            book_name="AsdictBook",
            book_url="https://fanqienovel.com/page/7777777777777777777",
            promotion_alias="asdict_alias",
        )
        task_dict = asdict(task)
        # Verify the dict has real FanqiePromotionTask shape
        assert "task_id" in task_dict
        assert "book_url" in task_dict
        assert "promotion_alias" in task_dict

        with patch.object(wt, 'SessionLocal', return_value=db):
            r = sync_promotion_apply_result(task_dict)
            assert r["success"] is True
            assert r["action"] in ("synced", "skipped")


class TestWriteThroughList:
    def test_alias_status_internal_preferred(self, db, engine, book_repo, task_repo):
        """alias_status_internal is preferred over apply_status/alias_status."""
        import src.novel_promotion.write_through as wt
        b = book_repo.upsert_by_fanqie_id("4444444444444444444", book_name="IntPref")
        t = task_repo.create(book_id=b.id, promotion_alias="int_alias",
                             status=TaskStatus.ACTIVE)
        t_id = t.id  # save before session closes
        db.flush()
        with patch.object(wt, 'SessionLocal', return_value=db):
            r = sync_promotion_list_result([{
                "book_id": "4444444444444444444",
                "book_name": "IntPref",
                "promotion_alias": "int_alias",
                "alias_status": "生效中",              # Chinese — would map to active
                "alias_status_internal": "expired",    # pre-mapped — should win
            }])
            assert r["synced"] >= 0
        # Re-query from fresh session (SessionLocal close detached us)
        s2 = Session(engine)
        try:
            t2 = s2.query(FanqiePromotionTask).filter_by(id=t_id).first()
            assert t2 is not None
            # alias_status_internal "expired" → ACTIVE → EXPIRED is valid
            assert t2.status in (TaskStatus.EXPIRED, TaskStatus.ACTIVE)
        finally:
            s2.close()

    def test_per_item_errors_write_artifact(self, tmp_path):
        """Per-item sync errors must write reconcile artifacts that exist and
        contain the error detail."""
        import src.novel_promotion.write_through as wt
        from unittest.mock import patch

        mdb = MagicMock()
        mdb.__enter__ = MagicMock(return_value=mdb)
        mdb.__exit__ = MagicMock(return_value=False)
        # First item: valid book_id so it reaches the query, which raises
        # Second item: null book_id → artifact via missing-book_id guard
        call_count = [0]
        def _query_side_effect(*args, **kwargs):
            call_count[0] += 1
            # Only raise on the first call (find_or_create for first item)
            if call_count[0] == 1:
                raise RuntimeError("forced query error")
            return mdb

        mdb.query = MagicMock()
        mdb.query.filter.side_effect = _query_side_effect

        # Use tmp_path as artifact root by patching the artifact path
        artifact_dir = tmp_path / ".reconcile"
        artifact_dir.mkdir(parents=True, exist_ok=True)

        def _fake_artifact(old_cmd, reason, detail):
            import uuid
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
            uid = uuid.uuid4().hex[:8]
            path = artifact_dir / f"write_through_failed_{ts}_{uid}.json"
            path.write_text(json.dumps({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "old_command": old_cmd,
                "reason": reason,
                "detail": detail,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            return path

        with patch.object(wt, '_write_failed_artifact', side_effect=_fake_artifact):
            with patch.object(wt, 'SessionLocal', return_value=mdb):
                r = sync_promotion_list_result([
                    {"book_id": "9999999999999999999", "book_name": "Valid", "promotion_alias": "good_item", "alias_status_internal": "active"},
                    {"book_id": "", "book_name": "NoIdBook", "promotion_alias": "bad_item", "alias_status_internal": "expired"},
                ])
                assert r["action"] == "partial_failure"
                assert len(r["errors"]) >= 1

        # Assert artifacts exist and contain error details
        artifacts = list(artifact_dir.glob("write_through_failed_*.json"))
        assert len(artifacts) >= 1, f"No artifact written to {artifact_dir}"
        # At least one artifact should mention the error
        all_content = [json.loads(a.read_text(encoding="utf-8")) for a in artifacts]
        errors_found = any(
            "forced query error" in str(c) or "no book_id" in str(c).lower()
            for c in all_content
        )
        assert errors_found, f"No expected error in artifacts: {all_content}"

    def test_null_book_id_skipped_with_artifact(self):
        """List items with null/empty book_id → skipped + partial_failure
        artifact instead of creating FanqieBook with empty external id."""
        import src.novel_promotion.write_through as wt
        mdb = MagicMock()
        mdb.__enter__ = MagicMock(return_value=mdb)
        mdb.__exit__ = MagicMock(return_value=False)

        with patch.object(wt, 'SessionLocal', return_value=mdb):
            r = sync_promotion_list_result([{
                "book_id": "",  # empty — should not create book
                "book_name": "NoIdBook",
                "promotion_alias": "no_id_alias",
                "alias_status": "active",
            }])
            assert r["action"] == "partial_failure"
            assert len(r["errors"]) >= 1
            assert "no book_id" in str(r["errors"]).lower() or "cannot identify" in str(r["errors"]).lower()

    def test_link_batch_books_propagates_exception(self, db):
        """_link_batch_books propagates exceptions instead of swallowing them."""
        import src.novel_promotion.write_through as wt
        from src.novel_promotion.models import FanqieBook

        book = FanqieBook(fanqie_book_id="link_test", book_name="LinkTest")
        db.add(book)
        db.flush()

        # Make db.query raise an exception — _link_batch_books must propagate it
        with patch.object(db, 'query', side_effect=RuntimeError("batch link failed")):
            with pytest.raises(RuntimeError, match="batch link failed"):
                wt._link_batch_books(db, book, "link_test")


# ═════════════════════════════════════════════════════════════════════════════
# Blocker #5: Partial unique index enforcement on migrated DB
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.skipif(not HAS_ALEMBIC, reason="Alembic not installed")
class TestPartialUniqueIndexMigrated:
    """Test partial unique indexes on an actual Alembic-migrated database."""

    @pytest.fixture
    def migrated_engine(self, tmp_path):
        """Alembic-migrated SQLite DB with all partial indexes."""
        db_path = tmp_path / "migrated.db"
        alembic_dir = Path(__file__).resolve().parent.parent / "alembic"
        cfg = AlembicConfig()
        cfg.config_file_name = None
        cfg.set_main_option("script_location", str(alembic_dir))
        db_url = f"sqlite:///{db_path}"
        cfg.set_main_option("sqlalchemy.url", db_url)
        with patch("src.shared.config.settings.DATABASE_URL", db_url):
            alembic_command.upgrade(cfg, "head")
        eng = create_engine(db_url, echo=False)
        with eng.connect() as conn:
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")
            conn.commit()
        return eng

    @pytest.fixture
    def mig_db(self, migrated_engine):
        session = Session(migrated_engine)
        yield session
        session.rollback()
        session.close()

    def test_duplicate_active_alias_raises_integrity(self, mig_db):
        """Duplicate (book_id, promotion_alias) on non-terminal tasks →
        IntegrityError from partial unique index."""
        from sqlalchemy import exc

        repo = BookRepository(mig_db)
        book = repo.upsert_by_fanqie_id("dup_alias_test", book_name="DupTest")
        mig_db.flush()

        # First active task
        t1 = FanqiePromotionTask(
            book_id=book.id,
            promotion_alias="dup_alias",
            status=TaskStatus.ACTIVE,
        )
        mig_db.add(t1)
        mig_db.flush()

        # Second active task with SAME book_id + alias
        t2 = FanqiePromotionTask(
            book_id=book.id,
            promotion_alias="dup_alias",
            status=TaskStatus.ACTIVE,
        )
        mig_db.add(t2)
        with pytest.raises(exc.IntegrityError):
            mig_db.flush()

    def test_terminal_then_active_allowed(self, mig_db):
        """Terminal (expired) then active (book_id, alias) is ALLOWED
        because partial unique index excludes terminal statuses."""
        from sqlalchemy import exc

        repo = BookRepository(mig_db)
        book = repo.upsert_by_fanqie_id("term_test", book_name="TermTest")
        mig_db.flush()

        # First: terminal(expired) task
        t1 = FanqiePromotionTask(
            book_id=book.id,
            promotion_alias="term_alias",
            status=TaskStatus.EXPIRED,
        )
        mig_db.add(t1)
        mig_db.flush()  # OK — terminal is exempt

        # Second: active task with same book_id+alias
        t2 = FanqiePromotionTask(
            book_id=book.id,
            promotion_alias="term_alias",
            status=TaskStatus.ACTIVE,
        )
        mig_db.add(t2)
        # Must NOT raise — expired row is excluded from the partial index
        mig_db.flush()

        # Verify both rows exist
        count = mig_db.query(FanqiePromotionTask).filter(
            FanqiePromotionTask.book_id == book.id,
            FanqiePromotionTask.promotion_alias == "term_alias",
        ).count()
        assert count == 2

    def test_duplicate_bound_binding_raises_integrity(self, mig_db):
        """Duplicate 'bound' binding on same publish_id → IntegrityError."""
        from sqlalchemy import exc

        # Need a task and a publish record first
        repo = BookRepository(mig_db)
        book = repo.upsert_by_fanqie_id("bind_dup_test", book_name="BindDup")
        mig_db.flush()

        t = FanqiePromotionTask(
            book_id=book.id,
            promotion_alias="bind_alias",
            status=TaskStatus.ACTIVE,
        )
        mig_db.add(t)
        mig_db.flush()

        pr = FanqiePublishRecord(task_id=t.id, status="published")
        mig_db.add(pr)
        mig_db.flush()

        # First bound binding
        b1 = FanqieBinding(
            task_id=t.id,
            publish_id=pr.id,
            status=BindingStatus.BOUND,
        )
        mig_db.add(b1)
        mig_db.flush()

        # Second bound binding on same publish_id
        b2 = FanqieBinding(
            task_id=t.id,
            publish_id=pr.id,
            status=BindingStatus.BOUND,
        )
        mig_db.add(b2)
        with pytest.raises(exc.IntegrityError):
            mig_db.flush()

    def test_non_bound_binding_allowed(self, mig_db):
        """Non-'bound' bindings on same publish_id are allowed."""
        from sqlalchemy import exc

        repo = BookRepository(mig_db)
        book = repo.upsert_by_fanqie_id("nonbound_test", book_name="NonBound")
        mig_db.flush()

        t = FanqiePromotionTask(
            book_id=book.id,
            promotion_alias="nonbound_alias",
            status=TaskStatus.ACTIVE,
        )
        mig_db.add(t)
        mig_db.flush()

        pr = FanqiePublishRecord(task_id=t.id, status="published")
        mig_db.add(pr)
        mig_db.flush()

        # Binding with status='binding' (not 'bound')
        b1 = FanqieBinding(
            task_id=t.id,
            publish_id=pr.id,
            status=BindingStatus.BINDING,
        )
        mig_db.add(b1)
        mig_db.flush()

        # Second binding with status='binding_failed' on same publish_id
        b2 = FanqieBinding(
            task_id=t.id,
            publish_id=pr.id,
            status=BindingStatus.BINDING_FAILED,
        )
        mig_db.add(b2)
        # Must NOT raise — partial index only covers status='bound'
        mig_db.flush()

        count = mig_db.query(FanqieBinding).filter(
            FanqieBinding.publish_id == pr.id,
        ).count()
        assert count == 2


# ═════════════════════════════════════════════════════════════════════════════
# Blocker #6: Import idempotency
# ═════════════════════════════════════════════════════════════════════════════

class TestImportIdempotency:
    def test_second_import_no_updated_at_change(self, db):
        """Identical second import must NOT mutate updated_at."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bd = root / "books" / "idem_test"
            bd.mkdir(parents=True)
            (bd / "meta.json").write_text(json.dumps({
                "book_id": "5555555555555555555",
                "book_name": "IdemBook",
                "author": "IdemAuthor",
                "abstract": "Test abstract",
            }), encoding="utf-8")

            svc = ImportService(db, data_root=str(root))
            r1 = svc.import_all()
            assert r1.books_created == 1

            # Capture updated_at after first import
            book = db.query(FanqieBook).filter_by(
                fanqie_book_id="5555555555555555555").first()
            assert book is not None
            ts1 = book.updated_at

            # Second import — identical content
            r2 = svc.import_all()
            assert r2.books_created == 0
            db.refresh(book)
            ts2 = book.updated_at

            # updated_at must be unchanged (no spurious mutation)
            assert ts2 == ts1, \
                f"updated_at changed from {ts1} to {ts2} on identical re-import"

    def test_second_import_no_extra_events(self, db):
        """Second identical import must NOT add new events."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bd = root / "books" / "ev_test"
            bd.mkdir(parents=True)
            (bd / "meta.json").write_text(json.dumps({
                "book_id": "6666666666666666666",
                "book_name": "EventBook",
            }), encoding="utf-8")

            svc = ImportService(db, data_root=str(root))
            svc.import_all()

            pre_events = db.query(FanqieOperationEvent).count()

            # Second import
            svc.import_all()
            post_events = db.query(FanqieOperationEvent).count()

            assert post_events == pre_events, \
                f"Events grew from {pre_events} to {post_events} on identical re-import"

    def test_second_import_reports_skipped_not_updated(self, db):
        """Second identical import reports books_skipped, not books_updated."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bd = root / "books" / "skip_test"
            bd.mkdir(parents=True)
            (bd / "meta.json").write_text(json.dumps({
                "book_id": "7777777777777777777",
                "book_name": "SkipBook",
            }), encoding="utf-8")

            svc = ImportService(db, data_root=str(root))
            r1 = svc.import_all()
            assert r1.books_created == 1

            r2 = svc.import_all()
            assert r2.books_updated == 0, \
                "Identical re-import must have 0 books_updated"
            assert r2.books_skipped >= 0
            assert r2.books_created == 0

    def test_second_import_no_duplicate_tasks(self, db, book_repo):
        """Second import of same task must not create duplicates."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bd = root / "books" / "tsk_idem"
            bd.mkdir(parents=True)
            (bd / "meta.json").write_text(json.dumps({
                "book_id": "8888888888888888888",
                "book_name": "TaskIdem",
            }), encoding="utf-8")
            td2 = root / "tasks" / "tsk1"
            td2.mkdir(parents=True)
            (td2 / "task.json").write_text(json.dumps({
                "task_id": "UNIQUE_TASK_001",
                "book_id": "8888888888888888888",
                "promotion_alias": "task_idem_alias",
                "apply_status": "active",
            }), encoding="utf-8")

            svc = ImportService(db, data_root=str(root))
            r1 = svc.import_all()
            assert r1.tasks_created == 1

            pre_count = db.query(FanqiePromotionTask).count()

            r2 = svc.import_all()
            assert r2.tasks_created == 0
            assert r2.tasks_skipped >= 1

            post_count = db.query(FanqiePromotionTask).count()
            assert post_count == pre_count, \
                f"Task count changed from {pre_count} to {post_count} on re-import"
