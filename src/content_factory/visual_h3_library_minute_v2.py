"""Fresh four-part minute with library-bound feature cards and actual guides."""
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
from . import visual_asset_feature_cards_v1 as features
from .visual_spatial_clock_v30 import clock_input
from PIL import Image
import hashlib

SERIES='h3_library_bound_minute_series/v2'
SCHEMA='h3_library_bound_minute_native/v2'
CONTRACT='library_bound_segment_input/v2'
CONDITIONING='Ref2VA_library_refs_and_actual_frame0_guide'
REVIEW='library_segment_state/v2'
MODEL='minimax_h3_ref2va_pruned_int8_convrot.safetensors'
COMFY=Path('D:/IT/AI_vido/ComfyUI')
CAPABILITY_FILES=(COMFY/'comfy_extras/nodes_minimax_h3.py',COMFY/'comfy/model_base.py',COMFY/'comfy/ldm/minimax/model.py')
IDS=('S01','S02','S03','S04')
NEW=IDS
read,bind=native.read,core.binding


def freeze(path,value):
    Path(path).parent.mkdir(parents=True,exist_ok=True);native.freeze(path,value)


def _strings(value):return isinstance(value,list) and bool(value) and all(isinstance(x,str) and x.strip() for x in value)
def part(run,sid):
    if sid not in IDS:raise ValueError('explicit_four_segment_id_required')
    return Path(run)/'segments'/sid
def native_run(run,sid):return Path(run)/'visual_h3_v3'/(Path(run).name+'_'+sid)


def image_binding(value):return {k:value[k] for k in ('path','sha256')}


def library_value(run,entry):
    plan=read(Path(run)/'PLAN.json');sel=read(core.check(plan['library_selection']))
    actors=core.validate_entry(entry)['visible_actors']
    result=features.resolve_segment(plan['library_binding'],actor_ids=actors,place_id=sel['place_id'],
        angle_by_actor=sel['angle_by_actor'],place_views=tuple(sel['place_views']),
        approval_path=core.check(plan['binding_approval']),reference_limit=8)
    if result.get('status')!='ready':return result
    refs=result['references']
    if not refs or len(refs)>8 or len({r['image']['sha256'] for r in refs})!=len(refs):
        raise ValueError('one_to_eight_distinct_fixed_library_images_required')
    for cid in actors:
        selected=[r for r in refs if r.get('actor_id')==cid]
        if not any(r['view']=='front' for r in selected) or len(selected)<2:
            raise ValueError('each_full_clip_actor_needs_front_and_angle')
        if not result['character_descriptions'][cid].get('description','').strip():
            raise ValueError('version_bound_character_description_required')
    if not result['environment_description'].get('description','').strip():
        raise ValueError('version_bound_environment_description_required')
    return result


def missing_notice(run,value):
    payload=dict(schema='library_minute_missing_notice/v2',status='waiting_asset',details=value,
        model_posts=0,publication=False,production_approved=False)
    folder=Path(run)/'notices';freeze(folder/(core.digest(payload)+'.json'),payload)
    native.write(Path(run)/'MISSING_ASSETS.latest.json',payload)
    return payload


