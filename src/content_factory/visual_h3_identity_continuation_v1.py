"""Source-bound FL2VA continuations from actual predecessor native tails.

Full-clip identity coverage is independent of the first dramatic camera beat.
Only a root-observed tail containing every required identity is eligible; this
contract makes no general production-quality or exact-output-prefix claim.
"""
from copy import deepcopy
from pathlib import Path
import re
import subprocess
import time
import urllib.error
import uuid

from . import visual_h3_continuity_input_v33 as core
from . import visual_h3_handoff_v3 as native
from . import visual_h3_prompt_parity_v19 as clock
from .visual_spatial_clock_v30 import clock_input

SERIES='h3_identity_continuation_series/v1'
SCHEMA='h3_identity_continuation_native/v1'
CONTRACT='actual_native_tail_identity/v1'
CONDITIONING='FL2VA_first_frame_only'
REVIEW='h3_identity_tail_coverage/v1'
IDS=('S01','S02','S03','S04')
NEW=('S03','S04')
read,bind=native.read,core.binding


def freeze(path,value):
    Path(path).parent.mkdir(parents=True,exist_ok=True);native.freeze(path,value)


def _strings(value):return isinstance(value,list) and bool(value) and all(isinstance(x,str) and x.strip() for x in value)
def part(run,sid):
    if sid not in IDS:raise ValueError('explicit_four_segment_id_required')
    return Path(run)/'segments'/sid
def native_run(run,sid):return Path(run)/'visual_h3_v3'/(Path(run).name+'_'+sid)


def verify_native(result_binding):
    """Authenticate saved originals and native history, without visual claims."""
    path=Path(core.check(result_binding));result=read(path);folder=path.parent;run=folder.parents[1]
    plan=read(run/'PLAN.json');sid=result['shot_id'];rows=[x for x in plan['shots'] if x['id']==sid]
    if len(rows)!=1 or folder!=run/'shots'/sid:raise ValueError('original_native_result_scope_required')
    row=rows[0];state=native._shot_state(folder,plan,row);graph=read(folder/'workflow_api.json')
    native._validate_graph(graph,row['scope'],row['input_name'])
    if (result.get('schema')!=native.SCHEMA or result.get('technical_status')!='technical_saved'
            or result.get('production_approved') is not False or result.get('publication') is not False
            or state['status']!='technical_saved' or result['prompt_id']!=state['prompt_id']
            or core.digest(graph)!=row['graph_sha256'] or graph['pick_last']['inputs']['batch_index']!=361
            or row['timing']['native_frames']!=362):raise ValueError('saved_native_frame_clock_or_id_changed')
    native._verify_result(folder,plan,row,state)
    history=read(folder/'HISTORY.json');event=history.get(result['prompt_id'],{});hp=event.get('prompt',[])
    if (len(hp)<3 or hp[1]!=result['prompt_id'] or native.native_graph_equivalence(graph,hp[2]) is None
            or event.get('status',{}).get('completed') is not True or event['status'].get('status_str')!='success'):
        raise ValueError('original_success_history_required')
    cfg=plan['config'];output_root=Path(cfg['output_root']).resolve();scope=(output_root/row['scope']).resolve()
    for role,item in result['files'].items():
        origin=Path(item['source_path']).resolve();saved=event['outputs']['save_'+role]['audio' if role=='audio' else 'images']
        if (origin.parent!=scope or native.file_sha(origin)!=item['sha256'] or len(saved)!=1
                or saved[0].get('type')!='output'
                or (output_root/saved[0].get('subfolder','')/saved[0]['filename']).resolve()!=origin):
            raise ValueError('native_original_output_history_changed')
    return dict(result=result,result_binding=result_binding,records=dict(plan=bind(run/'PLAN.json'),
        request=bind(folder/'REQUEST.json'),history=bind(folder/'HISTORY.json'),result=result_binding),
        last_image={k:result['files']['last'][k] for k in ('path','sha256')},last_frame_index=361,
        native_graph_sha256=core.digest(graph),actual_native_tail_verified=True)


