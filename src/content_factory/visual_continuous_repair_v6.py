"""Bounded source-physical-state successor repairs; original native drafts survive."""
from copy import deepcopy
import json
from pathlib import Path
import re

from jsonschema import validate
from . import visual_continuous_stage_v6 as stage

VERSION='source_physical_state_successor/v1'
POSES={'lying':r'躺|仰卧|平躺|\blies\b|\blying\b','kneeling':r'跪坐|跪倒|跪在|\bkneels?\b','sitting':r'坐在|坐到|坐起|\bsits?\b',
    'standing':r'站起|站在|站着|站定|\bstands?\b','running':r'狂奔|跑出|跑向|\bruns?\b','walking':r'走回|走向|走过去|\bwalks?\b'}
EXPRESSIONS=['neutral','pensive','tense','afraid','pained','startled','caring','guarded','relieved']
POSE_ZH=dict(lying='躺在原有床铺上',kneeling='跪坐在当前源文位置',sitting='坐在原有床沿',standing='站立在当前源文位置',running='朝原文离开方向跑动',walking='沿原文方向行走')
EXPR_ZH=dict(neutral='神情自然',pensive='神情沉思',tense='神情紧张',afraid='神情害怕',pained='神情忍痛',startled='神情惊讶',caring='神情关切',guarded='神情戒备',relieved='神情稍缓')


def _guard(run):
    run=Path(run).resolve()
    if run.parent.name!='visual_continuous_stage_repairs_v6' or not re.fullmatch(stage.legacy.SLUG,run.name):raise stage.StageBlocked('new_successor_repair_namespace_required')
    return run


def physical_ledger(plan,segment_id):
    text,data,cast,_=stage.legacy._source_data(plan['source']['path'],plan['coverage']['path'],plan['cast_root'])
    scenes,_=stage.legacy._scene_materials(data,text);scene_map={s['id']:s for s in scenes};names={c['id']:c['name'] for c in cast['characters']}
    current_scene=None;poses={};injuries={};history=[]
    def update(record):
        value=record['text']
        for cid,name in names.items():
            position=value.find(name)
            if position<0:continue
            chunk=value[position+len(name):];ends=[chunk.find(other) for other in names.values() if other!=name and other in chunk]
            if ends:chunk=chunk[:min(ends)]
            injury_chunk=re.split(r'[。；\n]',chunk)[0][:90]
            chunk=re.split(r'[，,。；\n]',chunk)[0][:60]
            if '或' not in chunk:
                matches=[(m.start(),pose) for pose,pattern in POSES.items() for m in re.finditer(pattern,chunk)]
                if matches:
                    pose='kneeling' if re.search(POSES['kneeling'],chunk) else min(matches)[1]
                    # A completed approach establishes an upright posture for
                    # subsequent holds; it does not make future windows walk forever.
                    poses[cid]=dict(pose='standing' if pose=='walking' else pose,source_id=record['id'],text=value)
            patient=re.search(r'扶住|掀起|抱住|查看',value[max(0,position-3):position])
            indirect=re.search(r'弟弟|妹妹|哥哥|姐姐|他身|她身|擦拭|点在|蘸',injury_chunk)
            if re.search(r'青紫|肿胀|伤口|伤痕|身上的伤',injury_chunk) and (patient or not indirect):
                injuries.setdefault(cid,[]).append(record['id'])
    for segment in data['segments']:
        scene=scene_map[segment['scene']]
        if current_scene!=scene['id']:
            poses={};injuries={};history=[];current_scene=scene['id']
            for record in scene['initial_metadata']:update(record)
        records=[]
        for unit in segment['units']:
            parts=[]
            for part in scene['physical_actions']:
                a=max(part['start'],unit['start']);b=min(part['end'],unit['end'])
                if a<b:parts.append(text[a:b])
            value=''.join(parts).strip()
            if value:records.append(dict(id=unit['id'],text=value))
        start_poses=deepcopy(poses)
        for record in records:update(record)
        if segment['id']==segment_id:
            return dict(scene_id=scene['id'],initial_metadata=scene['initial_metadata'],source_current_physical_state=poses,
                start_physical_state=start_poses,visible_injury_source_ids=injuries,current_physical_records=records,
                physical_history=history[-30:],pure_voice_window=not records,names=names)
        history.extend(records)
    raise stage.StageBlocked('unknown_repair_window')


def _compile(candidate,names):
    parts=['采用已有'+candidate['place_view']+'机位，保持当前住所既定布局、材质和原有陈设，中近景连续呈现。']
    for actor in candidate['actors']:
        text=names[actor['id']]+' '+POSE_ZH[actor['pose']]+'，'+EXPR_ZH[actor['expression']]+'。'+actor['action']
        if actor['visible_injury']=='none':text+='面部和身体沿用该人物已审核的正常造型。'
        else:text+='保留当前原文已呈现的身体青紫伤处。'
        parts.append(text)
    return ''.join(parts)


