"""Supervised, one-use idle deployment of the validated recommendation-feed playback fix."""
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "data/recommendation_playback_repair/20261020"
ACCOUNT = "account:9e5f9e75192fa45becb945bc"
OWNER = "backend:13144:108e0108ef474c8090722af344b6344d"


def main():
    import psutil
    from scripts.handoff_idle_browser_control import assert_profile_exited
    from src.operations_accounts.browser_control import BrowserControlStore
    from src.operations_accounts.publication_autonomous_reconciliation import unresolved
    receipt = OUT / "UNCAPPED_DEPLOYMENT_STOP_INTENT.json"
    if receipt.exists():
        raise RuntimeError("Execution already recorded; inspect, do not repeat")
    report = OUT / "TEST_UNCAPPED.xml"
    suite = ET.parse(report).getroot().find("testsuite")
    if not (suite.attrib["tests"] == "49" and all(suite.attrib[k] == "0" for k in ("errors", "failures", "skipped"))):
        raise RuntimeError("Expected successful regression evidence missing")
    sources = ["src/platform_adapter/douyin_playback.py", "src/platform_adapter/douyin_recommendation_playback.py",
        "src/operations_accounts/maintenance.py", "src/web/account_refresh_dashboard.py",
        "src/web/trend_dashboard.py", "src/agent/registry.py", "src/operations_accounts/repository.py"]
    hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sources}
    store = BrowserControlStore(ROOT / "data/account_browser_control.db")
    with ExitStack() as stack:
        def fence(name):
            db = stack.enter_context(sqlite3.connect((ROOT / "data" / name).as_uri() + "?mode=rw", uri=True, timeout=3))
            db.row_factory = sqlite3.Row
            db.execute("BEGIN IMMEDIATE")
            return db
        plans = fence("account_refresh.db")
        control = plans.execute("SELECT * FROM account_controls WHERE account_uuid=?", (ACCOUNT,)).fetchone()
        if control["state"] != "paused" or control["revision"] != 56 or control["recovery_token"]:
            raise RuntimeError("Pause changed")
        for table in ("refresh_accounts", "smart_accounts", "playback_accounts"):
            if plans.execute(f"SELECT 1 FROM {table} WHERE run_id IS NOT NULL OR coalesce(lease_until,0)<>0").fetchone():
                raise RuntimeError("Business lease remains")
        if plans.execute("SELECT 1 FROM account_handling_requests WHERE status IN ('requested','probing')").fetchone():
            raise RuntimeError("Handling remains")
        manual = fence("account_manual_windows.db")
        if manual.execute("SELECT 1 FROM manual_window_jobs WHERE state NOT IN ('closed','failed')").fetchone():
            raise RuntimeError("Manual window remains")
        runtime = fence("douyin.db")
        if runtime.execute("SELECT 1 FROM account_runtime_state WHERE lock_owner!=''").fetchone():
            raise RuntimeError("Runtime lease remains")
        profile = runtime.execute("SELECT browser_profile_dir FROM account_runtime_bindings WHERE account_uuid=?", (ACCOUNT,)).fetchone()[0]
        with store._db(write=True) as db:
            if unresolved(store, db, ACCOUNT, ("queued","running","paused","waiting_human","outcome_unknown")):
                raise RuntimeError("Unresolved command remains")
            owner = dict(db.execute("SELECT * FROM browser_control_owners WHERE account_id=?", (ACCOUNT,)).fetchone())
            if owner["owner_id"] != OWNER or owner["generation"] != 37 or owner["state"] != "released":
                raise RuntimeError("Owner identity changed")
            window = db.execute("SELECT state,result FROM browser_control_commands WHERE command_id='d5cd60d958c14f3cb7e3387264d0aab3'").fetchone()
            if window["state"] != "succeeded" or json.loads(window["result"]).get("window_closed") is not True:
                raise RuntimeError("Original window not confirmed closed")
            proc = psutil.Process(14796)
            if (proc.create_time() != 1792497727.2973776 or Path(proc.cwd()).resolve() != ROOT
                    or str(ROOT / "scripts/run_streamlit_web.py").lower() not in [s.lower() for s in proc.cmdline()]
                    or int((ROOT / "data/logs/streamlit_web.pid").read_text()) != proc.pid
                    or proc.children(recursive=True)):
                raise RuntimeError("Process identity changed or children remain")
            assert_profile_exited(profile)
            record = dict(phase="stop_requested", pid=proc.pid, create_time=proc.create_time(),
                owner=OWNER, generation=37, owner_before=owner, sources=hashes,
                regression_sha256=hashlib.sha256(report.read_bytes()).hexdigest(),
                window_closure_evidence="d5cd60 native window_closed=true; no service children",
                at=time.time(), original_commands_preserved=True, new_playback_submitted=False)
            receipt.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf8")
            proc.terminate()
            proc.wait(timeout=10)
            assert_profile_exited(profile)
            # Supervised retirement of this exact stopped, idle generation,
            # including its expired heartbeat. Never forge a fresh heartbeat.
            db.execute("""CREATE TABLE IF NOT EXISTS browser_control_idle_deploy_audit(
                deployment_id TEXT PRIMARY KEY, evidence TEXT NOT NULL, retired_at REAL NOT NULL)""")
            db.execute("INSERT INTO browser_control_idle_deploy_audit VALUES(?,?,?)",
                       ("recommend-feed-uncapped-20261020-gen37", json.dumps(record, ensure_ascii=False), time.time()))
            db.execute("UPDATE browser_control_owners SET state='released',updated_at=? WHERE account_id=? AND owner_id=? AND generation=37 AND state='active'",
                       (time.time(), ACCOUNT, OWNER))
    record.update(phase="stopped_owner_already_released", completed_at=time.time())
    receipt.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps({"phase": record["phase"], "pid": 14796, "tests": 49}))


if __name__ == "__main__":
    main()