def prepare(run,spec):
    """Import the exact accepted prefix, and prepare source/review requests only."""
    run=Path(run).resolve();run.mkdir(parents=True,exist_ok=True)
    if set(spec['prefix_results'])!={'S01','S02'} or set(spec['sources'])!=set(NEW):raise ValueError('two_imports_two_new_sources_required')
    cfg=deepcopy(spec['config']);cfg['runs_root']=str(run/'visual_h3_v3')
    freeze(run/'H3_CONFIG.json',cfg);freeze(run/'USER_AUTHORIZATION.json',spec['authorization'])
    prefix=[]
    for sid in IDS[:2]:
        proof=verify_native(spec['prefix_results'][sid]);result=proof['result']
        if result['shot_id']!=sid:raise ValueError('prefix_native_order_changed')
        value=dict(schema=SERIES,shot_id=sid,kind='preserved_native_prefix',native_result=proof['result_binding'],
            native_records=proof['records'],native_files=result['files'],prompt_id=result['prompt_id'],
            file={k:result['files']['video'][k] for k in ('path','sha256')},new_model_calls=0,source_media_unchanged=True)
        freeze(run/'imported'/sid/'IMPORT.json',value);prefix.append(dict(shot_id=sid,imported=bind(run/'imported'/sid/'IMPORT.json')))
    sources=[]
    for sid in NEW:
        entries=core._entries(spec['sources'][sid])
        if len(entries)!=1 or entries[0]['shot_id']!=sid or 'reanchor' in entries[0]:raise ValueError('original_single_source_required')
        core.validate_entry(entries[0]);freeze(part(run,sid)/'SOURCE_CASE.json',dict(schema=core.SCHEMA,shots=entries))
        sources.append(dict(shot_id=sid,source_case=bind(part(run,sid)/'SOURCE_CASE.json'),native_run=str(native_run(run,sid))))
    plan=dict(schema=SERIES,prefix=prefix,sources=sources,config=bind(run/'H3_CONFIG.json'),authority=bind(run/'USER_AUTHORIZATION.json'),
        frames_per_segment=362,expected_frames=1448,width=736,height=1312,fps=24,steps=12,
        new_video_submissions=2,new_image_submissions=0,publication=False,production_approved=False,
        preserved_prefix_frames=724,prefix_source_media_unchanged=True,output_prefix_pixel_identity_claimed=False)
    freeze(run/'PLAN.json',plan)
    return dict(status='source_prepared_no_post',plan=bind(run/'PLAN.json'),S03=review_request(run,'S03'),
        S04=review_request(run,'S04'),model_posts=0)


def _predecessor(run,sid):
    if sid=='S03':return read(core.check(read(run/'PLAN.json')['prefix'][1]['imported']))['native_result']
    if sid!='S04':raise ValueError('only_two_new_continuations_allowed')
    path=native_run(run,'S03')/'shots/S03/RESULT.json'
    if not path.exists():return None
    # The second continuation can only consume this run's completed first one.
    p=read(native_run(run,'S03')/'PLAN.json')
    if p.get('schema')!=SCHEMA or p.get('series_plan')!=bind(run/'PLAN.json'):raise ValueError('current_run_S03_tail_required')
    return bind(path)


def review_request(run,sid):
    run=Path(run).resolve();source=bind(part(run,sid)/'SOURCE_CASE.json');entry=core._entries(source)[0]
    req=core.validate_entry(entry);previous=_predecessor(run,sid)
    if previous is None:return dict(status='upstream_native_tail_required',predecessor_shot_id='S03',model_posts=0)
    proof=verify_native(previous)
    value=dict(schema=REVIEW+'_request',shot_id=sid,anchor_result=previous,anchor_image=proof['last_image'],
        clip_identity_actor_ids=req['visible_actors'],opening_actor_ids=list(entry['camera_beats'][0]['actors']),
        required_review_file=str(part(run,sid)/'TAIL_ANCHOR_COVERAGE_REVIEW.json'),review_not_observed=True)
    freeze(part(run,sid)/'TAIL_ANCHOR_COVERAGE_REQUEST.json',value)
    return dict(status='actual_tail_coverage_review_required',request=bind(part(run,sid)/'TAIL_ANCHOR_COVERAGE_REQUEST.json'),model_posts=0)


