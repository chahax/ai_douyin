"""Persistent, account-bound manual-window jobs; workers never call Streamlit."""
from contextlib import contextmanager
import logging
import os
from pathlib import Path
import re
import sqlite3
import stat
import threading
import time
import uuid

DB = Path(__file__).resolve().parents[2] / 'data/account_manual_windows.db'
_PID = os.getpid()
_SESSION_NONCE = uuid.uuid4().hex
_registry_lock = threading.RLock()
_registry = {}
_KNOWN_STATES = frozenset({'starting', 'running', 'outcome_unknown', 'closed', 'failed'})
_KEY = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z')
_UUID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z')
_PHASES = frozenset({'validating', 'preparing', 'acquiring', 'starting_browser', 'window_open_waiting_close', 'closed'})
_ERROR_CODES = frozenset({'locked', 'cooldown', 'circuit_open', 'daily_quota_exceeded', 'account_disabled',
    'binding_required', 'account_uuid_mismatch', 'browser_environment_mismatch', 'identity_mismatch',
    'identity_unavailable', 'human_required', 'login_expired', 'login_unhealthy', 'manual_window_not_opened',
    'browser_start_timeout', 'browser_environment_in_use', 'browser_unavailable'})
_PUBLIC_COLUMNS = ('job_id', 'account_uuid', 'account_key', 'requested_by', 'state', 'phase',
                   'error_code', 'error_type', 'created_at', 'updated_at', 'finished_at')
logger = logging.getLogger(__name__)


def _identity(account_uuid, account_key):
    if (not isinstance(account_uuid, str) or not _UUID.fullmatch(account_uuid)
            or not isinstance(account_key, str) or not _KEY.fullmatch(account_key)):
        raise ValueError('人工窗口任务需要一致的原账号UUID和账号标识')


def _db_exists(path):
    try:
        metadata = Path(path).stat()
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(metadata.st_mode):
        raise sqlite3.DatabaseError('人工窗口状态路径不是数据库文件')
    return True


def _error_type(exc):
    name = type(exc).__name__
    return name if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}', name) else 'Exception'


@contextmanager
def _connection(path, *, create=False):
    target = Path(path).resolve()
    if create:
        target.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(target, timeout=2)
    else:
        db = sqlite3.connect(target.as_uri() + '?mode=ro', uri=True, timeout=1)
    db.row_factory = sqlite3.Row
    try:
        if create:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {'manual_window_accounts', 'manual_window_jobs'} <= tables:
                fresh_schema = not tables
                db.executescript('''BEGIN IMMEDIATE;
                    CREATE TABLE IF NOT EXISTS manual_window_accounts(
                        account_uuid TEXT PRIMARY KEY, account_key TEXT NOT NULL UNIQUE);
                    CREATE TABLE IF NOT EXISTS manual_window_jobs(
                        job_id TEXT PRIMARY KEY, account_uuid TEXT NOT NULL, account_key TEXT NOT NULL,
                        requested_by TEXT NOT NULL, state TEXT NOT NULL, phase TEXT NOT NULL,
                        owner_pid INTEGER NOT NULL, owner_nonce TEXT NOT NULL,
                        created_at REAL NOT NULL, updated_at REAL NOT NULL, finished_at REAL,
                        error_code TEXT NOT NULL DEFAULT '', error_type TEXT NOT NULL DEFAULT '');
                    CREATE INDEX IF NOT EXISTS manual_window_job_account
                        ON manual_window_jobs(account_uuid,created_at DESC);
                    COMMIT;''')
                if fresh_schema:
                    # Only the first, empty-store initialization changes mode.
                    # Existing jobs/stores and every normal/RO connection stay untouched.
                    mode = str(db.execute('PRAGMA journal_mode=WAL').fetchone()[0]).lower()
                    if mode != 'wal':
                        raise sqlite3.DatabaseError('新人工窗口状态库的WAL初始化未确认生效')
        yield db
        if create:
            db.commit()
    except BaseException:
        if create:
            db.rollback()
        raise
    finally:
        db.close()