def validate_graph(graph,scope,mapping):
    count=len(mapping)
    if not 2<=count<=9:raise ValueError('library_reference_capacity_required')
    expected=dict(native.CLASSES);expected.pop('ref_scene');expected['condition']='MiniMaxH3ReferenceToVideo'
    expected.update({f'ref_{i}':'LoadImage' for i in range(count)});expected['guide_start']='MiniMaxH3AddGuide'
    if set(graph)!=set(expected) or any(graph[n].get('class_type')!=kind for n,kind in expected.items()):
        raise ValueError('exact_library_Ref2VA_graph_required')
    c=graph['condition']['inputs'];slots={f'ref_images.ref_image_{i}':[f'ref_{i}',0] for i in range(count)}
    if (set(c)!=set(slots)|{'clip','vae','prompt','width','height','length','ref_image_size'}
        or any(c[k]!=v for k,v in slots.items()) or c['clip']!=['128',0] or c['vae']!=['119',0]
        or (c['width'],c['height'],c['length'],c['ref_image_size'])!=(736,1312,362,'match')
        or graph['127']['inputs']['unet_name']!=MODEL or graph['124']['inputs']['steps']!=12 or graph['130']['inputs']['fps']!=24):
        raise ValueError('actual_library_refs_videoVAE_and_profile_required')
    for i,r in enumerate(mapping):
        if r['slot']!=i or r['tag']!=f'<Picture {i+1}>' or graph[f'ref_{i}']['inputs']!={'image':r['input_name']}:
            raise ValueError('library_slot_to_actual_image_changed')
    guide=mapping[-1]
    if guide['kind']!='dynamic_guide' or graph['guide_start']['inputs']!=dict(positive=['condition',0],latent=['condition',1],vae=['119',0],image=[f'ref_{count-1}',0],frame_idx=0):
        raise ValueError('actual_dynamic_guide_frame0_required')
    if graph['126']['inputs']!=dict(model=['127',0],conditioning=['guide_start',0]) or graph['125']['inputs']['latent_image']!=['condition',1] or graph['125']['inputs']['guider']!=['126',0]:
        raise ValueError('library_refs_and_guide_must_reach_sampler')
    for role in ('video','audio','first','last'):
        if graph['save_'+role]['inputs']['filename_prefix']!=scope+'/'+role:raise ValueError('new_native_output_scope_required')
    if graph['pick_first']['inputs']['batch_index']!=0 or graph['pick_last']['inputs']['batch_index']!=361:
        raise ValueError('actual_native_endpoint_indices_required')


def build_graph(base,shot,value,mapping,scope):
    graph=deepcopy(base);graph.pop('ref_scene');count=len(mapping)
    graph['127']['inputs']['unet_name']=MODEL
    refs={f'ref_images.ref_image_{i}':[f'ref_{i}',0] for i in range(count)}
    graph['condition']=dict(class_type='MiniMaxH3ReferenceToVideo',inputs=dict(clip=['128',0],vae=['119',0],
        prompt=value['compiled_prompt'],width=736,height=1312,length=362,ref_image_size='match',**refs))
    for i,ref in enumerate(mapping):graph[f'ref_{i}']=dict(class_type='LoadImage',inputs=dict(image=ref['input_name']))
    graph['guide_start']=dict(class_type='MiniMaxH3AddGuide',inputs=dict(positive=['condition',0],latent=['condition',1],vae=['119',0],image=[f'ref_{count-1}',0],frame_idx=0))
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
    run=Path(run).resolve();run.mkdir(parents=True,exist_ok=True)
    if set(spec['sources'])!=set(IDS) or 'prefix_results' in spec:raise ValueError('four_fresh_sources_no_imports_required')
    selection=spec['library_selection']
    if set(selection['angle_by_actor'])!={'su_mo','ye_nan','ye_xijue'} or not selection.get('place_id') or not selection.get('place_views'):
        raise ValueError('explicit_library_selection_required')
    try:
        for b in (spec['library_binding'],spec['binding_approval']):core.check(b)
    except (OSError,ValueError) as error:
        return missing_notice(run,dict(code='library_binding_missing_or_changed',reason=str(error)))
    # Missing assets are reported before freezing a plan with unusable bindings.
    for sid in IDS:
        e=core._entries(spec['sources'][sid])[0]
        value=features.resolve_segment(spec['library_binding'],actor_ids=core.validate_entry(e)['visible_actors'],
            place_id=selection['place_id'],angle_by_actor=selection['angle_by_actor'],place_views=tuple(selection['place_views']),
            approval_path=core.check(spec['binding_approval']),reference_limit=8)
        if value.get('status')!='ready':return missing_notice(run,dict(shot_id=sid,library_notice=value))
    cfg=deepcopy(spec['config']);cfg['runs_root']=str(run/'visual_h3_v3')
    freeze(run/'H3_CONFIG.json',cfg);freeze(run/'USER_AUTHORIZATION.json',spec['authorization'])
    freeze(run/'LIBRARY_SELECTION.json',selection);sources=[]
    for sid in IDS:
        entries=core._entries(spec['sources'][sid])
        if len(entries)!=1 or entries[0]['shot_id']!=sid or 'reanchor' in entries[0]:raise ValueError('original_single_source_required')
        core.validate_entry(entries[0]);freeze(part(run,sid)/'SOURCE_CASE.json',dict(schema=core.SCHEMA,shots=entries))
        sources.append(dict(shot_id=sid,source_case=bind(part(run,sid)/'SOURCE_CASE.json'),native_run=str(native_run(run,sid))))
    p=dict(schema=SERIES,sources=sources,config=bind(run/'H3_CONFIG.json'),authority=bind(run/'USER_AUTHORIZATION.json'),
        frames_per_segment=362,expected_frames=1448,width=736,height=1312,fps=24,steps=12,new_video_submissions=4,
        all_segments_new=True,library_binding=spec['library_binding'],binding_approval=spec['binding_approval'],
        library_selection=bind(run/'LIBRARY_SELECTION.json'),publication=False,production_approved=False)
    freeze(run/'PLAN.json',p)
    # Validate library scope before any image or video dispatch; later guides are not invented.
    for sid in IDS:
        value=library_value(run,core._entries(bind(part(run,sid)/'SOURCE_CASE.json'))[0])
        if value.get('status')!='ready':return missing_notice(run,value)
    return dict(status='source_prepared_no_post',plan=bind(run/'PLAN.json'),model_posts=0)


