"""Explicit local Ref2VA + native time-anchored guides, diagnostic movies only.

This independent namespace never changes old asset/production qualification.
Known jobs are collected through pause/input changes; uncertain POSTs stay unknown.
"""
from copy import deepcopy
from pathlib import Path
from fractions import Fraction
import json
import re
import subprocess
import time
import urllib.error
import uuid

from PIL import Image
from . import visual_h3_handoff_v3 as native
from . import visual_image_jobs_v3 as jobs
from . import visual_h3_prompt_parity_v19 as clock

SCHEMA='spatial_h3_delivery/v24'
SPEC='spatial_h3_spec/v24'
PREFIX='visual_spatial_h3_v24'
PROJECT=Path(__file__).resolve().parents[2]
ROOT=PROJECT/'data/video_generation/spatial_minute_experiments_20261107_v1'
SOURCE=PROJECT/'data/video_generation/h3_reference_full_minute_20261107_v1'
IDS=('S01','S02','S03','S04')
BAD={'outcome_unknown','failed','interrupted','rejected'}
ROLES=('video','audio','first','last')
MODEL='minimax_h3_ref2va_pruned_int8_convrot.safetensors'
ROOM_ONLY_VARIANT='C_room_only_20261108_v1'


class SpatialDeliveryError(ValueError):pass


def binding(path):
    p=Path(path).resolve();return dict(path=str(p),sha256=native.file_sha(p))


def check(value):
    if not isinstance(value,dict) or set(value)!={'path','sha256'} or binding(value['path'])!=value:
        raise SpatialDeliveryError('bound_file_changed')
    return Path(value['path'])


def quotes(text):return re.findall('“[^”]*”|「[^」]*」',text)


def _image(value):
    p=check(value)
    with Image.open(p) as im:
        if getattr(im,'n_frames',1)!=1:raise SpatialDeliveryError('single_image_required')
        size=im.size;im.verify()
    return size


def _scope(run):
    run=Path(run).resolve()
    if run.parent!=ROOT/'variants':raise SpatialDeliveryError('new_v24_variant_scope_required')
    native.slug(run.name);return run


def _guide(value):
    if not isinstance(value,dict):raise SpatialDeliveryError('explicit_guide_provenance_required')
    _image(value['image']);review=native.read(check(value['root_review']))
    if (review.get('reviewed_by')!='root_agent' or review.get('accepted_for_guide') is not True
            or review.get('image')!=value['image']):raise SpatialDeliveryError('root_guide_review_required')
    if value.get('native_result'):
        result=native.read(check(value['native_result']));role=value.get('role')
        if role not in ('first','last') or not result.get('prompt_id') or result.get('technical_status')!='technical_saved':
            raise SpatialDeliveryError('known_native_guide_required')
        if {k:result['files'][role][k] for k in ('path','sha256')}!=value['image']:
            raise SpatialDeliveryError('guide_not_original_native_frame')
    else:
        producer=check(value['producer_receipt'])
        if review.get('producer_receipt')!=value['producer_receipt']:
            raise SpatialDeliveryError('generated_guide_producer_not_reviewed')
    return value


def _references(refs):
    if not isinstance(refs,list) or len(refs)!=5:raise SpatialDeliveryError('five_independent_refs_required')
    expected=[('character','su_mo'),('character','ye_nan'),('character','ye_xijue'),('place','su_mo_room'),('place','su_mo_room')]
    if [(r.get('kind'),r.get('entity_id')) for r in refs]!=expected or len({r['reference_id'] for r in refs})!=5:
        raise SpatialDeliveryError('ordered_three_cast_two_environment_refs_required')
    for r in refs:
        _image(r['image']);proof=native.read(check(r['root_review']))
        if (proof.get('reviewed_by')!='root_agent' or proof.get('accepted_for_reference') is not True
                or proof.get('image')!=r['image'] or proof.get('entity_id')!=r['entity_id']):
            raise SpatialDeliveryError('explicit_reference_review_required')
        provenance=native.read(check(r['provenance']))
        if not isinstance(provenance,dict):raise SpatialDeliveryError('reference_provenance_required')
        if proof.get('provenance')!=r['provenance']:raise SpatialDeliveryError('reference_provenance_not_reviewed')
    return refs


