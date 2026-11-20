"""Clear a legacy account circuit only with verified successful backend-sync evidence."""

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
    audit_path = output_dir / "runtime_circuit_reconciliation_20260921.json"
    if audit_path.exists():
        raise RuntimeError("该旧版误熔断已经校正并保存凭据，拒绝重复修改运行状态。")

    log_root = ROOT / "data" / "account_maintenance" / args.account
    evidence = None
    evidence_path = None
    for path in sorted(log_root.glob("maintenance_*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        row = json.loads(path.read_text(encoding="utf-8"))
        if (
            row.get("status") == "partial"
            and row.get("login_healthy") is True
            and row.get("published_data_sync_completed") is True
            and int(row.get("comment_sync_failures") or 0) > 0
        ):
            evidence = row
            evidence_path = path
            break
    if evidence is None or evidence_path is None:
        raise RuntimeError("没有找到可证明后台数据同步成功的旧版评论失败记录。")

    db_path = ROOT / "data" / "douyin.db"
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    try:
        state = db.execute(
            "SELECT * FROM account_runtime_state WHERE account_uuid=?",
            (evidence["account_uuid"],),
        ).fetchone()
        if state is None:
            raise RuntimeError("账号运行状态不存在。")
        if state["lock_owner"]:
            raise RuntimeError("账号仍有任务持锁，不能校正熔断。")
        before = dict(state)
        reconciled_at = datetime.now(timezone.utc).isoformat()
        db.execute(
            """UPDATE account_runtime_state
               SET consecutive_failures=0, circuit_open_until='', updated_at=?
               WHERE account_uuid=?""",
            (reconciled_at, evidence["account_uuid"]),
        )
        db.commit()
        after = dict(db.execute(
            "SELECT * FROM account_runtime_state WHERE account_uuid=?",
            (evidence["account_uuid"],),
        ).fetchone())
    finally:
        db.close()

    audit_path.write_text(json.dumps({
        "reason": "legacy comment sync failure incorrectly counted as full maintenance failure",
        "evidence_run_id": evidence["run_id"],
        "evidence_log": str(evidence_path),
        "before": before,
        "after": after,
        "reconciled_at": reconciled_at,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "audit": str(audit_path),
        "before_failures": before["consecutive_failures"],
        "after_failures": after["consecutive_failures"],
        "circuit_open_until": after["circuit_open_until"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
