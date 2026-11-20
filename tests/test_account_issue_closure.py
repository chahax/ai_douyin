"""Per-event human alert closure; no platform/model calls or production databases."""
import importlib.util
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

spec = importlib.util.spec_from_file_location('isolated_account_issue_closure', Path(__file__).parents[1] / 'src/scheduler/account_refresh.py')
ar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ar)


def seed(db):
    run = ar.claim('A', 'a', now=100, path=db)
    ar.pause_account('A', 'a', '原身份暂未读取', path=db)
    return run, ar.snapshot(db)['issues'][0]['id']


def close(db, issue_id, **kwargs):
    return ar.close_account_issue(issue_id, 'A', 'a', closed_by='admin', path=db, **kwargs)


def test_closure_is_persistent_audited_and_preserves_pause_original_run_and_message(tmp_path):
    db = tmp_path / 'closure.db'
    run, issue_id = seed(db)
    original = ar.snapshot(db)
    assert close(db, issue_id, note='已检查原页面，本次无异常')
    current = ar.snapshot(db)
    assert current['controls'] == original['controls']
    assert current['accounts'] == original['accounts']
    assert current['runs'] == original['runs']
    assert current['accounts'][0]['run_id'] == run
    issue = current['issues'][0]
    assert issue['status'] == 'closed'
    assert issue['message'] == original['issues'][0]['message']
    assert issue['created_at'] == original['issues'][0]['created_at']
    assert issue['closed_by'] == 'admin'
    assert issue['closure_note'] == '已检查原页面，本次无异常'
    assert issue['closed_at'] > 0
    assert not close(db, issue_id, note='重复点击不得覆盖原审计')
    with ar.connect(db) as connection:
        audits = connection.execute('SELECT * FROM account_issue_closures').fetchall()
    assert len(audits) == 1 and audits[0]['note'] == '已检查原页面，本次无异常'


def test_account_scope_and_operator_validation_reject_without_changes(tmp_path):
    db = tmp_path / 'closure.db'
    _, issue_id = seed(db)
    for account_uuid, account_key in [('B', 'a'), ('A', 'b'), ('B', 'b')]:
        assert not ar.close_account_issue(issue_id, account_uuid, account_key, closed_by='admin', path=db)
    with pytest.raises(ValueError, match='实际操作者'):
        ar.close_account_issue(issue_id, 'A', 'a', closed_by='  ', path=db)
    assert not close(db, issue_id + 100)
    assert ar.snapshot(db)['issues'][0]['status'] == 'open'
    with ar.connect(db) as connection:
        assert connection.execute('SELECT COUNT(*) FROM account_issue_closures').fetchone()[0] == 0


def test_close_old_event_does_not_hide_concurrent_recurrence_with_same_error(tmp_path):
    db = tmp_path / 'closure.db'
    _, old_issue_id = seed(db)
    barrier = Barrier(2)
    def close_old():
        barrier.wait()
        return close(db, old_issue_id)
    def recur():
        barrier.wait()
        ar.pause_account('A', 'a', '原身份暂未读取', path=db)
    with ThreadPoolExecutor(max_workers=2) as pool:
        old = pool.submit(close_old)
        new = pool.submit(recur)
        assert old.result() is True
        new.result()
    issues = ar.snapshot(db)['issues']
    assert len(issues) == 2
    assert issues[0]['id'] != old_issue_id and issues[0]['status'] == 'open'
    assert issues[1]['id'] == old_issue_id and issues[1]['status'] == 'closed'
    assert issues[0]['error_code'] == issues[1]['error_code']
    assert issues[0]['closed_at'] is None


def test_concurrent_duplicate_closure_has_exactly_one_audit(tmp_path):
    db = tmp_path / 'closure.db'
    _, issue_id = seed(db)
    barrier = Barrier(2)
    def attempt():
        barrier.wait()
        return close(db, issue_id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt) for _ in range(2)]
        assert sorted(future.result() for future in futures) == [False, True]
    with ar.connect(db) as connection:
        assert connection.execute('SELECT COUNT(*) FROM account_issue_closures').fetchone()[0] == 1


def test_resolved_issue_cannot_be_closed_as_human_no_issue_judgment(tmp_path):
    db = tmp_path / 'closure.db'
    ar.pause_account('A', 'a', '待核验', path=db)
    issue_id = ar.snapshot(db)['issues'][0]['id']
    ar.request_account_recovery('A', 'a', path=db)
    token = ar._claim_recovery('A', 'a', path=db)
    assert ar._finish_recovery('A', 'a', token, healthy=True, status='active', path=db)
    assert not close(db, issue_id)
    issue = ar.snapshot(db)['issues'][0]
    assert issue['status'] == 'resolved' and issue['closed_at'] is None


def test_old_database_migrates_audit_table_without_rewriting_existing_evidence(tmp_path):
    db = tmp_path / 'legacy.db'
    seed(db)
    ar.set_policy(False, 3600, db)
    original = ar.snapshot(db)
    with sqlite3.connect(db) as connection:
        connection.execute('DROP TABLE account_issue_closures')
    migrated = ar.snapshot(db)
    assert migrated == original
    assert close(db, original['issues'][0]['id'])
    assert ar.snapshot(db)['policy']['enabled'] == 0


def test_malformed_audit_structure_stops_and_valid_snapshot_remains_read_only(tmp_path, monkeypatch):
    db = tmp_path / 'closure.db'
    seed(db)
    statements = []
    original_connect = sqlite3.connect
    def traced_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection
    monkeypatch.setattr(ar.sqlite3, 'connect', traced_connect)
    with original_connect(db) as writer:
        writer.execute('BEGIN IMMEDIATE')
        ar.snapshot(db)
    assert not any(sql.lstrip().upper().startswith(('BEGIN', 'CREATE', 'INSERT', 'UPDATE')) for sql in statements)
    with original_connect(db) as connection:
        connection.execute('DROP TABLE account_issue_closures')
        connection.execute('CREATE TABLE account_issue_closures(issue_id INTEGER PRIMARY KEY)')
    with pytest.raises(sqlite3.DatabaseError, match='account_issue_closures missing'):
        ar.snapshot(db)


def test_snapshot_keeps_all_open_issues_even_when_newer_history_exceeds_limit(tmp_path):
    db = tmp_path / 'closure.db'
    _, original_issue_id = seed(db)
    with ar.connect(db) as connection:
        connection.executemany('''INSERT INTO account_issues(account_uuid,account_key,error_code,message,status,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?)''', [('B', 'b', 'network_error', '旧事件', 'closed', 100, 100)] * 205)
    issues = ar.snapshot(db)['issues']
    assert len(issues) == 201
    assert any(issue['id'] == original_issue_id and issue['status'] == 'open' for issue in issues)
    assert sum(issue['status'] != 'open' for issue in issues) == 200


def test_closure_notes_are_public_safe(tmp_path):
    db = tmp_path / 'closure.db'
    _, issue_id = seed(db)
    assert close(db, issue_id, note='Cookie: sessionid=private-value')
    assert 'private-value' not in json.dumps(ar.snapshot(db))
