"""One approved clip or a bounded, original-ID, GET-only wait with exit evidence."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import sys
import time
import traceback
import urllib.error

PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))


def _parser():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','submit','collect','status','wait'])
    parser.add_argument('--route',choices=['library','asset'],required=True)
    parser.add_argument('--run',type=Path,required=True);parser.add_argument('--policy',type=Path,required=True)
    parser.add_argument('--scene-reuse-approval',type=Path)
    parser.add_argument('--shot');parser.add_argument('--draft',type=Path);parser.add_argument('--config',type=Path)
    parser.add_argument('--prompt-profiles',type=Path);parser.add_argument('--authorization',type=Path)
    parser.add_argument('--prompt-id');parser.add_argument('--poll-seconds',type=int,default=30)
    parser.add_argument('--max-seconds',type=int,default=21600)
    return parser


def _api(args):
    from src.content_factory import h3_universal_direction_execution_v1 as v1
    from src.content_factory import h3_universal_direction_execution_v2 as v2
    from src.content_factory import h3_asset_flow_v2 as flow
    policy=flow.bind(args.policy)
    if args.route=='asset':return v1.asset_for_run(args.run,policy)
    if args.scene_reuse_approval is not None:
        return v2.library_for_run(args.run,policy,flow.bind(args.scene_reuse_approval))
    return v1.library_for_run(args.run,policy)


def _call(api,args,name):
    return getattr(api,name)(args.run,args.shot) if args.route=='library' else getattr(api,name)(args.run)


def _wait(args):
    from src.content_factory import h3_asset_flow_v2 as flow
    evidence=args.run/'collectors'/('cli_v2_'+str(os.getpid())+'_'+str(time.time_ns()))
    started=time.monotonic();final=None;exit_code=3;fatal=False;phase='factory';errors=0
    flow.freeze(evidence/'START.json',dict(schema='universal_CLI_wait/v2',pid=os.getpid(),
        original_prompt_id=args.prompt_id,run=str(args.run),shot=args.shot,route=args.route,
        collector=flow.bind(__file__),started_at_utc=datetime.now(timezone.utc).isoformat(),
        poll_seconds=args.poll_seconds,max_seconds=args.max_seconds,HTTP_method='GET_ONLY',rePOST_allowed=False))
    try:
        api=_api(args);phase='state_identity'
        native=api.native_run(args.run,args.shot) if args.route=='library' else args.run
        shot=args.shot if args.route=='library' else flow.read(args.run/'PLAN.json')['shots'][0]['id']
        state_path=native/'shots'/shot/'STATE.json'
        flow.freeze(evidence/'TARGET.json',dict(native_run=str(native),shot=shot,state_path=str(state_path)))
        state=flow.read(state_path)
        if state.get('prompt_id')!=args.prompt_id:raise ValueError('only_original_returned_UUID_allowed')
        if state.get('status')=='outcome_unknown':
            final=dict(status='outcome_unknown',original_prompt_id=args.prompt_id,unknown_record_preserved=True)
        last=-300;previous=None
        while final is None and time.monotonic()-started<args.max_seconds:
            phase='state_identity'
            if flow.read(state_path).get('prompt_id')!=args.prompt_id:raise ValueError('original_UUID_changed_during_wait')
            phase='collect_known_GET'
            try:result=_call(api,args,'collect_known')
            except (OSError,TimeoutError,urllib.error.URLError,json.JSONDecodeError) as error:
                errors+=1
                flow.freeze(evidence/'errors'/f'{time.time_ns()}.json',dict(type=type(error).__name__,message=str(error),
                    traceback=traceback.format_exc(),phase=phase,rePOST=False))
                if errors>=10:final=dict(status='collector_GET_errors',original_prompt_id=args.prompt_id)
            else:
                errors=0;current=result.get('shot',result);status=current.get('status',result.get('status'))
                elapsed=round(time.monotonic()-started)
                if status!=previous or elapsed-last>=300:
                    print(json.dumps(dict(status=status,shot=shot,original_prompt_id=args.prompt_id,elapsed_seconds=elapsed)),flush=True)
                    previous=status;last=elapsed
                if status in ('technical_saved','media_review_required','failed','interrupted','rejected','outcome_unknown'):
                    final=dict(status=status,original_prompt_id=args.prompt_id)
            if final is None:time.sleep(args.poll_seconds)
        if final is None:final=dict(status='bounded_wait_elapsed_no_resubmit',original_prompt_id=args.prompt_id)
        exit_code=0 if final['status'] in ('technical_saved','media_review_required') else 3
    except BaseException as error:
        fatal=True;exit_code=130 if isinstance(error,KeyboardInterrupt) else 1
        detail=dict(type=type(error).__name__,message=str(error),traceback=traceback.format_exc(),phase=phase,
            original_prompt_id=args.prompt_id,rePOST=False)
        flow.freeze(evidence/'ERROR.json',detail)
        final=dict(status='collector_fatal_error',original_prompt_id=args.prompt_id,error_type=detail['type'],
            error_message=detail['message'],phase=phase,error_record=flow.bind(evidence/'ERROR.json'))
    finally:
        # Integrity/factory/state errors are terminal too. They retain their
        # evidence and returned UUID; this path never calls submit or prepare.
        flow.freeze(evidence/'EXIT.json',dict(schema='universal_CLI_wait_exit/v2',result=final,
            elapsed_seconds=round(time.monotonic()-started),ended_at_utc=datetime.now(timezone.utc).isoformat(),
            exit_code=exit_code,fatal=fatal,rePOST_performed=False,original_records_modified=False))
    print(json.dumps(dict(final,evidence=str(evidence),exit_record=flow.bind(evidence/'EXIT.json')),ensure_ascii=False),flush=True)
    return exit_code


def main(argv=None):
    parser=_parser();args=parser.parse_args(argv)
    for field in ('run','policy','draft','config','prompt_profiles','authorization','scene_reuse_approval'):
        value=getattr(args,field)
        if value is not None:setattr(args,field,value.resolve())
    if args.route=='library' and not args.shot:parser.error('library route requires --shot')
    if args.route=='asset' and args.scene_reuse_approval is not None:parser.error('scene reuse approval is only for library route')
    if args.action=='wait':
        if not args.prompt_id or not 10<=args.poll_seconds<=60 or not 60<=args.max_seconds<=21600:
            parser.error('wait requires original UUID, 10..60s poll and 60..21600s deadline')
        return _wait(args)
    from src.content_factory import h3_asset_flow_v2 as flow
    api=_api(args)
    if args.action=='prepare':
        if args.route=='library':result=api.prepare_video(args.run,args.shot,code_files=[__file__])
        else:
            if not all((args.draft,args.config,args.prompt_profiles,args.authorization)):
                parser.error('asset prepare requires draft/config/prompt-profiles/authorization')
            result=api.prepare(args.run,args.draft,flow.read(args.config),prompt_profiles=flow.bind(args.prompt_profiles),
                authorization=flow.bind(args.authorization),code_files=[__file__])
    else:result=_call(api,args,'collect_known' if args.action=='collect' else args.action)
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
