"""Explicit user-review diagnostics from observed, imperfect opening images.

This does not relax visual-ready contracts or create a visual approval. Source
and pixel receipts are authenticated separately from the retained deviations.
"""
from copy import deepcopy
import argparse
import json
from pathlib import Path
import re
import sys
import time
import urllib.error
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import run_h3_story_opening_minute as minute

core,native,stills,opening=minute.core,minute.native,minute.stills,minute.opening
read,bind,freeze=minute.read,minute.bind,minute.freeze
RUN=minute.RUN
IDS=minute.NEW_IDS
SCHEMA='h3_story_opening_diagnostic/v1'
INPUT_SCHEMA='source_bound_user_review_diagnostic/v1'


def scope(run):
    run=Path(run).resolve()
    if run!=Path(RUN).resolve():raise ValueError('explicit_diagnostic_minute_scope_required')
    return run


def _nonempty(value):
    return isinstance(value,list) and bool(value) and all(isinstance(x,str) and x.strip() for x in value)


def input_value(run,sid):
    """Read real source/native/crop lineage; quality remains a separate false."""
    if sid not in IDS:raise ValueError('only_three_new_diagnostic_segments_allowed')
    part=minute.segment(run,sid);source=bind(part/'SOURCE_CASE.json')
    selection=bind(part/'DIAGNOSTIC_GENERATION_SELECTION.json');chosen=read(core.check(selection))
    if (chosen.get('schema')!='h3_story_opening_diagnostic_selection/v1' or chosen.get('shot_id')!=sid
            or chosen.get('source_case')!=source or chosen.get('decision')!='generate_for_user_review'
            or chosen.get('quality_passed') is not False or not chosen.get('selected_by')
            or not chosen.get('reason') or not _nonempty(chosen.get('evidence'))):
        raise ValueError('explicit_observed_diagnostic_selection_required')
    observation=chosen['observation'];seen=read(core.check(observation));image=chosen['image'];core.image(image)
    if (seen.get('schema')!='h3_story_opening_anchor_observation/v1' or seen.get('shot_id')!=sid
            or seen.get('actual_image')!=image or seen.get('quality_passed') is not False
            or seen.get('completion_known') is not True or seen.get('outcome_unknown') is not False
            or not seen.get('reviewed_by') or not _nonempty(seen.get('deviations')) or not _nonempty(seen.get('evidence'))):
        raise ValueError('actual_failed_or_deviated_image_observation_required')
    entries=core._entries(source)
    if len(entries)!=1 or entries[0]['shot_id']!=sid or 'reanchor' in entries[0]:raise ValueError('original_unmodified_source_required')
    entry=entries[0];requirements=opening.requirements(entry,core.validate_entry(entry));report=core.evaluate(entry)
    if report['status']!='reanchor_required':raise ValueError('actual_pending_source_evaluation_required')
    receipt=read(part/'IMAGE_RECEIPT_TEMPLATE.json');candidate_path=Path(receipt['candidates']['path'])
    receipt['candidates']=bind(candidate_path)
    candidate=next(x for x in read(candidate_path)['items'] if x['id']==sid+'_start')
    raw=candidate['image'];generation=receipt
    if chosen.get('crop_result'):
        generation=dict(kind='derived_opening_crop/v1',parent_image=raw,
            parent_generation_receipt=receipt,crop_result=chosen['crop_result'])
    elif image!=raw:raise ValueError('raw_diagnostic_must_use_actual_saved_native_candidate')
    anchor=dict(image=image,generation_receipt=generation,work_order_sha256=core.digest(report['work_order']))
    proof=core._generation_receipt(entry,anchor,report['work_order'],requirements)
    prompt=core.compile_prompt(entry)
    authority=bind(Path(run)/'USER_AUTHORIZATION.json');core.check(authority)
    return dict(schema=INPUT_SCHEMA,shot_id=sid,source_case=source,entry_sha256=core.digest(entry),
        first_image=image,raw_native_image=raw,generation_receipt=proof,compiled_prompt=prompt['compiled_prompt'],
        compiled_prompt_utf8_sha256=prompt['compiled_prompt_utf8_sha256'],source_evaluation=report,
        observation=observation,override=selection,authority=authority,quality_passed=False,
        visual_ready=False,production_approved=False,publication=False)


def validate_input(binding):
    """Authenticate a diagnostic input without reclassifying it as core ready."""
    path=Path(core.check(binding));value=read(path)
    run=path.parents[2];sid=path.parent.name
    if path!=minute.segment(run,sid)/'DIAGNOSTIC_INPUT.json' or input_value(run,sid)!=value:
        raise ValueError('diagnostic_source_or_selected_pixels_changed')
    entry=core._entries(value['source_case'])[0]
    proof=dict(schema=INPUT_SCHEMA,input=binding,source_case=value['source_case'],first_image=value['first_image'],
        compiled_prompt_utf8_sha256=value['compiled_prompt_utf8_sha256'],override=value['override'],
        observation=value['observation'],quality_passed=False,visual_ready=False)
    return dict(value,entry=entry,proof=proof)


