"""Compile/verify offline H3 inputs. This command has no production action."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='action',required=True)
    prep=commands.add_parser('prepare');prep.add_argument('--spec',type=Path,required=True);prep.add_argument('--out',type=Path,required=True)
    verify=commands.add_parser('validate');verify.add_argument('--out',type=Path,required=True)
    args=parser.parse_args(argv)
    from src.content_factory import h3_asset_flow_v2 as flow
    value=flow.prepare(args.spec,args.out) if args.action=='prepare' else flow.validate(args.out)
    print(json.dumps(value,ensure_ascii=False,indent=2))

if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    main()
