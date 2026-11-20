"""Pure-CPU shot actor continuity and explainable reference-angle allocation.

Source-action permissions are an upstream, evidence-bound semantic contract.
This module validates and carries that contract; it never guesses an unknown
pose from a portrait, submits media, or applies an appearance-compatibility gate.
"""
from copy import deepcopy
import json
import math

VERSION='shot_actor_continuity/v1'
CASE='shot_actor_continuity_case/v1'
STATE_PLAN='shot_actor_state_plan/v1'
ANGLE='shot_actor_angle_selection/v1'
STATE_FIELDS=('instance_id','position','posture','gaze','held_items','body_ownership')
CHANGE_FIELDS=set(STATE_FIELDS)-{'instance_id','body_ownership'}
POSTURES={'unknown','seated','standing','kneeling','lying','crouching'}
CLOSE_FRAMINGS={'face_close','hands_close','detail','close','closeup'}
SIDE_ORDER=('left_oblique','right_oblique','left_side','right_side','side')
HAND_PARTS={'hand','hands','wrist','wrists','left_hand','right_hand','left_wrist','right_wrist','fingers','left_fingers','right_fingers','palm','left_palm','right_palm'}
ANGLE_WEIGHTS=dict(speaking_seconds=2.0,closeup_seconds=1.0,hand_action_complexity=3.0)


def _notice(code,**details):return dict(code=code,**details)


def _result(status,notices,**value):
    return dict(schema=VERSION,status=status,notices=notices,production_ready=False,
        model_calls=0,media_calls=0,appearance_compatibility_gate=False,**value)


def _number(value):return isinstance(value,(float,int)) and not isinstance(value,bool) and math.isfinite(value)


def _actors(actors):
    return isinstance(actors,list) and bool(actors) and all(isinstance(c,str) and c for c in actors) and len(actors)==len(set(actors))


def _state_errors(cid,state):
    if not isinstance(state,dict) or any(k not in state for k in STATE_FIELDS):return [_notice('complete_initial_actor_state_required',actor_id=cid)]
    errors=[]
    if not isinstance(state['instance_id'],str) or not state['instance_id']:errors.append(_notice('instance_id_required',actor_id=cid))
    if state['posture'] not in POSTURES:errors.append(_notice('explicit_posture_or_unknown_required',actor_id=cid))
    for key in ('position','gaze'):
        if not isinstance(state[key],(str,dict)) or not state[key]:errors.append(_notice('state_location_or_gaze_required',actor_id=cid,field=key))
    items=state['held_items']
    if not isinstance(items,list) or len({json.dumps(i,sort_keys=True,ensure_ascii=False) for i in items})!=len(items):
        errors.append(_notice('explicit_unique_held_items_required',actor_id=cid))
    ownership=state['body_ownership']
    if not isinstance(ownership,dict) or not ownership:errors.append(_notice('explicit_body_ownership_required',actor_id=cid))
    elif any(owner not in (cid,state['instance_id']) for owner in ownership.values()):
        errors.append(_notice('body_part_cannot_belong_to_another_instance',actor_id=cid))
    return errors


def _permission_map(source_spans,source_actions,actors):
    notices=[];spans={}
    for span in source_spans:
        if not isinstance(span,dict) or not span.get('id') or span['id'] in spans:
            notices.append(_notice('unique_source_span_ids_required'));continue
        spans[span['id']]=span
    permissions={}
    for action in source_actions:
        identity=action.get('source_span_id');cid=action.get('actor_id');key=(identity,cid)
        if (identity not in spans or spans[identity].get('kind')!='action' or cid not in actors
                or key in permissions or not isinstance(action.get('allowed_changes'),list)
                or not set(action['allowed_changes'])<=CHANGE_FIELDS or not isinstance(action.get('body_parts',[]),list)):
            notices.append(_notice('source_action_permission_invalid',source_span_id=identity,actor_id=cid));continue
        permissions[key]=action
    return spans,permissions,notices


def _source_authority(ids,cid,permissions,spans):
    if not isinstance(ids,list) or not ids or len(ids)!=len(set(ids)):return None
    if any(i not in spans or spans[i].get('kind')!='action' or (i,cid) not in permissions for i in ids):return None
    return [permissions[(i,cid)] for i in ids]


