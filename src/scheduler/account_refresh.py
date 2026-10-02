"""Persistent, coalesced account refresh; no offline backlog and no publishing."""
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

DB = Path(__file__).resolve().parents[2] / 'data/account_refresh.db'
DEFAULT_INTERVAL = 4 * 3600
DEFAULT_SMART_INTERVAL = 24 * 3600
LEASE_SECONDS = 3600


@contextmanager
def connect(path=DB):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.executescript('''
      CREATE TABLE IF NOT EXISTS refresh_policy(id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL, interval_seconds INTEGER NOT NULL);
      INSERT OR IGNORE INTO refresh_policy VALUES(1,1,14400);
      CREATE TABLE IF NOT EXISTS refresh_accounts(account_uuid TEXT PRIMARY KEY, account_key TEXT NOT NULL,
        next_due REAL NOT NULL DEFAULT 0, lease_until REAL NOT NULL DEFAULT 0, run_id TEXT);
      CREATE TABLE IF NOT EXISTS refresh_runs(run_id TEXT PRIMARY KEY, account_uuid TEXT NOT NULL,
        account_key TEXT NOT NULL, reason TEXT NOT NULL, started_at REAL NOT NULL,
        finished_at REAL, status TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '{}');
      CREATE TABLE IF NOT EXISTS refresh_run_corrections(run_id TEXT PRIMARY KEY, corrected_at REAL NOT NULL, reason TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS smart_policy(id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL, interval_seconds INTEGER NOT NULL);
      INSERT OR IGNORE INTO smart_policy VALUES(1,1,86400);
      CREATE TABLE IF NOT EXISTS smart_accounts(account_uuid TEXT PRIMARY KEY, account_key TEXT NOT NULL,
        next_due REAL NOT NULL DEFAULT 0, lease_until REAL NOT NULL DEFAULT 0, run_id TEXT);
      CREATE TABLE IF NOT EXISTS smart_runs(run_id TEXT PRIMARY KEY, account_uuid TEXT NOT NULL,
        account_key TEXT NOT NULL, reason TEXT NOT NULL, started_at REAL NOT NULL,
        finished_at REAL, status TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '{}');
    ''')
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def set_policy(enabled, interval_seconds, path=DB):
    if not 3600 <= interval_seconds <= 7 * 86400:
        raise ValueError('同步间隔须在 1 小时至 7 天之间')
    with connect(path) as db:
        db.execute('UPDATE refresh_policy SET enabled=?, interval_seconds=? WHERE id=1', (int(enabled), interval_seconds))
        db.execute('''UPDATE refresh_accounts SET next_due=COALESCE(
            (SELECT MAX(finished_at) FROM refresh_runs WHERE refresh_runs.account_uuid=refresh_accounts.account_uuid),0)+?''',
            (interval_seconds,))


def set_smart_policy(enabled, interval_seconds, path=DB):
    if not 6 * 3600 <= interval_seconds <= 7 * 86400:
        raise ValueError('智能运营间隔须在 6 小时至 7 天之间')
    with connect(path) as db:
        db.execute('UPDATE smart_policy SET enabled=?, interval_seconds=? WHERE id=1', (int(enabled), interval_seconds))
        db.execute('''UPDATE smart_accounts SET next_due=COALESCE(
            (SELECT MAX(finished_at) FROM smart_runs WHERE smart_runs.account_uuid=smart_accounts.account_uuid),0)+?''',
            (interval_seconds,))


def snapshot(path=DB):
    with connect(path) as db:
        return dict(policy=dict(db.execute('SELECT * FROM refresh_policy').fetchone()),
                    smart_policy=dict(db.execute('SELECT * FROM smart_policy').fetchone()),
                    accounts=[dict(r) for r in db.execute('SELECT * FROM refresh_accounts')],
                    smart_accounts=[dict(r) for r in db.execute('SELECT * FROM smart_accounts')],
                    runs=[dict(r) for r in db.execute('SELECT r.*, c.reason AS correction FROM refresh_runs r LEFT JOIN refresh_run_corrections c ON c.run_id=r.run_id ORDER BY started_at DESC LIMIT 100')],
                    smart_runs=[dict(r) for r in db.execute('SELECT * FROM smart_runs ORDER BY started_at DESC LIMIT 100')])