def _predecessor(run,sid):
    if sid not in IDS:raise ValueError('four_fresh_segment_id_required')
    if sid=='S01':return None
    prev=IDS[IDS.index(sid)-1];path=native_run(run,prev)/'shots'/prev/'RESULT.json'
    if not path.exists():return None
    p=read(native_run(run,prev)/'PLAN.json')
    if p.get('schema')!=SCHEMA or p.get('series_plan')!=bind(Path(run)/'PLAN.json'):
        raise ValueError('current_run_predecessor_required')
    return bind(path)


def initial_guide(run):
    path=Path(run)/'INITIAL_GUIDE.json'
    if not path.exists():return None
    v=read(path)
    if v.get('schema')!='library_initial_guide/v2' or v.get('completion_known') is not True or v.get('outcome_unknown') is not False:
        raise ValueError('actually_completed_initial_guide_required')
    core.check(v['image'])
    if set(v['generation_records'])!={'plan','request','history','result'}:raise ValueError('initial_native_records_required')
    for b in v['generation_records'].values():core.check(b)
    request=read(core.check(v['generation_records']['request']));history=read(core.check(v['generation_records']['history']))
    pid=v['native_prompt_id'];event=history.get(pid,{});hp=event.get('prompt',[])
    if (not isinstance(pid,str) or len(hp)<3 or hp[1]!=pid or request.get('prompt')!=hp[2]
        or event.get('status',{}).get('completed') is not True or event['status'].get('status_str')!='success'):
        raise ValueError('initial_guide_native_success_graph_required')
    if v.get('source_image'):core.check(v['source_image'])
    output=v.get('native_output',{});node=output.get('node_id');index=output.get('index')
    if not isinstance(node,str) or type(index) is not int or index<0:raise ValueError('initial_native_output_locator_required')
    outputs=event.get('outputs',{}).get(node,{}).get('images',[])
    if index>=len(outputs):raise ValueError('initial_native_saved_image_required')
    record=outputs[index]
    if record.get('type')!='output':raise ValueError('initial_native_output_type_required')
    cfg=read(core.check(read(Path(run)/'PLAN.json')['config']))
    source=native.bound(cfg['output_root'],(Path(record.get('subfolder',''))/record.get('filename','')).as_posix())
    if source!=Path(output['source_path']).resolve() or Path(run).name not in source.relative_to(Path(cfg['output_root']).resolve()).parts:
        raise ValueError('initial_output_must_belong_to_this_new_run')
    if bind(source)['sha256']!=v['image']['sha256'] or v.get('source_image')!=bind(source):
        raise ValueError('initial_guide_pixels_not_native_output')
    result=read(core.check(v['generation_records']['result']))
    def contains(value):
        if isinstance(value,dict):return any(contains(x) for x in value.values())
        if isinstance(value,list):return any(contains(x) for x in value)
        return value in (v['image']['sha256'],str(source))
    if not contains(result):raise ValueError('initial_guide_result_image_binding_required')
    return v


