"""Persistent, coalesced account refresh; no offline backlog and no publishing."""
import json
import re
import sqlite3
import stat
import time
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path

DB = Path(__file__).resolve().parents[2] / 'data/account_refresh.db'
DEFAULT_INTERVAL = 4 * 3600
DEFAULT_SMART_INTERVAL = 24 * 3600
LEASE_SECONDS = 3600
_RECOVERY_SCAN_LOCK = threading.Lock()


_REQUIRED_COLUMNS = {
    'refresh_policy': {'id', 'enabled', 'interval_seconds'},
    'smart_policy': {'id', 'enabled', 'interval_seconds'},
    'refresh_accounts': {'account_uuid', 'account_key', 'next_due', 'lease_until', 'run_id'},
    'smart_accounts': {'account_uuid', 'account_key', 'next_due', 'lease_until', 'run_id'},
    'playback_policies': {'account_uuid', 'account_key', 'enabled', 'interval_seconds', 'options_json',
                          'authorization_reference', 'updated_at', 'revision'},
    'playback_accounts': {'account_uuid', 'account_key', 'next_due', 'lease_until', 'run_id'},
    'playback_runs': {'run_id', 'account_uuid', 'account_key', 'reason', 'started_at', 'finished_at',
                      'status', 'detail', 'policy_snapshot', 'dispatched_at'},
    'refresh_runs': {'run_id', 'account_uuid', 'account_key', 'reason', 'started_at', 'finished_at', 'status', 'detail'},
    'smart_runs': {'run_id', 'account_uuid', 'account_key', 'reason', 'started_at', 'finished_at', 'status', 'detail'},
    'refresh_run_corrections': {'run_id', 'corrected_at', 'reason'},
    'account_controls': {'account_uuid', 'account_key', 'state', 'reason', 'error_code',
                         'consecutive_failures', 'updated_at', 'recovery_requested_at',
                         'recovery_lease_until', 'recovery_token', 'revision'},
    'account_issues': {'id', 'account_uuid', 'account_key', 'error_code', 'message', 'status', 'created_at', 'updated_at'},
    'account_issue_closures': {'issue_id', 'account_uuid', 'account_key', 'closed_by', 'note', 'closed_at'},
    'account_handling_requests': {'request_id', 'account_uuid', 'account_key', 'handled_by', 'requested_at',
                                  'control_revision', 'status', 'probe_token', 'targets_json', 'policies_json',
                                  'finished_at', 'message'},
    'automation_service': {'component', 'status', 'message', 'error_code', 'updated_at'},
}


def _schema_ready(db):
    """Read-only fast path: snapshots and heartbeats need no migration write lock."""
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    ready = True
    for table, required in _REQUIRED_COLUMNS.items():
        if table not in tables:
            ready = False
            continue
        columns = {row[1] for row in db.execute(f'PRAGMA table_info({table})')}
        missing = required - columns
        if missing:
            raise sqlite3.DatabaseError(f'Account automation schema mismatch: {table} missing {", ".join(sorted(missing))}')
    for policy in ('refresh_policy', 'smart_policy'):
        if policy in tables and db.execute(f'SELECT 1 FROM {policy} WHERE id=1').fetchone() is None:
            ready = False
    return ready