def request_recheck(run_id, reason, path=DB):
    """Append a correction without erasing the original execution result."""
    with connect(path) as db:
        db.execute('INSERT OR REPLACE INTO refresh_run_corrections VALUES(?,?,?)', (run_id, time.time(), reason))
        db.execute('UPDATE refresh_accounts SET next_due=0 WHERE run_id IS NULL AND account_uuid=(SELECT account_uuid FROM refresh_runs WHERE run_id=?)', (run_id,))


def claim(account_uuid, account_key, *, reason='periodic', now=None, path=DB):
    now = time.time() if now is None else now
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        policy = db.execute('SELECT * FROM refresh_policy').fetchone()
        if not policy['enabled']:
            return None
        db.execute('INSERT OR IGNORE INTO refresh_accounts(account_uuid,account_key) VALUES(?,?)', (account_uuid, account_key))
        row = db.execute('SELECT * FROM refresh_accounts WHERE account_uuid=?', (account_uuid,)).fetchone()
        if row['lease_until'] > now or row['next_due'] > now:
            return None
        if row['run_id']:
            db.execute("UPDATE refresh_runs SET status='interrupted', finished_at=?, detail=? WHERE run_id=? AND status='running'",
                       (now, json.dumps({'message': '上次运行未写入结束回执，租约已过期；本次重新检查。'}, ensure_ascii=False), row['run_id']))
        run_id = uuid.uuid4().hex
        db.execute('UPDATE refresh_accounts SET account_key=?,lease_until=?,run_id=? WHERE account_uuid=?',
                   (account_key, now + LEASE_SECONDS, run_id, account_uuid))
        db.execute('INSERT INTO refresh_runs(run_id,account_uuid,account_key,reason,started_at,status) VALUES(?,?,?,?,?,?)',
                   (run_id, account_uuid, account_key, reason, now, 'running'))
        return run_id


def claim_smart(account_uuid, account_key, *, reason='periodic', now=None, path=DB):
    now = time.time() if now is None else now
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        policy = db.execute('SELECT * FROM smart_policy').fetchone()
        if not policy['enabled']:
            return None
        db.execute('INSERT OR IGNORE INTO smart_accounts(account_uuid,account_key) VALUES(?,?)', (account_uuid, account_key))
        row = db.execute('SELECT * FROM smart_accounts WHERE account_uuid=?', (account_uuid,)).fetchone()
        if row['lease_until'] > now or row['next_due'] > now:
            return None
        if row['run_id']:
            db.execute("UPDATE smart_runs SET status='interrupted', finished_at=?, detail=? WHERE run_id=? AND status='running'",
                       (now, json.dumps({'message': '上次智能运营未写入结束回执，租约已过期；本次重新检查。'}, ensure_ascii=False), row['run_id']))
        run_id = uuid.uuid4().hex
        db.execute('UPDATE smart_accounts SET account_key=?,lease_until=?,run_id=? WHERE account_uuid=?',
                   (account_key, now + LEASE_SECONDS, run_id, account_uuid))
        db.execute('INSERT INTO smart_runs(run_id,account_uuid,account_key,reason,started_at,status) VALUES(?,?,?,?,?,?)',
                   (run_id, account_uuid, account_key, reason, now, 'running'))
        return run_id