def carry_states(actors,camera_beats,audio,source_spans,state_plan):
    """Compute every beat's complete state, including actors outside its frame."""
    if not _actors(actors):return _result('needs_material',[_notice('unique_actor_ids_required')])
    if not isinstance(state_plan,dict) or state_plan.get('schema')!=STATE_PLAN:
        return _result('needs_material',[_notice('structured_state_plan_required')])
    initial=state_plan.get('initial',{})
    if not isinstance(initial,dict) or set(initial)!=set(actors):return _result('needs_material',[_notice('initial_state_must_cover_exact_cast')])
    notices=[]
    for cid in actors:notices+=_state_errors(cid,initial[cid])
    instances=[initial[c].get('instance_id') for c in actors]
    if len(instances)!=len(set(instances)):notices.append(_notice('one_unique_instance_per_actor_required'))
    if notices:return _result('needs_state_repair',notices)
    rows=state_plan.get('beats')
    if (not isinstance(camera_beats,list) or not camera_beats or not isinstance(rows,list)
            or len(rows)!=len(camera_beats) or [r.get('beat_index') for r in rows]!=list(range(len(camera_beats)))):
        return _result('needs_material',[_notice('one_ordered_state_row_per_camera_beat_required')])
    duration=camera_beats[-1].get('end')
    if not isinstance(audio,list) or not _number(duration):return _result('needs_material',[_notice('bounded_audio_list_required')])
    for item in audio:
        if (not isinstance(item,dict) or not _number(item.get('start')) or not _number(item.get('end'))
                or not 0<=item['start']<item['end']<=duration
                or item.get('mode') in ('onscreen','dialogue','inner_voice','offscreen_dialogue') and item.get('speaker') not in actors):
            return _result('needs_material',[_notice('bounded_known_speaker_audio_required')])
    spans,permissions,notices=_permission_map(source_spans,state_plan.get('source_actions',[]),actors)
    if notices:return _result('needs_material',notices)
    current=deepcopy(initial);computed=[];adjusted=[];previous_end=0.0
    for index,(original,row) in enumerate(zip(camera_beats,rows)):
        beat=deepcopy(original);start,end=beat.get('start'),beat.get('end')
        if (not _number(start) or not _number(end) or start!=previous_end or end<=start
                or type(beat.get('cut')) is not bool or index==0 and beat['cut'] or not isinstance(beat.get('actors'),dict)):
            notices.append(_notice('ordered_bounded_camera_beat_required',beat_index=index));break
        previous_end=end
        if not set(beat['actors'])<=set(actors):
            notices.append(_notice('extra_actor_or_entity_in_camera',beat_index=index,actor_ids=sorted(set(beat['actors'])-set(actors))));continue
        for cid,visual in beat['actors'].items():
            if not isinstance(visual,dict) or visual.get('instance_id',current[cid]['instance_id'])!=current[cid]['instance_id']:
                notices.append(_notice('camera_actor_instance_must_match_carried_entity',beat_index=index,actor_id=cid))
        before=deepcopy(current);touched=set()
        deltas=row.get('deltas',[])
        if not isinstance(deltas,list):notices.append(_notice('delta_list_required',beat_index=index));continue
        for delta in deltas:
            cid=delta.get('actor_id');changes=delta.get('changes');ids=delta.get('source_span_ids')
            if cid not in current or cid in touched or not isinstance(changes,dict) or not changes:
                notices.append(_notice('one_explicit_delta_per_actor_per_beat_required',beat_index=index,actor_id=cid));continue
            touched.add(cid)
            if not set(changes)<=CHANGE_FIELDS:
                notices.append(_notice('instance_and_body_ownership_are_immutable',beat_index=index,actor_id=cid));continue
            authority=_source_authority(ids,cid,permissions,spans)
            if authority is None:
                notices.append(_notice('state_change_requires_bound_source_action',beat_index=index,actor_id=cid));continue
            allowed=set().union(*(set(p['allowed_changes']) for p in authority))
            if not set(changes)<=allowed:
                notices.append(_notice('source_action_does_not_authorize_changed_field',beat_index=index,actor_id=cid,fields=sorted(set(changes)-allowed)));continue
            # A permission may narrow actual values, e.g. source-authorized
            # standing→seated rather than an arbitrary posture reset.
            invalid=False
            for field,value in changes.items():
                restrictions=[p.get('change_values',{}).get(field) for p in authority if field in p.get('change_values',{})]
                if restrictions and not any(isinstance(values,list) and value in values for values in restrictions):
                    notices.append(_notice('state_delta_value_outside_source_authority',beat_index=index,actor_id=cid,field=field));invalid=True
            if invalid:continue
            candidate=dict(current[cid],**deepcopy(changes));errors=_state_errors(cid,candidate)
            if errors:notices+=errors;continue
            current[cid]=candidate
        assertions=row.get('asserted_states',{})
        if not isinstance(assertions,dict) or not set(assertions)<=set(actors):
            notices.append(_notice('asserted_states_have_extra_entity',beat_index=index));assertions={}
        for cid,claims in assertions.items():
            if not isinstance(claims,dict):notices.append(_notice('state_assertion_object_required',beat_index=index,actor_id=cid));continue
            for field,value in claims.items():
                if field not in STATE_FIELDS or current[cid].get(field)!=value:
                    notices.append(_notice('asserted_state_does_not_follow_carried_entity',beat_index=index,actor_id=cid,field=field))
        body_actions=row.get('body_actions',[]);adjustments=[]
        if not isinstance(body_actions,list):notices.append(_notice('body_action_list_required',beat_index=index));body_actions=[]
        for action in body_actions:
            performer=action.get('performer_actor_id');owner=action.get('owner_actor_id');part=action.get('body_part');relation=action.get('relation')
            if performer not in actors or owner not in actors or not isinstance(part,str) or not part or relation not in ('self','other'):
                notices.append(_notice('body_action_performer_owner_part_required',beat_index=index));continue
            if relation=='self' and owner!=performer:
                notices.append(_notice('self_body_action_owner_mismatch',beat_index=index,actor_id=performer,owner_actor_id=owner));continue
            if relation=='other' and owner==performer:
                notices.append(_notice('other_body_action_owner_mismatch',beat_index=index,actor_id=performer));continue
            if (action.get('performer_instance_id',current[performer]['instance_id'])!=current[performer]['instance_id']
                    or action.get('owner_instance_id',current[owner]['instance_id'])!=current[owner]['instance_id']):
                notices.append(_notice('body_action_instance_must_match_carried_entity',beat_index=index,actor_id=performer));continue
            authority=_source_authority(action.get('source_span_ids'),performer,permissions,spans)
            if authority is None or not any(part in p.get('body_parts',[]) for p in authority):
                notices.append(_notice('body_action_requires_source_bound_part',beat_index=index,actor_id=performer,body_part=part));continue
            if relation=='other' and not any(owner in p.get('target_actor_ids',[]) for p in authority):
                notices.append(_notice('other_body_target_requires_explicit_source_authority',beat_index=index,actor_id=performer,owner_actor_id=owner));continue
            if action.get('requires_visible_owner',True):
                # The action's source body text and carried actor state are the
                # only pose sources. Portrait poses never enter this function.
                for cid in dict.fromkeys([performer,owner]):
                    if cid not in beat['actors']:
                        beat['actors'][cid]=dict(pose=''.join(spans[i].get('text','') for i in action['source_span_ids']),visible_parts=['face','torso','hands'])
                        adjustments.append(dict(code='source_body_action_actor_added_to_reaction_shot',actor_id=cid))
                if part in HAND_PARTS:
                    for cid in dict.fromkeys([performer,owner]):
                        parts=beat['actors'][cid].setdefault('visible_parts',[])
                        if 'hands' not in parts:parts.append('hands')
                    if beat.get('framing') in ('face_close','close','closeup'):
                        beat['framing']='medium'
                        adjustments.append(dict(code='same_body_face_and_hand_relation_visible',actor_id=owner))
                if len(beat['actors'])>1 and beat.get('framing') in CLOSE_FRAMINGS:
                    beat['framing']='medium';adjustments.append(dict(code='reaction_shot_includes_speaker_and_body_owner'))
        active_speakers={a['speaker'] for a in audio if a.get('mode') in ('onscreen','dialogue') and a.get('speaker') in actors
            and a['start']<end and a['end']>start}
        for speaker in active_speakers:
            if speaker not in beat['actors'] or 'face' not in beat['actors'][speaker].get('visible_parts',[]):
                notices.append(_notice('onscreen_speaker_face_missing_in_speaking_window',beat_index=index,actor_id=speaker))
        computed.append(dict(beat_index=index,start=start,end=end,cut=beat['cut'],before=before,after=deepcopy(current),
            visible_instance_map={c:current[c]['instance_id'] for c in beat['actors']},body_actions=deepcopy(body_actions),camera_adjustments=adjustments))
        adjusted.append(beat)
    if notices:return _result('needs_state_repair',notices,state_plan_result=dict(initial=deepcopy(initial),beats=computed),camera_beats=adjusted)
    return _result('ready',[],state_plan_result=dict(schema=STATE_PLAN,initial=deepcopy(initial),initial_basis=deepcopy(state_plan.get('initial_basis')),beats=computed,final=deepcopy(current)),
        camera_beats=adjusted,free_camera=True,all_actors_in_every_frame_required=False)


