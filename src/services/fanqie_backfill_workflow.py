"""Promotion-to-publication binding and durable, single-attempt backfill.

No network, browser startup or scheduling at import time. Callers supply the
managed browser adapter and live account/lease guard. Preparation is offline.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
import xml.etree.ElementTree as ET
import zipfile


SCHEMA = "fanqie_backfill/v1"
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


class BackfillBlocked(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@dataclass(frozen=True)
class BackfillBinding:
    fanqie_account: str
    douyin_account_uuid: str
    binding_version: str
    publication_command_id: str
    book_id: str
    alias: str
    douyin_display_id: str
    published_date: str  # Original publication date, never the backfill date.
    publish_type: str = "AIGC"

    def validate(self):
        for name, value in asdict(self).items():
            if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 512:
                raise BackfillBlocked(f"invalid_{name}")
        if not re.fullmatch(r"[0-9]{10,24}", self.book_id):
            raise BackfillBlocked("invalid_book_id")
        if not re.fullmatch(r"[a-f0-9]{32}", self.publication_command_id):
            raise BackfillBlocked("invalid_publication_command_id")
        if self.publish_type != "AIGC":
            raise BackfillBlocked("this_workflow_requires_aigc")
        if not re.fullmatch(r"\d{4}/\d{2}/\d{2}", self.published_date):
            raise BackfillBlocked("invalid_publication_date")
        date.fromisoformat(self.published_date.replace("/", "-"))


def read_publication(db_path, binding: BackfillBinding):
    """Normalize original success and independently verified reconciliation."""
    from src.services.publication_evidence import PublicationEvidenceReader
    binding.validate()
    try:
        return PublicationEvidenceReader(db_path).read(binding.publication_command_id,
                binding.douyin_account_uuid, binding.binding_version)
    except (ValueError, TypeError, KeyError) as exc:
        raise BackfillBlocked(str(exc)) from exc


def validate_snapshot(binding, snapshot, *, now=None, require_active=True):
    now = time.time() if now is None else now
    if snapshot.get("account") != binding.fanqie_account or snapshot.get("identity_verified") is not True:
        raise BackfillBlocked("fanqie_identity_unverified")
    observed = snapshot.get("observed_at")
    if not isinstance(observed, (int, float)) or not 0 <= now - observed <= 60:
        raise BackfillBlocked("stale_fanqie_observation")
    if snapshot.get("challenge") or snapshot.get("table_ready") is not True:
        raise BackfillBlocked("fanqie_page_not_ready")
    rows = [r for r in snapshot.get("items", []) if r.get("alias") == binding.alias]
    if len(rows) != 1:
        raise BackfillBlocked("promotion_alias_missing_or_ambiguous")
    row = rows[0]
    if row.get("book_id") != binding.book_id or row.get("publish_type") != binding.publish_type:
        raise BackfillBlocked("promotion_binding_mismatch")
    if require_active and (row.get("alias_status") != "生效中" or row.get("book_status") != "可用"):
        raise BackfillBlocked("promotion_not_active")
    return row


def validate_workbook(manifest):
    """Check actual cells, not merely a caller-provided workbook digest."""
    binding = BackfillBinding(**manifest["binding"])
    binding.validate()
    if file_sha(manifest["workbook"]) != manifest["workbook_sha256"]:
        raise BackfillBlocked("prepared_artifact_changed")
    with zipfile.ZipFile(manifest["workbook"]) as archive:
        tree = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        rows = tree.findall("s:sheetData/s:row", NS)
        if len(rows) != 2 or [r.get("r") for r in rows] != ["1", "2"] or tree.findall(".//s:f", NS):
            raise BackfillBlocked("workbook_rows_or_formulas_changed")
        cells = rows[1].findall("s:c", NS)
        values = [c.findtext("s:is/s:t", namespaces=NS) for c in cells]
        if ([c.get("r") for c in cells] != ["A2", "B2", "C2", "D2"]
                or any(c.get("t") != "inlineStr" for c in cells)
                or values != [binding.alias, binding.published_date, manifest["publication"]["publish_url"], binding.douyin_display_id]):
            raise BackfillBlocked("workbook_fields_differ_from_binding")


def export_template(template, output, binding, publication):
    """Preserve official header/style/assets, replace the sample with one text row."""
    binding.validate()
    with zipfile.ZipFile(template) as archive:
        original = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
        tree = ET.fromstring(original)
        cells = tree.findall("s:sheetData/s:row[@r='1']/s:c", NS)
        headers = [(c.findtext("s:v", default="", namespaces=NS)) for c in cells[:4]]
        if len(headers) != 4 or not all(h.startswith(prefix) for h, prefix in
                zip(headers, ("别名", "发文日期", "发文链接", "抖音号"))):
            raise BackfillBlocked("official_template_headers_changed")
        first = re.search(r'<row\b[^>]*\br="1"[^>]*>.*?</row>', original, flags=re.S)
        if not first:
            raise BackfillBlocked("official_template_header_missing")
        row = ET.Element("row", r="2")
        values = [binding.alias, binding.published_date, publication["publish_url"], binding.douyin_display_id]
        for col, value in zip("ABCD", values):
            cell = ET.SubElement(row, "c", r=col+"2", t="inlineStr")
            ET.SubElement(ET.SubElement(cell, "is"), "t").text = value
        sheet = re.sub(r"<sheetData>.*?</sheetData>", lambda _: "<sheetData>" + first[0]
                       + ET.tostring(row, encoding="unicode") + "</sheetData>", original, count=1, flags=re.S)
        sheet = re.sub(r'<dimension ref="[^"]*"', '<dimension ref="A1:E2"', sheet, count=1)
        with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as target:
            for info in archive.infolist():
                target.writestr(info, sheet.encode("utf-8") if info.filename == "xl/worksheets/sheet1.xml"
                                else archive.read(info.filename))


def prepare(binding, browser_db, template, directory):
    publication = read_publication(browser_db, binding)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    workbook = directory / "backfill.xlsx"
    export_template(template, workbook, binding, publication)
    manifest = {"schema": SCHEMA, "binding": asdict(binding), "publication": publication,
                "workbook": str(workbook.resolve()), "workbook_sha256": file_sha(workbook),
                "template_sha256": file_sha(template), "state": "prepared", "submitted": False}
    manifest["job_id"] = digest({"binding": manifest["binding"], "publication": publication})
    (directory/"manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


class BackfillStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS backfill_jobs (
                job_id TEXT PRIMARY KEY, fanqie_account TEXT NOT NULL, alias TEXT NOT NULL,
                publish_url TEXT NOT NULL, manifest_sha TEXT NOT NULL, state TEXT NOT NULL,
                evidence TEXT NOT NULL, updated_at REAL NOT NULL,
                UNIQUE(fanqie_account,alias,publish_url))""")

    def get(self, job_id):
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM backfill_jobs WHERE job_id=?", (job_id,)).fetchone()
            return dict(row) if row else None

    def claim(self, manifest, authorization):
        b = manifest["binding"]
        with sqlite3.connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            exists = db.execute("SELECT job_id FROM backfill_jobs WHERE job_id=? OR "
                                "(fanqie_account=? AND alias=? AND publish_url=?)",
                                (manifest["job_id"], b["fanqie_account"], b["alias"],
                                 manifest["publication"]["publish_url"])).fetchone()
            if exists:
                raise BackfillBlocked("original_backfill_claim_exists")
            db.execute("INSERT INTO backfill_jobs VALUES (?,?,?,?,?,?,?,?)",
                       (manifest["job_id"], b["fanqie_account"], b["alias"], manifest["publication"]["publish_url"],
                        digest(manifest), "dispatching", json.dumps({"authorization_reference": authorization["reference"],
                            "authorization_sha256": digest(authorization)}, ensure_ascii=False), time.time()))

    def finish(self, job_id, state, evidence):
        with sqlite3.connect(self.path) as db:
            cur = db.execute("UPDATE backfill_jobs SET state=?,evidence=?,updated_at=? WHERE job_id=? AND state='dispatching'",
                             (state, json.dumps(evidence, ensure_ascii=False), time.time(), job_id))
            if cur.rowcount != 1:
                raise BackfillBlocked("original_backfill_state_changed")


