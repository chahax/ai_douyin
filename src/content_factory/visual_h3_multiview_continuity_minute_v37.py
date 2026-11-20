"""Tail-conditioned multiview minute; the user reviews the finished film.

Independent of frozen v34/v35/v36. No semantic approval is manufactured.
Each image/video stage is explicit; the owner controls cold family switching.
"""
from copy import deepcopy
from pathlib import Path
import json,re,subprocess,time,urllib.error,uuid
from PIL import Image
from . import visual_h3_handoff_v3 as native
from . import visual_image_jobs_v3 as jobs
from . import visual_h3_prompt_parity_v19 as clock
from .visual_spatial_clock_v30 import clock_input

PROJECT=Path(__file__).resolve().parents[2]
RUN=PROJECT/'data/video_generation/h3_multiview_continuity_minute_20261109_v3'
SHARED_GPU=PROJECT/'data/visual_asset_pipeline/gpu'
LOCAL_SERVICE='http://127.0.0.1:8190'
PROMPT_MODULE=Path(__file__).with_name('visual_h3_scene_prompt_v37.py')
SCHEMA='h3_multiview_continuity_minute/v37'
IDS=('S01','S02','S03','S04')
WIDTH,HEIGHT,FRAMES,FPS,SECONDS,QUOTE_COUNT=736,1312,362,24,15,10
BAD={'outcome_unknown','failed','interrupted','rejected','cancelled'}

class MultiviewError(ValueError):pass

def read(path):return native.read(path)
def bind(path):return dict(path=str(Path(path).resolve()),sha256=native.file_sha(path))
def check(value):
    if not isinstance(value,dict) or set(value)!={'path','sha256'} or bind(value['path'])!=value:raise MultiviewError('bound_input_changed')
    return Path(value['path'])
def freeze(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);native.freeze(path,value)
def digest(value):return native.fingerprint(value)
def _scope(run):
    run=Path(run).resolve()
    if run!=Path(RUN).resolve():raise MultiviewError('explicit_new_scene_performance_root_required')
    return run
def _folder(run,sid):
    if sid not in IDS:raise MultiviewError('four_source_segments_required')
    return Path(run)/'shots'/sid
def _scene():
    from . import visual_multiview_continuity_stills_v37 as scene
    return scene
def _scene_run(run):return Path(run)/'scene'
def _profile():return dict(width=WIDTH,height=HEIGHT,frames=FRAMES,fps=FPS,source_seconds=SECONDS,steps=12,native_audio=True)
def _quotes(text):return re.findall('“[^”]*”|「[^」]*」',text)
def _image(binding):
    path=check(binding)
    with Image.open(path) as im:
        if getattr(im,'n_frames',1)!=1 or im.size!=(WIDTH,HEIGHT):raise MultiviewError('technical_first_image_geometry_changed')
        im.verify()
    return path

def _authority(path):
    auth=read(path);limits=auth.get('engineering_limits',{})
    if (auth.get('schema')!='h3_multiview_continuity_minute_authorization/v37' or not isinstance(auth.get('user_statement'),str)
        or not auth['user_statement'].strip() or auth.get('engineering_scope_not_user_quoted_numeric_limit') is not True
        or limits!={'image_submissions':8,'video_submissions':4,'cloud_media':0} or auth.get('text_model_calls')!=0
        or auth.get('publication') is not False or auth.get('unknown_native_replay') is not False
        or auth.get('semantic_video_retakes') is not False or auth.get('review_policy')!='user_reviews_completed_film'
        or auth.get('semantic_generation_gates') is not False):raise MultiviewError('explicit_user_delegated_technical_only_authority_required')
    return auth

