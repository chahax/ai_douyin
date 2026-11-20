"""Independent, source-bound FL2VA/I2V recipe restoration diagnostic.

No five-reference or AddGuide hybrid. Preparation is CPU/filesystem only;
only explicit approved execution may contact the existing local service.
"""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import re
import subprocess
import time
import urllib.error
import uuid
from PIL import Image
from . import visual_h3_handoff_v3 as native
from . import visual_image_jobs_v3 as jobs
from . import visual_spatial_delivery_v24 as spatial
from . import visual_h3_prompt_parity_v19 as clock
from .visual_spatial_clock_v30 import clock_input

PROJECT=Path(__file__).resolve().parents[2]
RUN=PROJECT/'data/video_generation/h3_legacy_call_restore_20261108_v1'
RAW=PROJECT/'data/video_generation/h3_seedance_prompt_parity_60s_20261107_v1'
A_SPEC=PROJECT/'data/video_generation/spatial_minute_experiments_20261107_v1/A_SPEC.json'
CALL_AUDIT=PROJECT/'data/qa/h3_actual_call_comparison_20261108/ACTUAL_CALL_DIFF.json'
CPU_ACCEPTANCE=PROJECT/'data/qa/h3_legacy_call_restore_v32_20261108/ACCEPTANCE.json'
SCHEMA='h3_legacy_call_restore/v32'
AUTH_SCHEMA='h3_legacy_call_restore_authorization/v32'
APPROVAL_SCHEMA='h3_legacy_call_restore_launch_approval/v32'
IDS=('S01','S02','S03','S04')
ROLES=('video','audio','first','last')
BAD={'outcome_unknown','failed','interrupted','rejected'}
MODEL='minimax_h3_fl2va_pruned_int8_convrot.safetensors'
REPLACEMENTS=(
 ('场景是苏墨的房间，人物外观、服装与场景环境采用本段具名参考图。','场景是苏墨的房间，人物外观、服装与场景环境承接本段首图。',True),
 ('人物与参考图逐一对应：','首图中的人物与服装：',True),
 ('苏墨是<Picture 1>中的成年父亲','苏墨是首图中的成年父亲',True),
 ('叶南是<Picture 2>中的哥哥','叶南是首图中的哥哥',True),
 ('叶西决是<Picture 3>中的弟弟','叶西决是首图中的弟弟',True),
 ('人物造型与房间环境以具名参考图为准。','人物造型与房间环境以本段首图为准。',False),
)


class RestoreError(ValueError):pass


def sha(data):return hashlib.sha256(data).hexdigest()
def binding(path):
    path=Path(path).resolve();return dict(path=str(path),sha256=native.file_sha(path))
def check(value):
    if not isinstance(value,dict) or set(value)!={'path','sha256'} or binding(value['path'])!=value:raise RestoreError('bound_file_changed')
    return Path(value['path'])
def _scope(run):
    run=Path(run).resolve()
    if run!=RUN.resolve():raise RestoreError('only_new_legacy_restore_root_allowed')
    return run
def _text(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);data=value.encode('utf-8')
    if path.exists():
        if path.read_bytes()!=data:raise RestoreError('frozen_text_changed_use_new_revision')
    else:
        with path.open('xb') as stream:stream.write(data)
def _image(value):
    path=check(value)
    with Image.open(path) as image:
        if getattr(image,'n_frames',1)!=1:raise RestoreError('one_static_first_image_required')
        size=image.size;image.verify()
    return size