@contextmanager
def connect(path=DB):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        # Existing valid databases are checked only with reads. New/old databases
        # migrate atomically; a malformed existing table is never silently accepted.
        if not _schema_ready(db):
            db.executescript('''
      BEGIN IMMEDIATE;
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
      CREATE TABLE IF NOT EXISTS playback_policies(account_uuid TEXT PRIMARY KEY, account_key TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 0, interval_seconds INTEGER NOT NULL,
        options_json TEXT NOT NULL, authorization_reference TEXT NOT NULL, updated_at REAL NOT NULL,
        revision INTEGER NOT NULL DEFAULT 1);
      CREATE TABLE IF NOT EXISTS playback_accounts(account_uuid TEXT PRIMARY KEY, account_key TEXT NOT NULL,
        next_due REAL NOT NULL DEFAULT 0, lease_until REAL NOT NULL DEFAULT 0, run_id TEXT);
      CREATE TABLE IF NOT EXISTS playback_runs(run_id TEXT PRIMARY KEY, account_uuid TEXT NOT NULL,
        account_key TEXT NOT NULL, reason TEXT NOT NULL, started_at REAL NOT NULL, finished_at REAL,
        status TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '{}', policy_snapshot TEXT NOT NULL, dispatched_at REAL);
      CREATE TABLE IF NOT EXISTS account_controls(account_uuid TEXT PRIMARY KEY, account_key TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'active', reason TEXT NOT NULL DEFAULT '', error_code TEXT NOT NULL DEFAULT '',
        consecutive_failures INTEGER NOT NULL DEFAULT 0, updated_at REAL NOT NULL,
        recovery_requested_at REAL, recovery_lease_until REAL NOT NULL DEFAULT 0,
        recovery_token TEXT, revision INTEGER NOT NULL DEFAULT 0);
      CREATE TABLE IF NOT EXISTS account_issues(id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_uuid TEXT NOT NULL, account_key TEXT NOT NULL, error_code TEXT NOT NULL,
        message TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', created_at REAL NOT NULL, updated_at REAL NOT NULL);
      CREATE TABLE IF NOT EXISTS account_issue_closures(issue_id INTEGER PRIMARY KEY,
        account_uuid TEXT NOT NULL, account_key TEXT NOT NULL, closed_by TEXT NOT NULL,
        note TEXT NOT NULL, closed_at REAL NOT NULL,
        FOREIGN KEY(issue_id) REFERENCES account_issues(id));
      CREATE TABLE IF NOT EXISTS account_handling_requests(request_id TEXT PRIMARY KEY,
        account_uuid TEXT NOT NULL, account_key TEXT NOT NULL, handled_by TEXT NOT NULL,
        requested_at REAL NOT NULL, control_revision INTEGER NOT NULL, status TEXT NOT NULL,
        probe_token TEXT, targets_json TEXT NOT NULL, policies_json TEXT NOT NULL,
        finished_at REAL, message TEXT NOT NULL DEFAULT '');
      CREATE TABLE IF NOT EXISTS automation_service(component TEXT PRIMARY KEY, status TEXT NOT NULL,
        message TEXT NOT NULL, error_code TEXT NOT NULL, updated_at REAL NOT NULL);
      COMMIT;
            ''')
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def initialize_wal_storage(*, path=DB, idle_confirmed=False):
    """Explicit offline maintenance only; ordinary connections never change journal mode.

    The caller must stop every service using this file and retain a consistent
    backup first. Application claims are checked again here; this is not a way
    to clear an unknown run or steal its lock.
    """
    if idle_confirmed is not True:
        raise ValueError('必须先确认服务空闲、已停止且已有一致备份，再离线初始化WAL')
    target = Path(path).resolve()
    if not target.is_file():
        raise FileNotFoundError('离线WAL初始化需要已存在的账号调度数据库')
    db = sqlite3.connect(target.as_uri() + '?mode=rw', uri=True, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        if not _schema_ready(db):
            raise sqlite3.DatabaseError('账号调度schema尚未迁移完成，未改变日志模式')
        for table in ('refresh_accounts', 'smart_accounts', 'playback_accounts'):
            if db.execute(f'SELECT 1 FROM {table} WHERE run_id IS NOT NULL LIMIT 1').fetchone():
                raise RuntimeError('存在未结清的原业务运行，未改变日志模式')
        if db.execute('SELECT 1 FROM account_controls WHERE recovery_token IS NOT NULL LIMIT 1').fetchone():
            raise RuntimeError('存在未结清的原恢复核验，未改变日志模式')
        if (db.execute("SELECT 1 FROM account_controls WHERE state IN ('recovery_requested','recovering') LIMIT 1").fetchone()
                or db.execute("SELECT 1 FROM account_handling_requests WHERE status IN ('requested','probing') LIMIT 1").fetchone()):
            raise RuntimeError('存在等待或正在执行的原核验请求，未改变日志模式')
        previous = str(db.execute('PRAGMA journal_mode').fetchone()[0]).lower()
        mode = previous
        if previous != 'wal':
            mode = str(db.execute('PRAGMA journal_mode=WAL').fetchone()[0]).lower()
        if mode != 'wal':
            raise RuntimeError('WAL初始化未生效，未确认完成')
        return dict(path=str(target), previous_journal_mode=previous, journal_mode=mode, changed=previous != mode)
    finally:
        db.close()


def set_policy(enabled, interval_seconds, path=DB):
    if not 3600 <= interval_seconds <= 7 * 86400:
        raise ValueError('同步间隔须在 1 小时至 7 天之间')
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        old = db.execute('SELECT enabled,interval_seconds FROM refresh_policy WHERE id=1').fetchone()
        if (old['enabled'], old['interval_seconds']) != (int(enabled), interval_seconds):
            _invalidate_handling_requests(db, None, time.time(), '同步计划设置已变更，请确认当前设置后重新点击处理完成。')
        db.execute('UPDATE refresh_policy SET enabled=?, interval_seconds=? WHERE id=1', (int(enabled), interval_seconds))
        db.execute('''UPDATE refresh_accounts SET next_due=COALESCE(
            (SELECT MAX(finished_at) FROM refresh_runs WHERE refresh_runs.account_uuid=refresh_accounts.account_uuid),0)+?''',
            (interval_seconds,))


def set_smart_policy(enabled, interval_seconds, path=DB):
    if not 6 * 3600 <= interval_seconds <= 7 * 86400:
        raise ValueError('智能运营间隔须在 6 小时至 7 天之间')
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        old = db.execute('SELECT enabled,interval_seconds FROM smart_policy WHERE id=1').fetchone()
        if (old['enabled'], old['interval_seconds']) != (int(enabled), interval_seconds):
            _invalidate_handling_requests(db, None, time.time(), '智能运营计划设置已变更，请确认当前设置后重新点击处理完成。')
        db.execute('UPDATE smart_policy SET enabled=?, interval_seconds=? WHERE id=1', (int(enabled), interval_seconds))
        db.execute('''UPDATE smart_accounts SET next_due=COALESCE(
            (SELECT MAX(finished_at) FROM smart_runs WHERE smart_runs.account_uuid=smart_accounts.account_uuid),0)+?''',
            (interval_seconds,))


def set_playback_policy(account_uuid, account_key, enabled, interval_seconds=86400, options=None, *,
                        authorization_reference='', schedule=None, path=DB):
    from src.scheduler.account_playback import normalize_options
    if not account_uuid or not account_key:
        raise ValueError('自动播放计划必须绑定具体账号')
    if isinstance(interval_seconds, bool) or not isinstance(interval_seconds, int) or not 8 * 3600 <= interval_seconds <= 7 * 86400:
        raise ValueError('自动播放间隔须在8小时至7天之间')
    normalized = normalize_options(options)
    reference = _safe_text(str(authorization_reference or '').strip())
    if enabled and not reference:
        raise ValueError('启用自动播放必须记录授权来源')
    now = time.time()
    options_json = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        old = db.execute('SELECT * FROM playback_policies WHERE account_uuid=?', (account_uuid,)).fetchone()
        from src.scheduler.playback_random_schedule import (
            read as read_random, normalize as normalize_random, save as save_random, next_due as random_next)
        old_schedule = read_random(db, account_uuid)
        random_schedule = normalize_random(schedule, old_schedule)
        if old and old['account_key'] != account_key:
            raise ValueError('自动播放策略的账号绑定不一致')
        if old and old_schedule == random_schedule and (old['enabled'], old['interval_seconds'], old['options_json'], old['authorization_reference']) == (int(bool(enabled)), interval_seconds, options_json, reference):
            return
        revision = old['revision'] + 1 if old else 1
        _invalidate_handling_requests(db, account_uuid, now, '自动播放设置已变更，请确认当前设置后重新点击处理完成。')
        db.execute('''INSERT INTO playback_policies VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(account_uuid) DO UPDATE SET enabled=excluded.enabled,interval_seconds=excluded.interval_seconds,
            options_json=excluded.options_json,authorization_reference=excluded.authorization_reference,
            updated_at=excluded.updated_at,revision=excluded.revision''',
            (account_uuid, account_key, int(bool(enabled)), interval_seconds, options_json, reference, now, revision))
        db.execute('INSERT OR IGNORE INTO playback_accounts(account_uuid,account_key) VALUES(?,?)', (account_uuid, account_key))
        save_random(db, account_uuid, account_key, random_schedule)
        # Settings never clear a run/lease, or replay every interval missed offline.
        db.execute('''UPDATE playback_accounts SET next_due=COALESCE(
            (SELECT MAX(finished_at)+? FROM playback_runs WHERE account_uuid=?),0)
            WHERE account_uuid=? AND run_id IS NULL''', (interval_seconds, account_uuid, account_uuid))
        if random_schedule is not None:
            db.execute('UPDATE playback_accounts SET next_due=? WHERE account_uuid=? AND run_id IS NULL',
                       (random_next(db, account_uuid, random_schedule, now), account_uuid))


def _playback_policy_dict(row, db=None):
    result = dict(row)
    result['options'] = json.loads(result.pop('options_json'))
    if db is not None:
        from src.scheduler.playback_random_schedule import read
        schedule = read(db, result['account_uuid'])
        if schedule is not None:
            result['schedule'] = schedule
    return result


def snapshot(path=DB):
    with connect(path) as db:
        from src.scheduler.queued_refresh_recovery import snapshot as queued_refresh_snapshot
        return dict(policy=dict(db.execute('SELECT * FROM refresh_policy').fetchone()),
                    queued_refresh_waits=queued_refresh_snapshot(db),
                    smart_policy=dict(db.execute('SELECT * FROM smart_policy').fetchone()),
                    accounts=[dict(r) for r in db.execute('SELECT * FROM refresh_accounts')],
                    smart_accounts=[dict(r) for r in db.execute('SELECT * FROM smart_accounts')],
                    runs=[dict(r) for r in db.execute('SELECT r.*, c.reason AS correction FROM refresh_runs r LEFT JOIN refresh_run_corrections c ON c.run_id=r.run_id ORDER BY started_at DESC LIMIT 100')],
                    smart_runs=[dict(r) for r in db.execute('SELECT * FROM smart_runs ORDER BY started_at DESC LIMIT 100')],
                    playback_policies=[_playback_policy_dict(r,db) for r in db.execute('SELECT * FROM playback_policies')],
                    playback_accounts=[dict(r) for r in db.execute('SELECT * FROM playback_accounts')],
                    playback_runs=[dict(r) for r in db.execute('SELECT * FROM playback_runs ORDER BY started_at DESC LIMIT 100')],
                    handling_requests=[dict(r) for r in db.execute('''SELECT request_id,account_uuid,account_key,handled_by,
                        requested_at,control_revision,status,targets_json,finished_at,message
                        FROM account_handling_requests ORDER BY requested_at DESC LIMIT 200''')],
                    controls=[dict(r) for r in db.execute('SELECT account_uuid,account_key,state,reason,error_code,consecutive_failures,updated_at,recovery_requested_at,recovery_lease_until FROM account_controls')],
                    issues=[dict(r) for r in db.execute('''SELECT i.*, c.closed_at, c.closed_by, c.note AS closure_note
                        FROM account_issues i LEFT JOIN account_issue_closures c
                        ON c.issue_id=i.id AND c.account_uuid=i.account_uuid AND c.account_key=i.account_key
                        WHERE i.status='open' OR i.id IN (
                            SELECT id FROM account_issues WHERE status!='open' ORDER BY id DESC LIMIT 200)
                        ORDER BY i.id DESC''')],
                    service={r['component']: dict(r) for r in db.execute('SELECT * FROM automation_service')})


def _safe_text(value):
    # These public summaries must never copy cookies, auth URLs or exception payloads.
    text = str(value or '')[:500]
    if re.search(r'(?i)(cookie|authorization|bearer|token|password|sessionid|https?://)', text):
        return '详细信息可能包含敏感数据，请在本机安全日志中处理。'
    return text


def update_service_status(component, status, *, message='', error_code='', path=DB):
    with connect(path) as db:
        db.execute('INSERT OR REPLACE INTO automation_service VALUES(?,?,?,?,?)',
                   (component, status, _safe_text(message), _safe_text(error_code), time.time()))


def _ensure_control(db, account_uuid, account_key, now):
    db.execute('INSERT OR IGNORE INTO account_controls(account_uuid,account_key,updated_at) VALUES(?,?,?)',
               (account_uuid, account_key, now))


def _issue(db, account_uuid, account_key, error_code, message, now):
    # Preserve the event on repeated observations instead of overwriting history.
    db.execute('INSERT INTO account_issues(account_uuid,account_key,error_code,message,created_at,updated_at) VALUES(?,?,?,?,?,?)',
               (account_uuid, account_key, _safe_text(error_code), _safe_text(message), now, now))


def _pause(db, account_uuid, account_key, reason, error_code, now):
    _ensure_control(db, account_uuid, account_key, now)
    _invalidate_handling_requests(db, account_uuid, now, '账号再次暂停，原人工完成请求已失效。', pause_controls=False)
    db.execute("UPDATE account_controls SET state='paused',reason=?,error_code=?,updated_at=?,recovery_requested_at=NULL,revision=revision+1 WHERE account_uuid=?",
               (_safe_text(reason), _safe_text(error_code), now, account_uuid))
    _issue(db, account_uuid, account_key, error_code, reason, now)


def pause_account(account_uuid, account_key, reason, *, preserve_existing_pause=False, path=DB):
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        if preserve_existing_pause:
            _ensure_control(db, account_uuid, account_key, time.time())
            existing = db.execute('SELECT * FROM account_controls WHERE account_uuid=?', (account_uuid,)).fetchone()
            if existing['account_key'] != account_key:
                raise ValueError('账号UUID与原账号标识不一致')
            if existing['state'] == 'paused':
                return
        _pause(db, account_uuid, account_key, reason or '已由人工暂停后台任务', 'manual_pause', time.time())


def close_account_issue(issue_id, account_uuid, account_key, *, closed_by,
                        note='人工判断无异常，关闭本次提示', path=DB):
    """Close this single alert with an immutable audit, without changing execution controls."""
    operator = _safe_text(str(closed_by or '').strip())
    if not operator:
        raise ValueError('关闭异常提示必须记录实际操作者')
    explanation = _safe_text(str(note or '').strip() or '人工判断无异常，关闭本次提示')
    now = time.time()
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        updated = db.execute("""UPDATE account_issues SET status='closed', updated_at=?
            WHERE id=? AND account_uuid=? AND account_key=? AND status='open'""",
            (now, issue_id, account_uuid, account_key))
        if updated.rowcount != 1:
            return False
        db.execute('''INSERT INTO account_issue_closures(issue_id,account_uuid,account_key,closed_by,note,closed_at)
            VALUES(?,?,?,?,?,?)''', (issue_id, account_uuid, account_key, operator, explanation, now))
        return True


_PLAN_KINDS = ('refresh', 'smart', 'playback')
_UNKNOWN_OUTCOME_CODES = frozenset({'outcome_unknown', 'recovery_outcome_unknown'})


def _unknown_outcome_code(code):
    return str(code or '').lower() in _UNKNOWN_OUTCOME_CODES


def _run_has_unknown_outcome(run):
    try:
        detail = json.loads(run['detail'])
    except (TypeError, ValueError):
        return False
    return isinstance(detail, dict) and _unknown_outcome_code(detail.get('error_code'))


def _invalidate_handling_requests(db, account_uuid, now, message, *, pause_controls=True):
    query = "SELECT * FROM account_handling_requests WHERE status IN ('requested','probing')"
    parameters = ()
    if account_uuid is not None:
        query += ' AND account_uuid=?'
        parameters = (account_uuid,)
    for request in db.execute(query, parameters).fetchall():
        db.execute("UPDATE account_handling_requests SET status='invalidated',finished_at=?,message=? WHERE request_id=?",
                   (now, _safe_text(message), request['request_id']))
        if pause_controls:
            # Keep an original probe's token/lease until its actual receipt arrives.
            db.execute("""UPDATE account_controls SET state='paused',reason=?,error_code='handling_request_invalidated',
                updated_at=?,recovery_requested_at=NULL,revision=revision+1
                WHERE account_uuid=? AND revision=? AND state IN ('recovery_requested','recovering')""",
                (_safe_text(message), now, request['account_uuid'], request['control_revision']))


def _handling_policies(db, account_uuid, account_key):
    values = {kind: dict(db.execute(f'SELECT enabled,interval_seconds FROM {kind}_policy WHERE id=1').fetchone())
              for kind in ('refresh', 'smart')}
    row = db.execute('SELECT * FROM playback_policies WHERE account_uuid=? AND account_key=?', (account_uuid, account_key)).fetchone()
    values['playback'] = dict(row) if row else None
    return values


def _latest_plan_run(db, kind, account_uuid, account_key):
    return db.execute(f'''SELECT * FROM {kind}_runs WHERE account_uuid=? AND account_key=?
        ORDER BY started_at DESC,rowid DESC LIMIT 1''', (account_uuid, account_key)).fetchone()


def _handling_targets_valid(db, request):
    targets = json.loads(request['targets_json'])
    for target in targets:
        if target.get('kind') not in _PLAN_KINDS:
            return False
        latest = _latest_plan_run(db, target['kind'], request['account_uuid'], request['account_key'])
        owner = db.execute(f"SELECT * FROM {target['kind']}_accounts WHERE account_uuid=? AND account_key=?",
                           (request['account_uuid'], request['account_key'])).fetchone()
        if target.get('status') == 'waiting_original':
            from src.scheduler.queued_refresh_recovery import reference
            current_wait=reference(db,target['run_id'])
            if (target['kind']!='refresh' or not latest or latest['run_id']!=target['run_id']
                    or not current_wait or current_wait!=target.get('queued_wait')):
                return False
            continue
        if (not latest or not owner or owner['run_id'] is not None or latest['run_id'] != target['run_id']
                or latest['status'] not in {'failed', 'blocked'} or latest['status'] != target['status']
                or latest['finished_at'] is None or latest['finished_at'] != target['finished_at']
                or _run_has_unknown_outcome(latest)):
            return False
    return True


def _handling_unresolved(db, account_uuid, now):
    if _pending_manual_window(db, account_uuid):
        return 'manual_window_pending'
    busy = False
    for kind in _PLAN_KINDS:
        owner = db.execute(f'SELECT * FROM {kind}_accounts WHERE account_uuid=?', (account_uuid,)).fetchone()
        rows = db.execute(f'SELECT run_id,status,finished_at,detail FROM {kind}_runs WHERE account_uuid=?', (account_uuid,)).fetchall()
        from src.scheduler.queued_refresh_recovery import reference
        waiting = reference(db,owner['run_id']) if kind=='refresh' and owner and owner['run_id'] else None
        rows = [row for row in rows if not waiting or row['run_id']!=waiting['run_id']]
        if waiting:
            owner = None  # Keep its actual cursor/lease untouched; exclude only from this gate.
        if (any(row['status'] == 'outcome_unknown' or _run_has_unknown_outcome(row) for row in rows)
                or (owner and owner['run_id'] and owner['lease_until'] <= now)):
            return 'outcome_unknown'
        if any(row['status'] == 'running' or row['finished_at'] is None for row in rows) or (owner and owner['run_id']):
            busy = True
    return 'busy' if busy else None


def _pending_manual_window(db, account_uuid):
    """Lightweight RO sibling-store gate; no operations package import under this writer lock."""
    main = next((row[2] for row in db.execute('PRAGMA database_list') if row[1] == 'main'), '')
    if not main:
        raise sqlite3.DatabaseError('无法确认人工窗口状态库位置，未放行恢复')
    target = Path(main).parent / 'account_manual_windows.db'
    try:
        metadata = target.stat()
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(metadata.st_mode):
        raise sqlite3.DatabaseError('人工窗口状态路径不是数据库文件')
    control = db.execute('SELECT account_key FROM account_controls WHERE account_uuid=?', (account_uuid,)).fetchone()
    if not control:
        raise sqlite3.DatabaseError('缺少原账号控制绑定，无法核对人工窗口状态')
    window_db = sqlite3.connect(target.resolve().as_uri() + '?mode=ro', uri=True, timeout=1)
    window_db.row_factory = sqlite3.Row
    try:
        binding = window_db.execute('SELECT account_uuid,account_key FROM manual_window_accounts WHERE account_uuid=? OR account_key=?',
                                    (account_uuid, control['account_key'])).fetchone()
        if binding and (binding['account_uuid'] != account_uuid or binding['account_key'] != control['account_key']):
            raise sqlite3.DatabaseError('人工窗口任务与原账号控制绑定不一致')
        # Same terminal contract as manual_window_jobs.has_pending_manual_window_job:
        # only known closed/failed releases the gate; all active/unknown states block.
        return window_db.execute("""SELECT 1 FROM manual_window_jobs WHERE account_uuid=? AND account_key=?
            AND state NOT IN ('closed','failed') LIMIT 1""", (account_uuid, control['account_key'])).fetchone() is not None
    finally:
        window_db.close()


def complete_account_handling(account_uuid, account_key, *, handled_by, path=DB,
                              plan_kinds=None, expected_revision=None):
    """Record a single human completion; identity verification still happens in the scheduler."""
    actor = _safe_text(str(handled_by or '').strip())
    if not actor:
        return dict(accepted=False, state='invalid_actor', message='请使用已登录的管理员身份登记处理完成。')
    selected = _PLAN_KINDS if plan_kinds is None else tuple(plan_kinds)
    if not selected or any(kind not in _PLAN_KINDS for kind in selected):
        raise ValueError('Invalid continuation plans')
    now = time.time()
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        control = db.execute('SELECT * FROM account_controls WHERE account_uuid=?', (account_uuid,)).fetchone()
        if not control:
            return dict(accepted=False, state='binding_required', message='未找到此账号的后台控制绑定，请先核对原账号。')
        if control['account_key'] != account_key:
            return dict(accepted=False, state='binding_mismatch', message='账号UUID与原账号标识不一致，已拒绝登记。')
        if expected_revision is not None and control['revision'] != expected_revision:
            return dict(accepted=False, state='revision_changed', message='账号状态已变化，未登记旧页面的恢复请求。')
        if _unknown_outcome_code(control['error_code']):
            return dict(accepted=False, state='outcome_unknown', message='原运行或原恢复核验的结果仍未知，请先核对原任务；没有登记新请求。')
        if control['state'] != 'paused':
            return dict(accepted=False, state=control['state'], message='当前账号已在等待核验、核验中或正常运行，不重复登记。')
        if control['recovery_token']:
            state = 'outcome_unknown' if control['error_code'] == 'recovery_outcome_unknown' or control['recovery_lease_until'] <= now else 'busy'
            return dict(accepted=False, state=state, message='原恢复核验尚未结清，请先核对原任务；没有重新派发。')
        unresolved = _handling_unresolved(db, account_uuid, now)
        if unresolved:
            if unresolved == 'manual_window_pending':
                return dict(accepted=False, state=unresolved, message='原人工处理窗口尚未确认结束或结果未知，请先核对原窗口任务；没有重新派发。')
            return dict(accepted=False, state=unresolved, message='原业务仍在运行或结果未知，请先核对原任务；原ID和锁保持，未登记新核验。')
        if db.execute("SELECT 1 FROM account_handling_requests WHERE account_uuid=? AND status IN ('requested','probing')", (account_uuid,)).fetchone():
            return dict(accepted=False, state='busy', message='本账号已有人工完成请求，未重复登记。')
        policies = _handling_policies(db, account_uuid, account_key)
        targets = []
        for kind in selected:
            latest = _latest_plan_run(db, kind, account_uuid, account_key)
            policy = policies[kind]
            if (policy and policy['enabled'] and latest and latest['finished_at'] is not None
                    and latest['status'] in {'failed', 'blocked'}):
                targets.append(dict(kind=kind, run_id=latest['run_id'], status=latest['status'], finished_at=latest['finished_at']))
            elif kind=='refresh' and latest:
                from src.scheduler.queued_refresh_recovery import reference
                queued = reference(db,latest['run_id'])
                if queued:
                    targets.append(dict(kind=kind,run_id=latest['run_id'],status='waiting_original',queued_wait=queued))
        revision = control['revision'] + 1
        db.execute("UPDATE account_controls SET state='recovery_requested',recovery_requested_at=?,updated_at=?,revision=? WHERE account_uuid=?",
                   (now, now, revision, account_uuid))
        request_id = uuid.uuid4().hex
        db.execute('''INSERT INTO account_handling_requests(request_id,account_uuid,account_key,handled_by,
            requested_at,control_revision,status,targets_json,policies_json,message) VALUES(?,?,?,?,?,?,?,?,?,?)''',
            (request_id, account_uuid, account_key, actor, now, revision, 'requested',
             json.dumps(targets, ensure_ascii=False), json.dumps(policies, ensure_ascii=False, sort_keys=True), '人工已登记处理完成，等待原身份核验。'))
        return dict(accepted=True, state='recovery_requested', request_id=request_id, requested_at=now,
                    message='已登记处理完成，后台将核验原身份；通过后继续原先明确停止的计划。')


def request_account_recovery(account_uuid, account_key, *, path=DB):
    """Request a single original-identity probe; never activate a binding here."""
    now = time.time()
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        _ensure_control(db, account_uuid, account_key, now)
        control = db.execute('SELECT * FROM account_controls WHERE account_uuid=?', (account_uuid,)).fetchone()
        if control['state'] != 'paused' or control['recovery_token']:
            return False
        db.execute("UPDATE account_controls SET state='recovery_requested',recovery_requested_at=?,updated_at=?,revision=revision+1 WHERE account_uuid=?", (now, now, account_uuid))
        return True


def _unresolved_runs(db, account_uuid):
    from src.scheduler.queued_refresh_recovery import reference
    for table in ('refresh_accounts','smart_accounts','playback_accounts'):
        row=db.execute(f'SELECT run_id FROM {table} WHERE account_uuid=? AND run_id IS NOT NULL',(account_uuid,)).fetchone()
        if row and not (table=='refresh_accounts' and reference(db,row['run_id'])):
            return True
    return False


def _gate(db, account_uuid, account_key, now):
    _ensure_control(db, account_uuid, account_key, now)
    control = db.execute('SELECT * FROM account_controls WHERE account_uuid=?', (account_uuid,)).fetchone()
    if control['account_key'] != account_key:
        _pause(db, account_uuid, account_key, '账号标识与后台控制绑定不一致，需人工核对。', 'account_uuid_mismatch', now)
        return False
    if control['state'] != 'active':
        return False
    from src.scheduler.tracked_refresh_gate import waiting_state
    tracked = waiting_state(db,account_uuid,now)
    if tracked is not None:
        if tracked == 'outcome_unknown':
            _pause(db,account_uuid,account_key,'原浏览器请求结果或执行证据待核对，保留原任务；未重新派发。','outcome_unknown',now)
        return False  # Original browser dispatch/journal owns the current lifetime.
    from src.scheduler.deployment_maintenance import has_active_hold
    if has_active_hold(db, account_uuid):
        return False  # Original queued wait has an audited restart continuation.
    for table, runs in (('refresh_accounts', 'refresh_runs'), ('smart_accounts', 'smart_runs'), ('playback_accounts', 'playback_runs')):
        row = db.execute(f'SELECT * FROM {table} WHERE account_uuid=?', (account_uuid,)).fetchone()
        if row and row['run_id']:
            if row['lease_until'] <= now:
                # A missing terminal receipt is not proof of failure; keep its identity.
                db.execute(f"UPDATE {runs} SET status='outcome_unknown' WHERE run_id=? AND status='running'", (row['run_id'],))
                _pause(db, account_uuid, account_key, '上次运行缺少结束回执，需人工核对原任务；未自动重新派发。', 'outcome_unknown', now)
            return False
    return True


def request_recheck(run_id, reason, path=DB):
    """Append a correction without erasing the original execution result."""
    with connect(path) as db:
        db.execute('INSERT OR REPLACE INTO refresh_run_corrections VALUES(?,?,?)', (run_id, time.time(), reason))
        db.execute('UPDATE refresh_accounts SET next_due=0 WHERE run_id IS NULL AND account_uuid=(SELECT account_uuid FROM refresh_runs WHERE run_id=?)', (run_id,))


def _account_already_paused(db, account_uuid, account_key):
    """Read-only rejection only; every allowed path still uses the atomic gate."""
    row = db.execute('SELECT account_key,state FROM account_controls WHERE account_uuid=?', (account_uuid,)).fetchone()
    return bool(row and row['account_key'] == account_key and row['state'] == 'paused')


def claim(account_uuid, account_key, *, reason='periodic', now=None, path=DB):
    now = time.time() if now is None else now
    with connect(path) as db:
        if _account_already_paused(db, account_uuid, account_key):
            return None
        db.execute('BEGIN IMMEDIATE')
        policy = db.execute('SELECT * FROM refresh_policy').fetchone()
        if not policy['enabled']:
            return None
        if not _gate(db, account_uuid, account_key, now):
            return None
        db.execute('INSERT OR IGNORE INTO refresh_accounts(account_uuid,account_key) VALUES(?,?)', (account_uuid, account_key))
        row = db.execute('SELECT * FROM refresh_accounts WHERE account_uuid=?', (account_uuid,)).fetchone()
        if row['lease_until'] > now or row['next_due'] > now:
            return None
        run_id = uuid.uuid4().hex
        db.execute('UPDATE refresh_accounts SET account_key=?,lease_until=?,run_id=? WHERE account_uuid=?',
                   (account_key, now + LEASE_SECONDS, run_id, account_uuid))
        db.execute('INSERT INTO refresh_runs(run_id,account_uuid,account_key,reason,started_at,status) VALUES(?,?,?,?,?,?)',
                   (run_id, account_uuid, account_key, reason, now, 'running'))
        return run_id


def claim_smart(account_uuid, account_key, *, reason='periodic', now=None, path=DB):
    now = time.time() if now is None else now
    with connect(path) as db:
        if _account_already_paused(db, account_uuid, account_key):
            return None
        db.execute('BEGIN IMMEDIATE')
        policy = db.execute('SELECT * FROM smart_policy').fetchone()
        if not policy['enabled']:
            return None
        if not _gate(db, account_uuid, account_key, now):
            return None
        db.execute('INSERT OR IGNORE INTO smart_accounts(account_uuid,account_key) VALUES(?,?)', (account_uuid, account_key))
        row = db.execute('SELECT * FROM smart_accounts WHERE account_uuid=?', (account_uuid,)).fetchone()
        if row['lease_until'] > now or row['next_due'] > now:
            return None
        run_id = uuid.uuid4().hex
        db.execute('UPDATE smart_accounts SET account_key=?,lease_until=?,run_id=? WHERE account_uuid=?',
                   (account_key, now + LEASE_SECONDS, run_id, account_uuid))
        db.execute('INSERT INTO smart_runs(run_id,account_uuid,account_key,reason,started_at,status) VALUES(?,?,?,?,?,?)',
                   (run_id, account_uuid, account_key, reason, now, 'running'))
        return run_id


def claim_playback(account_uuid, account_key, *, reason='periodic', now=None, path=DB):
    from src.scheduler.account_playback import normalize_options, playback_lease_seconds
    now = time.time() if now is None else now
    with connect(path) as db:
        if _account_already_paused(db, account_uuid, account_key):
            return None
        db.execute('BEGIN IMMEDIATE')
        policy = db.execute('SELECT * FROM playback_policies WHERE account_uuid=? AND account_key=?', (account_uuid, account_key)).fetchone()
        if not policy or not policy['enabled']:
            return None
        if not _gate(db, account_uuid, account_key, now):
            return None
        frozen = _playback_policy_dict(policy,db)
        frozen['options'] = normalize_options(frozen['options'])
        if not frozen['authorization_reference']:
            _pause(db, account_uuid, account_key, '自动播放策略缺少有效授权来源，已拒绝派发。', 'playback_authorization_missing', now)
            return None
        db.execute('INSERT OR IGNORE INTO playback_accounts(account_uuid,account_key) VALUES(?,?)', (account_uuid, account_key))
        row = db.execute('SELECT * FROM playback_accounts WHERE account_uuid=?', (account_uuid,)).fetchone()
        if frozen.get('schedule') and row['run_id'] is None:
            from src.scheduler.playback_random_schedule import next_due
            due = next_due(db, account_uuid, frozen['schedule'], now)
            db.execute('UPDATE playback_accounts SET next_due=? WHERE account_uuid=?', (due, account_uuid))
            row = db.execute('SELECT * FROM playback_accounts WHERE account_uuid=?', (account_uuid,)).fetchone()
        if row['lease_until'] > now or row['next_due'] > now:
            return None
        run_id = uuid.uuid4().hex
        db.execute('UPDATE playback_accounts SET account_key=?,lease_until=?,run_id=? WHERE account_uuid=?',
                   (account_key, now + playback_lease_seconds(frozen['options']['total_minutes']), run_id, account_uuid))
        db.execute('''INSERT INTO playback_runs(run_id,account_uuid,account_key,reason,started_at,status,policy_snapshot)
            VALUES(?,?,?,?,?,?,?)''', (run_id, account_uuid, account_key, reason, now, 'running', json.dumps(frozen, ensure_ascii=False)))
        return run_id


def _prepare_playback_dispatch(run_id, *, now=None, path=DB):
    """Atomically accept this exact configuration for external execution, or cancel it."""
    now = time.time() if now is None else now
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        run = db.execute('SELECT * FROM playback_runs WHERE run_id=?', (run_id,)).fetchone()
        if not run or run['status'] != 'running' or run['dispatched_at'] is not None:
            return None
        control = db.execute('SELECT * FROM account_controls WHERE account_uuid=?', (run['account_uuid'],)).fetchone()
        policy = db.execute('SELECT * FROM playback_policies WHERE account_uuid=? AND account_key=?', (run['account_uuid'], run['account_key'])).fetchone()
        owner = db.execute('SELECT * FROM playback_accounts WHERE account_uuid=?', (run['account_uuid'],)).fetchone()
        frozen = json.loads(run['policy_snapshot'])
        allowed = (control and control['state'] == 'active' and control['account_key'] == run['account_key']
                   and policy and policy['enabled'] and policy['revision'] == frozen['revision']
                   and owner and owner['run_id'] == run_id and owner['lease_until'] > now)
        if not allowed:
            db.execute("UPDATE playback_runs SET status='cancelled',finished_at=?,detail=? WHERE run_id=?",
                       (now, json.dumps({'message': '派发前账号已暂停、策略已停用/变更或租约失效；未启动平台任务。',
                                         'error_code': 'dispatch_admission_changed', 'external_dispatched': False}, ensure_ascii=False), run_id))
            db.execute('UPDATE playback_accounts SET lease_until=0,run_id=NULL WHERE run_id=?', (run_id,))
            return None
        # The actual service must receive the frozen request, never a later UI edit.
        db.execute('UPDATE playback_runs SET dispatched_at=? WHERE run_id=?', (now, run_id))
        return frozen


IMMEDIATE_PAUSE_CODES = frozenset({
    'human_required', 'verification_ui_unconfirmed', 'login_expired', 'login_unhealthy', 'identity_unavailable',
    'identity_mismatch', 'mismatch', 'account_uuid_mismatch', 'browser_environment_mismatch',
    'binding_required', 'account_disabled', 'blocked', 'expired', 'captcha_required',
    'security_verification_required', 'outcome_unknown',
})


def _error_guidance(code):
    if code == 'browser_navigation_timeout':
        return '页面跳转超时，尚未确认可用内容，自动播放已暂停；请检查网络和原页面，验证码或登录失效尚未确认。'
    if code == 'verification_ui_unconfirmed':
        return '验证界面未就绪或读取不明，尚未确认可操作验证码。请在原账号窗口核对页面加载与网络；不要反复提交完成，页面恢复后再申请核验。'
    if code == 'recovery_probe_failed':
        return '原会话核验出现运行异常，尚未确认登录过期。请检查浏览器环境和网络，处理后再申请核验。'
    if code in {'human_required', 'captcha_required', 'security_verification_required'}:
        return '平台要求人工安全验证。请打开原账号浏览器完成验证，再申请恢复探测。'
    if code in {'login_expired', 'expired'}:
        return '页面已明确要求登录。请在原账号浏览器重新登录，再申请恢复探测。'
    if code == 'identity_unavailable':
        return '页面未读取到可确认身份，不能据此判为登录过期。请检查原账号页面，再申请恢复探测。'
    if code in {'identity_mismatch', 'mismatch', 'account_uuid_mismatch', 'browser_environment_mismatch'}:
        return '当前身份或浏览器环境与原绑定不一致。请核对原账号和环境，禁止自动换绑；处理后申请恢复探测。'
    if code in {'login_unhealthy', 'blocked'}:
        return '账号绑定状态受阻，原因尚需核验。请先申请原会话恢复探测，按实际结果处理登录或安全验证。'
    if code == 'binding_required':
        return '该账号缺少已确认的身份绑定，请人工核对账号配置。'
    if code == 'outcome_unknown':
        return '原运行缺少结束回执，需人工核对原任务；没有自动重新派发。'
    return '后台任务连续异常已暂停，请检查本地日志、网络和账号页面，处理后申请恢复探测。'


def _finish(run_id, status, detail, kind, now, path):
    now = time.time() if now is None else now
    runs = f'{kind}_runs'
    accounts = f'{kind}_accounts'
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        run = db.execute(f'SELECT * FROM {runs} WHERE run_id=?', (run_id,)).fetchone()
        if not run or run['status'] not in {'running', 'outcome_unknown', 'waiting_original'}:
            return  # Duplicate/late terminal receipts cannot increment failures or release another lease.
        if kind == 'refresh' and detail.get('error_code') == 'command_wait_timeout':
            from .browser_task_tracking import waiting_before_dispatch
            if waiting_before_dispatch(db,run_id):
                db.execute("UPDATE refresh_runs SET status='waiting_original',detail=? WHERE run_id=?",
                    (json.dumps(dict(detail,error_code='queue_wait_timeout',message='原请求仍未派发，保留原ID等待恢复。'),ensure_ascii=False),run_id))
                _issue(db,run['account_uuid'],run['account_key'],'queue_wait_timeout','原浏览器请求仍在排队，未重复派发。',now)
                return
        if kind == 'playback':
            interval = db.execute('SELECT interval_seconds FROM playback_policies WHERE account_uuid=?', (run['account_uuid'],)).fetchone()[0]
        else:
            interval = db.execute(f'SELECT interval_seconds FROM {kind}_policy').fetchone()[0]
        detail = dict(detail)
        if 'message' in detail:
            detail['message'] = _safe_text(detail['message'])
        error_code = str(detail.get('error_code') or '').lower()
        if not error_code and status == 'blocked':
            error_code = 'blocked'  # Compatibility with older structured blocked results.
        successful = status == 'completed' and not error_code
        skipped = kind == 'playback' and status == 'skipped' and error_code == 'no_playback_candidates' and detail.get('playback_verified_videos') == 0
        cancelled = kind == 'playback' and status == 'cancelled' and not run['dispatched_at']
        delay = interval if successful or skipped or cancelled else min(interval, 1800)
        db.execute(f'UPDATE {runs} SET status=?, finished_at=?, detail=? WHERE run_id=?',
                   (status, now, json.dumps(detail, ensure_ascii=False), run_id))
        due = now + delay
        if kind == 'playback':
            from src.scheduler.playback_random_schedule import read, next_due
            schedule = read(db, run['account_uuid'])
            if schedule is not None:
                due = next_due(db, run['account_uuid'], schedule, now)
        db.execute(f'UPDATE {accounts} SET next_due=?, lease_until=0,run_id=NULL WHERE run_id=?', (due, run_id))
        _ensure_control(db, run['account_uuid'], run['account_key'], now)
        if cancelled:
            return  # A known unsubmitted claim is not a failed account operation.
        if successful or skipped:
            # An in-flight success may reset the error counter, but never unpause an account.
            db.execute('UPDATE account_controls SET consecutive_failures=0 WHERE account_uuid=?', (run['account_uuid'],))
        else:
            db.execute('UPDATE account_controls SET consecutive_failures=consecutive_failures+1 WHERE account_uuid=?', (run['account_uuid'],))
            failures = db.execute('SELECT consecutive_failures FROM account_controls WHERE account_uuid=?', (run['account_uuid'],)).fetchone()[0]
            message = _error_guidance(error_code) if (error_code in IMMEDIATE_PAUSE_CODES or failures >= 3
                or (kind == 'playback' and error_code == 'browser_navigation_timeout')) else '后台任务失败，已保留记录；将在退避间隔后检查。'
            if kind == 'playback' and error_code not in IMMEDIATE_PAUSE_CODES and error_code != 'browser_navigation_timeout':
                message = '自动播放出现异常并已暂停账号，请查看本轮维护记录，人工处理后申请恢复核验。'
            if kind == 'playback' or error_code in IMMEDIATE_PAUSE_CODES or failures >= 3:
                _pause(db, run['account_uuid'], run['account_key'], message,
                       error_code or 'consecutive_failures', now)
            else:
                _issue(db, run['account_uuid'], run['account_key'], error_code or 'transient_failure', message, now)


def finish(run_id, status, detail, *, now=None, path=DB):
    _finish(run_id, status, detail, 'refresh', now, path)


def finish_smart(run_id, status, detail, *, now=None, path=DB):
    _finish(run_id, status, detail, 'smart', now, path)


def finish_playback(run_id, status, detail, *, now=None, path=DB):
    _finish(run_id, status, detail, 'playback', now, path)


def _claim_recovery(account_uuid, account_key, *, now=None, path=DB):
    now = time.time() if now is None else now
    with connect(path) as db:
        existing = db.execute('SELECT state,recovery_token FROM account_controls WHERE account_uuid=?', (account_uuid,)).fetchone()
        if existing is None or (existing['state'] != 'recovery_requested' and not existing['recovery_token']):
            return None
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM account_controls WHERE account_uuid=?', (account_uuid,)).fetchone()
        if row and row['recovery_token'] and row['recovery_lease_until'] <= now:
            if row['error_code'] == 'recovery_outcome_unknown':
                return None
            _pause(db, account_uuid, account_key, '恢复探测缺少结束回执，需人工核对；没有自动重派。', 'recovery_outcome_unknown', now)
            return None
        if not row or row['state'] != 'recovery_requested' or row['recovery_token'] or _unresolved_runs(db, account_uuid):
            return None
        if _pending_manual_window(db, account_uuid):
            return None
        request = db.execute("""SELECT * FROM account_handling_requests WHERE account_uuid=? AND account_key=?
            AND status='requested' ORDER BY requested_at DESC LIMIT 1""", (account_uuid, account_key)).fetchone()
        if request:
            if (row['revision'] != request['control_revision'] or _unknown_outcome_code(row['error_code'])
                    or _handling_policies(db, account_uuid, account_key) != json.loads(request['policies_json'])
                    or not _handling_targets_valid(db, request) or _handling_unresolved(db, account_uuid, now)):
                _invalidate_handling_requests(db, account_uuid, now, '原计划或设置已变化，请核对后重新登记处理完成。')
                db.execute("""UPDATE account_controls SET state='paused',reason=?,error_code='handling_request_invalidated',
                    updated_at=?,revision=revision+1 WHERE account_uuid=? AND state='recovery_requested'""",
                    ('原计划或设置已变化，请核对后重新登记处理完成。', now, account_uuid))
                return None
        token = uuid.uuid4().hex
        db.execute("UPDATE account_controls SET state='recovering',recovery_token=?,recovery_lease_until=?,updated_at=? WHERE account_uuid=?",
                   (token, now + LEASE_SECONDS, now, account_uuid))
        if request:
            db.execute("UPDATE account_handling_requests SET status='probing',probe_token=?,message=? WHERE request_id=?",
                       (token, '正在核验原账号身份，尚未恢复业务运行。', request['request_id']))
        return token


def _finish_recovery(account_uuid, account_key, token, *, healthy, status, diagnostic='', path=DB):
    now = time.time()
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM account_controls WHERE account_uuid=?', (account_uuid,)).fetchone()
        if not row or row['recovery_token'] != token:
            return False  # An operator pause while probing invalidates this result.
        request = db.execute('''SELECT * FROM account_handling_requests WHERE account_uuid=? AND account_key=?
            AND probe_token=? ORDER BY requested_at DESC LIMIT 1''', (account_uuid, account_key, token)).fetchone()
        if row['state'] != 'recovering':
            # Preserve a pause issued during this probe; the receipt only settles its lease.
            db.execute('UPDATE account_controls SET recovery_token=NULL,recovery_lease_until=0 WHERE account_uuid=? AND recovery_token=?', (account_uuid, token))
            return False
        if request and (request['status'] != 'probing' or request['control_revision'] != row['revision']
                or _unknown_outcome_code(row['error_code'])
                or _handling_policies(db, account_uuid, account_key) != json.loads(request['policies_json'])
                or not _handling_targets_valid(db, request)):
            _invalidate_handling_requests(db, account_uuid, now, '原控制版本、计划或设置已变化，本次完成请求失效。')
            db.execute("""UPDATE account_controls SET state='paused',reason=?,error_code='handling_request_invalidated',
                updated_at=?,revision=revision+1 WHERE account_uuid=? AND state='recovering'""",
                ('原控制版本、计划或设置已变化，本次完成请求失效。', now, account_uuid))
            db.execute('UPDATE account_controls SET recovery_token=NULL,recovery_lease_until=0 WHERE account_uuid=?', (account_uuid,))
            return False
        if healthy and status == 'active' and _pending_manual_window(db, account_uuid):
            _invalidate_handling_requests(db, account_uuid, now, '人工窗口任务尚未确认结束，本次核验不能恢复业务。')
            db.execute("""UPDATE account_controls SET state='paused',reason=?,error_code='manual_window_pending',
                recovery_token=NULL,recovery_lease_until=0,recovery_requested_at=NULL,updated_at=?,revision=revision+1
                WHERE account_uuid=?""", ('人工窗口任务尚未确认结束，请先核对原窗口任务。', now, account_uuid))
            return False
        if healthy and status == 'active' and not _unresolved_runs(db, account_uuid):
            if request:
                if _handling_unresolved(db, account_uuid, now):
                    _invalidate_handling_requests(db, account_uuid, now, '发现原运行未决，未继续业务。')
                    db.execute('UPDATE account_controls SET recovery_token=NULL,recovery_lease_until=0 WHERE account_uuid=?', (account_uuid,))
                    return False
                for target in json.loads(request['targets_json']):
                    db.execute(f"UPDATE {target['kind']}_accounts SET next_due=MIN(next_due,?) WHERE account_uuid=? AND account_key=? AND run_id IS NULL",
                               (now, account_uuid, account_key))
                db.execute("UPDATE account_handling_requests SET status='completed',finished_at=?,message=? WHERE request_id=?",
                           (now, '原身份核验通过，原先明确失败的计划已安排下次扫描继续。', request['request_id']))
            db.execute("UPDATE account_controls SET state='active',reason='',error_code='',consecutive_failures=0,updated_at=?,recovery_requested_at=NULL,recovery_lease_until=0,recovery_token=NULL,revision=revision+1 WHERE account_uuid=?", (now, account_uuid))
            db.execute("UPDATE account_issues SET status='resolved',updated_at=? WHERE account_uuid=? AND status='open'", (now, account_uuid))
            return True
        db.execute('UPDATE account_controls SET recovery_token=NULL,recovery_lease_until=0 WHERE account_uuid=?', (account_uuid,))
        reason = _error_guidance(status)
        if diagnostic:
            reason += ' 诊断：' + _safe_text(diagnostic)
        if request:
            db.execute("UPDATE account_handling_requests SET status='failed',finished_at=?,message=? WHERE request_id=?",
                       (now, _safe_text(reason), request['request_id']))
        _pause(db, account_uuid, account_key, reason, status or 'recovery_probe_failed', now)
        return False


def recover_requested_accounts(*, path=DB, requested_only=False):
    # Normal scans and the fast human-completion lane share the same claim/lease.
    # A busy probe is never duplicated or waited on by another scanner.
    if not _RECOVERY_SCAN_LOCK.acquire(blocking=False):
        return
    try:
        return _recover_requested_accounts(path=path, requested_only=requested_only)
    finally:
        _RECOVERY_SCAN_LOCK.release()


def handling_poll_seconds(*, path=DB):
    """Read-only UI cadence; no initialization or recovery dispatch."""
    target = Path(path).resolve()
    if not target.exists():
        return 15
    try:
        db = sqlite3.connect(target.as_uri()+'?mode=ro', uri=True, timeout=1)
        try:
            pending = db.execute("SELECT 1 FROM account_handling_requests WHERE status IN ('requested','probing') LIMIT 1").fetchone()
        finally:
            db.close()
        return 2 if pending else 15
    except sqlite3.Error:
        return 15


def _recover_requested_accounts(*, path, requested_only):
    from src.scheduler.handling_fast_lane import pending_controls, probe_controls
    if requested_only:
        # Only existing, explicitly registered human-completion requests. This
        # path never creates startup rechecks, refresh, playback or publication.
        controls = pending_controls(path)
    else:
        from src.scheduler.account_startup_recheck import request_rechecks
        request_rechecks(path=path)
        controls = snapshot(path)['controls']
    probe_controls(controls,path=path,claim=_claim_recovery,finish=_finish_recovery,exception_code=_exception_code)


def _exception_code(exc):
    code = str(getattr(exc, 'code', '') or '')
    return code if re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,63}', code) else 'unexpected_error'