def _bound_account(db, account_uuid, account_key):
    row = db.execute('SELECT account_uuid,account_key FROM manual_window_accounts WHERE account_uuid=? OR account_key=?',
                     (account_uuid, account_key)).fetchone()
    if row and (row['account_uuid'] != account_uuid or row['account_key'] != account_key):
        raise ValueError('人工窗口任务与原账号身份绑定不一致')


def _owner_process_running(owner_pid):
    if os.name != 'nt':
        try:
            os.kill(owner_pid, 0)
        except ProcessLookupError:
            return False
        except OSError:
            return True  # Unknown/access denied never permits replacement.
        return True
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.OpenProcess(0x1000, False, owner_pid)
    if not handle:
        return ctypes.get_last_error() != 87  # Invalid PID is known absent.
    try:
        code = wintypes.DWORD()
        return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
    finally:
        kernel.CloseHandle(handle)


def _orphaned(row):
    if row['state'] not in _KNOWN_STATES:
        return True
    if row['state'] not in {'starting', 'running'}:
        return False
    if row['owner_pid'] != _PID:
        # On Windows os.kill(pid, 0) can terminate a process; query only.
        return not _owner_process_running(row['owner_pid'])
    if row['owner_nonce'] != _SESSION_NONCE:
        return True
    with _registry_lock:
        thread = _registry.get(row['job_id'])
        return thread is None or not thread.is_alive()


def _public(row, *, project_orphan=True):
    result = {name: row[name] for name in _PUBLIC_COLUMNS}
    if project_orphan and _orphaned(row):
        result.update(state='outcome_unknown', phase='outcome_unknown', error_code='worker_outcome_unknown', error_type='')
    return result


def get_manual_window_job(account_uuid, account_key, *, path=DB):
    """Pure read: no DB creation, platform access, job launch or orphan writeback."""
    _identity(account_uuid, account_key)
    from src.operations_accounts.browser_control_runtime import enabled
    if enabled():
        from .browser_control_runtime import manual_window_snapshot
        current = manual_window_snapshot(account_uuid, account_key)
        if current is not None:
            return current
    if not _db_exists(path):
        return None
    with _connection(path) as db:
        _bound_account(db, account_uuid, account_key)
        row = db.execute('SELECT * FROM manual_window_jobs WHERE account_uuid=? AND account_key=? ORDER BY created_at DESC,rowid DESC LIMIT 1',
                         (account_uuid, account_key)).fetchone()
        return _public(row) if row else None


def has_pending_manual_window_job(account_uuid, account_key, *, path=DB, _legacy_only=False):
    """Pure RO gate; malformed or unreadable state raises instead of allowing recovery."""
    _identity(account_uuid, account_key)
    if not _db_exists(path):
        return False
    with _connection(path) as db:
        _bound_account(db, account_uuid, account_key)
        return db.execute("""SELECT 1 FROM manual_window_jobs WHERE account_uuid=? AND account_key=?
            AND state NOT IN ('closed','failed') LIMIT 1""", (account_uuid, account_key)).fetchone() is not None


def _write_phase(job_id, phase, path):
    if phase not in _PHASES:
        return
    with _connection(path, create=True) as db:
        db.execute('''UPDATE manual_window_jobs SET phase=?,state=CASE WHEN ?='window_open_waiting_close'
            THEN 'running' ELSE state END,updated_at=? WHERE job_id=? AND owner_pid=? AND owner_nonce=?
            AND state IN ('starting','running')''', ('closing' if phase == 'closed' else phase, phase, time.time(), job_id, _PID, _SESSION_NONCE))
    logger.info('manual_window_job job=%s phase=%s', job_id, 'closing' if phase == 'closed' else phase)


def _terminal(job_id, state, error_code, error_type, path):
    now = time.time()
    with _connection(path, create=True) as db:
        db.execute('''UPDATE manual_window_jobs SET state=?,phase=?,error_code=?,error_type=?,updated_at=?,finished_at=?
            WHERE job_id=? AND owner_pid=? AND owner_nonce=? AND state IN ('starting','running','outcome_unknown')''',
            (state, state, error_code, error_type, now, now, job_id, _PID, _SESSION_NONCE))
    logger.info('manual_window_job job=%s phase=%s error_type=%s', job_id, state, error_type)


