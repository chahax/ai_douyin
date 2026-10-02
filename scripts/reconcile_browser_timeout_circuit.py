"""Clear the one-time circuit created while repairing browser start timeouts."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", required=True)
    args = parser.parse_args()
    output_dir = ROOT / "data" / "smart_operations" / args.account
    output_dir.mkdir(parents=True, exist_ok=True)
    audit_path = output_dir / "runtime_browser_timeout_reconciliation_20260921.json"
    if audit_path.exists():
        raise RuntimeError("该浏览器启动故障已校正，拒绝重复修改运行状态。")

    logs = sorted(
        (ROOT / "data" / "account_maintenance" / args.account).glob("maintenance_*.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    evidence_path = next((path for path in logs if (
        (row := json.loads(path.read_text(encoding="utf-8"))).get("status") == "failed"
        and "TimeoutError" in str(row.get("message") or "")
        and "start" in str(row.get("message") or "")
    )), None)
    if evidence_path is None:
        raise RuntimeError("没有找到浏览器启动超时的失败记录。")
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

    db = sqlite3.connect(ROOT / "data" / "douyin.db")
    db.row_factory = sqlite3.Row
    try:
        state = db.execute(
            "SELECT * FROM account_runtime_state WHERE account_uuid=?",
            (evidence["account_uuid"],),
        ).fetchone()
        if state is None or state["lock_owner"]:
            raise RuntimeError("账号状态不存在或仍有任务持锁。")
        before = dict(state)
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            """UPDATE account_runtime_state
               SET consecutive_failures=0, circuit_open_until='', updated_at=?
               WHERE account_uuid=?""",
            (now, evidence["account_uuid"]),
        )
        db.commit()
        after = dict(db.execute(
            "SELECT * FROM account_runtime_state WHERE account_uuid=?",
            (evidence["account_uuid"],),
        ).fetchone())
    finally:
        db.close()
    audit_path.write_text(json.dumps({
        "reason": "browser subprocess start timeout repaired with bounded startup and ephemeral headless context",
        "evidence_log": str(evidence_path),
        "before": before,
        "after": after,
        "reconciled_at": now,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"audit": str(audit_path), "after": after}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
