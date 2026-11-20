"""Local prepare/status only; Root separately approves ARM and execution."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.operations_accounts import manual_republication_runtime_v4 as runtime

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('prepare');p.add_argument('--config',required=True);p.add_argument('--request',required=True);p.add_argument('--output-directory',required=True)
    p=sub.add_parser('status');p.add_argument('--plan',required=True);args=parser.parse_args(argv)
    value=runtime.prepare(runtime.reference(args.config),runtime.reference(args.request),args.output_directory) if args.action=='prepare' else runtime.status(runtime.reference(args.plan))
    print(json.dumps(value,ensure_ascii=False));return 0

if __name__=='__main__':raise SystemExit(main())
