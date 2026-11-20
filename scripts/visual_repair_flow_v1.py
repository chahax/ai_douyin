"""File-based independent entry point: plan/apply only; no GPU or account calls."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory.visual_repair_flow_v1 import plan, apply


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('operation',choices=['plan','apply'])
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:
        project=json.loads(args.project.read_text(encoding='utf-8'))
        other=json.loads(args.input.read_text(encoding='utf-8'))
        result=(plan if args.operation=='plan' else apply)(project,other)
        # Exclusive create: an old result can never be overwritten by a new run.
        with args.output.open('x',encoding='utf-8') as f:
            json.dump(result,f,ensure_ascii=False,indent=2)
    except (ValueError,KeyError,TypeError,OSError) as error:
        print(json.dumps(dict(status='rejected',reason=str(error)),ensure_ascii=False))
        return 2
    print(json.dumps(dict(status='saved',output=str(args.output)),ensure_ascii=False))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
