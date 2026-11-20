"""One prompt-only S02 native probe; no minute/image/service orchestration."""
from copy import deepcopy
from pathlib import Path
import re,time,urllib.error,uuid
from . import visual_h3_baseline_two_rounds_v38 as base
from . import visual_h3_handoff_v3 as native
from . import visual_image_jobs_v3 as jobs

PROJECT=Path(__file__).resolve().parents[2]
RUN=PROJECT/'data/video_generation/h3_s02_prompt_probe_20261110_v1'
SOURCE=PROJECT/'data/video_generation/h3_baseline_two_rounds_20261109_v1/R2'
SHARED_GPU=PROJECT/'data/visual_asset_pipeline/gpu'
LOCAL_SERVICE='http://127.0.0.1:8190'
SCHEMA='h3_s02_prompt_probe/v39';SID='S02';SEED=45905597282583733
FIRST_SHA='d44f2e648f91e6546e8b6da857c812b47d31a48ec3fcd1be272da2dc11558917'
read=base.read;bind=base.bind;check=base.check;freeze=base.freeze;digest=base.digest
BAD={'outcome_unknown','failed','interrupted','rejected'}

class ProbeError(ValueError):pass
def _scope(run):
    run=Path(run).resolve()
    if run!=Path(RUN).resolve():raise ProbeError('only_explicit_new_single_S02_probe_allowed')
    return run
def _folder(run):return Path(run)/'shots'/SID

def _source():
    p=read(SOURCE/'PLAN.json');rows=[r for r in p['segments'] if r['id']==SID]
    if p.get('round')!='R2' or len(rows)!=1:raise ProbeError('actual_R2_S02_source_required')
    row=rows[0];folder=SOURCE/'shots'/SID;request=bind(folder/'REQUEST.json');g=read(check(request))['prompt'];state=read(folder/'STATE.json');result=read(folder/'RESULT.json')
    pid=state.get('prompt_id');history=read(folder/'HISTORY.json').get(pid,{});prompt=history.get('prompt',[])
    if (state.get('status')!='technical_saved' or state.get('id')!=SID or state.get('plan_sha256')!=digest(p)
        or read(folder/'GRAPH_BINDING.json')!=row or result.get('technical_status')!='technical_saved' or result.get('prompt_id')!=pid
        or not pid or len(prompt)<3 or prompt[1]!=pid or history.get('status',{}).get('completed') is not True
        or history['status'].get('status_str')!='success' or native.native_graph_equivalence(g,prompt[2]) is None
        or read(folder/'workflow_api.json')!=g or result.get('graph_sha256')!=digest(g) or result.get('timing')!=row.get('timing')
        or row.get('timing',{}).get('native_frames')!=362 or row['timing'].get('requested_seconds')!=15):
        raise ProbeError('source_original_native_request_and_saved_identity_required')
    first=row['first_frame'];base._image(first)
    if first['sha256']!=FIRST_SHA or row['seed']!=SEED or g['129']['inputs']['noise_seed']!=SEED or result.get('first_frame_sha256')!=FIRST_SHA:
        raise ProbeError('fixed_R2_S02_seed_and_first_pixels_required')
    c=g['condition']['inputs'];scope=g['save_video']['inputs']['filename_prefix'].rsplit('/',1)[0]
    native._validate_graph(g,scope,g['ref_scene']['inputs']['image'])
    if (c['width'],c['height'],c['length'],g['124']['inputs']['steps'],g['130']['inputs']['fps'])!=(736,1312,362,12,24):raise ProbeError('fixed_native_S02_profile_required')
    cfg=deepcopy(p['config'])
    if cfg['service_url']!=LOCAL_SERVICE or Path(cfg['gpu_lock_root']).resolve()!=Path(SHARED_GPU).resolve():raise ProbeError('same_local_service_and_gpu_mutex_required')
    return dict(plan=bind(SOURCE/'PLAN.json'),request=request,result=bind(folder/'RESULT.json'),native_id=pid,first=first,template=g,timing=row['timing'],config=cfg,protected_pause=p['protected_pause'])