def prepare(run=RUN,sid=None):
    run=scope(run)
    if sid is None:return {s:prepare(run,s) for s in IDS}
    value=input_value(run,sid);part=minute.segment(run,sid)
    freeze(part/'DIAGNOSTIC_INPUT.json',value);input_binding=bind(part/'DIAGNOSTIC_INPUT.json')
    current=validate_input(input_binding);cfg=deepcopy(read(run/'H3_CONFIG.json'))
    config_base=dict(config=dict(image_service=cfg,**{k:cfg[k] for k in ('gpu_lock_root','protected_pause_path')}))
    cfg=native._config(config_base,cfg);video_run=minute.folders(run,sid)[1];native._target(video_run,cfg)
    snapshot,_,bindings=core.handoff_snapshot(value['source_case'],cfg)
    shot=bindings['shots'][0];timing=native._timing(shot);prefix=native.PREFIX+'/'+video_run.name+'/'+sid
    input_name=prefix+'/first_frame.png';frame=value['first_image'];base=Path(cfg['base_workflow'])
    graph=native.build_graph(read(base),shot,frame,timing,input_name,prefix,736,1312,native_prompt=value['compiled_prompt'])
    if (graph['condition']['inputs']['length'],graph['124']['inputs']['steps'],graph['130']['inputs']['fps'])!=(362,12,24):
        raise ValueError('unchanged_native_profile_required')
    row=dict(id=sid,binding_sha256=shot['binding_sha256'],first_frame=frame,graph_sha256=core.digest(graph),
        scope=prefix,input_name=input_name,timing=timing,diagnostic_input=current['proof'])
    plan=dict(schema=SCHEMA,upstream_contract=INPUT_SCHEMA,config=cfg,source=value['source_case'],
        diagnostic_input=input_binding,source_evaluation=value['source_evaluation'],shots=[row],
        base_workflow=bind(base),protected_pause=dict(path=cfg['protected_pause_path'],sha256=native.file_sha(cfg['protected_pause_path'])),
        authority=value['authority'],code=[bind(x) for x in (__file__,minute.__file__,core.__file__,native.__file__,stills.__file__,opening.__file__)],
        quality_passed=False,visual_ready=False,production_approved=False,publication=False,old_batch_resume=False)
    video_run.mkdir(parents=True,exist_ok=True)
    with stills.jobs.run_lock(video_run):
        # No native READY/accepted file is manufactured, including on resume.
        freeze(video_run/'PLAN.json',plan)
        native.jobs.stage_input({k:cfg[k] for k in ('service_url','input_root','output_root','timeout')},frame['path'],input_name,frame['sha256'])
        folder=video_run/'shots'/sid;freeze(folder/'workflow_api.json',graph)
        if not (folder/'STATE.json').exists():native.write(folder/'STATE.json',dict(id=sid,status='prepared',prompt_id=None,plan_sha256=core.digest(plan)))
        freeze(video_run/'DIAGNOSTIC_PREPARATION.json',dict(input=input_binding,source_snapshot_reports=snapshot['reports'],
            semantic_approval_inherited=False,graph=bind(folder/'workflow_api.json'),model_posts=0))
    freeze(part/'LAUNCH_REQUEST_DIAGNOSTIC_VIDEO.json',launch_request(run,sid))
    return status(run,sid)


def _load(run,sid,current=True):
    scope(run)
    if sid not in IDS:raise ValueError('only_three_new_diagnostic_segments_allowed')
    video_run=minute.folders(run,sid)[1];plan=read(video_run/'PLAN.json');row=plan['shots'][0]
    if (plan.get('schema')!=SCHEMA or plan.get('upstream_contract')!=INPUT_SCHEMA or row['id']!=sid
            or plan.get('quality_passed') is not False or plan.get('visual_ready') is not False
            or plan.get('publication') is not False or plan.get('production_approved') is not False
            or plan.get('old_batch_resume') is not False):
        raise ValueError('explicit_nonready_diagnostic_contract_required')
    graph=read(video_run/'shots'/sid/'workflow_api.json')
    native._validate_graph(graph,row['scope'],row['input_name'])
    if core.digest(graph)!=row['graph_sha256']:raise ValueError('frozen_diagnostic_graph_changed')
    if current:
        value=validate_input(plan['diagnostic_input'])
        for item in (plan['base_workflow'],plan['authority'],*plan['code']):core.check(item)
        if (row['diagnostic_input']!=value['proof'] or row['first_frame']!=value['first_image']
                or graph['condition']['inputs']['prompt']!=value['compiled_prompt']):
            raise ValueError('diagnostic_current_source_prompt_or_pixels_changed')
        shot=core.handoff_snapshot(value['source_case'],plan['config'])[2]['shots'][0]
        expected=native.build_graph(read(core.check(plan['base_workflow'])),shot,value['first_image'],native._timing(shot),
            row['input_name'],row['scope'],736,1312,native_prompt=value['compiled_prompt'])
        if graph!=expected:raise ValueError('diagnostic_profile_seed_or_source_graph_changed')
    return video_run,plan,row