def render(entry,review):
    """Keep source action/audio; only adapt the inherited anchor's opening beat."""
    req=core.validate_entry(entry);lines=['真人写实摄影剧情。输入是上一段原生视频的真实尾帧，人物外貌、服装、房间与持物状态从该画面继续；叙事通过表演和声音传达。对白文字仅作为声音轨的发音内容，画面按摄影镜头呈现。人物注意力在剧情中的互动对象上，按后续分镜改变景别和视线。']
    for cid in req['visible_actors']:
        who=review['identity_by_actor'][cid];lines.append(entry['character_names'][cid]+'：'+who['screen_description']+'；'+who['appearance']+'。')
    if review.get('anchor_action_state'):lines.append('承接中的真实状态：'+review['anchor_action_state'])
    lines.append('0—0.5秒，接续输入画面中当时的姿态、持物与互动，声音从0秒开始；随后进入下面的原剧情镜头。')
    framing=dict(face_close='头肩近景',hands_close='手部及所持物近景',medium='中景',wide='全景',detail='局部细节镜头')
    parts=dict(face='面部',mouth='嘴部',head='头部',shoulders='肩部',torso='躯干',hands='双手',legs='双腿',feet='双脚',back='背部')
    for index,beat in enumerate(entry['camera_beats']):
        start=.5 if index==0 else beat['start']
        if beat['end']<=start:raise ValueError('opening_beat_too_short_for_tail_handoff')
        actors='；'.join('画面呈现'+entry['character_names'][cid]+'的'+'、'.join(parts[p] for p in a['visible_parts']) for cid,a in beat['actors'].items())
        actions=''.join(req['spans'][s]['text'] for s in beat['source_span_ids'])
        lines.append(f"{start:g}—{beat['end']:g}秒，"+('明确切到' if index==0 or beat['cut'] else '以')+framing[beat['framing']]+'呈现。'+actors+'。'+actions)
    original=core.compile_prompt(entry)['compiled_prompt'];audio=original.split('声音轨按原句依次演出：',1)[1]
    lines.append('声音轨按原句依次演出：'+audio);text='\n'.join(lines)
    if core.QUOTE.findall(text)!=core.QUOTE.findall(original):raise ValueError('original_verbatim_audio_changed')
    return text


def input_value(run,sid):
    request=review_request(run,sid)
    if request['status']=='upstream_native_tail_required':return request
    source=bind(part(run,sid)/'SOURCE_CASE.json');entry=core._entries(source)[0];req=core.validate_entry(entry)
    previous=_predecessor(run,sid);proof=verify_native(previous);path=part(run,sid)/'TAIL_ANCHOR_COVERAGE_REVIEW.json'
    if not path.exists():return request
    review=read(path);clip=req['visible_actors'];opening_ids=list(entry['camera_beats'][0]['actors'])
    if (review.get('schema')!=REVIEW or review.get('shot_id')!=sid or review.get('anchor_result')!=previous
            or review.get('anchor_image')!=proof['last_image'] or review.get('completion_known') is not True
            or review.get('outcome_unknown') is not False or not review.get('reviewed_by') or not _strings(review.get('evidence'))):
        raise ValueError('actual_native_tail_bound_observation_required')
    by=review.get('identity_by_actor',{});missing=[c for c in clip if by.get(c,{}).get('present') is not True or by[c].get('identity_matches') is not True]
    if (set(review.get('clip_identity_actor_ids',[]))!=set(clip) or review.get('opening_actor_ids')!=opening_ids
            or set(review.get('actual_anchor_actor_ids',[]))!=set(clip) or missing):
        return dict(status='identity_materialization_or_shot_split_required',missing_actor_ids=missing,
            clip_identity_actor_ids=clip,opening_actor_ids=opening_ids,model_posts=0)
    if any(not isinstance(by[c].get(k),str) or not by[c][k].strip() for c in clip for k in ('screen_description','appearance')):
        raise ValueError('actual_screen_identity_mapping_required')
    text=render(entry,review)
    return dict(schema=CONTRACT,shot_id=sid,source_case=source,entry_sha256=core.digest(entry),first_image=proof['last_image'],
        predecessor_result=previous,generation_receipt=proof,coverage_review=bind(path),clip_identity_actor_ids=clip,
        opening_actor_ids=opening_ids,anchor_actor_ids=review['actual_anchor_actor_ids'],compiled_prompt=text,
        compiled_prompt_utf8_sha256=core.sha(text),opening_handoff_seconds=.5,identity_coverage_complete=True,
        full_video_quality_passed=False,production_approved=False,publication=False,conditioning_mode=CONDITIONING)


