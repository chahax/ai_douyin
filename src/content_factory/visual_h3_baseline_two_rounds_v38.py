"""Two explicit baseline video rounds, with a real overall review between them.

Only native H3 videos are submitted. R1 preserves the confirmed v34 request
recipe/first pixels/seeds and adds two reversible text insertions. R2 is an
explicit prompt/first-image selection made after the finished R1 review.
"""
from copy import deepcopy
from pathlib import Path
import hashlib,json,re,subprocess,time,urllib.error,uuid
from PIL import Image
from . import visual_h3_handoff_v3 as native
from . import visual_image_jobs_v3 as jobs
from . import visual_h3_prompt_parity_v19 as clock
from .visual_spatial_clock_v30 import clock_input

PROJECT=Path(__file__).resolve().parents[2]
ROOT=PROJECT/'data/video_generation/h3_baseline_two_rounds_20261109_v1'
BASELINE=PROJECT/'data/qa/h3_baseline_rollback_20261109_v1'
ORIGIN=PROJECT/'data/video_generation/h3_continuity_full_minute_20261109_v1/PLAN.json'
BASELINE_NAME='h3_continuity_full_minute_20261109_v1'
LOCAL_SERVICE='http://127.0.0.1:8190'
SHARED_GPU=PROJECT/'data/visual_asset_pipeline/gpu'
SCHEMA='h3_baseline_two_rounds/v38'
IDS=('S01','S02','S03','S04');ROLES=('video','audio','first','last')
WIDTH,HEIGHT,FRAMES,FPS,SECONDS=736,1312,362,24,15
BAD={'outcome_unknown','failed','interrupted','rejected'}
TEXT='画面不出现字幕，台词仅作为声音演出。'
GAZE={
 'S01':'逐镜视线沿剧情对象：0—5秒叶西决看叶南；5—9秒叶南看叶西决；9—13秒兄弟看着彼此；13—15秒苏墨维持原闭眼状态。',
 'S02':'逐镜视线沿剧情对象：0—7秒苏墨在睁眼后看向叶西决；7—12秒叶西决看苏墨、苏墨看叶西决和面包、叶南看弟弟；12—13.5秒沿用原手部近景；13.5—15秒苏墨看面包与孩子。',
 'S03':'逐镜视线沿剧情对象：0—2秒叶西决看苏墨；2—7秒苏墨看叶西决；7—10秒叶西决沿原动作闭紧双眼；10—13秒叶南关注弟弟与苏墨、苏墨看孩子；13—15秒苏墨看面包与叶西决、叶南看两人的交接。',
 'S04':'逐镜视线沿剧情对象：0—3秒苏墨看叶西决；3—10秒叶西决看苏墨、叶南按原动作看苏墨再看弟弟；10—12秒孩子的视线随行进方向与房门；12—15秒苏墨看他们离开的门口。'}

class BaselineError(ValueError):pass
def read(p):return native.read(p)
def bind(p):return dict(path=str(Path(p).resolve()),sha256=native.file_sha(p))
def check(b):
    if not isinstance(b,dict) or set(b)!={'path','sha256'} or bind(b['path'])!=b:raise BaselineError('bound_input_changed')
    return Path(b['path'])
def freeze(p,v):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);native.freeze(p,v)
def digest(v):return native.fingerprint(v)
def quotes(text):return re.findall('“[^”]*”|「[^」]*」',text)
def _bytes(path,raw):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if path.read_bytes()!=raw:raise BaselineError('frozen_bytes_changed')
    else:
        with path.open('xb') as stream:stream.write(raw)
def _scope(run):
    run=Path(run).resolve()
    if run.parent!=Path(ROOT).resolve() or run.name not in ('R1','R2'):raise BaselineError('only_new_R1_or_R2_scope_allowed')
    return run