def _prompts(binding):
    plan=read(check(binding));rows=plan.get('segments',[])
    if plan.get('schema')!='h3_multiview_continuity_prompts/v37':raise MultiviewError('explicit_source_bound_prompt_plan_required')
    if plan.get('implementation') is not None and plan['implementation']!=bind(PROMPT_MODULE):raise MultiviewError('prompt_compiler_binding_changed')
    if plan.get('source_case') is not None:check(plan['source_case'])
    if [r.get('id') for r in rows]!=list(IDS):raise MultiviewError('four_ordered_prompt_sources_required')
    count=0
    for row in rows:
        text=check(row['prompt']).read_bytes().decode('utf-8');source=check(row['source']).read_bytes().decode('utf-8')
        if not text.strip() or _quotes(text)!=_quotes(source):raise MultiviewError('original_quotes_changed_or_duplicated')
        count+=len(_quotes(text))
    if count!=QUOTE_COUNT:raise MultiviewError('all_original_quotes_required')
    return rows

def _settings(spec,run):
    if spec.get('schema')!='h3_multiview_continuity_minute_spec/v37':raise MultiviewError('explicit_scene_performance_spec_required')
    rows=_prompts(spec['prompt_plan']);check(spec['scene_spec']);cfg=deepcopy(spec['h3_config'])
    required={'service_url','input_root','output_root','gpu_lock_root','protected_pause_path','base_workflow','timeout','video_enabled'}
    if not required<=set(cfg) or set(cfg)-required-{'width','height','runs_root'} or cfg['video_enabled'] is not True:raise MultiviewError('explicit_local_native_config_required')
    service=jobs.Config(**{k:cfg[k] for k in ('service_url','input_root','output_root','timeout')})
    # Config validates the local endpoint and actual service directories.
    normalized=service.normalized()
    if normalized['service_url']!=LOCAL_SERVICE or any(not Path(normalized[k]).is_dir() for k in ('input_root','output_root')):
        raise MultiviewError('existing_loopback_service_and_directories_required')
    cfg.update({k:normalized[k] for k in ('service_url','input_root','output_root','timeout')})
    for k in ('input_root','output_root','gpu_lock_root','protected_pause_path','base_workflow'):cfg[k]=str(Path(cfg[k]).resolve())
    if Path(cfg['gpu_lock_root'])!=Path(SHARED_GPU).resolve():raise MultiviewError('existing_shared_gpu_lock_required')
    if cfg.get('width',WIDTH)!=WIDTH or cfg.get('height',HEIGHT)!=HEIGHT:raise MultiviewError('exact_new_native_dimensions_required')
    base=read(cfg['base_workflow'])
    if (set(base)!=set(native.CLASSES) or any(base[k]['class_type']!=v for k,v in native.CLASSES.items())
        or base['124']['inputs']['steps']!=12 or base['130']['inputs']['fps']!=FPS):raise MultiviewError('sealed_twelve_step_i2v_base_required')
    return rows,cfg

def _scene_contract(run,cfg,authorization):
    scene=read(_scene_run(run)/'PLAN.json')
    if scene.get('authorization')!=authorization:raise MultiviewError('same_image_and_video_authorization_required')
    rows=_scene().status(_scene_run(run))['shots']
    if [s['id'] for s in rows]!=list(IDS):raise MultiviewError('four_ordered_scene_jobs_required')
    for row in rows:
        job=Path(row['job_dir']).resolve()
        if not job.is_relative_to(_scene_run(run)):raise MultiviewError('new_scene_job_scope_required')
        if row['status']=='unprepared':
            if (job/'PLAN.json').exists():raise MultiviewError('unprepared_scene_must_not_have_native_plan')
            continue
        _,plan,_=jobs._load(job);image_cfg=plan['config']
        if any(image_cfg[k]!=cfg[k] for k in ('service_url','input_root','output_root')) or plan['protected_pause']!=bind(cfg['protected_pause_path']):
            raise MultiviewError('images_and_videos_must_share_native_service_and_pause')