def review_request(run,sid):
    run=Path(run).resolve();entry=core._entries(bind(part(run,sid)/'SOURCE_CASE.json'))[0]
    previous=_predecessor(run,sid)
    if sid=='S01':
        proof=initial_guide(run)
        if proof is None:return dict(status='initial_generated_guide_required',model_posts=0)
        guide=proof['image']
    else:
        if previous is None:return dict(status='upstream_native_tail_required',predecessor_shot_id=IDS[IDS.index(sid)-1],model_posts=0)
        proof=verify_native(previous);guide=proof['last_image']
    req=core.validate_entry(entry)
    value=dict(schema=REVIEW+'_request',shot_id=sid,predecessor_result=previous,guide_image=guide,
        generation_receipt=proof,required_actor_assets=req['visible_actors'],opening_actor_ids=list(entry['camera_beats'][0]['actors']),
        required_review_file=str(part(run,sid)/'GUIDE_STATE_REVIEW.json'),guide_visibility_does_not_filter_required_assets=True)
    freeze(part(run,sid)/'GUIDE_STATE_REQUEST.json',value)
    return dict(status='actual_guide_state_review_required',request=bind(part(run,sid)/'GUIDE_STATE_REQUEST.json'),model_posts=0)



def script_fields(entry,selection):
    req=core.validate_entry(entry);original=core.compile_prompt(entry)['compiled_prompt'];quotes=core.QUOTE.findall(original)
    actions=[dict(start=b['start'],end=b['end'],text=''.join(req['spans'][s]['text'] for s in b['source_span_ids']),source_span_ids=b['source_span_ids']) for b in entry['camera_beats']]
    return dict(characters=req['visible_actors'],time=dict(story_time='原文未明确具体时刻',clip_start_seconds=IDS.index(entry['shot_id'])*362/24,clip_duration_seconds=362/24),
        location=dict(place_id=selection['place_id'],name=selection.get('place_name','苏墨的房间')),actions=actions,
        language=[dict(a,text=quotes[a['quote_index']][1:-1]) for a in entry['audio']],visuals=deepcopy(entry['camera_beats']))