def bootstrap(run=RUN):
    run=_scope(run);scope=read(run/'ROOT_USER_SCOPE.json');s=_source()
    if (not scope.get('user_statement') or Path(PROJECT/scope.get('source','')).resolve()!=(SOURCE/'shots'/SID).resolve()
        or scope.get('engineering_limits_not_user_quoted_numeric')!={'video':1,'images':0,'cloud':0,'publication':False} or scope.get('unknown_replay') is not False):
        raise ProbeError('explicit_one_S02_prompt_probe_scope_required')
    value=dict(schema='h3_s02_prompt_probe_authorization/v39',user_statement=scope['user_statement'],user_scope=bind(run/'ROOT_USER_SCOPE.json'),
        source_request=s['request'],engineering_scope_not_user_quoted_numeric_limit=True,engineering_limits=dict(video_submissions=1,image_submissions=0,cloud_media=0),publication=False,unknown_native_replay=False)
    freeze(run/'USER_AUTHORIZATION.json',value);return value

def _authority(run):
    v=read(run/'USER_AUTHORIZATION.json');scope=read(check(v['user_scope']))
    if (v.get('schema')!='h3_s02_prompt_probe_authorization/v39' or v.get('user_statement')!=scope.get('user_statement')
        or not v.get('user_statement') or v.get('engineering_scope_not_user_quoted_numeric_limit') is not True
        or v.get('engineering_limits')!={'video_submissions':1,'image_submissions':0,'cloud_media':0}
        or v.get('publication') is not False or v.get('unknown_native_replay') is not False
        or v.get('source_request')!=bind(SOURCE/'shots/S02/REQUEST.json')):raise ProbeError('single_native_probe_authority_changed')
    return v

def prepare(run=RUN):
    run=_scope(run)
    if not (run/'USER_AUTHORIZATION.json').exists():bootstrap(run)
    _authority(run);s=_source();prompt=bind(run/'PROMPT.txt');text=check(prompt).read_bytes().decode('utf-8');old=s['template']['condition']['inputs']['prompt']
    if not text.strip() or base.quotes(text)!=base.quotes(old) or len(base.quotes(text))!=2:raise ProbeError('both_original_S02_quotes_required_exactly_once')
    folder=_folder(run);folder.mkdir(parents=True,exist_ok=True);first=folder/'first_input.png'
    if not first.exists():jobs._copy_new(check(s['first']),first)
    if bind(first)['sha256']!=FIRST_SHA:raise ProbeError('copied_first_pixels_changed')
    scope=run.name+'/'+SID;graph=base.build_graph(s['template'],text,scope)
    row=dict(id=SID,scope=scope,graph_sha256=digest(graph),first_frame=bind(first),input_name=scope+'/first_input.png',timing=s['timing'],source_prompt=prompt,
        source_request=s['request'],source_first=s['first'],seed=SEED,only_prompt_and_namespace_changed=True)
    p=dict(schema=SCHEMA,authorization=bind(run/'USER_AUTHORIZATION.json'),source_plan=s['plan'],source_request=s['request'],source_result=s['result'],source_native_id=s['native_id'],
        prompt=prompt,config=s['config'],protected_pause=s['protected_pause'],shot=row,max_native_video_submissions=1,image_generation_calls=0,publication=False,production_approved=False)
    freeze(folder/'workflow_api.json',graph);freeze(folder/'GRAPH_BINDING.json',row);freeze(run/'PLAN.json',p)
    if not (folder/'STATE.json').exists():native.write(folder/'STATE.json',dict(id=SID,status='prepared',prompt_id=None,plan_sha256=digest(p)))
    return status(run)

def _load(run,current=False):
    run=_scope(run);p=read(run/'PLAN.json')
    if p.get('schema')!=SCHEMA or p.get('max_native_video_submissions')!=1 or p.get('image_generation_calls')!=0 or p.get('publication') is not False or p.get('shot',{}).get('id')!=SID:
        raise ProbeError('single_S02_frozen_plan_required')
    if current:
        _authority(run);check(p['authorization']);s=_source();text=check(p['prompt']).read_bytes().decode('utf-8');base._image(p['shot']['first_frame']);check(p['protected_pause'])
        if (p['source_plan']!=s['plan'] or p['source_request']!=s['request'] or p['source_result']!=s['result'] or p['config']!=s['config']
            or p['shot']['source_first']!=s['first'] or p['shot']['first_frame']['sha256']!=FIRST_SHA or p['shot']['seed']!=SEED
            or base.quotes(text)!=base.quotes(s['template']['condition']['inputs']['prompt'])):raise ProbeError('frozen_source_prompt_or_first_changed')
        expected=base.build_graph(s['template'],text,p['shot']['scope'])
        if expected!=read(_folder(run)/'workflow_api.json') or digest(expected)!=p['shot']['graph_sha256']:raise ProbeError('graph_changed_beyond_prompt_and_namespace')
    return run,p