def compile_prompt(source,expected_sha256):
    """Only exact reference-wording edits; original offsets permit reverse replay."""
    if sha(source.encode('utf-8'))!=expected_sha256:raise RestoreError('a_prompt_source_changed')
    edits=[]
    for old,new,required in REPLACEMENTS:
        count=source.count(old)
        if (required and count!=1) or count>1:raise RestoreError('explicit_reference_wording_anchor_changed')
        if not count:continue
        start=source.index(old);edits.append(dict(char_start=start,char_end=start+len(old),utf8_byte_start=len(source[:start].encode('utf-8')),old=old,new=new))
    edits.sort(key=lambda x:x['char_start']);out=source
    for row in reversed(edits):out=out[:row['char_start']]+row['new']+out[row['char_end']:]
    if re.search(r'<Picture\s|具名参考|参考图',out):raise RestoreError('phantom_reference_input_wording_remains')
    if spatial.quotes(out)!=spatial.quotes(source):raise RestoreError('original_quotes_changed')
    if '画面以纯剧情影像呈现，叙事信息通过表演和声音传达。' not in out:raise RestoreError('plain_story_visual_contract_missing')
    offset=0
    for row in edits:
        row['compiled_start']=row['char_start']+offset;offset+=len(row['new'])-len(row['old'])
    audit=dict(schema='first_image_prompt_adaptation/v32',source_utf8_sha256=expected_sha256,compiled_utf8_sha256=sha(out.encode('utf-8')),edits=edits,original_quotes=spatial.quotes(source),only_declared_reference_wording_changed=True,actions_and_timeline_not_rewritten=True,model_calls=0)
    if restore_prompt(out,audit)!=source:raise RestoreError('adaptation_reverse_replay_failed')
    return out,audit


def restore_prompt(text,audit):
    if sha(text.encode('utf-8'))!=audit['compiled_utf8_sha256']:raise RestoreError('compiled_prompt_changed')
    for row in reversed(audit['edits']):
        start=row['compiled_start'];end=start+len(row['new'])
        if text[start:end]!=row['new']:raise RestoreError('adaptation_offset_changed')
        text=text[:start]+row['old']+text[end:]
    if sha(text.encode('utf-8'))!=audit['source_utf8_sha256']:raise RestoreError('source_reverse_sha_changed')
    return text


def _authorization(run):
    path=run/'USER_AUTHORIZATION.json';auth=native.read(path)
    if (auth.get('schema')!=AUTH_SCHEMA or not isinstance(auth.get('user_statement'),str) or not auth['user_statement'].strip()
            or auth.get('engineering_scope_not_user_quoted_numeric_limit') is not True
            or type(auth.get('max_full_video_submissions')) is not int or auth['max_full_video_submissions']!=4
            or type(auth.get('max_probe_video_submissions')) is not int or auth['max_probe_video_submissions']!=0
            or type(auth.get('new_cloud_media_calls')) is not int or auth['new_cloud_media_calls']!=0
            or any(auth.get(k) is not False for k in ('publication','service_restarts','downloads','unknown_native_replay','old_paused_batches_resumed'))):
        raise RestoreError('explicit_new_four_video_zero_probe_authorization_required')
    for key,path in (('baseline_a_spec',A_SPEC),('legacy_raw_plan',RAW/'PLAN.json'),('call_difference_audit',CALL_AUDIT)):
        if auth.get(key)!=binding(path):raise RestoreError('fixed_a_raw_and_call_audit_bindings_required')
    return auth


def _template(index):
    folder=RAW/'segments'/IDS[index];graph=native.read(folder/'workflow_api.json');request=native.read(folder/'REQUEST.json');result=native.read(folder/'RESULT.json');history=native.read(folder/'HISTORY.json')
    pid=result.get('prompt_id');entry=history.get(pid,{});observed=entry.get('prompt',[]);terminal=entry.get('status',{})
    if (request.get('prompt')!=graph or len(observed)<3 or observed[1]!=pid
            or terminal.get('completed') is not True or terminal.get('status_str')!='success'
            or native.native_graph_equivalence(graph,observed[2]) is None):raise RestoreError('completed_actual_legacy_graph_history_required')
    ci=graph['condition']['inputs']
    if (graph['condition']['class_type']!='MiniMaxH3ImageToVideo' or ci.get('first_frame')!=['ref_scene',0]
            or any(k=='last_frame' or k.startswith('ref_') for k in ci)
            or graph['127']['inputs']['unet_name']!=MODEL or graph['129']['inputs']['noise_seed']!=2026110700+index
            or (ci['width'],ci['height'],ci['length'])!=(736,1312,362)
            or graph['124']['inputs']['steps']!=12 or graph['130']['inputs']['fps']!=24
            or any(v['class_type'] in ('MiniMaxH3AddGuide','MiniMaxH3ReferenceToVideo') for v in graph.values())):
        raise RestoreError('actual_legacy_first_only_profile_required')
    return graph,dict(request=binding(folder/'REQUEST.json'),workflow=binding(folder/'workflow_api.json'),history=binding(folder/'HISTORY.json'),result=binding(folder/'RESULT.json'),original_native_id=pid)