def status(run=RUN,sid=None):
    run=scope(run)
    if sid is None:return {s:status(run,s) for s in IDS}
    video_run,plan,row=_load(run,sid,current=False);state=native._shot_state(video_run/'shots'/sid,plan,row)
    result=('media_review_required' if state['status']=='technical_saved' else
        'blocked_native_failure' if state['status'] in ('failed','interrupted','rejected') else
        'paused' if (video_run/'PAUSE.json').exists() else state['status'])
    return dict(schema=SCHEMA,status=result,shot=state,quality_passed=False,visual_ready=False,production_approved=False)


def launch_request(run,sid):
    video_run,plan,row=_load(run,sid)
    return dict(schema=SCHEMA,shot_id=sid,plan=bind(video_run/'PLAN.json'),input=plan['diagnostic_input'],
        graph=bind(video_run/'shots'/sid/'workflow_api.json'),authority=plan['authority'],code=plan['code'],
        quality_passed=False,publication=False,unknown_replay=False)


def require_approval(run,sid):
    expected=launch_request(run,sid);approval=read(minute.segment(run,sid)/'ROOT_LAUNCH_DIAGNOSTIC_VIDEO.json')
    if approval.get('request')!=expected or not approval.get('approved_by') or not _nonempty(approval.get('evidence')):
        raise ValueError('actual_diagnostic_launch_approval_required')


def _record_native(run,sid,pid,event):
    """Append exact known IDs/events once without replacing the image ledger."""
    with stills.jobs.run_lock(run,'DIAGNOSTIC_LEDGER.lock'):
        ledger=Path(run)/'job_ids.txt';line=f'diagnostic_video {sid} {pid}\n'
        if not ledger.exists() or line not in ledger.read_text(encoding='utf-8'):
            with ledger.open('a',encoding='utf-8') as stream:stream.write(line)
        log=Path(run)/'LOG.md';suffix=f' {event} {sid} {pid}\n'
        if not log.exists() or suffix not in log.read_text(encoding='utf-8'):
            with log.open('a',encoding='utf-8') as stream:stream.write(f'\n- {time.time()}'+suffix)


def submit(run,sid):
    video_run,plan,row=_load(run,sid);cfg=plan['config'];folder=video_run/'shots'/sid
    with stills.jobs.run_lock(video_run),native._gpu(plan),stills.jobs.run_lock(minute.segment(run,sid),'DIAGNOSTIC_INPUT_DISPATCH.lock'):
        _load(run,sid);current=status(run,sid);state=current['shot']
        if state['status']!='prepared' or (video_run/'PAUSE.json').exists() or not cfg['video_enabled']:return current
        require_approval(run,sid);native._service_paths(cfg);queue=native._queue(cfg)
        if queue['queue_running'] or queue['queue_pending']:return dict(current,dispatch='waiting_gpu_queue')
        if native.file_sha(native.bound(cfg['input_root'],row['input_name']))!=row['first_frame']['sha256']:
            raise ValueError('diagnostic_staged_first_image_changed')
        request=dict(prompt=read(folder/'workflow_api.json'),client_id=uuid.uuid4().hex)
        freeze(folder/'REQUEST.json',request)
        freeze(folder/'CLAIM.json',dict(at=time.time(),graph_sha256=row['graph_sha256'],first_frame_sha256=row['first_frame']['sha256']))
        try:response=native._http(cfg,'/prompt',request)
        except urllib.error.HTTPError as error:
            freeze(folder/'SUBMISSION_ERROR.json',dict(type='HTTPError',code=error.code,response=error.read(16000).decode('utf-8',errors='replace')))
            state.update(status='rejected' if error.code in (400,422) else 'outcome_unknown',reason='native_http_'+str(error.code))
        except Exception as error:
            freeze(folder/'SUBMISSION_ERROR.json',dict(type=type(error).__name__,message=str(error)))
            state.update(status='outcome_unknown',reason='post_result_not_observed')
        else:
            freeze(folder/'RESPONSE.json',response);pid=response.get('prompt_id') if isinstance(response,dict) else None
            state.update(status='submitted' if isinstance(pid,str) and re.fullmatch(r'[A-Za-z0-9_-]{1,100}',pid) else 'outcome_unknown')
            if state['status']=='submitted':
                state.update(prompt_id=pid,submitted_at=time.time());_record_native(run,sid,pid,'NATIVE_ID')
        native.write(folder/'STATE.json',state)
    return status(run,sid)