def render(entry,review,library,refs,fields):
    names=entry['character_names'];lines=['真人写实中国家庭短剧，竖屏9:16，普通话与原生同步声音。对白文字仅作发音内容，画面呈现摄影剧情；人物按情节看互动对象，自由切换景别。']
    lines.append('本段时间：'+fields['time']['story_time']+'；地点：'+fields['location']['name']+'。')
    for cid in fields['characters']:
        who=library['character_descriptions'][cid];tags='、'.join(r['tag'] for r in refs if r.get('actor_id')==cid)
        lines.append(names[cid]+'对应'+tags+'中的同一人物。身份与服装特点：'+who['description'])
    room_tags='、'.join(r['tag'] for r in refs if r['kind'] not in ('character','dynamic_guide'))
    lines.append('背景对应'+room_tags+'。'+library['environment_description']['description'])
    lines.append(refs[-1]['tag']+'是当前真实首帧状态参考，姿态、位置、视线与持物依本段状态继续；人物肖像中的制图姿态不作为剧情动作。')
    for cid in review['guide_visible_actor_ids']:
        lines.append(refs[-1]['tag']+'中'+review['screen_identity_map'][cid]+'对应'+names[cid]+'。')
    lines.append('当前真实状态：'+'；'.join(names[c]+':'+review['world_actor_state'][c] for c in fields['characters']))
    lines.append('声音从0秒开始；声线保持苏墨自然中低男声、叶南较稳男童声、叶西决更轻男童声。')
    framing=dict(face_close='头肩近景',hands_close='手部及所持物近景',medium='中景',wide='全景',detail='局部细节镜头')
    emitted=set()
    for beat,action in zip(entry['camera_beats'],fields['actions']):
        cast='、'.join(names[c] for c in beat['actors'])
        lines.append(f"{beat['start']:g}—{beat['end']:g}秒，"+('切到' if beat.get('cut') else '以')+framing[beat['framing']]+'呈现，画面人物为'+cast+'。'+action['text'])
        for i,a in enumerate(fields['language']):
            if i in emitted or not beat['start']<=a['start']<beat['end']:continue
            emitted.add(i);who=names[a['speaker']]
            if a['mode']=='inner_voice':lead=who+'的内心独白，以'+who+'的画外音说';tail='；本人入镜时嘴唇自然闭合，保持当时动作与思考神情。'
            else:lead=who+'本人开口说';tail='，其他人在其台词期间倾听并按剧情反应。'
            lines.append(f"{a['start']:g}—{a['end']:g}秒，"+lead+'：“'+a['text']+'”'+tail)
    if len(emitted)!=len(fields['language']):raise ValueError('every_original_audio_must_be_interwoven_once')
    text='\n'.join(lines)
    if core.QUOTE.findall(text)!=core.QUOTE.findall(core.compile_prompt(entry)['compiled_prompt']):raise ValueError('original_quotes_or_order_changed')
    return text



def input_value(run,sid):
    run=Path(run).resolve();source=bind(part(run,sid)/'SOURCE_CASE.json');entry=core._entries(source)[0]
    lib=library_value(run,entry)
    if lib.get('status')!='ready':return missing_notice(run,lib)
    request=review_request(run,sid)
    if request['status']!='actual_guide_state_review_required':return request
    q=read(core.check(request['request']));path=part(run,sid)/'GUIDE_STATE_REVIEW.json'
    if not path.exists():return request
    review=read(path);visible=review.get('guide_visible_actor_ids',[]);world=review.get('world_actor_state',{});screen=review.get('screen_identity_map',{})
    actors=core.validate_entry(entry)['visible_actors']
    if (review.get('schema')!=REVIEW or review.get('shot_id')!=sid or review.get('predecessor_result')!=q['predecessor_result']
        or review.get('guide_image')!=q['guide_image'] or review.get('completion_known') is not True or review.get('outcome_unknown') is not False
        or not review.get('reviewed_by') or not _strings(review.get('evidence')) or not isinstance(visible,list) or len(visible)!=len(set(visible))
        or not set(visible)<=set(actors) or set(world)!=set(actors) or set(screen)!=set(visible)
        or any(not isinstance(v,str) or not v.strip() for v in [*world.values(),*screen.values()])):
        raise ValueError('actual_guide_visibility_and_world_state_required')
    refs=[]
    for i,ref in enumerate(lib['references']):refs.append(dict(ref,slot=i,tag=f'<Picture {i+1}>'))
    pid=q['generation_receipt'].get('native_prompt_id') if sid=='S01' else q['generation_receipt']['result']['prompt_id']
    refs.append(dict(slot=len(refs),tag=f'<Picture {len(refs)+1}>',kind='dynamic_guide',entity_id='current_scene_state',
        asset_id=('initial:' if sid=='S01' else 'native_tail:')+pid,version=1,view='guide_start',image=q['guide_image']))
    if len(refs)>9:raise ValueError('model_reference_capacity_exceeded_no_truncation')
    p=read(run/'PLAN.json');selection=read(core.check(p['library_selection']));fields=script_fields(entry,selection)
    text=render(entry,review,lib,refs,fields)
    return dict(schema=CONTRACT,shot_id=sid,source_case=source,entry_sha256=core.digest(entry),first_image=q['guide_image'],
        predecessor_result=q['predecessor_result'],generation_receipt=q['generation_receipt'],guide_review=bind(path),
        library_binding=p['library_binding'],binding_approval=p['binding_approval'],library_resolution=lib,references=refs,
        required_actor_assets=actors,guide_visible_actor_ids=visible,world_actor_state=world,script_fields=fields,
        compiled_prompt=text,compiled_prompt_utf8_sha256=core.sha(text),full_video_quality_passed=False,
        production_approved=False,publication=False,conditioning_mode=CONDITIONING)