def prepare(run=RUN):
    run=_scope(run);spec_binding=bind(run/'MINUTE_SPEC.json');spec=read(check(spec_binding));rows,cfg=_settings(spec,run)
    authorization=bind(run/'USER_AUTHORIZATION.json');authority=_authority(check(authorization))
    prompts=read(check(spec['prompt_plan']))
    if authority.get('source_case') is not None:
        check(authority['source_case'])
        if authority['source_case']!=prompts.get('source_case'):raise MultiviewError('authorized_source_case_changed')
    _scene().prepare(check(spec['scene_spec']),_scene_run(run),authorization=authorization)
    _scene_contract(run,cfg,authorization)
    plan=dict(schema=SCHEMA,spec=spec_binding,authorization=authorization,prompt_plan=spec['prompt_plan'],scene_spec=spec['scene_spec'],
        scene_plan=bind(_scene_run(run)/'PLAN.json'),config=cfg,base_workflow=bind(cfg['base_workflow']),
        protected_pause=bind(cfg['protected_pause_path']),profile=_profile(),segments=rows,
        review_policy='user_reviews_completed_film',content_status='user_review_pending',production_approved=False,publication=False)
    freeze(run/'PLAN.json',plan)
    for row in rows:
        folder=_folder(run,row['id']);folder.mkdir(parents=True,exist_ok=True)
        if not (folder/'STATE.json').exists():native.write(folder/'STATE.json',dict(id=row['id'],status='prepared',prompt_id=None,plan_sha256=digest(plan)))
    first=_scene().status(_scene_run(run))['shots'][0]
    if first['status']=='unprepared':_scene().prepare_shot(_scene_run(run),IDS[0],prior_video_result=None)
    _scene_contract(run,cfg,authorization)
    return status(run)

def _load(run,current=False):
    run=_scope(run);p=read(run/'PLAN.json')
    if (p.get('schema')!=SCHEMA or p.get('profile')!=_profile() or p.get('content_status')!='user_review_pending'
        or p.get('production_approved') is not False or p.get('publication') is not False
        or p.get('review_policy')!='user_reviews_completed_film' or [r.get('id') for r in p.get('segments',[])]!=list(IDS)):
        raise MultiviewError('frozen_technical_only_minute_plan_changed')
    if current:
        _authority(check(p['authorization']));spec=read(check(p['spec']));rows,cfg=_settings(spec,run)
        if rows!=p['segments'] or cfg!=p['config'] or spec['scene_spec']!=p['scene_spec'] or spec['prompt_plan']!=p['prompt_plan']:
            raise MultiviewError('frozen_source_or_config_changed')
        if bind(cfg['base_workflow'])!=p['base_workflow'] or bind(cfg['protected_pause_path'])!=p['protected_pause']:
            raise MultiviewError('base_or_original_pause_changed')
        check(p['scene_plan'])
        _scene_contract(run,cfg,p['authorization'])
    return run,p

def _state(run,plan,sid):
    folder=_folder(run,sid);row=read(folder/'GRAPH_BINDING.json') if (folder/'GRAPH_BINDING.json').exists() else dict(id=sid)
    state=native._shot_state(folder,plan,row)
    if state['status']=='technical_saved':
        entry=read(folder/'HISTORY.json').get(state['prompt_id'],{});prompt=entry.get('prompt',[]);terminal=entry.get('status',{})
        if (len(prompt)<3 or prompt[1]!=state['prompt_id'] or terminal.get('completed') is not True
            or terminal.get('status_str')!='success' or native.native_graph_equivalence(read(folder/'workflow_api.json'),prompt[2]) is None):
            raise MultiviewError('saved_original_native_history_changed')
    return state

def _images(run):
    return _scene().status(_scene_run(run))

def status(run=RUN):
    run,p=_load(run);states=[_state(run,p,sid) for sid in IDS];ids=[s['prompt_id'] for s in states if s.get('prompt_id')]
    if len(ids)!=len(set(ids)):raise MultiviewError('distinct_native_video_ids_required')
    return dict(schema=SCHEMA,run=str(run),shots=states,images=_images(run),technical_saved=sum(s['status']=='technical_saved' for s in states),
        paused=(run/'PAUSE.json').exists(),content_status='user_review_pending',production_approved=False,publication=False)

def _sources():
    return dict(coordinator=bind(__file__),cli=bind(PROJECT/'scripts/run_h3_multiview_continuity_minute_v37.py'),scene=bind(_scene().__file__),
        prompts=bind(PROMPT_MODULE),
        native=bind(native.__file__),image_jobs=bind(jobs.__file__),clock=bind(clock.__file__),
        native_clock=bind(Path(__file__).with_name('visual_spatial_clock_v30.py')))

