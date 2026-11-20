"""Ref2VA: all fixed identity/environment assets plus actual dynamic tail/guide."""
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
from . import visual_h3_identity_continuation_v1 as source_renderer
from .visual_spatial_clock_v30 import clock_input
from PIL import Image
import hashlib

SERIES='h3_full_asset_continuation_series/v1'
SCHEMA='h3_full_asset_continuation_native/v1'
CONTRACT='actual_full_assets_and_native_guide/v1'
CONDITIONING='Ref2VA_six_references_and_frame0_guide'
REVIEW='h3_full_asset_guide_state/v1'
MANIFEST='accepted_video_fixed_reference_assets/v1'
MODEL='minimax_h3_ref2va_pruned_int8_convrot.safetensors'
COMFY=Path('D:/IT/AI_vido/ComfyUI')
CAPABILITY_FILES=(COMFY/'comfy_extras/nodes_minimax_h3.py',COMFY/'comfy/model_base.py',COMFY/'comfy/ldm/minimax/model.py')
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


def image_binding(value):return {k:value[k] for k in ('path','sha256')}


def bundle(manifest_binding,observation_binding):
    m=read(core.check(manifest_binding));seen=read(core.check(observation_binding))
    if (m.get('schema')!=MANIFEST or m.get('fixed_reference_count')!=5 or m.get('fixed_order')!=['P1','P2','P3','P4','P5']
            or seen.get('schema')!='root_fixed_reference_asset_observation/v1' or seen.get('manifest')!=manifest_binding
            or seen.get('asset_version')!=m.get('asset_version') or seen.get('fixed_reference_set_eligible') is not True
            or seen.get('completion_known') is not True or seen.get('outcome_unknown') is not False or not _strings(seen.get('evidence'))):
        raise ValueError('actual_observed_fixed_asset_version_required')
    for b in (m['source_native_result'],m['source_video'],m['source_frame_verification'],m['extraction_script']):core.check(b)
    if len(m['references'])!=5 or len(seen.get('reviewed_assets',[]))!=5:raise ValueError('five_independent_assets_required')
    for i,(ref,observation) in enumerate(zip(m['references'],seen['reviewed_assets'])):
        image=image_binding(ref['image']);path=core.check(image);frame=core.check(ref['source']['frame']);core.check(ref['source']['video'])
        if (ref['slot']!=i or ref['tag']!=f'<Picture {i+1}>' or ref['asset_version']!=m['asset_version']
                or ref['source']['video']!=m['source_video'] or ref['source']['native_id']!=m['source_native_id']
                or ref['kind']!=('character' if i<3 else 'environment_detail')
                or ref['intended_person_count']!=(1 if i<3 else 0)
                or observation.get('image')!=image or observation.get('observed') is not True
                or any(observation.get(k)!=ref[k] for k in ('reference_id','slot','tag','entity_id','intended_person_count'))):
            raise ValueError('fixed_reference_order_identity_or_observation_changed')
        roi=ref['roi'];box=(roi['x'],roi['y'],roi['x']+roi['width'],roi['y']+roi['height'])
        with Image.open(frame) as original:
            if min(box)<0 or box[2]>original.width or box[3]>original.height:raise ValueError('asset_crop_outside_source')
            expected=original.convert('RGB').crop(box)
        with Image.open(path) as actual:
            if actual.size!=(ref['image']['width'],ref['image']['height']) or actual.convert('RGB').tobytes()!=expected.tobytes():raise ValueError('asset_not_exact_bound_source_crop')
        d=ref['derivation']
        if (d.get('resize') is not None or d.get('upscale') is not False or d.get('rotation_degrees')!=0
                or hashlib.sha256(expected.tobytes()).hexdigest()!=d['exact_pixels_sha256']
                or any(x%32 for x in expected.size) or expected.width*expected.height>736*1312):raise ValueError('unchanged_native_reference_pixels_required')
    if [r['actor_id'] for r in m['references'][:3]]!=m['clip_actor_ids']:raise ValueError('fixed_full_clip_character_assets_required')
    return m


