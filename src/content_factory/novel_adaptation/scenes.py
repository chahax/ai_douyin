"""Scene writing consumes reviewed dependencies and advances explicit screen state.

These checks establish mechanical continuity, not truth of prose or performance.
"""
from copy import deepcopy
from . import contracts as c
from . import containers
from . import lifecycle


def reviewed_packet(entities,banks,visual,entity_ids,fact_ids,source,previous_state,reviews):
    c.validate_entities(entities,source)
    packet=c.build_scene_packet(entities,banks,visual,entity_ids,fact_ids,source,previous_state)
    errors=[]
    for record in packet['entities']+packet['facts']:
        review=reviews.get(record['id'],{})
        if (review.get('verdict')!='accepted' or review.get('source_sha256')!=c.digest(source)
            or review.get('record_sha256')!=c.digest(record if 'category' not in record else {k:v for k,v in record.items() if k!='category'})):
            errors.append(c.Issue('review','/'+record['id'],'unreviewed_or_changed_dependency',record['id']))
    if errors:raise c.ContractError(errors)
    packet['semantic_status']='selected_dependencies_reviewed'
    return packet


def plan_schema(entity_ids,fact_ids,character_ids=None,separate_opening=False):
    schema=c.obj(title=c.TEXT,world_fact_ids=c.refs(fact_ids),
        visual_design=c.array(c.obj(aspect=c.TEXT,description=c.TEXT,basis=c.choices(['adaptation_design']))),
        places=c.array(c.obj(id=c.TEXT,description=c.TEXT,basis=c.choices(['source','adaptation_design'])),1),
        initial_locations=c.obj(**{p:c.TEXT for p in (character_ids or entity_ids)}),
        props=c.array(c.obj(id=c.TEXT,kind=c.TEXT,owner=c.TEXT,description=c.TEXT)),
        scenes=c.array(c.obj(id=c.TEXT,place=c.TEXT,duration_seconds={'type':'integer','minimum':1,'maximum':180},
            objective=c.TEXT,fact_ids=c.refs(fact_ids)),2))
    if separate_opening:
        del schema['properties']['initial_locations'];schema['required'].remove('initial_locations')
        props=schema['properties']['props']['items']
        del props['properties']['owner'];props['required'].remove('owner')
        schema['properties']['places']['items']['properties']['basis']=c.choices(['adaptation_design'])
    schema['properties']['planned_props']=c.array(c.TEXT)
    prop_properties=schema['properties']['props']['items']['properties']
    prop_properties['stationary']={'type':'boolean'}
    prop_properties['visible_from']=c.array(c.TEXT,1)
    schema['properties']['container_actions']={'type':'boolean'}
    schema['properties']['action_contract_version']={'type':'integer','enum':[1,2]}
    schema['properties']['recipes']=c.array(c.obj(id=c.TEXT,action=c.TEXT,inputs=c.array(c.TEXT,1),outputs=c.array(c.TEXT,1),retained_inputs=c.array(c.TEXT),source_ids=c.array(c.TEXT,1)))
    schema['properties']['recipes']['items']['properties']['input_containers']={'type':'object','additionalProperties':c.TEXT,
        'description':'Optional input prop ID to required processing vessel ID. These inputs must be packed into this exact vessel before transform.'}
    schema['properties']['recipes']['items']['properties']['output_containers']={'type':'object','additionalProperties':c.TEXT,
        'description':'Optional output prop ID to existing serving/cooking vessel ID. On completion, output is inside that local vessel and shares its owner.'}
    return schema


def opening_schema(plan,entities):
    people=[r['id'] for r in entities['entities'] if r['kind']=='character']
    places=[p['id'] for p in plan['places']]
    return c.obj(locations=c.obj(**{who:c.choices(places) for who in people}),
        owners=c.obj(**{p['id']:c.choices(people+places) for p in plan['props']}))


def bind_opening(plan,opening,entities):
    errors=c.schema_issues(opening,opening_schema(plan,entities),'opening')
    if errors:raise c.ContractError(errors)
    result=deepcopy(plan);result['initial_locations']=deepcopy(opening['locations'])
    for prop in result['props']:prop['owner']=opening['owners'][prop['id']]
    initial_state(result,entities)
    return result


