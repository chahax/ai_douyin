"""Preview, or explicitly settle one fully ended zero-playback failure."""
import argparse
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description='仅对账完整已知失败的零播放初态，不恢复/重派任何任务。')
    for name in ('command-id', 'account-id', 'account-key', 'owner-id', 'receipt', 'receipt-sha256', 'legacy-run-id'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--generation', required=True, type=int)
    parser.add_argument('--audit-dir')
    parser.add_argument('--apply', action='store_true', help='默认只读预检；此开关仅将精确原paused结清为failed。')
    args = parser.parse_args()
    from src.operations_accounts.browser_control import BrowserControlStore
    from src.operations_accounts.known_zero_playback_reconciliation import reconcile_known_zero_playback
    db_path = ROOT / 'data/account_browser_control.db'
    if not db_path.is_file():
        raise RuntimeError('原管控库缺失，不创建或初始化新库')
    audit_dir = Path(args.audit_dir) if args.audit_dir else (
        ROOT / 'data/browser_control_reconciliations' / args.command_id / uuid.uuid4().hex)
    report = reconcile_known_zero_playback(BrowserControlStore(db_path), args.command_id,
        account_id=args.account_id, account_key=args.account_key, owner_id=args.owner_id,
        generation=args.generation, receipt_path=args.receipt, receipt_sha256=args.receipt_sha256,
        legacy_run_id=args.legacy_run_id, scheduler_db=ROOT / 'data/account_refresh.db',
        runtime_db=ROOT / 'data/douyin.db', audit_dir=audit_dir, apply=args.apply, workspace_root=ROOT)
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