def validate_graph(graph,scope,mapping):
    expected=dict(native.CLASSES);expected.pop('ref_scene');expected['condition']='MiniMaxH3ReferenceToVideo'
    expected.update({f'ref_{i}':'LoadImage' for i in range(6)});expected['guide_start']='MiniMaxH3AddGuide'
    if set(graph)!=set(expected) or any(graph[n].get('class_type')!=kind for n,kind in expected.items()):raise ValueError('exact_Ref2VA_plus_guide_graph_required')
    condition=graph['condition']['inputs'];slots={f'ref_images.ref_image_{i}':[f'ref_{i}',0] for i in range(6)}
    if (set(condition)!=set(slots)|{'clip','vae','prompt','width','height','length','ref_image_size'}
            or any(condition[k]!=v for k,v in slots.items()) or condition['clip']!=['128',0] or condition['vae']!=['119',0]
            or (condition['width'],condition['height'],condition['length'],condition['ref_image_size'])!=(736,1312,362,'match')
            or graph['127']['inputs']['unet_name']!=MODEL or graph['124']['inputs']['steps']!=12 or graph['130']['inputs']['fps']!=24):
        raise ValueError('six_references_videoVAE_and_native_profile_required')
    if len(mapping)!=6:raise ValueError('six_actual_independent_image_bindings_required')
    for i,ref in enumerate(mapping):
        if ref['slot']!=i or ref['tag']!=f'<Picture {i+1}>' or graph[f'ref_{i}']['inputs']!={'image':ref['input_name']}:
            raise ValueError('actual_reference_slot_mapping_changed')
    if graph['guide_start']['inputs']!=dict(positive=['condition',0],latent=['condition',1],vae=['119',0],image=['ref_5',0],frame_idx=0):raise ValueError('dynamic_P6_positive_frame0_guide_required')
    if graph['126']['inputs']!=dict(model=['127',0],conditioning=['guide_start',0]) or graph['125']['inputs']['latent_image']!=['condition',1] or graph['125']['inputs']['guider']!=['126',0]:raise ValueError('references_and_guide_must_reach_positive_sampler')
    for role in ('video','audio','first','last'):
        if graph['save_'+role]['inputs']['filename_prefix']!=scope+'/'+role:raise ValueError('new_native_output_scope_required')
    if graph['pick_first']['inputs']['batch_index']!=0 or graph['pick_last']['inputs']['batch_index']!=361:raise ValueError('actual_native_endpoint_indices_required')


def build_graph(base,shot,value,mapping,scope):
    graph=deepcopy(base);graph.pop('ref_scene')
    graph['127']['inputs']['unet_name']=MODEL
    refs={f'ref_images.ref_image_{i}':[f'ref_{i}',0] for i in range(6)}
    graph['condition']=dict(class_type='MiniMaxH3ReferenceToVideo',inputs=dict(clip=['128',0],vae=['119',0],
        prompt=value['compiled_prompt'],width=736,height=1312,length=362,ref_image_size='match',**refs))
    for i,ref in enumerate(mapping):graph[f'ref_{i}']=dict(class_type='LoadImage',inputs=dict(image=ref['input_name']))
    graph['guide_start']=dict(class_type='MiniMaxH3AddGuide',inputs=dict(positive=['condition',0],latent=['condition',1],vae=['119',0],image=['ref_5',0],frame_idx=0))
    graph['126']['inputs']=dict(model=['127',0],conditioning=['guide_start',0]);graph['125']['inputs']['latent_image']=['condition',1]
    graph['129']['inputs']['noise_seed']=int(core.digest(dict(shot=shot['binding_sha256'],images=[r['image']['sha256'] for r in mapping]))[:14],16)
    graph['pick_first']['inputs']['batch_index']=0;graph['pick_last']['inputs']['batch_index']=361
    for role in ('video','audio','first','last'):graph['save_'+role]['inputs']['filename_prefix']=scope+'/'+role
    validate_graph(graph,scope,mapping);return graph


