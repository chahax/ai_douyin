"""Independent serial novel workflow. Local prepare does not authorize cloud calls."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.content_factory import serial_story_production_v1 as p
from src.content_factory import serial_story_production_v2 as v2
from src.content_factory import serial_story_production_v6 as v6
from src.content_factory.corpus_screenplay_v1 import read


def implementation_for(run):
    version = read(Path(run)/'PLAN.json')['version']
    implementations = {p.VERSION:p, v2.VERSION:v2, v6.VERSION:v6}
    if version not in implementations: raise ValueError('unsupported_frozen_version')
    return implementations[version]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action', choices=['prepare', 'authorize', 'execute', 'status'])
    ap.add_argument('--run', required=True)
    ap.add_argument('--manifest'); ap.add_argument('--statement'); ap.add_argument('--scope-file')
    ap.add_argument('--max-calls', type=int, default=400)
    ap.add_argument('--episode-limit', type=int, default=2)
    ap.add_argument('--shot-seconds', type=int, default=15)
    ap.add_argument('--resume', action='store_true')
    ap.add_argument('--workflow', choices=['v2', 'scoped-v6'], default='v2',
                    help='New prepares only. scoped-v6 uses episode/scene-specific fact gates.')
    args = ap.parse_args()
    if args.action == 'prepare':
        if not args.manifest or not args.statement: ap.error('prepare requires manifest and statement')
        implementation = v6 if args.workflow == 'scoped-v6' else v2
        result = implementation.prepare(args.manifest, args.run, user_statement=args.statement,
                           max_calls=args.max_calls, episode_limit=args.episode_limit, shot_seconds=args.shot_seconds)
    elif args.action == 'authorize':
        if not args.scope_file: ap.error('authorize requires explicit scope file')
        implementation = implementation_for(args.run)
        implementation.authorize(args.run, read(args.scope_file)); result = {'authorization_recorded': True, 'calls_started': 0}
    elif args.action == 'execute':
        implementation = implementation_for(args.run)
        if args.resume and implementation is p: ap.error('v1 has no resume support')
        result = implementation.execute(args.run, **({'resume':args.resume} if implementation in (v2, v6) else {}))
    else: result = read(Path(args.run)/'STATE.json')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.action == 'execute' and result['error']: raise SystemExit(1)


if __name__ == '__main__': main()