def _schema(shot,ledger,previous_poses):
    names=ledger['names'];actors=[]
    for cid in shot['visible_cast']:
        known=ledger['source_current_physical_state'].get(cid)
        current_posture_action=(any(a['speaker']==cid and a['mode']=='onscreen' for a in shot['audio']) and
            any(re.search(pattern,r['text']) for pattern in POSES.values() for r in ledger['current_physical_records']))
        if known is None and not current_posture_action:known=previous_poses.get(cid)
        pose_schema=dict(const=known['pose']) if known else dict(enum=list(POSES))
        injured=bool(ledger['visible_injury_source_ids'].get(cid))
        actors.append(stage.legacy.obj(dict(id=dict(const=cid),pose=pose_schema,
            expression=dict(enum=EXPRESSIONS),action=dict(type='string',minLength=1,maxLength=650),
            visible_injury=dict(const='source_body_bruises' if injured else 'none'))))
    return stage.legacy.obj(dict(id=dict(const=shot['id']),place_view=dict(enum=['front','reverse','side']),
        actors=dict(type='array',minItems=len(actors),maxItems=len(actors),items=dict(oneOf=actors)),
        source_ids=dict(type='array',minItems=1,uniqueItems=True,items=dict(enum=shot['source_unit_ids']))))


def _check(candidate,shot,ledger,required_actions=None):
    if {a['id'] for a in candidate['actors']}!=set(shot['visible_cast']):raise stage.StageBlocked('repair_actor_coverage_changed')
    text=''.join(a['action'] for a in candidate['actors'])
    for cid,name in ledger['names'].items():
        if cid not in shot['visible_cast'] and name in text:raise stage.StageBlocked('free_action_mentions_nonvisible_actor:'+cid)
    for actor in candidate['actors']:
        if actor['visible_injury']=='none' and re.search(r'青紫|肿胀|伤眼|眼伤|失明|独眼|受伤的眼|眼周.*伤',actor['action']):
            patients=[a for a in candidate['actors'] if a['id']!=actor['id'] and a['visible_injury']=='source_body_bruises']
            caring_for_patient=(not re.search(r'眼|自己的|自身',actor['action']) and re.search(r'扶|擦|棉签|护理|碘酒',actor['action']) and
                any(ledger['names'][p['id']] in actor['action'] for p in patients))
            if not caring_for_patient:raise stage.StageBlocked('unfounded_current_visible_injury:'+actor['id'])
        if ledger['pure_voice_window'] and re.search(r'躺回|坐起|站起|倒下|跑出|走回|狂奔|跪倒',actor['action']):
            raise stage.StageBlocked('pure_voice_changes_physical_pose')
    for required in required_actions or []:
        actor=next(a for a in candidate['actors'] if a['id']==required['actor_id'])
        if actor['pose']!=required['pose'] and not re.search(POSES[required['pose']],actor['action']):
            raise stage.StageBlocked('required_current_source_pose_missing:'+required['actor_id'])