def _room_only_authorization(spec,run):
    # One explicitly authorized comparison, not a general quota reset or variant API.
    expected_run=ROOT/'variants'/ROOM_ONLY_VARIANT
    if Path(run).resolve()!=expected_run or spec.get('variant')!=ROOM_ONLY_VARIANT:
        raise SpatialDeliveryError('room_only_fixed_variant_scope_required')
    if spec.get('authorization')!=binding(ROOT/'C_ROOM_ONLY_USER_AUTHORIZATION.json'):
        raise SpatialDeliveryError('room_only_fixed_authorization_required')
    auth=native.read(check(spec['authorization']))
    if (auth.get('schema')!='spatial_room_only_authorization/v31' or auth.get('user_statement')!='好'
            or not isinstance(auth.get('approved_proposal'),str) or not auth['approved_proposal'].strip()
            or not isinstance(auth.get('interpretation'),str) or not auth['interpretation'].strip()
            or auth.get('engineering_scope_not_user_quoted_numeric_limit') is not True
            or type(auth.get('max_full_video_submissions')) is not int or auth['max_full_video_submissions']!=4
            or type(auth.get('max_probe_video_submissions')) is not int or auth['max_probe_video_submissions']!=0
            or type(auth.get('new_cloud_media_calls')) is not int or auth['new_cloud_media_calls']!=0
            or auth.get('publication') is not False or auth.get('old_authorization_and_usage_preserved') is not True
            or any(auth.get(k) is not False for k in ('service_restarts','downloads','unknown_native_replay'))):
        raise SpatialDeliveryError('explicit_room_only_four_formal_zero_probe_authorization_required')
    for key,name in (('baseline_a_spec','A_SPEC.json'),('spatial_room_donor_spec','B_NATIVE_SPEC.json')):
        if auth.get(key)!=binding(ROOT/name):raise SpatialDeliveryError('room_only_fixed_baseline_and_donor_bindings_required')
    baseline=native.read(check(auth['baseline_a_spec']));donor=native.read(check(auth['spatial_room_donor_spec']))
    if (baseline.get('schema')!=SPEC or baseline.get('variant')!='A' or baseline.get('profile')!='minute'
            or donor.get('schema')!=SPEC or donor.get('variant')!='B'
            or len(baseline.get('references',[]))!=5 or len(donor.get('references',[]))!=5):
        raise SpatialDeliveryError('room_only_known_a_baseline_b_donor_required')
    expected=deepcopy(baseline);expected['variant']=ROOM_ONLY_VARIANT;expected['authorization']=spec['authorization']
    for index in (3,4):
        for key in ('image','provenance','root_review'):expected['references'][index][key]=deepcopy(donor['references'][index][key])
    if native.fingerprint(spec)!=native.fingerprint(expected):
        raise SpatialDeliveryError('room_only_spec_changed_outside_exact_six_reference_fields')
    return auth


def _authorization(spec,run):
    if spec.get('variant')==ROOM_ONLY_VARIANT:return _room_only_authorization(spec,run)
    auth=native.read(check(spec['authorization']))
    if (auth.get('schema')!='spatial_minute_experiment_authorization/v24' or not auth.get('user_statement')
            or auth.get('publication') is not False or auth.get('new_cloud_media_calls')!=0
            or spec['variant'] not in ('A','B','canary_A','canary_B')
            or auth.get('engineering_scope_not_user_quoted_numeric_limit') is not True
            or type(auth.get('max_full_video_submissions')) is not int or not 0<=auth['max_full_video_submissions']<=8
            or type(auth.get('max_probe_video_submissions')) is not int or not 0<=auth['max_probe_video_submissions']<=2):
        raise SpatialDeliveryError('explicit_bounded_local_authorization_required')
    return auth


