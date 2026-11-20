from dataclasses import asdict, replace
import json
import sqlite3
import time
import xml.etree.ElementTree as ET
import zipfile

import pytest
from playwright.sync_api import sync_playwright

from src.services.fanqie_backfill_workflow import (
    BackfillBinding, BackfillBlocked, BackfillStore, NS, digest, execute,
    export_template, prepare, read_publication, validate_snapshot,
)
from src.platform_adapter.fanqie_backfill import FanqieBatchPageAdapter, PROMOTION_LIST_URL

URL = "https://www.douyin.com/video/1234567890123456789"


@pytest.fixture
def setup(tmp_path):
    b = BackfillBinding("fanqie-test-id", "account:test", "bound-v1", "a"*32,
                       "7656344274241326104", "测试别名", "example-douyin-id", "2026/10/24")
    dbpath = tmp_path/"browser.db"
    result = {"status": "published", "success": True, "post_id": URL.rsplit("/", 1)[1],
              "publish_url": URL, "publish_evidence": {"post_verified": True}}
    with sqlite3.connect(dbpath) as db:
        db.execute("CREATE TABLE browser_control_commands(command_id TEXT,account_id TEXT,binding_version TEXT,kind TEXT,state TEXT,result TEXT)")
        db.execute("INSERT INTO browser_control_commands VALUES (?,?,?,?,?,?)",
                   (b.publication_command_id, b.douyin_account_uuid, b.binding_version, "publish", "succeeded", json.dumps(result)))
    template = tmp_path/"template.xlsx"
    with zipfile.ZipFile(template, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", '''<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><dimension ref="A1"/><sheetData><row r="1"><c r="A1" t="str"><v>别名</v></c><c r="B1" t="str"><v>发文日期 YYYY/MM/DD</v></c><c r="C1" t="str"><v>发文链接</v></c><c r="D1" t="str"><v>抖音号</v></c></row><row r="2"><c r="A2"><v>OLD EXAMPLE</v></c></row></sheetData></worksheet>''')
        z.writestr("template-preserved.txt", "unchanged")
    manifest = prepare(b, dbpath, template, tmp_path/"prepared")
    return b, dbpath, template, manifest, BackfillStore(tmp_path/"backfill.db")


def snapshot(b, **row_updates):
    row = dict(alias=b.alias, book_id=b.book_id, publish_type="AIGC", alias_status="生效中",
               book_status="可用", fill_status="未填写", published_links=[])
    row.update(row_updates)
    return dict(account=b.fanqie_account, identity_verified=True, challenge=False,
                table_ready=True, observed_at=time.time(), items=[row])


class Adapter:
    def __init__(self, b, *, fail=None, confirmed=True):
        self.b, self.fail, self.confirmed = b, fail, confirmed
        self.uploads = self.submits = 0
    def observe(self, b):
        return snapshot(b, published_links=[URL] if self.submits and self.confirmed else [])
    def upload(self, path, b):
        self.uploads += 1
        if self.fail == "upload": raise TimeoutError()
    def submit(self, b):
        self.submits += 1
        if self.fail == "submit": raise TimeoutError()


def run(setup, adapter=None, *, dry_run=False, authorize=True, guard=lambda b: None):
    b, db, _, m, store = setup
    auth = {"job_id": m["job_id"], "manifest_sha256": digest(m), "reference": "test-user-grant", "allow_submit": True}
    return execute(m, browser_db=db, store=store, adapter=adapter or Adapter(b), guard=guard,
                   authorization=auth if authorize else None, dry_run=dry_run)


def test_exact_original_receipt_and_official_columns(setup):
    b, db, template, m, _ = setup
    assert read_publication(db, b)["publish_url"] == URL
    with zipfile.ZipFile(m["workbook"]) as z:
        assert z.read("template-preserved.txt") == b"unchanged"
        xml = z.read("xl/worksheets/sheet1.xml")
        assert b"OLD EXAMPLE" not in xml
        tree = ET.fromstring(xml)
        values = [c.findtext("s:is/s:t", namespaces=NS) for c in tree.findall("s:sheetData/s:row[@r='2']/s:c", NS)]
        assert values == [b.alias, b.published_date, URL, b.douyin_display_id]
        assert not tree.findall(".//s:f", NS)


@pytest.mark.parametrize("column,value", [("state", "outcome_unknown"), ("state", "running"),
    ("account_id", "other"), ("binding_version", "v2"), ("kind", "maintenance")])
def test_rejects_wrong_original_receipt(setup, column, value):
    b, db, *_ = setup
    with sqlite3.connect(db) as conn: conn.execute(f"UPDATE browser_control_commands SET {column}=?", (value,))
    with pytest.raises(BackfillBlocked): read_publication(db, b)


@pytest.mark.parametrize("change", [{"alias_status": "强制失效"}, {"alias_status": "审核中"},
    {"book_status": "不可用"}, {"publish_type": "AI数字人"}, {"book_id": "other"}])
def test_promotion_must_be_active_and_match(setup, change):
    with pytest.raises(BackfillBlocked): validate_snapshot(setup[0], snapshot(setup[0], **change))


@pytest.mark.parametrize("change", [{"identity_verified": False}, {"account": "other"},
    {"observed_at": 0}, {"table_ready": False}, {"challenge": True}])
def test_page_identity_and_freshness(setup, change):
    s = snapshot(setup[0]); s.update(change)
    with pytest.raises(BackfillBlocked): validate_snapshot(setup[0], s)


def test_ambiguous_alias_rejected(setup):
    s = snapshot(setup[0]); s["items"] *= 2
    with pytest.raises(BackfillBlocked): validate_snapshot(setup[0], s)


def test_dry_run_never_uploads_or_claims(setup):
    a = Adapter(setup[0]); result = run(setup, a, dry_run=True)
    assert result["state"] == "ready_for_authorization" and a.uploads == a.submits == 0
    assert setup[-1].get(setup[3]["job_id"]) is None


def test_no_authorization_never_uploads(setup):
    a = Adapter(setup[0])
    with pytest.raises(BackfillBlocked): run(setup, a, authorize=False)
    assert a.uploads == 0


def test_success_requires_exact_readback_and_repeated_call_no_upload(setup):
    a = Adapter(setup[0]); assert run(setup, a)["state"] == "succeeded"
    another = Adapter(setup[0])
    with pytest.raises(BackfillBlocked): run(setup, another)
    assert another.uploads == 0
    assert setup[-1].get(setup[3]["job_id"])["state"] == "succeeded"


@pytest.mark.parametrize("fail", ["upload", "submit", None])
def test_timeout_or_missing_readback_remains_unknown_no_replay(setup, fail):
    a = Adapter(setup[0], fail=fail, confirmed=False)
    assert run(setup, a)["state"] == "outcome_unknown"
    with pytest.raises(BackfillBlocked): run(setup, Adapter(setup[0]))
    assert setup[-1].get(setup[3]["job_id"])["state"] == "outcome_unknown"


def test_changed_file_rejected(setup):
    from pathlib import Path
    Path(setup[3]["workbook"]).write_bytes(b"changed")
    with pytest.raises(BackfillBlocked): run(setup)


def test_guard_failure_has_no_upload(setup):
    a = Adapter(setup[0])
    def guard(b): raise BackfillBlocked("lease_lost")
    with pytest.raises(BackfillBlocked): run(setup, a, guard=guard)
    assert a.uploads == 0


def test_claim_survives_crash_before_upload(setup):
    m, store = setup[3:]
    store.claim(m, {"reference": "test"})
    with pytest.raises(BackfillBlocked): run(setup)
    assert store.get(m["job_id"])["state"] == "dispatching"


def test_known_existing_link_skips_all_external_actions(setup):
    a = Adapter(setup[0]); a.observe = lambda b: snapshot(b, published_links=[URL], fill_status=URL)
    assert run(setup, a)["state"] == "already_present"
    assert a.uploads == a.submits == 0


def test_promotion_changed_after_upload_does_not_submit(setup):
    a = Adapter(setup[0])
    a.observe = lambda b: snapshot(b, alias_status="强制失效" if a.uploads else "生效中")
    assert run(setup, a)["state"] == "outcome_unknown"
    assert a.uploads == 1 and a.submits == 0


def test_second_job_for_same_alias_link_cannot_bypass_claim(setup):
    m, store = setup[3:]
    store.claim(m, {"reference": "first"})
    other = dict(m, job_id="different")
    with pytest.raises(BackfillBlocked): store.claim(other, {"reference": "second"})


def test_formula_like_alias_is_text_not_formula(setup, tmp_path):
    b, db, template, m, _ = setup
    b = replace(b, alias='=HYPERLINK("https://example.invalid")')
    output = tmp_path/"literal.xlsx"
    export_template(template, output, b, m["publication"])
    with zipfile.ZipFile(output) as z:
        tree = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
        assert tree.findtext("s:sheetData/s:row[@r='2']/s:c[@r='A2']/s:is/s:t", namespaces=NS) == b.alias
        assert not tree.findall(".//s:f", NS)


@pytest.fixture(scope="module")
def chrome():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True, args=["--mute-audio"])
        yield browser
        browser.close()


