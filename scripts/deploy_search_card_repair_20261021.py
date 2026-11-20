"""One explicitly authorized manual-window disposition and guarded deployment."""
from contextlib import ExitStack
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "data/browser_lifecycle_repair/20261020"
ACCOUNT = "account:9e5f9e75192fa45becb945bc"
CID = "f4eafa4d7c5e48e4bc4643dc0dc640da"
OWNER = "backend:1504:f932f6a5957c46b38296bd30e4aa4837"


def main(execute=False):
    import psutil
    from scripts.handoff_idle_browser_control import assert_profile_exited
    from src.operations_accounts.browser_control import BrowserControlStore, _json
    from src.operations_accounts.publication_autonomous_reconciliation import unresolved
    from src.platform_adapter.browser_session import _PW_SCRIPT

    receipt = OUT / "SEARCH_DEPLOYMENT_INTENT.json"
    if receipt.exists():
        raise RuntimeError("Prior intent exists; inspect original outcome, never repeat")
    for name, expected in (("SEARCH_TEST_V1.xml", 71), ("SEARCH_TEST_V2.xml", 10)):
        suite = ET.parse(OUT / name).getroot().find("testsuite")
        if int(suite.attrib["tests"]) != expected or any(
                suite.attrib[key] != "0" for key in ("errors", "failures", "skipped")):
            raise RuntimeError("Successful regression evidence missing")
    previous = json.loads((OUT / "DEPLOYMENT_STOP_INTENT.json").read_text(encoding="utf8"))
    sources = set(previous["sources"]) | {"src/trend_intelligence/providers/douyin_web.py"}
    hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sorted(sources)}
    store = BrowserControlStore(ROOT / "data/account_browser_control.db")
    with ExitStack() as stack:
        def fence(name):
            db = stack.enter_context(sqlite3.connect(
                (ROOT / "data" / name).as_uri() + "?mode=rw", uri=True, timeout=5))
            db.row_factory = sqlite3.Row
            db.execute("BEGIN IMMEDIATE")
            return db
        plans = fence("account_refresh.db")
        control = dict(plans.execute("SELECT * FROM account_controls WHERE account_uuid=?", (ACCOUNT,)).fetchone())
        if control["state"] != "paused" or control["revision"] != 59 or control["recovery_token"]:
            raise RuntimeError("Original pause changed")
        for table in ("refresh_accounts", "smart_accounts", "playback_accounts"):
            if plans.execute(f"SELECT 1 FROM {table} WHERE run_id IS NOT NULL OR coalesce(lease_until,0)<>0").fetchone():
                raise RuntimeError("Business work remains")
        if plans.execute("SELECT 1 FROM account_handling_requests WHERE status IN ('requested','probing')").fetchone():
            raise RuntimeError("Recovery already pending")
        manual = fence("account_manual_windows.db")
        if manual.execute("SELECT 1 FROM manual_window_jobs WHERE state NOT IN ('closed','failed')").fetchone():
            raise RuntimeError("Other manual job remains")
        runtime = fence("douyin.db")
        if runtime.execute("SELECT 1 FROM account_runtime_state WHERE lock_owner!=''").fetchone():
            raise RuntimeError("Business runtime lease remains")
        profile = Path(runtime.execute(
            "SELECT browser_profile_dir FROM account_runtime_bindings WHERE account_uuid=?", (ACCOUNT,)).fetchone()[0]).resolve()
        with store._db(write=True) as db:
            pending = unresolved(store, db, ACCOUNT, ("queued", "running", "paused", "waiting_human", "outcome_unknown"))
            if len(pending) != 1 or pending[0]["command_id"] != CID:
                raise RuntimeError("Unexpected unresolved command")
            original = dict(db.execute("SELECT * FROM browser_control_commands WHERE command_id=?", (CID,)).fetchone())
            if (original["kind"] != "manual" or original["state"] != "outcome_unknown"
                    or original["owner_id"] != OWNER or original["generation"] != 39
                    or original["error_code"] != "handler_exception:BrowserNavigationTimeout"):
                raise RuntimeError("Original manual timeout changed")
            owner = dict(db.execute("SELECT * FROM browser_control_owners WHERE account_id=?", (ACCOUNT,)).fetchone())
            if owner["owner_id"] != OWNER or owner["generation"] != 39 or owner["state"] != "active":
                raise RuntimeError("Owner changed")
            proc = psutil.Process(1504)
            if (proc.create_time() != 1792511177.5618048 or Path(proc.cwd()).resolve() != ROOT
                    or str(ROOT / "scripts/run_streamlit_web.py").lower() not in [x.lower() for x in proc.cmdline()]
                    or int((ROOT / "data/logs/streamlit_web.pid").read_text()) != 1504):
                raise RuntimeError("Service identity changed")
            children = proc.children(recursive=True)
            identities = []
            worker_sha = hashlib.sha256(_PW_SCRIPT.encode()).hexdigest()
            for child in children:
                args, name = child.cmdline(), child.name().lower()
                if name in ("python.exe", "pythonw.exe"):
                    valid = (len(args) == 4 and args[1:3] == ["-S", "-c"]
                        and Path(args[0]).resolve() == ROOT / ".venv/Scripts" / name
                        and hashlib.sha256(args[3].encode()).hexdigest() == worker_sha)
                elif name == "node.exe":
                    valid = args == [str(ROOT / ".local_py/site-packages/playwright/driver/node.exe"),
                        str(ROOT / ".local_py/site-packages/playwright/driver/package/cli.js"), "run-driver"]
                elif name == "conhost.exe":
                    valid = child.parent().name().lower() == "node.exe"
                elif name == "chrome.exe":
                    valid = any(a.startswith("--user-data-dir=") and Path(a.split("=", 1)[1]).resolve() == profile for a in args)
                else:
                    valid = False
                if not valid or child.create_time() < proc.create_time():
                    raise RuntimeError("Unrelated child process; stop")
                identities.append(dict(pid=child.pid, created_at=child.create_time(), name=name))
            authorization = dict(user_response="允许处置并继续部署实测", command_id=CID,
                scope="Preserve original unknown; cancel this manual window; close its project browser; deploy; identity, search and feed tests",
                at=time.time())
            record = dict(phase="validated", authorization=authorization, original=original, owner=owner,
                service_pid=1504, service_created_at=proc.create_time(), children=identities,
                sources=hashes, pause_preserved=True, replay_original=False, at=time.time())
            if not execute:
                print(json.dumps({"validated": True, "children": len(children), "command_id": CID}))
                return
            record["phase"] = "stop_requested"
            receipt.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf8")
            proc.terminate()
            proc.wait(timeout=10)
            for child, identity in reversed(list(zip(children, identities))):
                try:
                    if child.create_time() != identity["created_at"]:
                        raise RuntimeError("Child PID reused")
                    child.terminate()
                except psutil.NoSuchProcess:
                    pass
            _, alive = psutil.wait_procs(children, timeout=10)
            if alive:
                raise RuntimeError("Observed child still alive; inspect, no cancellation committed")
            assert_profile_exited(profile)
            now = time.time()
            facts = dict(old_process_absent=True, profile_absent=True, leases_empty=True,
                manual_windows_closed=True, pause_preserved=True, children=identities)
            db.execute("""CREATE TABLE IF NOT EXISTS browser_control_operator_disposals(
                command_id TEXT PRIMARY KEY, original_command TEXT NOT NULL, original_owner TEXT NOT NULL,
                authorization TEXT NOT NULL, idle_evidence TEXT NOT NULL, disposed_at REAL NOT NULL)""")
            db.execute("INSERT INTO browser_control_operator_disposals VALUES(?,?,?,?,?,?)",
                (CID, _json(original), _json(owner), _json(authorization), _json(facts), now))
            result = dict(operator_cancelled_unknown_manual=True, original_outcome_known=False,
                original_snapshot_sha256=hashlib.sha256(_json(original).encode()).hexdigest(),
                cancelled_at=now, task_replayed=False)
            db.execute("UPDATE browser_control_commands SET state='failed',error_code='operator_cancelled_unknown_manual',result=?,updated_at=? WHERE command_id=?",
                (_json(result), now, CID))
            db.execute("UPDATE browser_control_owners SET state='released',updated_at=? WHERE account_id=? AND owner_id=? AND generation=39",
                (now, ACCOUNT, OWNER))
    record.update(phase="stopped_disposed_owner_released", completed_at=time.time())
    receipt.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps({"phase": record["phase"], "command_id": CID}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    main(parser.parse_args().execute)
