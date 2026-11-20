"""Explicit local experiment entry. prepare/status never dispatch media."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_h3_prompt_parity_v19 as parity


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'execute', 'status', 'assemble', 'qa'))
    parser.add_argument('--run', type=Path, default=parity.RUN)
    parser.add_argument('--through', choices=parity.IDS, default='S04')
    parser.add_argument('--poll-seconds', type=float, default=30)
    parser.add_argument('--max-seconds', type=float, default=86400)
    args = parser.parse_args()
    if args.command == 'execute':
        value = parity.execute(args.run, through=parity.IDS.index(args.through) + 1,
                               poll_seconds=args.poll_seconds, max_seconds=args.max_seconds)
        if value['technical_saved'] == 4 and args.through == 'S04':
            value['assembly'] = parity.assemble(args.run)
    else:
        value = getattr(parity, args.command)(args.run)
    print(json.dumps(value, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