def _folder(run,sid):return Path(run)/'shots'/sid
def _image(b):
    p=check(b)
    with Image.open(p) as im:
        if im.size!=(WIDTH,HEIGHT) or getattr(im,'n_frames',1)!=1:raise BaselineError('baseline_native_first_dimensions_changed')
        im.verify()
    return p

def compile_r1(source,sid):
    """Two additions only. The source is actual REQUEST text, not a CRLF copy."""
    raw=source.encode('utf-8');anchor='声音轨按原句依次演出：'.encode('utf-8')
    if sid not in IDS or raw.count(anchor)!=1 or b'\n' not in raw:raise BaselineError('confirmed_baseline_text_structure_required')
    offsets=[raw.index(b'\n')+1,raw.index(anchor)];inserted=[(TEXT+'\n').encode('utf-8'),(GAZE[sid]+'\n').encode('utf-8')]
    out=raw;edits=[];added=0
    for pos,data in zip(offsets,inserted):
        edits.append(dict(source_byte_offset=pos,compiled_byte_offset=pos+added,insertion_utf8=data.decode('utf-8')));added+=len(data)
    for pos,data in reversed(list(zip(offsets,inserted))):out=out[:pos]+data+out[pos:]
    audit=dict(schema='baseline_minimal_prompt_patch/v38',source_utf8_sha256=hashlib.sha256(raw).hexdigest(),source_byte_sha256=hashlib.sha256(raw).hexdigest(),
        compiled_byte_sha256=hashlib.sha256(out).hexdigest(),insertions=edits,only_caption_and_per_camera_partner_gaze_added=True,
        original_quotes=quotes(source),audio_section_byte_identical=True)
    if undo_patch(out,audit)!=raw or quotes(out.decode('utf-8'))!=quotes(source):raise BaselineError('baseline_text_not_exactly_reversible')
    return out,audit

def undo_patch(raw,audit):
    if hashlib.sha256(raw).hexdigest()!=audit['compiled_byte_sha256']:raise BaselineError('compiled_patch_bytes_changed')
    out=raw
    for edit in reversed(audit['insertions']):
        p=edit['compiled_byte_offset'];value=edit['insertion_utf8'].encode('utf-8')
        if out[p:p+len(value)]!=value:raise BaselineError('patch_offset_changed')
        out=out[:p]+out[p+len(value):]
    if hashlib.sha256(out).hexdigest()!=audit['source_byte_sha256']:raise BaselineError('baseline_byte_replay_changed')
    return out

def _baseline():
    audit=read(BASELINE/'INPUT_AUDIT.json')
    if audit.get('user_selected_baseline')!=BASELINE_NAME:raise BaselineError('confirmed_v34_baseline_required')
    groups=[r for r in audit['runs'] if r['run']==BASELINE_NAME]
    if len(groups)!=1 or [s['shot'] for s in groups[0]['segments']]!=list(IDS):raise BaselineError('four_actual_baseline_requests_required')
    rows=[]
    for item in groups[0]['segments']:
        sid=item['shot'];folder=BASELINE/sid;request=bind(folder/'REQUEST.baseline.original.json')
        if request['sha256']!=item['request']['sha256']:raise BaselineError('baseline_request_snapshot_not_original_bytes')
        graph=read(check(request))['prompt'];text=graph['condition']['inputs']['prompt'];snapshot=bind(folder/'PROMPT.baseline.actual.txt')
        if snapshot!=item['prompt_snapshot'] or check(snapshot).read_bytes().decode('utf-8').replace('\r\n','\n')!=text:
            raise BaselineError('readable_prompt_copy_not_actual_request_text')
        first=bind(folder/'first_input.baseline.png')
        if first!=item['baseline_first_input']['snapshot'] or first['sha256']!=item['baseline_first_input']['original']['sha256']:
            raise BaselineError('baseline_staged_first_snapshot_changed')
        _image(first);oldscope=graph['save_video']['inputs']['filename_prefix'].rsplit('/',1)[0]
        native._validate_graph(graph,oldscope,graph['ref_scene']['inputs']['image'])
        c=graph['condition']['inputs']
        if (c['width'],c['height'],c['length'],graph['130']['inputs']['fps'],graph['124']['inputs']['steps'])!=(WIDTH,HEIGHT,FRAMES,FPS,12):raise BaselineError('actual_baseline_profile_changed')
        seed=graph['129']['inputs']['noise_seed']
        if seed!=item['seed'] or [q[1:-1] for q in quotes(text)]!=item['quotes']:raise BaselineError('baseline_seed_or_actual_quotes_changed')
        rows.append(dict(id=sid,baseline_request=request,baseline_prompt_snapshot=snapshot,baseline_first=first,baseline_seed=seed,
            template=graph,actual_text=text,snapshot_newline_transport=dict(snapshot_CRLF=check(snapshot).read_bytes().count(b'\r\n'),actual_request_CR=text.count('\r'),authority='actual_REQUEST.condition.prompt_UTF8')))
    if sum(len(quotes(r['actual_text'])) for r in rows)!=10:raise BaselineError('ten_actual_baseline_quotes_required')
    return rows

