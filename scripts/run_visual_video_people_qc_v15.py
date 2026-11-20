"""Standalone sampled-people brake. Never dispatches media or resumes H3."""
import argparse
import json
import subprocess
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_video_people_qc_v15 as flow


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','observe','apply','worker'])
    parser.add_argument('--run',type=Path);parser.add_argument('--h3-run',type=Path);parser.add_argument('--packet',type=Path);parser.add_argument('--objective-qa',type=Path)
    parser.add_argument('--request',type=Path);parser.add_argument('--output',type=Path);args=parser.parse_args()
    if args.action=='worker':
        if not args.request or not args.output:parser.error('worker requires request/output')
        flow._worker(args.request,args.output);return 0
    if not args.run:parser.error('run is required')
    if args.action=='prepare':
        if not all((args.h3_run,args.packet,args.objective_qa)):parser.error('prepare requires h3-run/packet/objective-qa')
        result=flow.prepare(args.run,args.h3_run,args.packet,args.objective_qa)
    elif args.action=='observe':result=flow.observe(args.run)
    else:result=flow.apply(args.run)
    print(json.dumps(result,ensure_ascii=True,indent=2))
    if args.action=='apply':return 4 if result['hard_reject'] else 5 if result['decision']=='needs_review_unknown' else 0
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,OSError,KeyError,RuntimeError,subprocess.SubprocessError) as error:
        print(json.dumps(dict(error=type(error).__name__,reason=str(error)),ensure_ascii=True));raise SystemExit(2)