def _validate_spec(spec,run):
    if spec.get('schema')!=SPEC or spec.get('variant')!=run.name or spec.get('profile') not in ('minute','probe'):
        raise SpatialDeliveryError('explicit_v24_spec_required')
    if spec.get('prompt_format') not in (None,'official_ref2va_v29'):
        raise SpatialDeliveryError('unsupported_explicit_prompt_format')
    _authorization(spec,run);_references(spec['references']);_guide(spec['initial_guide'])
    if Path(check(spec['parent_runner_plan'])).parent!=SOURCE:
        raise SpatialDeliveryError('original_minute_parent_required')
    if spec['profile']=='minute':
        if [x['id'] for x in spec['segments']]!=list(IDS) or (spec['width'],spec['height'],spec['frames'])!=(736,1312,362):
            raise SpatialDeliveryError('four_formal_segments_native_geometry_required')
    elif ([x['id'] for x in spec['segments']]!=['S01'] or (spec['width'],spec['height']) not in ((288,512),(384,672)) or spec['frames']!=124):
        raise SpatialDeliveryError('single_bounded_five_second_probe_required')
    for s in spec['segments']:
        original=check(s['original_prompt']).read_text(encoding='utf-8')
        if s['original_prompt']!=binding(SOURCE/'sources'/(s['id']+'.prompt.txt')):
            raise SpatialDeliveryError('original_source_prompt_required')
        text=check(s['prompt']).read_text(encoding='utf-8')
        expected=quotes(original) if spec['profile']=='minute' else quotes(original)[:1]
        if quotes(text)!=expected:raise SpatialDeliveryError('original_dialogue_changed_or_probe_overloaded')
        if spec.get('prompt_format')=='official_ref2va_v29':
            from .visual_spatial_native_prompt_v29 import validate_native_prompt
            validate_native_prompt(text,expected)
        if s.get('end_guide'):_guide(s['end_guide'])
    return spec


def prepare(spec_path,approval_path,run):
    run=_scope(run);spec=native.read(spec_path);_validate_spec(spec,run)
    approved=native.read(approval_path)
    if (approved.get('reviewed_by')!='root_agent' or approved.get('approved_for_generation') is not True
            or approved.get('spec')!=binding(spec_path) or approved.get('diagnostic_only') is not True):
        raise SpatialDeliveryError('root_spec_approval_required')
    cfg=deepcopy(spec['config']);base=native.read(check(cfg.pop('base_workflow')))
    allowed={'service_url','input_root','output_root','gpu_lock_root','timeout'}
    if set(cfg)!=allowed or cfg['service_url']!='http://127.0.0.1:8190':raise SpatialDeliveryError('existing_local_service_only')
    # Exact pre-existing native service paths, never an arbitrary filesystem copy target.
    old=native.read(PROJECT/'data/video_generation/visual_h3_ref_v20/seedance_reference_S01_736_20261107_v1/PLAN.json')
    if any(cfg[k]!=old['config'][k] for k in allowed):raise SpatialDeliveryError('existing_service_config_changed')
    if base.get('condition',{}).get('class_type') not in ('MiniMaxH3ImageToVideo','MiniMaxH3ReferenceToVideo'):
        raise SpatialDeliveryError('known_h3_base_graph_required')
    plan=dict(schema=SCHEMA,spec=binding(spec_path),approval=binding(approval_path),authorization=spec['authorization'],
        variant=run.name,profile=spec['profile'],config=cfg,base=base,settings=spec,
        protected_pause=old['protected_pause'],diagnostic_preview=True,production_approved=False,publication=False)
    run.mkdir(parents=True,exist_ok=True)
    with jobs.run_lock(run):
        native.freeze(run/'PLAN.json',plan)
        for s in spec['segments']:
            folder=run/'shots'/s['id'];folder.mkdir(parents=True,exist_ok=True)
            if not (folder/'STATE.json').exists():native.write(folder/'STATE.json',dict(id=s['id'],status='prepared',prompt_id=None,plan_sha256=native.fingerprint(plan)))
    return status(run)


def _load(run,current=False):
    run=_scope(run);plan=native.read(run/'PLAN.json')
    if plan.get('schema')!=SCHEMA or plan.get('variant')!=run.name or plan.get('production_approved') is not False or plan.get('publication') is not False:
        raise SpatialDeliveryError('v24_independent_diagnostic_plan_required')
    if current:
        spec=native.read(check(plan['spec']));approved=native.read(check(plan['approval']))
        if spec!=plan['settings'] or approved.get('spec')!=plan['spec']:raise SpatialDeliveryError('frozen_spec_changed')
        _validate_spec(spec,run)
        if native.file_sha(plan['protected_pause']['path'])!=plan['protected_pause']['sha256']:raise SpatialDeliveryError('old_pause_changed')
    return run,plan