def repair(run,base_packet_path,issues,*,user_statement,client=None,required_actions=None):
    run=_guard(run);base_packet_path=Path(base_packet_path).resolve();base=stage.files.read(base_packet_path);stage.validate_packet(base)
    original_plan=stage.files.read(base['stage_plan']['path']);shots={s['id']:s for s in base['shots']}
    if not issues or not set(issues)<=set(shots) or not user_statement:raise stage.StageBlocked('explicit_bounded_repair_scope_required')
    required_actions=required_actions or {}
    _,source_data,source_cast,_=stage.legacy._source_data(original_plan['source']['path'],original_plan['coverage']['path'],original_plan['cast_root'])
    units={u['id']:u for s in source_data['segments'] for u in s['units']};cast_names={c['id']:c['name'] for c in source_cast['characters']}
    for sid,events in required_actions.items():
        if sid not in issues:raise stage.StageBlocked('required_action_outside_repair_scope')
        for event in events:
            unit=units[event['source_id']]
            if event['source_id'] not in shots[sid]['source_unit_ids'] or not re.search(POSES[event['pose']],unit['text']):raise stage.StageBlocked('required_action_not_in_current_source')
            if cast_names[event['actor_id']] not in unit['text'] and not any(a['speaker']==cast_names[event['actor_id']] for a in unit['audio_items']):
                raise stage.StageBlocked('required_action_actor_not_source_bound')
    plan=dict(schema=VERSION,source=base['source'],base_packet=dict(path=str(base_packet_path),sha256=stage.files.file_sha(base_packet_path)),
        issues=issues,required_actions=required_actions,config=original_plan['config'],authorization=user_statement,production_approved=False)
    run.mkdir(parents=True,exist_ok=True);stage.files.freeze(run/'PLAN.json',plan)
    client=client or stage.legacy.PlanningClient(plan['config']);records=[];previous_poses={};previous_scene=None
    for shot in base['shots']:
        if shot['id'] not in issues:continue
        ledger=physical_ledger(original_plan,shot['id'])
        if previous_scene!=ledger['scene_id']:previous_poses={};previous_scene=ledger['scene_id']
        schema=_schema(shot,ledger,previous_poses)
        payload=dict(id=shot['id'],current_source_unit_ids=shot['source_unit_ids'],current_physical_ledger=ledger,
            original_rejected_visual_prompt=shot['visual_prompt'],precise_issues=issues[shot['id']],
            required_current_actions=required_actions.get(shot['id'],[]),last_validated_repair_pose=previous_poses,audio_is_program_preserved=True)
        previous=None;accepted=None
        for attempt in range(2):
            folder=run/'calls'/shot['id']/f'attempt_{attempt:02d}';folder.mkdir(parents=True,exist_ok=True)
            messages=[dict(role='system',content='Repair only this rejected visual staging using current physical source, never change story/audio. Rejected prose is not facts. Narration, thoughts, future events and another person\'s injuries must never become the current actor\'s wounds or pose. Source physical ledger and typed pose/injury constraints are authoritative; previous model prose cannot override them. Pure voice windows retain the last source-confirmed/validated pose and allow small facial/hand reactions only. Output exactly the existing visible actors, no name or presence claim about people outside them. action is concise positive physical action only, without camera instructions, exclusions, audio explanations or extra characters/props. Use enum expression and typed pose/injury fields; do not hide conflicting body states in free action. source_ids use only current source units. JSON_SCHEMA:'+json.dumps(schema,ensure_ascii=False)),dict(role='user',content=json.dumps(dict(materials=payload,previous_failure=previous),ensure_ascii=False))]
            stage.files.freeze(folder/'REQUEST.json',dict(schema=VERSION,messages=messages,response_schema=schema,model=client.binding()))
            if (folder/'NATIVE.json').exists():raw=stage.files.read(folder/'NATIVE.json')
            else:
                if (folder/'CLAIM.json').exists():raise stage.StageBlocked('unknown_successor_call_not_replayed')
                stage.files.freeze(folder/'CLAIM.json',dict(source_packet_sha256=plan['base_packet']['sha256']))
                try:raw=client.call(messages,schema)
                except Exception as error:
                    from .creative_workflow_roles import RoleResponseError
                    native=getattr(error,'response_payload',None);metadata=getattr(error,'response_metadata',{})
                    choices=native.get('choices',[]) if isinstance(native,dict) else []
                    known=isinstance(error,RoleResponseError) and len(choices)==1 and choices[0].get('finish_reason') in ('stop','length') and choices[0]['finish_reason']==metadata.get('finish_reason')
                    stage.files.freeze(folder/'ERROR.json',dict(type=type(error).__name__,message=str(error),completion_known=known,native=native,metadata=metadata))
                    if not known:raise stage.StageBlocked('unknown_successor_call_not_replayed') from error
                    raw=dict(text=choices[0].get('message',{}).get('content') or '',native=native,metadata=metadata,completion_known=True,rejected=True)
                stage.files.freeze(folder/'NATIVE.json',raw)
            if raw.get('completion_known') is not True:raise stage.StageBlocked('unknown_successor_completion')
            try:
                if raw.get('rejected') or raw.get('metadata',{}).get('finish_reason')=='length':raise ValueError('known_truncated_or_rejected_successor')
                text=raw['text'].strip()
                if text.startswith('```json') and text.endswith('```'):text=text[7:-3].strip()
                candidate=json.loads(text);validate(candidate,schema);_check(candidate,shot,ledger,required_actions.get(shot['id']))
            except Exception as error:
                previous=dict(reason=str(error),candidate=raw.get('text'));stage.files.freeze(folder/'VALIDATION_ERROR.json',previous);continue
            stage.files.freeze(folder/'RESULT.json',candidate);accepted=(candidate,folder);break
        if not accepted:raise stage.StageBlocked('known_successor_validation_failed:'+shot['id'])
        candidate,folder=accepted
        records.append(dict(shot_id=shot['id'],original_stage_sha256=stage.fingerprint(shot),structured_state=candidate,
            ledger=ledger,required_actions=required_actions.get(shot['id'],[]),visual_prompt=_compile(candidate,ledger['names']),
            bindings={key:dict(path=str(folder/filename),sha256=stage.files.file_sha(folder/filename)) for key,filename in [('request','REQUEST.json'),('native','NATIVE.json'),('result','RESULT.json')]}))
        for actor in candidate['actors']:previous_poses[actor['id']]=dict(pose=actor['pose'],basis='validated_successor_visual_choice',shot_id=shot['id'])
    result=deepcopy(base);by_id={r['shot_id']:r for r in records}
    for shot in result['shots']:
        if shot['id'] not in by_id:continue
        record=by_id[shot['id']];shot['visual_prompt']=record['visual_prompt'];shot['place_view']=record['structured_state']['place_view']
        shot['semantic_repair_provenance']=dict(original_stage_sha256=record['original_stage_sha256'],successor_bindings=record['bindings'])
    for place in result['places']:
        needed={s['place_view'] for s in result['shots'] if s['place_id']==place['id']}|{'front'}
        place['required_views']=[v for v in ('front','reverse','side') if v in needed]
    stage.files.freeze(run/'REPAIRS.json',records)
    result['semantic_repair_layer']=dict(schema=VERSION,base_packet=plan['base_packet'],plan=dict(path=str(run/'PLAN.json'),sha256=stage.files.file_sha(run/'PLAN.json')),
        records=dict(path=str(run/'REPAIRS.json'),sha256=stage.files.file_sha(run/'REPAIRS.json')))
    validate_repaired_packet(result);stage.files.freeze(run/'REPAIRED_PACKET.json',result);return result