def validate_input(value):
    path=Path(core.check(value));run=path.parents[2];sid=path.parent.name;data=read(path)
    if path!=part(run,sid)/'IDENTITY_CONTINUATION_INPUT.json' or input_value(run,sid)!=data:
        raise ValueError('identity_continuation_source_or_pixels_changed')
    proof={k:deepcopy(data[k]) for k in ('schema','source_case','first_image','predecessor_result','coverage_review',
        'clip_identity_actor_ids','opening_actor_ids','compiled_prompt_utf8_sha256')};proof['input']=value
    return dict(data,entry=core._entries(data['source_case'])[0],proof=proof,quality_passed=False)


def prepare_video(run,sid,*,code_files=()):
    run=Path(run).resolve();value=input_value(run,sid)
    if 'status' in value:return value
    p=part(run,sid);freeze(p/'IDENTITY_CONTINUATION_INPUT.json',value);ib=bind(p/'IDENTITY_CONTINUATION_INPUT.json');checked=validate_input(ib)
    cfg=read(core.check(read(run/'PLAN.json')['config']));cfg=native._config(dict(config=dict(image_service=cfg,**{k:cfg[k] for k in ('gpu_lock_root','protected_pause_path')})),cfg)
    nr=native_run(run,sid);native._target(nr,cfg);shot=core.handoff_snapshot(value['source_case'],cfg)[2]['shots'][0]
    timing=native._timing(shot);scope=native.PREFIX+'/'+nr.name+'/'+sid;name=scope+'/first_frame.png'
    graph=native.build_graph(read(cfg['base_workflow']),shot,value['first_image'],timing,name,scope,736,1312,native_prompt=value['compiled_prompt'])
    if tuple(graph['condition']['inputs'][k] for k in ('width','height','length'))!=(736,1312,362) or graph['124']['inputs']['steps']!=12 or graph['130']['inputs']['fps']!=24:
        raise ValueError('unchanged_FL2VA_native_profile_required')
    row=dict(id=sid,binding_sha256=shot['binding_sha256'],first_frame=value['first_image'],graph_sha256=core.digest(graph),
        scope=scope,input_name=name,timing=timing,identity_continuation=checked['proof'])
    plan=dict(schema=SCHEMA,upstream_contract=CONTRACT,series_plan=bind(run/'PLAN.json'),config=cfg,input=ib,source=value['source_case'],
        shots=[row],base_workflow=bind(cfg['base_workflow']),protected_pause=bind(cfg['protected_pause_path']),
        code=[bind(x) for x in ( __file__,native.__file__,core.__file__,*code_files)],
        publication=False,production_approved=False,old_batch_resume=False,full_video_quality_passed=False,conditioning_mode=CONDITIONING)
    nr.mkdir(parents=True,exist_ok=True)
    with native.jobs.run_lock(nr):
        freeze(nr/'PLAN.json',plan);native.jobs.stage_input({k:cfg[k] for k in ('service_url','input_root','output_root','timeout')},value['first_image']['path'],name,value['first_image']['sha256'])
        freeze(nr/'shots'/sid/'workflow_api.json',graph)
        state=nr/'shots'/sid/'STATE.json'
        if not state.exists():native.write(state,dict(id=sid,status='prepared',prompt_id=None,plan_sha256=core.digest(plan)))
    freeze(p/'LAUNCH_REQUEST_VIDEO.json',launch_request(run,sid));return status(run,sid)


