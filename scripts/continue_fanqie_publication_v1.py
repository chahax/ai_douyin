"""Explicit, bounded continuation of an already existing publication only."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.services.fanqie_promotion_workspace_v1 import PromotionWorkspace, CLOSED_LOOP_DB_PATH
from src.services.fanqie_publication_continuation_v1 import PublicationContinuation, file_ref, TERMINAL


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'step', 'status', 'run'))
    parser.add_argument('--directory', required=True, type=Path)
    parser.add_argument('--spec', type=Path)
    parser.add_argument('--ledger', type=Path, default=CLOSED_LOOP_DB_PATH)
    parser.add_argument('--max-wait-seconds', type=int, default=60)
    args = parser.parse_args(argv)
    if not 1 <= args.max_wait_seconds <= 3600:
        parser.error('--max-wait-seconds must be 1..3600')
    runner = PublicationContinuation(args.directory, workspace=PromotionWorkspace(args.ledger))
    if args.action == 'prepare':
        if args.spec is None:
            parser.error('prepare requires --spec')
        result = runner.prepare(file_ref(args.spec))
    elif args.action == 'run':
        deadline = time.monotonic() + args.max_wait_seconds
        while True:
            result = runner.step()
            if result['phase'] in TERMINAL or time.monotonic() >= deadline:
                break
            time.sleep(min(2, max(0, deadline - time.monotonic())))
    else:
        result = getattr(runner, args.action)()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == '__main__':
    main()