def bootstrap():
    scope=read(ROOT/'ROOT_USER_SCOPE.json');limits=scope.get('engineering_limits_not_user_quoted_numbers',{})
    if (scope.get('baseline')!=BASELINE_NAME or scope.get('semantic_review_authorized') is not True
        or limits!={'rounds':2,'video_submissions':8,'image_submissions':0,'cloud_media':0}
        or scope.get('unknown_replay') is not False or scope.get('publication') is not False):raise BaselineError('explicit_two_round_review_scope_required')
    auth=dict(schema='h3_baseline_two_rounds_authorization/v38',user_statement=scope['user_statement'],user_scope=bind(ROOT/'ROOT_USER_SCOPE.json'),
        baseline_audit=bind(BASELINE/'INPUT_AUDIT.json'),baseline_source_plan=bind(ORIGIN),engineering_scope_not_user_quoted_numeric_limit=True,
        engineering_limits=dict(video_submissions_per_round=4,video_submissions_total=8,image_submissions=0,cloud_media=0),
        publication=False,unknown_native_replay=False,review_between_rounds=True)
    freeze(ROOT/'USER_AUTHORIZATION.json',auth);cfg=deepcopy(read(ORIGIN)['config']);cfg['runs_root']=str(ROOT/'video')
    freeze(ROOT/'H3_CONFIG.json',cfg)
    return auth

def _authority():
    value=read(ROOT/'USER_AUTHORIZATION.json')
    if (value.get('schema')!='h3_baseline_two_rounds_authorization/v38' or not value.get('user_statement')
        or value.get('engineering_scope_not_user_quoted_numeric_limit') is not True or value.get('review_between_rounds') is not True
        or value.get('publication') is not False or value.get('unknown_native_replay') is not False
        or value.get('engineering_limits')!={'video_submissions_per_round':4,'video_submissions_total':8,'image_submissions':0,'cloud_media':0}
        or value.get('baseline_audit')!=bind(BASELINE/'INPUT_AUDIT.json') or value.get('baseline_source_plan')!=bind(ORIGIN)):
        raise BaselineError('two_round_baseline_authority_changed')
    scope=read(check(value['user_scope']))
    if value['user_statement']!=scope['user_statement'] or scope.get('semantic_review_authorized') is not True:raise BaselineError('exact_user_statement_and_review_scope_required')
    return value