def _views(value):
    if isinstance(value,dict):return set(value)
    if isinstance(value,(list,tuple)) and all(isinstance(v,str) for v in value):return set(value)
    return set()


def select_angles(actors,camera_beats,audio,available_views,room_views,guide,*,max_references=9,state_plan=None,previous_selection=None):
    """Reserve mandatory references, then spend remaining slots by current work."""
    if not _actors(actors):return _result('needs_material',[_notice('unique_actor_ids_required')])
    if type(max_references) is not int or max_references<1:return _result('needs_material',[_notice('explicit_reference_budget_required')])
    if not isinstance(room_views,list) or len(room_views)!=2 or len({json.dumps(v,sort_keys=True) for v in room_views})!=2:
        return _result('needs_material',[_notice('two_explicit_room_views_required')])
    if (not isinstance(guide,dict) or guide.get('actual') is not True or not isinstance(guide.get('image'),dict)
            or not guide['image'].get('path') or not guide['image'].get('sha256')):
        return _result('needs_material',[_notice('actual_guide_reference_required')])
    if not isinstance(available_views,dict) or any('front' not in _views(available_views.get(c)) for c in actors):
        return _result('needs_material',[_notice('required_actor_front_missing',actor_id=c) for c in actors if 'front' not in _views(available_views.get(c) if isinstance(available_views,dict) else None)])
    fixed=len(actors)+3
    if fixed>max_references:return _result('needs_material',[_notice('required_fronts_rooms_guide_exceed_reference_budget',required=fixed,capacity=max_references)])
    metrics={c:dict(actor_id=c,speaking_seconds=0.0,closeup_seconds=0.0,hand_action_complexity=0) for c in actors}
    for a in audio:
        if a.get('mode') in ('onscreen','dialogue') and a.get('speaker') in metrics:
            if (not _number(a.get('start')) or not _number(a.get('end')) or a['start']<0 or a['end']<=a['start']
                    or not camera_beats or a['end']>camera_beats[-1]['end']):
                return _result('needs_material',[_notice('bounded_audio_window_required')])
            metrics[a['speaker']]['speaking_seconds']+=a['end']-a['start']
    for beat in camera_beats:
        if not _number(beat.get('start')) or not _number(beat.get('end')) or beat['end']<=beat['start']:
            return _result('needs_material',[_notice('bounded_camera_window_required')])
        if beat.get('framing') in CLOSE_FRAMINGS:
            for c in beat.get('actors',{}):
                if c in metrics:metrics[c]['closeup_seconds']+=beat['end']-beat['start']
    seen=set()
    for row in (state_plan or {}).get('beats',[]):
        for action in row.get('body_actions',[]):
            c=action.get('performer_actor_id');part=action.get('body_part')
            key=(c,action.get('owner_actor_id'),part,action.get('action'),tuple(action.get('source_span_ids',[])))
            if c in metrics and part in HAND_PARTS and key not in seen:
                metrics[c]['hand_action_complexity']+=1;seen.add(key)
    for row in metrics.values():
        row['speaking_seconds']=round(row['speaking_seconds'],6);row['closeup_seconds']=round(row['closeup_seconds'],6)
        row['score']=round(sum(row[k]*weight for k,weight in ANGLE_WEIGHTS.items()),6)
    ranking=sorted(metrics.values(),key=lambda r:(-r['score'],-r['speaking_seconds'],-r['closeup_seconds'],-r['hand_action_complexity'],r['actor_id']))
    remaining=max_references-fixed;selection={c:['front'] for c in actors};notices=[];allocations=[]
    # One useful side per ranked actor before spending any second side. Never
    # silently replace a missing priority actor's requested side with another CID.
    for rank,row in enumerate(ranking[:min(remaining,len(actors))],1):
        cid=row['actor_id'];side=next((v for v in SIDE_ORDER if v in _views(available_views[cid])),None)
        if side is None:notices.append(_notice('priority_actor_side_view_missing',actor_id=cid,score=row['score']))
        else:
            selection[cid].append(side)
            allocations.append(dict(actor_id=cid,view=side,rank=rank,score=row['score'],
                available_side_variants=[v for v in SIDE_ORDER if v in _views(available_views[cid])],
                reason='Current-script weighted speech, closeup and source-bound hand-action priority; first available view in deterministic side preference order.'))
    if notices:return _result('needs_material',notices,ranking=ranking,required_front_actor_ids=list(actors))
    previous=previous_selection.get('actor_views',previous_selection) if isinstance(previous_selection,dict) else None
    return _result('ready',[],angle_selection=dict(schema=ANGLE,actor_views=selection,side_priority=[r['actor_id'] for r in ranking],ranking=ranking,
        weights=deepcopy(ANGLE_WEIGHTS),side_allocations=allocations,tie_break='score_desc,speaking_seconds_desc,closeup_seconds_desc,hand_action_complexity_desc,actor_id_ascending',
        required_front_actor_ids=list(actors),room_views=deepcopy(room_views),guide=deepcopy(guide),
        reference_budget=dict(capacity=max_references,fronts=len(actors),rooms=2,guide=1,sides=sum(len(v)-1 for v in selection.values()),used=fixed+sum(len(v)-1 for v in selection.values())),
        previous_selection_recomputed=previous is not None and previous!=selection,previous_selection_was_authority=False))