def test_observed_batch_ui_local_chrome(setup, chrome):
    b = setup[0]
    html = '''<!doctype html><meta charset="utf-8"><table><thead><tr>''' + ''.join(f'<th>{h}</th>' for h in
       ['关键词','书本信息','发文类型','别名状态','书籍状态','发文详情']) + '''</tr></thead><tbody><tr>'''
    html += ''.join(f'<td>{v}</td>' for v in [b.alias, '书名 id: '+b.book_id, 'AIGC','生效中','可用','未填写'])
    html += '''</tr></tbody></table><button onclick="document.querySelector('[role=dialog]').hidden=false">批量回填发文</button>
      <div role="dialog" aria-label="批量上传发文-番茄小说" hidden><input type="file"
      onchange="document.querySelector('#send').disabled=false"><button id="send" disabled
      onclick="window.submitted=(window.submitted||0)+1">提交</button></div>'''
    page = chrome.new_page()
    page.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html)
               if route.request.url == PROMOTION_LIST_URL else route.abort())
    try:
        page.goto(PROMOTION_LIST_URL)
        adapter = FanqieBatchPageAdapter(page, identity_probe=lambda p: dict(account=b.fanqie_account,verified=True,challenge=False))
        assert validate_snapshot(b, adapter.observe(b))["book_id"] == b.book_id
        adapter.upload(setup[3]["workbook"], b)
        assert page.evaluate("window.submitted||0") == 0
        adapter.submit(b)
        assert page.evaluate("window.submitted") == 1
        # Server readback remains unfilled: submission must never imply success.
        assert adapter.observe(b)["items"][0]["published_links"] == []
    finally: page.close()