def validate_repaired_packet(value):
    layer=value['semantic_repair_layer'];origin=layer['base_packet']
    if layer['schema']!=VERSION or stage.files.file_sha(origin['path'])!=origin['sha256']:raise stage.StageBlocked('successor_origin_changed')
    base=stage.files.read(origin['path']);stage.validate_packet(base)
    for key in ('plan','records'):
        if stage.files.file_sha(layer[key]['path'])!=layer[key]['sha256']:raise stage.StageBlocked('successor_artifact_changed')
    plan=stage.files.read(layer['plan']['path']);records=stage.files.read(layer['records']['path']);expected=deepcopy(base)
    if {r['shot_id'] for r in records}!=set(plan['issues']):raise stage.StageBlocked('successor_scope_changed')
    by_id={r['shot_id']:r for r in records};old_plan=stage.files.read(base['stage_plan']['path']);previous_poses={};previous_scene=None
    for shot in expected['shots']:
        if shot['id'] not in by_id:continue
        r=by_id[shot['id']]
        if r['original_stage_sha256']!=stage.fingerprint(shot):raise stage.StageBlocked('successor_replaces_other_original')
        for key,binding in r['bindings'].items():
            if stage.files.file_sha(binding['path'])!=binding['sha256']:raise stage.StageBlocked('successor_native_binding_changed')
        native=stage.files.read(r['bindings']['native']['path']);candidate=stage.files.read(r['bindings']['result']['path'])
        if native.get('completion_known') is not True or native.get('metadata',{}).get('finish_reason')=='length':raise stage.StageBlocked('successor_completion_unknown')
        ledger=physical_ledger(old_plan,shot['id'])
        if ledger!=r['ledger']:raise stage.StageBlocked('successor_source_ledger_changed')
        if previous_scene!=ledger['scene_id']:previous_poses={};previous_scene=ledger['scene_id']
        validate(candidate,_schema(shot,ledger,previous_poses))
        native_text=native['text'].strip()
        if native_text.startswith('```json') and native_text.endswith('```'):native_text=native_text[7:-3].strip()
        if json.loads(native_text)!=candidate:raise stage.StageBlocked('successor_result_differs_from_native')
        _check(candidate,shot,ledger,plan.get('required_actions',{}).get(shot['id']))
        if candidate!=r['structured_state'] or _compile(candidate,ledger['names'])!=r['visual_prompt']:raise stage.StageBlocked('successor_compilation_changed')
        shot['visual_prompt']=r['visual_prompt'];shot['place_view']=candidate['place_view'];shot['semantic_repair_provenance']=dict(original_stage_sha256=r['original_stage_sha256'],successor_bindings=r['bindings'])
        for actor in candidate['actors']:previous_poses[actor['id']]=dict(pose=actor['pose'],basis='validated_successor_visual_choice',shot_id=shot['id'])
    for place in expected['places']:
        needed={s['place_view'] for s in expected['shots'] if s['place_id']==place['id']}|{'front'}
        place['required_views']=[v for v in ('front','reverse','side') if v in needed]
    expected['semantic_repair_layer']=layer
    if stage.fingerprint(expected)!=stage.fingerprint(value):raise stage.StageBlocked('successor_changes_outside_declared_windows')
    stage.requirements(value);return True
