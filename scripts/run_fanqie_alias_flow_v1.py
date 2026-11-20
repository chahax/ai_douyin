"""Prepare/advance/read the durable dedicated-account Fanqie alias flow."""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.services.fanqie_alias_flow_v1 import AliasFlow, TERMINAL
from src.services.fanqie_promotion_workspace_v1 import PromotionWorkspace, ref, CLOSED_LOOP_DB_PATH


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'step', 'status', 'run'))
    parser.add_argument('--directory', required=True, type=Path)
    parser.add_argument('--spec', type=Path)
    parser.add_argument('--ledger', type=Path, default=CLOSED_LOOP_DB_PATH)
    parser.add_argument('--max-wait-seconds', type=int, default=900)
    args = parser.parse_args(argv)
    if (args.action == 'prepare') != (args.spec is not None):
        parser.error('--spec is required only for prepare')
    if not 1 <= args.max_wait_seconds <= 3600:
        parser.error('--max-wait-seconds must be between 1 and 3600')
    flow = AliasFlow(args.directory, workspace=PromotionWorkspace(args.ledger))
    if args.action == 'run':
        deadline = time.monotonic() + args.max_wait_seconds
        while True:
            result = flow.step()
            if result['phase'] in TERMINAL or time.monotonic() >= deadline:
                break
            time.sleep(2)
    else:
        result = flow.prepare(ref(args.spec)) if args.action == 'prepare' else getattr(flow, args.action)()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == '__main__':
    main()