def build_graph(template,prompt,scope):
    graph=deepcopy(template);graph['condition']['inputs']['prompt']=prompt
    graph['ref_scene']['inputs']['image']=scope+'/first_input.png'
    for role in ROLES:graph['save_'+role]['inputs']['filename_prefix']=scope+'/'+role
    return graph


def prepare(run=RUN):
    run=_scope(run);auth=_authorization(run);a=native.read(check(auth['baseline_a_spec']));legacy=native.read(check(auth['legacy_raw_plan']))
    if a.get('variant')!='A' or [s['id'] for s in a['segments']]!=list(IDS):raise RestoreError('a_four_source_segments_required')
    guide=deepcopy(a['initial_guide']);spatial._guide(guide);spatial._references(a['references'])
    cfg=deepcopy(legacy['config'])
    if (cfg.get('service_url')!='http://127.0.0.1:8190'
            or any(cfg.get(k)!=a['config'].get(k) for k in ('service_url','input_root','output_root','gpu_lock_root','timeout'))):raise RestoreError('existing_local_service_config_changed')
    rows=[];reading=['# FL2VA/I2V first-only candidate — root review required\n\nTask-specific prompt contract plus a previously executed sampling recipe; not proof that Guide caused the defect. A canonical initial image is retained, so this is not an exact reproduction of the old Seedance-input video. No direct five-reference slots or AddGuide nodes.\n']
    for i,source in enumerate(a['segments']):
        raw=check(source['prompt']).read_bytes().decode('utf-8');text,audit=compile_prompt(raw,source['prompt']['sha256']);template,evidence=_template(i)
        folder=run/'prompts';folder.mkdir(parents=True,exist_ok=True);p=folder/(IDS[i]+'.txt');_text(p,text);ap=folder/(IDS[i]+'.audit.json');native.freeze(ap,dict(audit,source_prompt=source['prompt']))
        rows.append(dict(id=IDS[i],original_prompt=source['prompt'],prompt=binding(p),adaptation_audit=binding(ap),template=template,legacy_actual_call=evidence))
        reading.append('\n## '+IDS[i]+'\n\n```text\n'+text+'\n```\n')
    if sum(len(spatial.quotes(check(s['prompt']).read_bytes().decode('utf-8'))) for s in rows)!=10:raise RestoreError('ten_original_quotes_required')
    plan=dict(schema=SCHEMA,authorization=binding(run/'USER_AUTHORIZATION.json'),baseline_a_spec=auth['baseline_a_spec'],legacy_raw_plan=auth['legacy_raw_plan'],call_difference_audit=auth['call_difference_audit'],config=cfg,protected_pause=legacy['protected_pause'],settings=dict(width=736,height=1312,frames=362,fps=24,segments=rows,initial_guide=guide),task_mode='fl2va_i2v_first_only',direct_reference_slots=0,upstream_asset_references=a['references'],semantic_retakes=0,production_approved=False,publication=False,diagnostic_preview=True)
    with jobs.run_lock(run):
        native.freeze(run/'PLAN.json',plan);_text(run/'PROMPTS_READING.md',''.join(reading))
        for sid in IDS:
            folder=run/'shots'/sid;folder.mkdir(parents=True,exist_ok=True)
            if not (folder/'STATE.json').exists():native.write(folder/'STATE.json',dict(id=sid,status='prepared',prompt_id=None,plan_sha256=native.fingerprint(plan)))
    return status(run)


