"""One explicitly selected technical attempt of the authorized library minute."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_h3_library_attempts_v1 as adapter

PROJECT = Path(__file__).resolve().parents[1]
RUN = PROJECT / 'data/video_generation/h3_library_bound_minute_20261112_v1'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['initialize', 'routes', 'register-attempt', 'review-request',
        'prepare-video', 'status', 'video', 'collect', 'assemble'])
    parser.add_argument('--run', type=Path, default=RUN)
    parser.add_argument('--shot', choices=adapter.IDS)
    parser.add_argument('--terminal-history', type=Path)
    parser.add_argument('--controlled-abort-approval', type=Path)
    parser.add_argument('--queue-observation', type=Path)
    parser.add_argument('--confirmed-by')
    parser.add_argument('--evidence', action='append')
    parser.add_argument('--poll-seconds', type=int, default=30)
    parser.add_argument('--max-seconds', type=int, default=21600)
    args = parser.parse_args()
    if args.run.resolve() != RUN.resolve():
        parser.error('this CLI is scoped to the explicitly authorized fresh minute')
    if args.action == 'initialize': value = adapter.initialize(args.run)
    elif args.action == 'routes': value = adapter.resolve_routes(args.run)
    elif args.action == 'assemble': value = adapter.assemble(args.run)
    else:
        if args.shot is None: parser.error('this action requires --shot')
        if args.action == 'register-attempt':
            route = adapter.resolve_routes(args.run)['routes'][args.shot]
            if args.shot != 'S02' or route['attempt_id'] != 'A01':
                parser.error('this production recovery authorizes only S02 A01 to A02')
            if args.controlled_abort_approval:
                if args.terminal_history: parser.error('terminal history and controlled local abort are separate proof channels')
                proof = adapter.local_abort_proof(args.run, args.shot, args.controlled_abort_approval)
            else:
                if not all((args.terminal_history, args.queue_observation, args.confirmed_by, args.evidence)):
                    parser.error('actual terminal history, queue evidence and root confirmation are required')
                proof = adapter.terminal_proof(args.run, args.shot, args.terminal_history, args.queue_observation,
                    confirmed_by=args.confirmed_by, evidence=args.evidence)
            value = adapter.register_attempt(args.run, args.shot, proof)
        else:
            flow = adapter.routed_flow(args.run)
            if args.action == 'prepare-video': value = flow.prepare_video(args.run, args.shot, code_files=[adapter.__file__, __file__])
            elif args.action == 'video': value = flow.execute(args.run, args.shot, poll_seconds=args.poll_seconds, max_seconds=args.max_seconds)
            else: value = {'review-request': flow.review_request, 'status': flow.status, 'collect': flow.collect_known}[args.action](args.run, args.shot)
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    main()