def _launch(run,p):
    value=read(run/'LAUNCH_APPROVAL.json')
    if (value.get('schema')!='h3_multiview_continuity_technical_launch/v37' or value.get('plan')!=bind(run/'PLAN.json')
        or value.get('authorization')!=p['authorization'] or value.get('execution_sources')!=_sources()
        or value.get('approved_for_technical_execution') is not True or value.get('review_policy')!='user_reviews_completed_film'):
        raise MultiviewError('frozen_technical_launch_binding_required')
    acceptance=check(value['cpu_acceptance'])
    if not acceptance.is_relative_to(PROJECT/'data/qa'):raise MultiviewError('project_cpu_acceptance_required')
    return value

def _append(run,sid,pid,event):
    line=sid+' '+pid;ledger=run/'job_ids.txt';old=ledger.read_text(encoding='utf-8').splitlines() if ledger.exists() else []
    if any(x.split()[0]==sid and x!=line for x in old) or any(len(x.split())==2 and x.split()[1]==pid and x!=line for x in old):raise MultiviewError('native_id_ledger_conflict')
    if line not in old:
        with ledger.open('a',encoding='utf-8') as stream:stream.write(line+'\n');stream.flush()
    with (run/'LOG.md').open('a',encoding='utf-8') as stream:stream.write(f'{time.time()} {event} {line}\n')

def _selected_image(run,sid):
    item=_scene().result(_scene_run(run),sid);image={k:item['image'][k] for k in ('path','sha256')};_image(image)
    result=read(check(item['native_result']));pid=result.get('prompt_id')
    if (result.get('technical_status')!='saved' or not pid or len(result.get('images',[]))!=1
        or {k:result['images'][0][k] for k in ('path','sha256')}!=image):raise MultiviewError('actual_saved_image_required')
    if item.get('native_id',item.get('prompt_id',pid))!=pid:raise MultiviewError('scene_receipt_native_id_changed')
    return dict(item,image=image,native_id=pid,technical_status='saved')

def _prepare_video(run,p,index):
    source=p['segments'][index];sid=source['id'];folder=_folder(run,sid);image_result=_selected_image(run,sid)
    image=image_result['image'];text=check(source['prompt']).read_bytes().decode('utf-8');scope=run.name+'/'+sid;input_name=scope+'/first_input.png'
    shot=dict(visual_prompt=text,audio=[],visible_cast=[],binding_sha256=digest(dict(source=source,image=image)))
    timing=native._timing(dict(start=0,end=SECONDS))
    if timing['native_frames']!=FRAMES:raise MultiviewError('native_clock_profile_changed')
    graph=native.build_graph(read(check(p['base_workflow'])),shot,image,timing,input_name,scope,width=WIDTH,height=HEIGHT,native_prompt=text)
    first=folder/'first_input.png'
    if not first.exists():jobs._copy_new(check(image),first)
    if bind(first)['sha256']!=image['sha256']:raise MultiviewError('first_input_not_saved_scene_pixels')
    row=dict(id=sid,scope=scope,graph_sha256=digest(graph),first_frame=bind(first),input_name=input_name,timing=timing,
        source_prompt=source['prompt'],source=source['source'],scene_result=image_result,content_status='user_review_pending')
    if index:
        previous=_folder(run,IDS[index-1]);result=read(previous/'RESULT.json')
        if _state(run,p,IDS[index-1])['status']!='technical_saved':raise MultiviewError('original_previous_segment_not_saved')
        prior=bind(previous/'RESULT.json')
        proof=image_result.get('prior_video')
        if not isinstance(proof,dict) or proof.get('result')!=prior:raise MultiviewError('scene_image_not_bound_to_actual_previous_video')
        row['previous_tail']=dict(image={k:result['files']['last'][k] for k in ('path','sha256')},native_result=prior,
            native_id=result['prompt_id'],previous_segment=IDS[index-1],
            use='actual_primary_positive_input_to_current_scene_job_not_an_additional_direct_video_input')
    freeze(folder/'workflow_api.json',graph);freeze(folder/'GRAPH_BINDING.json',row)
    return row,graph