def verify_native(result_binding):
    """Authenticate saved originals and native history, without visual claims."""
    path=Path(core.check(result_binding));result=read(path);folder=path.parent;run=folder.parents[1]
    plan=read(run/'PLAN.json');sid=result['shot_id'];rows=[x for x in plan['shots'] if x['id']==sid]
    if len(rows)!=1 or folder!=run/'shots'/sid:raise ValueError('original_native_result_scope_required')
    row=rows[0];state=native._shot_state(folder,plan,row);graph=read(folder/'workflow_api.json')
    validate_graph(graph,row['scope'],row['reference_map']) if plan.get('schema')==SCHEMA else native._validate_graph(graph,row['scope'],row['input_name'])
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
    fixed=bundle(spec['asset_manifest'],spec['asset_observation'])
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
        asset_manifest=spec['asset_manifest'],asset_observation=spec['asset_observation'],asset_version=fixed['asset_version'],
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
    run=Path(run).resolve();entry=core._entries(bind(part(run,sid)/'SOURCE_CASE.json'))[0]
    previous=_predecessor(run,sid)
    if previous is None:return dict(status='upstream_native_tail_required',predecessor_shot_id='S03',model_posts=0)
    proof=verify_native(previous);req=core.validate_entry(entry)
    value=dict(schema=REVIEW+'_request',shot_id=sid,predecessor_result=previous,guide_image=proof['last_image'],
        required_actor_assets=req['visible_actors'],opening_actor_ids=list(entry['camera_beats'][0]['actors']),
        required_review_file=str(part(run,sid)/'GUIDE_STATE_REVIEW.json'),guide_visibility_does_not_filter_required_assets=True,review_not_observed=True)
    freeze(part(run,sid)/'GUIDE_STATE_REQUEST.json',value)
    return dict(status='actual_guide_state_review_required',request=bind(part(run,sid)/'GUIDE_STATE_REQUEST.json'),model_posts=0)



def render(entry,review,manifest):
    refs=manifest['references'];names=entry['character_names']
    appearances={'su_mo':'灰色纽扣衬衫、深色夹克','ye_nan':'灰色纽扣短袖衬衫','ye_xijue':'米色纽扣领短袖上衣'}
    by={r['actor_id']:dict(screen_description=r['tag']+'中的同一人物，采用该人物面部与上衣外观',appearance=appearances[r['actor_id']]) for r in refs[:3]}
    surrogate=dict(identity_by_actor=by)
    if review.get('world_actor_state'):surrogate['anchor_action_state']='；'.join(names[c]+'：'+review['world_actor_state'][c] for c in core.validate_entry(entry)['visible_actors'])
    text=source_renderer.render(entry,surrogate)
    text=text.replace('输入是上一段原生视频的真实尾帧，人物外貌、服装、房间与持物状态从该画面继续；',
        '人物身份和上衣外观采用<Picture 1>、<Picture 2>、<Picture 3>，房间材料采用<Picture 4>、<Picture 5>，当前姿态、持物和空间承接<Picture 6>；',1)
    lines=['参考图分工与同一身份映射：']
    for r in refs[:3]:lines.append(r['tag']+'：'+names[r['actor_id']]+'的独立人物身份与上衣参考。表演的姿态、神情按本段剧情推进。')
    lines.extend(['<Picture 4>：同一房间的家具与墙面材料局部。','<Picture 5>：同一房间的窗与墙面局部。',
        '<Picture 6>：上一段真实结束画面，提供当前动作、持物和空间；其中每位可见人物按下述位置对应已有独立身份。'])
    for cid in review['guide_visible_actor_ids']:lines.append('<Picture 6>中的'+review['screen_identity_map'][cid]+'对应'+names[cid]+'，与'+refs[[r['actor_id'] for r in refs[:3]].index(cid)]['tag']+'为同一人。')
    result=text+'\n'+'\n'.join(lines)
    if core.QUOTE.findall(result)!=core.QUOTE.findall(core.compile_prompt(entry)['compiled_prompt']):raise ValueError('five_original_quote_content_changed')
    return result



