"""Explicit audio-only trial prepare/execute/status; never H3 or assembly."""
import argparse
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.content_factory import audio_full_scope_v1 as scope
from src.content_factory import audio_quality_execution_v1 as execution


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('prepare')
    prepare.add_argument('--run', required=True, type=Path)
    prepare.add_argument('--input', required=True, type=Path)
    for command in ('execute', 'status'):
        item = commands.add_parser(command)
        item.add_argument('--run', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        run = args.run.resolve()
        if args.command == 'prepare':
            result = execution.prepare(run, scope.bind(args.input.resolve()))
        else:
            result = getattr(execution, args.command)(run)
        print(json.dumps(dict(ok=True, command=args.command, result=result), ensure_ascii=False))
        return 0
    except Exception as error:
        print(json.dumps(dict(ok=False, command=args.command,
            error=dict(type=type(error).__name__, message=str(error)),
            H3_generation_performed=False, automatic_retry=False), ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