def _state(run,p):
    folder=_folder(run);row=p['shot']
    if read(folder/'GRAPH_BINDING.json')!=row:raise ProbeError('original_graph_binding_changed')
    state=native._shot_state(folder,p,row)
    if state['status']=='technical_saved':
        entry=read(folder/'HISTORY.json').get(state['prompt_id'],{});prompt=entry.get('prompt',[])
        if len(prompt)<3 or prompt[1]!=state['prompt_id'] or entry.get('status',{}).get('completed') is not True or native.native_graph_equivalence(read(folder/'workflow_api.json'),prompt[2]) is None:raise ProbeError('saved_original_native_history_changed')
    return state

def status(run=RUN):
    run,p=_load(run);return dict(schema=SCHEMA,run=str(run),shot=_state(run,p),paused=(run/'PAUSE.json').exists(),image_generation_calls=0,content_status='review_pending',production_approved=False)

def _sources():
    return dict(executor=bind(__file__),cli=bind(PROJECT/'scripts/run_h3_s02_prompt_probe_v39.py'),baseline_graph_helpers=bind(base.__file__),native=bind(native.__file__),image_jobs=bind(jobs.__file__))

def _launch(run,p):
    v=read(run/'LAUNCH_APPROVAL.json')
    if (v.get('schema')!='h3_s02_probe_technical_launch/v39' or v.get('plan')!=bind(run/'PLAN.json') or v.get('authorization')!=p['authorization']
        or v.get('execution_sources')!=_sources() or v.get('approved_for_technical_execution') is not True):raise ProbeError('single_probe_technical_launch_required')
    if not check(v['cpu_acceptance']).is_relative_to(PROJECT/'data/qa'):raise ProbeError('project_CPU_acceptance_required')

def _log(run,event,pid=''):
    with (run/'LOG.md').open('a',encoding='utf-8') as stream:stream.write(f'{time.time()} {event} {SID} {pid}\n')
    if pid:
        path=run/'job_ids.txt';line=SID+' '+pid
        if path.exists():
            if path.read_text(encoding='utf-8').strip()!=line:raise ProbeError('single_original_native_ID_required')
        else:base._bytes(path,(line+'\n').encode('utf-8'))

def submit(run=RUN):
    run,p=_load(run);folder=_folder(run);row=p['shot']
    with jobs.run_lock(run,'DISPATCH.lock'):
        state=_state(run,p)
        if state['status']!='prepared' or (run/'PAUSE.json').exists():return status(run)
        _load(run,current=True);_launch(run,p)
        with native._gpu(p):
            _load(run,current=True);_launch(run,p)
            if (run/'PAUSE.json').exists() or (folder/'CLAIM.json').exists():return status(run)
            native._service_paths(p['config']);queue=native._queue(p['config'])
            if queue['queue_running'] or queue['queue_pending']:return dict(status(run),dispatch='waiting_native_queue')
            jobs.stage_input({k:p['config'][k] for k in ('service_url','input_root','output_root','timeout')},check(row['first_frame']),row['input_name'],FIRST_SHA)
            graph=read(folder/'workflow_api.json');request=read(folder/'REQUEST.json') if (folder/'REQUEST.json').exists() else dict(prompt=graph,client_id=uuid.uuid4().hex)
            if digest(request.get('prompt'))!=row['graph_sha256']:raise ProbeError('prepost_request_changed')
            freeze(folder/'REQUEST.json',request);freeze(folder/'CLAIM.json',dict(at=time.time(),graph_sha256=row['graph_sha256'],first_frame_sha256=FIRST_SHA,request=bind(folder/'REQUEST.json')))
            try:response=native._http(p['config'],'/prompt',request)
            except urllib.error.HTTPError as error:
                freeze(folder/'POST_ERROR.json',dict(type='HTTPError',code=error.code));state['status']='rejected' if error.code in (400,422) else 'outcome_unknown'
            except Exception as error:
                freeze(folder/'POST_ERROR.json',dict(type=type(error).__name__));state['status']='outcome_unknown'
            else:
                freeze(folder/'RESPONSE.json',response);pid=response.get('prompt_id') if isinstance(response,dict) else None
                if isinstance(pid,str) and re.fullmatch('[A-Za-z0-9_-]{1,100}',pid) and not response.get('node_errors'):
                    state.update(status='submitted',prompt_id=pid);_log(run,'SUBMIT',pid)
                else:state['status']='rejected' if isinstance(response,dict) and response.get('node_errors') else 'outcome_unknown'
            native.write(folder/'STATE.json',state)
    return status(run)