def _config():
    cfg=read(ROOT/'H3_CONFIG.json');original=read(ORIGIN)['config']
    keys=('service_url','input_root','output_root','gpu_lock_root','protected_pause_path','timeout','video_enabled','width','height')
    if any(cfg.get(k)!=original.get(k) for k in keys):raise BaselineError('baseline_service_or_native_config_changed')
    checked=jobs.Config(**{k:cfg[k] for k in ('service_url','input_root','output_root','timeout')}).normalized()
    if checked['service_url']!=LOCAL_SERVICE or Path(cfg['gpu_lock_root']).resolve()!=Path(SHARED_GPU).resolve() or cfg['video_enabled'] is not True:
        raise BaselineError('existing_local_native_service_and_shared_lock_required')
    return cfg

def _r1_review():
    run=ROOT/'R1';p=read(run/'PLAN.json');value=read(run/'ROOT_OVERALL_VIDEO_REVIEW.json');final=read(run/'FINAL_RESULT.json')
    if (value.get('schema')!='h3_baseline_overall_review/v38' or value.get('review_completed_by')!='root_agent'
        or value.get('overall_video_review_completed') is not True or value.get('allow_prepare_r2') is not True
        or value.get('final_result')!=bind(run/'FINAL_RESULT.json') or value.get('reviewed_video')!=final.get('file')):
        raise BaselineError('actual_completed_R1_overall_review_required_before_R2')
    check(final['file'])
    if status(run)['technical_saved']!=4 or final.get('native_ids')!=[read(_folder(run,sid)/'RESULT.json')['prompt_id'] for sid in IDS]:raise BaselineError('four_saved_R1_segments_required_before_R2')
    inputs=dict(plan=bind(run/'PLAN.json'),native_results=[bind(_folder(run,sid)/'RESULT.json') for sid in IDS])
    if (final.get('schema')!=SCHEMA or final.get('round')!='R1' or final.get('native_results')!=inputs['native_results']
        or final.get('assembly_inputs_sha256')!=digest(inputs) or final.get('clock',{}).get('native_frames')!=4*FRAMES):
        raise BaselineError('complete_R1_native_clock_and_original_results_required')
    return bind(run/'ROOT_OVERALL_VIDEO_REVIEW.json')

def build_graph(template,text,scope):
    graph=deepcopy(template);graph['condition']['inputs']['prompt']=text;graph['ref_scene']['inputs']['image']=scope+'/first_input.png'
    for role in ROLES:graph['save_'+role]['inputs']['filename_prefix']=scope+'/'+role
    native._validate_graph(graph,scope,scope+'/first_input.png')
    return graph