def _smart_error_code(report, account_key=None):
    code = report.get('error_code')
    if code and (str(code) in IMMEDIATE_PAUSE_CODES or _unknown_outcome_code(str(code))):
        return str(code)
    # Report status can be completed while maintenance still requires a human challenge.
    # Read only a matching local maintenance receipt, and only its structured code.
    log = report.get('maintenance_log')
    if log:
        try:
            receipt = json.loads(Path(log).read_text(encoding='utf-8'))
            if (receipt.get('run_id') == report.get('maintenance_run_id')
                    and (account_key is None or receipt.get('account_key') == account_key)):
                receipt_code = str(receipt.get('error_code') or '')
                if receipt_code in IMMEDIATE_PAUSE_CODES or _unknown_outcome_code(receipt_code):
                    return receipt_code
                # A later creator-sync error is still the maintenance failure,
                # but must not erase a search verification block for scheduling.
                detection = (receipt.get('blocked_search') or {}).get('detection')
                if detection in {'visible_challenge', 'verification_ui_unconfirmed',
                                 'security_text_without_results'}:
                    evidence = receipt.get('challenge_evidence') or {}
                    return ('human_required' if detection == 'visible_challenge'
                        and evidence.get('blocking') is True
                        and evidence.get('surface_state') == 'challenge_ready'
                        and evidence.get('confirmations', 0) >= 2
                        else 'verification_ui_unconfirmed')
                return receipt_code
        except (OSError, ValueError, TypeError):
            pass
    if code:
        return str(code)
    maintenance_status = str(report.get('maintenance_status') or '')
    return 'blocked' if maintenance_status == 'blocked' else ''