def validate_input(value):
    path=Path(core.check(value));run=path.parents[2];sid=path.parent.name;data=read(path)
    if path!=part(run,sid)/'LIBRARY_INPUT.json' or input_value(run,sid)!=data:raise ValueError('library_source_description_or_pixels_changed')
    proof={k:deepcopy(data[k]) for k in ('schema','source_case','first_image','predecessor_result','guide_review','library_binding',
        'binding_approval','library_resolution','references','required_actor_assets','guide_visible_actor_ids','world_actor_state','script_fields','compiled_prompt_utf8_sha256')};proof['input']=value
    return dict(data,entry=core._entries(data['source_case'])[0],proof=proof,quality_passed=False)



def prepare_video(run,sid,*,code_files=()):
    run=Path(run).resolve();value=input_value(run,sid)
    if 'status' in value:return value
    p=part(run,sid);freeze(p/'LIBRARY_INPUT.json',value);ib=bind(p/'LIBRARY_INPUT.json');checked=validate_input(ib)
    cfg=read(core.check(read(run/'PLAN.json')['config']));cfg=native._config(dict(config=dict(image_service=cfg,**{k:cfg[k] for k in ('gpu_lock_root','protected_pause_path')})),cfg)
    nr=native_run(run,sid);native._target(nr,cfg);shot=core.handoff_snapshot(value['source_case'],cfg)[2]['shots'][0]
    timing=native._timing(shot);scope=native.PREFIX+'/'+nr.name+'/'+sid
    mapping=[dict(r,input_name=scope+'/references/P'+str(i+1)+'.png') for i,r in enumerate(value['references'])]
    graph=build_graph(read(cfg['base_workflow']),shot,value,mapping,scope)
    row=dict(id=sid,binding_sha256=shot['binding_sha256'],first_frame=value['first_image'],graph_sha256=core.digest(graph),
        scope=scope,input_name=mapping[-1]['input_name'],timing=timing,library_input=checked['proof'],reference_map=mapping)
    plan=dict(schema=SCHEMA,upstream_contract=CONTRACT,series_plan=bind(run/'PLAN.json'),config=cfg,input=ib,source=value['source_case'],
        shots=[row],base_workflow=bind(cfg['base_workflow']),protected_pause=bind(cfg['protected_pause_path']),
        code=[bind(x) for x in (__file__,features.__file__,features.registry.__file__,native.__file__,core.__file__,*code_files,*CAPABILITY_FILES)],
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
    if sid not in NEW:raise ValueError('four_fresh_segment_required')
    nr=native_run(run,sid);plan=read(nr/'PLAN.json');row=plan['shots'][0];graph=read(nr/'shots'/sid/'workflow_api.json')
    if (plan.get('schema')!=SCHEMA or plan.get('upstream_contract')!=CONTRACT or plan.get('old_batch_resume') is not False
            or plan.get('publication') is not False or plan.get('production_approved') is not False or row['id']!=sid):raise ValueError('explicit_full_asset_contract_required')
    validate_graph(graph,row['scope'],row['reference_map'])
    if core.digest(graph)!=row['graph_sha256']:raise ValueError('frozen_full_asset_graph_changed')
    if current:
        v=validate_input(plan['input'])
        for x in (plan['series_plan'],plan['base_workflow'],*plan['code']):core.check(x)
        series=read(core.check(plan['series_plan']))
        for x in (series['config'],series['authority'],series['library_binding'],series['binding_approval'],series['library_selection'],*[s['source_case'] for s in series['sources']]):core.check(x)
        if plan.get('conditioning_mode')!=CONDITIONING:raise ValueError('explicit_Ref2VA_conditioning_contract_required')
        shot=core.handoff_snapshot(v['source_case'],plan['config'])[2]['shots'][0]
        expected=build_graph(read(core.check(plan['base_workflow'])),shot,v,row['reference_map'],row['scope'])
        if graph!=expected or row['library_input']!=v['proof'] or row['first_frame']!=v['first_image']:raise ValueError('full_asset_current_source_profile_or_seed_changed')
        for ref,actual in zip(row['reference_map'],v['references']):
            if {k:ref[k] for k in actual}!=actual:raise ValueError('frozen_full_asset_reference_map_changed')
    return nr,plan,row



def status(run,sid):
    if not (native_run(run,sid)/'PLAN.json').exists():return review_request(run,sid)
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
                input=p['input'],library_input=row['library_input'],native_records=dict(plan=bind(nr/'PLAN.json'),
                request=bind(folder/'REQUEST.json'),history=bind(folder/'HISTORY.json')),production_approved=False)
            freeze(nr/'LIBRARY_RESULT.json',receipt)
            freeze(part(run,sid)/'FINAL_RESULT.json',dict(native_result=bind(folder/'RESULT.json'),
                file={k:r['files']['video'][k] for k in ('path','sha256')},prompt_id=pid,postprocessing=[],
                library_receipt=bind(nr/'LIBRARY_RESULT.json'),production_approved=False));_ledger(run,sid,pid,'SAVED')
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
        if p.get('all_segments_new') is not True or 'prefix' in p:raise ValueError('all_four_fresh_no_imports_required')
        for sid in IDS:
            path=part(run,sid)/'FINAL_RESULT.json';descriptor=read(path);proof=verify_native(descriptor['native_result']);r=proof['result']
            _load(run,sid)
            rows.append(dict(shot_id=sid,native_result=descriptor['native_result'],file={k:r['files']['video'][k] for k in ('path','sha256')},
                prompt_id=r['prompt_id'],kind='new',descriptor=bind(path)))
        if len({r['prompt_id'] for r in rows})!=4 or len({r['file']['sha256'] for r in rows})!=4:raise ValueError('four_distinct_native_originals_required')
        inputs=dict(plan=bind(run/'PLAN.json'),segments=rows);digest=core.digest(inputs);final=run/'FINAL_RESULT.json';out=run/'H3_LIBRARY_BOUND_MINUTE_736x1312.mp4'
        if final.exists():
            v=read(final);core.check(v['file'])
            if v['assembly_inputs_sha256']!=digest:raise ValueError('frozen_assembly_sources_changed')
            return v
        if out.exists():raise ValueError('unreceipted_final_movie_preserved')
        adjustments=[clock_input(r['file']['path'],r['file']['sha256'],frames=362,width=736,height=1312) for r in rows]
        filters=run/'ASSEMBLY_FILTER.txt';command,text=clock.assembly_command([r['file']['path'] for r in rows],filters,out,frames=362)
        filters.write_text(text,encoding='utf-8');freeze(run/'ASSEMBLY_REQUEST.json',dict(inputs=inputs,adjustments=adjustments,command=command,all_segments_new=True,temporal_leading_trim=False))
        result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=1800)
        (run/'ASSEMBLY.stderr.log').write_text(result.stderr,encoding='utf-8');result.check_returncode()
        timing=clock.verify_clock(clock._probe(out,count=True),frames=1448,width=736,height=1312)
        for row in rows:core.check(row['native_result']);core.check(row['file'])
        v=dict(schema=SERIES,file=bind(out),segments=rows,native_ids=[r['prompt_id'] for r in rows],clock=timing,assembly_inputs_sha256=digest,
            all_segments_new=True,production_approved=False,publication=False)
        freeze(final,v);return v
