"""Plan independent static first frames without dispatching media."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_static_start_planner_v13 as flow


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','plan','status'])
    parser.add_argument('--run',type=Path,required=True);parser.add_argument('--production-plan',type=Path)
    parser.add_argument('--user-statement');parser.add_argument('--shot-ids');args=parser.parse_args()
    if args.action=='prepare':
        if not args.production_plan or not args.user_statement:parser.error('production-plan and user-statement required')
        value=flow.prepare(args.run,args.production_plan,user_statement=args.user_statement)
    elif args.action=='plan':value=flow.plan(args.run,shot_ids=args.shot_ids.split(',') if args.shot_ids else None)
    else:value=flow.status(args.run)
    print(json.dumps(value,ensure_ascii=True,indent=2))


if __name__=='__main__':
    try:main()
    except (ValueError,OSError,KeyError) as error:
        print(json.dumps(dict(error=type(error).__name__,message=str(error)),ensure_ascii=True));raise SystemExit(2)
