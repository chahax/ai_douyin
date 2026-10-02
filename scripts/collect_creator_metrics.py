"""Collect bound-account creator metrics using the existing authenticated runtime."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    from src.operations_accounts import AccountRuntimeService
    from src.platform_adapter.douyin_adapter import DouyinAdapter

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--account', required=True)
    parser.add_argument('--pages', type=int, default=5, choices=range(1, 51))
    args = parser.parse_args()
    runtime = AccountRuntimeService()
    context = runtime.resolve(args.account)
    with runtime.operation_lease(context, operation='creator_metrics', daily_limit=100,
                                 cooldown_seconds=60, lock_seconds=1800):
        adapter = DouyinAdapter(session=context.create_browser_session(headless=True), runtime_context=context)
        try:
            result = adapter.sync_videos(page_limit=args.pages)
            print(json.dumps({'success': result.success, 'status': result.status,
                              'count': len(result.videos), 'message': result.message}, ensure_ascii=False))
            return 0 if result.success else 1
        finally:
            adapter.close()


if __name__ == '__main__':
    raise SystemExit(main())