def submit_video(run=RUN,*,shot):
    run,p=_load(run)
    with jobs.run_lock(run,'DISPATCH.lock'):
        current=status(run)
        if current['paused']:return dict(current,dispatch='paused')
        states=current['shots'];index=next((i for i,s in enumerate(states) if s['status']!='technical_saved'),None)
        if index is None or states[index]['status']!='prepared':return current
        if IDS[index]!=shot:return dict(current,dispatch='waiting_prior_video',expected_shot=IDS[index])
        _load(run,current=True);_launch(run,p)
        if any(s.get('status') in BAD for s in states):return dict(current,dispatch='unknown_or_failed_native_preserved')
        with native._gpu(p):
            _load(run,current=True);_launch(run,p)
            if (run/'PAUSE.json').exists():return dict(current,dispatch='paused')
            native._service_paths(p['config']);q=native._queue(p['config'])
            if q['queue_running'] or q['queue_pending']:return dict(current,dispatch='waiting_native_queue')
            if len(list((run/'shots').glob('*/CLAIM.json')))>=4:raise MultiviewError('four_new_video_submissions_maximum')
            row,graph=_prepare_video(run,p,index);sid=row['id'];folder=_folder(run,sid)
            jobs.stage_input({k:p['config'][k] for k in ('service_url','input_root','output_root','timeout')},check(row['first_frame']),row['input_name'],row['first_frame']['sha256'])
            request=read(folder/'REQUEST.json') if (folder/'REQUEST.json').exists() else dict(prompt=graph,client_id=uuid.uuid4().hex)
            if digest(request.get('prompt'))!=row['graph_sha256']:raise MultiviewError('prepost_request_changed')
            freeze(folder/'REQUEST.json',request)
            freeze(folder/'CLAIM.json',dict(at=time.time(),graph_sha256=row['graph_sha256'],first_frame_sha256=row['first_frame']['sha256'],request=bind(folder/'REQUEST.json')))
            state=states[index]
            try:response=native._http(p['config'],'/prompt',request)
            except urllib.error.HTTPError as error:
                freeze(folder/'POST_ERROR.json',dict(type='HTTPError',code=error.code));state['status']='rejected' if error.code in (400,422) else 'outcome_unknown'
            except Exception as error:
                freeze(folder/'POST_ERROR.json',dict(type=type(error).__name__));state['status']='outcome_unknown'
            else:
                freeze(folder/'RESPONSE.json',response);pid=response.get('prompt_id') if isinstance(response,dict) else None
                if isinstance(pid,str) and re.fullmatch('[A-Za-z0-9_-]{1,100}',pid) and not response.get('node_errors'):
                    state.update(status='submitted',prompt_id=pid);_append(run,sid,pid,'SUBMIT')
                else:state['status']='rejected' if isinstance(response,dict) and response.get('node_errors') else 'outcome_unknown'
            native.write(folder/'STATE.json',state)
    return status(run)