def _load(run,sid,current=True):
    if sid not in NEW:raise ValueError('only_two_new_continuations_allowed')
    nr=native_run(run,sid);plan=read(nr/'PLAN.json');row=plan['shots'][0];graph=read(nr/'shots'/sid/'workflow_api.json')
    if (plan.get('schema')!=SCHEMA or plan.get('upstream_contract')!=CONTRACT or plan.get('old_batch_resume') is not False
            or plan.get('publication') is not False or plan.get('production_approved') is not False or row['id']!=sid):raise ValueError('explicit_continuation_contract_required')
    native._validate_graph(graph,row['scope'],row['input_name'])
    if core.digest(graph)!=row['graph_sha256']:raise ValueError('frozen_continuation_graph_changed')
    if current:
        v=validate_input(plan['input'])
        for x in (plan['series_plan'],plan['base_workflow'],*plan['code']):core.check(x)
        series=read(core.check(plan['series_plan']))
        for x in (series['config'],series['authority'],*[s['source_case'] for s in series['sources']],*[s['imported'] for s in series['prefix']]):core.check(x)
        if plan.get('conditioning_mode')!=CONDITIONING:raise ValueError('explicit_FL2VA_conditioning_contract_required')
        shot=core.handoff_snapshot(v['source_case'],plan['config'])[2]['shots'][0]
        expected=native.build_graph(read(core.check(plan['base_workflow'])),shot,v['first_image'],native._timing(shot),row['input_name'],row['scope'],736,1312,native_prompt=v['compiled_prompt'])
        if graph!=expected or row['identity_continuation']!=v['proof'] or row['first_frame']!=v['first_image']:raise ValueError('continuation_current_source_profile_or_seed_changed')
    return nr,plan,row


def status(run,sid):
    nr,plan,row=_load(run,sid,current=False);s=native._shot_state(nr/'shots'/sid,plan,row)
    label='media_review_required' if s['status']=='technical_saved' else 'blocked_native_failure' if s['status'] in ('failed','interrupted','rejected') else 'paused' if (nr/'PAUSE.json').exists() else s['status']
    return dict(schema=SCHEMA,status=label,shot=s,production_approved=False)


def launch_request(run,sid):
    nr,p,_=_load(run,sid);return dict(schema=SCHEMA,shot_id=sid,plan=bind(nr/'PLAN.json'),input=p['input'],
        graph=bind(nr/'shots'/sid/'workflow_api.json'),code=p['code'],series_plan=p['series_plan'],publication=False,unknown_replay=False)


def _approval(run,sid):
    a=read(part(run,sid)/'ROOT_LAUNCH_VIDEO.json')
    if a.get('request')!=launch_request(run,sid) or not a.get('approved_by') or not _strings(a.get('evidence')):raise ValueError('actual_continuation_launch_required')


def _ledger(run,sid,pid,event):
    with native.jobs.run_lock(run,'NATIVE_LEDGER.lock'):
        for file,line in [('job_ids.txt',f'{sid} {pid}\n'),('LOG.md',f'- {event} {sid} {pid}\n')]:
            path=Path(run)/file
            if not path.exists() or line not in path.read_text(encoding='utf-8'):
                with path.open('a',encoding='utf-8') as stream:stream.write(line)