def input_value(run,sid):
    run=Path(run).resolve();request=review_request(run,sid)
    if request['status']=='upstream_native_tail_required':return request
    series=read(run/'PLAN.json');manifest=bundle(series['asset_manifest'],series['asset_observation'])
    source=bind(part(run,sid)/'SOURCE_CASE.json');entry=core._entries(source)[0];req=core.validate_entry(entry)
    if set(req['visible_actors'])!=set(manifest['clip_actor_ids']):raise ValueError('all_clip_actors_need_fixed_independent_assets')
    previous=_predecessor(run,sid);proof=verify_native(previous);path=part(run,sid)/'GUIDE_STATE_REVIEW.json'
    if not path.exists():return request
    review=read(path);visible=review.get('guide_visible_actor_ids',[]);world=review.get('world_actor_state',{});screen=review.get('screen_identity_map',{})
    if (review.get('schema')!=REVIEW or review.get('shot_id')!=sid or review.get('predecessor_result')!=previous
            or review.get('guide_image')!=proof['last_image'] or review.get('completion_known') is not True or review.get('outcome_unknown') is not False
            or not review.get('reviewed_by') or not _strings(review.get('evidence')) or not isinstance(visible,list) or len(visible)!=len(set(visible))
            or not set(visible)<=set(req['visible_actors']) or set(world)!=set(req['visible_actors']) or set(screen)!=set(visible)
            or any(not isinstance(v,str) or not v.strip() for v in [*world.values(),*screen.values()])):
        raise ValueError('actual_tail_guide_visibility_and_world_state_required')
    text=render(entry,review,manifest)
    references=[dict(slot=r['slot'],tag=r['tag'],reference_id=r['reference_id'],entity_id=r['entity_id'],identity_group=r['identity_group'],
        kind=r['kind'],asset_version=r['asset_version'],image=image_binding(r['image'])) for r in manifest['references']]
    references.append(dict(slot=5,tag='<Picture 6>',reference_id='dynamic_native_tail:'+proof['result']['prompt_id'],kind='dynamic_native_tail',
        identity_group='same_known_actors_current_state',image=proof['last_image']))
    return dict(schema=CONTRACT,shot_id=sid,source_case=source,entry_sha256=core.digest(entry),first_image=proof['last_image'],
        predecessor_result=previous,generation_receipt=proof,guide_review=bind(path),asset_manifest=series['asset_manifest'],asset_observation=series['asset_observation'],
        asset_version=manifest['asset_version'],references=references,required_actor_assets=req['visible_actors'],guide_visible_actor_ids=visible,
        world_actor_state=world,opening_actor_ids=list(entry['camera_beats'][0]['actors']),compiled_prompt=text,compiled_prompt_utf8_sha256=core.sha(text),
        opening_handoff_seconds=.5,full_video_quality_passed=False,production_approved=False,publication=False,conditioning_mode=CONDITIONING)



def validate_input(value):
    path=Path(core.check(value));run=path.parents[2];sid=path.parent.name;data=read(path)
    if path!=part(run,sid)/'FULL_ASSET_INPUT.json' or input_value(run,sid)!=data:raise ValueError('full_asset_source_or_pixels_changed')
    proof={k:deepcopy(data[k]) for k in ('schema','source_case','first_image','predecessor_result','guide_review','asset_manifest','asset_observation',
        'asset_version','references','required_actor_assets','guide_visible_actor_ids','world_actor_state','compiled_prompt_utf8_sha256')};proof['input']=value
    return dict(data,entry=core._entries(data['source_case'])[0],proof=proof,quality_passed=False)



def prepare_video(run,sid,*,code_files=()):
    run=Path(run).resolve();value=input_value(run,sid)
    if 'status' in value:return value
    p=part(run,sid);freeze(p/'FULL_ASSET_INPUT.json',value);ib=bind(p/'FULL_ASSET_INPUT.json');checked=validate_input(ib)
    cfg=read(core.check(read(run/'PLAN.json')['config']));cfg=native._config(dict(config=dict(image_service=cfg,**{k:cfg[k] for k in ('gpu_lock_root','protected_pause_path')})),cfg)
    nr=native_run(run,sid);native._target(nr,cfg);shot=core.handoff_snapshot(value['source_case'],cfg)[2]['shots'][0]
    timing=native._timing(shot);scope=native.PREFIX+'/'+nr.name+'/'+sid
    mapping=[dict(r,input_name=scope+'/references/P'+str(i+1)+'.png') for i,r in enumerate(value['references'])]
    graph=build_graph(read(cfg['base_workflow']),shot,value,mapping,scope)
    row=dict(id=sid,binding_sha256=shot['binding_sha256'],first_frame=value['first_image'],graph_sha256=core.digest(graph),
        scope=scope,input_name=mapping[5]['input_name'],timing=timing,full_asset_input=checked['proof'],reference_map=mapping)
    plan=dict(schema=SCHEMA,upstream_contract=CONTRACT,series_plan=bind(run/'PLAN.json'),config=cfg,input=ib,source=value['source_case'],
        shots=[row],base_workflow=bind(cfg['base_workflow']),protected_pause=bind(cfg['protected_pause_path']),
        code=[bind(x) for x in (__file__,source_renderer.__file__,native.__file__,core.__file__,*code_files,*CAPABILITY_FILES)],
        publication=False,production_approved=False,old_batch_resume=False,full_video_quality_passed=False,conditioning_mode=CONDITIONING)
    nr.mkdir(parents=True,exist_ok=True)
    with native.jobs.run_lock(nr):
        freeze(nr/'PLAN.json',plan)
        for ref in mapping:native.jobs.stage_input({k:cfg[k] for k in ('service_url','input_root','output_root','timeout')},ref['image']['path'],ref['input_name'],ref['image']['sha256'])
        freeze(nr/'shots'/sid/'workflow_api.json',graph)
        state=nr/'shots'/sid/'STATE.json'
        if not state.exists():native.write(state,dict(id=sid,status='prepared',prompt_id=None,plan_sha256=core.digest(plan)))
    freeze(p/'LAUNCH_REQUEST_VIDEO.json',launch_request(run,sid));return status(run,sid)