def _state(run,plan,sid):
    folder=run/'shots'/sid;state=native.read(folder/'STATE.json')
    if state.get('id')!=sid or state.get('plan_sha256')!=native.fingerprint(plan):raise SpatialDeliveryError('state_plan_changed')
    claim=(folder/'CLAIM.json').exists();response=native.read(folder/'RESPONSE.json') if (folder/'RESPONSE.json').exists() else {}
    if claim:
        graph=native.read(folder/'workflow_api.json');row=native.read(folder/'GRAPH_BINDING.json');req=native.read(folder/'REQUEST.json')
        if (native.fingerprint(graph)!=row['graph_sha256'] or req['prompt']!=graph
                or native.read(folder/'CLAIM.json')['graph_sha256']!=row['graph_sha256']
                or state.get('graph_sha256')!=row['graph_sha256']):
            raise SpatialDeliveryError('native_submission_claim_changed')
        pid=response.get('prompt_id')
        if pid:
            native.slug(pid)
            if state.get('prompt_id') not in (None,pid):raise SpatialDeliveryError('original_id_changed')
            state['prompt_id']=pid
            if state['status']=='prepared':state['status']='submitted'
        elif state['status']=='prepared':state.update(status='outcome_unknown',reason='claim_without_native_id')
    elif response or state.get('prompt_id'):raise SpatialDeliveryError('native_id_without_original_claim')
    if state['status']=='technical_saved':
        result=native.read(folder/'RESULT.json');row=native.read(folder/'GRAPH_BINDING.json')
        if (state.get('result_sha256')!=native.file_sha(folder/'RESULT.json') or result.get('prompt_id')!=state['prompt_id']
                or result.get('graph_sha256')!=row['graph_sha256'] or result.get('technical_status')!='technical_saved'):
            raise SpatialDeliveryError('original_result_changed')
        for f in result['files'].values():
            p=check({k:f[k] for k in ('path','sha256')})
            if not p.is_relative_to(folder/'artifacts'):raise SpatialDeliveryError('native_copy_scope_changed')
        entry=native.read(folder/'HISTORY.json').get(state['prompt_id'],{})
        prompt=entry.get('prompt',[]);terminal=entry.get('status',{})
        if (len(prompt)<3 or prompt[1]!=state['prompt_id'] or terminal.get('completed') is not True
                or terminal.get('status_str')!='success' or native.native_graph_equivalence(native.read(folder/'workflow_api.json'),prompt[2]) is None):
            raise SpatialDeliveryError('saved_native_history_changed')
    return state


def status(run):
    run,plan=_load(run);states=[_state(run,plan,s['id']) for s in plan['settings']['segments']]
    ids=[s['prompt_id'] for s in states if s.get('prompt_id')]
    if len(ids)!=len(set(ids)):raise SpatialDeliveryError('distinct_native_id_each_shot_required')
    return dict(schema=SCHEMA,run=str(run),profile=plan['profile'],shots=states,technical_saved=sum(s['status']=='technical_saved' for s in states),total=len(states),
                paused=(run/'PAUSE.json').exists(),diagnostic_preview=True,production_approved=False,publication=False)


def _append(run,event,sid,pid=''):
    with (run/'LOG.md').open('a',encoding='utf-8') as f:f.write(f'{time.time():.3f} {event} {sid} {pid}\n')
    if event=='SUBMIT':
        line=sid+' '+pid+'\n';ledger=run/'job_ids.txt'
        if not ledger.exists() or line not in ledger.read_text(encoding='utf-8'):
            with ledger.open('a',encoding='utf-8') as f:f.write(line)


def _tail(run,plan,index):
    if index==0:return deepcopy(plan['settings']['initial_guide'])
    previous=plan['settings']['segments'][index-1]['id'];state=_state(run,plan,previous)
    if state['status']!='technical_saved':raise SpatialDeliveryError('previous_actual_native_tail_required')
    path=run/'shots'/previous/'RESULT.json';result=native.read(path)
    return dict(image={k:result['files']['last'][k] for k in ('path','sha256')},native_result=binding(path),role='last',
        native_id=result['prompt_id'],previous_segment=previous,policy='actual_previous_native_tail_even_if_semantically_imperfect')