def compile_design(raw,packet):
    """Source constraints are copied by ID, never rewritten as visual prose."""
    if packet.get('semantic_status')!='selected_dependencies_reviewed':raise ValueError('unreviewed_design_input')
    facts={f['id']:f for f in packet['facts']};ids=raw['world_fact_ids']
    if len(ids)!=len(set(ids)) or not set(ids)<=facts.keys():raise ValueError('world_fact_scope')
    result=deepcopy(raw)
    result['world_framework']='\n'.join(facts[id]['statement'] for id in ids)
    result['source_constraints']=[deepcopy(facts[id]) for id in ids]
    result['world_framework_origin']='program_copy_of_reviewed_records'
    result['reviewed_packet_sha256']=c.digest(packet)
    return result


def scene_schema(plan,entities,fact_ids,source):
    people=[e['id'] for e in entities['entities'] if e['kind']=='character']
    places=[p['id'] for p in plan['places']];owners=people+places
    evidence={id:row for id,row in c.catalog(source).items()
              if not plan.get('target_chapters') or row['chapter'] in plan['target_chapters']}
    schema=c.obj(id=c.choices([s['id'] for s in plan['scenes']]),beats=c.array(c.obj(
        id=c.TEXT,start={'type':'number','minimum':0},end={'type':'number','exclusiveMinimum':0},
        present=c.refs(people,0),camera=c.TEXT,action=c.TEXT,emotion=c.TEXT,
        audio=c.array(c.obj(kind=c.choices(['dialogue','inner','narration']),speaker=c.choices(people+['NARRATOR']),
            text=c.TEXT,start={'type':'number','minimum':0},end={'type':'number','exclusiveMinimum':0})),
        moves=c.array(c.obj(person=c.choices(people),origin=c.choices(places),destination=c.choices(places),action=c.TEXT)),
        transfers=c.array(c.obj(prop=c.choices([p['id'] for p in plan['props']]),origin=c.choices(owners),destination=c.choices(owners),action=c.TEXT)),
        fact_ids=c.refs(fact_ids,0),source_ids=c.refs(evidence),
        adaptation_detail=c.TEXT),1))
    beat=schema['properties']['beats']['items']
    beat['required'].remove('present')
    beat['properties']['present']['description']='Optional cross-check only; the program derives presence from previous locations and moves.'
    for field in ('moves','transfers'):
        beat['required'].remove(field)
        beat['properties'][field]['default']=[]
        beat['properties'][field]['description']='Omitted means no transition, equivalent to an empty array.'
        beat['properties'][field]['items']['properties']['phase']={'type':'string','enum':['start','end','after_audio'],'default':'start',
            'description':'start before all audio; end after all audio; after_audio after the indexed utterance finishes. Omitted means start.'}
        item=beat['properties'][field]['items']
        item['properties']['after_audio_index']={'type':'integer','minimum':0}
        item['allOf']=[{'if':{'properties':{'phase':{'const':'after_audio'}},'required':['phase']},
            'then':{'required':['after_audio_index']},
            'else':{'not':{'required':['after_audio_index']}}}]
    use=c.obj(prop=c.choices([p['id'] for p in plan['props']]),holder=c.choices(owners))
    timing=beat['properties']['moves']['items']
    timing['properties']['carry_from_origin']=c.refs([p['id'] for p in plan['props']],1)
    for field in ('phase','after_audio_index'):use['properties'][field]=deepcopy(timing['properties'][field])
    use['allOf']=deepcopy(timing['allOf'])
    beat['properties']['prop_uses']=c.array(use)
    beat['properties']['prop_uses']['description']='Visible ownership claims for registered props at the stated moment, not speech mentions.'
    gesture=c.obj(actor=c.choices(people),verb=c.TEXT,target=c.choices(owners+[p['id'] for p in plan['props']]))
    gesture['properties']['instrument']=c.choices([p['id'] for p in plan['props']])
    gesture['properties']['posture_change']=c.obj(
        before=c.choices(['unknown','standing','seated','crouching','lying']),
        after=c.choices(['standing','seated','crouching','lying']),
        participants=c.refs(people,1))
    gesture['properties']['posture_change']['description']='Optional explicit body-state transition or first establishment from unknown; includes actor. All participants must be physically present and share the stated prior posture. Does not infer missing sitting/standing actions.'
    gesture['properties']['execution_place']=c.choices(places)
    gesture['properties']['execution_place']['description']='Explicit physical location of this interaction, independent of camera location. Actor and target must still be co-located; never grants remote reach.'
    for field in ('phase','after_audio_index'):gesture['properties'][field]=deepcopy(timing['properties'][field])
    gesture['allOf']=deepcopy(timing['allOf'])
    beat['properties']['gestures']=c.array(gesture)
    operations={
        'unpacks':c.obj(actor=c.choices(people),prop=c.choices([p['id'] for p in plan['props']]),container=c.choices([p['id'] for p in plan['props']]),destination=c.choices(owners)),
        'packs':c.obj(actor=c.choices(people),prop=c.choices([p['id'] for p in plan['props']]),container=c.choices([p['id'] for p in plan['props']])),
        'transforms':c.obj(actor=c.choices(people),recipe=c.choices([r['id'] for r in plan.get('recipes',[])]),destination=c.choices(owners))}
    if plan.get('action_contract_version') == 2:
        operations['transforms']['properties']['completion_action']=c.TEXT
    operations['transforms']['properties']['participants']=c.refs(people,1)
    operations['transforms']['properties']['participants']['description']='Optional explicit group performing this transformation or consumption together; includes actor and every participant must be physically present.'
    for field in ('input_containers','output_containers'):
        operations['transforms']['properties'][field]={'type':'object',
            'propertyNames':c.choices([p['id'] for p in plan['props']]),
            'additionalProperties':c.choices([p['id'] for p in plan['props']]),
            'description':'Explicit vessels at this event. Keys must be recipe inputs/outputs respectively; cannot override fixed recipe vessel constraints.'}
    for field,item in operations.items():
        for key in ('phase','after_audio_index'):item['properties'][key]=deepcopy(timing['properties'][key])
        item['allOf']=deepcopy(timing['allOf'])
        enabled=bool(plan.get('recipes')) if field=='transforms' else bool(plan.get('container_actions'))
        beat['properties'][field]=c.array(item) if enabled else {'type':'array','maxItems':0,'items':False}
    beat['properties']['action_order']=c.array(c.obj(field=c.choices(['moves','transfers','gestures','prop_uses','unpacks','packs','transforms']),index={'type':'integer','minimum':0}))
    beat['properties']['shot_subjects']=c.refs(owners+[p['id'] for p in plan['props']],0)
    beat['properties']['requires_information']=c.array(c.obj(person=c.choices(people),event_id=c.TEXT))
    beat['properties']['requires_information']['description']='Earlier audible events this beat explicitly relies on; omitted means none declared.'
    return schema


