"""Generic opt-in pre-video narration agent; no video or account actions."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.content_factory import narration_prevideo_agent_v1 as agent
from src.content_factory import narration_placement_policy_v2 as policy


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['prepare','run'])
    parser.add_argument('--run',type=Path,required=True);parser.add_argument('--spec',type=Path)
    args=parser.parse_args(argv)
    if args.action=='prepare':
        if args.spec is None:parser.error('prepare requires --spec')
        value=agent.prepare(args.run,policy.read(args.spec))
    else:value=agent.execute(args.run)
    print(json.dumps(value,ensure_ascii=False,indent=2))


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    main()