def build_graph(base,settings,segment,scope,guide,seed):
    graph=deepcopy(base)
    # Source may already be the old Ref2VA graph; remove its previous image slots.
    for k in list(graph):
        if graph[k].get('class_type')=='LoadImage' or k.startswith('guide_'):graph.pop(k)
    old=base['condition']['inputs'];inputs={k:deepcopy(old[k]) for k in ('clip','vae')}
    text=check(segment['prompt']).read_text(encoding='utf-8');lines=['参考身份与环境：']
    for i,r in enumerate(settings['references']):
        node='ref_'+str(i);graph[node]=dict(class_type='LoadImage',inputs=dict(image=scope+'/references/'+str(i)+'.png'))
        inputs['ref_images.ref_image_'+str(i)]=[node,0]
        lines.append('<Picture '+str(i+1)+'>：'+r['description'])
    if settings.get('prompt_format')=='official_ref2va_v29':
        from .visual_spatial_native_prompt_v29 import validate_native_prompt
        validate_native_prompt(text)
        compiled_text=text
    else:
        compiled_text=text+'\n\n'+'\n'.join(lines)
    inputs.update(prompt=compiled_text,width=settings['width'],height=settings['height'],length=settings['frames'],ref_image_size='match')
    graph['condition']=dict(class_type='MiniMaxH3ReferenceToVideo',inputs=inputs)
    graph['127']['inputs']['unet_name']=MODEL;graph['129']['inputs']['noise_seed']=seed
    graph['124']['inputs']['steps']=12;graph['124']['inputs']['denoise']=1
    graph['guide_start_image']=dict(class_type='LoadImage',inputs=dict(image=scope+'/guides/start.png'))
    graph['guide_start']=dict(class_type='MiniMaxH3AddGuide',inputs=dict(positive=['condition',0],latent=['condition',1],vae=inputs['vae'],image=['guide_start_image',0],frame_idx=0))
    positive=['guide_start',0]
    if segment.get('end_guide'):
        graph['guide_end_image']=dict(class_type='LoadImage',inputs=dict(image=scope+'/guides/end.png'))
        graph['guide_end']=dict(class_type='MiniMaxH3AddGuide',inputs=dict(positive=positive,latent=['condition',1],vae=inputs['vae'],image=['guide_end_image',0],frame_idx=settings['frames']-1))
        positive=['guide_end',0]
    graph['126']['inputs']['conditioning']=positive
    graph['pick_first']['inputs']['batch_index']=0;graph['pick_last']['inputs']['batch_index']=settings['frames']-1
    graph['130']['inputs']['fps']=24
    for role in ROLES:graph['save_'+role]['inputs']['filename_prefix']=scope+'/'+role
    for node in graph.values():
        for value in node.get('inputs',{}).values():
            if isinstance(value,list) and len(value)==2 and isinstance(value[0],str) and type(value[1]) is int and value[0] not in graph:
                raise SpatialDeliveryError('dangling_graph_input')
    return graph


def _room_only_budget(run,plan):
    auth=_room_only_authorization(plan['settings'],run)
    if (plan.get('authorization')!=plan['settings']['authorization'] or plan.get('profile')!='minute'
            or plan.get('variant')!=ROOM_ONLY_VARIANT):
        raise SpatialDeliveryError('room_only_plan_authorization_or_profile_changed')
    count=0
    for claim in (ROOT/'variants').glob('*/shots/*/CLAIM.json'):
        other_run=claim.parents[2];other=native.read(other_run/'PLAN.json')
        same=other.get('authorization')==plan['authorization']
        if other_run==run or other.get('variant')==ROOM_ONLY_VARIANT or same:
            if (other_run!=run or other.get('variant')!=ROOM_ONLY_VARIANT or not same
                    or other.get('profile')!='minute' or native.fingerprint(other.get('settings'))!=native.fingerprint(plan['settings'])
                    or claim.parent.name not in IDS):
                raise SpatialDeliveryError('room_only_authorization_claim_outside_fixed_run')
            # CLAIM consumes its slot even if the original POST outcome is unknown.
            count+=1
    if count>=auth['max_full_video_submissions']:raise SpatialDeliveryError('shared_native_submission_budget_exhausted')