def _load(run,current=False):
    run=_scope(run);plan=native.read(run/'PLAN.json')
    if (plan.get('schema')!=SCHEMA or plan.get('task_mode')!='fl2va_i2v_first_only' or plan.get('direct_reference_slots')!=0
            or plan.get('publication') is not False or plan.get('production_approved') is not False):raise RestoreError('new_i2v_diagnostic_plan_required')
    if current:
        check(plan['authorization']);auth=_authorization(run)
        if any(plan[k]!=auth[k] for k in ('baseline_a_spec','legacy_raw_plan','call_difference_audit')):raise RestoreError('plan_authority_changed')
        a=native.read(check(auth['baseline_a_spec']));legacy=native.read(check(auth['legacy_raw_plan']));settings=plan['settings']
        if (native.fingerprint(plan['config'])!=native.fingerprint(legacy['config'])
                or plan['config'].get('service_url')!='http://127.0.0.1:8190'
                or plan['protected_pause']!=legacy['protected_pause']
                or settings.get('initial_guide')!=a['initial_guide'] or plan.get('upstream_asset_references')!=a['references']
                or [s.get('id') for s in settings.get('segments',[])]!=list(IDS)
                or native.fingerprint({k:settings.get(k) for k in ('width','height','frames','fps')})!=native.fingerprint(dict(width=736,height=1312,frames=362,fps=24))):
            raise RestoreError('bound_local_config_canonical_assets_or_profile_changed')
        for i,row in enumerate(plan['settings']['segments']):
            source=check(row['original_prompt']).read_bytes().decode('utf-8');text,audit=compile_prompt(source,row['original_prompt']['sha256']);template,evidence=_template(i)
            if (row['original_prompt']!=a['segments'][i]['prompt'] or row['id']!=IDS[i] or row['template']!=template or row['legacy_actual_call']!=evidence
                    or check(row['prompt']).read_bytes()!=text.encode('utf-8')
                    or native.read(check(row['adaptation_audit']))!=dict(audit,source_prompt=row['original_prompt'])):raise RestoreError('frozen_task_or_template_changed')
        if native.file_sha(plan['protected_pause']['path'])!=plan['protected_pause']['sha256']:raise RestoreError('old_pause_changed')
    return run,plan


def status(run=RUN):
    run,plan=_load(run);states=[_state(run,plan,sid) for sid in IDS];ids=[s['prompt_id'] for s in states if s.get('prompt_id')]
    if len(ids)!=len(set(ids)):raise RestoreError('distinct_native_ids_required')
    return dict(schema=SCHEMA,run=str(run),shots=states,total=4,technical_saved=sum(s['status']=='technical_saved' for s in states),paused=(run/'PAUSE.json').exists(),task_mode=plan['task_mode'],direct_reference_slots=0,production_approved=False,publication=False)


def _state(run,plan,sid):
    folder=run/'shots'/sid
    if (folder/'CLAIM.json').exists():
        claim=native.read(folder/'CLAIM.json')
        if claim.get('request')!=binding(folder/'REQUEST.json'):raise RestoreError('original_claim_request_changed')
    return spatial._state(run,plan,sid)


def _approval(run,plan):
    value=native.read(run/'LAUNCH_APPROVAL.json');auth=native.read(check(plan['authorization']))
    basis=value.get('selection_basis')
    if (value.get('schema')!=APPROVAL_SCHEMA or value.get('reviewed_by')!='root_agent'
            or value.get('approved_for_generation') is not True or value.get('diagnostic_only') is not True
            or value.get('plan')!=binding(run/'PLAN.json') or value.get('authorization')!=plan['authorization']
            or value.get('baseline_selection_by')!='root_agent' or not isinstance(basis,list) or len(basis)<2
            or auth['call_difference_audit'] not in basis or auth.get('selection_evidence') not in basis
            or len({json.dumps(x,sort_keys=True) for x in basis})!=len(basis)):
        raise RestoreError('explicit_root_plan_selection_approval_required')
    for item in basis:check(item)
    sources=value.get('execution_sources')
    expected=dict(executor=binding(Path(__file__).resolve()),cli=binding(PROJECT/'scripts/run_h3_legacy_call_restore_v32.py'))
    acceptance=value.get('cpu_acceptance')
    if (sources!=expected or not isinstance(acceptance,dict)
            or acceptance.get('path')!=str(CPU_ACCEPTANCE.resolve())):
        raise RestoreError('exact_execution_source_and_cpu_acceptance_bindings_required')
    check(acceptance)
    return value


