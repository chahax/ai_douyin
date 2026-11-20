"""Explicit reference-H3 entry; status/prepare do not submit media."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_h3_reference_delivery_v20 as flow


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('prepare','status','submit','poll','execute','pause','resume'))
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--asset-run',type=Path)
    parser.add_argument('--shot-id')
    parser.add_argument('--source-prompt',type=Path)
    parser.add_argument('--config',type=Path)
    parser.add_argument('--poll-seconds',type=float,default=30)
    parser.add_argument('--max-seconds',type=float,default=86400)
    args=parser.parse_args(argv)
    if args.command=='prepare':
        if not args.asset_run:parser.error('prepare requires --asset-run')
        if args.source_prompt and not args.shot_id:parser.error('--source-prompt requires --shot-id')
        cfg=flow.native.read(args.config) if args.config else None
        result=flow.prepare(args.asset_run,args.run,cfg,shot_id=args.shot_id,
            source_prompts={args.shot_id:args.source_prompt} if args.source_prompt else None)
    elif args.command=='execute':
        result=flow.execute(args.run,poll_seconds=args.poll_seconds,max_seconds=args.max_seconds)
    elif args.command in ('pause','resume'):
        result=flow.set_paused(args.run,args.command=='pause')
    else:result=getattr(flow,{'submit':'submit_next','poll':'poll_collect'}.get(args.command,args.command))(args.run)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    main()