def _budget(run,plan):
    if run.name==ROOM_ONLY_VARIANT:return _room_only_budget(run,plan)
    auth=_authorization(plan['settings'],run);counts={'minute':0,'probe':0}
    for f in (ROOT/'variants').glob('*/shots/*/CLAIM.json'):
        other=native.read(f.parents[2]/'PLAN.json')
        if other.get('authorization')!=plan['authorization']:raise SpatialDeliveryError('shared_budget_authorization_mismatch')
        counts[other['profile']]+=1
    key='max_full_video_submissions' if plan['profile']=='minute' else 'max_probe_video_submissions'
    if counts[plan['profile']]>=auth[key]:raise SpatialDeliveryError('shared_native_submission_budget_exhausted')


def submit_next(run):
    run,plan=_load(run,current=True);cfg=plan['config'];settings=plan['settings']
    with jobs.run_lock(run):
        current=status(run)
        if current['paused']:return dict(current,dispatch='paused')
        for index,(seg,state) in enumerate(zip(settings['segments'],current['shots'])):
            if state['status']=='technical_saved':continue
            if state['status']!='prepared':return current
            break
        else:return current
        with native._gpu(plan),jobs.run_lock(ROOT,'BUDGET.lock'):
            _load(run,current=True);_budget(run,plan)
            if (run/'PAUSE.json').exists():return dict(current,dispatch='paused')
            native._service_paths(cfg);q=native._queue(cfg)
            if q['queue_running'] or q['queue_pending']:return dict(current,dispatch='waiting_gpu_queue')
            capability=native._http(cfg,'/object_info')
            if not all(k in capability for k in ('MiniMaxH3ReferenceToVideo','MiniMaxH3AddGuide')):raise SpatialDeliveryError('live_reference_plus_guide_nodes_required')
            folder=run/'shots'/seg['id'];scope=PREFIX+'/'+run.name+'/'+seg['id'];guide=_tail(run,plan,index)
            _image(guide['image'])
            graph=build_graph(plan['base'],settings,seg,scope,guide,settings.get('seed',12345)+index)
            row=dict(id=seg['id'],graph_sha256=native.fingerprint(graph),guide=guide,scope=scope,source_prompt=seg['prompt'],
                     reference_sha256=native.fingerprint(settings['references']),end_guide=seg.get('end_guide'))
            for name,value in [('workflow_api.json',graph),('GRAPH_BINDING.json',row),('CAPABILITY.json',{k:capability[k] for k in ('MiniMaxH3ReferenceToVideo','MiniMaxH3AddGuide')})]:native.freeze(folder/name,value)
            # Image staging's Config is narrower than the video executor config.
            # Keep its real normalization and source/target SHA checks enabled.
            stage_cfg={k:cfg[k] for k in ('service_url','input_root','output_root','timeout')}
            for i,r in enumerate(settings['references']):jobs.stage_input(stage_cfg,r['image']['path'],scope+'/references/'+str(i)+'.png',r['image']['sha256'])
            jobs.stage_input(stage_cfg,guide['image']['path'],scope+'/guides/start.png',guide['image']['sha256'])
            if seg.get('end_guide'):
                g=seg['end_guide'];jobs.stage_input(stage_cfg,g['image']['path'],scope+'/guides/end.png',g['image']['sha256'])
            # A crash before CLAIM is known pre-POST; reuse its frozen request.
            # Once CLAIM exists _state forbids replay without a known response.
            request=(native.read(folder/'REQUEST.json') if (folder/'REQUEST.json').exists()
                     else dict(prompt=graph,client_id=uuid.uuid4().hex))
            if request.get('prompt')!=graph:raise SpatialDeliveryError('frozen_prepost_request_changed')
            native.freeze(folder/'REQUEST.json',request)
            state['graph_sha256']=row['graph_sha256'];native.write(folder/'STATE.json',state)
            native.freeze(folder/'CLAIM.json',dict(at=time.time(),graph_sha256=row['graph_sha256']))
            try:response=native._http(cfg,'/prompt',request)
            except urllib.error.HTTPError as error:
                native.freeze(folder/'SUBMISSION_ERROR.json',dict(type='HTTPError',code=error.code));state.update(status='rejected' if error.code in (400,422) else 'outcome_unknown')
            except Exception as error:
                native.freeze(folder/'SUBMISSION_ERROR.json',dict(type=type(error).__name__));state.update(status='outcome_unknown')
            else:
                native.freeze(folder/'RESPONSE.json',response);pid=response.get('prompt_id') if isinstance(response,dict) else None
                if isinstance(pid,str) and re.fullmatch('[A-Za-z0-9_-]{1,100}',pid):
                    state.update(status='submitted',prompt_id=pid,submitted_at=time.time());_append(run,'SUBMIT',seg['id'],pid)
                else:state.update(status='outcome_unknown')
            native.write(folder/'STATE.json',state)
    return status(run)