def submit(run,sid):
    nr,plan,row=_load(run,sid);cfg=plan['config'];folder=nr/'shots'/sid
    with native.jobs.run_lock(nr),native._gpu(plan),native.jobs.run_lock(part(run,sid),'IDENTITY_INPUT_DISPATCH.lock'):
        _load(run,sid);cur=status(run,sid);state=cur['shot']
        if state['status']!='prepared' or (nr/'PAUSE.json').exists() or not cfg['video_enabled']:return cur
        _approval(run,sid);native._service_paths(cfg);queue=native._queue(cfg)
        if queue['queue_running'] or queue['queue_pending']:return dict(cur,dispatch='waiting_gpu_queue')
        if native.file_sha(native.bound(cfg['input_root'],row['input_name']))!=row['first_frame']['sha256']:raise ValueError('actual_staged_tail_pixels_changed')
        request=dict(prompt=read(folder/'workflow_api.json'),client_id=uuid.uuid4().hex);freeze(folder/'REQUEST.json',request)
        freeze(folder/'CLAIM.json',dict(at=time.time(),graph_sha256=row['graph_sha256'],first_frame_sha256=row['first_frame']['sha256']))
        try:response=native._http(cfg,'/prompt',request)
        except urllib.error.HTTPError as e:
            freeze(folder/'SUBMISSION_ERROR.json',dict(type='HTTPError',code=e.code,response=e.read(16000).decode('utf-8',errors='replace')))
            state.update(status='rejected' if e.code in (400,422) else 'outcome_unknown')
        except Exception as e:
            freeze(folder/'SUBMISSION_ERROR.json',dict(type=type(e).__name__,message=str(e)));state['status']='outcome_unknown'
        else:
            freeze(folder/'RESPONSE.json',response);pid=response.get('prompt_id') if isinstance(response,dict) else None
            state['status']='submitted' if isinstance(pid,str) and re.fullmatch(r'[A-Za-z0-9_-]{1,100}',pid) else 'outcome_unknown'
            if state['status']=='submitted':state.update(prompt_id=pid,submitted_at=time.time());_ledger(run,sid,pid,'NATIVE_ID')
        native.write(folder/'STATE.json',state)
    return status(run,sid)


def collect_known(run,sid):
    nr,p,row=_load(run,sid,current=False);folder=nr/'shots'/sid;cfg=p['config']
    with native.jobs.run_lock(nr):
        state=native._shot_state(folder,p,row);pid=state.get('prompt_id')
        if pid:_ledger(run,sid,pid,'NATIVE_ID')
        if pid and state['status'] not in ('technical_saved','failed','interrupted','rejected'):
            history=native._http(cfg,'/history/'+native.slug(pid))
            if not isinstance(history,dict):raise ValueError('actual_native_history_required')
            e=history.get(pid)
            if e:
                hp=e.get('prompt',[]);hs=e.get('status',{})
                if (len(hp)<3 or hp[1]!=pid or not native._verify_native_graph(folder,row,hp[2],pid)
                        or type(hs.get('completed')) is not bool or hs.get('status_str') not in ('success','error')):raise ValueError('actual_native_history_changed')
                native.write(folder/'HISTORY.latest.json',history)
                if hs['status_str']=='error':state.update(status='failed',native_terminal=hs)
                elif hs['completed']:freeze(folder/'HISTORY.json',history);native._collect(folder,p,row,state,e)
                else:state['status']='running'
            else:
                q=native._queue(cfg);matches=[x for x in q['queue_running']+q['queue_pending'] if x[1]==pid]
                if any(not native._verify_native_graph(folder,row,x[2],pid) for x in matches):raise ValueError('actual_native_queue_graph_changed')
                state['status']='running' if matches else 'outcome_unknown'
            native.write(folder/'STATE.json',state)
        if state['status']=='technical_saved':
            r=native._verify_result(folder,p,row,state);receipt=dict(schema=CONTRACT,native_result=bind(folder/'RESULT.json'),
                input=p['input'],identity_continuation=row['identity_continuation'],native_records=dict(plan=bind(nr/'PLAN.json'),
                request=bind(folder/'REQUEST.json'),history=bind(folder/'HISTORY.json')),production_approved=False)
            freeze(nr/'IDENTITY_CONTINUATION_RESULT.json',receipt)
            freeze(part(run,sid)/'FINAL_RESULT.json',dict(native_result=bind(folder/'RESULT.json'),
                file={k:r['files']['video'][k] for k in ('path','sha256')},prompt_id=pid,postprocessing=[],
                continuation_receipt=bind(nr/'IDENTITY_CONTINUATION_RESULT.json'),production_approved=False));_ledger(run,sid,pid,'SAVED')
    return status(run,sid)


