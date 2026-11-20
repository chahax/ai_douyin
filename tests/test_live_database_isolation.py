"""A mistaken default database in a test must fail before opening production."""
import sqlite3
from pathlib import Path

import pytest


def test_live_database_default_and_readonly_uri_are_rejected():
    path = Path(__file__).resolve().parents[1] / 'data/account_browser_control.db'
    for target in (path, path.as_uri() + '?mode=ro', 'data/account_refresh.db'):
        with pytest.raises(RuntimeError, match='live project database'):
            sqlite3.connect(target, uri=str(target).startswith('file:'))


def test_temporary_and_memory_databases_remain_available(tmp_path):
    for target in (tmp_path / 'test.db', ':memory:'):
        with sqlite3.connect(target) as db:
            db.execute('create table probe (value integer)')
            db.execute('insert into probe values (1)')
            assert db.execute('select value from probe').fetchone()[0] == 1