def normalize_scene(scene):
    result=deepcopy(scene)
    for beat in result['beats']:
        for field in ('moves','transfers','requires_information','prop_uses','gestures','shot_subjects','unpacks','packs','transforms'):beat.setdefault(field,[])
    return result


def initial_state(plan,entities):
    people={e['id'] for e in entities['entities'] if e['kind']=='character'}
    places={p['id'] for p in plan['places']}
    rows=plan['initial_locations']
    locations=deepcopy(rows) if isinstance(rows,dict) else {r['person']:r['place'] for r in rows}
    if len(locations)!=len(plan['initial_locations']) or set(locations)!=people:
        raise ValueError('initial_character_coverage')
    if not set(locations.values())<=places:raise ValueError('initial_unknown_place')
    props={r['id']:r['owner'] for r in plan['props']}
    if len(props)!=len(plan['props']) or not set(props.values())<=people|places:
        raise ValueError('initial_prop_identity_or_owner')
    if len(places)!=len(plan['places']) or len({s['id'] for s in plan['scenes']})!=len(plan['scenes']):
        raise ValueError('duplicate_place_or_scene')
    if any(s['place'] not in places for s in plan['scenes']):raise ValueError('scene_unknown_place')
    state={'locations':locations,'props':props}
    fixtures={}
    for row in plan['props']:
        if row.get('visible_from') and not row.get('stationary'):raise ValueError('visibility_requires_stationary_fixture')
        if row.get('stationary'):
            views=row.get('visible_from',[row['owner']])
            if row['owner'] not in places or not set(views)<=places or row['owner'] not in views:
                raise ValueError('invalid_fixture_visibility')
            fixtures[row['id']]=deepcopy(views)
    if fixtures:state['fixtures']=fixtures
    if plan.get('containers'):
        containers.validate(plan['containers'],props)
        state['containers']=deepcopy(plan['containers'])
    lifecycle.initialize(plan,state)
    return state