def _collect(folder,plan,row,state,entry):
    cfg=plan['config'];files={};scope=(Path(cfg['output_root'])/row['scope']).resolve()
    for role,key,suffix in [('video','images','.mp4'),('audio','audio','.flac'),('first','images','.png'),('last','images','.png')]:
        records=entry.get('outputs',{}).get('save_'+role,{}).get(key)
        if not isinstance(records,list) or len(records)!=1 or records[0].get('type')!='output':raise SpatialDeliveryError('four_original_native_outputs_required')
        rec=records[0];name=rec.get('filename','')
        if '/' in name or '\\' in name or not name.startswith(role+'_') or Path(name).suffix.lower()!=suffix:raise SpatialDeliveryError('native_filename_changed')
        source=native.bound(cfg['output_root'],rec.get('subfolder','').replace('\\','/')+'/'+name)
        if source.parent!=scope or not source.is_file() or not source.stat().st_size:raise SpatialDeliveryError('native_output_scope_changed')
        dest=folder/'artifacts'/name;dest.parent.mkdir(exist_ok=True);sha=native.file_sha(source)
        if not dest.exists():jobs._copy_new(source,dest)
        if native.file_sha(dest)!=sha:raise SpatialDeliveryError('native_copy_changed')
        files[role]=dict(path=str(dest),source_path=str(source),sha256=sha)
    meta=native._metadata(files['video']['path']);v=next(x for x in meta['streams'] if x['codec_type']=='video')
    a=next((x for x in meta['streams'] if x['codec_type']=='audio'),None);s=plan['settings']
    if not a or (v['width'],v['height'],int(v.get('nb_frames',-1)),v['r_frame_rate'])!=(s['width'],s['height'],s['frames'],'24/1'):
        raise SpatialDeliveryError('native_video_audio_geometry_mismatch')
    if not any(x['codec_type']=='audio' for x in native._metadata(files['audio']['path'])['streams']):raise SpatialDeliveryError('original_audio_missing')
    for role in ('first','last'):
        if _image({k:files[role][k] for k in ('path','sha256')})!=(s['width'],s['height']):raise SpatialDeliveryError('native_frame_geometry_mismatch')
    result=dict(schema=SCHEMA,shot_id=row['id'],prompt_id=state['prompt_id'],graph_sha256=row['graph_sha256'],
        files=files,native_metadata=meta,guide=row['guide'],source_prompt=row['source_prompt'],references_sha256=row['reference_sha256'],
        technical_status='technical_saved',content_status='diagnostic_raw_quality_not_gated',production_approved=False,publication=False)
    native.freeze(folder/'RESULT.json',result);state.update(status='technical_saved',result_sha256=native.file_sha(folder/'RESULT.json'));_append(folder.parents[1],'SAVED',row['id'],state['prompt_id'])


def poll_collect(run):
    run,plan=_load(run);cfg=plan['config']
    with jobs.run_lock(run):
        for seg in plan['settings']['segments']:
            sid=seg['id'];folder=run/'shots'/sid;state=_state(run,plan,sid)
            if state['status'] not in ('submitted','running') or not state.get('prompt_id'):continue
            pid=state['prompt_id'];row=native.read(folder/'GRAPH_BINDING.json');history=native._http(cfg,'/history/'+native.slug(pid));entry=history.get(pid)
            if entry:
                prompt=entry.get('prompt');terminal=entry.get('status',{})
                if not isinstance(prompt,list) or len(prompt)<3 or prompt[1]!=pid or not native._verify_native_graph(folder,row,prompt[2],pid):raise SpatialDeliveryError('original_native_history_mismatch')
                native.write(folder/'HISTORY.latest.json',history)
                if terminal.get('status_str')=='error':
                    events=[x[0] for x in terminal.get('messages',[]) if isinstance(x,list) and x]
                    state.update(status='interrupted' if 'execution_interrupted' in events else 'failed',native_terminal=terminal)
                elif terminal.get('completed') is True and terminal.get('status_str')=='success':
                    native.freeze(folder/'HISTORY.json',history);_collect(folder,plan,row,state,entry)
                else:state['status']='running'
            else:
                q=native._queue(cfg);matches=[x for x in q['queue_running']+q['queue_pending'] if x[1]==pid]
                if any(not native._verify_native_graph(folder,row,x[2],pid) for x in matches):raise SpatialDeliveryError('original_native_queue_mismatch')
                state.update(status='running' if matches else 'outcome_unknown',reason=None if matches else 'original_id_absent_history_queue')
            native.write(folder/'STATE.json',state)
    return status(run)


