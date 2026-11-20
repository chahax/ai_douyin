"""Offline-only H3 input compilation: images, approved voices, actor-state carry.

No transport, upload, sampler, ASR, or service operation is exposed here. Draft
graphs are inspectable inputs, never native job plans or a production approval.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

from . import visual_h3_continuity_input_v33 as core
from . import visual_asset_feature_cards_v1 as features
from . import shot_actor_continuity_v1 as continuity
from . import voice_asset_registry_v1 as voices

SCHEMA='h3_asset_flow_spec/v2'
VERSION='h3_asset_flow_offline/v2'
PROFILE=dict(width=736,height=1312,frames=362,fps=24,steps=12)
FORBIDDEN_SPEC_KEYS={'submit','execute','video_enabled','auto_run','service_url','api_key'}
MODEL='minimax_h3_ref2va_pruned_int8_convrot.safetensors'
CLASSES={'119':'VAELoader','120':'VAELoader','121':'VAEDecodeAudio','122':'VAEDecodeTiled',
    '123':'KSamplerSelect','124':'BasicScheduler','125':'SamplerCustomAdvanced','126':'BasicGuider',
    '127':'UNETLoader','128':'CLIPLoader','129':'RandomNoise','130':'CreateVideo',
    'condition':'MiniMaxH3ReferenceToVideo','pick_first':'ImageFromBatch','pick_last':'ImageFromBatch',
    'save_first':'SaveImage','save_last':'SaveImage','save_video':'SaveVideo','save_audio':'SaveAudio',
    'guide_start':'MiniMaxH3AddGuide'}

def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def bind(path):return core.binding(path)
def digest(value):return core.digest(value)

def freeze(path,value):
    path=Path(path);data=(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    if path.exists():
        if path.read_bytes()!=data:raise ValueError('offline_artifact_changed:'+str(path))
    else:
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as handle:handle.write(data)
    return bind(path)

def _bound(value):return read(core.check(value))
def _safe(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}',value):
        raise ValueError('safe_shot_id_required')
    return value

def _notice(code,details=None):
    return dict(schema=VERSION,status='needs_material_or_state',notices=[dict(code=code,details=details)],
        offline_only=True,model_calls=0,ASR_calls=0,staged_files=0,production_dispatch_allowed=False,
        production_ready=False,content_quality_passed=False)

def _equivalent(expected,observed):
    # The existing native protocol's two observed FLOAT casts only. This pure
    # copy avoids importing the live dispatcher and its application loggers.
    if not isinstance(expected,dict) or not isinstance(observed,dict):return False
    normal=deepcopy(observed)
    for node,field,value in [('124','denoise',1),('130','fps',24)]:
        original=expected.get(node,{}).get('inputs',{}).get(field)
        actual=normal.get(node,{}).get('inputs',{}).get(field)
        if type(original) is int and original==value and type(actual) is float and actual==value:
            normal[node]['inputs'][field]=original
    return digest(normal)==digest(expected)

def _library(binding,approval_binding,actors,selection):
    path,index,cards=features._load_index(binding);approval=_bound(approval_binding)
    if (approval.get('schema')!=features.APPROVAL_SCHEMA or approval.get('binding_index')!=bind(path)
            or not approval.get('approved_by') or not approval.get('evidence')
            or set(approval.get('confirmed_entities',[]))!=set(index['characters'])|set(index['places'])
            or approval.get('production_approved') is not False):
        raise ValueError('confirmed_book_asset_binding_required')
    allowed={(a['asset_id'],a['version'],a['sha256']) for a in approval.get('allow_candidate_assets',[])}
    requests=[(c,'character',v) for c in actors for v in selection['actor_views'][c]]
    requests += [(selection['place_id'],'place',v) for v in selection['place_views']]
    if len(requests)>8:raise ValueError('required_images_exceed_capacity_no_truncation')
    refs=[]
    for eid,kind,view in requests:
        category='characters' if kind=='character' else 'places';card=cards[category][eid]
        if view not in card['images']:raise ValueError('required_asset_view_missing:'+eid+':'+view)
        pinned=card['images'][view]
        row,_=features._asset(index['library'],index['book_id'],eid,kind,view,pinned)
        if (row['status']!='reviewed' and not (row['status']=='candidate'
                and (pinned['asset_id'],pinned['version'],pinned['image']['sha256']) in allowed)):
            raise ValueError('unconfirmed_candidate_image:'+eid+':'+view)
        refs.append(dict(entity_id=eid,actor_id=eid if kind=='character' else None,
            feature_card=index[category][eid]['feature_card'],
            **{k:pinned[k] for k in ('kind','view','asset_id','version','design_version','identity_group','image')}))
    if len({r['image']['sha256'] for r in refs})!=len(refs):raise ValueError('distinct_reference_images_required')
    return dict(status='ready',references=refs,character_descriptions={c:cards['characters'][c] for c in actors},
        environment_description=cards['places'][selection['place_id']],binding_index=binding,binding_approval=approval_binding,
        book_id=index['book_id'],production_approved=False)

def verify_guide(value,actors):
    """Authenticate existing local originals and scoped observation, no ffprobe."""
    image=value['image'];core.image(image)
    path=core.check(value['native_result']);result=read(path);folder=path.parent
    if result.get('technical_status')!='technical_saved' or result.get('publication') is not False:
        raise ValueError('completed_original_guide_required')
    state=read(folder/'STATE.json');request=read(folder/'REQUEST.json');history=read(folder/'HISTORY.json')
    native_run=folder.parents[1];plan=read(native_run/'PLAN.json')
    sid=_safe(result['shot_id']);rows=[row for row in plan.get('shots',[]) if row.get('id')==sid]
    if folder!=native_run/'shots'/sid or len(rows)!=1 or set(result.get('files',{}))!={'video','audio','first','last'}:
        raise ValueError('four_complete_originals_in_native_scope_required')
    row=rows[0];graph=read(folder/'workflow_api.json')
    if (digest(graph)!=row.get('graph_sha256') or digest(graph)!=result.get('graph_sha256')
            or not _equivalent(graph,request['prompt'])):
        raise ValueError('guide_result_plan_and_request_graph_required')
    pid=result['prompt_id'];event=history.get(pid,{});prompt=event.get('prompt',[])
    if (state.get('id')!=sid or state.get('plan_sha256')!=digest(plan)
            or state.get('prompt_id')!=pid or state.get('status')!='technical_saved' or len(prompt)<3
            or prompt[1]!=pid or event.get('status',{}).get('completed') is not True
            or event['status'].get('status_str')!='success'
            or not _equivalent(request['prompt'],prompt[2])):
        raise ValueError('original_guide_request_history_identity_required')
    if {k:result['files']['last'][k] for k in ('path','sha256')}!=image:
        raise ValueError('guide_must_be_saved_native_last')
    output_root=Path(plan['config']['output_root']).resolve();scope=(output_root/row['scope']).resolve()
    if not scope.is_relative_to(output_root):raise ValueError('guide_native_output_scope_escaped')
    for role,item in result['files'].items():
        saved_path=core.check({k:item[k] for k in ('path','sha256')})
        source=Path(item['source_path']).resolve()
        outputs=event.get('outputs',{}).get('save_'+role,{}).get('audio' if role=='audio' else 'images',[])
        if (not saved_path.is_relative_to(folder/'artifacts') or source.parent!=scope or len(outputs)!=1
                or outputs[0].get('type')!='output'
                or (output_root/outputs[0].get('subfolder','')/outputs[0]['filename']).resolve()!=source
                or bind(source)['sha256']!=item['sha256']):
            raise ValueError('guide_original_output_history_locator_changed')
    review=value['review'];visible=review.get('guide_visible_actor_ids',[])
    if (review.get('guide_image')!=image or review.get('predecessor_result')!=value['native_result']
            or review.get('completion_known') is not True or review.get('outcome_unknown') is not False
            or not isinstance(review.get('reviewed_by'),str) or not review['reviewed_by'].strip()
            or not isinstance(review.get('evidence'),list) or not review['evidence']
            or any(not isinstance(x,str) or not x.strip() for x in review['evidence'])
            or len(visible)!=len(set(visible)) or not set(visible)<=set(actors)
            or set(review.get('screen_identity_map',{}))!=set(visible)
            or set(review.get('world_actor_state',{}))!=set(actors)
            or any(not isinstance(x,str) or not x.strip() for x in [*review['screen_identity_map'].values(),*review['world_actor_state'].values()])):
        raise ValueError('actual_guide_scoped_state_review_required')
    if (review.get('usable_for_continuation') is not True or review.get('unexpected_actor_ids')!=[]
            or type(review.get('observed_actor_count')) is not int
            or review['observed_actor_count']!=len(visible)):
        raise ValueError('known_extra_actor_or_unusable_guide')
    return dict(image=image,native_result=value['native_result'],native_id=pid,review=review,
        records={k:bind(folder/(k+'.json')) for k in ('REQUEST','HISTORY','STATE','RESULT')},native_plan=bind(native_run/'PLAN.json'),
        appearance_compatibility_gate=False)

def _entry(spec):
    if spec.get('schema')!=SCHEMA or FORBIDDEN_SPEC_KEYS & set(spec):
        raise ValueError('explicit_offline_only_spec_required')
    if spec.get('profile',PROFILE)!=PROFILE:raise ValueError('explicit_supported_native_profile_required')
    rows=core._entries(spec['source_case'])
    if len(rows)!=1:raise ValueError('single_source_shot_per_input_package')
    entry=rows[0];req=core.validate_entry(entry)
    if not req['source_coverage_complete'] or entry['duration']!=15:
        raise ValueError('source_coverage_or_profile_duration_mismatch')
    _safe(entry['shot_id']);actors=req['visible_actors']
    if len(actors)!=len(set(actors)) or set(entry.get('full_clip_actor_ids',actors))!=set(actors):
        raise ValueError('full_clip_cast_must_match_actual_camera_union')
    place=spec['place']
    if place['id']!=entry.get('place_id') or place.get('views')!=['front','side']:
        raise ValueError('source_bound_place_and_two_views_required')
    return entry,req,actors

def _speakers(entry):return list(dict.fromkeys(a['speaker'] for a in entry['audio']))

def _render(entry,req,library,refs,guide,states,voice_resolution,place):
    names=entry['character_names'];actors=sorted(library['character_descriptions'])
    lines=['真人写实中国家庭短剧，竖屏9:16，普通话和原生同步声音。对白引号内是发音内容；其余文字用于画面与表演。人物看互动对象，自由切换景别。',
        '时间：'+place.get('story_time',entry.get('story_time','原文未明'))+'；地点：'+place['name']+'。']
    for cid in actors:
        tags='、'.join(r['tag'] for r in refs if r.get('actor_id')==cid)
        desc=library['character_descriptions'][cid]['description']
        if core.QUOTE.search(desc):raise ValueError('asset_description_contains_dialogue')
        lines.append(names[cid]+'对应'+tags+'中的同一人物。外形与衣着：'+desc)
    lines.append('背景对应'+'、'.join(r['tag'] for r in refs if r['kind']=='place')+'。'+library['environment_description']['description'])
    lines.append(refs[-1]['tag']+'是上一段保存的实际尾帧，当前空间与人物起点按该画面承接；肖像图用于身份参考。')
    for cid in guide['review']['guide_visible_actor_ids']:
        lines.append(refs[-1]['tag']+'中'+guide['review']['screen_identity_map'][cid]+'对应'+names[cid]+'。')
    for voice in voice_resolution['voices']:
        lines.append(names[voice['speaker_id']]+'的音色对应'+voice['tag']+'，用于该角色本段署名台词。')
    by_beat={s['beat_index']:s['text'] for s in continuity.render_state_beats(states,names)}
    framing=dict(face_close='头肩近景',hands_close='手部近景',medium='中景',wide='全景',detail='局部细节')
    emitted=set()
    for i,beat in enumerate(states['camera_beats']):
        lines.append(f"{beat['start']:g}—{beat['end']:g}秒，"+framing[beat['framing']]+'，画面人物：'+'、'.join(names[c] for c in beat['actors'])+'。')
        # Structured carry is authoritative over the legacy pose hints. Source
        # action prose stays exact; old actor.pose is never re-rendered here.
        lines.append(by_beat[i])
        lines.append(''.join(req['spans'][sid]['text'] for sid in beat['source_span_ids']))
        for ai,a in enumerate(entry['audio']):
            if ai in emitted or not beat['start']<=a['start']<beat['end']:continue
            emitted.add(ai);who=names[a['speaker']];text=req['quotes'][a['quote_index']].group()[1:-1]
            if a['mode']=='voiceover':lead=who+'在此动作时窗以画外声叙述'
            elif a['mode']=='inner_voice':lead=who+'以自己的内心画外声说'
            elif a['mode']=='offscreen_dialogue':lead=who+'从画外说'
            else:lead=who+'本人开口说'
            lines.append(f"{a['start']:g}—{a['end']:g}秒，"+lead+'：“'+text+'”')
    text='\n'.join(lines)
    if len(emitted)!=len(entry['audio']) or core.QUOTE.findall(text)!=[req['quotes'][a['quote_index']].group() for a in entry['audio']]:
        raise ValueError('all_exact_source_quotes_once_required')
    return text

def _graph(base_workflow,entry,prompt,refs,voice_resolution,scope):
    graph=deepcopy(base_workflow);graph.pop('ref_scene',None)
    graph['127']['inputs']['unet_name']=MODEL
    graph['condition']=dict(class_type='MiniMaxH3ReferenceToVideo',inputs=dict(
        clip=['128',0],vae=['119',0],prompt=prompt,width=736,height=1312,length=362,ref_image_size='match',
        **{'ref_images.ref_image_'+str(i):['ref_'+str(i),0] for i in range(len(refs))}))
    for i,row in enumerate(refs):graph['ref_'+str(i)]=dict(class_type='LoadImage',inputs=dict(image=row['input_name']))
    graph['guide_start']=dict(class_type='MiniMaxH3AddGuide',inputs=dict(positive=['condition',0],latent=['condition',1],
        vae=['119',0],image=['ref_'+str(len(refs)-1),0],frame_idx=0))
    graph['126']['inputs']=dict(model=['127',0],conditioning=['guide_start',0])
    graph['125']['inputs']['latent_image']=['condition',1]
    graph['129']['inputs']['noise_seed']=int(digest(dict(source=entry['source'],prompt=core.sha(prompt),
        images=[r['image']['sha256'] for r in refs],voices=[v['audio']['sha256'] for v in voice_resolution['voices']]))[:14],16)
    graph['pick_first']['inputs']['batch_index']=0;graph['pick_last']['inputs']['batch_index']=361
    for role in ('video','audio','first','last'):graph['save_'+role]['inputs']['filename_prefix']=scope+'/'+role
    for voice in voice_resolution['voices']:
        i=voice['slot'];node='voice_'+str(i)
        graph[node]=dict(class_type='LoadAudio',inputs=dict(audio=voice['input_name']))
        graph['condition']['inputs']['ref_audios.ref_audio_'+str(i)]=[node,0]
    if voice_resolution['voices']:
        graph['condition']['inputs']['audio_vae']=['120',0]
    return graph

def validate_graph(graph,refs,voice_resolution,scope):
    clean=deepcopy(graph);c=clean['condition']['inputs'];expected=set()
    for voice in voice_resolution['voices']:
        i=voice['slot'];node='voice_'+str(i);key='ref_audios.ref_audio_'+str(i);expected.add(node)
        if (graph.get(node)!=dict(class_type='LoadAudio',inputs=dict(audio=voice['input_name']))
                or c.pop(key,None)!=[node,0]):raise ValueError('voice_slot_or_LoadAudio_path_changed')
        clean.pop(node)
    if voice_resolution['voices']:
        if c.pop('audio_vae',None)!=['120',0]:raise ValueError('audio_waveform_VAE_input_required')
    elif 'audio_vae' in c:raise ValueError('undeclared_audio_conditioning')
    if any(v.get('class_type')=='LoadAudio' for v in clean.values()):raise ValueError('undeclared_audio_reference')
    kinds=dict(CLASSES,**{'ref_'+str(i):'LoadImage' for i in range(len(refs))})
    if set(clean)!=set(kinds) or any(clean[n].get('class_type')!=kind for n,kind in kinds.items()):
        raise ValueError('exact_offline_graph_node_contract_required')
    # Loader class and a connected port alone do not distinguish audio from
    # video latents. Check the bound template's H3 VAE roles without opening
    # any model weights; the real executor must still authenticate its files.
    for node,role in [('119','video'),('120','audio')]:
        name=clean[node]['inputs'].get('vae_name')
        if (not isinstance(name,str) or '\\' in name or name.startswith('/')
                or '..' in PurePosixPath(name).parts
                or not re.fullmatch('minimax_h3_'+role+r'_vae(?:_[a-z0-9]+)*\.safetensors',PurePosixPath(name).name)):
            raise ValueError('h3_'+role+'_vae_loader_role_required')
    if (clean['121']['inputs']!=dict(samples=['125',0],vae=['120',0])
            or clean['122']['inputs'].get('samples')!=['125',0]
            or clean['122']['inputs'].get('vae')!=['119',0]):
        raise ValueError('h3_audio_video_vae_decoder_roles_required')
    expected={f'ref_images.ref_image_{i}':['ref_'+str(i),0] for i in range(len(refs))}
    if (set(c)!=set(expected)|{'clip','vae','prompt','width','height','length','ref_image_size'}
            or any(c[k]!=v for k,v in expected.items()) or c['clip']!=['128',0] or c['vae']!=['119',0]
            or (c['width'],c['height'],c['length'],c['ref_image_size'])!=(736,1312,362,'match')
            or clean['127']['inputs']['unet_name']!=MODEL or clean['124']['inputs']['steps']!=12
            or clean['130']['inputs']['fps']!=24):raise ValueError('image_conditioning_or_native_profile_changed')
    for i,row in enumerate(refs):
        if row['slot']!=i or row['tag']!=f'<Picture {i+1}>' or clean['ref_'+str(i)]['inputs']!={'image':row['input_name']}:
            raise ValueError('physical_image_slot_mapping_changed')
    if (refs[-1]['kind']!='dynamic_guide' or clean['guide_start']['inputs']!=dict(positive=['condition',0],latent=['condition',1],
            vae=['119',0],image=['ref_'+str(len(refs)-1),0],frame_idx=0)
            or clean['126']['inputs']!=dict(model=['127',0],conditioning=['guide_start',0])
            or clean['125']['inputs']['latent_image']!=['condition',1] or clean['125']['inputs']['guider']!=['126',0]):
        raise ValueError('reference_and_actual_guide_must_reach_sampler')
    for role in ('video','audio','first','last'):
        if clean['save_'+role]['inputs']['filename_prefix']!=scope+'/'+role:raise ValueError('output_scope_changed')
    if clean['pick_first']['inputs']['batch_index']!=0 or clean['pick_last']['inputs']['batch_index']!=361:
        raise ValueError('native_endpoint_indices_changed')
    return dict(image_references=len(refs),audio_references=len(voice_resolution['voices']),guide_frame=0,
        audio_vae_input_connected=bool(voice_resolution['voices']),voice_identity_locked=False,
        GPU_inference_performed=False,actual_model_consumption_verified=False)

def compile_spec(spec):
    try:
        entry,req,actors=_entry(spec)
        guide=verify_guide(spec['guide'],actors)
        state_plan=_bound(spec['state_plan'])
        basis=state_plan.get('initial_basis',{})
        if basis!={'guide_image':guide['image'],'native_result':guide['native_result'],'guide_review_sha256':digest(guide['review'])}:
            return _notice('state_initial_guide_binding_required')
        _,index,cards=features._load_index(spec['library_binding'])
        if index['book_id']!=str(spec['voice']['book_id']):return _notice('voice_and_image_book_mismatch')
        state_case=dict(schema='shot_actor_continuity_case/v1',actors=actors,camera_beats=entry['camera_beats'],
            audio=entry['audio'],source_spans=entry['source_spans'],state_plan=state_plan,
            available_views={c:list(cards['characters'][c]['images']) for c in actors},
            room_views=spec['place']['views'],guide=dict(actual=True,image=guide['image'],native_result=guide['native_result']),
            max_references=9)
        state=continuity.evaluate(state_case)
        if state['status']!='ready':return _notice('actor_continuity_or_view_missing',state)
        selected=state['angle_selection'];selection=dict(mode='same_scene',actor_views=selected['actor_views'],
            place_id=spec['place']['id'],place_name=spec['place']['name'],place_views=spec['place']['views'],
            capacity_decision=dict(front_only_actor_ids=[c for c in actors if len(selected['actor_views'][c])==1],
                reason='All actor fronts, two room views and actual guide reserved; current script speech, close-ups and body actions rank remaining angles.'))
        lib=_library(spec['library_binding'],spec['binding_approval'],actors,selection)
        if lib['status']!='ready':return _notice('image_asset_missing',lib)
        voice_cfg=spec['voice']
        vr=voices.resolve_speakers(voice_cfg['library'],book_id=str(voice_cfg['book_id']),speaker_ids=_speakers(entry),
            bindings=voice_cfg.get('bindings',{}),mode=voice_cfg.get('mode','voice_required'))
        if vr['status']!='ready':return _notice('voice_asset_missing_or_capacity',vr)
        scope='offline_h3_asset_v2/'+_safe(entry['shot_id'])
        refs=[dict(row,slot=i,tag=f'<Picture {i+1}>',input_name=scope+'/images/P'+str(i+1)+'.png') for i,row in enumerate(lib['references'])]
        refs.append(dict(slot=len(refs),tag=f'<Picture {len(refs)+1}>',kind='dynamic_guide',entity_id='current_scene_state',
            asset_id='native_tail:'+guide['native_id'],version=1,view='guide_start',image=guide['image'],
            input_name=scope+'/images/P'+str(len(refs)+1)+'.png'))
        if len(refs)>9:raise ValueError('image_capacity_no_truncation')
        vr=deepcopy(vr)
        for voice in vr['voices']:
            voice['input_name']=scope+'/voices/A'+str(voice['slot']+1)+Path(voice['audio']['path']).suffix.lower()
        prompt=_render(entry,req,lib,refs,guide,state,vr,spec['place'])
        graph=_graph(_bound(spec['base_workflow']),entry,prompt,refs,vr,scope)
        routes=validate_graph(graph,refs,vr,scope)
        value=dict(schema=VERSION,status='offline_draft_valid',source_case=spec['source_case'],
            state_plan_binding=spec['state_plan'],guide=guide,library_binding=spec['library_binding'],binding_approval=spec['binding_approval'],
            library_resolution=lib,angle_selection=selected,actor_state=state,voice_resolution=vr,references=refs,
            required_actor_assets=actors,compiled_prompt=prompt,compiled_prompt_utf8_sha256=core.sha(prompt),
            graph_sha256=digest(graph),routes=routes,scope=scope,
            physical_staging_performed=False,model_calls=0,ASR_calls=0,production_ready=False,
            production_dispatch_allowed=False,content_quality_passed=False,voice_identity_locked=False)
        return dict(manifest=value,graph=graph)
    except (OSError,ValueError,KeyError,TypeError) as error:
        return _notice(str(error))

def prepare(spec_path,out):
    spec_path=Path(spec_path).resolve();out=Path(out).resolve()
    if spec_path==out or spec_path.is_relative_to(out):raise ValueError('spec_must_be_outside_new_artifact_folder')
    spec_binding=bind(spec_path);spec=read(spec_path)
    result=compile_spec(spec)
    prior_path=out/'CHECK_RESULT.json'
    if prior_path.exists():
        prior=read(prior_path)
        if prior.get('spec')!=spec_binding or (prior.get('status')=='offline_draft_valid')!=('manifest' in result):
            raise ValueError('changed_offline_inputs_require_new_output_namespace')
        validate(out)
    if 'manifest' not in result:
        if (out/'DRAFT_WORKFLOW.json').exists():raise ValueError('existing_draft_preserved_create_new_output_for_changed_inputs')
        notice=freeze(out/'CHECK_RESULT.json',dict(result,spec=spec_binding))
        return dict(status=result['status'],check=notice,model_calls=0,production_dispatch_allowed=False)
    manifest=freeze(out/'INPUT_MANIFEST.json',dict(result['manifest'],spec=spec_binding))
    graph=freeze(out/'DRAFT_WORKFLOW.json',result['graph'])
    check=freeze(out/'CHECK_RESULT.json',dict(schema=VERSION,status='offline_draft_valid',spec=spec_binding,
        input_manifest=manifest,draft_graph=graph,model_calls=0,ASR_calls=0,physical_staging_performed=False,
        production_dispatch_allowed=False,production_ready=False,content_quality_passed=False))
    return dict(status='offline_draft_valid',input_manifest=manifest,draft_graph=graph,check=check,
        model_calls=0,production_dispatch_allowed=False)

def validate(out):
    out=Path(out).resolve();check=read(out/'CHECK_RESULT.json');spec=_bound(check['spec'])
    result=compile_spec(spec)
    if check['status']!='offline_draft_valid':
        if 'manifest' in result or dict(result,spec=check['spec'])!=check:raise ValueError('offline_notice_or_input_changed')
        return dict(status='notice_verified',model_calls=0,production_dispatch_allowed=False)
    expected_check=dict(schema=VERSION,status='offline_draft_valid',spec=check['spec'],
        input_manifest=bind(out/'INPUT_MANIFEST.json'),draft_graph=bind(out/'DRAFT_WORKFLOW.json'),
        model_calls=0,ASR_calls=0,physical_staging_performed=False,
        production_dispatch_allowed=False,production_ready=False,content_quality_passed=False)
    if check!=expected_check:raise ValueError('offline_check_scope_or_permission_changed')
    m=_bound(check['input_manifest']);g=_bound(check['draft_graph'])
    if 'manifest' not in result or m!=dict(result['manifest'],spec=check['spec']) or g!=result['graph']:
        raise ValueError('offline_inputs_or_compiled_artifact_changed')
    return dict(status='offline_draft_verified',model_calls=0,ASR_calls=0,production_dispatch_allowed=False,
        production_ready=False,content_quality_passed=False)