def _load(run,sid,current=True):
    if sid not in NEW:raise ValueError('only_two_new_continuations_allowed')
    nr=native_run(run,sid);plan=read(nr/'PLAN.json');row=plan['shots'][0];graph=read(nr/'shots'/sid/'workflow_api.json')
    if (plan.get('schema')!=SCHEMA or plan.get('upstream_contract')!=CONTRACT or plan.get('old_batch_resume') is not False
            or plan.get('publication') is not False or plan.get('production_approved') is not False or row['id']!=sid):raise ValueError('explicit_full_asset_contract_required')
    validate_graph(graph,row['scope'],row['reference_map'])
    if core.digest(graph)!=row['graph_sha256']:raise ValueError('frozen_full_asset_graph_changed')
    if current:
        v=validate_input(plan['input'])
        for x in (plan['series_plan'],plan['base_workflow'],*plan['code']):core.check(x)
        series=read(core.check(plan['series_plan']))
        for x in (series['config'],series['authority'],series['asset_manifest'],series['asset_observation'],*[s['source_case'] for s in series['sources']],*[s['imported'] for s in series['prefix']]):core.check(x)
        if plan.get('conditioning_mode')!=CONDITIONING:raise ValueError('explicit_Ref2VA_conditioning_contract_required')
        shot=core.handoff_snapshot(v['source_case'],plan['config'])[2]['shots'][0]
        expected=build_graph(read(core.check(plan['base_workflow'])),shot,v,row['reference_map'],row['scope'])
        if graph!=expected or row['full_asset_input']!=v['proof'] or row['first_frame']!=v['first_image']:raise ValueError('full_asset_current_source_profile_or_seed_changed')
        for ref,actual in zip(row['reference_map'],v['references']):
            if {k:ref[k] for k in actual}!=actual:raise ValueError('frozen_full_asset_reference_map_changed')
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
        for ref in row['reference_map']:
            if native.file_sha(native.bound(cfg['input_root'],ref['input_name']))!=ref['image']['sha256']:raise ValueError('actual_staged_reference_pixels_changed')
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
                input=p['input'],full_asset_input=row['full_asset_input'],native_records=dict(plan=bind(nr/'PLAN.json'),
                request=bind(folder/'REQUEST.json'),history=bind(folder/'HISTORY.json')),production_approved=False)
            freeze(nr/'FULL_ASSET_RESULT.json',receipt)
            freeze(part(run,sid)/'FINAL_RESULT.json',dict(native_result=bind(folder/'RESULT.json'),
                file={k:r['files']['video'][k] for k in ('path','sha256')},prompt_id=pid,postprocessing=[],
                full_asset_receipt=bind(nr/'FULL_ASSET_RESULT.json'),production_approved=False));_ledger(run,sid,pid,'SAVED')
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
        inputs=dict(plan=bind(run/'PLAN.json'),segments=rows);digest=core.digest(inputs);final=run/'FINAL_RESULT.json';out=run/'H3_FULL_ASSET_CONTINUATION_MINUTE_736x1312.mp4'
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