def advance(scene,scene_plan,plan,entities,fact_ids,source,previous,*,effects=None):
    errors=c.schema_issues(scene,scene_schema(plan,entities,fact_ids,source),'scene')
    if errors:raise c.ContractError(errors)
    scene=normalize_scene(scene)
    state=deepcopy(previous);place=scene_plan['place'];last=0;seen=set();audio_end=0
    containers.validate(state.get('containers',{}),state['props'])
    people=set(state['locations'])
    def fail(path,code,message):errors.append(c.Issue('continuity',path,code,message))
    if scene['id']!=scene_plan['id']:fail('/id','wrong_scene',scene['id'])
    for i,b in enumerate(scene['beats']):
        path=f'/beats/{i}'
        if b['id'] in seen:fail(path,'duplicate_beat',b['id'])
        seen.add(b['id'])
        if abs(b['start']-last)>0.01 or not 0<b['end']-b['start']<=15:
            fail(path,'beat_timing','contiguous beats, each at most 15 seconds')
        last=b['end']
        for a in b['audio']:
            if not b['start']<=a['start']<a['end']<=b['end']:
                fail(path,'audio_outside_beat',a['text'])
            if a['start']<audio_end:fail(path,'audio_overlap','single audible line at a time')
            audio_end=a['end']
            if a['end']<=a['start'] or len(a['text'])/(a['end']-a['start'])>6:fail(path,'speech_too_fast',a['text'])
        play_beat(state,b,place,scene['id'],path,fail,effects=effects)
        final_present={who for who,p in state['locations'].items() if p==place}
        if 'present' in b and final_present!=set(b['present']):fail(path,'presence_mismatch',f'expected {sorted(final_present)}')
    if abs(last-scene_plan['duration_seconds'])>0.01:fail('/beats','scene_duration','duration must match plan')
    if errors:raise c.ContractError(errors)
    return state


def audible_information(previous,scene_id,beat,present,index_offset=0):
    """Record access to actual utterances, never infer truth or agreement."""
    out=deepcopy(previous)
    for index,a in enumerate(beat['audio'],start=index_offset):
        recipients=present if a['kind']=='dialogue' else ({a['speaker']} if a['kind']=='inner' else set())
        event={'id':f'{scene_id}:{beat["id"]}:a{index}','speaker':a['speaker'],'kind':a['kind'],'text':a['text']}
        for who in sorted(recipients):
            history=out.setdefault(who,[])
            if any(old['id']==event['id'] and old!=event for old in history):raise ValueError('information_event_identity_changed')
            if not any(old['id']==event['id'] for old in history):history.append(deepcopy(event))
    return out


def production_scene(scene,spec,plan,entities,fact_ids,source,previous):
    """Compile a downstream view; canonical state is computed, never narrated.

    Native draft and repair rationale remain separate audit artifacts. This view
    is not semantic approval and cannot unlock media generation by itself.
    """
    ending=advance(scene,spec,plan,entities,fact_ids,source,previous)
    state=deepcopy(previous);beats=[]
    for raw in normalize_scene(scene)['beats']:
        trace=play_beat(state,raw,spec['place'],scene['id'],'',lambda *args: (_ for _ in ()).throw(ValueError(str(args))))
        audible_present=set().union(*(set(x['present']) for x in trace)) if trace else {p for p,loc in state['locations'].items() if loc==spec['place']}
        beat={k:deepcopy(raw[k]) for k in ('id','start','end','camera','action','emotion','audio','moves','transfers','prop_uses')}
        for field in ('action_order','gestures','shot_subjects','unpacks','packs','transforms'):
            if field in raw:beat[field]=deepcopy(raw[field])
        beat['present_during_audio']=sorted(audible_present)
        beat['audio_presence']=trace
        beat['present_after_moves']=sorted(p for p,loc in state['locations'].items() if loc==spec['place'])
        beat['prop_owners_after_transfers']=deepcopy(state['props'])
        beat['information_access_after_audio']=deepcopy(state['information'])
        beats.append(beat)
    return {'scene_id':scene['id'],'place':spec['place'],'source_scene_sha256':c.digest(scene),
        'semantic_status':'unapproved','beats':beats,'end_state':ending}


