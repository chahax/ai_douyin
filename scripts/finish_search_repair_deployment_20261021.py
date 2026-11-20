"""Resume the verified idle service with original failures and corrected pause intact."""
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
OUT = ROOT / "data/browser_lifecycle_repair/20261020"
ACCOUNT = "account:9e5f9e75192fa45becb945bc"


def main():
    import psutil
    from src.operations_accounts.browser_control import BrowserControlStore, _json
    from src.operations_accounts.publication_autonomous_reconciliation import unresolved
    from src.scheduler.account_refresh import _pause, _smart_error_code
    from scripts.handoff_idle_browser_control import assert_profile_exited
    target = OUT / "FINAL_DEPLOYMENT_READY.json"
    if target.exists():
        raise RuntimeError("Original deployment receipt exists; do not repeat")
    migration = json.loads((OUT / "OFFLINE_WAL_MIGRATION_READY.json").read_text())
    assert migration["after_mode"] == "wal" and migration["backup_quick_check"] == "ok"
    assert migration["backup_byte_identical_verified"] is True
    assert migration["critical_tables_quick_check"] == {"browser_control_owners": "ok", "browser_control_commands": "ok"}
    suite = ET.parse(OUT / "VERIFICATION_PRIORITY_TEST.xml").getroot().find("testsuite")
    assert suite.attrib["tests"] == "61" and all(suite.attrib[k] == "0" for k in ("errors", "failures", "skipped"))
    latest = ET.parse(OUT / "VERIFICATION_PRIORITY_TEST_V2.xml").getroot().find("testsuite")
    assert latest.attrib["tests"] == "8" and all(latest.attrib[k] == "0" for k in ("errors", "failures", "skipped"))
    idle = ET.parse(OUT / "IDLE_HISTORY_TEST.xml").getroot().find("testsuite")
    assert int(idle.attrib["tests"]) >= 4 and all(idle.attrib[k] == "0" for k in ("errors", "failures", "skipped"))
    assert not psutil.pid_exists(25992)
    assert_profile_exited(ROOT / "data/douyin_warmup/accounts/account01/profile")
    sources = set(json.loads((OUT / "SEARCH_DEPLOYMENT_INTENT.json").read_text(encoding="utf8"))["sources"])
    sources.add("src/scheduler/account_refresh.py")
    hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sorted(sources)}
    store = BrowserControlStore(ROOT / "data/account_browser_control.db")
    with ExitStack() as stack:
        def fence(name):
            db = stack.enter_context(sqlite3.connect((ROOT / "data" / name).as_uri() + "?mode=rw", uri=True, timeout=5))
            db.row_factory = sqlite3.Row
            db.execute("BEGIN IMMEDIATE")
            return db
        plans = fence("account_refresh.db")
        control = dict(plans.execute("SELECT * FROM account_controls WHERE account_uuid=?", (ACCOUNT,)).fetchone())
        assert control["state"] == "paused" and control["revision"] == 62 and not control["recovery_token"]
        for table in ("refresh_accounts", "smart_accounts", "playback_accounts"):
            assert not plans.execute(f"SELECT 1 FROM {table} WHERE run_id IS NOT NULL OR coalesce(lease_until,0)<>0").fetchone()
        runtime = fence("douyin.db")
        assert not runtime.execute("SELECT 1 FROM account_runtime_state WHERE lock_owner!=''").fetchone()
        with store._db(write=True) as db:
            assert not unresolved(store, db, ACCOUNT, ("queued", "running", "paused", "waiting_human", "outcome_unknown"))
            owner = dict(db.execute("SELECT * FROM browser_control_owners WHERE account_id=?", (ACCOUNT,)).fetchone())
            assert owner["owner_id"] == "backend:25992:c13d9cf0a6714139a4869c69ce007679" and owner["generation"] == 40
            command = dict(db.execute("SELECT * FROM browser_control_commands WHERE command_id='4609be5484634f7aa56e530fb3381ca6'").fetchone())
            assert command["state"] == "failed"
            receipt = json.loads(command["result"])["maintenance_result"]
            code = _smart_error_code({"maintenance_log": receipt["log_path"], "maintenance_run_id": receipt["run_id"],
                                     "error_code": receipt["error_code"]}, "account01")
            assert code == "human_required"
            record = dict(at=time.time(), owner_before=owner, control_before=control, sources=hashes,
                observed_command_id=command["command_id"], original_result_preserved=True,
                pause_reason_code=code, migration="OFFLINE_WAL_MIGRATION_READY.json")
            plans.execute("""CREATE TABLE IF NOT EXISTS browser_repair_pause_audit(
                repair_id TEXT PRIMARY KEY, evidence TEXT NOT NULL, created_at REAL NOT NULL)""")
            plans.execute("INSERT INTO browser_repair_pause_audit VALUES(?,?,?)",
                          ("search-card-repair-20261021", _json(record), time.time()))
            _pause(plans, ACCOUNT, "account01",
                "本轮搜索已连续确认平台验证码；后续作品同步失败不解除验证暂停。请完成原账号验证后申请恢复。",
                code, time.time())
            db.execute("""CREATE TABLE IF NOT EXISTS browser_control_idle_deploy_audit(
                deployment_id TEXT PRIMARY KEY,evidence TEXT NOT NULL,retired_at REAL NOT NULL)""")
            db.execute("INSERT INTO browser_control_idle_deploy_audit VALUES(?,?,?)",
                       ("search-priority-repair-20261021-gen40", _json(record), time.time()))
            db.execute("UPDATE browser_control_owners SET state='released',updated_at=? WHERE account_id=? AND generation=40",
                       (time.time(), ACCOUNT))
    record["phase"] = "idle_owner_released_verification_pause_preserved"
    target.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps({"phase": record["phase"], "code": code}))


if __name__ == "__main__":
    main()