def refresh_due_accounts(*, reason='periodic', path=DB):
    from src.operations_accounts import AccountProfileRepository, AccountBindingRepository
    from src.operations_accounts.maintenance import AccountMaintenanceService
    update_service_status('account_refresh', 'running', message='正在检查账号后台计划', path=path)
    from .browser_task_tracking import reconcile
    reconcile(path)
    recover_requested_accounts(path=path)
    profiles = AccountProfileRepository()
    bindings = AccountBindingRepository(profiles.db_path)
    for profile in profiles.list_active():
        try:
            _refresh_one_account(profile, bindings, AccountMaintenanceService, reason=reason, path=path)
        except Exception as exc:
            # Infrastructure/receipt errors for one account must not hide other accounts.
            with connect(path) as db:
                db.execute('BEGIN IMMEDIATE')
                _pause(db, profile.account_uuid, profile.account_key,
                       '后台账号处理异常，请人工核对本地日志和原运行记录。', _exception_code(exc), time.time())
    update_service_status('account_refresh', 'healthy', message='本轮账号计划检查完成', path=path)


def _refresh_one_account(profile, bindings, maintenance_service, *, reason, path):
        binding = bindings.get_optional(profile.account_key)
        if binding is None:
            return  # An unbound strategy profile is not a configured platform account.
        if getattr(binding, 'status', 'active') != 'active':
            # Surface a pre-existing unhealthy binding immediately, even if its
            # business schedule is not due. Only a requested probe may inspect it.
            with connect(path) as db:
                db.execute('BEGIN IMMEDIATE')
                _ensure_control(db, profile.account_uuid, profile.account_key, time.time())
                current = db.execute('SELECT state FROM account_controls WHERE account_uuid=?', (profile.account_uuid,)).fetchone()[0]
                if current == 'active':
                    _pause(db, profile.account_uuid, profile.account_key,
                           '历史账号绑定状态受阻，请先探测原会话并核验身份；按实际结果处理登录或安全验证。',
                           'login_unhealthy', time.time())
            return
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
                    error_code=_smart_error_code(report, profile.account_key),
                ), path=path)
            except Exception as exc:
                finish_smart(smart_run_id, 'failed', {
                    'message': '智能运营异常，请查看账号维护日志',
                    'error_type': type(exc).__name__,
                    'error_code': _exception_code(exc),
                }, path=path)

        run_id = claim(profile.account_uuid, profile.account_key, reason=reason, path=path)
        if run_id is None:
            return
        if smart_completed_backend_sync:
            finish(run_id, 'completed', {
                'message': '本轮智能运营已同时完成作品后台数据同步。',
                'videos': 0,
                'comments': 0,
                'comment_failures': 0,
                'login_healthy': True,
                'smart_run_id': smart_run_id,
            }, path=path)
            return
        try:
            from .browser_task_tracking import tracking
            with tracking(run_id,path):
                result = maintenance_service().run(profile.account_key, 'post-publish', headless=True)
            finish(run_id, result.status, dict(message=result.message, maintenance_run_id=result.run_id,
                videos=result.synced_videos, comments=result.synced_comments,
                comment_failures=result.comment_sync_failures,
                login_healthy=result.login_healthy, error_code=getattr(result, 'error_code', '')), path=path)
        except Exception as exc:
            # Do not copy arbitrary exception payloads (which might contain auth data).
            finish(run_id, 'failed', {'message': '同步异常，请查看账号维护日志', 'error_type': type(exc).__name__, 'error_code': _exception_code(exc)}, path=path)
