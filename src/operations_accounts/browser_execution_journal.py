"""Transactional execution evidence; missing evidence never permits replay."""
from .browser_control import _json, BrowserControlRejected

TABLE = 'browser_control_execution'


def exists(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)).fetchone() is not None


def initialize(db):
    # Called inside the first dispatch transaction, never by read-only snapshots.
    if exists(db):
        return
    db.execute('''CREATE TABLE browser_control_execution(
        command_id TEXT PRIMARY KEY, request_sha TEXT NOT NULL,
        owner_id TEXT NOT NULL, generation INTEGER NOT NULL,
        phase TEXT NOT NULL, handler_entered INTEGER NOT NULL,
        next_retry_at REAL NOT NULL, updated_at REAL NOT NULL)''')
    db.execute('''CREATE TABLE browser_control_execution_events(
        event_id INTEGER PRIMARY KEY, command_id TEXT NOT NULL,
        evidence TEXT NOT NULL, recorded_at REAL NOT NULL)''')


def record(db, command, phase, now, *, entered=False, retry_at=0):
    initialize(db)
    previous = db.execute('SELECT * FROM browser_control_execution WHERE command_id=?', (command['command_id'],)).fetchone()
    if phase == 'admission_pending' and previous and previous['handler_entered']:
        raise BrowserControlRejected('execution_already_started', 'Durable handler evidence forbids replay')
    entered = bool(entered or (previous and previous['handler_entered']))
    values = (command['command_id'], command['request_sha'], command['owner_id'], command['generation'],
              phase, int(entered), retry_at, now)
    db.execute('INSERT OR REPLACE INTO browser_control_execution VALUES(?,?,?,?,?,?,?,?)', values)
    db.execute('INSERT INTO browser_control_execution_events(command_id,evidence,recorded_at) VALUES(?,?,?)',
               (command['command_id'], _json(dict(zip(('command_id','request_sha','owner_id','generation',
                   'phase','handler_entered','next_retry_at','updated_at'), values), prior_error=command.get('error_code'))), now))


def before_handler(store, command_id, owner_id, generation):
    # Commit this BEFORE invoking any handler (including a special reconciliation).
    with store._db(write=True) as db:
        command = store._command(db.execute('SELECT * FROM browser_control_commands WHERE command_id=?', (command_id,)).fetchone())
        if not command or command['state'] != 'running' or command['owner_id'] != owner_id or command['generation'] != generation:
            raise BrowserControlRejected('command_fenced', 'Handler entry lost ownership')
        store._owner(db, command['account_id'], owner_id, generation, command['binding_version'])
        record(db, command, 'handler_entered', store.clock(), entered=True)


def finish(db, command, state, error_code, now):
    # A legacy running task must not gain fabricated pre-execution evidence.
    if not exists(db):
        return
    old = db.execute('SELECT * FROM browser_control_execution WHERE command_id=?', (command['command_id'],)).fetchone()
    if not old:
        return
    # Human completion and a cleared circuit should take effect immediately.
    # Only quota exhaustion is time-polled; cap the wait at the next UTC day.
    retry_at = min(now + 300, (int(now // 86400) + 1) * 86400) if state == 'queued' and error_code == 'daily_quota_exceeded' else 0
    record(db, command, 'admission_wait' if state == 'queued' else state, now, retry_at=retry_at)