def collect_known(run,sid):
    run=scope(run);video_run,plan,row=_load(run,sid,current=False);folder=video_run/'shots'/sid;cfg=plan['config']
    with stills.jobs.run_lock(video_run):
        state=native._shot_state(folder,plan,row);pid=state.get('prompt_id')
        if pid:_record_native(run,sid,pid,'NATIVE_ID')
        if pid and state['status'] not in ('technical_saved','failed','interrupted','rejected'):
            history=native._http(cfg,'/history/'+native.slug(pid))
            if not isinstance(history,dict):raise ValueError('native_history_response_required')
            entry=history.get(pid)
            if entry:
                prompt=entry.get('prompt');result=entry.get('status')
                if (not isinstance(prompt,list) or len(prompt)<3 or prompt[1]!=pid
                        or not native._verify_native_graph(folder,row,prompt[2],pid) or not isinstance(result,dict)
                        or type(result.get('completed')) is not bool or result.get('status_str') not in ('success','error')):
                    raise ValueError('diagnostic_native_history_identity_changed')
                native.write(folder/'HISTORY.latest.json',history)
                if result['status_str']=='error':state.update(status='failed',native_terminal=result)
                elif result['completed']:
                    freeze(folder/'HISTORY.json',history);native._collect(folder,plan,row,state,entry)
                else:state['status']='running'
            else:
                queue=native._queue(cfg);matches=[q for q in queue['queue_running']+queue['queue_pending'] if q[1]==pid]
                if any(not native._verify_native_graph(folder,row,q[2],pid) for q in matches):raise ValueError('diagnostic_native_queue_graph_changed')
                state.update(status='running' if matches else 'outcome_unknown')
            native.write(folder/'STATE.json',state)
        if state['status']=='technical_saved':
            result=native._verify_result(folder,plan,row,state);receipt=dict(schema=SCHEMA,native_result=bind(folder/'RESULT.json'),
                input=plan['diagnostic_input'],diagnostic_input=row['diagnostic_input'],quality_passed=False,
                source_evaluation=plan['source_evaluation'],visual_ready=False,production_approved=False,
                native_records=dict(plan=bind(video_run/'PLAN.json'),request=bind(folder/'REQUEST.json'),history=bind(folder/'HISTORY.json')))
            freeze(video_run/'DIAGNOSTIC_RESULT.json',receipt)
            freeze(minute.segment(run,sid)/'FINAL_RESULT.json',dict(native_result=bind(folder/'RESULT.json'),
                file={k:result['files']['video'][k] for k in ('path','sha256')},prompt_id=pid,
                production_approved=False,postprocessing=[],diagnostic_receipt=bind(video_run/'DIAGNOSTIC_RESULT.json')))
            _record_native(run,sid,pid,'SAVED')
    return status(run,sid)


def execute(run=RUN,sid=None,poll_seconds=30,max_seconds=21600):
    run=scope(run)
    if not 1<=poll_seconds<=60 or not 1<=max_seconds<=21600:raise ValueError('bounded_wait_required')
    if sid is None:
        results={}
        for shot in IDS:
            results[shot]=execute(run,shot,poll_seconds,max_seconds)
            if results[shot]['status']!='media_review_required':break
        return results
    video_run=minute.folders(run,sid)[1];deadline=time.monotonic()+max_seconds
    with stills.jobs.run_lock(video_run,'DIAGNOSTIC_WORKER.lock'):
        while True:
            current=collect_known(run,sid)
            if current['status'] in ('media_review_required','blocked_native_failure','outcome_unknown','paused'):return current
            if current['status']=='prepared':submit(run,sid)
            if time.monotonic()>=deadline:return dict(current,bounded_wait_original_id_preserved=True)
            time.sleep(poll_seconds)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['prepare','status','video','collect']);p.add_argument('--run',type=Path,default=RUN)
    p.add_argument('--shot',choices=IDS);p.add_argument('--poll-seconds',type=int,default=30);p.add_argument('--max-seconds',type=int,default=21600)
    a=p.parse_args()
    if a.action=='video':value=execute(a.run,a.shot,a.poll_seconds,a.max_seconds)
    elif a.action=='collect':
        if a.shot is None:p.error('collect requires --shot')
        value=collect_known(a.run,a.shot)
    else:value={'prepare':prepare,'status':status}[a.action](a.run,a.shot)
    print(json.dumps(value,ensure_ascii=False,indent=2))


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    main()