def assemble(run):
    run,plan=_load(run,current=True);s=plan['settings']
    if plan['profile']!='minute':raise SpatialDeliveryError('probe_is_not_minute')
    with jobs.run_lock(run,'ASSEMBLY.lock'):
        if status(run)['technical_saved']!=4:raise SpatialDeliveryError('four_distinct_native_segments_required')
        rows=[native.read(run/'shots'/sid/'RESULT.json') for sid in IDS];videos=[r['files']['video'] for r in rows];ids=[r['prompt_id'] for r in rows]
        if len(set(ids))!=4 or len({v['sha256'] for v in videos})!=4:raise SpatialDeliveryError('distinct_native_videos_required')
        inputs=dict(plan=binding(run/'PLAN.json'),results=[binding(run/'shots'/sid/'RESULT.json') for sid in IDS]);digest=native.fingerprint(inputs)
        output=run/'DIAGNOSTIC_MINUTE_736x1312.mp4';final=run/'FINAL_RESULT.json'
        if final.exists():
            value=native.read(final);check(value['file'])
            if value['assembly_inputs_sha256']!=digest:raise SpatialDeliveryError('assembly_input_changed')
            return value
        if output.exists():raise SpatialDeliveryError('unreceipted_output_preserved')
        from .visual_h3_reference_full_minute_v20 import _probe
        from .visual_spatial_clock_v30 import clock_input as _clock_input
        adjustments=[_clock_input(v['path'],v['sha256']) for v in videos]
        filters=run/'ASSEMBLY_FILTER.txt';command,text=clock.assembly_command([v['path'] for v in videos],filters,output,frames=362);filters.write_text(text,encoding='utf-8')
        native.freeze(run/'ASSEMBLY_REQUEST.json',dict(inputs=inputs,inputs_sha256=digest,command=command,adjustments=adjustments))
        p=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=1800);(run/'ASSEMBLY.stderr.log').write_text(p.stderr,encoding='utf-8');p.check_returncode()
        timing=clock.verify_clock(_probe(output),frames=1448,width=736,height=1312)
        if inputs['results']!=[binding(run/'shots'/sid/'RESULT.json') for sid in IDS]:raise SpatialDeliveryError('original_results_changed_during_assembly')
        value=dict(schema=SCHEMA,file=binding(output),assembly_inputs_sha256=digest,native_ids=ids,clock=timing,diagnostic_preview=True,content_status='raw_movie_for_root_review',production_approved=False,publication=False)
        native.freeze(final,value);_append(run,'ASSEMBLED','ALL');return value


def execute(run,poll_seconds=30,max_seconds=86400):
    if not 1<=poll_seconds<=60 or not 0<max_seconds<=86400:raise SpatialDeliveryError('bounded_poll_window_required')
    run,plan=_load(run)
    with jobs.run_lock(run,'RUNNER.lock'):
        start=time.monotonic()
        while True:
            current=poll_collect(run);active=any(x['status'] in ('running','submitted') for x in current['shots'])
            if any(x['status'] in BAD for x in current['shots']):return current
            if current['technical_saved']==current['total']:
                return assemble(run) if plan['profile']=='minute' else current
            error=None
            try:_load(run,current=True)
            except (OSError,ValueError,KeyError) as exc:error=dict(type=type(exc).__name__,message=str(exc))
            if current['paused'] or error:
                if not active or time.monotonic()-start>=max_seconds:return dict(current,input_error=error)
            else:submit_next(run)
            if time.monotonic()-start>=max_seconds:return dict(status(run),dispatch='bounded_wait_original_ids_preserved')
            time.sleep(poll_seconds)