def execute(run,sid,*,poll_seconds=30,max_seconds=21600):
    if not 1<=poll_seconds<=60 or not 1<=max_seconds<=21600:raise ValueError('bounded_wait_required')
    deadline=time.monotonic()+max_seconds
    with native.jobs.run_lock(native_run(run,sid),'CONTINUATION_WORKER.lock'):
        while True:
            s=collect_known(run,sid)
            if s['status'] in ('media_review_required','blocked_native_failure','outcome_unknown','paused'):return s
            if s['status']=='prepared':submit(run,sid)
            if time.monotonic()>=deadline:return dict(s,bounded_wait_original_id_preserved=True)
            time.sleep(poll_seconds)


def assemble(run):
    run=Path(run);p=read(run/'PLAN.json');rows=[]
    with native.jobs.run_lock(run,'ASSEMBLY.lock'):
        for sid in IDS:
            path=run/'imported'/sid/'IMPORT.json' if sid in IDS[:2] else part(run,sid)/'FINAL_RESULT.json'
            descriptor=read(path);proof=verify_native(descriptor['native_result']);r=proof['result']
            rows.append(dict(shot_id=sid,native_result=descriptor['native_result'],file={k:r['files']['video'][k] for k in ('path','sha256')},
                prompt_id=r['prompt_id'],kind='imported' if sid in IDS[:2] else 'new',descriptor=bind(path)))
        if len({r['prompt_id'] for r in rows})!=4 or len({r['file']['sha256'] for r in rows})!=4:raise ValueError('four_distinct_native_originals_required')
        for original,current in zip(p['prefix'],rows[:2]):
            if original['imported']!=current['descriptor']:raise ValueError('frozen_prefix_changed')
        for sid in NEW:_load(run,sid)
        inputs=dict(plan=bind(run/'PLAN.json'),segments=rows);digest=core.digest(inputs);final=run/'FINAL_RESULT.json';out=run/'H3_IDENTITY_CONTINUATION_MINUTE_736x1312.mp4'
        if final.exists():
            v=read(final);core.check(v['file'])
            if v['assembly_inputs_sha256']!=digest:raise ValueError('frozen_assembly_sources_changed')
            return v
        if out.exists():raise ValueError('unreceipted_final_movie_preserved')
        adjustments=[clock_input(r['file']['path'],r['file']['sha256'],frames=362,width=736,height=1312) for r in rows]
        filters=run/'ASSEMBLY_FILTER.txt';command,text=clock.assembly_command([r['file']['path'] for r in rows],filters,out,frames=362)
        filters.write_text(text,encoding='utf-8');freeze(run/'ASSEMBLY_REQUEST.json',dict(inputs=inputs,adjustments=adjustments,command=command,
            prefix_source_media_unchanged=True,output_prefix_pixel_identity_claimed=False,temporal_leading_trim=False))
        result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=1800)
        (run/'ASSEMBLY.stderr.log').write_text(result.stderr,encoding='utf-8');result.check_returncode()
        timing=clock.verify_clock(clock._probe(out,count=True),frames=1448,width=736,height=1312)
        for row in rows:core.check(row['native_result']);core.check(row['file'])
        v=dict(schema=SERIES,file=bind(out),segments=rows,native_ids=[r['prompt_id'] for r in rows],clock=timing,assembly_inputs_sha256=digest,
            prefix_source_media_unchanged=True,output_prefix_pixel_identity_claimed=False,production_approved=False,publication=False)
        freeze(final,v);return v