def collect_known(run=RUN):
    run,p=_load(run);folder=_folder(run);row=p['shot']
    with jobs.run_lock(run,'COLLECT.lock'):
        state=_state(run,p)
        if not state.get('prompt_id') or state['status'] in ('technical_saved','failed','interrupted','rejected'):return status(run)
        pid=state['prompt_id'];history=native._http(p['config'],'/history/'+native.slug(pid))
        if not isinstance(history,dict):raise ProbeError('native_history_response_required')
        entry=history.get(pid)
        if entry:
            prompt=entry.get('prompt',[]);terminal=entry.get('status',{})
            if (len(prompt)<3 or prompt[1]!=pid or not native._verify_native_graph(folder,row,prompt[2],pid)
                or type(terminal.get('completed')) is not bool or terminal.get('status_str') not in ('success','error')):raise ProbeError('original_native_history_changed')
            native.write(folder/'HISTORY.latest.json',history)
            if terminal['status_str']=='error':
                events=[x[0] for x in terminal.get('messages',[]) if isinstance(x,list) and x];state['status']='interrupted' if 'execution_interrupted' in events else 'failed'
            elif terminal['completed']:
                freeze(folder/'HISTORY.json',history);native._collect(folder,p,row,state,entry);_log(run,'SAVED',pid)
            else:state['status']='running'
        else:
            q=native._queue(p['config']);matches=[v for v in q['queue_running']+q['queue_pending'] if len(v)>2 and v[1]==pid]
            if any(not native._verify_native_graph(folder,row,v[2],pid) for v in matches):raise ProbeError('original_native_queue_graph_changed')
            state['status']='running' if matches else 'outcome_unknown'
        native.write(folder/'STATE.json',state)
    return status(run)

def finalize(run=RUN):
    run,p=_load(run)
    if _state(run,p)['status']!='technical_saved':raise ProbeError('one_saved_original_S02_required')
    native_result=_folder(run)/'RESULT.json';r=read(native_result)
    value=dict(schema=SCHEMA,file={k:r['files']['video'][k] for k in ('path','sha256')},native_id=r['prompt_id'],native_result=bind(native_result),
        files=r['files'],timing=r['timing'],content_status='review_pending',production_approved=False,publication=False,postprocessing=[])
    freeze(run/'FINAL_RESULT.json',value);return value

def tick(run=RUN,*,allow_submit=False):
    if type(allow_submit) is not bool:raise ProbeError('explicit_submit_boolean_required')
    run,p=_load(run)
    with jobs.run_lock(run,'STEP.lock'):
        cur=collect_known(run)
        if cur['shot']['status']=='technical_saved':return finalize(run)
        if cur['paused']:return dict(cur,dispatch='paused')
        if cur['shot']['status'] in BAD:return dict(cur,dispatch='unknown_or_failed_native_preserved')
        try:
            _load(run,current=True)
            if allow_submit:_launch(run,p)
        except (OSError,ValueError,KeyError) as error:
            v=dict(cur,dispatch='blocked_current_inputs',error=dict(type=type(error).__name__,message=str(error)));native.write(run/'INPUT_INVALID.json',v);return v
        return submit(run) if allow_submit else cur

def execute(run=RUN,*,poll_seconds=30,max_seconds=86400):
    if not 1<=poll_seconds<=60 or not 0<max_seconds<=86400:raise ProbeError('bounded_execution_required')
    run,_=_load(run)
    with jobs.run_lock(run,'RUNNER.lock'):
        start=time.monotonic()
        while True:
            v=tick(run,allow_submit=True)
            if 'file' in v or v.get('dispatch') in ('blocked_current_inputs','unknown_or_failed_native_preserved'):return v
            if time.monotonic()-start>=max_seconds:return dict(v,dispatch='bounded_wait_original_ID_preserved')
            time.sleep(poll_seconds)
