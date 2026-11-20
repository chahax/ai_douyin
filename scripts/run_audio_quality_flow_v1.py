"""Plan reusable audio quality routing; no media/model execution commands."""
import argparse
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from src.content_factory import audio_full_scope_v1 as scope
from src.content_factory import audio_quality_flow_v1 as flow


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    inspect = commands.add_parser('verify-scope', help='Verify existing full-waveform ASR evidence, offline')
    inspect.add_argument('--candidate', type=Path, required=True)
    inspect.add_argument('--asr-receipt', type=Path, required=True)
    inspect.add_argument('--output', type=Path, required=True)
    plan = commands.add_parser('plan', help='Route every declared segment without execution')
    plan.add_argument('--manifest', type=Path, required=True)
    plan.add_argument('--run', type=Path, required=True)
    current = commands.add_parser('status', help='Recheck frozen route inputs and internal evidence')
    current.add_argument('--run', type=Path, required=True)
    cleanup = commands.add_parser('prepare-cleanup', help='Compile an eligible CPU cleanup job, no editing')
    cleanup.add_argument('--run', type=Path, required=True)
    cleanup.add_argument('--segment-id', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'verify-scope':
            proof = scope.verify(scope.bind(args.asr_receipt.resolve()), scope.bind(args.candidate.resolve()))
            result = dict(status=proof['status'], proof=flow.freeze(args.output.resolve(), proof))
        elif args.command == 'plan':
            result = flow.prepare_batch(args.run.resolve(), scope.bind(args.manifest.resolve()))
        elif args.command == 'status':
            result = flow.status(args.run.resolve())
        else:
            result = flow.prepare_cleanup(args.run.resolve(), args.segment_id)
        print(json.dumps(dict(ok=True, command=args.command, result=result), ensure_ascii=False))
    except Exception as error:
        print(json.dumps(dict(ok=False, command=args.command,
            error=dict(type=type(error).__name__, message=str(error)),
            media_execution_performed=False), ensure_ascii=False))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
