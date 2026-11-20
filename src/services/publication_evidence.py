"""Read verified original publications without mutating commands or replaying UI."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sqlite3


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class PublicationEvidenceReader:
    def __init__(self, path, *, evidence_root=None):
        self.path = Path(path).resolve()
        self.evidence_root = Path(evidence_root or Path(__file__).resolve().parents[2]).resolve()

    def read(self, command_id, account_uuid, binding_version):
        with sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM browser_control_commands WHERE command_id=?",
                             (command_id,)).fetchone()
            if row is None or row["state"] != "succeeded" or row["kind"] != "publish":
                raise ValueError("original_publication_not_verified")
            if row["account_id"] != account_uuid or row["binding_version"] != binding_version:
                raise ValueError("original_account_binding_changed")
            result = json.loads(row["result"])
            if result.get("status") != "published" or result.get("success") is not True:
                raise ValueError("original_publication_not_verified")
            if "reconciliation_command_id" in result:
                recovered = db.execute("SELECT * FROM browser_control_commands WHERE command_id=?",
                    (result["reconciliation_command_id"],)).fetchone()
                if recovered is not None and recovered["kind"] == "publication_verify":
                    from .publication_verify_evidence_v1 import read_verified_recovery
                    evidence = read_verified_recovery(row, result, recovered, self.evidence_root)
                else:
                    evidence = self._reconciled(db, row, result)
            else:
                evidence = result.get("publish_evidence", {})
            if evidence.get("post_verified") is not True:
                raise ValueError("original_publication_not_verified")
            post, url = result.get("post_id"), result.get("publish_url")
            if not isinstance(post, str) or not re.fullmatch(r"\d{10,24}", post) or url != f"https://www.douyin.com/video/{post}":
                raise ValueError("canonical_publication_url_required")
            # Mutable command metadata (cursor/updated_at/owner) is not identity.
            receipt = {"command_id": command_id, "account_id": account_uuid,
                       "binding_version": binding_version, "post_id": post,
                       "publish_url": url, "evidence": evidence}
            return {"post_id": post, "publish_url": url, "receipt_sha256": _sha(receipt)}

    def _reconciled(self, db, original, result):
        old = result.get("original_unknown_snapshot", {})
        if any(old.get(k) != original[k] for k in ("command_id", "account_id", "binding_version", "kind")) or old.get("state") != "outcome_unknown":
            raise ValueError("reconciliation_original_mismatch")
        ref = result.get("reconciliation_evidence", {})
        path = Path(ref.get("path", "")).resolve()
        if not path.is_relative_to(self.evidence_root) or not path.is_file():
            raise ValueError("reconciliation_evidence_missing")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != ref.get("sha256"):
            raise ValueError("reconciliation_evidence_changed")
        frozen = json.loads(raw)
        reconciliation_id = result["reconciliation_command_id"]
        command = db.execute("SELECT * FROM browser_control_commands WHERE command_id=?",
                             (reconciliation_id,)).fetchone()
        if (command is None or command["state"] != "succeeded"
                or command["kind"] not in {"publication_reconcile", "publication_comment_settlement"}
                or command["account_id"] != original["account_id"]
                or command["binding_version"] != original["binding_version"]):
            raise ValueError("reconciliation_command_not_verified")
        if (frozen.get("schema") != "publication_reconciliation_evidence/20261019/v1"
                or frozen.get("original_command_id") != original["command_id"]
                or frozen.get("account_uuid") != original["account_id"]
                or frozen.get("reconciliation_command_id") != reconciliation_id):
            raise ValueError("reconciliation_evidence_mismatch")
        verified = frozen.get("result", {})
        evidence = verified.get("publish_evidence", {})
        command_result = json.loads(command["result"] or "{}")
        if (verified.get("status") != "verified_published"
                or command_result.get("evidence_ref") != ref
                or any(command_result.get(k) != verified.get(k) for k in ("status", "publish_evidence", "comment"))
                or any(evidence.get(k) != result.get(k) for k in ("post_id", "publish_url", "post_verified"))):
            raise ValueError("reconciliation_result_mismatch")
        return {**evidence, "reconciliation_command_id": reconciliation_id,
                "reconciliation_evidence_sha256": ref["sha256"]}