def advance_knowledge(previous,acquisitions,present,audio,known_fact_ids):
    """Optional knowledge ledger. Voice-over never informs another character.

    The content-to-fact match still requires source review; this enforces channel
    and witness boundaries rather than inferring meaning from arbitrary prose.
    """
    result={person:list(facts) for person,facts in previous.items()}
    errors=[]
    for i,change in enumerate(acquisitions):
        who=change['person'];fact=change['fact_id'];channel=change['channel']
        if who not in present or fact not in known_fact_ids:
            errors.append(c.Issue('knowledge',f'/{i}','unknown_or_absent_learner',who));continue
        if channel=='heard_dialogue':
            index=change['audio_index']
            if type(index) is not int or not 0<=index<len(audio) or audio[index]['kind']!='dialogue':
                errors.append(c.Issue('knowledge',f'/{i}','private_or_missing_audio',who));continue
        elif channel=='own_inner':
            index=change['audio_index']
            if type(index) is not int or not 0<=index<len(audio) or audio[index]['kind']!='inner' or audio[index]['speaker']!=who:
                errors.append(c.Issue('knowledge',f'/{i}','not_own_inner',who));continue
        elif channel=='observed':
            if not change.get('observation','').strip():
                errors.append(c.Issue('knowledge',f'/{i}','missing_observation',who));continue
        else:
            errors.append(c.Issue('knowledge',f'/{i}','unknown_channel',channel));continue
        if fact not in result.setdefault(who,[]):result[who].append(fact)
    if errors:raise c.ContractError(errors)
    return result


def model_scene_schema(plan,entities,fact_ids,source,previous=None,evidence_ids=None):
    """Model authors transitions; presence is exclusively program-derived."""
    schema=scene_schema(plan,entities,fact_ids,source)
    properties=schema['properties']['beats']['items']['properties']
    properties.pop('present')
    if evidence_ids is not None:properties['source_ids']=c.refs(sorted(set(evidence_ids)))
    schema['properties']['beats']['items']['required'].append('prop_uses')
    if previous is not None:
        variants=[]
        for person,history in previous.get('information',{}).items():
            ids=sorted({row['id'] for row in history})
            if ids:variants.append(c.obj(person=c.choices([person]),event_id=c.choices(ids)))
        properties['requires_information']=(c.array({'oneOf':variants}) if variants else
            {'type':'array','maxItems':0,'items':False})
        properties['requires_information']['description']='Only actual audible event IDs already in this person previous-state access history. Fact IDs are not audio IDs.'
    return schema


def derive_presence_input(scene):
    """Drop obsolete redundant cross-checks from a copy, preserving raw evidence."""
    result=deepcopy(scene)
    for beat in result['beats']:
        beat.pop('present',None)
    return result


