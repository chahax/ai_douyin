"""Shared residence style planning; no images/video dispatched by this CLI."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_residence_plan_v5 as flow


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','plan','status','packet','background-packet'])
    parser.add_argument('--run',type=Path,required=True);parser.add_argument('--origin-run',type=Path)
    parser.add_argument('--home-id');parser.add_argument('--place-ids');parser.add_argument('--master-place-id')
    parser.add_argument('--user-statement');parser.add_argument('--novel-source',type=Path,action='append',default=[])
    parser.add_argument('--config',type=Path);parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.action=='prepare':
        if not all((args.origin_run,args.home_id,args.place_ids,args.master_place_id,args.user_statement)):
            parser.error('origin-run, home-id, place-ids, master-place-id and user-statement required')
        result=flow.prepare(args.run,args.origin_run,home_id=args.home_id,place_ids=args.place_ids.split(','),
            master_place_id=args.master_place_id,user_statement=args.user_statement,novel_sources=args.novel_source,
            config=flow.files.read(args.config) if args.config else None)
    elif args.action=='plan':result=flow.plan(args.run)
    elif args.action in ('packet','background-packet'):
        result=flow.background_packet(args.run) if args.action=='background-packet' else flow.packet(args.run)
        if args.output:flow.files.freeze(args.output,result)
    else:result=flow.status(args.run)
    print(json.dumps(result,ensure_ascii=True,indent=2))


if __name__=='__main__':
    try:main()
    except (ValueError,OSError,KeyError) as error:
        print(json.dumps(dict(error=type(error).__name__,reason=str(error)),ensure_ascii=True));raise SystemExit(2)
