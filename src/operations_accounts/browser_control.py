"""Durable browser ownership and serial, cooperative account commands.

This database does not replace operation leases, publication claims or quotas.
An expired owner is unknown, never an invitation to launch another profile.
Only the owner thread touches business handlers and the browser context.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import logging
from pathlib import Path
import sqlite3
import threading
import time
import uuid
from typing import Any, Callable


_METADATA_LOCKS_GUARD = threading.Lock()
_METADATA_LOCKS: dict[str, Any] = {}
logger = logging.getLogger(__name__)


def _publication_locator_policy_ready(command, owner_id, generation):
    """Only explicitly registered publications require this optional provider."""
    if command['kind'] not in {'publish', 'publication_verify'}:
        return True
    target = (command['command_id'] if command['kind'] == 'publish'
              else command['payload'].get('original_command_id'))
    if not isinstance(target, str) or not target or Path(target).name != target:
        return True
    directory = Path(__file__).resolve().parents[2] / 'data/publication_locator_provider_v1/policies'
    if not any((directory / (target + suffix)).exists() for suffix in ('.json', '.required.json')):
        return True
    try:
        from .publication_locator_provider_v1 import provider_ready
        return provider_ready(command, owner_id, generation) is True
    except Exception:
        return False


def _sqlite_contention(exc):
    code = getattr(exc, "sqlite_errorcode", None)
    return (isinstance(exc, sqlite3.Error) and isinstance(code, int)
            and code & 0xFF in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED})


def _metadata_lock(path: Path):
    # Independent Store objects in UI/host code share one short connection
    # fence. Readers remain mode=ro, but do not starve this process's rollback
    # journal commits. SQLite retains cross-process transaction exclusion.
    key = str(path).casefold()
    with _METADATA_LOCKS_GUARD:
        return _METADATA_LOCKS.setdefault(key, threading.RLock())


class BrowserControlError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class BrowserControlRejected(BrowserControlError):
    """Known rejection before an external effect, not a transport failure."""


class BrowserControlSuspended(BrowserControlError):
    """The current saved stack must not continue after a nested stop."""


class BrowserControlDeferred(BrowserControlError):
    """Admission waits for human/other safety gates; business has not run."""


@dataclass(frozen=True)
class BrowserCommandResult:
    state: str = "succeeded"
    result: dict | None = None


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _required(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ValueError(f"{field} must be a nonempty stable identifier")
    return value


class BrowserControlStore:
    """Dedicated SQLite state; construction is explicit schema initialization."""

    def __init__(self, path: str | Path, *, clock: Callable[[], float] = time.time, owner_ttl: float = 90):
        if owner_ttl <= 0:
            raise ValueError("owner_ttl must be positive")
        self.path = Path(path).resolve()
        self.clock = clock
        self.owner_ttl = float(owner_ttl)
        self._connection_lock = _metadata_lock(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            # Web snapshots must not acquire a write lock merely to build their
            # store object. Existing schema is inspected through a read-only URI.
            with self._db() as db:
                tables = {row[0] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('browser_control_owners','browser_control_commands')")}
                expected = {
                    "browser_control_owners": {"account_id", "binding_version", "owner_id", "generation", "state", "heartbeat", "updated_at"},
                    "browser_control_commands": {"command_id", "account_id", "binding_version", "kind", "idempotency_key", "payload", "request_sha", "priority", "state", "owner_id", "generation", "cursor", "result", "error_code", "created_at", "updated_at"},
                }
                if tables != set(expected) or any(
                    {row[1] for row in db.execute(f"PRAGMA table_info({name})")} != columns
                    for name, columns in expected.items()
                ):
                    raise BrowserControlError("schema_incompatible", "Existing control database is incomplete or incompatible; explicit offline reconciliation required")
                for name, primary_key in (("browser_control_owners", "account_id"), ("browser_control_commands", "command_id")):
                    columns = db.execute(f"PRAGMA table_info({name})").fetchall()
                    primary = [(row[1], row[5]) for row in columns if row[5]]
                    if primary != [(primary_key, 1)]:
                        raise BrowserControlError("schema_incompatible", "Existing control database lacks owner or command uniqueness")
                    numeric = {"generation": "INTEGER", "priority": "INTEGER", "heartbeat": "REAL", "created_at": "REAL", "updated_at": "REAL"}
                    if any(row[2].upper() != numeric.get(row[1], "TEXT") for row in columns):
                        raise BrowserControlError("schema_incompatible", "Existing control database column types differ from the supported schema")
                unique_sets = []
                for index in db.execute("PRAGMA index_list(browser_control_commands)").fetchall():
                    if index[2]:
                        # SQLite-generated names are data; quote the identifier.
                        quoted = '"' + index[1].replace('"', '""') + '"'
                        unique_sets.append(tuple(row[2] for row in db.execute(f"PRAGMA index_info({quoted})")))
                if ("account_id", "idempotency_key") not in unique_sets:
                    raise BrowserControlError("schema_incompatible", "Existing control database lacks immutable idempotency constraint")
            return
        with self._db(write=True) as db:
            db.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS browser_control_owners (
                    account_id TEXT PRIMARY KEY, binding_version TEXT NOT NULL,
                    owner_id TEXT NOT NULL, generation INTEGER NOT NULL,
                    state TEXT NOT NULL, heartbeat REAL NOT NULL, updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS browser_control_commands (
                    command_id TEXT PRIMARY KEY, account_id TEXT NOT NULL,
                    binding_version TEXT NOT NULL, kind TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL, payload TEXT NOT NULL,
                    request_sha TEXT NOT NULL, priority INTEGER NOT NULL,
                    state TEXT NOT NULL, owner_id TEXT, generation INTEGER,
                    cursor TEXT, result TEXT, error_code TEXT,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    UNIQUE(account_id,idempotency_key)
                );
                CREATE INDEX IF NOT EXISTS browser_control_queue
                    ON browser_control_commands(account_id,state,priority DESC,created_at);
                COMMIT;
            """)

    @contextmanager
    def _db(self, *, write: bool = False):
        # No per-connection journal-mode mutation, no production database use.
        with self._connection_lock:
            if write:
                db = sqlite3.connect(str(self.path), timeout=2, isolation_level=None)
            else:
                db = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=2, isolation_level=None)
            db.row_factory = sqlite3.Row
            try:
                if write:
                    db.execute("BEGIN IMMEDIATE")
                yield db
                if write and db.in_transaction:
                    db.commit()
            except BaseException:
                if write and db.in_transaction:
                    db.rollback()
                raise
            finally:
                db.close()

    @staticmethod
    def _command(row) -> dict | None:
        if row is None:
            return None
        item = dict(row)
        for key in ("payload", "cursor", "result"):
            if item[key] is not None:
                item[key] = json.loads(item[key])
        item["task_id"] = item["command_id"]
        return item

    def submit(self, account_id: str, binding_version: str, kind: str,
               idempotency_key: str, payload: dict, priority: int = 0) -> dict:
        for value, name in ((account_id, "account_id"), (binding_version, "binding_version"),
                            (kind, "kind"), (idempotency_key, "idempotency_key")):
            _required(value, name)
        if not isinstance(payload, dict) or type(priority) is not int:
            raise ValueError("payload must be an object; priority must be an integer")
        body = _json(payload)
        request_sha = hashlib.sha256(_json([account_id, binding_version, kind, payload, priority]).encode()).hexdigest()
        now = self.clock()
        with self._db(write=True) as db:
            previous = db.execute("SELECT * FROM browser_control_commands WHERE account_id=? AND idempotency_key=?",
                                  (account_id, idempotency_key)).fetchone()
            if previous:
                if previous["request_sha"] != request_sha:
                    raise BrowserControlRejected("idempotency_conflict", "Idempotency key has a different immutable request")
                return self._command(previous)
            command_id = uuid.uuid4().hex
            db.execute("""INSERT INTO browser_control_commands
                (command_id,account_id,binding_version,kind,idempotency_key,payload,request_sha,priority,state,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (command_id, account_id, binding_version, kind, idempotency_key, body, request_sha, priority, "queued", now, now))
            return self._command(db.execute("SELECT * FROM browser_control_commands WHERE command_id=?", (command_id,)).fetchone())

    def get(self, command_id: str) -> dict | None:
        with self._db() as db:
            return self._command(db.execute("SELECT * FROM browser_control_commands WHERE command_id=?", (command_id,)).fetchone())

    def cancel_queued(self, command_id, expected_snapshot_sha256, reason, requested_by):
        """Cancel exactly one not-yet-dispatched request; never interrupt work."""
        _required(reason, 'reason')
        _required(requested_by, 'requested_by')
        with self._db(write=True) as db:
            row = db.execute('SELECT * FROM browser_control_commands WHERE command_id=?', (command_id,)).fetchone()
            if not row or row['state'] != 'queued':
                raise BrowserControlRejected('command_not_queued', 'Only a request still queued before dispatch can be cancelled')
            before = self._command(row)
            actual_sha = hashlib.sha256(_json(before).encode('utf-8')).hexdigest()
            if actual_sha != expected_snapshot_sha256:
                raise BrowserControlRejected('command_changed', 'Queued request changed before cancellation')
            now = self.clock()
            result = {'cancelled_before_dispatch': True, 'requested_by': requested_by,
                'reason': reason, 'cancelled_at': now, 'before_snapshot_sha256': actual_sha,
                'before_error_code': before['error_code'], 'before_result': before['result'],
                'platform_submission_started': False}
            db.execute("UPDATE browser_control_commands SET state='failed',error_code='operator_cancelled_before_dispatch',result=?,updated_at=? WHERE command_id=?",
                       (_json(result), now, command_id))
            return self._command(db.execute('SELECT * FROM browser_control_commands WHERE command_id=?', (command_id,)).fetchone())

    def operator_cancel_unknown_manual(self, command_id, owner_id, generation, *,
            expected_snapshot_sha256, reason, requested_by, authorization):
        """Explicit human cancellation; preserves uncertainty, never redispatches."""
        _required(reason, 'reason')
        _required(requested_by, 'requested_by')
        # This is cancellation evidence, not permission to infer a known result.
        root = Path(__file__).resolve().parents[2]
        if not isinstance(authorization, dict) or set(authorization) != {'path', 'sha256'}:
            raise BrowserControlRejected('cancellation_authorization_invalid', 'Frozen explicit cancellation evidence required')
        path = Path(authorization['path']).resolve()
        if not path.is_relative_to(root):
            raise BrowserControlRejected('cancellation_authorization_invalid', 'Cancellation evidence must be in this project')
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != authorization['sha256']:
            raise BrowserControlRejected('cancellation_authorization_invalid', 'Cancellation evidence changed')
        decision = json.loads(body)
        if (not isinstance(decision, dict) or decision.get('decision_source') != 'explicit_user_statement'
                or not isinstance(decision.get('user_statement'), str)
                or not decision['user_statement'].strip()
                or decision.get('command_id', decision.get('cancel_manual_command_id')) != command_id):
            raise BrowserControlRejected('cancellation_authorization_invalid', 'Explicit statement and original manual ID required')
        with self._db(write=True) as db:
            row = db.execute('SELECT * FROM browser_control_commands WHERE command_id=?', (command_id,)).fetchone()
            if not row or row['kind'] != 'manual' or row['state'] != 'outcome_unknown':
                raise BrowserControlRejected('manual_not_unknown', 'Only the exact unknown manual command can be cancelled')
            if row['owner_id'] != owner_id or row['generation'] != generation:
                raise BrowserControlRejected('command_fenced', 'Original manual owner/generation differs')
            self._owner(db, row['account_id'], owner_id, generation, row['binding_version'])
            if decision.get('account_uuid') != row['account_id']:
                raise BrowserControlRejected('cancellation_authorization_invalid', 'Cancellation account differs')
            before = self._command(row)
            actual_sha = hashlib.sha256(_json(before).encode('utf-8')).hexdigest()
            if actual_sha != expected_snapshot_sha256:
                raise BrowserControlRejected('command_changed', 'Unknown manual command changed before cancellation')
            result = {'operator_cancelled_unknown_manual': True, 'original_outcome_known': False,
                'requested_by': requested_by, 'reason': reason, 'cancelled_at': self.clock(),
                'authorization': {'path': str(path), 'sha256': authorization['sha256']},
                'before_snapshot_sha256': actual_sha, 'before_snapshot': before}
            db.execute("UPDATE browser_control_commands SET state='failed',error_code='operator_cancelled_unknown_manual',result=?,updated_at=? WHERE command_id=?",
                (_json(result), self.clock(), command_id))
            return self._command(db.execute('SELECT * FROM browser_control_commands WHERE command_id=?', (command_id,)).fetchone())

    def operator_close_unknown_publication(self, command_id, owner_id, generation, *,
            expected_snapshot_sha256, authorization, reason, requested_by):
        """Human disposal of one unknown publication, never a known-failure claim."""
        _required(reason, 'reason')
        _required(requested_by, 'requested_by')
        from .publication_unknown_closure import validate_closure_authorization
        with self._db(write=True) as db:
            row = db.execute('SELECT * FROM browser_control_commands WHERE command_id=?', (command_id,)).fetchone()
            if not row or row['kind'] != 'publish' or row['state'] != 'outcome_unknown':
                raise BrowserControlRejected('publication_not_unknown', 'Only the exact unknown publication can be human-closed')
            if row['owner_id'] != owner_id or row['generation'] != generation:
                raise BrowserControlRejected('command_fenced', 'Original publication owner/generation differs')
            self._owner(db, row['account_id'], owner_id, generation, row['binding_version'])
            before = self._command(row)
            actual_sha = hashlib.sha256(_json(before).encode('utf-8')).hexdigest()
            if actual_sha != expected_snapshot_sha256:
                raise BrowserControlRejected('command_changed', 'Unknown publication changed before human closure')
            validate_closure_authorization(before, authorization)
            result = {'operator_closed_external_outcome_unknown': True, 'original_outcome_known': False,
                'reason': reason, 'requested_by': requested_by, 'closed_at': self.clock(),
                'authorization': dict(authorization), 'before_snapshot_sha256': actual_sha,
                'before_snapshot': before}
            db.execute("UPDATE browser_control_commands SET state='failed',error_code='operator_closed_external_outcome_unknown',result=?,updated_at=? WHERE command_id=?",
                (_json(result), self.clock(), command_id))
            return self._command(db.execute('SELECT * FROM browser_control_commands WHERE command_id=?', (command_id,)).fetchone())

    def operator_abandon_unknown_publication(self, plan, *, requested_by, runtime):
        """Explicit business-target abandonment; retain unknown/platform claims."""
        from .publication_abandonment_v1 import apply
        return apply(self, plan, requested_by=requested_by, runtime=runtime)

    def list_pending_accounts(self) -> list[str]:
        with self._db() as db:
            projection = (" UNION SELECT account_id FROM publication_verified_work_outbox WHERE state='pending'"
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='publication_verified_work_outbox'").fetchone() else '')
            return [row[0] for row in db.execute("""SELECT account_id FROM browser_control_commands
                WHERE state IN ('queued','running','paused','waiting_human','outcome_unknown')
                UNION SELECT account_id FROM browser_control_owners WHERE state!='released'"""
                + projection + ' ORDER BY account_id')]

    def complete_waiting(self, command_id, owner_id, generation, result=None):
        """Record known window closure; this does not prove login or resume."""
        with self._db(write=True) as db:
            row = db.execute("SELECT * FROM browser_control_commands WHERE command_id=?", (command_id,)).fetchone()
            if not row or row["owner_id"] != owner_id or row["generation"] != generation or row["state"] != "waiting_human":
                raise BrowserControlRejected("command_fenced", "Waiting command is not held by this owner")
            self._owner(db, row["account_id"], owner_id, generation, row["binding_version"])
            db.execute("UPDATE browser_control_commands SET state='succeeded',result=?,updated_at=? WHERE command_id=?",
                       (_json(result or {}), self.clock(), command_id))
            return self._command(db.execute("SELECT * FROM browser_control_commands WHERE command_id=?", (command_id,)).fetchone())

    def operational_snapshot(self, account_id: str) -> dict:
        """Bounded UI view without historical payloads or large result blobs."""
        with self._db() as db:
            owner = db.execute('SELECT * FROM browser_control_owners WHERE account_id=?', (account_id,)).fetchone()
            commands = [dict(r) for r in db.execute('''SELECT command_id,kind,state,error_code,
                updated_at,created_at,cursor IS NOT NULL AS has_cursor FROM browser_control_commands
                WHERE account_id=? ORDER BY CASE WHEN state IN ('succeeded','failed') THEN 1 ELSE 0 END,
                updated_at DESC LIMIT 100''', (account_id,))]
            from .browser_execution_journal import exists
            journal_available = exists(db)
            for command in commands:
                stage = db.execute('SELECT phase,next_retry_at FROM browser_control_execution WHERE command_id=?',
                                   (command['command_id'],)).fetchone() if journal_available else None
                command.update(dict(stage) if stage else {'phase': 'legacy_unrecorded', 'next_retry_at': 0})
            return {'account_id': account_id, 'owner': dict(owner) if owner else None, 'commands': commands}

    def commands_of_kind(self, account_id: str, kind: str) -> list[dict]:
        """Window polling must not deserialize unrelated publication receipts."""
        with self._db() as db:
            return [self._command(row) for row in db.execute(
                "SELECT * FROM browser_control_commands WHERE account_id=? AND kind=? "
                "ORDER BY priority DESC,created_at,command_id", (account_id, kind))]

    def manual_status_snapshot(self, account_id: str) -> dict:
        """One RO transaction: original manual rows and their current owner only."""
        with self._db() as db:
            db.execute('BEGIN')
            owner = db.execute('SELECT * FROM browser_control_owners WHERE account_id=?',
                               (account_id,)).fetchone()
            commands = [self._command(row) for row in db.execute(
                "SELECT * FROM browser_control_commands WHERE account_id=? AND kind='manual' "
                "ORDER BY created_at,command_id", (account_id,))]
        return {'owner': dict(owner) if owner else None, 'commands': commands}

    def snapshot(self, account_id: str) -> dict:
        """Read-only even for a stale owner; never tests caller PID equality."""
        with self._db() as db:
            row = db.execute("SELECT * FROM browser_control_owners WHERE account_id=?", (account_id,)).fetchone()
            owner = dict(row) if row else None
            commands = [self._command(r) for r in db.execute(
                "SELECT * FROM browser_control_commands WHERE account_id=? ORDER BY priority DESC,created_at,command_id", (account_id,))]
        if owner:
            owner["persisted_state"] = owner["state"]
            owner["heartbeat_expired"] = self.clock() - owner["heartbeat"] > self.owner_ttl
            if owner["state"] == "active" and owner["heartbeat_expired"]:
                owner["state"] = "outcome_unknown"
        return {"account_id": account_id, "owner": owner, "commands": commands}

    def acquire_owner(self, account_id: str, binding_version: str, owner_id: str) -> dict:
        for value, field in ((account_id, "account_id"), (binding_version, "binding_version"), (owner_id, "owner_id")):
            _required(value, field)
        now = self.clock()
        with self._db(write=True) as db:
            row = db.execute("SELECT * FROM browser_control_owners WHERE account_id=?", (account_id,)).fetchone()
            if row and row["state"] != "released":
                # Even the same owner cannot reacquire an existing generation after
                # process restart. Live objects retain their generation directly.
                raise BrowserControlRejected("owner_busy_or_unknown", "Existing browser owner requires original-owner reconciliation")
            from .publication_autonomous_reconciliation import unresolved as reconciliation_unresolved
            unresolved = reconciliation_unresolved(self,db,account_id,('running','paused','outcome_unknown'))
            if unresolved:
                raise BrowserControlRejected("command_unresolved", "Original command outcome is unresolved")
            generation = int(row["generation"]) + 1 if row else 1
            db.execute("""INSERT INTO browser_control_owners VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(account_id) DO UPDATE SET binding_version=excluded.binding_version,
                owner_id=excluded.owner_id,generation=excluded.generation,state=excluded.state,
                heartbeat=excluded.heartbeat,updated_at=excluded.updated_at""",
                (account_id, binding_version, owner_id, generation, "active", now, now))
            return dict(db.execute("SELECT * FROM browser_control_owners WHERE account_id=?", (account_id,)).fetchone())

    def handoff_publication_reconciliation(self, *, owner_id, generation, authorization,
            expected_snapshot_sha256, retirement_evidence, connection):
        from .publication_reconciliation_authorization import handoff
        return handoff(self, owner_id=owner_id, generation=generation, authorization=authorization,
            expected_snapshot_sha256=expected_snapshot_sha256, retirement_evidence=retirement_evidence, connection=connection)

    def acquire_reconciliation_owner(self, account_id, binding_version, owner_id, authorization):
        from . import publication_autonomous_reconciliation as autonomous
        if autonomous.is_v2(authorization):
            return autonomous.acquire_owner(self,account_id,binding_version,owner_id,authorization)
        from .publication_reconciliation_authorization import acquire_owner
        return acquire_owner(self,account_id,binding_version,owner_id,authorization)

    def handoff_publication_reconciliation_v2(self, *, owner_id, generation, authorization,
            expected_snapshots_sha256, retirement_evidence, connection):
        from .publication_autonomous_reconciliation import handoff
        return handoff(self,owner_id=owner_id,generation=generation,authorization=authorization,
            expected_snapshots_sha256=expected_snapshots_sha256,retirement_evidence=retirement_evidence,connection=connection)

    def pending_reconciliation_authorization(self, account_id):
        from .publication_reconciliation_authorization import handoff_row
        with self._db() as db:
            from .publication_autonomous_reconciliation import row as autonomous_row
            newer=autonomous_row(db,account_id,include_retirement=False)
            if newer and newer['resolution'] is not None:return None
            if newer and newer['new_owner_id'] is None:return json.loads(newer['authorization'])
            row=handoff_row(db,account_id)
            return json.loads(row['authorization']) if row and row['new_owner_id'] is None else None

    def resolve_publication_reconciliation(self, reconciliation_id, owner_id, generation, result):
        from . import publication_autonomous_reconciliation as autonomous
        command=self.get(reconciliation_id)
        if command and autonomous.is_v2(command['payload'].get('reconciliation_authorization')):
            return autonomous.resolve(self,reconciliation_id,owner_id,generation,result)
        from .publication_reconciliation_authorization import resolve
        return resolve(self,reconciliation_id,owner_id,generation,result)

    def queue_publication_comment_settlement(self, reference, binding_version, *, attempt=None):
        from .publication_comment_settlement_control import queue
        return queue(self,reference,binding_version,attempt)

    def _owner(self, db, account_id, owner_id, generation, binding_version=None):
        row = db.execute("SELECT * FROM browser_control_owners WHERE account_id=?", (account_id,)).fetchone()
        if not row or row["owner_id"] != owner_id or row["generation"] != generation:
            raise BrowserControlRejected("owner_fenced", "Browser owner generation does not match")
        if row["state"] != "active" or self.clock() - row["heartbeat"] > self.owner_ttl:
            raise BrowserControlRejected("owner_unknown", "Browser owner is no longer demonstrably live")
        if binding_version is not None and row["binding_version"] != binding_version:
            raise BrowserControlRejected("binding_changed", "Browser owner binding version differs")
        return row

    def heartbeat(self, account_id: str, owner_id: str, generation: int) -> None:
        with self._db(write=True) as db:
            self._owner(db, account_id, owner_id, generation)
            now = self.clock()
            db.execute("UPDATE browser_control_owners SET heartbeat=?,updated_at=? WHERE account_id=?", (now, now, account_id))

    def mark_owner_unknown(self, account_id, owner_id, generation):
        with self._db(write=True) as db:
            db.execute("UPDATE browser_control_owners SET state='outcome_unknown',updated_at=? WHERE account_id=? AND owner_id=? AND generation=? AND state='active'",
                       (self.clock(), account_id, owner_id, generation))

    def release_owner(self, account_id: str, owner_id: str, generation: int) -> None:
        with self._db(write=True) as db:
            self._owner(db, account_id, owner_id, generation)
            from .publication_autonomous_reconciliation import unresolved as reconciliation_unresolved
            unresolved = reconciliation_unresolved(self,db,account_id,('running','paused','outcome_unknown','waiting_human'))
            if unresolved:
                raise BrowserControlRejected("command_unresolved", "Browser cannot be released with an unresolved command")
            db.execute("UPDATE browser_control_owners SET state='released',updated_at=? WHERE account_id=?", (self.clock(), account_id))

    def claim_next(self, account_id, binding_version, owner_id, generation, *, above_priority=None, kinds=None, parent_command_id=None):
        with self._db(write=True) as db:
            self._owner(db, account_id, owner_id, generation, binding_version)
            from . import publication_autonomous_reconciliation as autonomous
            newer=autonomous.row(db,account_id,include_retirement=False)
            if newer and newer['resolution'] is None and newer['new_owner_id']==owner_id and newer['new_generation']==generation:
                from .publication_comment_settlement_control import claim as claim_comment_settlement
                readonly=claim_comment_settlement(self,db,account_id,binding_version,owner_id,generation) if parent_command_id is None else None
                if readonly:return readonly
                return autonomous.claim(self,db,account_id,binding_version,owner_id,generation) if parent_command_id is None else None
            from .publication_reconciliation_authorization import handoff_row, claim
            reconciliation=handoff_row(db,account_id)
            if reconciliation and reconciliation['resolution'] is None and reconciliation['new_owner_id']==owner_id and reconciliation['new_generation']==generation:
                return claim(self,db,account_id,binding_version,owner_id,generation) if parent_command_id is None else None
            if autonomous.unresolved(self,db,account_id,('outcome_unknown',)):
                if parent_command_id is None and above_priority is None:
                    from .publication_verification_recovery import claim as claim_verification
                    return claim_verification(self,db,account_id,binding_version,owner_id,generation,
                        allowed_kinds=kinds)
                return None
            blocking = db.execute("SELECT command_id,state FROM browser_control_commands WHERE account_id=? AND state IN ('running','paused')", (account_id,)).fetchall()
            recovery_only = False
            if any(row[0] != parent_command_id for row in blocking):
                # Known paused background may receive explicit human/recovery
                # work, but cannot be restarted or bypassed by fresh business.
                if parent_command_id is None and all(row[1] == "paused" for row in blocking):
                    recovery_only = True
                else:
                    return None
            query = "SELECT * FROM browser_control_commands WHERE account_id=? AND state='queued'"
            args = [account_id]
            from . import browser_execution_journal as execution
            if execution.exists(db):
                query += " AND NOT EXISTS (SELECT 1 FROM browser_control_execution e WHERE e.command_id=browser_control_commands.command_id AND e.next_retry_at>?)"
                args.append(self.clock())
            if recovery_only:
                query += " AND kind IN ('manual','recovery')"
            if above_priority is not None:
                query += " AND priority>?"
                args.append(above_priority)
            if kinds is not None:
                if not kinds:
                    return None
                query += " AND kind IN (" + ",".join("?" for _ in kinds) + ")"
                args.extend(kinds)
            row = db.execute(query + " ORDER BY priority DESC,created_at,command_id LIMIT 1", args).fetchone()
            if not row:
                return None
            # Bindings are immutable per request. A changed identity never runs it.
            if row["binding_version"] != binding_version:
                db.execute("UPDATE browser_control_commands SET state='failed',error_code='binding_changed',updated_at=? WHERE command_id=?", (self.clock(), row["command_id"]))
                return self._command(db.execute("SELECT * FROM browser_control_commands WHERE command_id=?", (row["command_id"],)).fetchone())
            if not _publication_locator_policy_ready(self._command(row), owner_id, generation):
                return None
            db.execute("UPDATE browser_control_commands SET state='running',owner_id=?,generation=?,updated_at=? WHERE command_id=?",
                       (owner_id, generation, self.clock(), row["command_id"]))
            claimed = self._command(db.execute("SELECT * FROM browser_control_commands WHERE command_id=?", (row['command_id'],)).fetchone())
            execution.record(db, claimed, 'admission_pending', self.clock())
            db.execute("UPDATE browser_control_commands SET error_code=NULL WHERE command_id=?", (row['command_id'],))
            return self._command(db.execute("SELECT * FROM browser_control_commands WHERE command_id=?", (row["command_id"],)).fetchone())

    def transition(self, command_id, owner_id, generation, state, *, cursor=None, result=None, error_code=None,
                   expected_snapshot_sha256=None):
        if state not in {"queued", "running", "paused", "succeeded", "failed", "waiting_human", "outcome_unknown"}:
            raise ValueError("Invalid command state")
        with self._db(write=True) as db:
            row = db.execute("SELECT * FROM browser_control_commands WHERE command_id=?", (command_id,)).fetchone()
            if not row or row["owner_id"] != owner_id or row["generation"] != generation:
                raise BrowserControlRejected("command_fenced", "Command is not owned by this generation")
            if expected_snapshot_sha256 is not None:
                observed = hashlib.sha256(_json(self._command(row)).encode('utf-8')).hexdigest()
                if observed != expected_snapshot_sha256:
                    raise BrowserControlRejected("command_changed", "Command changed after evidence reconciliation")
            if row["state"] not in {"running", "paused"}:
                # Read-only recovery commits both original and verifier in one
                # transaction. Finalizing that exact receipt is idempotent.
                if (row['kind'] == 'publication_verify' and row['state'] == state == 'succeeded'
                        and result is not None and row['result'] == _json(result)):
                    self._owner(db,row['account_id'],owner_id,generation,row['binding_version'])
                    return self._command(row)
                raise BrowserControlRejected("command_terminal", "An existing command cannot be re-executed")
            # Unknown/paused may still be saved after a heartbeat failure, but no
            # successful result or resume can be recorded by a stale owner.
            if state not in {"outcome_unknown", "paused"}:
                self._owner(db, row["account_id"], owner_id, generation, row["binding_version"])
            from .browser_execution_journal import finish
            finish(db, self._command(row), state, error_code, self.clock())
            db.execute("UPDATE browser_control_commands SET state=?,cursor=COALESCE(?,cursor),result=?,error_code=?,updated_at=? WHERE command_id=?",
                       (state, _json(cursor) if cursor is not None else None,
                        _json(result) if result is not None else None, error_code, self.clock(), command_id))
            if state == "queued":
                db.execute("UPDATE browser_control_commands SET owner_id=NULL,generation=NULL WHERE command_id=?", (command_id,))
            return self._command(db.execute("SELECT * FROM browser_control_commands WHERE command_id=?", (command_id,)).fetchone())


@dataclass
class BrowserTaskContext:
    actor: "BrowserControlActor"
    command: dict
    resource: Any = None
    suspension_reason: str | None = None

    @property
    def task_id(self):
        return self.command["command_id"]

    @property
    def account_id(self):
        return self.command["account_id"]

    @property
    def binding_version(self):
        return self.command["binding_version"]

    def safe_point(self, cursor: dict) -> float:
        return self.actor.safe_point(cursor)

    def check_dispatch(self) -> None:
        """Recheck binding, authorization and pause gates immediately before IO."""
        self.actor._assert_thread()
        if self.suspension_reason:
            raise BrowserControlSuspended(self.suspension_reason, "Saved background command remains suspended")
        self.actor._admit(self, "dispatch")


class BrowserControlActor:
    """One live owner; handlers and nested priority work run on one thread.

    Heartbeat thread only writes control metadata. It never touches browser or
    business leases. A failed/unknown nested command pauses the background stack;
    no restart re-enters a handler from an arbitrary saved cursor.
    """
    PRIORITY_KINDS = ("publish", "publish_verify", "comment")

    def __init__(self, store: BrowserControlStore, account_id: str, binding_version: str,
                 owner_id: str, handlers: dict[str, Callable], admission: Callable | None = None,
                 context=None, heartbeat_seconds: float = 30, owner_acquirer=None):
        if not 0 < heartbeat_seconds < store.owner_ttl:
            raise ValueError("heartbeat interval must be below owner TTL")
        self.store, self.account_id = store, account_id
        self.binding_version, self.owner_id = binding_version, owner_id
        self.handlers, self.admission, self.context = dict(handlers), admission, context
        self.heartbeat_seconds = heartbeat_seconds
        self.owner_acquirer = owner_acquirer
        self.generation = None
        self._thread_id = None
        self._stack: list[BrowserTaskContext] = []
        self._stop = threading.Event()
        self._heartbeat_thread = None
        self._heartbeat_error = None

    def start(self):
        if self.generation is not None:
            self._assert_thread()
            self._check_owner(renew=True)
            return self
        acquire=self.owner_acquirer or self.store.acquire_owner
        owner = acquire(self.account_id, self.binding_version, self.owner_id)
        self.generation = owner["generation"]
        self._thread_id = threading.get_ident()
        self._heartbeat_thread = threading.Thread(target=self._heartbeats, daemon=True, name="account-browser-heartbeat")
        self._heartbeat_thread.start()
        return self

    def _heartbeats(self):
        while not self._stop.wait(self.heartbeat_seconds):
            try:
                self.store.heartbeat(self.account_id, self.owner_id, self.generation)
            except BaseException as exc:
                if _sqlite_contention(exc):
                    # No task replay and no lease extension is fabricated.
                    # The next normal heartbeat must still satisfy owner TTL.
                    logger.warning("Browser owner heartbeat deferred by SQLite contention")
                    continue
                self._heartbeat_error = type(exc).__name__
                try:
                    self.store.mark_owner_unknown(self.account_id, self.owner_id, self.generation)
                except Exception:
                    pass
                return

    def _assert_thread(self):
        if threading.get_ident() != self._thread_id:
            raise BrowserControlRejected("wrong_thread", "Browser tasks must run on the owner thread")

    def _check_owner(self, *, renew=False):
        if self._heartbeat_error:
            raise BrowserControlRejected("owner_unknown", "Owner heartbeat could not be maintained")
        if renew:
            self.store.heartbeat(self.account_id, self.owner_id, self.generation)
        else:
            # Every browser read/click checks fencing, but need not commit a
            # heartbeat. The independent heartbeat thread renews the lease.
            with self.store._db() as db:
                self.store._owner(db, self.account_id, self.owner_id, self.generation, self.binding_version)

    def _admit(self, ctx, phase):
        self._check_owner()
        if self.admission is not None:
            if self.admission(ctx, phase) is False:
                raise BrowserControlRejected("admission_rejected", "Account identity or safety gate rejected command")

    def run_next(self):
        try:
            self.start()
            self._assert_thread()
            if self._stack:
                raise BrowserControlRejected("already_running", "Use safe_point for nested priority work")
            command = self.store.claim_next(self.account_id, self.binding_version, self.owner_id, self.generation)
        except sqlite3.Error as exc:
            if not _sqlite_contention(exc):
                raise
            # Store transactions have rolled back. No handler has started.
            # Leave the original queue and owner unchanged for the next poll.
            logger.warning("Browser dispatch deferred before handler by SQLite contention")
            return None
        # Handler/finalization errors are intentionally outside this boundary:
        # uncertainty after external work must never turn into an idle retry.
        return self._execute(command) if command else None

    def _execute(self, command):
        if command["state"] != "running":
            return command
        ctx = BrowserTaskContext(self, command, self.context)
        self._stack.append(ctx)
        state, result, error = "outcome_unknown", None, None
        handler_started = False
        try:
            self._admit(ctx, "start")
            handler = self.handlers.get(command["kind"])
            if handler is None:
                raise BrowserControlRejected("handler_missing", "No handler registered for this command")
            from .browser_execution_journal import before_handler
            before_handler(self.store, command['command_id'], self.owner_id, self.generation)
            handler_started = True
            outcome = handler(ctx, command["payload"])
            self._check_owner()
            if isinstance(outcome, BrowserCommandResult):
                if outcome.state not in {"succeeded", "failed", "waiting_human", "outcome_unknown"}:
                    raise ValueError("Invalid handler outcome state")
                state, result = outcome.state, outcome.result
            elif isinstance(outcome, dict):
                state, result = "succeeded", outcome
            else:
                raise ValueError("Handler must return a dictionary or BrowserCommandResult")
        except BrowserControlSuspended as exc:
            state, error = "paused", exc.code
        except BrowserControlDeferred as exc:
            state, error = ("outcome_unknown" if handler_started else "queued"), exc.code
        except BrowserControlRejected as exc:
            # A heartbeat/fencing rejection after a handler started is not proof
            # that its external request failed. Preserve uncertainty.
            state = "outcome_unknown" if exc.code in {"owner_unknown", "owner_fenced"} else "failed"
            error = exc.code
        except BaseException as exc:
            error = "handler_exception:" + type(exc).__name__
            # Diagnostic facts only: preserve the original unknown outcome gate.
            # Do not save exception strings, which may contain private payloads.
            result = {"failure_phase": "handler" if handler_started else "admission",
                      "handler_started": handler_started, "error_type": type(exc).__name__}
            from src.shared.exception_diagnostics import exception_causes
            causes = exception_causes(exc)
            if causes:
                result["exception_causes"] = causes
        finally:
            self._stack.pop()
        # Legacy services may catch Exception around their entire loop. A caught
        # suspension must never be laundered into successful handler completion.
        if ctx.suspension_reason:
            state, error = "paused", ctx.suspension_reason
        try:
            return self.store.transition(command["command_id"], self.owner_id, self.generation,
                                         state, result=result, error_code=error)
        except BrowserControlRejected:
            # Save the external uncertainty, never turn a stale response into a
            # successful command. Fencing still protects a different command.
            return self.store.transition(command["command_id"], self.owner_id, self.generation,
                                         "outcome_unknown", error_code="owner_unknown")

    def safe_point(self, cursor: dict) -> float:
        self._assert_thread()
        if not self._stack or not isinstance(cursor, dict):
            raise BrowserControlRejected("invalid_safe_point", "Safe points require a running handler and durable cursor")
        ctx = self._stack[-1]
        if ctx.suspension_reason:
            raise BrowserControlSuspended(ctx.suspension_reason, "Original saved background command is suspended")
        started = time.monotonic()
        self.store.transition(ctx.task_id, self.owner_id, self.generation, "paused", cursor=cursor)
        try:
            self._check_owner()
            while True:
                command = self.store.claim_next(self.account_id, self.binding_version, self.owner_id, self.generation,
                                                above_priority=ctx.command["priority"], kinds=self.PRIORITY_KINDS,
                                                parent_command_id=ctx.task_id)
                if command is None:
                    break
                outcome = self._execute(command)
                if outcome["state"] != "succeeded":
                    raise BrowserControlSuspended("priority_task_stopped", "Background remains paused after priority command did not succeed")
            # Recheck original binding, pause and unknown gates after publication.
            self._admit(ctx, "resume")
            self.store.transition(ctx.task_id, self.owner_id, self.generation, "running", cursor=cursor)
            return time.monotonic() - started
        except BrowserControlSuspended as exc:
            ctx.suspension_reason = exc.code
            raise
        except BaseException as exc:
            ctx.suspension_reason = "resume_gate_rejected"
            raise BrowserControlSuspended("resume_gate_rejected", "Background checkpoint saved; resume was not approved") from exc

    def close(self):
        self._assert_thread()
        if self._stack:
            raise BrowserControlRejected("already_running", "Cannot close while a handler is executing")
        self.store.release_owner(self.account_id, self.owner_id, self.generation)
        self._stop.set()
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=2)

    def stop_heartbeat(self):
        """Process shutdown only: retains owner and commands for reconciliation."""
        self._stop.set()
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=2)