def _worker(job_id, account_uuid, account_key, runtime, path, before_open=None):
    try:
        if before_open is not None and not before_open():
            _terminal(job_id, 'failed', 'incident_no_longer_actionable', '', path)
            return
        # All platform and identity work stays in the existing shared helper.
        from src.operations_accounts.manual_handling import open_bound_manual_handling_window
        result = open_bound_manual_handling_window(account_uuid, account_key, runtime=runtime,
            on_progress=lambda phase: _write_phase(job_id, phase, path))
        if getattr(result, 'closed', None) is True:
            _terminal(job_id, 'closed', '', '', path)
        else:
            _terminal(job_id, 'outcome_unknown', 'manual_window_result_unknown', '', path)
    except BaseException as exc:
        error_type = _error_type(exc)
        code = getattr(exc, 'code', '')
        error_code = code if isinstance(code, str) and code in _ERROR_CODES else ('manual_window_timeout' if isinstance(exc, TimeoutError) or error_type == 'TimeoutError' else 'manual_window_failed')
        try:
            _terminal(job_id, 'failed', error_code, error_type, path)
        except Exception as record_error:
            logger.error('manual_window_job terminal_not_saved job=%s error_type=%s', job_id, _error_type(record_error))
    finally:
        with _registry_lock:
            _registry.pop(job_id, None)


def get_incident_window_job(incident_id, account_uuid, account_key, *, path=DB):
    """Read-only durable once-per-incident lookup, including closed/failed jobs."""
    _identity(account_uuid, account_key)
    from src.operations_accounts.browser_control_runtime import enabled
    if enabled():
        from .browser_control_runtime import manual_window_snapshot
        current = manual_window_snapshot(account_uuid, account_key, incident_id=incident_id)
        if current is not None:
            return current
    if not _db_exists(path):
        return None
    with _connection(path) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='manual_window_incidents'").fetchone():
            return None
        mapping = db.execute('SELECT * FROM manual_window_incidents WHERE incident_id=?', (incident_id,)).fetchone()
        if mapping is None:
            return None
        if mapping['account_uuid'] != account_uuid or mapping['account_key'] != account_key:
            raise ValueError('异常窗口记录归属不一致')
        row = db.execute('SELECT * FROM manual_window_jobs WHERE job_id=?', (mapping['job_id'],)).fetchone()
        if row is None or row['account_uuid'] != account_uuid or row['account_key'] != account_key:
            raise ValueError('异常原窗口任务缺失或归属不一致')
        return _public(row)