def collect_known(run=RUN):
    run,p=_load(run);errors=[]
    with jobs.run_lock(run,'COLLECT.lock'):
        for sid in IDS:
            state=_state(run,p,sid)
            if not state.get('prompt_id') or state['status'] in ('technical_saved','failed','interrupted','rejected'):continue
            folder=_folder(run,sid);row=read(folder/'GRAPH_BINDING.json');pid=state['prompt_id']
            try:
                history=native._http(p['config'],'/history/'+native.slug(pid))
                if not isinstance(history,dict):raise MultiviewError('native_history_response_required')
                entry=history.get(pid)
                if entry:
                    prompt=entry.get('prompt',[]);terminal=entry.get('status',{})
                    if (len(prompt)<3 or prompt[1]!=pid or not native._verify_native_graph(folder,row,prompt[2],pid)
                        or type(terminal.get('completed')) is not bool or terminal.get('status_str') not in ('success','error')):
                        raise MultiviewError('native_history_identity_or_schema_changed')
                    native.write(folder/'HISTORY.latest.json',history)
                    if terminal['status_str']=='error':
                        events=[x[0] for x in terminal.get('messages',[]) if isinstance(x,list) and x]
                        state.update(status='interrupted' if 'execution_interrupted' in events else 'failed',native_terminal=terminal)
                    elif terminal['completed']:
                        freeze(folder/'HISTORY.json',history);native._collect(folder,p,row,state,entry)
                        freeze(folder/'USER_REVIEW_STATUS.json',dict(content_status='user_review_pending',native_result=bind(folder/'RESULT.json'),production_approved=False))
                        _append(run,sid,pid,'SAVED')
                    else:state['status']='running'
                else:
                    q=native._queue(p['config']);matches=[r for r in q['queue_running']+q['queue_pending'] if len(r)>2 and r[1]==pid]
                    if any(not native._verify_native_graph(folder,row,r[2],pid) for r in matches):raise MultiviewError('native_queue_graph_changed')
                    state.update(status='running' if matches else 'outcome_unknown')
                native.write(folder/'STATE.json',state)
            except OSError as error:errors.append(dict(id=sid,native_id=pid,type=type(error).__name__,message=str(error)))
        # A changed current scene spec cannot prevent existing video collection.
        try:_scene().collect_known(_scene_run(run))
        except (OSError,ValueError,KeyError) as error:errors.append(dict(stage='images',type=type(error).__name__,message=str(error)))
    value=status(run)
    if errors:
        native.write(run/'COLLECTION_ERRORS.json',dict(errors=errors,new_dispatch_blocked=True));value['collection_errors']=errors
    return value

def tick(run=RUN,*,stage,shot,allow_submit=False):
    if stage not in ('images','videos') or shot not in IDS or type(allow_submit) is not bool:raise MultiviewError('explicit_stage_shot_and_submit_boolean_required')
    run,p=_load(run)
    with jobs.run_lock(run,'STEP.lock'):
        current=collect_known(run)
        if current['technical_saved']==4:return assemble(run)
        if current.get('collection_errors'):return dict(current,dispatch='collection_error_no_new_post')
        if current['paused']:return dict(current,dispatch='paused')
        index=next(i for i,s in enumerate(current['shots']) if s['status']!='technical_saved')
        if shot!=IDS[index]:
            if current['shots'][IDS.index(shot)]['status']=='technical_saved':return dict(current,dispatch='segment_saved_next_image_required',next_shot=IDS[index])
            return dict(current,dispatch='waiting_prior_video',expected_shot=IDS[index])
        try:
            _load(run,current=True)
            if allow_submit:_launch(run,p)
        except (OSError,ValueError,KeyError) as error:
            value=dict(current,dispatch='blocked_current_inputs',error=dict(type=type(error).__name__,message=str(error)))
            native.write(run/'INPUT_INVALID.json',value);return value
        if any(s['status'] in BAD for s in current['shots']):return dict(current,dispatch='unknown_or_failed_native_preserved')
        if any(s['status'] in BAD for s in current['images']['shots']):return dict(current,dispatch='unknown_or_failed_native_preserved')
        if any(s['status'] in ('submitted','running') for s in current['shots']):return current
        if stage=='images':
            prior=bind(_folder(run,IDS[index-1])/'RESULT.json') if index else None
            try:
                _scene().prepare_shot(_scene_run(run),shot,prior_video_result=prior)
                _scene_contract(run,p['config'],p['authorization'])
            except (OSError,ValueError,KeyError) as error:
                value=dict(current,dispatch='blocked_current_inputs',error=dict(type=type(error).__name__,message=str(error)))
                native.write(run/'INPUT_INVALID.json',value);return value
            image=_images(run)['shots'][index]
            if image['status']=='saved':return dict(status(run),dispatch='image_saved_cold_family_transition_by_owner',shot_id=shot)
            if image['status'] in BAD:return dict(status(run),dispatch='unknown_or_failed_native_preserved')
            if allow_submit:
                root=Path(p['config']['gpu_lock_root']);root.mkdir(parents=True,exist_ok=True)
                # Producer's jobs.submit owns input/VISUAL_GPU.lock; the outer
                # shared GPU lock also serializes older asset/VLM callers.
                with jobs.run_lock(root,'GPU.lock'):
                    _load(run,current=True);_launch(run,p)
                    if not (run/'PAUSE.json').exists():_scene().submit_next(_scene_run(run))
            return status(run)
        if current['images']['shots'][index]['status']!='saved':return dict(current,dispatch='current_saved_scene_image_required',shot_id=shot)
        return submit_video(run,shot=shot) if allow_submit else dict(current,dispatch='video_prepared_technical_only',shot_id=shot)