def prepare(run):
    run=_scope(run)
    if not (ROOT/'USER_AUTHORIZATION.json').exists():bootstrap()
    _authority();cfg=_config();baseline=_baseline();review=None;round_spec=None
    if run.name=='R2':
        review=_r1_review();round_spec=bind(run/'ROUND_SPEC.json');choices=read(check(round_spec))
        if choices.get('schema')!='h3_baseline_round_spec/v38' or choices.get('round')!='R2' or choices.get('r1_overall_review')!=review or [r.get('id') for r in choices.get('segments',[])]!=list(IDS):
            raise BaselineError('explicit_review_bound_R2_prompt_and_first_choices_required')
    run.mkdir(parents=True,exist_ok=True)
    rows=[];reading=[]
    for index,b in enumerate(baseline):
        sid=b['id'];folder=_folder(run,sid);folder.mkdir(parents=True,exist_ok=True)
        source=run/'source'/(sid+'.actual.baseline.txt');_bytes(source,b['actual_text'].encode('utf-8'))
        if run.name=='R1':
            raw,patch=compile_r1(b['actual_text'],sid);first=b['baseline_first'];prompt=run/'prompts'/(sid+'.txt');_bytes(prompt,raw);patch.update(snapshot_newline_transport=b['snapshot_newline_transport'])
        else:
            choice=choices['segments'][index];first=choice['first'];_image(first);raw=check(choice['prompt']).read_bytes();prompt=run/'prompts'/(sid+'.txt');_bytes(prompt,raw)
            if quotes(raw.decode('utf-8'))!=quotes(b['actual_text']):raise BaselineError('R2_original_quotes_changed')
            patch=dict(schema='explicit_reviewed_round_patch/v38',choice=choice,r1_overall_review=review,original_quotes=quotes(b['actual_text']))
        patch_path=run/'prompts'/(sid+'.byte_diff.json');freeze(patch_path,patch)
        _image(first);local=folder/'first_input.png'
        if not local.exists():jobs._copy_new(check(first),local)
        if bind(local)['sha256']!=first['sha256']:raise BaselineError('selected_first_pixels_changed')
        scope=ROOT.name+'_'+run.name+'/'+sid;graph=build_graph(b['template'],raw.decode('utf-8'),scope)
        row=dict(id=sid,scope=scope,baseline_request=b['baseline_request'],baseline_prompt=bind(source),baseline_prompt_snapshot=b['baseline_prompt_snapshot'],
            baseline_first=b['baseline_first'],first=first,first_frame=bind(local),prompt=bind(prompt),source_prompt=bind(prompt),byte_diff=bind(patch_path),
            baseline_seed=b['baseline_seed'],seed=graph['129']['inputs']['noise_seed'],timing=native._timing(dict(start=0,end=SECONDS)),
            graph_sha256=digest(graph),input_name=scope+'/first_input.png',graph_namespace_changes_only_except_explicit_prompt=True)
        if row['seed']!=b['baseline_seed'] or row['timing']['native_frames']!=FRAMES:raise BaselineError('baseline_seed_or_clock_changed')
        freeze(folder/'workflow_api.json',graph);freeze(folder/'GRAPH_BINDING.json',row);rows.append(row);reading += ['\n## '+sid+'\n\n'+raw.decode('utf-8')+'\n']
    p=dict(schema=SCHEMA,round=run.name,authorization=bind(ROOT/'USER_AUTHORIZATION.json'),config=cfg,config_file=bind(ROOT/'H3_CONFIG.json'),
        baseline_audit=bind(BASELINE/'INPUT_AUDIT.json'),baseline_source_plan=bind(ORIGIN),protected_pause=bind(cfg['protected_pause_path']),
        profile=dict(width=WIDTH,height=HEIGHT,frames=FRAMES,fps=FPS,steps=12,native_audio=True),segments=rows,round_spec=round_spec,r1_overall_review=review,
        image_generation_calls=0,production_approved=False,publication=False,semantic_review='root_overall_after_finished_round')
    freeze(run/'PLAN.json',p);_bytes(run/'PROMPTS_READING.md',''.join(reading).encode('utf-8'))
    for row in rows:
        folder=_folder(run,row['id'])
        if not (folder/'STATE.json').exists():native.write(folder/'STATE.json',dict(id=row['id'],status='prepared',prompt_id=None,plan_sha256=digest(p)))
    return status(run)

def _load(run,current=False):
    run=_scope(run);p=read(run/'PLAN.json')
    if (p.get('schema')!=SCHEMA or p.get('round')!=run.name or p.get('image_generation_calls')!=0 or p.get('publication') is not False
        or [r.get('id') for r in p.get('segments',[])]!=list(IDS)):raise BaselineError('frozen_baseline_round_plan_changed')
    if current:
        _authority();check(p['authorization']);check(p['config_file']);check(p['baseline_source_plan']);check(p['baseline_audit']);check(p['protected_pause'])
        if _config()!=p['config']:raise BaselineError('frozen_native_config_changed')
        baseline=_baseline()
        if run.name=='R2' and (_r1_review()!=p['r1_overall_review'] or check(p['round_spec'])!=run/'ROUND_SPEC.json'):raise BaselineError('R2_overall_review_or_spec_changed')
        for row,b in zip(p['segments'],baseline):
            check(row['prompt']);_image(row['first']);_image(row['first_frame']);check(row['byte_diff'])
            if row['baseline_request']!=b['baseline_request'] or row['baseline_seed']!=b['baseline_seed'] or row['seed']!=b['baseline_seed']:
                raise BaselineError('frozen_actual_baseline_identity_changed')
            text=check(row['prompt']).read_bytes().decode('utf-8');graph=build_graph(b['template'],text,row['scope'])
            if graph!=read(_folder(run,row['id'])/'workflow_api.json') or digest(graph)!=row['graph_sha256']:raise BaselineError('graph_changed_outside_explicit_baseline_delta')
            if run.name=='R1':
                expected,audit=compile_r1(b['actual_text'],row['id'])
                if expected!=text.encode('utf-8') or row['first']!=b['baseline_first'] or undo_patch(expected,read(check(row['byte_diff'])))!=b['actual_text'].encode('utf-8'):
                    raise BaselineError('R1_exceeded_two_insertions_or_changed_first')
    return run,p

