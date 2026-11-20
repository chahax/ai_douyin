"""Independent reviewed-shot H3 consumer; never targets or resumes legacy jobs."""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.content_factory import visual_h3_handoff_v3 as flow
from src.content_factory import visual_image_jobs_v3 as jobs


def tick(run):
    result=flow.poll_collect(run)
    if result['status'] in ('blocked_upstream_changed','outcome_unknown','blocked_native_failure','media_review_required','paused'):
        return result
    return flow.submit_next(run)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','status','tick','run','pause','resume'])
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--asset-run',type=Path)
    parser.add_argument('--config',type=Path)
    parser.add_argument('--enable-video',action='store_true',help='Explicit new plan only; absent means no video POST')
    parser.add_argument('--operator',default='local_cli_owner')
    parser.add_argument('--interval',type=float,default=5)
    args=parser.parse_args(argv)
    if not 1<=args.interval<=60:raise ValueError('invalid_poll_interval')
    if args.action=='prepare':
        if not args.asset_run:raise ValueError('reviewed_asset_run_required')
        config=flow.read(args.config) if args.config else {}
        if config.get('video_enabled') not in (None,False) and not args.enable_video:
            raise ValueError('explicit_enable_video_flag_required')
        config['video_enabled']=args.enable_video
        result=flow.prepare_from_ready(args.asset_run,args.run,config)
    elif args.enable_video or args.config or args.asset_run:
        raise ValueError('policy_changes_require_new_prepare_plan')
    elif args.action=='status':result=flow.status(args.run)
    elif args.action in ('pause','resume'):
        result=flow.set_paused(args.run,args.action=='pause',actor=args.operator)
    elif args.action=='tick':result=tick(args.run)
    else:
        with jobs.run_lock(args.run,'WORKER.lock'):
            while True:
                result=tick(args.run)
                if result['status'] in ('blocked_upstream_changed','outcome_unknown','blocked_native_failure','media_review_required','paused') or result.get('dispatch')=='video_policy_disabled':break
                time.sleep(args.interval)
    print(json.dumps(result,ensure_ascii=True,indent=2))
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,OSError,KeyError) as error:
        print(json.dumps(dict(status='error',type=type(error).__name__,message=str(error)),ensure_ascii=True))
        raise SystemExit(2)