def finish(run_id, status, detail, *, now=None, path=DB):
    now = time.time() if now is None else now
    with connect(path) as db:
        interval = db.execute('SELECT interval_seconds FROM refresh_policy').fetchone()[0]
        # Auth blocks wait a full interval; transient errors retry after 30 minutes.
        delay = interval if status in {'completed', 'blocked'} else min(interval, 1800)
        db.execute('UPDATE refresh_runs SET status=?, finished_at=?, detail=? WHERE run_id=? AND status=?',
                   (status, now, json.dumps(detail, ensure_ascii=False), run_id, 'running'))
        db.execute('UPDATE refresh_accounts SET next_due=?, lease_until=0,run_id=NULL WHERE run_id=?', (now + delay, run_id))


def finish_smart(run_id, status, detail, *, now=None, path=DB):
    now = time.time() if now is None else now
    with connect(path) as db:
        interval = db.execute('SELECT interval_seconds FROM smart_policy').fetchone()[0]
        # A complete report waits for the next full cycle; failures retry after 30 minutes.
        delay = interval if status == 'completed' else min(interval, 1800)
        db.execute('UPDATE smart_runs SET status=?, finished_at=?, detail=? WHERE run_id=? AND status=?',
                   (status, now, json.dumps(detail, ensure_ascii=False), run_id, 'running'))
        db.execute('UPDATE smart_accounts SET next_due=?, lease_until=0,run_id=NULL WHERE run_id=?', (now + delay, run_id))


def refresh_due_accounts(*, reason='periodic', path=DB):
    from src.operations_accounts import AccountProfileRepository, AccountBindingRepository
    from src.operations_accounts.maintenance import AccountMaintenanceService
    profiles = AccountProfileRepository()
    bindings = AccountBindingRepository(profiles.db_path)
    for profile in profiles.list_active():
        binding = bindings.get_optional(profile.account_key)
        if binding is None:
            continue  # An unbound strategy profile is not a configured platform account.
        smart_run_id = claim_smart(profile.account_uuid, profile.account_key, reason=reason, path=path)
        smart_completed_backend_sync = False
        if smart_run_id is not None:
            try:
                from src.services.smart_operations import run_smart_operations
                report = run_smart_operations(profile.account_key, headless=True)
                backend = report.get('backend_sync') or {}
                smart_completed_backend_sync = bool(backend.get('completed'))
                finish_smart(smart_run_id, str(report.get('status') or 'failed'), dict(
                    message='智能运营报告已生成' if report.get('status') == 'completed' else '智能运营未完整通过，请查看报告',
                    maintenance_run_id=report.get('maintenance_run_id'),
                    topics=report.get('research_keywords') or [],
                    videos=backend.get('videos', 0),
                    related_videos=(report.get('research') or {}).get('unique_relevant_videos', 0),
                    report_markdown=report.get('report_markdown'),
                ), path=path)
            except Exception as exc:
                finish_smart(smart_run_id, 'failed', {
                    'message': '智能运营异常，请查看账号维护日志',
                    'error_type': type(exc).__name__,
                }, path=path)

        run_id = claim(profile.account_uuid, profile.account_key, reason=reason, path=path)
        if run_id is None:
            continue
        if smart_completed_backend_sync:
            finish(run_id, 'completed', {
                'message': '本轮智能运营已同时完成作品后台数据同步。',
                'videos': 0,
                'comments': 0,
                'comment_failures': 0,
                'login_healthy': True,
                'smart_run_id': smart_run_id,
            }, path=path)
            continue
        try:
            result = AccountMaintenanceService().run(profile.account_key, 'post-publish', headless=True)
            finish(run_id, result.status, dict(message=result.message, maintenance_run_id=result.run_id,
                videos=result.synced_videos, comments=result.synced_comments,
                comment_failures=result.comment_sync_failures,
                login_healthy=result.login_healthy), path=path)
        except Exception as exc:
            # Do not copy arbitrary exception payloads (which might contain auth data).
            finish(run_id, 'failed', {'message': '同步异常，请查看账号维护日志', 'error_type': type(exc).__name__}, path=path)
