"""Explicit opt-in executable repair loop; adapter methods may have side effects."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.content_factory import media_repair_loop_v1 as loop


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'step', 'drive', 'status', 'review'))
    parser.add_argument('--run', required=True)
    parser.add_argument('--spec')
    parser.add_argument('--attempt')
    parser.add_argument('--review')
    parser.add_argument('--execute', action='store_true', help='Explicitly authorize invoking the pinned adapter methods')
    parser.add_argument('--max-steps', type=int, default=12)
    args = parser.parse_args(argv)
    run = Path(args.run).resolve()
    if args.action == 'prepare':
        loop.require(args.spec, 'explicit_spec_file_required')
        result = loop.prepare(run, loop.bind(Path(args.spec).resolve()))
    elif args.action == 'status':
        result = loop.status(run)
    elif args.action == 'review':
        loop.require(args.attempt and args.review, 'explicit_fresh_attempt_and_review_file_required')
        result = loop.record_review(run, args.attempt, loop.bind(Path(args.review).resolve()))
    else:
        loop.require(args.execute, 'explicit_execute_flag_required_to_invoke_adapters')
        adapters = loop.load_adapters(run)
        result = (loop.step(run, **adapters) if args.action == 'step'
                  else loop.drive(run, **adapters, max_steps=args.max_steps))
    # Keep catalogs, request prompts and provenance in files, not giant stdout.
    summary = {k: v for k, v in result.items() if k in ('status', 'phase', 'reason', 'attempt_id', 'native_id', 'file', 'clock', 'plan', 'notice', 'receipt')}
    print(json.dumps(summary, ensure_ascii=False))
    return result


if __name__ == '__main__':
    main()
