"""Prepare/plan one text-only H3 native-format canary; never submits media."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_h3_native_prompt_v15 as flow


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','plan','status','compile'])
    p.add_argument('--run',type=Path,required=True);p.add_argument('--parent',type=Path);p.add_argument('--packet',type=Path)
    p.add_argument('--asset-run',type=Path);p.add_argument('--user-statement');p.add_argument('--anchor-mode',choices=['first','first_last'])
    p.add_argument('--camera-contract',choices=[flow.CAMERA_CONTRACT_V19,flow.LEGACY_CAMERA_CONTRACT],default=flow.CAMERA_CONTRACT_V19)
    p.add_argument('--camera-design',type=Path)
    a=p.parse_args()
    if a.action=='prepare':
        if not all((a.parent,a.packet,a.asset_run,a.user_statement)):p.error('parent, packet, asset-run and user-statement required')
        result=flow.prepare(a.run,a.parent,a.packet,a.asset_run,user_statement=a.user_statement,camera_contract=a.camera_contract,camera_design=flow._binding(a.camera_design) if a.camera_design else None)
    elif a.action=='plan':result=flow.plan(a.run)
    elif a.action=='status':result=flow.status(a.run)
    else:
        state=flow.status(a.run);packet=flow._read_binding(state['plan']['packet']);shot=packet['shots'][0]
        entry=flow.load_for(packet,flow._binding(a.run/'NATIVE_PROMPT_PLAN.json'),shot)
        from src.content_factory.visual_h3_handoff_v3 import _timing
        mode=a.anchor_mode or ('first' if state['plan'].get('camera_contract')==flow.CAMERA_CONTRACT_V19 else 'first_last')
        result=flow.compile_for(shot,_timing(shot),entry,mode)
    print(result if isinstance(result,str) else json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    try:main()
    except (ValueError,OSError,KeyError) as error:
        print(json.dumps(dict(error=type(error).__name__,message=str(error)),ensure_ascii=False));raise SystemExit(2)