def _state(run,p,row):
    if read(_folder(run,row['id'])/'GRAPH_BINDING.json')!=row:raise BaselineError('original_graph_binding_changed')
    state=native._shot_state(_folder(run,row['id']),p,row)
    if state['status']=='technical_saved':
        entry=read(_folder(run,row['id'])/'HISTORY.json').get(state['prompt_id'],{});prompt=entry.get('prompt',[])
        if len(prompt)<3 or prompt[1]!=state['prompt_id'] or entry.get('status',{}).get('completed') is not True or native.native_graph_equivalence(read(_folder(run,row['id'])/'workflow_api.json'),prompt[2]) is None:raise BaselineError('saved_original_history_changed')
    return state

def status(run):
    run,p=_load(run);states=[_state(run,p,r) for r in p['segments']];ids=[s['prompt_id'] for s in states if s.get('prompt_id')]
    if len(ids)!=len(set(ids)):raise BaselineError('native_id_reused_between_segments')
    return dict(schema=SCHEMA,round=run.name,run=str(run),shots=states,technical_saved=sum(s['status']=='technical_saved' for s in states),
        paused=(run/'PAUSE.json').exists(),content_status='root_overall_review_pending',production_approved=False,publication=False)

def _sources():
    return dict(executor=bind(__file__),cli=bind(PROJECT/'scripts/run_h3_baseline_two_rounds_v38.py'),native=bind(native.__file__),
        image_jobs=bind(jobs.__file__),clock=bind(clock.__file__),native_clock=bind(Path(__file__).with_name('visual_spatial_clock_v30.py')))

def _launch(run,p):
    v=read(run/'LAUNCH_APPROVAL.json')
    if (v.get('schema')!='h3_baseline_round_technical_launch/v38' or v.get('plan')!=bind(run/'PLAN.json') or v.get('authorization')!=p['authorization']
        or v.get('execution_sources')!=_sources() or v.get('approved_for_technical_execution') is not True):raise BaselineError('round_technical_launch_required')
    if not check(v['cpu_acceptance']).is_relative_to(PROJECT/'data/qa'):raise BaselineError('project_CPU_acceptance_required')

def _budget(run):
    own=list((run/'shots').glob('*/CLAIM.json'));total=[f for n in ('R1','R2') for f in (ROOT/n/'shots').glob('*/CLAIM.json')]
    if len(own)>=4 or len(total)>=8:raise BaselineError('two_round_native_video_budget_exhausted')
    if any(f.parent.name not in IDS for f in total):raise BaselineError('foreign_video_claim_in_round_scope')

def _append(run,sid,pid,event):
    ledger=run/'job_ids.txt';line=sid+' '+pid;old=ledger.read_text(encoding='utf-8').splitlines() if ledger.exists() else []
    if any(x!=line and (x.split()[0]==sid or x.split()[-1]==pid) for x in old):raise BaselineError('native_ledger_conflict')
    if line not in old:
        with ledger.open('a',encoding='utf-8') as stream:stream.write(line+'\n');stream.flush()
    with (run/'LOG.md').open('a',encoding='utf-8') as stream:stream.write(f'{time.time()} {event} {line}\n')