def evaluate(case):
    """Validate state carry and choose angles; no filesystem/network/model work."""
    try:
        if not isinstance(case,dict) or case.get('schema')!=CASE:return _result('needs_material',[_notice('explicit_continuity_case_required')])
        state=carry_states(case['actors'],case['camera_beats'],case['audio'],case['source_spans'],case['state_plan'])
        if state['status']!='ready':return state
        angles=select_angles(case['actors'],state['camera_beats'],case['audio'],case['available_views'],case['room_views'],case['guide'],
            max_references=case.get('max_references',9),state_plan=case['state_plan'],previous_selection=case.get('previous_selection'))
        if angles['status']!='ready':return _result('needs_material',angles['notices'],state_plan_result=state['state_plan_result'],camera_beats=state['camera_beats'])
        return _result('ready',[],state_plan_result=state['state_plan_result'],camera_beats=state['camera_beats'],angle_selection=angles['angle_selection'],
            free_camera=True,all_actors_in_every_frame_required=False,state_source='initial_actual_state_plus_bound_action_deltas_not_portrait_pose')
    except (TypeError,KeyError,AttributeError,ValueError,IndexError) as error:
        return _result('needs_material',[_notice('malformed_continuity_input',error_type=type(error).__name__)])


def render_state_beats(evaluation,character_names):
    """Materialize actual per-shot state/ownership into the model prompt.

    Returning only a metadata report is insufficient: callers append this text
    to the newly compiled prompt, while preserving their original dialogue.
    """
    if evaluation.get('status')!='ready' or not evaluation.get('state_plan_result'):
        raise ValueError('ready_continuity_evaluation_required_before_state_render')
    result=evaluation['state_plan_result'];actors=list(result['initial'])
    if not isinstance(character_names,dict) or any(c not in character_names or not character_names[c] for c in actors):
        raise ValueError('every_actor_name_required_for_state_render')
    posture_names=dict(unknown='姿态尚未确认，沿用实际承接状态',seated='坐着',standing='站立',kneeling='屈膝或跪姿',lying='躺着',crouching='蹲着')
    parts=dict(right_wrist='右手腕',left_wrist='左手腕',wrist='手腕',wrists='双手腕',right_hand='右手',left_hand='左手',hand='手',hands='双手')
    def printable(value):return value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,sort_keys=True)
    rendered=[]
    for row in result['beats']:
        lines=[]
        lines.append(f"{row['start']:g}—{row['end']:g}秒的承接状态：")
        visible=row['visible_instance_map']
        for cid,state in row['before'].items():
            shown='镜头内' if cid in visible else '本镜画外，状态承接'
            lines.append(shown+'，'+character_names[cid]+'〔'+state['instance_id']+'〕：位置'+printable(state['position'])+'；'+posture_names[state['posture']]
                +'；视线'+printable(state['gaze'])+'；持物登记'+printable(state['held_items'])+'；身体归属此同一实体。')
        for action in row['body_actions']:
            performer=action['performer_actor_id'];owner=action['owner_actor_id'];part=parts.get(action['body_part'],action['body_part'])
            target='自己这具身体的'+part if action['relation']=='self' else character_names[owner]+'这具身体的'+part
            lines.append(character_names[performer]+'的动作'+str(action.get('action',''))+'作用于'+target+'，对应实体'+row['after'][owner]['instance_id']+'。')
        changes=[]
        for cid,after in row['after'].items():
            delta={k:after[k] for k in STATE_FIELDS if after[k]!=row['before'][cid][k]}
            if delta:changes.append(character_names[cid]+'〔'+after['instance_id']+'〕'+printable(delta))
        lines.append('镜后状态：'+('；'.join(changes)+'；其他实体与字段沿用本镜承接状态。' if changes else '以上同一实体的全部状态继续承接。'))
        rendered.append(dict(beat_index=row['beat_index'],text='\n'.join(lines)))
    return rendered


def render_state_instructions(evaluation,character_names):
    return '以下每镜沿用同一人物实体与动作归属；镜头景别与方向依剧情自由变化。\n'+'\n'.join(r['text'] for r in render_state_beats(evaluation,character_names))
