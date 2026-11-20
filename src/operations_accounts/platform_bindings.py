"""Explicit platform identity bindings alongside the existing control database.

This repository stores confirmed identities; it never logs in or infers identity
from a nickname. The platform probe and authenticated confirmation UI must supply
their frozen evidence before a binding can be created.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time

from .browser_control import BrowserControlStore, BrowserControlRejected


def _reject(code):
    raise BrowserControlRejected(code, code)


def install_platform_binding_schema(control_path, backup_path):
    source, backup = Path(control_path).resolve(), Path(backup_path).resolve()
    if not source.is_file() or backup.exists():
        _reject("existing_control_and_new_backup_required")
    BrowserControlStore(source)  # Validate existing schema without changing it.
    backup.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source.as_uri() + "?mode=rw", uri=True) as db:
        # Pin a WAL read snapshot: frequent service heartbeats must not restart
        # a multi-gigabyte backup indefinitely. No business writes are stopped.
        db.execute("BEGIN")
        db.execute("SELECT count(*) FROM sqlite_master").fetchone()
        with backup.open("xb"):
            pass
        started = time.monotonic()
        progress_path = backup.with_suffix('.progress.json')
        def progress(status, remaining, total):
            progress_path.write_text(json.dumps({'status':status,'remaining_pages':remaining,
                'total_pages':total,'elapsed_seconds':time.monotonic()-started}), encoding='utf-8')
            if time.monotonic() - started > 600:
                raise TimeoutError('platform_schema_backup_timeout; original database unchanged')
        with sqlite3.connect(backup) as target:
            # This brand-new, disposable backup has no preexisting data to undo.
            # Avoid rollback-journal churn while copying; fsync only once the
            # complete snapshot exists. Failure never proceeds to migration.
            target.execute('PRAGMA journal_mode=OFF')
            target.execute('PRAGMA synchronous=OFF')
            db.backup(target, pages=16384, progress=progress)
        with backup.open('r+b') as finished:
            os.fsync(finished.fileno())
        db.rollback()
        db.execute("BEGIN IMMEDIATE")
        db.execute("""CREATE TABLE IF NOT EXISTS platform_identity_bindings (
            resource_id TEXT PRIMARY KEY, platform TEXT NOT NULL,
            platform_identity_key TEXT NOT NULL, binding_version TEXT NOT NULL,
            environment_key TEXT UNIQUE NOT NULL, profile_dir TEXT UNIQUE NOT NULL,
            status TEXT NOT NULL, confirmation_path TEXT NOT NULL,
            confirmation_sha256 TEXT NOT NULL, created_at REAL NOT NULL,
            UNIQUE(platform,platform_identity_key))""")
    return {"backup": str(backup), "table": "platform_identity_bindings"}


class PlatformBindingRepository:
    def __init__(self, path, *, evidence_root, profile_root, clock=time.time):
        self.path = Path(path).resolve()
        self.evidence_root = Path(evidence_root).resolve()
        self.profile_root = Path(profile_root).resolve()
        self.clock = clock

    @contextmanager
    def _db(self, write=False):
        db = sqlite3.connect(self.path.as_uri() + ("?mode=rw" if write else "?mode=ro"), uri=True, timeout=2)
        db.row_factory = sqlite3.Row
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            if write:
                db.commit()
        finally:
            db.close()

    def _evidence(self, reference):
        p = Path(reference["path"]).resolve()
        if not p.is_relative_to(self.evidence_root) or not p.is_file():
            _reject("identity_evidence_outside_root")
        raw = p.read_bytes()
        if hashlib.sha256(raw).hexdigest() != reference.get("sha256"):
            _reject("identity_evidence_changed")
        return json.loads(raw)

    def confirm(self, reference):
        value = self._evidence(reference)
        fields = ("resource_id", "platform_identity_key", "binding_version", "environment_key", "profile_dir")
        if (value.get("schema") != "platform_identity_confirmation/v1"
                or value.get("platform") != "fanqie"
                or value.get("decision_source") != "explicit_user_confirmation"
                or not str(value.get("user_statement", "")).strip()
                or any(not isinstance(value.get(k), str) or not value[k].strip() for k in fields)):
            _reject("explicit_platform_identity_confirmation_required")
        profile = Path(value["profile_dir"]).resolve()
        if not profile.is_relative_to(self.profile_root) or profile == self.profile_root:
            _reject("dedicated_platform_profile_required")
        resource = value["resource_id"]
        if not resource.startswith("fanqie:") or resource == "fanqie:":
            _reject("namespaced_platform_resource_required")
        probe = self._evidence(value["probe_evidence"])
        if (probe.get("schema") != "platform_identity_probe/v1"
                or probe.get("platform") != "fanqie" or probe.get("verified") is not True
                or probe.get("challenge") is not False
                or probe.get("platform_identity_key") != value["platform_identity_key"]
                or probe.get("environment_key") != value["environment_key"]
                or probe.get("identity_source") not in {"platform_account_id", "official_authorized_identity"}
                or not isinstance(probe.get("observed_at"), (int, float))
                or not 0 <= self.clock() - probe["observed_at"] <= 300):
            _reject("stable_platform_identity_probe_required")
        with self._db(True) as db:
            old = db.execute("SELECT * FROM platform_identity_bindings WHERE resource_id=?", (resource,)).fetchone()
            if old:
                if old["confirmation_sha256"] == reference["sha256"]:
                    return dict(old)
                _reject("existing_platform_binding_requires_explicit_rebind")
            # Never adopt an environment already owned by another binding.
            owner = db.execute("SELECT * FROM browser_control_owners WHERE account_id=?", (resource,)).fetchone()
            if owner and (owner["state"] != "released" or owner["binding_version"] != value["binding_version"]):
                _reject("existing_platform_owner_requires_reconciliation")
            if db.execute("SELECT 1 FROM browser_control_commands WHERE account_id=? AND state IN ('queued','running','paused','waiting_human','outcome_unknown') LIMIT 1", (resource,)).fetchone():
                _reject("pending_platform_command_requires_reconciliation")
            db.execute("INSERT INTO platform_identity_bindings VALUES(?,?,?,?,?,?,?,?,?,?)",
                (resource, "fanqie", value["platform_identity_key"], value["binding_version"],
                 value["environment_key"], str(profile), "active", str(Path(reference["path"]).resolve()),
                 reference["sha256"], self.clock()))
        return self.get(resource)

    def get(self, resource_id):
        with self._db() as db:
            row = db.execute("SELECT * FROM platform_identity_bindings WHERE resource_id=?", (resource_id,)).fetchone()
            return dict(row) if row else None

    def guard(self, resource_id, binding_version, owner_id, generation, identity, *, ttl=90):
        """Fence a live managed command against persistent binding and owner.

        identity is supplied by the trusted platform probe, never UI form input.
        """
        with self._db() as db:
            binding = db.execute("SELECT * FROM platform_identity_bindings WHERE resource_id=?", (resource_id,)).fetchone()
            owner = db.execute("SELECT * FROM browser_control_owners WHERE account_id=?", (resource_id,)).fetchone()
        if (not binding or binding["status"] != "active" or binding["binding_version"] != binding_version
                or not owner or owner["state"] != "active" or owner["owner_id"] != owner_id
                or owner["generation"] != generation or owner["binding_version"] != binding_version
                or not 0 <= self.clock() - owner["heartbeat"] <= ttl):
            _reject("platform_binding_or_owner_fenced")
        observed = identity.get("observed_at")
        if (identity.get("platform") != "fanqie" or identity.get("verified") is not True
                or identity.get("challenge") is not False
                or identity.get("platform_identity_key") != binding["platform_identity_key"]
                or identity.get("environment_key") != binding["environment_key"]
                or not isinstance(observed, (int, float)) or not 0 <= self.clock() - observed <= 60):
            _reject("platform_identity_unverified")
        return dict(binding)