def submit_next(run):
    run,p=_load(run)
    with jobs.run_lock(run,'DISPATCH.lock'):
        cur=status(run)
        if cur['paused'] or any(s['status'] in BAD for s in cur['shots']):return cur
        index=next((i for i,s in enumerate(cur['shots']) if s['status']!='technical_saved'),None)
        if index is None or cur['shots'][index]['status']!='prepared':return cur
        _load(run,current=True);_launch(run,p)
        with native._gpu(p):
            _load(run,current=True);_launch(run,p);_budget(run)
            if (run/'PAUSE.json').exists():return cur
            native._service_paths(p['config']);q=native._queue(p['config'])
            if q['queue_running'] or q['queue_pending']:return dict(cur,dispatch='waiting_native_queue')
            row=p['segments'][index];sid=row['id'];folder=_folder(run,sid);graph=read(folder/'workflow_api.json')
            jobs.stage_input({k:p['config'][k] for k in ('service_url','input_root','output_root','timeout')},check(row['first_frame']),row['input_name'],row['first_frame']['sha256'])
            request=read(folder/'REQUEST.json') if (folder/'REQUEST.json').exists() else dict(prompt=graph,client_id=uuid.uuid4().hex)
            if digest(request.get('prompt'))!=row['graph_sha256']:raise BaselineError('frozen_prepost_request_changed')
            freeze(folder/'REQUEST.json',request);freeze(folder/'CLAIM.json',dict(at=time.time(),graph_sha256=row['graph_sha256'],first_frame_sha256=row['first_frame']['sha256'],request=bind(folder/'REQUEST.json')))
            state=cur['shots'][index]
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

def collect_known(run):
    run,p=_load(run);errors=[]
    with jobs.run_lock(run,'COLLECT.lock'):
        for row in p['segments']:
            state=_state(run,p,row)
            if not state.get('prompt_id') or state['status'] in ('technical_saved','failed','interrupted','rejected'):continue
            folder=_folder(run,row['id']);pid=state['prompt_id']
            try:
                history=native._http(p['config'],'/history/'+native.slug(pid))
                if not isinstance(history,dict):raise BaselineError('native_history_response_required')
                entry=history.get(pid)
                if entry:
                    prompt=entry.get('prompt',[]);terminal=entry.get('status',{})
                    if (len(prompt)<3 or prompt[1]!=pid or not native._verify_native_graph(folder,row,prompt[2],pid)
                        or type(terminal.get('completed')) is not bool or terminal.get('status_str') not in ('success','error')):raise BaselineError('original_native_history_changed')
                    native.write(folder/'HISTORY.latest.json',history)
                    if terminal['status_str']=='error':
                        events=[x[0] for x in terminal.get('messages',[]) if isinstance(x,list) and x];state.update(status='interrupted' if 'execution_interrupted' in events else 'failed')
                    elif terminal['completed']:
                        freeze(folder/'HISTORY.json',history);native._collect(folder,p,row,state,entry);_append(run,row['id'],pid,'SAVED')
                    else:state['status']='running'
                else:
                    q=native._queue(p['config']);matches=[r for r in q['queue_running']+q['queue_pending'] if len(r)>2 and r[1]==pid]
                    if any(not native._verify_native_graph(folder,row,r[2],pid) for r in matches):raise BaselineError('original_native_queue_graph_changed')
                    state['status']='running' if matches else 'outcome_unknown'
                native.write(folder/'STATE.json',state)
            except OSError as error:errors.append(dict(id=row['id'],native_id=pid,type=type(error).__name__,message=str(error)))
    value=status(run)
    if errors:native.write(run/'COLLECTION_ERRORS.json',dict(errors=errors,new_dispatch_blocked=True));value['collection_errors']=errors
    return value

