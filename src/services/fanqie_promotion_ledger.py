"""Versioned extension of the existing P0 ledger, never a second job database.

Construction is read-only. Migration is explicit, additive and backed up first.
State lives in fanqie_bindings; immutable events live in fanqie_operation_events.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid

from .fanqie_backfill_workflow import BackfillBlocked, digest, file_sha, validate_workbook


VERSION = "fanqie_backfill_ledger/2"
REQUIRED = {
    "fanqie_books": {"id", "fanqie_book_id"},
    "fanqie_promotion_tasks": {"id", "task_uuid", "book_id", "platform_task_id", "promotion_alias", "publish_type"},
    "fanqie_publish_records": {"id", "task_id", "douyin_video_id", "douyin_video_url"},
    "fanqie_bindings": {"id", "binding_uuid", "task_id", "publish_id", "status", "attempt_count", "submitted_url", "field_contract_json", "idempotency_key", "created_at"},
    "fanqie_operation_events": {"event_uuid", "task_id", "event_type", "from_status", "to_status", "actor_type", "actor_id", "payload_json", "created_at", "audit_artifact_hash"},
}
EXTENSIONS = {
    "fanqie_backfill_contracts": {"binding_uuid", "business_key", "post_id", "manifest_json", "manifest_sha", "contract_json", "authorization_json", "revision", "batch_id", "created_at"},
    "fanqie_dispatch_outbox": {"binding_uuid", "dispatch_key", "account_id", "binding_version", "payload_json", "command_id", "created_at"},
}


def _unique_columns(db, table):
    values = set()
    for row in db.execute(f"PRAGMA index_list({table})").fetchall():
        if row[2] and not row[4]:  # partial unique indexes cannot fence all intents
            index = '"' + row[1].replace('"', '""') + '"'
            values.add(tuple(x[2] for x in db.execute(f"PRAGMA index_info({index})")))
    return values


def _extensions(db):
    for table, columns in EXTENSIONS.items():
        if {r[1] for r in db.execute(f"PRAGMA table_info({table})")} != columns:
            raise BackfillBlocked("ledger_extension_schema_incompatible")
    for table, keys in {
        "fanqie_backfill_contracts": {("binding_uuid",), ("business_key",), ("post_id",)},
        "fanqie_dispatch_outbox": {("binding_uuid",), ("dispatch_key",), ("command_id",)},
    }.items():
        if not keys <= _unique_columns(db, table):
            raise BackfillBlocked("ledger_unique_constraints_missing")
TRANSITIONS = {
    "prepared": {"ready"}, "ready": {"upload_started", "confirmed"},
    "upload_started": {"uploaded", "outcome_unknown"},
    "uploaded": {"submit_started", "failed_known", "outcome_unknown"},
    "submit_started": {"accepted", "verify_pending", "confirmed", "outcome_unknown"},
    "accepted": {"verify_pending", "confirmed", "failed_known", "outcome_unknown"},
    "verify_pending": {"verify_pending", "confirmed", "failed_known", "outcome_unknown"},
    "outcome_unknown": {"confirmed"},
}


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _schema(db):
    for table, needed in REQUIRED.items():
        cols = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
        if not needed <= cols:
            raise BackfillBlocked("closed_loop_schema_incompatible:" + table)


def migrate_ledger(path, backup_path):
    """Explicit offline migration. Existing rows and old schema are untouched."""
    path, backup = Path(path).resolve(), Path(backup_path).resolve()
    if not path.is_file() or backup.exists() or path == backup:
        raise BackfillBlocked("migration_requires_existing_source_and_new_backup")
    backup.parent.mkdir(parents=True, exist_ok=True)
    # No implicit creation of a missing source; backup uses SQLite's consistent snapshot.
    with sqlite3.connect(path.as_uri() + "?mode=rw", uri=True) as db:
        _schema(db)
        with backup.open("xb"):
            pass
        with sqlite3.connect(backup) as target:
            db.backup(target)
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN IMMEDIATE")
        _schema(db)
        db.execute("""CREATE TABLE IF NOT EXISTS fanqie_backfill_contracts (
            binding_uuid TEXT PRIMARY KEY REFERENCES fanqie_bindings(binding_uuid),
            business_key TEXT UNIQUE NOT NULL, post_id TEXT UNIQUE NOT NULL,
            manifest_json TEXT NOT NULL, manifest_sha TEXT NOT NULL,
            contract_json TEXT NOT NULL, authorization_json TEXT,
            revision INTEGER NOT NULL DEFAULT 0, batch_id TEXT, created_at TEXT NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS fanqie_dispatch_outbox (
            binding_uuid TEXT PRIMARY KEY REFERENCES fanqie_backfill_contracts(binding_uuid),
            dispatch_key TEXT UNIQUE NOT NULL, account_id TEXT NOT NULL,
            binding_version TEXT NOT NULL, payload_json TEXT NOT NULL,
            command_id TEXT UNIQUE, created_at TEXT NOT NULL)""")
        db.execute("CREATE TABLE IF NOT EXISTS fanqie_schema_versions (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
        _extensions(db)
        db.execute("INSERT OR IGNORE INTO fanqie_schema_versions VALUES (?,?)", (VERSION, _now()))
    # Constructor verifies the shape, not just the version marker.
    PromotionLedger(path)
    return {"version": VERSION, "backup": str(backup), "backup_sha256": file_sha(backup)}


class PromotionLedger:
    def __init__(self, path):
        self.path = Path(path).resolve()
        with self._db() as db:
            _schema(db)
            if not db.execute("SELECT 1 FROM fanqie_schema_versions WHERE version=?", (VERSION,)).fetchone():
                raise BackfillBlocked("ledger_migration_required")
            _extensions(db)

    @contextmanager
    def _db(self, write=False):
        db = sqlite3.connect(self.path.as_uri() + ("?mode=rw" if write else "?mode=ro"), uri=True, timeout=2)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            if write:
                db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _event(self, db, row, before, after, evidence):
        payload = {"binding_uuid": row["binding_uuid"], "evidence": evidence}
        db.execute("""INSERT INTO fanqie_operation_events
            (event_uuid,task_id,event_type,from_status,to_status,actor_type,actor_id,payload_json,created_at,audit_artifact_hash)
            VALUES(?,?,?,?,?,?,?,?,?,?)""", (uuid.uuid4().hex, row["task_id"], "backfill_v2",
            before, after, "service", "fanqie_backfill", _json(payload), _now(), digest(payload)))

    def register(self, task_id, publish_id, manifest, contract):
        """Freeze service-validated preparation against existing business records.

        This API is internal; identity/asset validation is the coordinator's job.
        It does not approve anything and cannot dispatch a browser command.
        """
        native = contract.get('schema') == 'fanqie_backfill_contract/v3'
        if native:
            # Shared native meaning and the authoritative P0 identity mapping
            # are checked read-only. No alias-to-platform-task substitution.
            from .fanqie_backfill_native_v3 import validate_registration
            validate_registration(self.path, task_id, manifest, contract)
        else:
            required = ("fanqie_resource_id", "fanqie_binding_version", "platform_task_id", "alias_id", "promotion_path",
                        "account_link_version", "identity_evidence", "publication_metadata_evidence")
            if any(not isinstance(contract.get(k), str) or not contract[k].strip() for k in required):
                raise BackfillBlocked("complete_promotion_contract_required")
        b, p = manifest["binding"], manifest["publication"]
        validate_workbook(manifest)
        with self._db(True) as db:
            task = db.execute("SELECT t.*,b.fanqie_book_id FROM fanqie_promotion_tasks t JOIN fanqie_books b ON b.id=t.book_id WHERE t.id=?", (task_id,)).fetchone()
            pub = db.execute("SELECT * FROM fanqie_publish_records WHERE id=?", (publish_id,)).fetchone()
            if (not task or not pub or pub["task_id"] != task_id
                    or str(task["fanqie_book_id"]) != b["book_id"]
                    or task["promotion_alias"] != b["alias"] or task["publish_type"] != b["publish_type"]
                    or (not native and task["platform_task_id"] != contract["platform_task_id"])
                    or (native and (task['platform_task_id'] is not None
                        or task['native_identity_scope'] != contract['native_identity_scope']))
                    or pub["douyin_video_id"] != p["post_id"] or pub["douyin_video_url"] != p["publish_url"]):
                raise BackfillBlocked("closed_loop_record_binding_mismatch")
            business_key = digest([contract["fanqie_resource_id"], task["task_uuid"], p["post_id"]])
            existing = db.execute("SELECT * FROM fanqie_backfill_contracts WHERE post_id=? OR business_key=?", (p["post_id"], business_key)).fetchone()
            if existing:
                if existing["business_key"] == business_key and existing["manifest_sha"] == digest(manifest) and existing["contract_json"] == _json(contract):
                    return existing["binding_uuid"]
                raise BackfillBlocked("publication_already_bound_or_preparation_changed")
            if db.execute("SELECT 1 FROM fanqie_bindings WHERE publish_id=?", (publish_id,)).fetchone():
                raise BackfillBlocked("legacy_backfill_requires_reconciliation")
            binding_uuid = uuid.uuid4().hex
            db.execute("""INSERT INTO fanqie_bindings
                (binding_uuid,task_id,publish_id,status,attempt_count,submitted_url,field_contract_json,idempotency_key,created_at)
                VALUES(?,?,?,?,?,?,?,?,?)""", (binding_uuid, task_id, publish_id, "prepared", 0,
                p["publish_url"], _json(contract), business_key, _now()))
            db.execute("""INSERT INTO fanqie_backfill_contracts
                (binding_uuid,business_key,post_id,manifest_json,manifest_sha,contract_json,created_at)
                VALUES(?,?,?,?,?,?,?)""", (binding_uuid, business_key, p["post_id"], _json(manifest),
                digest(manifest), _json(contract), _now()))
            self._event(db, {"binding_uuid": binding_uuid, "task_id": task_id}, None, "prepared", {"manifest_sha256": digest(manifest)})
            return binding_uuid

    @staticmethod
    def _row(db, binding_uuid):
        row = db.execute("""SELECT c.*,b.task_id,b.publish_id,b.status,b.attempt_count
            FROM fanqie_backfill_contracts c JOIN fanqie_bindings b USING(binding_uuid)
            WHERE c.binding_uuid=?""", (binding_uuid,)).fetchone()
        if row is None:
            raise BackfillBlocked("backfill_not_registered")
        return dict(row)

    def get(self, binding_uuid):
        with self._db() as db:
            return self._row(db, binding_uuid)

    def authorize(self, binding_uuid, *, manifest_sha, reference):
        """Called by the authenticated application after resolving user scope."""
        if not isinstance(reference, str) or not reference.strip():
            raise BackfillBlocked("authorization_reference_required")
        with self._db(True) as db:
            row = self._row(db, binding_uuid)
            auth = {"manifest_sha256": manifest_sha, "reference": reference}
            if row["manifest_sha"] != manifest_sha:
                raise BackfillBlocked("authorization_preparation_mismatch")
            if row["status"] == "ready" and row["authorization_json"] == _json(auth):
                return
            if row["status"] != "prepared":
                raise BackfillBlocked("authorization_state_changed")
            db.execute("UPDATE fanqie_backfill_contracts SET authorization_json=?,revision=revision+1 WHERE binding_uuid=?", (_json(auth), binding_uuid))
            db.execute("UPDATE fanqie_bindings SET status='ready' WHERE binding_uuid=?", (binding_uuid,))
            self._event(db, row, "prepared", "ready", auth)

    def transition(self, binding_uuid, expected_revision, state, evidence):
        with self._db(True) as db:
            row = self._row(db, binding_uuid)
            if row["revision"] != expected_revision or state not in TRANSITIONS.get(row["status"], set()):
                raise BackfillBlocked("backfill_state_changed_or_transition_invalid")
            if state == "upload_started" and not row["authorization_json"]:
                raise BackfillBlocked("backfill_not_authorized")
            batch = evidence.get("batch_id")
            if batch is not None and (not isinstance(batch, str) or not batch.strip() or (row["batch_id"] and row["batch_id"] != batch)):
                raise BackfillBlocked("original_batch_mismatch")
            if state == "accepted" and not batch:
                raise BackfillBlocked("accepted_batch_identity_required")
            if state == "confirmed" and evidence.get("post_id") != row["post_id"]:
                raise BackfillBlocked("exact_publication_readback_required")
            db.execute("UPDATE fanqie_bindings SET status=?,attempt_count=COALESCE(attempt_count,0)+? WHERE binding_uuid=?",
                       (state, int(state == "upload_started"), binding_uuid))
            db.execute("UPDATE fanqie_backfill_contracts SET revision=revision+1,batch_id=COALESCE(?,batch_id) WHERE binding_uuid=?", (batch, binding_uuid))
            self._event(db, row, row["status"], state, evidence)
        return self.get(binding_uuid)

    def enqueue(self, binding_uuid):
        with self._db(True) as db:
            row = self._row(db, binding_uuid)
            if row["status"] != "ready" or not row["authorization_json"]:
                raise BackfillBlocked("backfill_not_ready")
            contract = json.loads(row["contract_json"])
            payload = {"binding_uuid": binding_uuid, "manifest_sha256": row["manifest_sha"]}
            db.execute("""INSERT OR IGNORE INTO fanqie_dispatch_outbox
                (binding_uuid,dispatch_key,account_id,binding_version,payload_json,created_at) VALUES(?,?,?,?,?,?)""",
                (binding_uuid, "fanqie-backfill:" + row["business_key"], contract["fanqie_resource_id"],
                 contract["fanqie_binding_version"], _json(payload), _now()))

    def dispatch(self, binding_uuid, control_store):
        # No cross-database transaction. ControlStore.submit deduplicates a crash
        # after enqueue but before command_id is saved back to this ledger.
        with self._db() as db:
            row = db.execute("SELECT * FROM fanqie_dispatch_outbox WHERE binding_uuid=?", (binding_uuid,)).fetchone()
            if not row:
                raise BackfillBlocked("outbox_entry_required")
            row = dict(row)
        if row["command_id"]:
            return control_store.get(row["command_id"])
        state = self.get(binding_uuid)
        if state["status"] != "ready":
            raise BackfillBlocked("outbox_not_ready")
        command = control_store.submit(row["account_id"], row["binding_version"], "fanqie_backfill",
            row["dispatch_key"], json.loads(row["payload_json"]), priority=200)
        with self._db(True) as db:
            db.execute("UPDATE fanqie_dispatch_outbox SET command_id=? WHERE binding_uuid=? AND command_id IS NULL", (command["command_id"], binding_uuid))
            stored = db.execute("SELECT command_id FROM fanqie_dispatch_outbox WHERE binding_uuid=?", (binding_uuid,)).fetchone()[0]
            if stored != command["command_id"]:
                raise BackfillBlocked("outbox_command_conflict")
        return command