def _remember(run,sid,pid,event):
    ledger=run/'job_ids.txt';line=sid+' '+pid
    lines=ledger.read_text(encoding='utf-8').splitlines() if ledger.exists() else []
    if any((x.split()[0]==sid and x!=line) or (len(x.split())==2 and x.split()[1]==pid and x.split()[0]!=sid) for x in lines):
        raise RestoreError('native_id_ledger_conflict')
    if line not in lines:
        with ledger.open('a',encoding='utf-8') as stream:stream.write(line+'\n');stream.flush()
    with (run/'LOG.md').open('a',encoding='utf-8') as stream:stream.write(f'{time.time():.3f} {event} {sid} {pid}\n')


def _budget(run):
    claims=list(run.glob('shots/*/CLAIM.json'))
    if any(p.parent.name not in IDS for p in claims):raise RestoreError('unexpected_claim_scope')
    if len(claims)>=4:raise RestoreError('four_native_submission_budget_exhausted')


def submit_next(run=RUN):
    run,plan=_load(run);cfg=plan['config']
    with jobs.run_lock(run):
        current=status(run)
        if current['paused']:return dict(current,dispatch='paused')
        for index,state in enumerate(current['shots']):
            if state['status']=='technical_saved':continue
            if state['status']!='prepared':return current
            break
        else:return current
        _load(run,current=True);_approval(run,plan)
        with native._gpu(plan):
            _load(run,current=True);_approval(run,plan);_budget(run)
            if (run/'PAUSE.json').exists():return dict(current,dispatch='paused')
            native._service_paths(cfg);queue=native._queue(cfg)
            if queue['queue_running'] or queue['queue_pending']:return dict(current,dispatch='waiting_gpu_queue')
            segment=plan['settings']['segments'][index];sid=segment['id'];folder=run/'shots'/sid
            if index:
                previous=run/'shots'/IDS[index-1]/'RESULT.json';result=native.read(previous)
                guide=dict(image={k:result['files']['last'][k] for k in ('path','sha256')},native_result=binding(previous),role='last',native_id=result['prompt_id'],previous_segment=IDS[index-1],policy='actual_previous_native_tail_even_if_semantically_imperfect')
            else:guide=deepcopy(plan['settings']['initial_guide'])
            _image(guide['image']);scope=run.name+'/'+sid
            text=check(segment['prompt']).read_bytes().decode('utf-8');graph=build_graph(segment['template'],text,scope)
            first=folder/'first_input.png'
            if not first.exists():jobs._copy_new(check(guide['image']),first)
            if binding(first)['sha256']!=guide['image']['sha256']:raise RestoreError('first_image_not_original_native_bytes')
            row=dict(id=sid,scope=scope,graph_sha256=native.fingerprint(graph),guide=guide,first_frame=binding(first),input_name=scope+'/first_input.png',source_prompt=segment['prompt'],original_prompt=segment['original_prompt'],task_mode='fl2va_i2v_first_only',direct_reference_slots=0)
            native.freeze(folder/'workflow_api.json',graph);native.freeze(folder/'GRAPH_BINDING.json',row)
            stage_cfg={k:cfg[k] for k in ('service_url','input_root','output_root','timeout')}
            jobs.stage_input(stage_cfg,first,scope+'/first_input.png',guide['image']['sha256'])
            request=native.read(folder/'REQUEST.json') if (folder/'REQUEST.json').exists() else dict(prompt=graph,client_id=uuid.uuid4().hex)
            if native.fingerprint(request.get('prompt'))!=native.fingerprint(graph):raise RestoreError('frozen_prepost_request_changed')
            native.freeze(folder/'REQUEST.json',request);state['graph_sha256']=row['graph_sha256'];native.write(folder/'STATE.json',state)
            native.freeze(folder/'CLAIM.json',dict(at=time.time(),graph_sha256=row['graph_sha256'],request=binding(folder/'REQUEST.json'),native_post_budget=1))
            try:response=native._http(cfg,'/prompt',request)
            except urllib.error.HTTPError as error:
                native.freeze(folder/'POST_ERROR.json',dict(type='HTTPError',code=error.code));state.update(status='rejected' if error.code in (400,422) else 'outcome_unknown')
            except Exception as error:
                native.freeze(folder/'POST_ERROR.json',dict(type=type(error).__name__));state.update(status='outcome_unknown')
            else:
                native.freeze(folder/'RESPONSE.json',response);pid=response.get('prompt_id') if isinstance(response,dict) else None
                if isinstance(pid,str) and re.fullmatch('[A-Za-z0-9_-]{1,100}',pid) and not response.get('node_errors'):
                    state.update(status='submitted',prompt_id=pid,submitted_at=time.time());_remember(run,sid,pid,'SUBMIT')
                else:state.update(status='rejected' if isinstance(response,dict) and response.get('node_errors') else 'outcome_unknown')
            native.write(folder/'STATE.json',state)
    return status(run)