def assemble(run):
    run,p=_load(run)
    with jobs.run_lock(run,'ASSEMBLY.lock'):
        if status(run)['technical_saved']!=4:raise BaselineError('four_saved_original_videos_required')
        results=[read(_folder(run,sid)/'RESULT.json') for sid in IDS];ids=[r['prompt_id'] for r in results];videos=[r['files']['video'] for r in results]
        if len(set(ids))!=4 or len({v['sha256'] for v in videos})!=4:raise BaselineError('four_distinct_native_videos_required')
        inputs=dict(plan=bind(run/'PLAN.json'),native_results=[bind(_folder(run,sid)/'RESULT.json') for sid in IDS]);source=digest(inputs)
        final=run/'FINAL_RESULT.json';output=run/('BASELINE_'+run.name+'_736x1312.mp4')
        if final.exists():
            v=read(final);check(v['file'])
            if v['assembly_inputs_sha256']!=source:raise BaselineError('frozen_assembly_sources_changed')
            return v
        if output.exists():raise BaselineError('unreceipted_final_movie_preserved')
        adjustments=[clock_input(v['path'],v['sha256'],frames=FRAMES,width=WIDTH,height=HEIGHT) for v in videos]
        filters=run/'ASSEMBLY_FILTER.txt';cmd,text=clock.assembly_command([v['path'] for v in videos],filters,output,frames=FRAMES);_bytes(filters,text.encode('utf-8'))
        freeze(run/'ASSEMBLY_REQUEST.json',dict(inputs=inputs,adjustments=adjustments,command=cmd));process=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=1800)
        _bytes(run/'ASSEMBLY.stderr.log',process.stderr.encode('utf-8'));process.check_returncode();timing=clock.verify_clock(clock._probe(output,count=True),frames=4*FRAMES,width=WIDTH,height=HEIGHT)
        if inputs['native_results']!=[bind(_folder(run,sid)/'RESULT.json') for sid in IDS]:raise BaselineError('native_results_changed_during_assembly')
        v=dict(schema=SCHEMA,round=run.name,file=bind(output),native_ids=ids,native_results=inputs['native_results'],clock=timing,assembly_inputs_sha256=source,
            content_status='root_overall_review_pending',production_approved=False,publication=False)
        freeze(final,v);return v

def tick(run,*,allow_submit=False):
    if type(allow_submit) is not bool:raise BaselineError('explicit_submit_boolean_required')
    run,p=_load(run)
    with jobs.run_lock(run,'STEP.lock'):
        cur=collect_known(run)
        if cur['technical_saved']==4:return assemble(run)
        if cur.get('collection_errors'):return dict(cur,dispatch='collection_error_no_new_post')
        if cur['paused']:return dict(cur,dispatch='paused')
        if any(s['status'] in BAD for s in cur['shots']):return dict(cur,dispatch='unknown_or_failed_native_preserved')
        try:
            _load(run,current=True)
            if allow_submit:_launch(run,p)
        except (OSError,ValueError,KeyError) as error:
            out=dict(cur,dispatch='blocked_current_inputs',error=dict(type=type(error).__name__,message=str(error)));native.write(run/'INPUT_INVALID.json',out);return out
        return submit_next(run) if allow_submit else cur

def execute(run,*,poll_seconds=30,max_seconds=86400):
    if not 1<=poll_seconds<=60 or not 0<max_seconds<=86400:raise BaselineError('bounded_execution_required')
    run,_=_load(run)
    with jobs.run_lock(run,'RUNNER.lock'):
        start=time.monotonic()
        while True:
            result=tick(run,allow_submit=True)
            if 'file' in result or result.get('dispatch') in ('blocked_current_inputs','unknown_or_failed_native_preserved'):return result
            if time.monotonic()-start>=max_seconds:return dict(result,dispatch='bounded_wait_original_ids_preserved')
            time.sleep(poll_seconds)