def assemble(run=RUN):
    run,p=_load(run)
    with jobs.run_lock(run,'ASSEMBLY.lock'):
        if status(run)['technical_saved']!=4:raise MultiviewError('four_saved_native_video_results_required')
        paths=[_folder(run,sid)/'RESULT.json' for sid in IDS];results=[read(path) for path in paths]
        ids=[r['prompt_id'] for r in results];videos=[r['files']['video'] for r in results]
        if len(set(ids))!=4 or len({v['sha256'] for v in videos})!=4:raise MultiviewError('four_distinct_original_videos_required')
        inputs=dict(plan=bind(run/'PLAN.json'),native_results=[bind(path) for path in paths]);source_sha=digest(inputs)
        final=run/'FINAL_RESULT.json';output=run/'H3_MULTIVIEW_CONTINUITY_MINUTE_736x1312.mp4'
        if final.exists():
            value=read(final);check(value['file'])
            if value['assembly_inputs_sha256']!=source_sha:raise MultiviewError('frozen_assembly_input_changed')
            return value
        if output.exists():raise MultiviewError('unreceipted_final_preserved')
        adjustments=[clock_input(v['path'],v['sha256'],frames=FRAMES,width=WIDTH,height=HEIGHT) for v in videos]
        filters=run/'ASSEMBLY_FILTER.txt';command,text=clock.assembly_command([v['path'] for v in videos],filters,output,frames=FRAMES)
        filters.write_text(text,encoding='utf-8');freeze(run/'ASSEMBLY_REQUEST.json',dict(inputs=inputs,adjustments=adjustments,command=command,subtitle_postproduction_enabled=False))
        process=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=1800)
        (run/'ASSEMBLY.stderr.log').write_text(process.stderr,encoding='utf-8');process.check_returncode()
        timing=clock.verify_clock(clock._probe(output,count=True),frames=4*FRAMES,width=WIDTH,height=HEIGHT)
        if inputs['native_results']!=[bind(path) for path in paths]:raise MultiviewError('native_results_changed_during_assembly')
        value=dict(schema=SCHEMA,file=bind(output),native_ids=ids,clock=timing,assembly_inputs_sha256=source_sha,
            content_status='user_review_pending',production_approved=False,publication=False,subtitle_postproduction_enabled=False,
            burned_text_absence_verified=False,semantic_review='delegated_to_user')
        freeze(final,value);return value

def execute(run=RUN,*,stage,shot,poll_seconds=30,max_seconds=86400):
    if stage not in ('images','videos') or shot not in IDS or not 1<=poll_seconds<=60 or not 0<max_seconds<=86400:raise MultiviewError('bounded_explicit_stage_shot_required')
    run,p=_load(run)
    with jobs.run_lock(run,'RUNNER.lock'):
        started=time.monotonic()
        while True:
            result=tick(run,stage=stage,shot=shot,allow_submit=True)
            if 'file' in result or result.get('dispatch') in ('image_saved_cold_family_transition_by_owner','segment_saved_next_image_required',
                    'waiting_prior_video','unknown_or_failed_native_preserved','blocked_current_inputs','current_saved_scene_image_required'):return result
            if time.monotonic()-started>=max_seconds:return dict(result,dispatch='bounded_wait_original_ids_preserved')
            time.sleep(poll_seconds)
