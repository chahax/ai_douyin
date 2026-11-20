"""Explicit original-work recheck; no uploader, actor launch or service change."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def reference(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def main(argv=None):
    from src.operations_accounts import publication_recheck_request_v1 as api
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'enqueue', 'status'])
    parser.add_argument('--report', type=Path)
    parser.add_argument('--request', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    if args.action == 'prepare':
        if not args.report or not args.output or args.request:
            parser.error('prepare requires --report/--output only')
        result = api.prepare(reference(args.report), output_path=args.output)
    else:
        if not args.request or args.report or args.output:
            parser.error('enqueue/status require --request only')
        result = getattr(api, args.action)(reference(args.request))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == '__main__':
    main()
