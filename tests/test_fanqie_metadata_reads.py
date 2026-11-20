import json
import sqlite3
import threading
import time
import pytest
from src.operations_accounts.fanqie_account_control import metadata_read
from src.operations_accounts.browser_control import BrowserControlRejected


def test_real_sqlite_lock_retries_only_read_then_recovers(tmp_path):
    path=tmp_path/'locked.db'
    db=sqlite3.connect(path)
    db.execute('CREATE TABLE sample(value)');db.execute('INSERT INTO sample VALUES(42)');db.commit();db.close()
    ready=threading.Event()
    def hold():
        connection=sqlite3.connect(path)
        connection.execute('BEGIN EXCLUSIVE');ready.set();time.sleep(.4)
        connection.rollback();connection.close()
    thread=threading.Thread(target=hold);thread.start();assert ready.wait(2)
    calls=[]
    def read():
        connection=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=.02)
        try:
            calls.append(1)
            return connection.execute('SELECT value FROM sample').fetchone()[0]
        finally: connection.close()
    evidence=tmp_path/'diagnostic.json'
    try:
        assert metadata_read(read,evidence_path=evidence,stage='fixture_guard',deadline_seconds=2)==42
    finally: thread.join()
    assert len(calls)>1
    value=json.loads(evidence.read_text())
    assert value['sqlite_errorcode']==sqlite3.SQLITE_BUSY and value['read_only_retry']


def test_persistent_lock_stops_without_success(tmp_path):
    now=[0.0]; calls=[]
    def read():
        calls.append(1)
        error=sqlite3.OperationalError('private query must not be recorded')
        error.sqlite_errorcode=sqlite3.SQLITE_BUSY
        raise error
    evidence=tmp_path/'diagnostic.json'
    with pytest.raises(BrowserControlRejected,match='读取失败'):
        metadata_read(read,evidence_path=evidence,stage='guard',deadline_seconds=.5,
            clock=lambda:now[0],sleep=lambda amount:now.__setitem__(0,now[0]+amount))
    assert len(calls)==3 and 'private' not in evidence.read_text()


def test_non_contention_operational_error_is_not_retried(tmp_path):
    calls=[]
    def read():
        calls.append(1)
        error=sqlite3.OperationalError('fixture I/O failure')
        error.sqlite_errorcode=sqlite3.SQLITE_IOERR
        raise error
    with pytest.raises(BrowserControlRejected):
        metadata_read(read,evidence_path=tmp_path/'diag.json',stage='binding')
    assert len(calls)==1
