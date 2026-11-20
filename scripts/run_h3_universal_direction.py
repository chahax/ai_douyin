"""One explicitly approved local clip, or a bounded GET-only original-ID wait."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['prepare','submit','collect','status','wait'])
    p.add_argument('--route',choices=['library','asset'],required=True)
    p.add_argument('--run',type=Path,required=True);p.add_argument('--policy',type=Path,required=True)
    p.add_argument('--shot');p.add_argument('--draft',type=Path);p.add_argument('--config',type=Path)
    p.add_argument('--prompt-profiles',type=Path);p.add_argument('--authorization',type=Path)
    p.add_argument('--prompt-id');p.add_argument('--poll-seconds',type=int,default=30)
    p.add_argument('--max-seconds',type=int,default=21600)
    a=p.parse_args()
    from src.content_factory import h3_universal_direction_execution_v1 as module
    from src.content_factory import h3_asset_flow_v2 as flow
    if a.route=='library' and not a.shot:p.error('library route requires --shot')
    api=module.library_for_run(a.run,flow.bind(a.policy)) if a.route=='library' else module.asset_for_run(a.run,flow.bind(a.policy))
    def call(name):
        return getattr(api,name)(a.run,a.shot) if a.route=='library' else getattr(api,name)(a.run)
    if a.action=='prepare':
        if a.route=='library':result=api.prepare_video(a.run,a.shot,code_files=[__file__])
        else:
            if not all((a.draft,a.config,a.prompt_profiles,a.authorization)):
                p.error('asset prepare requires draft/config/prompt-profiles/authorization')
            result=api.prepare(a.run,a.draft,flow.read(a.config),prompt_profiles=flow.bind(a.prompt_profiles),
                               authorization=flow.bind(a.authorization),code_files=[__file__])
    elif a.action=='wait':
        if not a.prompt_id or not 10<=a.poll_seconds<=60 or not 60<=a.max_seconds<=21600:
            p.error('wait requires original UUID, 10..60s poll and 60..21600s deadline')
        native=api.native_run(a.run,a.shot) if a.route=='library' else a.run
        shot=a.shot if a.route=='library' else flow.read(a.run/'PLAN.json')['shots'][0]['id']
        state=flow.read(native/'shots'/shot/'STATE.json')
        if state.get('prompt_id')!=a.prompt_id:raise ValueError('only_original_returned_UUID_allowed')
        evidence=native/'collectors'/str(os.getpid())
        flow.freeze(evidence/'START.json',dict(pid=os.getpid(),original_prompt_id=a.prompt_id,
            collector=flow.bind(__file__),route=a.route,started_at_utc=datetime.now(timezone.utc).isoformat(),
            poll_seconds=a.poll_seconds,max_seconds=a.max_seconds,HTTP_method='GET_ONLY',rePOST_allowed=False))
        start=time.monotonic();last=-100;errors=0;previous=None;final=None
        while time.monotonic()-start<a.max_seconds:
            try:result=call('collect_known')
            except (OSError,TimeoutError,urllib.error.URLError,json.JSONDecodeError) as error:
                errors+=1
                flow.freeze(evidence/'errors'/f'{time.time_ns()}.json',dict(type=type(error).__name__,message=str(error),rePOST=False))
                if errors>=10:final={'status':'collector_GET_errors','original_prompt_id':a.prompt_id};break
            else:
                errors=0;s=result.get('shot',result);status=s.get('status',result.get('status'))
                elapsed=round(time.monotonic()-start)
                if status!=previous or elapsed-last>=300:
                    print(json.dumps(dict(status=status,shot=shot,original_prompt_id=a.prompt_id,elapsed_seconds=elapsed)),flush=True)
                    previous=status;last=elapsed
                if status in ('technical_saved','media_review_required','failed','interrupted','rejected','outcome_unknown'):
                    final={'status':status,'original_prompt_id':a.prompt_id};break
            time.sleep(a.poll_seconds)
        if final is None:final={'status':'bounded_wait_elapsed_no_resubmit','original_prompt_id':a.prompt_id}
        flow.freeze(evidence/'EXIT.json',dict(result=final,elapsed_seconds=round(time.monotonic()-start),
            ended_at_utc=datetime.now(timezone.utc).isoformat(),rePOST_performed=False))
        print(json.dumps(final),flush=True)
        return 0 if final['status'] in ('technical_saved','media_review_required') else 3
    elif a.action=='collect':result=call('collect_known')
    else:result=call(a.action)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
