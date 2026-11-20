"""Source-exact continuous text staging; media dispatch is a separate runner."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_continuous_stage_v6 as flow


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','plan','status','packet'])
    parser.add_argument('--run',type=Path,required=True);parser.add_argument('--home-run',type=Path);parser.add_argument('--baseline-asset-run',type=Path)
    parser.add_argument('--user-statement');parser.add_argument('--target-seconds',type=float,default=300);parser.add_argument('--tolerance',type=float,default=10)
    parser.add_argument('--output',type=Path);args=parser.parse_args()
    if args.action=='prepare':
        if not all((args.home_run,args.baseline_asset_run,args.user_statement)):parser.error('home-run, baseline-asset-run and user-statement required')
        result=flow.prepare(args.run,args.home_run,args.baseline_asset_run,user_statement=args.user_statement,target_seconds=args.target_seconds,tolerance=args.tolerance)
    elif args.action=='plan':result=flow.plan(args.run)
    elif args.action=='packet':
        result=flow.packet(args.run)
        if args.output:flow.files.freeze(args.output,result)
    else:result=flow.status(args.run)
    print(json.dumps(result,ensure_ascii=True,indent=2))


if __name__=='__main__':
    try:main()
    except (ValueError,OSError,KeyError) as error:
        print(json.dumps(dict(error=type(error).__name__,reason=str(error)),ensure_ascii=True));raise SystemExit(2)
