"""Prepare/status only; never ARM, upload, select declarations, or publish."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.operations_accounts import manual_republication_runtime_v2 as runtime


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    prepare = sub.add_parser('prepare')
    prepare.add_argument('--config', required=True)
    prepare.add_argument('--request', required=True)
    prepare.add_argument('--output-directory', required=True)
    status = sub.add_parser('status')
    status.add_argument('--plan', required=True)
    args = parser.parse_args(argv)
    result = (runtime.prepare(runtime.reference(args.config), runtime.reference(args.request), args.output_directory)
              if args.action == 'prepare' else runtime.status(runtime.reference(args.plan)))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