def _collect(folder,plan,row,state,entry):
    files={};cfg=plan['config'];scope=(Path(cfg['output_root'])/row['scope']).resolve()
    for role,key,suffix in [('video','images','.mp4'),('audio','audio','.flac'),('first','images','.png'),('last','images','.png')]:
        values=entry.get('outputs',{}).get('save_'+role,{}).get(key)
        if not isinstance(values,list) or len(values)!=1 or values[0].get('type')!='output':raise RestoreError('four_native_original_outputs_required')
        rec=values[0];name=rec.get('filename','')
        if '/' in name or '\\' in name or not name.startswith(role+'_') or Path(name).suffix.lower()!=suffix:raise RestoreError('native_output_filename_changed')
        source=native.bound(cfg['output_root'],rec.get('subfolder','').replace('\\','/')+'/'+name)
        if source.parent!=scope or not source.is_file() or source.stat().st_size<=0:raise RestoreError('native_output_scope_changed')
        dest=folder/'artifacts'/name;dest.parent.mkdir(exist_ok=True);digest=native.file_sha(source)
        if not dest.exists():jobs._copy_new(source,dest)
        if native.file_sha(dest)!=digest:raise RestoreError('native_output_copy_changed')
        files[role]=dict(path=str(dest),sha256=digest,source_path=str(source))
    metadata=native._metadata(files['video']['path']);video=next((s for s in metadata['streams'] if s.get('codec_type')=='video'),{})
    if ((video.get('width'),video.get('height'),int(video.get('nb_frames',-1)),video.get('r_frame_rate'))!=(736,1312,362,'24/1')
            or not any(s.get('codec_type')=='audio' for s in metadata['streams'])
            or not any(s.get('codec_type')=='audio' for s in native._metadata(files['audio']['path'])['streams'])):raise RestoreError('native_av_geometry_changed')
    if any(_image({k:files[role][k] for k in ('path','sha256')})!=(736,1312) for role in ('first','last')):raise RestoreError('native_endpoint_geometry_changed')
    result=dict(schema=SCHEMA,shot_id=row['id'],prompt_id=state['prompt_id'],graph_sha256=row['graph_sha256'],files=files,native_metadata=metadata,guide=row['guide'],first_frame=row['first_frame'],source_prompt=row['source_prompt'],original_prompt=row['original_prompt'],task_mode='fl2va_i2v_first_only',direct_reference_slots=0,technical_status='technical_saved',content_status='raw_diagnostic_not_semantic_approval',production_approved=False,publication=False)
    native.freeze(folder/'RESULT.json',result);state.update(status='technical_saved',result_sha256=native.file_sha(folder/'RESULT.json'));_remember(folder.parents[1],row['id'],state['prompt_id'],'SAVED')


