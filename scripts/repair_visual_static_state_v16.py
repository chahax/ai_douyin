"""Independent source-state r2 text successors; no media dispatch."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_static_state_repair_v16 as flow


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','plan','status'])
    parser.add_argument('--run',type=Path,required=True);parser.add_argument('--static-run',type=Path)
    parser.add_argument('--targets',type=Path);parser.add_argument('--authorization',type=Path)
    a=parser.parse_args()
    if a.action=='prepare':
        if not all((a.static_run,a.targets,a.authorization)):parser.error('static-run, targets and authorization required')
        targets=json.loads(a.targets.read_text(encoding='utf-8'));authorization=json.loads(a.authorization.read_text(encoding='utf-8'))
        result=flow.prepare(a.run,a.static_run,targets,root_authorization=authorization['root_authorization'])
    elif a.action=='plan':result=flow.plan(a.run)
    else:result=flow.status(a.run)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    try:main()
    except (ValueError,OSError,KeyError) as error:
        print(json.dumps(dict(error=type(error).__name__,message=str(error)),ensure_ascii=False));raise SystemExit(2)