def execute(manifest, *, browser_db, store, adapter, guard, authorization=None, dry_run=True):
    """One bounded attempt. Unknown results require reconciliation, never retry."""
    binding = BackfillBinding(**manifest["binding"])
    binding.validate()
    publication = read_publication(browser_db, binding)
    if (manifest.get("schema") != SCHEMA or manifest.get("publication") != publication
            or manifest.get("job_id") != digest({"binding": asdict(binding), "publication": publication})
            or file_sha(manifest["workbook"]) != manifest.get("workbook_sha256")):
        raise BackfillBlocked("prepared_artifact_or_publication_changed")
    guard(binding)
    snapshot = adapter.observe(binding)
    row = validate_snapshot(binding, snapshot)
    links = row.get("published_links", [])
    if publication["publish_url"] in links:
        return {"state": "already_present", "submitted": False, "job_id": manifest["job_id"]}
    if links or row.get("fill_status") != "未填写":
        raise BackfillBlocked("existing_backfill_requires_reconciliation")
    if dry_run:
        return {"state": "ready_for_authorization", "submitted": False, "job_id": manifest["job_id"]}
    if (not isinstance(authorization, dict) or authorization.get("job_id") != manifest["job_id"]
            or authorization.get("manifest_sha256") != digest(manifest)
            or not authorization.get("reference") or authorization.get("allow_submit") is not True):
        raise BackfillBlocked("exact_backfill_authorization_required")
    guard(binding)
    # Claim before uploading: upload itself can create a platform resource.
    store.claim(manifest, authorization)
    try:
        adapter.upload(manifest["workbook"], binding)
        guard(binding)
        before_submit = validate_snapshot(binding, adapter.observe(binding))
        if before_submit.get("published_links") or before_submit.get("fill_status") != "未填写":
            raise BackfillBlocked("backfill_changed_after_upload")
        adapter.submit(binding)
        guard(binding)
        after = adapter.observe(binding)
        matched = validate_snapshot(binding, after)
        if publication["publish_url"] not in matched.get("published_links", []):
            state = "outcome_unknown"
        else:
            state = "succeeded"
        evidence = {"publish_url": publication["publish_url"], "confirmed_exact_link": state == "succeeded"}
    except Exception as exc:
        state, evidence = "outcome_unknown", {"error_type": type(exc).__name__}
    evidence["authorization_reference"] = authorization["reference"]
    evidence["authorization_sha256"] = digest(authorization)
    store.finish(manifest["job_id"], state, evidence)
    return {"state": state, "job_id": manifest["job_id"], "attempt_reserved": True, "evidence": evidence}