def start_manual_window_job(account_uuid, account_key, requested_by, *, runtime=None, path=DB,
                            incident_id=None, incident_created_at=None, before_open=None):
    """Admin click or validated system incident; active/unknown jobs are never relaunched."""
    _identity(account_uuid, account_key)
    from src.operations_accounts.browser_control_runtime import enabled
    if enabled():
        from .browser_control_runtime import queue_manual_window
        if incident_id is not None and (not callable(before_open) or not before_open()):
            raise ValueError('异常已非当前可处理事件，未登记新窗口')
        return queue_manual_window(account_uuid, account_key, requested_by, incident_id=incident_id)
    if incident_id is not None:
        import math
        if (not isinstance(incident_id, int) or isinstance(incident_id, bool) or incident_id <= 0
                or not isinstance(incident_created_at, (int, float)) or isinstance(incident_created_at, bool)
                or not math.isfinite(incident_created_at) or incident_created_at < 0 or not callable(before_open)):
            raise ValueError('自动窗口需要明确异常编号、发生时间及当前状态核对')
    if not isinstance(requested_by, str) or not requested_by.strip() or len(requested_by) > 200:
        raise ValueError('人工窗口任务必须记录已登录的实际操作者')
    if re.search(r'(?i)(cookie\s*[:=]|authorization\s*[:=]|bearer\s|password\s*[:=]|https?://)', requested_by):
        raise ValueError('操作者标识不得包含认证内容')
    path = Path(path).resolve()
    with _registry_lock:
        with _connection(path, create=True) as db:
            db.execute('BEGIN IMMEDIATE')
            _bound_account(db, account_uuid, account_key)
            db.execute('INSERT OR IGNORE INTO manual_window_accounts VALUES(?,?)', (account_uuid, account_key))
            if incident_id is not None:
                db.execute('''CREATE TABLE IF NOT EXISTS manual_window_incidents(
                    incident_id INTEGER PRIMARY KEY, account_uuid TEXT NOT NULL,
                    account_key TEXT NOT NULL, job_id TEXT NOT NULL, created_at REAL NOT NULL)''')
                original = db.execute('SELECT * FROM manual_window_incidents WHERE incident_id=?', (incident_id,)).fetchone()
                if original is not None:
                    if original['account_uuid'] != account_uuid or original['account_key'] != account_key:
                        raise ValueError('异常窗口记录归属不一致')
                    previous = db.execute('SELECT * FROM manual_window_jobs WHERE job_id=?', (original['job_id'],)).fetchone()
                    if previous is None or previous['account_uuid'] != account_uuid or previous['account_key'] != account_key:
                        raise ValueError('异常原窗口任务缺失或归属不一致')
                    return dict(_public(previous), reused=True)
            row = db.execute("""SELECT * FROM manual_window_jobs WHERE account_uuid=? AND account_key=?
                AND state NOT IN ('closed','failed') ORDER BY created_at DESC,rowid DESC LIMIT 1""",
                (account_uuid, account_key)).fetchone()
            if row is None and incident_id is not None:
                # A human may already have opened and closed this incident's window.
                row = db.execute('''SELECT * FROM manual_window_jobs WHERE account_uuid=? AND account_key=?
                    AND created_at>=? ORDER BY created_at DESC,rowid DESC LIMIT 1''',
                    (account_uuid, account_key, incident_created_at)).fetchone()
            if row:
                if _orphaned(row):
                    db.execute("UPDATE manual_window_jobs SET state='outcome_unknown',phase='outcome_unknown',error_code='worker_outcome_unknown',updated_at=? WHERE job_id=?",
                               (time.time(), row['job_id']))
                    row = db.execute('SELECT * FROM manual_window_jobs WHERE job_id=?', (row['job_id'],)).fetchone()
                if incident_id is not None:
                    db.execute('INSERT INTO manual_window_incidents VALUES(?,?,?,?,?)',
                        (incident_id, account_uuid, account_key, row['job_id'], time.time()))
                return dict(_public(row), reused=True)
            job_id = uuid.uuid4().hex
            now = time.time()
            db.execute('''INSERT INTO manual_window_jobs(job_id,account_uuid,account_key,requested_by,state,phase,
                owner_pid,owner_nonce,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)''',
                (job_id, account_uuid, account_key, requested_by.strip(), 'starting', 'validating', _PID, _SESSION_NONCE, now, now))
            if incident_id is not None:
                db.execute('INSERT INTO manual_window_incidents VALUES(?,?,?,?,?)',
                    (incident_id, account_uuid, account_key, job_id, now))
            accepted = db.execute('SELECT * FROM manual_window_jobs WHERE job_id=?', (job_id,)).fetchone()
        # The job transaction is closed before any worker calls the account/runtime DBs.
        try:
            thread = threading.Thread(target=_worker, args=(job_id, account_uuid, account_key, runtime, path, before_open),
                                      daemon=True, name='ManualWindow-' + job_id[:8])
            _registry[job_id] = thread
            thread.start()
        except Exception as exc:
            _registry.pop(job_id, None)
            _terminal(job_id, 'failed', 'worker_start_failed', _error_type(exc), path)
            with _connection(path) as db:
                row = db.execute('SELECT * FROM manual_window_jobs WHERE job_id=?', (job_id,)).fetchone()
                return dict(_public(row), reused=False)
        # Acknowledge the committed request, not a racing worker's progress.
        # Subsequent RO polling provides the current phase and terminal result.
        return dict(_public(accepted, project_orphan=False), reused=False)
