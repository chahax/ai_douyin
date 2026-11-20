"""One-time idle deployment; retain the quota-waiting original command."""
from contextlib import ExitStack
from pathlib import Path
import hashlib
import json
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "data/browser_lifecycle_repair/20261020"
ACCOUNT = "account:9e5f9e75192fa45becb945bc"
COMMAND = "6dbb0d77e18240a49b4df7d014089e89"


def main():
    import psutil
    from src.operations_accounts.browser_control import BrowserControlStore
    from src.operations_accounts.publication_autonomous_reconciliation import unresolved
    target = OUT / "SCOPED_WINDOW_DEPLOYED.json"
    assert not target.exists(), "Already deployed; do not repeat"
    suite = ET.parse(OUT / "WINDOW_SCOPED_TEST.xml").getroot().find("testsuite")
    assert int(suite.attrib["tests"]) > 0
    assert all(suite.attrib[k] == "0" for k in ("errors", "failures", "skipped"))
    proc = psutil.Process(28196)
    assert abs(proc.create_time() - 1792515510.3428228) < 0.001
    assert any("run_streamlit_web.py" in arg for arg in proc.cmdline())
    assert not proc.children(recursive=True), "Browser or other children exist"
    store = BrowserControlStore(ROOT / "data/account_browser_control.db")
    with ExitStack() as stack:
        def fence(name):
            db = stack.enter_context(sqlite3.connect(
                (ROOT / "data" / name).as_uri() + "?mode=rw", uri=True, timeout=2))
            db.row_factory = sqlite3.Row
            db.execute("BEGIN IMMEDIATE")
            return db
        plans = fence("account_refresh.db")
        control = dict(plans.execute("SELECT * FROM account_controls WHERE account_uuid=?", (ACCOUNT,)).fetchone())
        assert control["state"] == "paused" and control["revision"] == 63
        for table in ("refresh_accounts", "smart_accounts", "playback_accounts"):
            assert not plans.execute(f"SELECT 1 FROM {table} WHERE run_id IS NOT NULL OR coalesce(lease_until,0)<>0").fetchone()
        runtime = fence("douyin.db")
        assert not runtime.execute("SELECT 1 FROM account_runtime_state WHERE lock_owner!=''").fetchone()
        with store._db(write=True) as db:
            pending = unresolved(store, db, ACCOUNT, ("queued", "running", "paused", "waiting_human", "outcome_unknown"))
            assert len(pending) == 1 and pending[0]["command_id"] == COMMAND
            command = pending[0]
            assert command["state"] == "queued" and command["error_code"] == "daily_quota_exceeded"
            owner = dict(db.execute("SELECT * FROM browser_control_owners WHERE account_id=?", (ACCOUNT,)).fetchone())
            assert owner["generation"] == 41 and owner["owner_id"] == "backend:28196:3b1f89aef13146b1a335538296d22559"
            assert not proc.children(recursive=True)
            sources = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
                "src/operations_accounts/browser_control.py", "src/operations_accounts/browser_control_runtime.py")}
            evidence = dict(at=time.time(), backend_pid=proc.pid, backend_created_at=proc.create_time(),
                            owner_before=owner, original_queued_command=command,
                            control_before=control, sources=sources, browser_children=[])
            (OUT / "SCOPED_WINDOW_STOP_INTENT.json").write_text(
                json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf8")
            proc.terminate()
            proc.wait(timeout=20)
            db.execute("""CREATE TABLE IF NOT EXISTS browser_control_idle_deploy_audit(
                deployment_id TEXT PRIMARY KEY,evidence TEXT NOT NULL,retired_at REAL NOT NULL)""")
            db.execute("INSERT INTO browser_control_idle_deploy_audit VALUES(?,?,?)",
                       ("scoped-window-query-20261021-gen41", json.dumps(evidence, ensure_ascii=False), time.time()))
            db.execute("UPDATE browser_control_owners SET state='released',updated_at=? WHERE account_id=? AND generation=41",
                       (time.time(), ACCOUNT))
            assert store._command(db.execute("SELECT * FROM browser_control_commands WHERE command_id=?", (COMMAND,)).fetchone()) == command
    evidence["status"] = "stopped_at_queued_gate_original_preserved"
    target.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps({"status": evidence["status"], "original_command": COMMAND}))


if __name__ == "__main__":
    main()