def poll_collect(run=RUN):
    run,plan=_load(run);cfg=plan['config']
    with jobs.run_lock(run):
        for sid in IDS:
            state=_state(run,plan,sid)
            if state['status'] not in ('submitted','running') or not state.get('prompt_id'):continue
            folder=run/'shots'/sid;row=native.read(folder/'GRAPH_BINDING.json');pid=state['prompt_id'];history=native._http(cfg,'/history/'+native.slug(pid))
            if not isinstance(history,dict):raise RestoreError('native_history_response_required')
            entry=history.get(pid)
            if entry:
                prompt=entry.get('prompt',[]);terminal=entry.get('status',{})
                if (len(prompt)<3 or prompt[1]!=pid or not native._verify_native_graph(folder,row,prompt[2],pid)
                        or type(terminal.get('completed')) is not bool or terminal.get('status_str') not in ('success','error')):raise RestoreError('original_native_history_identity_changed')
                native.write(folder/'HISTORY.latest.json',history)
                if terminal['status_str']=='error':
                    events=[x[0] for x in terminal.get('messages',[]) if isinstance(x,list) and x]
                    state.update(status='interrupted' if 'execution_interrupted' in events else 'failed',native_terminal=terminal)
                elif terminal['completed']:
                    native.freeze(folder/'HISTORY.json',history);_collect(folder,plan,row,state,entry)
                else:state['status']='running'
            else:
                queue=native._queue(cfg);matches=[q for q in queue['queue_running']+queue['queue_pending'] if q[1]==pid]
                if any(not native._verify_native_graph(folder,row,q[2],pid) for q in matches):raise RestoreError('original_native_queue_graph_changed')
                state.update(status='running' if matches else 'outcome_unknown',reason=None if matches else 'original_id_absent_history_queue')
            native.write(folder/'STATE.json',state)
    return status(run)


def assemble(run=RUN):
    run,plan=_load(run,current=True)
    with jobs.run_lock(run,'ASSEMBLY.lock'):
        if status(run)['technical_saved']!=4:raise RestoreError('four_saved_original_segments_required')
        results=[native.read(run/'shots'/sid/'RESULT.json') for sid in IDS];ids=[r['prompt_id'] for r in results];videos=[r['files']['video'] for r in results]
        if len(set(ids))!=4 or len({v['sha256'] for v in videos})!=4:raise RestoreError('four_distinct_native_segments_required')
        inputs=dict(plan=binding(run/'PLAN.json'),results=[binding(run/'shots'/sid/'RESULT.json') for sid in IDS]);digest=native.fingerprint(inputs)
        final=run/'FINAL_RESULT.json';output=run/'LEGACY_CALL_RESTORE_736x1312.mp4'
        if final.exists():
            value=native.read(final);check(value['file'])
            if value['assembly_inputs_sha256']!=digest:raise RestoreError('assembly_sources_changed')
            return value
        if output.exists():raise RestoreError('unreceipted_movie_preserved')
        adjustments=[clock_input(v['path'],v['sha256']) for v in videos];filters=run/'ASSEMBLY_FILTER.txt'
        command,text=clock.assembly_command([v['path'] for v in videos],filters,output,frames=362);_text(filters,text)
        native.freeze(run/'ASSEMBLY_REQUEST.json',dict(inputs=inputs,inputs_sha256=digest,command=command,adjustments=adjustments))
        process=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=1800);_text(run/'ASSEMBLY.stderr.log',process.stderr);process.check_returncode()
        timing=clock.verify_clock(clock._probe(output,count=True),frames=1448,width=736,height=1312)
        if inputs['results']!=[binding(run/'shots'/sid/'RESULT.json') for sid in IDS]:raise RestoreError('assembly_inputs_changed_while_running')
        value=dict(schema=SCHEMA,file=binding(output),native_ids=ids,clock=timing,assembly_inputs_sha256=digest,task_mode='fl2va_i2v_first_only',direct_reference_slots=0,diagnostic_preview=True,production_approved=False,publication=False)
        native.freeze(final,value);return value


def execute(run=RUN,poll_seconds=30,max_seconds=86400):
    if not 1<=poll_seconds<=60 or not 0<max_seconds<=86400:raise RestoreError('bounded_execution_window_required')
    run,plan=_load(run)
    with jobs.run_lock(run,'RUNNER.lock'):
        started=time.monotonic()
        while True:
            current=poll_collect(run);active=any(s['status'] in ('submitted','running') for s in current['shots'])
            if any(s['status'] in BAD for s in current['shots']):return current
            if current['technical_saved']==4:return assemble(run)
            error=None
            try:_load(run,current=True)
            except (OSError,ValueError,KeyError) as exc:error=dict(type=type(exc).__name__,message=str(exc))
            if current['paused'] or error:
                if not active or time.monotonic()-started>=max_seconds:return dict(current,input_error=error)
            else:submit_next(run)
            if time.monotonic()-started>=max_seconds:return dict(status(run),dispatch='bounded_wait_original_ids_preserved')
            time.sleep(poll_seconds)
