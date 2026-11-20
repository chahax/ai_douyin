import sqlite3
import time
import pytest

from src.trend_intelligence.repository import TrendRepository, TREND_SCHEMA_VERSION


def test_current_repository_opens_during_other_writer_without_write_attempt(tmp_path, monkeypatch):
    path = tmp_path/'trend.db'
    assert TrendRepository(path)._schema_ready()
    lock = sqlite3.connect(path)
    lock.execute('BEGIN IMMEDIATE')
    monkeypatch.setattr(TrendRepository, '_initialize_connection',
        classmethod(lambda *args: pytest.fail('current schema attempted migration')))
    try:
        started = time.monotonic()
        repo = TrendRepository(path)
        assert repo.db_path == path.resolve()
        assert time.monotonic()-started < 3
        assert lock.in_transaction
    finally:
        lock.rollback()
        lock.close()


@pytest.mark.parametrize('damage', ['version','table','index','column'])
def test_incomplete_schema_is_not_accepted_by_version_number(tmp_path, damage):
    path = tmp_path/'trend.db'
    repo = TrendRepository(path)
    with sqlite3.connect(path) as conn:
        if damage == 'version': conn.execute('PRAGMA user_version=7')
        if damage == 'table': conn.execute('DROP TABLE trend_metric_confirmations')
        if damage == 'index': conn.execute('DROP INDEX idx_collection_runs_plan')
        if damage == 'column': conn.execute('ALTER TABLE trend_items DROP COLUMN published_at_text')
    assert not repo._schema_ready()
    repaired = TrendRepository(path)
    assert repaired._schema_ready()
    with sqlite3.connect(path) as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0] == TREND_SCHEMA_VERSION


def test_locked_schema_read_is_not_treated_as_ready(tmp_path):
    path = tmp_path/'trend.db'
    repo = TrendRepository(path)
    lock = sqlite3.connect(path)
    lock.execute('BEGIN EXCLUSIVE')
    try:
        with pytest.raises(sqlite3.OperationalError):
            repo._schema_ready()
    finally:
        lock.rollback()
        lock.close()


def test_multiple_instances_serialize_only_short_transactions(tmp_path):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    path = tmp_path/'trend.db'
    repositories = [TrendRepository(path), TrendRepository(path)]
    with repositories[0].connection() as conn:
        conn.execute('CREATE TABLE concurrency_fixture(value INTEGER)')
    barrier = threading.Barrier(4)
    active = 0
    peak = 0
    def work(index):
        nonlocal active, peak
        # All analysis workers reach this point together. Only the connection
        # transaction must serialize, including independent repository objects.
        barrier.wait(timeout=5)
        with repositories[index % 2].connection() as conn:
            conn.execute('PRAGMA busy_timeout=10')
            conn.execute('INSERT INTO concurrency_fixture VALUES(?)',(index,))
            active += 1
            peak = max(peak, active)
            time.sleep(0.05)
            active -= 1
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(work, range(4)))
    assert peak == 1
    with repositories[0].connection() as conn:
        assert conn.execute('SELECT COUNT(*) FROM concurrency_fixture').fetchone()[0] == 4


def test_other_database_is_not_blocked_by_connection_scope(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    first = TrendRepository(tmp_path/'first.db')
    second = TrendRepository(tmp_path/'second.db')
    def read_second():
        with second.connection() as conn:
            return conn.execute('PRAGMA user_version').fetchone()[0]
    with ThreadPoolExecutor(max_workers=1) as pool:
        with first.connection():
            assert pool.submit(read_second).result(timeout=3) == TREND_SCHEMA_VERSION
