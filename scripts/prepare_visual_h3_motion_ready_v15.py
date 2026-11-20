"""Explicit ready-only motion-text commands. No media dispatch, no batch loop."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_h3_motion_ready_v15 as flow


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['status','prepare','plan'])
    parser.add_argument('--production-plan',type=Path,required=True);parser.add_argument('--shot-id',required=True)
    parser.add_argument('--run',type=Path,required=True);parser.add_argument('--user-statement')
    parser.add_argument('--known-predecessor',type=Path);parser.add_argument('--issue-file',type=Path)
    parser.add_argument('--frame-correction-proof',type=Path)
    parser.add_argument('--source-audio-insertion',action='store_true',default=None)
    parser.add_argument('--camera-contract',choices=[flow.native.CAMERA_CONTRACT_V19,flow.native.LEGACY_CAMERA_CONTRACT],default=flow.native.CAMERA_CONTRACT_V19)
    parser.add_argument('--camera-design',type=Path)
    parser.add_argument('--official-guide',type=Path,default=Path('data/visual_h3_native_prompts_v15/F0001_canary_20261107/official_VIDEO_PROMPT_WRITING_GUIDE_base_en.md'))
    args=parser.parse_args()
    if args.action=='prepare':
        if not args.user_statement:parser.error('user-statement required')
        if bool(args.known_predecessor)!=bool(args.issue_file):parser.error('known-predecessor and issue-file must be supplied together')
        issue=json.loads(args.issue_file.read_text(encoding='utf-8')) if args.issue_file else {}
        result=flow.prepare(args.production_plan,args.shot_id,args.run,user_statement=args.user_statement,official_guide_path=args.official_guide,
            known_predecessor=args.known_predecessor,known_issue=issue.get('issue'),issue_evidence=issue.get('source_evidence'),frame_correction_proof=args.frame_correction_proof,source_audio_insertion=args.source_audio_insertion,camera_contract=args.camera_contract,camera_design=flow.native._binding(args.camera_design) if args.camera_design else None)
    elif args.action=='plan':result=flow.plan(args.production_plan,args.shot_id,args.run)
    else:result=flow.status(args.production_plan,args.shot_id,args.run)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    try:main()
    except (ValueError,OSError,KeyError) as error:
        print(json.dumps(dict(error=type(error).__name__,message=str(error)),ensure_ascii=False));raise SystemExit(2)
