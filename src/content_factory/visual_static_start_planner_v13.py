"""Independent MiniMax static-start planning. Never changes dynamic staging/media."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
import time

from jsonschema import validate
from . import visual_continuous_stage_v6 as stage
from . import visual_continuous_repair_v6 as physical

VERSION='static_start_planner/v13'
ASCII_PATTERN=r'^[\x20-\x7E\r\n]+$'
ENGLISH_PATTERN=r'^[^\u3400-\u9FFF]+$'


class StaticBlocked(ValueError):pass


def _guard(run):
    run=Path(run).resolve()
    if run.parent.name!='visual_static_start_plans_v13' or not re.fullmatch(stage.legacy.SLUG,run.name):raise StaticBlocked('new_static_start_namespace_required')
    return run


def prepare(run,production_plan,*,user_statement):
    run=_guard(run);production_plan=Path(production_plan).resolve();production=stage.files.read(production_plan)
    parent=stage.files.read(production['parent']['path']);stage.validate_packet(parent)
    if stage.files.file_sha(production['parent']['path'])!=production['parent']['sha256'] or not user_statement:raise StaticBlocked('source_or_authorization_changed')
    rows=[]
    for row in production['shots']:
        scope=stage.files.read(row['packet']);stage.validate_packet(scope)
        if stage.files.file_sha(row['packet'])!=row['packet_sha256'] or len(scope['shots'])!=1 or scope['shots'][0]['id']!=row['id']:
            raise StaticBlocked('production_scope_changed')
        rows.append(dict(shot_id=row['id'],packet=dict(path=row['packet'],sha256=row['packet_sha256']),packet_sha256=stage.fingerprint(scope),shot_sha256=stage.fingerprint(scope['shots'][0])))
    if not rows or len(rows)>27 or len({r['shot_id'] for r in rows})!=len(rows):raise StaticBlocked('invalid_static_start_scope')
    old=stage.files.read(parent['stage_plan']['path'])
    plan=dict(schema=VERSION,production_plan=dict(path=str(production_plan),sha256=stage.files.file_sha(production_plan)),parent=production['parent'],
        source=parent['source'],shots=rows,config={**old['config'],'reasoning_effort':'medium','max_tokens':6000,'max_stage_attempts':3},
        max_primary_calls=27,max_known_repairs=2,max_calls=29,authorization=user_statement,media_dispatch=False,production_approved=False)
    run.mkdir(parents=True,exist_ok=True);stage.files.freeze(run/'PLAN.json',plan)
    if not (run/'STATE.json').exists():stage.files.write(run/'STATE.json',dict(status='prepared',completed_shots=[],awaiting_first_sample_review=True))
    return status(run)


def status(run):
    run=_guard(run);p=stage.files.read(run/'PLAN.json')
    if p['schema']!=VERSION or (p['max_calls'],p['max_primary_calls'],p['max_known_repairs'])!=(29,27,2) or p['media_dispatch'] is not False:raise StaticBlocked('static_contract_changed')
    for b in [p['parent'],p['source']]+[r['packet'] for r in p['shots']]:
        if stage.files.file_sha(b['path'])!=b['sha256']:raise StaticBlocked('static_input_changed')
    observed_routing_sha=stage.files.file_sha(p['production_plan']['path']);routing_changed=observed_routing_sha!=p['production_plan']['sha256']
    if routing_changed:
        current=stage.files.read(p['production_plan']['path']);parent=stage.files.read(p['parent']['path']);original={s['id']:s for s in parent['shots']}
        if current.get('parent')!=p['parent'] or current.get('source')!=p['source'] or [r['id'] for r in current['shots']]!=[r['shot_id'] for r in p['shots']]:
            raise StaticBlocked('routing_changed_static_source_scope')
        for now,old in zip(current['shots'],p['shots']):
            frames=original[old['shot_id']]['source_native_frames']
            if Path(now['packet']).resolve()!=Path(old['packet']['path']).resolve() or now['packet_sha256']!=old['packet']['sha256']:
                raise StaticBlocked('routing_changed_static_packet')
            if now['source_native_frames']!=frames or abs(now['native_seconds']-frames/24)>1e-8:raise StaticBlocked('routing_changed_source_clock')
        total=sum(s['source_native_frames'] for s in parent['shots'])
        if current.get('fps')!=24 or current.get('source_frame_total')!=total or abs(current.get('source_seconds',-1)-total/24)>1e-8:
            raise StaticBlocked('routing_changed_source_clock')
    count=len(list((run/'calls').glob('*/attempt_*/CLAIM.json')));budget=_extension_budget(run,p)
    return dict(plan=p,state=stage.files.read(run/'STATE.json'),claimed_calls=count,remaining_calls=budget['max_calls']-count,effective_max_calls=budget['max_calls'],media_dispatch=False,
        routing_changed=routing_changed,routing_observation=dict(original_sha256=p['production_plan']['sha256'],observed_sha256=observed_routing_sha,static_source_projection_verified=True))


def _extension_budget(run,p):
    maximum=29;allowed={}
    for path in sorted((Path(run)/'AUTHORIZATIONS').glob('EXTENSION_*.json')):
        value=stage.files.read(path)
        if (value['schema']!='static_known_successor_extension/v13' or value['original_plan_sha256']!=stage.files.file_sha(Path(run)/'PLAN.json')
            or value['prior_max_calls']!=maximum or value['additional_calls']!=len(value['allowed_successors']) or not 1<=value['additional_calls']<=2
            or not value.get('root_authorization') or not set(value['allowed_successors'])<={r['shot_id'] for r in p['shots']}):raise StaticBlocked('invalid_static_budget_extension')
        for sid in value['allowed_successors']:
            if sid in allowed:raise StaticBlocked('duplicate_successor_extension')
            allowed[sid]=dict(path=str(path),sha256=stage.files.file_sha(path))
        maximum+=value['additional_calls']
    return dict(max_calls=maximum,allowed_successors=allowed)


def authorize_extension(run,shot_ids,*,root_authorization):
    run=_guard(run);p=status(run)['plan']
    with stage.jobs.run_lock(run,'PLANNING.lock'):
        if not root_authorization or not shot_ids or len(shot_ids)!=len(set(shot_ids)) or len(shot_ids)>2:raise StaticBlocked('explicit_bounded_extension_required')
        for claim in (run/'calls').glob('*/attempt_*/CLAIM.json'):
            native=claim.parent/'NATIVE.json'
            if not native.exists() or stage.files.read(native).get('completion_known') is not True:raise StaticBlocked('unresolved_call_cannot_be_reallocated')
        budget=_extension_budget(run,p)
        for sid in shot_ids:
            verify_plan(run/'plans'/(sid+'.json'))
            if sid in budget['allowed_successors'] or (run/'calls'/sid/'attempt_01/CLAIM.json').exists():raise StaticBlocked('successor_slot_already_used')
        number=len(list((run/'AUTHORIZATIONS').glob('EXTENSION_*.json')))+1;path=run/'AUTHORIZATIONS'/f'EXTENSION_{number:02d}.json'
        stage.files.freeze(path,dict(schema='static_known_successor_extension/v13',original_plan_sha256=stage.files.file_sha(run/'PLAN.json'),prior_max_calls=budget['max_calls'],
            additional_calls=len(shot_ids),allowed_successors=shot_ids,root_authorization=root_authorization,unknown_calls_reallocated=False))
    return status(run)


def _physical_history(source_text,segments,scene,current_id):
    history=[]
    for earlier in segments:
        if earlier['id']==current_id:break
        if earlier['scene']!=scene['id']:continue
        for unit in earlier['units']:
            for part in scene['physical_actions']:
                a=max(unit['start'],part['start']);b=min(unit['end'],part['end'])
                if a<b:
                    quote=source_text[a:b];history.append(dict(source_id=unit['id'],parent_source_id=unit['parent'],shot_id=earlier['id'],start=a,end=b,text=quote,
                        sha256=hashlib.sha256(quote.encode()).hexdigest(),source_layer='screenplay_current_physical_action'))
    return history


def _materials(row,parent):
    scope=stage.files.read(row['packet']['path']);shot=scope['shots'][0];p=stage.files.read(parent['stage_plan']['path'])
    _,data,cast,_=stage.legacy._source_data(p['source']['path'],p['coverage']['path'],p['cast_root'])
    scenes,_=stage.legacy._scene_materials(data,Path(p['source']['path']).read_text(encoding='utf-8'));scene=next(s for s in scenes if s['id']==shot['scene_id'])
    segment=next(s for s in data['segments'] if s['id']==shot['id']);source_text=Path(p['source']['path']).read_text(encoding='utf-8');records=[]
    for unit in segment['units']:
        pieces=[]
        for part in scene['physical_actions']:
            a=max(unit['start'],part['start']);b=min(unit['end'],part['end'])
            if a<b:pieces.append(source_text[a:b])
        if pieces:records.append(dict(id=unit['id'],text=''.join(pieces)))
    index=next(i for i,s in enumerate(parent['shots']) if s['id']==shot['id']);previous=parent['shots'][index-1] if index else None
    previous_state=None
    if previous:
        ledger=physical.physical_ledger(p,previous['id'])
        previous_state=dict(shot_id=previous['id'],scene_id=previous['scene_id'],confirmed_pose=ledger['source_current_physical_state'],
            dynamic_visual_context_only=previous['visual_prompt'])
    history=_physical_history(source_text,data['segments'],scene,segment['id'])
    characters=[c for c in scope['characters'] if c['id'] in shot['visible_cast']]
    visible_identities=[{k:c[k] for k in ('id','name','age_band','appearance_design') if k in c} for c in characters]
    payload=dict(current_shot=dict(id=shot['id'],visible_cast=shot['visible_cast'],scene_id=shot['scene_id'],
        dynamic_stage_context_only=shot['visual_prompt']),visible_identities=visible_identities,
        current_physical_source=records,initial_source_context=scene['initial_metadata'],previous_end_state_context_only=previous_state,
        source_physical_history_before_current_window=history,
        physical_continuity_rule='Within the same scene, a source-established held item stays with its last holder until a source handoff, set-down or other explicit change. Micro-reactions and an LLM pose summary do not remove the item. This ordered history stops before the current window and contains no future events.',
        room={k:next(p for p in scope['places'] if p['id']==shot['place_id'])[k] for k in ('id','static_materials','spatial_layout')},
        requested_output='One frozen opening instant only, with exactly the already-visible actors; no audio text is supplied.')
    return payload,scope,shot,segment


def start_boundary_materials(materials):
    """Project existing exact evidence into before/start/after temporal roles.

    This does not infer physical facts from vocabulary or rewrite source. The
    caller must resolve a still's pose from the latest explicit *prior* action;
    present-window action paths are events to begin after its first frame.
    """
    value=deepcopy(materials)
    current=value['current_shot']
    model_dynamic=current.pop('dynamic_stage_context_only',None)
    initial=value.pop('initial_source_context',None)
    old_summary=value.pop('previous_end_state_context_only',None)
    pending=value.pop('current_physical_source',[])
    prior=value.pop('source_physical_history_before_current_window',[])
    value['start_boundary']=dict(
        source_actions_already_happened=prior,
        source_actions_to_begin_after_opening_instant=pending,
        scene_initial_fallback_only=initial,
        source_state_precedence=[
            'latest explicit prior physical source action for each actor/state/held item',
            'scene initial metadata only where no later prior source action changes it',
            'earlier model summaries and candidate images are proposals, never authority over source'],
        rule='The opening still precedes the first state-changing action contained in the current window. Carry the last established physical state forward until source changes it. An action written later in this window must happen in the video, not be pre-completed in its opening image. Do not reset opened eyes to closed, standing bodies to earlier lying poses, or held items to an earlier holder merely because initial metadata or a model summary says so.')
    value['model_proposals_not_source_facts']=dict(dynamic_motion_path=model_dynamic,previous_summary=old_summary)
    return value


def response_schema(visible,*,include_camera=False):
    properties=dict(visible_cast=dict(const=visible),depicted_moment=dict(const='start'),
        static_start_prompt=dict(type='string',minLength=30,maxLength=1800,pattern=ENGLISH_PATTERN))
    if include_camera:
        properties['camera_override']=stage.legacy.environment.layout_schema()['properties']['cameras']['properties']['front']
        properties['camera_design_note']=dict(type='string',minLength=10,maxLength=600,pattern=ENGLISH_PATTERN)
    return stage.legacy.obj(properties)


def _english_schema(value):
    if isinstance(value,dict):return {k:(ENGLISH_PATTERN if k=='pattern' and v==ASCII_PATTERN else _english_schema(v)) for k,v in value.items()}
    if isinstance(value,list):return [_english_schema(x) for x in value]
    return value


def _validate_native_schema(candidate,original_schema):
    try:validate(candidate,original_schema);return None
    except Exception:
        revised=_english_schema(original_schema)
        if revised==original_schema:raise
        validate(candidate,revised)
        return dict(schema='english_unicode_punctuation_revalidation/v1',original_schema_sha256=stage.fingerprint(original_schema),
            revised_schema_sha256=stage.fingerprint(revised),native_text_unchanged=True,
            reason='English typographic punctuation is legal; only the ASCII-only restriction was removed.')


def camera_report(scope,shot,candidate):
    from .visual_first_frame_static_v13 import validate_camera
    place=next(p for p in scope['places'] if p['id']==shot['place_id']);layout=deepcopy(place['spatial_layout'])
    camera=validate_camera(layout,candidate['camera_override']);view=shot['place_view'];layout['cameras'][view]=camera
    width,height=184,328
    _,visible=stage.legacy.environment._perspective(layout,view,(width,height),return_visibility=True)
    eye,target=camera['eye'],camera['target'];forward=[t-e for e,t in zip(eye,target)];length=math.sqrt(sum(x*x for x in forward));forward=[x/length for x in forward]
    right=[forward[1],-forward[0],0];length=math.hypot(right[0],right[1]);right=[x/length for x in right]
    up=[right[1]*forward[2],-right[0]*forward[2],right[0]*forward[1]-right[1]*forward[0]]
    focal=(width/2)/math.tan(math.radians(camera['fov']/2));anchors=[]
    for item in layout['objects']:
        if item['kind'] not in ('bed','table'):continue
        projected=[]
        for x,y in stage.legacy.environment._corners(item):
            for z in (item.get('base_z',0),item.get('base_z',0)+item['size'][2]):
                vec=[x-eye[0],y-eye[1],z-eye[2]];depth=sum(a*b for a,b in zip(vec,forward))
                if depth<=.08:continue
                projected.append((width/2+focal*sum(a*b for a,b in zip(vec,right))/depth,height/2-focal*sum(a*b for a,b in zip(vec,up))/depth))
        if projected:
            left=max(0,min(x for x,y in projected));right_edge=min(width,max(x for x,y in projected));top=max(0,min(y for x,y in projected));bottom=min(height,max(y for x,y in projected))
            fraction=max(0,right_edge-left)*max(0,bottom-top)/(width*height)
        else:fraction=0
        anchors.append(dict(id=item['id'],kind=item['kind'],visible_in_cpu_guide=item['id'] in visible,unoccluded_projected_fraction=round(fraction,5)))
    requested={kind for kind in ('bed','table') if re.search(r'\b'+kind+r'\b',candidate['static_start_prompt'],re.I)}
    for kind in requested:
        if not any(a['kind']==kind and a['visible_in_cpu_guide'] and a['unoccluded_projected_fraction']>.002 for a in anchors):
            raise StaticBlocked('required_static_anchor_not_visible:'+kind)
    return dict(schema='static_camera_cpu_check/v13',camera=camera,preview_size=[width,height],anchors=anchors,
        bbox_measure_is_unoccluded=True,subject_body_positions_not_assumed=True,real_image_review_required=True)


def _check(candidate,shot,scope,constraints=None):
    text=candidate['static_start_prompt']
    if re.search(r'\b(?:then|subsequently|afterwards?|later|offscreen|dialogue|voiceover|voice|speaks?|says?|begins? to|starts? to|stands? up|walks?|runs?|jumps?)\b',text,re.I):
        raise StaticBlocked('not_one_static_opening_instant')
    identities={c['id']:c for c in scope['characters']};visible=shot['visible_cast']
    if visible and all(identities[c].get('age_band')=='adult' for c in visible) and re.search(r'\b(?:children|child|boys?|girls?|kids?|teenagers?)\b',text,re.I):
        raise StaticBlocked('nonvisible_child_in_static_prompt')
    if len(visible)==1 and re.search(r'\b(?:two|three|second|another)\s+(?:adult|man|men|person|people|woman|women|body|bodies)\b',text,re.I):
        raise StaticBlocked('duplicate_static_subject')
    if len(visible)==1 and not re.search(r'\b(?:one|single)\b.{0,45}\b(?:man|woman|adult|person|boy|girl|child)\b',text,re.I):
        raise StaticBlocked('explicit_single_static_subject_required')
    if constraints:
        if not constraints.get('word_target_only') and len(re.findall(r"[A-Za-z]+(?:[-'][A-Za-z]+)*",text))>constraints['max_words']:raise StaticBlocked('static_word_budget_exceeded')
        positive_view=text
        states=candidate.get('opening_states')
        if (isinstance(states,list) and any(isinstance(state,dict) and state.get('character_id') in visible
                and state.get('held_items')=='' for state in states)):
            # A source-bound empty hand is a physical state, not an exclusion list.
            # Only the lexical validation view changes; native/result text is immutable.
            positive_view=re.sub(r'\bholds no item\b','has empty hands',positive_view,flags=re.I)
        if constraints.get('positive_only') and re.search(r'\b(?:no|without|not|exclude|excluded)\b',positive_view,re.I):raise StaticBlocked('static_exclusion_list_not_required')
        for term in constraints.get('forbidden_terms',[]):
            if re.search(r'\b'+re.escape(term)+r'\b',text,re.I):raise StaticBlocked('frame_irrelevant_term:'+term)
        for pattern in constraints.get('required_patterns',[]):
            if not re.search(pattern,text,re.I|re.S):raise StaticBlocked('required_static_source_property_missing:'+pattern)
    if candidate.get('camera_override'):camera_report(scope,shot,candidate)


def plan(run,*,shot_ids=None,client=None):
    run=_guard(run);p=status(run)['plan'];rows={r['shot_id']:r for r in p['shots']}
    selected=shot_ids if shot_ids is not None else [p['shots'][0]['shot_id']]
    if not selected or len(selected)!=len(set(selected)) or not set(selected)<=set(rows):raise StaticBlocked('unknown_or_duplicate_static_shot')
    parent=stage.files.read(p['parent']['path']);client=client or stage.legacy.PlanningClient(p['config'])
    with stage.jobs.run_lock(run,'PLANNING.lock'):
        for sid in selected:
            output=run/'plans'/(sid+'.json')
            if output.exists():verify_plan(output,rows[sid]);continue
            payload,scope,shot,segment=_materials(rows[sid],parent);include_camera=sid!=p['shots'][0]['shot_id'];schema=response_schema(shot['visible_cast'],include_camera=include_camera);previous=None
            for attempt in range(3):
                folder=run/'calls'/sid/f'attempt_{attempt:02d}';folder.mkdir(parents=True,exist_ok=True)
                messages=[dict(role='system',content='You are a static first-frame cinematography planner, not a screenwriter or video prompt writer. Freeze only the opening instant of the supplied dynamic shot. Exactly the current visible_cast exists in the image; other names/voices in source or dynamic context are not image subjects. Do not repeat exclusion lists or mention outside-frame people, dialogue or audio. Previous/source context helps determine the starting posture but later actions and future injuries do not belong to this still. Write one concise positive English image prompt: explicit subject count, current visible posture, gaze/eyes, subtle expression, source-consistent clothing, framing and existing room anchors. Preserve the current reviewed identities and clothing; do not invent another copy or standing reference figure. For a resting-bed opening choose head/shoulders/upper-torso framing, excluding feet by the chosen crop; keep a single physical body on the actual existing bed. Do not output camera coordinates; root will bind a separate geometry-reviewed camera. No before/after/then sequence, spoken text, names of invisible actors, added wounds or extra furniture. Output only JSON matching JSON_SCHEMA:'+json.dumps(schema,ensure_ascii=False)),
                    dict(role='user',content=json.dumps(dict(materials=payload,previous_failure=previous),ensure_ascii=False))]
                if include_camera:
                    messages[0]['content']=messages[0]['content'].replace('Do not output camera coordinates; root will bind a separate geometry-reviewed camera.',
                        'In this SAME response choose camera_override eye/target/fov from the supplied actual room geometry. Numeric camera placement is an art choice, not a new novel fact. Match the opening pose and close/medium crop: use the bed/table anchor and actual actor height rather than a default whole-room view. Eye and target must be finite and inside room bounds; eye must be outside furniture cuboids, with nondegenerate forward direction. Keep the source action anchor visible. Give camera_design_note explaining which existing anchor and opening posture it frames. No new geometry or subject-structure schema is needed. Aim for 150 English words in static_start_prompt, but word count is only an editorial target; necessary detail within the 1800-character schema limit is acceptable. Use entirely positive descriptions of what is visible in this crop. Omit exclusion lists, off-crop body/clothing/furniture references, and any instruction for a lamp fixture to appear; ambient illumination is enough.')
                if len(json.dumps(messages,ensure_ascii=False))>p['config']['max_input_chars']:raise StaticBlocked('static_context_budget_exceeded')
                request=dict(schema=VERSION,model=client.binding(),messages=messages,response_schema=schema)
                if (folder/'REQUEST.json').exists():
                    original_request=stage.files.read(folder/'REQUEST.json')
                    if (original_request['model']!=request['model'] or original_request['messages'][1]!=request['messages'][1]
                        or _english_schema(original_request['response_schema'])!=schema):raise StaticBlocked('frozen_static_request_source_changed')
                    request=original_request
                else:stage.files.freeze(folder/'REQUEST.json',request)
                if (folder/'NATIVE.json').exists():raw=stage.files.read(folder/'NATIVE.json')
                else:
                    if (folder/'CLAIM.json').exists():raise StaticBlocked('unknown_static_call_not_replayed:'+sid)
                    claims=list((run/'calls').glob('*/attempt_*/CLAIM.json'))
                    repairs=[f for f in claims if f.parent.name!='attempt_00']
                    if len(claims)>=29 or (attempt and len(repairs)>=2):raise StaticBlocked('static_global_text_budget_exhausted')
                    stage.files.freeze(folder/'CLAIM.json',dict(at=time.time(),request_sha256=stage.fingerprint(request)))
                    try:raw=client.call(messages,schema)
                    except Exception as error:
                        from .creative_workflow_roles import RoleResponseError
                        native=getattr(error,'response_payload',None);metadata=getattr(error,'response_metadata',{})
                        choices=native.get('choices',[]) if isinstance(native,dict) else []
                        known=isinstance(error,RoleResponseError) and len(choices)==1 and choices[0].get('finish_reason') in ('stop','length') and choices[0]['finish_reason']==metadata.get('finish_reason')
                        stage.files.freeze(folder/'ERROR.json',dict(type=type(error).__name__,message=str(error),native=native,metadata=metadata,completion_known=known))
                        if not known:raise StaticBlocked('unknown_static_call_not_replayed:'+sid) from error
                        raw=dict(text=choices[0].get('message',{}).get('content') or '',native=native,metadata=metadata,completion_known=True,rejected=True)
                    stage.files.freeze(folder/'NATIVE.json',raw)
                if raw.get('completion_known') is not True:raise StaticBlocked('unknown_static_completion')
                try:
                    if raw.get('rejected') or raw.get('metadata',{}).get('finish_reason')=='length':raise StaticBlocked('known_static_native_rejection')
                    text=raw['text'].strip()
                    if text.startswith('```json') and text.endswith('```'):text=text[7:-3].strip()
                    candidate=json.loads(text);revalidation=_validate_native_schema(candidate,request['response_schema']);_check(candidate,shot,scope,dict(max_words=220,soft_target_words=150,word_target_only=True,positive_only=True) if include_camera else None)
                except Exception as error:
                    previous=dict(reason=str(error),candidate=raw.get('text'));stage.files.freeze(folder/'VALIDATION_ERROR.json',previous);continue
                stage.files.freeze(folder/'RESULT.json',candidate)
                value=dict(schema='first_frame_static_plan/v13',source=scope['source'],packet_sha256=rows[sid]['packet_sha256'],
                    shots=[dict(shot_id=sid,shot_sha256=rows[sid]['shot_sha256'],visible_cast=shot['visible_cast'],static_start_prompt=candidate['static_start_prompt'])],
                    planning_provenance=dict(schema=VERSION,plan=dict(path=str(run/'PLAN.json'),sha256=stage.files.file_sha(run/'PLAN.json')),
                        packet=rows[sid]['packet'],source_unit_ids=[u['id'] for u in segment['units']],
                        bindings={key:dict(path=str(folder/filename),sha256=stage.files.file_sha(folder/filename)) for key,filename in [('request','REQUEST.json'),('native','NATIVE.json'),('result','RESULT.json')]}),
                    production_approved=False)
                for key in ('camera_override','camera_design_note'):
                    if key in candidate:value['shots'][0][key]=deepcopy(candidate[key])
                if candidate.get('camera_override'):value['planning_provenance']['camera_geometry_review']=camera_report(scope,shot,candidate)
                if include_camera:
                    value['planning_provenance']['acceptance_constraints']=dict(max_words=220,soft_target_words=150,word_target_only=True,positive_only=True)
                    words=len(re.findall(r"[A-Za-z]+(?:[-'][A-Za-z]+)*",candidate['static_start_prompt']))
                    if words>150:
                        note=dict(schema='static_word_target_revalidation/v1',word_target_overrun=True,actual_words=words,soft_target_words=150,word_count_only_warning=True,max_characters=1800,
                            native_text_unchanged=True,original_request_and_failure_preserved=True,classification='noncritical_expression_length')
                        stage.files.freeze(folder/'WORD_TARGET_REVALIDATION.json',note);value['planning_provenance']['word_target_overrun']=note
                if revalidation:
                    stage.files.freeze(folder/'PARSER_REVALIDATION.json',revalidation)
                    value['planning_provenance']['parser_revalidation']=revalidation
                stage.files.freeze(output,value);verify_plan(output,rows[sid]);break
            else:raise StaticBlocked('known_static_validation_failed:'+sid)
        completed=[r['shot_id'] for r in p['shots'] if (run/'plans'/(r['shot_id']+'.json')).exists()]
        stage.files.write(run/'STATE.json',dict(status='static_plans_ready',completed_shots=completed,awaiting_first_sample_review=len(completed)==1))
    return status(run)


def verify_plan(path,row=None):
    value=stage.files.read(path);proof=value['planning_provenance'];p=stage.files.read(proof['plan']['path']);scope=stage.files.read(proof['packet']['path'])
    status(Path(proof['plan']['path']).parent)
    if stage.files.file_sha(proof['plan']['path'])!=proof['plan']['sha256'] or stage.files.file_sha(proof['packet']['path'])!=proof['packet']['sha256']:
        raise StaticBlocked('static_plan_source_binding_changed')
    shot=scope['shots'][0]
    if value['schema']!='first_frame_static_plan/v13' or value['source']!=scope['source'] or value['packet_sha256']!=stage.fingerprint(scope):raise StaticBlocked('static_plan_scope_changed')
    if row and (value['packet_sha256']!=row['packet_sha256'] or stage.fingerprint(shot)!=row['shot_sha256']):raise StaticBlocked('static_plan_wrong_expected_row')
    if len(value['shots'])!=1 or value['shots'][0]['shot_id']!=shot['id'] or value['shots'][0]['shot_sha256']!=stage.fingerprint(shot) or value['shots'][0]['visible_cast']!=shot['visible_cast']:
        raise StaticBlocked('static_plan_shot_changed')
    for binding in proof['bindings'].values():
        if stage.files.file_sha(binding['path'])!=binding['sha256']:raise StaticBlocked('static_native_binding_changed')
    native=stage.files.read(proof['bindings']['native']['path']);result=stage.files.read(proof['bindings']['result']['path'])
    if native.get('completion_known') is not True or native.get('metadata',{}).get('finish_reason')=='length':raise StaticBlocked('static_native_not_completed')
    if result['static_start_prompt']!=value['shots'][0]['static_start_prompt']:raise StaticBlocked('static_prompt_not_native_result')
    if proof.get('parent_static_plan'):
        previous=proof['parent_static_plan']
        if stage.files.file_sha(previous['path'])!=previous['sha256']:raise StaticBlocked('static_successor_parent_changed')
        old=stage.files.read(previous['path'])['shots'][0]
        for key in ('shot_id','shot_sha256','visible_cast','camera_override','camera_design_note'):
            if old.get(key)!=value['shots'][0].get(key):raise StaticBlocked('static_successor_changed_camera_or_source')
    raw_text=native['text'].strip()
    if raw_text.startswith('```json') and raw_text.endswith('```'):raw_text=raw_text[7:-3].strip()
    if json.loads(raw_text)!=result:raise StaticBlocked('static_result_differs_from_native')
    request=stage.files.read(proof['bindings']['request']['path'])
    revalidation=_validate_native_schema(result,request['response_schema'])
    if revalidation!=proof.get('parser_revalidation'):raise StaticBlocked('static_parser_revision_proof_changed')
    _check(result,shot,scope,proof.get('acceptance_constraints'))
    for key in ('camera_override','camera_design_note'):
        if key in result and value['shots'][0].get(key)!=result[key]:raise StaticBlocked('static_camera_differs_from_native')
    return True


def repair_static(run,shot_id,*,instructions,constraints,client=None):
    """One explicit known successor within the original or appended budget."""
    run=_guard(run);p=status(run)['plan'];row=next(r for r in p['shots'] if r['shot_id']==shot_id)
    original=run/'plans'/(shot_id+'.json');verify_plan(original,row)
    output=run/'plans'/(shot_id+'_r1.json')
    if output.exists():verify_plan(output,row);return output
    stage.files.freeze(run/'CORRECTIONS'/(shot_id+'_r1.json'),dict(instructions=instructions,constraints=constraints,
        original=dict(path=str(original),sha256=stage.files.file_sha(original))))
    payload,scope,shot,segment=_materials(row,stage.files.read(p['parent']['path']));schema=response_schema(shot['visible_cast'])
    folder=run/'calls'/shot_id/'attempt_01';folder.mkdir(parents=True,exist_ok=True)
    client=client or stage.legacy.PlanningClient(p['config'])
    old=stage.files.read(original)['shots'][0]['static_start_prompt']
    messages=[dict(role='system',content='Create one corrected static opening image prompt from the original model candidate and source. This is a bounded local correction, not new story or dynamic action. Follow the correction exactly. Return the complete replacement prompt in positive English, one frozen moment, same visible cast and source clothing visible within the requested crop. Do not output camera numbers or audio. JSON_SCHEMA:'+json.dumps(schema,ensure_ascii=False)),
        dict(role='user',content=json.dumps(dict(materials=payload,original_model_prompt=old,correction=instructions,acceptance_constraints=constraints),ensure_ascii=False))]
    if len(json.dumps(messages,ensure_ascii=False))>p['config']['max_input_chars']:raise StaticBlocked('static_successor_context_budget_exceeded')
    stage.files.freeze(folder/'REQUEST.json',dict(schema=VERSION,kind='explicit_known_successor',model=client.binding(),messages=messages,response_schema=schema))
    if (folder/'NATIVE.json').exists():raw=stage.files.read(folder/'NATIVE.json')
    else:
        if (folder/'CLAIM.json').exists():raise StaticBlocked('unknown_static_successor_not_replayed')
        claims=list((run/'calls').glob('*/attempt_*/CLAIM.json'));repairs=[f for f in claims if f.parent.name!='attempt_00']
        extension=_extension_budget(run,p);authorization=extension['allowed_successors'].get(shot_id)
        if len(claims)>=extension['max_calls'] or ((len(claims)>=29 or len(repairs)>=2) and not authorization):raise StaticBlocked('static_global_text_budget_exhausted')
        stage.files.freeze(folder/'CLAIM.json',dict(at=time.time(),kind='explicit_known_successor',extension_authorization=authorization))
        try:raw=client.call(messages,schema)
        except Exception as error:
            from .creative_workflow_roles import RoleResponseError
            native=getattr(error,'response_payload',None);metadata=getattr(error,'response_metadata',{})
            choices=native.get('choices',[]) if isinstance(native,dict) else []
            known=isinstance(error,RoleResponseError) and len(choices)==1 and choices[0].get('finish_reason') in ('stop','length') and choices[0]['finish_reason']==metadata.get('finish_reason')
            stage.files.freeze(folder/'ERROR.json',dict(type=type(error).__name__,message=str(error),completion_known=known,native=native,metadata=metadata))
            if not known:raise StaticBlocked('unknown_static_successor_not_replayed') from error
            raw=dict(text=choices[0].get('message',{}).get('content') or '',native=native,metadata=metadata,completion_known=True,rejected=True)
        stage.files.freeze(folder/'NATIVE.json',raw)
    if raw.get('completion_known') is not True:raise StaticBlocked('unknown_static_successor_completion')
    try:
        if raw.get('rejected') or raw.get('metadata',{}).get('finish_reason')=='length':raise StaticBlocked('known_static_successor_native_rejection')
        text=raw['text'].strip()
        if text.startswith('```json') and text.endswith('```'):text=text[7:-3].strip()
        result=json.loads(text);validate(result,schema);_check(result,shot,scope,constraints)
    except Exception as error:
        stage.files.freeze(folder/'VALIDATION_ERROR.json',dict(reason=str(error),candidate=raw.get('text')))
        raise StaticBlocked('known_static_successor_validation_failed') from error
    stage.files.freeze(folder/'RESULT.json',result)
    value=deepcopy(stage.files.read(original));value['shots'][0]['static_start_prompt']=result['static_start_prompt']
    # These annotations describe the old native response, not the new one.
    # Its immutable parent binding retains them; do not mislabel the successor.
    value['planning_provenance'].pop('parser_revalidation',None)
    value['planning_provenance'].pop('word_target_overrun',None)
    value['planning_provenance'].update(parent_static_plan=dict(path=str(original),sha256=stage.files.file_sha(original)),acceptance_constraints=constraints,
        bindings={key:dict(path=str(folder/filename),sha256=stage.files.file_sha(folder/filename)) for key,filename in [('request','REQUEST.json'),('native','NATIVE.json'),('result','RESULT.json')]})
    if value['shots'][0].get('camera_override'):value['planning_provenance']['camera_inherited_from_parent']=True
    words=len(re.findall(r"[A-Za-z]+(?:[-'][A-Za-z]+)*",result['static_start_prompt']))
    if constraints.get('word_target_only') and words>constraints.get('soft_target_words',150):
        note=dict(schema='static_word_target_revalidation/v1',word_target_overrun=True,actual_words=words,
            soft_target_words=constraints.get('soft_target_words',150),word_count_only_warning=True,max_characters=1800,
            native_text_unchanged=True,original_request_and_failure_preserved=True,classification='noncritical_expression_length')
        stage.files.freeze(folder/'WORD_TARGET_REVALIDATION.json',note)
        value['planning_provenance']['word_target_overrun']=note
    stage.files.freeze(output,value);verify_plan(output,row);return output


def selected_plans(run):
    run=_guard(run);p=status(run)['plan'];rows=[]
    for row in p['shots']:
        original=run/'plans'/(row['shot_id']+'.json');successor=run/'plans'/(row['shot_id']+'_r1.json')
        path=successor if successor.exists() else original;verify_plan(path,row);value=stage.files.read(path)
        rows.append(dict(shot_id=row['shot_id'],path=str(path.resolve()),sha256=stage.files.file_sha(path),
            packet_sha256=value['packet_sha256'],shot_sha256=value['shots'][0]['shot_sha256'],visible_cast=value['shots'][0]['visible_cast'],
            original_plan=dict(path=str(original.resolve()),sha256=stage.files.file_sha(original)),successor_selected=path==successor,
            original_retained_not_selected=path==successor))
    result=dict(schema='selected_static_plans/v13',source=p['source'],plans=rows,claimed_calls=status(run)['claimed_calls'],effective_max_calls=status(run)['effective_max_calls'],
        original_plan_sha256=stage.files.file_sha(run/'PLAN.json'),authorizations=[dict(path=str(f.resolve()),sha256=stage.files.file_sha(f)) for f in sorted((run/'AUTHORIZATIONS').glob('EXTENSION_*.json'))],
        raw_model_camera_preserved=True,media_approved=False)
    stage.files.write(run/'SELECTED_PLANS.json',result)
    ledger=[]
    for claim in sorted((run/'calls').glob('*/attempt_*/CLAIM.json')):
        native=claim.parent/'NATIVE.json';item=dict(shot_id=claim.parent.parent.name,attempt=claim.parent.name,claim_path=str(claim.resolve()),claim_sha256=stage.files.file_sha(claim),
            claim=stage.files.read(claim),native_path=str(native.resolve()),native_sha256=stage.files.file_sha(native) if native.exists() else None,
            completion_known=stage.files.read(native).get('completion_known') if native.exists() else False)
        ledger.append(item)
    stage.files.write(run/'CALL_LEDGER.json',dict(schema='static_call_ledger/v13',original_plan_sha256=stage.files.file_sha(run/'PLAN.json'),original_max_calls=29,
        effective_max_calls=status(run)['effective_max_calls'],authorizations=result['authorizations'],calls=ledger))
    return result
