from types import SimpleNamespace

import pytest

from src.operations_accounts.browser_control import BrowserControlStore, BrowserControlRejected
from src.operations_accounts import browser_control_runtime as bridge


def test_window_queries_exclude_unrelated_receipts_and_preserve_unknown(tmp_path, monkeypatch):
    path = tmp_path / "browser.db"
    store = BrowserControlStore(path)
    unrelated = store.submit("account:a", "binding", "publish", "history", {})
    other = store.submit("account:b", "binding", "manual", "other", {"account_key": "other"})
    old = store.submit("account:a", "binding", "manual", "old",
                       {"account_key": "original", "incident_id": 1})
    current = store.submit("account:a", "binding", "manual", "current",
                           {"account_key": "original", "incident_id": 2})
    console = store.submit("account:a", "binding", "official_console", "console", {})
    with store._db(write=True) as db:
        # Invalid JSON proves unrelated blobs are never deserialized.
        db.execute("UPDATE browser_control_commands SET result=? WHERE command_id=?",
                   ("not-json:" + "x" * 1_000_000, unrelated["command_id"]))
        db.execute("UPDATE browser_control_commands SET state='outcome_unknown' WHERE command_id=?",
                   (old["command_id"],))
        db.execute("UPDATE browser_control_commands SET created_at=created_at+1 WHERE command_id=?",
                   (current["command_id"],))
    monkeypatch.setenv("ACCOUNT_BROWSER_CONTROL_DB", str(path))
    monkeypatch.setattr(bridge, "_store", lambda: store)
    profile = SimpleNamespace(account_uuid="account:a")
    monkeypatch.setattr(bridge, "_runtime", lambda: SimpleNamespace(
        profiles=SimpleNamespace(get=lambda _: profile),
        resolve=lambda *a, **k: profile))
    monkeypatch.setattr(bridge, "snapshot", lambda *_: pytest.fail("full history read"))
    assert {r["command_id"] for r in store.commands_of_kind("account:a", "manual")} == {
        old["command_id"], current["command_id"]}
    assert bridge.manual_window_snapshot("account:a", "original")["job_id"] == current["command_id"]
    assert bridge.manual_window_snapshot("account:a", "original", incident_id=1)["state"] == "outcome_unknown"
    assert bridge.queue_manual_window("account:a", "original", "operator")["reused"] is True
    assert bridge.official_console_snapshot("original")["command_id"] == console["command_id"]
    assert bridge.queue_official_console("account:a", "original", "operator")["command_id"] == console["command_id"]
    with pytest.raises(BrowserControlRejected):
        bridge.manual_window_snapshot("account:b", "original")
    assert store.get(other["command_id"])["state"] == "queued"