def play_beat(state,beat,place,scene_id,path,fail,*,effects=None,sensory_windows=()):
    """Shared event interpreter for validation and the downstream production view."""
    people=set(state['locations'])
    def present():return {who for who,location in state['locations'].items() if location==place}
    # Explicit direct view/hearing windows only; no movement or transitive reach.
    for window in sensory_windows:
        end=window.get('through_audio_index')
        start=window.get('from_audio_index',-1)
        if (type(end) is not int or end < -1 or end >= len(beat['audio']) or
            type(start) is not int or not -1<=start<=end or
            window.get('place')==place or not isinstance(window.get('place'),str) or
            type(window.get('visible')) is not bool or type(window.get('audible')) is not bool):
            fail(path,'invalid_sensory_window',str(window));return []
    def reached(kind,index):
        destinations={w['place'] for w in sensory_windows if w[kind] and w.get('from_audio_index',-1)<=index<=w['through_audio_index']}
        return {who for who,location in state['locations'].items() if location in destinations}
    for row in beat['moves']+beat['transfers']+beat['prop_uses']+beat['gestures']+beat['unpacks']+beat['packs']+beat['transforms']:
        if row.get('phase')=='after_audio' and row['after_audio_index']>=len(beat['audio']):
            fail(path,'transition_audio_anchor_missing',str(row['after_audio_index']))
    def moves(rows):
        for move in rows:
            who=move['person'];origin=move['origin'];destination=move['destination']
            if state['locations'].get(who)!=origin or origin==destination or place not in (origin,destination):
                fail(path,'invalid_move',who)
            else:
                carried=move.get('carry_from_origin',[])
                if carried and destination!=place:
                    fail(path,'carry_requires_arrival',who);continue
                if any(p in state.get('fixtures',{}) or p in state.get('containers',{}) or
                       not lifecycle.exists(state,p) or state['props'].get(p)!=origin for p in carried):
                    fail(path,'arrival_prop_unavailable_at_origin',who);continue
                before=deepcopy(state)
                for prop in carried:
                    for child in {prop}|containers.descendants(state.get('containers',{}),prop):state['props'][child]=who
                state['locations'][who]=destination
                record_effects(before)
    def transfers(rows):
        for row in rows:
            before=deepcopy(state)
            origin,destination=row['origin'],row['destination']
            if row['prop'] in state.get('fixtures',{}):
                fail(path,'stationary_fixture_transfer',row['prop'])
            elif not lifecycle.exists(state,row['prop']):
                fail(path,'prop_not_present',row['prop'])
            elif row['prop'] in state.get('containers',{}):
                fail(path,'contained_prop_requires_removal_action',row['prop'])
            elif state['props'].get(row['prop'])!=origin or origin==destination:
                fail(path,'prop_transfer_origin',row['prop'])
            elif any((state['locations'].get(x)!=place if x in people else x!=place) for x in (origin,destination)):
                fail(path,'prop_transfer_remote',row['prop'])
            else:
                state['props'][row['prop']]=destination
                for child in containers.descendants(state.get('containers',{}),row['prop']):
                    state['props'][child]=destination
            record_effects(before)
    def record_effects(before):
        if effects is None:return
        for prop,origin in before['props'].items():
            destination=state['props'][prop]
            if origin!=destination and lifecycle.exists(before,prop) and lifecycle.exists(state,prop):
                effects.append({'scene_id':scene_id,'beat_id':beat['id'],'prop':prop,'origin':origin,'destination':destination})
    def operate(row,kind):
        before=deepcopy(state)
        try:lifecycle.apply(state,row,kind,place)
        except ValueError as exc:fail(path,str(exc),kind)
        record_effects(before)
    def visible():
        audience=present()
        return audience|{place}|{p for p,owner in state['props'].items() if (owner in audience or owner==place or place in state.get('fixtures',{}).get(p,[])) and lifecycle.exists(state,p)}
    seen_visible=set(visible())|reached('visible',-1)
    order=beat.get('action_order')
    if order is not None:
        expected={(field,i) for field in ('moves','transfers','gestures','prop_uses','unpacks','packs','transforms') for i in range(len(beat[field]))}
        actual=[(r['field'],r['index']) for r in order]
        if len(actual)!=len(set(actual)) or set(actual)!=expected:
            fail(path,'action_order_coverage','Every action must occur exactly once')
            return []
    elif beat['unpacks'] or beat['packs'] or beat['transforms']:
        fail(path,'lifecycle_requires_action_order','Explicit action ordering required');return []
    def check_gesture(gesture):
        execution_place=gesture.get('execution_place',place)
        actors={who for who,location in state['locations'].items() if location==execution_place}
        objects=actors|{execution_place}|{p for p,owner in state['props'].items()
            if (owner in actors or owner==execution_place or execution_place in state.get('fixtures',{}).get(p,[])) and lifecycle.exists(state,p)}
        if gesture['actor'] not in actors:fail(path,'gesture_actor_absent',gesture['actor']);return
        if gesture['target'] not in objects:fail(path,'gesture_target_not_visible',gesture['target']);return
        instrument=gesture.get('instrument')
        if instrument is not None:
            if instrument==gesture['target']:fail(path,'instrument_is_affected_target',instrument)
            if instrument not in objects:fail(path,'instrument_not_visible',instrument)
            if state['props'].get(instrument)!=gesture['actor']:fail(path,'instrument_not_held',instrument)
            if instrument in state.get('containers',{}):fail(path,'instrument_still_contained',instrument)
        posture=gesture.get('posture_change')
        if posture is not None:
            participants=posture['participants'];before=posture['before'];after=posture['after']
            if (not participants or len(participants)!=len(set(participants)) or gesture['actor'] not in participants
                    or not set(participants)<=actors or before==after
                    or before not in ('unknown','standing','seated','crouching','lying')
                    or after not in ('standing','seated','crouching','lying')):
                fail(path,'invalid_posture_transition',str(posture));return
            current=state.get('postures',{})
            if any(current.get(person,'unknown')!=before for person in participants):
                fail(path,'posture_before_mismatch',str(posture));return
            state.setdefault('postures',{}).update({person:after for person in participants})
    def check_use(use):
        if not lifecycle.exists(state,use['prop']):fail(path,'prop_not_present',use['prop'])
        if state['props'].get(use['prop'])!=use['holder']:
            fail(path,'visible_prop_owner_mismatch',use['prop'])
        if (use['holder'] in people and use['holder'] not in present()) or (use['holder'] not in people and use['holder']!=place):
            fail(path,'visible_prop_holder_absent',use['holder'])
    def apply(phase,index=None):
        selected=lambda rows:[r for r in rows if r.get('phase','start')==phase and (phase!='after_audio' or r['after_audio_index']==index)]
        if order is not None:
            for ref in order:
                row=beat[ref['field']][ref['index']]
                if not selected([row]):continue
                {'moves':lambda r:moves([r]),'transfers':lambda r:transfers([r]),
                 'gestures':check_gesture,'prop_uses':check_use,
                 'unpacks':lambda r:operate(r,'unpack'),'packs':lambda r:operate(r,'pack'),
                 'transforms':lambda r:operate(r,'transform')}[ref['field']](row)
                seen_visible.update(visible())
            return
        # At end, put down/hand over before leaving. At start and an audio boundary,
        # entrants arrive before receiving a prop.
        if phase=='end':
            transfers(selected(beat['transfers']));moves(selected(beat['moves']))
        else:
            moves(selected(beat['moves']));transfers(selected(beat['transfers']))
        seen_visible.update(visible())
        for gesture in selected(beat['gestures']):
            check_gesture(gesture)
        for use in selected(beat['prop_uses']):
            check_use(use)
    apply('start')
    for dependency in beat['requires_information']:
        history=state.get('information',{}).get(dependency['person'],[])
        if dependency['person'] not in present():fail(path,'information_user_absent',dependency['person'])
        if not any(e['id']==dependency['event_id'] for e in history):
            fail(path,'unheard_information_dependency',dependency['event_id'])
    trace=[]
    for index,audio in enumerate(beat['audio']):
        physical=present()
        audience=physical|reached('audible',index)
        seen_visible.update(reached('visible',index))
        if audio['kind']=='narration':
            if audio['speaker']!='NARRATOR':fail(path,'narrator_identity',audio['speaker'])
        elif audio['kind']=='inner':
            inner_allowed=physical|(seen_visible & people if sensory_windows else set())
            if audio['speaker'] not in inner_allowed:fail(path,'absent_speaker',audio['speaker'])
        elif audio['speaker'] not in audience:fail(path,'absent_speaker',audio['speaker'])
        item={'audio_index':index,'present':sorted(physical)}
        if sensory_windows:item['audible_people']=sorted(audience)
        trace.append(item)
        single={'id':beat['id'],'audio':[audio]}
        state['information']=audible_information(state.get('information',{}),scene_id,single,audience,index)
        apply('after_audio',index)
    apply('end')
    for subject in beat['shot_subjects']:
        if subject not in seen_visible:fail(path,'shot_subject_not_visible',subject)
    return trace
